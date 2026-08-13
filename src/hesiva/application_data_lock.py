from pathlib import Path

from PySide6.QtCore import QLockFile


APPLICATION_DATA_LOCK_FILENAME = ".hesiva.lock"


class ApplicationDataLockError(Exception):
    """Base exception for application-data ownership failures."""


class ApplicationDataAlreadyInUseError(ApplicationDataLockError):
    """Raised when another live Hesiva process owns the application data."""


class ApplicationDataLock:
    """Own one application-data directory for the lifetime of an application context."""

    def __init__(self, application_data_directory: Path) -> None:
        directory = application_data_directory.expanduser()
        if not directory.is_absolute():
            raise ValueError("The application data directory must be absolute.")
        if not directory.is_dir():
            raise ValueError("The application data directory must exist before it is locked.")

        self.path = directory / APPLICATION_DATA_LOCK_FILENAME
        self._lock_file = QLockFile(str(self.path))
        # A live OS process must never lose ownership merely because a wall-clock
        # timeout elapsed. QLockFile still recognizes and removes a crashed local
        # owner's stale file through its PID/process checks.
        self._lock_file.setStaleLockTime(0)
        self._is_locked = False

    def acquire(self) -> None:
        """Acquire ownership immediately without waiting behind another process."""
        if self._is_locked:
            return
        if self._lock_file.tryLock(0):
            self._is_locked = True
            return

        if self._lock_file.error() == QLockFile.LockError.LockFailedError:
            raise ApplicationDataAlreadyInUseError(
                "Another Hesiva process already owns this application-data directory."
            )
        raise ApplicationDataLockError(
            "Hesiva could not establish exclusive ownership of its application data."
        )

    def release(self) -> None:
        """Release ownership after all application database resources are closed."""
        if not self._is_locked:
            return
        self._lock_file.unlock()
        self._is_locked = False
