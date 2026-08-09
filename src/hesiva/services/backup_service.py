import hashlib
import json
import os
import platform
import sqlite3
import tempfile
import zipfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from hesiva.configuration import (
    ApplicationConfiguration,
    ConfigurationError,
    ConfigurationStore,
    InvalidConfigurationError,
)
from hesiva.database.durability import sync_file, sync_parent_directory
from hesiva.database.startup import DatabaseState, inspect_database

BACKUP_FORMAT_VERSION = 1
BACKUP_EXTENSION = ".zip"
DATABASE_ARCHIVE_NAME = "database.sqlite"
CONFIG_ARCHIVE_NAME = "config.json"
METADATA_ARCHIVE_NAME = "metadata.json"
REQUIRED_ARCHIVE_NAMES = {
    DATABASE_ARCHIVE_NAME,
    CONFIG_ARCHIVE_NAME,
    METADATA_ARCHIVE_NAME,
}
COPY_BUFFER_SIZE = 1024 * 1024


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
        backup_directory = self.live_database_path.parent / "backups"
        backup_directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if os.name == "posix":
            backup_directory.chmod(0o700)
        return backup_directory

    def create_backup(self, destination_path: Path) -> BackupMetadata:
        """Create and atomically publish a verified ZIP backup archive."""
        destination = self._validate_destination_path(destination_path)
        snapshot_path = self._new_temporary_path(destination.parent, ".snapshot.sqlite")
        archive_path = self._new_temporary_path(destination.parent, ".backup.zip")
        try:
            configuration = self._load_live_configuration()
            self._online_backup(self.live_database_path, snapshot_path)
            self._validate_current_database(snapshot_path)
            sync_file(snapshot_path)

            metadata = self._build_metadata(snapshot_path)
            self._write_archive(archive_path, snapshot_path, configuration, metadata)
            sync_file(archive_path)
            verified_metadata = self.validate_backup(archive_path)

            os.replace(archive_path, destination)
            self._set_private_permissions(destination)
            sync_parent_directory(destination)
            return verified_metadata
        except BackupError:
            raise
        except Exception as error:
            raise BackupError("The Hesiva backup could not be created safely.") from error
        finally:
            self._remove_temporary_database(snapshot_path)
            archive_path.unlink(missing_ok=True)

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
        with self._validated_archive_database(source) as (
            candidate_database,
            candidate_configuration,
            metadata,
        ):
            replacement_path = self._new_temporary_path(
                self.live_database_path.parent,
                ".restore.sqlite",
            )
            try:
                self._online_backup(candidate_database, replacement_path)
                self._validate_current_database(replacement_path)
                sync_file(replacement_path)
                replacement_config_path = self.configuration_store.stage(
                    candidate_configuration,
                    suffix=".restore-config.json",
                )
                try:
                    safety_backup_path = self._create_safety_backup()
                    return self._publish_restore(
                        replacement_path,
                        replacement_config_path,
                        metadata,
                        safety_backup_path,
                        close_live_database,
                        reopen_live_database,
                    )
                finally:
                    replacement_config_path.unlink(missing_ok=True)
            finally:
                self._remove_temporary_database(replacement_path)

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
                raise RestoreError("The restore stopped before replacing the live database.") from (
                    restore_error
                )
            self._rollback_after_failed_restore(
                safety_backup_path,
                close_live_database,
                reopen_live_database,
            )
            raise RestoreError(
                "The restored application snapshot could not be reopened; the previous database "
                "was restored together with its configuration."
            ) from restore_error

        return RestoreResult(metadata, safety_backup_path)

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
            self._remove_temporary_database(rollback_path)
            if rollback_config_path is not None:
                rollback_config_path.unlink(missing_ok=True)

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

    def _validate_destination_path(self, destination_path: Path) -> Path:
        destination = destination_path.expanduser()
        if not destination.is_absolute():
            raise BackupPathError("The backup destination must be an absolute path.")
        if self._paths_refer_to_same_file(destination, self.live_database_path):
            raise BackupPathError("The live database cannot be used as a backup destination.")
        if destination.exists() and destination.is_dir():
            raise BackupPathError("The backup destination is a directory.")
        if destination.is_symlink():
            raise BackupPathError("Symbolic-link backup destinations are not supported.")
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
        try:
            with tempfile.TemporaryDirectory(prefix="hesiva-backup-validation-") as directory:
                database_path = Path(directory) / DATABASE_ARCHIVE_NAME
                with zipfile.ZipFile(archive_path, "r") as archive:
                    names = archive.namelist()
                    if len(names) != len(set(names)) or set(names) != REQUIRED_ARCHIVE_NAMES:
                        raise BackupValidationError(
                            "The selected archive does not have the required Hesiva contents."
                        )
                    if archive.testzip() is not None:
                        raise BackupValidationError("The selected backup archive is corrupt.")
                    metadata_payload = self._read_json_member(archive, METADATA_ARCHIVE_NAME)
                    config_payload = self._read_json_member(archive, CONFIG_ARCHIVE_NAME)
                    try:
                        configuration = ApplicationConfiguration.from_payload(config_payload)
                    except InvalidConfigurationError as error:
                        raise BackupValidationError(
                            "The backup configuration is invalid."
                        ) from error
                    self._copy_archive_member(archive, DATABASE_ARCHIVE_NAME, database_path)

                metadata = self._parse_metadata(metadata_payload)
                self._validate_metadata_database(database_path, metadata)
                yield database_path, configuration, metadata
        except BackupValidationError:
            raise
        except (OSError, ValueError, zipfile.BadZipFile, json.JSONDecodeError) as error:
            raise BackupValidationError(
                "The selected file is not a valid Hesiva backup."
            ) from error

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
            with self._connect_read_only(database_path) as connection:
                integrity_rows = connection.execute("PRAGMA integrity_check").fetchall()
        except (OSError, sqlite3.DatabaseError) as error:
            raise BackupValidationError(
                "The backup database could not be opened safely."
            ) from error
        if integrity_rows != [("ok",)]:
            raise BackupValidationError("The backup database failed SQLite integrity verification.")

        status = inspect_database(database_path)
        if status.state is DatabaseState.OUTDATED:
            raise BackupValidationError(
                "The backup database version is older than this Hesiva version."
            )
        if status.state is not DatabaseState.CURRENT:
            raise BackupValidationError("The backup is not a current valid Hesiva database.")

    def _online_backup(self, source_path: Path, destination_path: Path) -> None:
        try:
            with self._connect_read_only(source_path) as source_connection:
                with sqlite3.connect(destination_path) as destination_connection:
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

    def _build_metadata(self, database_path: Path) -> BackupMetadata:
        status = inspect_database(database_path)
        if status.current_revision is None:
            raise BackupValidationError("The database revision could not be determined.")
        return BackupMetadata(
            created_at=datetime.now(UTC),
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
    def _read_json_member(archive: zipfile.ZipFile, member_name: str) -> Any:
        with archive.open(member_name, "r") as member:
            return json.loads(member.read().decode("utf-8"))

    @staticmethod
    def _copy_archive_member(
        archive: zipfile.ZipFile,
        member_name: str,
        destination_path: Path,
    ) -> None:
        with archive.open(member_name, "r") as source, destination_path.open("wb") as destination:
            while chunk := source.read(COPY_BUFFER_SIZE):
                destination.write(chunk)

    @staticmethod
    def _connect_read_only(database_path: Path) -> sqlite3.Connection:
        database_uri = f"{database_path.resolve().as_uri()}?mode=ro"
        return sqlite3.connect(database_uri, uri=True)

    def _ensure_no_live_sidecars(self) -> None:
        sidecars = [path for path in self._live_sidecars() if path.exists()]
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
        os.close(file_descriptor)
        path = Path(name)
        BackupService._set_private_permissions(path)
        return path

    @staticmethod
    def _remove_temporary_database(database_path: Path) -> None:
        for path in (
            database_path,
            Path(f"{database_path}-wal"),
            Path(f"{database_path}-shm"),
            Path(f"{database_path}-journal"),
        ):
            path.unlink(missing_ok=True)

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
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as file_handle:
            while chunk := file_handle.read(COPY_BUFFER_SIZE):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _application_version() -> str:
        try:
            return version("hesiva")
        except PackageNotFoundError:
            return "0.1.0"
