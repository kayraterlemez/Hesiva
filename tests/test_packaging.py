import runpy
from pathlib import Path

import pytest

from hesiva.database import startup
from hesiva.database.paths import get_application_data_directory
from hesiva.database.startup import DatabaseStartupError
from hesiva.version import get_application_version

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def test_migration_resource_directory_is_complete() -> None:
    migration_directory = startup.get_migration_directory()

    assert migration_directory.is_dir()
    assert all(
        (migration_directory / resource).exists()
        for resource in startup.REQUIRED_MIGRATION_RESOURCES
    )
    assert startup.get_migration_head() == "b46d1256c5f2"


def test_missing_frozen_migration_resources_fail_clearly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(startup, "MIGRATION_DIRECTORY", tmp_path)

    with pytest.raises(DatabaseStartupError, match="migration resources"):
        startup.get_migration_directory()


def test_build_data_contains_only_metadata_and_migrations() -> None:
    support = runpy.run_path(str(REPOSITORY_ROOT / "packaging" / "pyinstaller_support.py"))
    data_sources = [Path(source) for source, _destination in support["hesiva_datas"]()]
    destinations = [destination for _source, destination in support["hesiva_datas"]()]

    assert data_sources[0] == REPOSITORY_ROOT / "src/hesiva/database/migrations"
    assert destinations[0] == "hesiva/database/migrations"
    assert any(destination.endswith(".dist-info") for destination in destinations[1:])
    assert all("tests" not in source.parts for source in data_sources)
    assert all(source.suffix not in {".db", ".exa", ".zip"} for source in data_sources)


def test_build_metadata_matches_authoritative_project_version() -> None:
    support = runpy.run_path(str(REPOSITORY_ROOT / "packaging" / "pyinstaller_support.py"))

    assert support["verify_build_metadata"]() == get_application_version()


def test_only_unavailable_unused_tiff_plugin_is_filtered() -> None:
    support = runpy.run_path(str(REPOSITORY_ROOT / "packaging" / "pyinstaller_support.py"))
    entries = [
        ("PySide6/Qt/plugins/imageformats/libqtiff.so", "/host/libqtiff.so", "BINARY"),
        ("PySide6/Qt/plugins/imageformats/libqjpeg.so", "/host/libqjpeg.so", "BINARY"),
        ("PySide6/Qt/plugins/platforms/libqxcb.so", "/host/libqxcb.so", "BINARY"),
    ]

    assert support["without_unused_qt_plugins"](entries) == entries[1:]


def test_host_hwcaps_libraries_are_replaced_with_baseline_variants(tmp_path: Path) -> None:
    support = runpy.run_path(str(REPOSITORY_ROOT / "packaging" / "pyinstaller_support.py"))
    library_root = tmp_path / "lib64"
    optimized = library_root / "glibc-hwcaps/x86-64-v3/libexample.so"
    baseline = library_root / "libexample.so"
    optimized.parent.mkdir(parents=True)
    optimized.touch()
    baseline.touch()
    ordinary = ("ordinary.so", "/vendor/ordinary.so", "BINARY")

    assert support["with_baseline_linux_libraries"](
        [("libexample.so", str(optimized), "BINARY"), ordinary]
    ) == [("libexample.so", str(baseline), "BINARY"), ordinary]


def test_linux_data_path_is_independent_of_working_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_home = tmp_path / "xdg-data"
    unrelated_working_directory = tmp_path / "working-directory"
    unrelated_working_directory.mkdir()
    monkeypatch.chdir(unrelated_working_directory)

    assert (
        get_application_data_directory(
            platform_name="linux",
            environment={"XDG_DATA_HOME": str(data_home)},
            home_directory=tmp_path / "home",
        )
        == data_home / "hesiva"
    )


def test_runtime_version_matches_project_metadata() -> None:
    project = REPOSITORY_ROOT / "pyproject.toml"

    assert f'version = "{get_application_version()}"' in project.read_text(encoding="utf-8")
