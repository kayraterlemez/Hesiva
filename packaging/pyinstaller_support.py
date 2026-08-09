"""Shared, non-runtime PyInstaller configuration helpers."""

import tomllib
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from PyInstaller.utils.hooks import copy_metadata

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
MIGRATION_SOURCE = SOURCE_ROOT / "hesiva" / "database" / "migrations"
MIGRATION_DESTINATION = "hesiva/database/migrations"

DEVELOPMENT_EXCLUDES = (
    "pytest",
    "ruff",
    "tests",
)
PROJECT_METADATA_PATH = REPOSITORY_ROOT / "pyproject.toml"

# Alembic executes migration source files dynamically, so imports that exist only
# in those files are not visible to PyInstaller's static analysis.
MIGRATION_HIDDEN_IMPORTS = (
    "hesiva.database.engine",
    "hesiva.models",
    "logging.config",
)


def hesiva_datas() -> list[tuple[str, str]]:
    """Bundle dynamic migration files and metadata generated from pyproject.toml."""
    verify_build_metadata()
    return [
        (str(MIGRATION_SOURCE), MIGRATION_DESTINATION),
        *copy_metadata("hesiva"),
    ]


def verify_build_metadata() -> str:
    """Reject a build when installed metadata is absent or stale."""
    project = tomllib.loads(PROJECT_METADATA_PATH.read_text(encoding="utf-8"))
    project_version = project["project"]["version"]
    try:
        installed_version = version("hesiva")
    except PackageNotFoundError as error:
        raise RuntimeError('Install the build environment with: pip install -e ".[dev]"') from error
    if installed_version != project_version:
        raise RuntimeError(
            "Installed Hesiva metadata does not match pyproject.toml; reinstall the build environment."
        )
    return installed_version


def without_unused_qt_plugins(entries: list[tuple[str, str, str]]) -> list[tuple[str, str, str]]:
    """Exclude only the unused TIFF plugin whose host dependency is unavailable."""
    excluded_suffix = "PySide6/Qt/plugins/imageformats/libqtiff.so"
    return [
        entry for entry in entries if not str(entry[0]).replace("\\", "/").endswith(excluded_suffix)
    ]


def with_baseline_linux_libraries(
    entries: list[tuple[str, str, str]],
) -> list[tuple[str, str, str]]:
    """Avoid host-selected x86-64-v3 libraries in the old-hardware Linux bundle."""
    baseline_entries: list[tuple[str, str, str]] = []
    for destination, source, entry_type in entries:
        normalized_source = str(source).replace("\\", "/")
        marker = "/glibc-hwcaps/"
        if marker not in normalized_source:
            baseline_entries.append((destination, source, entry_type))
            continue
        library_root, _optimized_suffix = normalized_source.split(marker, maxsplit=1)
        baseline_source = Path(library_root) / Path(normalized_source).name
        if not baseline_source.is_file():
            raise RuntimeError(f"Baseline system library is unavailable: {baseline_source}")
        baseline_entries.append((destination, str(baseline_source), entry_type))
    return baseline_entries
