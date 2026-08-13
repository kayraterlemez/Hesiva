import os
import sys
from collections.abc import Mapping
from pathlib import Path

from hesiva.database.durability import sync_parent_directory

APPLICATION_DIRECTORY_NAME = "hesiva"
WINDOWS_APPLICATION_DIRECTORY_NAME = "Hesiva"
DATABASE_FILENAME = "hesiva.db"
CONFIG_FILENAME = "config.json"


def get_application_data_directory(
    *,
    platform_name: str | None = None,
    environment: Mapping[str, str] | None = None,
    home_directory: Path | None = None,
) -> Path:
    """Return the platform-specific Hesiva data directory without creating it."""
    current_platform = sys.platform if platform_name is None else platform_name
    current_environment = os.environ if environment is None else environment
    current_home = Path.home() if home_directory is None else home_directory

    if current_platform == "win32":
        local_app_data = current_environment.get("LOCALAPPDATA")
        if local_app_data:
            local_app_data_path = Path(local_app_data)
            if local_app_data_path.is_absolute():
                return local_app_data_path / WINDOWS_APPLICATION_DIRECTORY_NAME

        return current_home / "AppData" / "Local" / WINDOWS_APPLICATION_DIRECTORY_NAME

    if current_platform.startswith("linux"):
        xdg_data_home = current_environment.get("XDG_DATA_HOME")
        if xdg_data_home:
            xdg_data_home_path = Path(xdg_data_home)
            if xdg_data_home_path.is_absolute():
                return xdg_data_home_path / APPLICATION_DIRECTORY_NAME

        return current_home / ".local" / "share" / APPLICATION_DIRECTORY_NAME

    raise ValueError(f"Unsupported platform: {current_platform}")


def get_production_database_path(application_data_directory: Path | None = None) -> Path:
    """Return the production database path without creating files or directories."""
    data_directory = (
        get_application_data_directory()
        if application_data_directory is None
        else application_data_directory
    )
    return data_directory / DATABASE_FILENAME


def get_config_path(application_data_directory: Path | None = None) -> Path:
    """Return the persistent configuration path without creating it."""
    data_directory = (
        get_application_data_directory()
        if application_data_directory is None
        else application_data_directory
    )
    return data_directory / CONFIG_FILENAME


def ensure_application_data_directory(application_data_directory: Path | None = None) -> Path:
    """Create the application data directory explicitly and return it."""
    data_directory = (
        get_application_data_directory()
        if application_data_directory is None
        else application_data_directory
    )
    missing_directories: list[Path] = []
    candidate = data_directory
    while not candidate.exists():
        missing_directories.append(candidate)
        if candidate.parent == candidate:
            break
        candidate = candidate.parent

    data_directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if os.name == "posix" and not data_directory.is_symlink():
        data_directory.chmod(0o700)
        # Persist every directory entry created by ``parents=True`` from the
        # existing ancestor down. Files fsynced inside a newly-created directory
        # are not a durable first-run database if the directory entry itself can
        # disappear after a power loss.
        for created_directory in reversed(missing_directories):
            sync_parent_directory(created_directory)
    return data_directory
