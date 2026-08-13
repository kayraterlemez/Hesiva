import hashlib
import json
import os
import platform
import sqlite3
import stat
import struct
import sys
import tempfile
import zipfile
from collections.abc import Callable, Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from string import hexdigits
from typing import Any, BinaryIO

from hesiva.configuration import (
    CONFIGURATION_SIZE_LIMIT,
    ApplicationConfiguration,
    ConfigurationError,
    ConfigurationStore,
    InvalidConfigurationError,
)
from hesiva.application_data_lock import APPLICATION_DATA_LOCK_FILENAME
from hesiva.database.durability import sync_file, sync_parent_directory
from hesiva.database.semantic_validation import find_database_semantic_error
from hesiva.database.startup import DatabaseState, inspect_database
from hesiva.version import get_application_version

BACKUP_FORMAT_VERSION = 1
BACKUP_EXTENSION = ".zip"
DATABASE_ARCHIVE_NAME = "database.sqlite"
CONFIG_ARCHIVE_NAME = "config.json"
METADATA_ARCHIVE_NAME = "metadata.json"
RESTORE_JOURNAL_NAME = ".hesiva-restore-journal.json"
REQUIRED_ARCHIVE_NAMES = {
    DATABASE_ARCHIVE_NAME,
    CONFIG_ARCHIVE_NAME,
    METADATA_ARCHIVE_NAME,
}
COPY_BUFFER_SIZE = 1024 * 1024
MAX_BACKUP_DATABASE_BYTES = 16 * 1024 * 1024 * 1024
MAX_BACKUP_CONFIGURATION_BYTES = CONFIGURATION_SIZE_LIMIT
MAX_BACKUP_METADATA_BYTES = 64 * 1024
MAX_BACKUP_ARCHIVE_BYTES = (
    MAX_BACKUP_DATABASE_BYTES
    + MAX_BACKUP_CONFIGURATION_BYTES
    + MAX_BACKUP_METADATA_BYTES
    + 1024 * 1024
)
MAX_RESTORE_JOURNAL_BYTES = 64 * 1024
MAX_BACKUP_CENTRAL_DIRECTORY_BYTES = 1024 * 1024
ZIP_END_OF_CENTRAL_DIRECTORY_SIGNATURE = b"PK\x05\x06"
ZIP_END_OF_CENTRAL_DIRECTORY = struct.Struct("<4s4H2LH")
ZIP64_END_OF_CENTRAL_DIRECTORY_SIGNATURE = b"PK\x06\x06"
ZIP64_END_OF_CENTRAL_DIRECTORY = struct.Struct("<4sQ2H2L4Q")
ZIP64_END_OF_CENTRAL_DIRECTORY_LOCATOR = struct.Struct("<4sLQL")
ZIP64_END_OF_CENTRAL_DIRECTORY_LOCATOR_SIGNATURE = b"PK\x06\x07"
ZIP16_SENTINEL = (1 << 16) - 1
ZIP32_SENTINEL = (1 << 32) - 1
MAX_BACKUP_ZIP64_END_RECORD_BYTES = 4096
ZIP_MAX_COMMENT_BYTES = (1 << 16) - 1


class BackupError(Exception):
    """Base exception for backup and restore failures."""


class BackupPathError(BackupError):
    """Raised when a selected backup path is unsafe."""


class BackupValidationError(BackupError):
    """Raised when a backup archive is corrupt or incompatible."""


class RestoreError(BackupError):
    """Raised when restore fails but the working database remains usable."""


class RestoreRollbackError(BackupError):
    """Raised when restore and its safety rollback both fail."""

    def __init__(self, message: str, safety_backup_path: Path) -> None:
        super().__init__(message)
        self.safety_backup_path = safety_backup_path


class RestoreRecoveryError(BackupError):
    """Raised when an interrupted restore cannot be recovered deterministically."""


class RestoreRecoveryRequiredError(RestoreRecoveryError):
    """Raised when the durable recovery marker may still require startup recovery."""


@dataclass(frozen=True, slots=True)
class BackupMetadata:
    created_at: datetime
    application_version: str
    database_revision: str
    backup_format_version: int
    database_size: int
    database_sha256: str


@dataclass(frozen=True, slots=True)
class RestoreResult:
    restored_backup: BackupMetadata
    safety_backup_path: Path


class BackupService:
    """Create, verify, and restore portable Hesiva backup archives."""

    def __init__(
        self,
        live_database_path: Path,
        configuration_store: ConfigurationStore | None = None,
    ) -> None:
        resolved_path = live_database_path.expanduser()
        if not resolved_path.is_absolute():
            raise ValueError("The live database path must be absolute.")
        self.live_database_path = resolved_path
        self.configuration_store = configuration_store or ConfigurationStore(
            resolved_path.parent / CONFIG_ARCHIVE_NAME
        )

    def prepare_default_backup_directory(self) -> Path:
        """Create the documented local fallback directory with private permissions."""
        backup_directory = self.default_backup_directory
        if backup_directory.is_symlink() or (
            backup_directory.exists() and not backup_directory.is_dir()
        ):
            raise BackupPathError("The local safety-backup path must be a real directory.")
        directory_existed = backup_directory.exists()
        try:
            backup_directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        except OSError as error:
            raise BackupPathError(
                "The local safety-backup directory could not be prepared."
            ) from error
        if backup_directory.is_symlink() or not backup_directory.is_dir():
            raise BackupPathError("The local safety-backup path must be a real directory.")
        if os.name == "posix":
            backup_directory.chmod(0o700)
            if not directory_existed:
                sync_parent_directory(backup_directory)
        return backup_directory

    @property
    def default_backup_directory(self) -> Path:
        """Return the established local fallback without creating it."""
        return self.live_database_path.parent / "backups"

    def create_backup(
        self,
        destination_path: Path,
        *,
        created_at: datetime | None = None,
    ) -> BackupMetadata:
        """Create and exclusively publish a verified ZIP backup archive."""
        destination = self._validate_destination_path(destination_path)
        if created_at is not None and created_at.tzinfo is None:
            raise ValueError("An explicit backup timestamp must include a timezone.")
        snapshot_path: Path | None = None
        archive_path: Path | None = None
        try:
            snapshot_path = self._new_temporary_path(destination.parent, ".snapshot.sqlite")
            archive_path = self._new_temporary_path(destination.parent, ".backup.zip")
            configuration = self._load_live_configuration()
            self._online_backup(self.live_database_path, snapshot_path)
            self._validate_current_database(snapshot_path)
            sync_file(snapshot_path)

            metadata = self._build_metadata(snapshot_path, created_at=created_at)
            self._write_archive(archive_path, snapshot_path, configuration, metadata)
            sync_file(archive_path)
            verified_metadata = self.validate_backup(archive_path)

            self._publish_without_overwrite(archive_path, destination)
            sync_parent_directory(destination)
            return verified_metadata
        except BackupError:
            raise
        except Exception as error:
            raise BackupError("The Hesiva backup could not be created safely.") from error
        finally:
            primary_error = sys.exception()
            if snapshot_path is not None:
                self._remove_temporary_database(snapshot_path, primary_error=primary_error)
            if archive_path is not None:
                self._remove_temporary_file(archive_path, primary_error=primary_error)

    def validate_backup(self, backup_path: Path) -> BackupMetadata:
        """Validate one Hesiva backup without changing it or the live database."""
        source = self._validate_source_path(backup_path)
        with self._validated_archive_database(source) as (_, _, metadata):
            return metadata

    def restore_backup(
        self,
        backup_path: Path,
        *,
        close_live_database: Callable[[], None],
        reopen_live_database: Callable[[], None],
    ) -> RestoreResult:
        """Replace the live database and roll back automatically if reopening fails."""
        source = self._validate_source_path(backup_path)
        replacement_path = self._new_temporary_path(
            self.live_database_path.parent,
            ".restore.sqlite",
        )
        replacement_config_path: Path | None = None
        try:
            with self._validated_archive_database(source) as (
                candidate_database,
                candidate_configuration,
                metadata,
            ):
                self._online_backup(candidate_database, replacement_path)
                self._validate_current_database(replacement_path)
                sync_file(replacement_path)
                replacement_config_path = self.configuration_store.stage(
                    candidate_configuration,
                    suffix=".restore-config.json",
                )

            safety_backup_path = self._create_safety_backup()
            self._begin_restore_recovery(safety_backup_path)
            return self._publish_restore(
                replacement_path,
                replacement_config_path,
                metadata,
                safety_backup_path,
                close_live_database,
                reopen_live_database,
            )
        finally:
            primary_error = sys.exception()
            if replacement_config_path is not None:
                self._remove_temporary_file(
                    replacement_config_path,
                    primary_error=primary_error,
                )
            self._remove_temporary_database(
                replacement_path,
                primary_error=primary_error,
            )

    def _publish_restore(
        self,
        replacement_path: Path,
        replacement_config_path: Path,
        metadata: BackupMetadata,
        safety_backup_path: Path,
        close_live_database: Callable[[], None],
        reopen_live_database: Callable[[], None],
    ) -> RestoreResult:
        database_closed = False
        database_replaced = False
        try:
            close_live_database()
            database_closed = True
            self._ensure_no_live_sidecars()
            os.replace(replacement_path, self.live_database_path)
            database_replaced = True
            os.replace(replacement_config_path, self.configuration_store.path)
            self._set_private_permissions(self.live_database_path)
            self._set_private_permissions(self.configuration_store.path)
            sync_parent_directory(self.configuration_store.path)
            reopen_live_database()
            database_closed = False
            self._validate_current_database(self.live_database_path)
            self.configuration_store.load()
        except Exception as restore_error:
            if not database_replaced:
                if database_closed:
                    self._reopen_original_or_raise(reopen_live_database)
                self._clear_restore_recovery()
                raise RestoreError("The restore stopped before replacing the live database.") from (
                    restore_error
                )
            self._rollback_after_failed_restore(
                safety_backup_path,
                close_live_database,
                reopen_live_database,
            )
            self._clear_restore_recovery()
            raise RestoreError(
                "The restored application snapshot could not be reopened; the previous database "
                "was restored together with its configuration."
            ) from restore_error

        # The restored pair is already published, durable, reopened, and validated.
        # If clearing the marker is uncertain, fail closed with this consistent pair;
        # starting another two-file rollback after unlinking the marker would create
        # an unjournaled crash window between the rollback database and config replaces.
        self._clear_restore_recovery()
        return RestoreResult(metadata, safety_backup_path)

    def recover_interrupted_restore(self) -> bool:
        """Recover the pre-restore DB/config pair recorded by a durable journal."""
        journal_path = self.restore_journal_path
        try:
            journal_path.lstat()
        except FileNotFoundError:
            return False
        except OSError as error:
            raise RestoreRecoveryError(
                "The restore recovery marker could not be inspected safely."
            ) from error
        safety_backup_path = self._read_restore_recovery_journal()
        replacement_path = self._new_temporary_path(
            self.live_database_path.parent,
            ".startup-rollback.sqlite",
        )
        replacement_config_path: Path | None = None
        try:
            with self._validated_archive_database(safety_backup_path) as (
                safety_database,
                safety_configuration,
                _,
            ):
                self._online_backup(safety_database, replacement_path)
            self._validate_current_database(replacement_path)
            sync_file(replacement_path)
            replacement_config_path = self.configuration_store.stage(
                safety_configuration,
                suffix=".startup-rollback-config.json",
            )
            self._remove_live_sidecars_for_rollback()
            os.replace(replacement_path, self.live_database_path)
            os.replace(replacement_config_path, self.configuration_store.path)
            self._set_private_permissions(self.live_database_path)
            self._set_private_permissions(self.configuration_store.path)
            sync_parent_directory(self.configuration_store.path)
            self._validate_current_database(self.live_database_path)
            self.configuration_store.load()
            self._clear_restore_recovery()
            return True
        except RestoreRecoveryError:
            raise
        except Exception as error:
            raise RestoreRecoveryError(
                "Hesiva could not recover the database/configuration pair from an interrupted "
                "restore. The safety backup and recovery marker were preserved."
            ) from error
        finally:
            primary_error = sys.exception()
            self._remove_temporary_database(replacement_path, primary_error=primary_error)
            if replacement_config_path is not None:
                self._remove_temporary_file(
                    replacement_config_path,
                    primary_error=primary_error,
                )

    @property
    def restore_journal_path(self) -> Path:
        return self.live_database_path.parent / RESTORE_JOURNAL_NAME

    def _rollback_after_failed_restore(
        self,
        safety_backup_path: Path,
        close_live_database: Callable[[], None],
        reopen_live_database: Callable[[], None],
    ) -> None:
        rollback_path = self._new_temporary_path(
            self.live_database_path.parent,
            ".rollback.sqlite",
        )
        rollback_config_path: Path | None = None
        try:
            with self._validated_archive_database(safety_backup_path) as (
                safety_database,
                safety_configuration,
                _,
            ):
                self._online_backup(safety_database, rollback_path)
            self._validate_current_database(rollback_path)
            sync_file(rollback_path)
            rollback_config_path = self.configuration_store.stage(
                safety_configuration,
                suffix=".rollback-config.json",
            )
            close_live_database()
            self._remove_live_sidecars_for_rollback()
            os.replace(rollback_path, self.live_database_path)
            os.replace(rollback_config_path, self.configuration_store.path)
            self._set_private_permissions(self.live_database_path)
            self._set_private_permissions(self.configuration_store.path)
            sync_parent_directory(self.configuration_store.path)
            reopen_live_database()
            self._validate_current_database(self.live_database_path)
            self.configuration_store.load()
        except Exception as rollback_error:
            raise RestoreRollbackError(
                "Restore and automatic rollback failed. The safety backup was preserved.",
                safety_backup_path,
            ) from rollback_error
        finally:
            primary_error = sys.exception()
            self._remove_temporary_database(rollback_path, primary_error=primary_error)
            if rollback_config_path is not None:
                self._remove_temporary_file(
                    rollback_config_path,
                    primary_error=primary_error,
                )

    def _reopen_original_or_raise(
        self,
        reopen_live_database: Callable[[], None],
    ) -> None:
        try:
            reopen_live_database()
        except Exception as reopen_error:
            raise RestoreError(
                "Restore stopped before replacement, but the live database could not be reopened."
            ) from reopen_error

    def _create_safety_backup(self) -> Path:
        backup_directory = self.prepare_default_backup_directory()
        timestamp = datetime.now(UTC).strftime("%Y-%m-%d_%H-%M-%S")
        base_path = backup_directory / f"hesiva_safety_before_restore_{timestamp}.zip"
        safety_path = self._next_available_path(base_path)
        self.create_backup(safety_path)
        return safety_path

    def _begin_restore_recovery(self, safety_backup_path: Path) -> None:
        journal_path = self.restore_journal_path
        if self._restore_journal_exists_or_is_uncertain():
            raise RestoreRecoveryRequiredError(
                "An earlier restore recovery marker must be resolved before restoring again."
            )
        resolved_safety_path = self._validate_safety_backup_path(safety_backup_path)
        payload = {
            "format_version": 1,
            "safety_backup_path": str(resolved_safety_path),
            "safety_backup_sha256": self._sha256(resolved_safety_path),
        }
        staged_path = self._new_temporary_path(
            journal_path.parent,
            ".restore-journal.json",
        )
        marker_published = False
        try:
            with staged_path.open("wb") as file_handle:
                file_handle.write(
                    (json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
                )
                file_handle.flush()
                os.fsync(file_handle.fileno())
            if self._restore_journal_exists_or_is_uncertain():
                raise RestoreRecoveryRequiredError(
                    "An earlier restore recovery marker appeared before publication."
                )
            os.replace(staged_path, journal_path)
            marker_published = True
            self._set_private_permissions(journal_path)
            sync_parent_directory(journal_path)
        except RestoreRecoveryRequiredError:
            raise
        except Exception as error:
            if marker_published:
                try:
                    self._clear_restore_recovery()
                except RestoreRecoveryError as cleanup_error:
                    raise RestoreRecoveryRequiredError(
                        "The restore recovery marker could not be cleared durably. "
                        "Hesiva must restart before any more data is changed."
                    ) from cleanup_error
            elif self._restore_journal_exists_or_is_uncertain():
                raise RestoreRecoveryRequiredError(
                    "A restore recovery marker may require startup recovery. "
                    "Hesiva must restart before any more data is changed."
                ) from error
            raise RestoreRecoveryError(
                "The restore recovery marker could not be published safely."
            ) from error
        finally:
            self._remove_temporary_file(
                staged_path,
                primary_error=sys.exception(),
            )

    def _read_restore_recovery_journal(self) -> Path:
        journal_path = self.restore_journal_path
        if journal_path.is_symlink() or not journal_path.is_file():
            raise RestoreRecoveryError("The restore recovery marker is not a regular file.")
        try:
            with journal_path.open("rb") as file_handle:
                payload_bytes = file_handle.read(MAX_RESTORE_JOURNAL_BYTES + 1)
            if len(payload_bytes) > MAX_RESTORE_JOURNAL_BYTES:
                raise RestoreRecoveryError("The restore recovery marker is too large.")
            payload = json.loads(payload_bytes.decode("utf-8"))
        except RestoreRecoveryError:
            raise
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise RestoreRecoveryError("The restore recovery marker is invalid.") from error
        if not isinstance(payload, dict) or set(payload) != {
            "format_version",
            "safety_backup_path",
            "safety_backup_sha256",
        }:
            raise RestoreRecoveryError("The restore recovery marker is invalid.")
        if payload["format_version"] != 1 or type(payload["format_version"]) is not int:
            raise RestoreRecoveryError("The restore recovery marker version is unsupported.")
        raw_path = payload["safety_backup_path"]
        expected_digest = payload["safety_backup_sha256"]
        if not isinstance(raw_path, str) or not isinstance(expected_digest, str):
            raise RestoreRecoveryError("The restore recovery marker is invalid.")
        safety_backup_path = self._validate_safety_backup_path(Path(raw_path))
        if len(expected_digest) != 64 or any(
            character not in hexdigits for character in expected_digest
        ):
            raise RestoreRecoveryError("The restore recovery marker checksum is invalid.")
        if self._sha256(safety_backup_path) != expected_digest:
            raise RestoreRecoveryError("The restore safety backup checksum has changed.")
        return safety_backup_path

    def _validate_safety_backup_path(self, safety_backup_path: Path) -> Path:
        expanded_path = safety_backup_path.expanduser()
        if not expanded_path.is_absolute() or expanded_path.is_symlink():
            raise RestoreRecoveryError("The restore recovery safety-backup path is invalid.")
        resolved_path = expanded_path.resolve(strict=False)
        backup_directory = self.default_backup_directory.resolve(strict=False)
        if (
            resolved_path.parent != backup_directory
            or not resolved_path.name.startswith("hesiva_safety_before_restore_")
            or resolved_path.suffix.lower() != BACKUP_EXTENSION
            or not resolved_path.is_file()
        ):
            raise RestoreRecoveryError("The restore recovery safety-backup path is invalid.")
        return resolved_path

    def _clear_restore_recovery(self) -> None:
        journal_path = self.restore_journal_path
        try:
            journal_path.unlink(missing_ok=True)
            sync_parent_directory(journal_path)
        except OSError as error:
            raise RestoreRecoveryRequiredError(
                "The completed restore recovery marker could not be removed durably."
            ) from error

    def _restore_journal_exists_or_is_uncertain(self) -> bool:
        try:
            self.restore_journal_path.lstat()
        except FileNotFoundError:
            return False
        except OSError as error:
            raise RestoreRecoveryRequiredError(
                "The restore recovery marker could not be inspected safely."
            ) from error
        return True

    def _validate_destination_path(self, destination_path: Path) -> Path:
        destination = destination_path.expanduser()
        if not destination.is_absolute():
            raise BackupPathError("The backup destination must be an absolute path.")
        if self._paths_refer_to_same_file(destination, self.live_database_path):
            raise BackupPathError("The live database cannot be used as a backup destination.")
        reserved_paths = (
            self.configuration_store.path,
            self.restore_journal_path,
            self.live_database_path.parent / APPLICATION_DATA_LOCK_FILENAME,
            *self._live_sidecars(),
        )
        if any(self._paths_refer_to_same_file(destination, path) for path in reserved_paths):
            raise BackupPathError(
                "Hesiva application-data files cannot be used as a backup destination."
            )
        if destination.is_symlink():
            raise BackupPathError("Symbolic-link backup destinations are not supported.")
        if destination.exists():
            raise BackupPathError("An existing backup file will not be overwritten.")
        if not destination.parent.is_dir():
            raise BackupPathError("The backup destination directory does not exist.")
        return destination

    def _validate_source_path(self, backup_path: Path) -> Path:
        source = backup_path.expanduser()
        if not source.is_absolute():
            raise BackupPathError("The backup source must be an absolute path.")
        if self._paths_refer_to_same_file(source, self.live_database_path):
            raise BackupPathError("The live database cannot be used as a restore source.")
        if not source.is_file():
            raise BackupValidationError("The selected backup file does not exist.")
        return source

    @contextmanager
    def _validated_archive_database(
        self,
        archive_path: Path,
    ) -> Iterator[tuple[Path, ApplicationConfiguration, BackupMetadata]]:
        temporary_directory: tempfile.TemporaryDirectory[str] | None = None
        try:
            try:
                with self._open_archive_source(archive_path) as archive_file:
                    initial_stat = os.fstat(archive_file.fileno())
                    if not stat.S_ISREG(initial_stat.st_mode):
                        raise BackupValidationError(
                            "The selected backup source is not a regular file."
                        )
                    if initial_stat.st_size > MAX_BACKUP_ARCHIVE_BYTES:
                        raise BackupValidationError("The selected backup archive is too large.")
                    self._validate_zip_directory_envelope(
                        archive_file,
                        archive_size=initial_stat.st_size,
                    )
                    temporary_directory = tempfile.TemporaryDirectory(
                        prefix="hesiva-backup-validation-",
                    )
                    database_path = Path(temporary_directory.name) / DATABASE_ARCHIVE_NAME
                    with zipfile.ZipFile(archive_file, "r") as archive:
                        members = archive.infolist()
                        names = [member.filename for member in members]
                        if len(names) != len(set(names)) or set(names) != REQUIRED_ARCHIVE_NAMES:
                            raise BackupValidationError(
                                "The selected archive does not have the required Hesiva contents."
                            )
                        if any(
                            member.is_dir()
                            or member.compress_type != zipfile.ZIP_STORED
                            or member.flag_bits & 0x1
                            for member in members
                        ):
                            raise BackupValidationError(
                                "The selected archive uses unsupported member encoding."
                            )
                        member_by_name = {member.filename: member for member in members}
                        database_member = member_by_name[DATABASE_ARCHIVE_NAME]
                        config_member = member_by_name[CONFIG_ARCHIVE_NAME]
                        metadata_member = member_by_name[METADATA_ARCHIVE_NAME]
                        if (
                            database_member.file_size <= 0
                            or database_member.file_size > MAX_BACKUP_DATABASE_BYTES
                            or config_member.file_size > MAX_BACKUP_CONFIGURATION_BYTES
                            or metadata_member.file_size > MAX_BACKUP_METADATA_BYTES
                        ):
                            raise BackupValidationError(
                                "The selected backup contains an oversized member."
                            )
                        metadata_payload = self._read_json_member(
                            archive,
                            metadata_member,
                            MAX_BACKUP_METADATA_BYTES,
                        )
                        metadata = self._parse_metadata(metadata_payload)
                        if metadata.database_size != database_member.file_size:
                            raise BackupValidationError(
                                "The backup database size does not match its metadata."
                            )
                        config_bytes = self._read_member_bytes(
                            archive,
                            config_member,
                            MAX_BACKUP_CONFIGURATION_BYTES,
                        )
                        try:
                            configuration = ConfigurationStore.parse_bytes(config_bytes)
                        except InvalidConfigurationError as error:
                            raise BackupValidationError(
                                "The backup configuration is invalid."
                            ) from error
                        self._copy_archive_member(
                            archive,
                            database_member,
                            database_path,
                            MAX_BACKUP_DATABASE_BYTES,
                        )
                    final_stat = os.fstat(archive_file.fileno())
                    if self._archive_identity(final_stat) != self._archive_identity(initial_stat):
                        raise BackupValidationError(
                            "The selected backup archive changed while it was being read."
                        )

                self._validate_metadata_database(database_path, metadata)
            except BackupValidationError:
                raise
            except (
                OSError,
                ValueError,
                UnicodeDecodeError,
                RecursionError,
                zipfile.BadZipFile,
                zipfile.LargeZipFile,
                json.JSONDecodeError,
            ) as error:
                raise BackupValidationError(
                    "The selected file is not a valid Hesiva backup."
                ) from error
            yield database_path, configuration, metadata
        finally:
            if temporary_directory is not None:
                self._cleanup_temporary_directory(
                    temporary_directory,
                    primary_error=sys.exception(),
                )

    @staticmethod
    def _open_archive_source(archive_path: Path) -> BinaryIO:
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NONBLOCK", 0)
        file_descriptor = os.open(archive_path, flags)
        try:
            return os.fdopen(file_descriptor, "rb")
        except BaseException as error:
            try:
                os.close(file_descriptor)
            except OSError as cleanup_error:
                error.add_note(
                    "The backup source descriptor could not be closed cleanly: "
                    f"{type(cleanup_error).__name__}."
                )
            raise

    @staticmethod
    def _archive_identity(file_stat: os.stat_result) -> tuple[int, int, int, int, int]:
        return (
            file_stat.st_dev,
            file_stat.st_ino,
            file_stat.st_size,
            file_stat.st_mtime_ns,
            file_stat.st_ctime_ns,
        )

    @staticmethod
    def _validate_zip_directory_envelope(
        archive_file: BinaryIO,
        *,
        archive_size: int,
    ) -> None:
        """Bound ZIP directory parsing before ``zipfile`` materializes every entry."""
        minimum_record_size = ZIP_END_OF_CENTRAL_DIRECTORY.size
        if archive_size < minimum_record_size:
            raise BackupValidationError("The selected backup archive is truncated.")
        tail_size = min(
            archive_size,
            minimum_record_size + ZIP_MAX_COMMENT_BYTES,
        )
        archive_file.seek(-tail_size, os.SEEK_END)
        tail = archive_file.read(tail_size)

        record_offset = len(tail)
        record: tuple[bytes, int, int, int, int, int, int, int] | None = None
        while True:
            record_offset = tail.rfind(
                ZIP_END_OF_CENTRAL_DIRECTORY_SIGNATURE,
                0,
                record_offset,
            )
            if record_offset < 0:
                break
            if len(tail) - record_offset >= minimum_record_size:
                candidate = ZIP_END_OF_CENTRAL_DIRECTORY.unpack_from(tail, record_offset)
                comment_size = candidate[-1]
                if record_offset + minimum_record_size + comment_size == len(tail):
                    record = candidate
                    break
            if record_offset == 0:
                break

        if record is None:
            raise BackupValidationError(
                "The selected backup archive has no valid directory terminator."
            )
        (
            _signature,
            disk_number,
            directory_disk_number,
            entries_on_disk,
            total_entries,
            directory_size,
            directory_offset,
            _comment_size,
        ) = record
        if disk_number != 0 or directory_disk_number != 0:
            raise BackupValidationError("Multi-volume backup archives are not supported.")
        absolute_record_offset = archive_size - tail_size + record_offset
        effective_directory_end = absolute_record_offset
        if (
            entries_on_disk == ZIP16_SENTINEL
            or total_entries == ZIP16_SENTINEL
            or directory_size == ZIP32_SENTINEL
            or directory_offset == ZIP32_SENTINEL
        ):
            (
                zip64_entries_on_disk,
                zip64_total_entries,
                zip64_directory_size,
                zip64_directory_offset,
                zip64_record_offset,
            ) = BackupService._read_zip64_directory_record(
                archive_file,
                locator_offset=absolute_record_offset - ZIP64_END_OF_CENTRAL_DIRECTORY_LOCATOR.size,
            )
            for legacy_value, sentinel, effective_value in (
                (entries_on_disk, ZIP16_SENTINEL, zip64_entries_on_disk),
                (total_entries, ZIP16_SENTINEL, zip64_total_entries),
                (directory_size, ZIP32_SENTINEL, zip64_directory_size),
                (directory_offset, ZIP32_SENTINEL, zip64_directory_offset),
            ):
                if legacy_value != sentinel and legacy_value != effective_value:
                    raise BackupValidationError("The ZIP64 directory metadata is inconsistent.")
            entries_on_disk = zip64_entries_on_disk
            total_entries = zip64_total_entries
            directory_size = zip64_directory_size
            directory_offset = zip64_directory_offset
            effective_directory_end = zip64_record_offset
        if entries_on_disk != total_entries:
            raise BackupValidationError("Multi-volume backup archives are not supported.")
        if total_entries != len(REQUIRED_ARCHIVE_NAMES):
            raise BackupValidationError(
                "The selected archive does not have the required Hesiva contents."
            )
        if directory_size > MAX_BACKUP_CENTRAL_DIRECTORY_BYTES:
            raise BackupValidationError("The backup archive directory is too large.")
        if directory_offset + directory_size != effective_directory_end:
            raise BackupValidationError("The backup archive directory layout is invalid.")

    @staticmethod
    def _read_zip64_directory_record(
        archive_file: BinaryIO,
        *,
        locator_offset: int,
    ) -> tuple[int, int, int, int, int]:
        if locator_offset < 0:
            raise BackupValidationError("The ZIP64 directory locator is missing.")
        archive_file.seek(locator_offset)
        locator_bytes = archive_file.read(ZIP64_END_OF_CENTRAL_DIRECTORY_LOCATOR.size)
        if len(locator_bytes) != ZIP64_END_OF_CENTRAL_DIRECTORY_LOCATOR.size:
            raise BackupValidationError("The ZIP64 directory locator is truncated.")
        (
            locator_signature,
            directory_disk,
            zip64_record_offset,
            disk_count,
        ) = ZIP64_END_OF_CENTRAL_DIRECTORY_LOCATOR.unpack(locator_bytes)
        if (
            locator_signature != ZIP64_END_OF_CENTRAL_DIRECTORY_LOCATOR_SIGNATURE
            or directory_disk != 0
            or disk_count != 1
            or zip64_record_offset >= locator_offset
        ):
            raise BackupValidationError("The ZIP64 directory locator is invalid.")
        archive_file.seek(zip64_record_offset)
        record_bytes = archive_file.read(ZIP64_END_OF_CENTRAL_DIRECTORY.size)
        if len(record_bytes) != ZIP64_END_OF_CENTRAL_DIRECTORY.size:
            raise BackupValidationError("The ZIP64 directory record is truncated.")
        (
            record_signature,
            record_payload_size,
            _creator_version,
            _required_version,
            disk_number,
            directory_disk_number,
            entries_on_disk,
            total_entries,
            directory_size,
            directory_offset,
        ) = ZIP64_END_OF_CENTRAL_DIRECTORY.unpack(record_bytes)
        if (
            record_signature != ZIP64_END_OF_CENTRAL_DIRECTORY_SIGNATURE
            or record_payload_size < ZIP64_END_OF_CENTRAL_DIRECTORY.size - 12
            or record_payload_size > MAX_BACKUP_ZIP64_END_RECORD_BYTES
            or zip64_record_offset + 12 + record_payload_size != locator_offset
        ):
            raise BackupValidationError("The ZIP64 directory record is invalid.")
        if disk_number != 0 or directory_disk_number != 0:
            raise BackupValidationError("Multi-volume backup archives are not supported.")
        return (
            entries_on_disk,
            total_entries,
            directory_size,
            directory_offset,
            zip64_record_offset,
        )

    def _validate_metadata_database(
        self,
        database_path: Path,
        metadata: BackupMetadata,
    ) -> None:
        self._validate_current_database(database_path)
        status = inspect_database(database_path)
        if status.current_revision != metadata.database_revision:
            raise BackupValidationError("The backup database revision does not match its metadata.")
        if database_path.stat().st_size != metadata.database_size:
            raise BackupValidationError("The backup database size does not match its metadata.")
        if self._sha256(database_path) != metadata.database_sha256:
            raise BackupValidationError("The backup database checksum does not match its metadata.")

    def _validate_current_database(self, database_path: Path) -> None:
        try:
            with closing(self._connect_read_only(database_path)) as connection:
                integrity_rows = connection.execute("PRAGMA integrity_check").fetchall()
                foreign_key_error = connection.execute("PRAGMA foreign_key_check").fetchone()
                unexpected_object = connection.execute(
                    "SELECT type, name FROM sqlite_schema WHERE type IN ('trigger', 'view') LIMIT 1"
                ).fetchone()
        except (OSError, sqlite3.DatabaseError) as error:
            raise BackupValidationError(
                "The backup database could not be opened safely."
            ) from error
        if integrity_rows != [("ok",)]:
            raise BackupValidationError("The backup database failed SQLite integrity verification.")
        if foreign_key_error is not None:
            raise BackupValidationError("The backup database has invalid relationships.")
        if unexpected_object is not None:
            raise BackupValidationError("The backup database contains unsupported schema objects.")
        status = inspect_database(database_path)
        if status.state is DatabaseState.OUTDATED:
            raise BackupValidationError(
                "The backup database version is older than this Hesiva version."
            )
        if status.state is not DatabaseState.CURRENT:
            raise BackupValidationError("The backup is not a current valid Hesiva database.")
        try:
            with closing(self._connect_read_only(database_path)) as connection:
                semantic_error = self._find_semantic_database_error(connection)
        except (OSError, sqlite3.DatabaseError) as error:
            raise BackupValidationError(
                "The backup database contents could not be validated safely."
            ) from error
        if semantic_error is not None:
            raise BackupValidationError(
                f"The backup database contains invalid {semantic_error} data."
            )

    def _online_backup(self, source_path: Path, destination_path: Path) -> None:
        try:
            with closing(self._connect_read_only(source_path)) as source_connection:
                with closing(sqlite3.connect(destination_path)) as destination_connection:
                    source_connection.backup(destination_connection)
        except sqlite3.DatabaseError as error:
            raise BackupError("SQLite could not create a consistent database snapshot.") from error
        self._set_private_permissions(destination_path)

    def _write_archive(
        self,
        archive_path: Path,
        snapshot_path: Path,
        configuration: ApplicationConfiguration,
        metadata: BackupMetadata,
    ) -> None:
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_STORED) as archive:
            archive.write(snapshot_path, DATABASE_ARCHIVE_NAME)
            archive.writestr(
                CONFIG_ARCHIVE_NAME,
                configuration.to_bytes(),
            )
            archive.writestr(
                METADATA_ARCHIVE_NAME,
                json.dumps(self._metadata_payload(metadata), sort_keys=True),
            )

    def _load_live_configuration(self) -> ApplicationConfiguration:
        try:
            return self.configuration_store.load()
        except ConfigurationError as error:
            raise BackupValidationError(
                "The live authentication configuration is missing or invalid."
            ) from error

    def _build_metadata(
        self,
        database_path: Path,
        *,
        created_at: datetime | None = None,
    ) -> BackupMetadata:
        status = inspect_database(database_path)
        if status.current_revision is None:
            raise BackupValidationError("The database revision could not be determined.")
        return BackupMetadata(
            created_at=(created_at or datetime.now(UTC)).astimezone(UTC),
            application_version=self._application_version(),
            database_revision=status.current_revision,
            backup_format_version=BACKUP_FORMAT_VERSION,
            database_size=database_path.stat().st_size,
            database_sha256=self._sha256(database_path),
        )

    def _parse_metadata(self, payload: Any) -> BackupMetadata:
        if not isinstance(payload, dict):
            raise BackupValidationError("The backup metadata is invalid.")
        if payload.get("application") != "Hesiva":
            raise BackupValidationError("The archive is not identified as a Hesiva backup.")
        try:
            created_at = datetime.fromisoformat(payload["created_at"])
            metadata = BackupMetadata(
                created_at=created_at,
                application_version=payload["application_version"],
                database_revision=payload["database_revision"],
                backup_format_version=payload["backup_format_version"],
                database_size=payload["database_size"],
                database_sha256=payload["database_sha256"],
            )
        except (KeyError, TypeError, ValueError) as error:
            raise BackupValidationError("The backup metadata is invalid.") from error
        if created_at.tzinfo is None:
            raise BackupValidationError("The backup timestamp has no timezone.")
        if metadata.backup_format_version != BACKUP_FORMAT_VERSION:
            raise BackupValidationError(
                "The backup format is not supported by this Hesiva version."
            )
        if (
            not isinstance(metadata.application_version, str)
            or not metadata.application_version
            or not isinstance(metadata.database_revision, str)
            or not metadata.database_revision
            or not isinstance(metadata.database_size, int)
            or metadata.database_size <= 0
            or not isinstance(metadata.database_sha256, str)
            or len(metadata.database_sha256) != 64
            or any(character not in hexdigits for character in metadata.database_sha256)
        ):
            raise BackupValidationError("The backup metadata is incomplete.")
        return metadata

    @staticmethod
    def _metadata_payload(metadata: BackupMetadata) -> dict[str, object]:
        return {
            "application": "Hesiva",
            "application_version": metadata.application_version,
            "backup_format_version": metadata.backup_format_version,
            "created_at": metadata.created_at.isoformat(),
            "database_revision": metadata.database_revision,
            "database_sha256": metadata.database_sha256,
            "database_size": metadata.database_size,
            "operating_system": platform.system(),
        }

    @staticmethod
    def _read_json_member(
        archive: zipfile.ZipFile,
        member: zipfile.ZipInfo,
        maximum_bytes: int,
    ) -> Any:
        payload = BackupService._read_member_bytes(archive, member, maximum_bytes)
        return json.loads(payload.decode("utf-8"))

    @staticmethod
    def _read_member_bytes(
        archive: zipfile.ZipFile,
        member: zipfile.ZipInfo,
        maximum_bytes: int,
    ) -> bytes:
        with archive.open(member, "r") as file_handle:
            payload = file_handle.read(maximum_bytes + 1)
            if len(payload) > maximum_bytes or file_handle.read(1):
                raise BackupValidationError("A backup metadata member is too large.")
            return payload

    @staticmethod
    def _copy_archive_member(
        archive: zipfile.ZipFile,
        member: zipfile.ZipInfo,
        destination_path: Path,
        maximum_bytes: int,
    ) -> None:
        copied_bytes = 0
        with archive.open(member, "r") as source, destination_path.open("wb") as destination:
            while chunk := source.read(COPY_BUFFER_SIZE):
                copied_bytes += len(chunk)
                if copied_bytes > maximum_bytes:
                    raise BackupValidationError("The backup database is too large.")
                destination.write(chunk)
        if copied_bytes != member.file_size:
            raise BackupValidationError("The backup database member is incomplete.")

    @staticmethod
    def _connect_read_only(database_path: Path) -> sqlite3.Connection:
        database_uri = f"{database_path.resolve().as_uri()}?mode=ro"
        return sqlite3.connect(database_uri, uri=True)

    def _ensure_no_live_sidecars(self) -> None:
        sidecars: list[Path] = []
        for path in self._live_sidecars():
            try:
                path.lstat()
            except FileNotFoundError:
                continue
            except OSError as error:
                raise RestoreError(
                    "SQLite sidecar state could not be inspected safely; restore was not started."
                ) from error
            sidecars.append(path)
        if sidecars:
            raise RestoreError(
                "SQLite sidecar files remained after engine shutdown; restore was not started."
            )

    def _remove_live_sidecars_for_rollback(self) -> None:
        for sidecar in self._live_sidecars():
            sidecar.unlink(missing_ok=True)

    def _live_sidecars(self) -> tuple[Path, Path, Path]:
        return (
            Path(f"{self.live_database_path}-wal"),
            Path(f"{self.live_database_path}-shm"),
            Path(f"{self.live_database_path}-journal"),
        )

    @staticmethod
    def _new_temporary_path(directory: Path, suffix: str) -> Path:
        file_descriptor, name = tempfile.mkstemp(
            prefix=".hesiva-",
            suffix=suffix,
            dir=directory,
        )
        path = Path(name)
        try:
            os.close(file_descriptor)
            # mkstemp already creates mode 0600. Keep the explicit policy helper
            # for platforms where permission application has different semantics.
            BackupService._set_private_permissions(path)
            return path
        except Exception as error:
            try:
                os.close(file_descriptor)
            except OSError as cleanup_error:
                error.add_note(
                    "The temporary-file descriptor could not be closed: "
                    f"{type(cleanup_error).__name__}."
                )
            BackupService._remove_temporary_file(path, primary_error=error)
            raise

    @staticmethod
    def _remove_temporary_database(
        database_path: Path,
        *,
        primary_error: BaseException | None = None,
    ) -> None:
        for path in (
            database_path,
            Path(f"{database_path}-wal"),
            Path(f"{database_path}-shm"),
            Path(f"{database_path}-journal"),
        ):
            BackupService._remove_temporary_file(path, primary_error=primary_error)

    @staticmethod
    def _set_private_permissions(path: Path) -> None:
        if os.name == "posix":
            path.chmod(0o600)

    @staticmethod
    def _paths_refer_to_same_file(first: Path, second: Path) -> bool:
        try:
            return first.samefile(second)
        except (FileNotFoundError, OSError):
            return first.resolve(strict=False) == second.resolve(strict=False)

    @staticmethod
    def _next_available_path(base_path: Path) -> Path:
        if not base_path.exists():
            return base_path
        for counter in range(1, 10_000):
            candidate = base_path.with_stem(f"{base_path.stem}_{counter}")
            if not candidate.exists():
                return candidate
        raise BackupPathError("A unique safety-backup filename could not be created.")

    @staticmethod
    def _publish_without_overwrite(
        staged_path: Path,
        destination_path: Path,
    ) -> None:
        """Copy to a newly created destination without replacing an existing path."""
        expected_digest = BackupService._sha256(staged_path)
        try:
            descriptor = os.open(
                destination_path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
        except FileExistsError as error:
            raise BackupPathError("An existing backup file will not be overwritten.") from error
        try:
            destination_handle = os.fdopen(descriptor, "wb")
            descriptor = -1
            copied_digest = hashlib.sha256()
            with destination_handle as destination, staged_path.open("rb") as source:
                while chunk := source.read(COPY_BUFFER_SIZE):
                    copied_digest.update(chunk)
                    destination.write(chunk)
                destination.flush()
                os.fsync(destination.fileno())
            if copied_digest.hexdigest() != expected_digest:
                raise BackupError("The published backup did not match its verified staging file.")
        except BaseException as error:
            if descriptor >= 0:
                try:
                    os.close(descriptor)
                except OSError as cleanup_error:
                    error.add_note(
                        "The backup destination descriptor could not be closed: "
                        f"{type(cleanup_error).__name__}."
                    )
            raise

    @staticmethod
    def _remove_temporary_file(
        path: Path,
        *,
        primary_error: BaseException | None,
    ) -> None:
        try:
            path.unlink(missing_ok=True)
        except OSError as cleanup_error:
            if primary_error is not None:
                primary_error.add_note(
                    "A private temporary file could not be removed: "
                    f"{type(cleanup_error).__name__}."
                )
                return
            raise BackupError("A private temporary file could not be removed safely.") from (
                cleanup_error
            )

    @staticmethod
    def _cleanup_temporary_directory(
        directory: tempfile.TemporaryDirectory[str],
        *,
        primary_error: BaseException | None,
    ) -> None:
        try:
            directory.cleanup()
        except OSError as cleanup_error:
            if primary_error is not None:
                primary_error.add_note(
                    "A private backup-validation directory could not be removed: "
                    f"{type(cleanup_error).__name__}."
                )
                return
            raise BackupError(
                "A private backup-validation directory could not be removed safely."
            ) from cleanup_error

    @staticmethod
    def _find_semantic_database_error(connection: sqlite3.Connection) -> str | None:
        return find_database_semantic_error(connection)

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as file_handle:
            while chunk := file_handle.read(COPY_BUFFER_SIZE):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _application_version() -> str:
        return get_application_version()
