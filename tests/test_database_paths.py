import os
import subprocess
import sys
from pathlib import Path

from hesiva.database.paths import (
    CONFIG_FILENAME,
    DATABASE_FILENAME,
    ensure_application_data_directory,
    get_application_data_directory,
    get_config_path,
    get_production_database_path,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_linux_data_directory_respects_xdg_without_creating_it(tmp_path: Path) -> None:
    xdg_data_home = tmp_path / "xdg-data"

    data_directory = get_application_data_directory(
        platform_name="linux",
        environment={"XDG_DATA_HOME": str(xdg_data_home)},
        home_directory=tmp_path / "home",
    )

    assert isinstance(data_directory, Path)
    assert data_directory == xdg_data_home / "hesiva"
    assert not xdg_data_home.exists()


def test_linux_data_directory_uses_xdg_default(tmp_path: Path) -> None:
    home_directory = tmp_path / "home"

    data_directory = get_application_data_directory(
        platform_name="linux",
        environment={},
        home_directory=home_directory,
    )

    assert data_directory == home_directory / ".local" / "share" / "hesiva"
    assert not home_directory.exists()


def test_windows_data_directory_uses_local_app_data(tmp_path: Path) -> None:
    local_app_data = tmp_path / "LocalAppData"

    data_directory = get_application_data_directory(
        platform_name="win32",
        environment={"LOCALAPPDATA": str(local_app_data)},
        home_directory=tmp_path / "home",
    )

    assert data_directory == local_app_data / "Hesiva"
    assert not local_app_data.exists()


def test_database_path_and_directory_creation_are_explicit(tmp_path: Path) -> None:
    data_directory = tmp_path / "application-data"

    database_path = get_production_database_path(data_directory)
    config_path = get_config_path(data_directory)

    assert DATABASE_FILENAME == "hesiva.db"
    assert database_path == data_directory / DATABASE_FILENAME
    assert CONFIG_FILENAME == "config.json"
    assert config_path == data_directory / CONFIG_FILENAME
    assert not data_directory.exists()
    assert ensure_application_data_directory(data_directory) == data_directory
    assert data_directory.is_dir()
    if os.name == "posix":
        assert data_directory.stat().st_mode & 0o777 == 0o700


def test_importing_database_modules_has_no_data_directory_side_effect(tmp_path: Path) -> None:
    data_home = tmp_path / "xdg-data"
    environment = os.environ.copy()
    environment["XDG_DATA_HOME"] = str(data_home)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONPATH"] = str(PROJECT_ROOT / "src")

    subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import hesiva.database.base; "
                "import hesiva.database.engine; "
                "import hesiva.database.paths; "
                "import hesiva.database.session"
            ),
        ],
        cwd=tmp_path,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )

    assert not data_home.exists()
    assert not (tmp_path / DATABASE_FILENAME).exists()
