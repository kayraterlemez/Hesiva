import logging
import re
import stat
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum
from pathlib import Path

from hesiva.database.durability import sync_parent_directory
from hesiva.services.backup_service import BackupError, BackupMetadata, BackupService

LOGGER = logging.getLogger(__name__)

AUTOMATIC_BACKUP_RETENTION_DAYS = 30
_AUTOMATIC_BACKUP_PATTERN = re.compile(
    r"hesiva_auto_(?P<date>\d{4}-\d{2}-\d{2})_"
    r"(?P<time>\d{2}-\d{2}-\d{2})(?:_(?P<counter>[1-9]\d*))?\.zip"
)


class AutomaticBackupStatus(StrEnum):
    """Outcome of one application-run automatic-backup check."""

    CREATED = "created"
    ALREADY_EXISTS = "already_exists"
    ALREADY_ATTEMPTED = "already_attempted"


@dataclass(frozen=True, slots=True)
class AutomaticBackupResult:
    """Plain result of the startup automatic-backup policy."""

    status: AutomaticBackupStatus
    backup_path: Path | None
    metadata: BackupMetadata | None


class AutomaticBackupService:
    """Apply the once-per-run daily backup and narrowly scoped retention policy."""

    def __init__(
        self,
        backup_service: BackupService,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._backup_service = backup_service
        self._clock = clock or (lambda: datetime.now().astimezone())
        self._attempted = False

    def run_daily_backup(
        self,
        *,
        reference_datetime: datetime | None = None,
    ) -> AutomaticBackupResult:
        """Create at most one verified automatic backup in this application run."""
        if self._attempted:
            return AutomaticBackupResult(
                status=AutomaticBackupStatus.ALREADY_ATTEMPTED,
                backup_path=None,
                metadata=None,
            )
        self._attempted = True

        reference = reference_datetime or self._clock()
        if reference.tzinfo is not None:
            reference = reference.astimezone()
        backup_directory = self._backup_service.prepare_default_backup_directory()
        existing = self._find_valid_backup_for_date(backup_directory, reference.date())
        if existing is not None:
            path, metadata = existing
            return AutomaticBackupResult(
                status=AutomaticBackupStatus.ALREADY_EXISTS,
                backup_path=path,
                metadata=metadata,
            )

        destination = self._next_destination(backup_directory, reference)
        metadata = self._backup_service.create_backup(
            destination,
            created_at=reference.astimezone(),
        )
        verified_metadata = self._backup_service.validate_backup(destination)
        identity = self._automatic_identity(destination)
        if (
            verified_metadata != metadata
            or identity is None
            or not self._metadata_matches_identity(verified_metadata, identity)
        ):
            raise BackupError("The automatic backup verification result changed unexpectedly.")

        self._apply_retention(backup_directory, reference.date())
        return AutomaticBackupResult(
            status=AutomaticBackupStatus.CREATED,
            backup_path=destination,
            metadata=verified_metadata,
        )

    @property
    def attempted(self) -> bool:
        """Return whether this application-run policy has already been evaluated."""
        return self._attempted

    def _find_valid_backup_for_date(
        self,
        backup_directory: Path,
        reference_date: date,
    ) -> tuple[Path, BackupMetadata] | None:
        for path in sorted(backup_directory.iterdir(), key=lambda candidate: candidate.name):
            identity = self._automatic_identity(path)
            if identity is None or identity.date() != reference_date:
                continue
            validated = self._validate_stable_candidate(path)
            if validated is not None:
                metadata, _fingerprint = validated
                if not self._metadata_matches_identity(metadata, identity):
                    continue
                return path, metadata
        return None

    def _apply_retention(self, backup_directory: Path, reference_date: date) -> None:
        cutoff = reference_date - timedelta(days=AUTOMATIC_BACKUP_RETENTION_DAYS - 1)
        for path in tuple(backup_directory.iterdir()):
            identity = self._automatic_identity(path)
            if identity is None or identity.date() >= cutoff:
                continue
            validated = self._validate_stable_candidate(path)
            if validated is None:
                continue
            metadata, fingerprint = validated
            if not self._metadata_matches_identity(metadata, identity):
                continue
            try:
                before = path.lstat()
                current_fingerprint = (
                    before.st_dev,
                    before.st_ino,
                    before.st_size,
                    before.st_mtime_ns,
                )
                if not stat.S_ISREG(before.st_mode) or current_fingerprint != fingerprint:
                    continue
                path.unlink()
                sync_parent_directory(path)
            except OSError as error:
                LOGGER.warning(
                    "Automatic-backup retention cleanup could not be completed durably: %s",
                    type(error).__name__,
                )

    def _validate_stable_candidate(
        self,
        path: Path,
    ) -> tuple[BackupMetadata, tuple[int, int, int, int]] | None:
        try:
            before = path.lstat()
            if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
                return None
            metadata = self._backup_service.validate_backup(path)
            after = path.lstat()
        except (BackupError, OSError):
            return None
        if after.st_nlink != 1:
            return None
        before_identity = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        after_identity = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        return (metadata, after_identity) if before_identity == after_identity else None

    @staticmethod
    def _metadata_matches_identity(metadata: BackupMetadata, identity: datetime) -> bool:
        local_created_at = metadata.created_at.astimezone().replace(tzinfo=None, microsecond=0)
        return local_created_at == identity

    @staticmethod
    def _automatic_identity(path: Path) -> datetime | None:
        if path.is_symlink():
            return None
        match = _AUTOMATIC_BACKUP_PATTERN.fullmatch(path.name)
        if match is None:
            return None
        try:
            return datetime.strptime(
                f"{match.group('date')} {match.group('time')}",
                "%Y-%m-%d %H-%M-%S",
            )
        except ValueError:
            return None

    @staticmethod
    def _next_destination(backup_directory: Path, reference: datetime) -> Path:
        timestamp = reference.strftime("%Y-%m-%d_%H-%M-%S")
        base = backup_directory / f"hesiva_auto_{timestamp}.zip"
        if not base.exists() and not base.is_symlink():
            return base
        for counter in range(1, 10_000):
            candidate = backup_directory / f"hesiva_auto_{timestamp}_{counter}.zip"
            if not candidate.exists() and not candidate.is_symlink():
                return candidate
        raise BackupError("A unique automatic-backup filename could not be created.")
