"""Shared, non-runtime PyInstaller configuration helpers."""

import tomllib
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from PyInstaller.utils.hooks import copy_metadata
from PyInstaller.depend.bindepend import resolve_library_path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
MIGRATION_SOURCE = SOURCE_ROOT / "hesiva" / "database" / "migrations"
MIGRATION_DESTINATION = "hesiva/database/migrations"
APPLICATION_ICON_SOURCE = REPOSITORY_ROOT / "assets" / "hesiva-icon.png"
APPLICATION_ICON_DESTINATION = "hesiva/assets"
WINDOWS_ICON_SOURCE = REPOSITORY_ROOT / "packaging" / "icons" / "hesiva.ico"
REQUIRED_LINUX_LIBRARIES = ("libxcb-cursor.so.0", "libcups.so.2")

DEVELOPMENT_EXCLUDES = (
    "pytest",
    # The windowed application has no interactive Python shell. Excluding the
    # optional module also prevents bundling GNU Readline's GPL-only runtime.
    "readline",
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
        (str(APPLICATION_ICON_SOURCE), APPLICATION_ICON_DESTINATION),
        *copy_metadata("hesiva"),
    ]


def executable_icon() -> str | None:
    """Return the native Windows executable icon; Linux uses desktop/runtime PNGs."""
    if sys.platform != "win32":
        return None
    if not WINDOWS_ICON_SOURCE.is_file():
        raise RuntimeError(f"Windows icon is unavailable: {WINDOWS_ICON_SOURCE}")
    return str(WINDOWS_ICON_SOURCE)


def required_linux_binaries() -> list[tuple[str, str]]:
    """Require and explicitly bundle Linux clients needed by XCB and printing."""
    if not sys.platform.startswith("linux"):
        return []
    binaries: list[tuple[str, str]] = []
    for soname in REQUIRED_LINUX_LIBRARIES:
        source = resolve_library_path(soname)
        if source is None:
            raise RuntimeError(f"Required Linux release library is unavailable: {soname}")
        binaries.append((source, "."))
    return binaries


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
    """Exclude unused Qt payloads that are outside Hesiva's desktop runtime contract."""
    excluded_suffixes = (
        # Hesiva does not load TIFF content and the Linux build host does not
        # provide the plugin's complete native dependency closure.
        "PySide6/Qt/plugins/imageformats/libqtiff.so",
        # Qt Virtual Keyboard is a GPL-only Qt module for open-source users.
        # Hesiva is a conventional desktop Widgets application and neither
        # imports this module nor provides an on-screen-keyboard workflow.
        "PySide6/Qt/plugins/platforminputcontexts/libqtvirtualkeyboardplugin.so",
        "PySide6/Qt/plugins/platforminputcontexts/qtvirtualkeyboardplugin.dll",
        "PySide6/Qt/lib/libQt6VirtualKeyboard.so.6",
        "PySide6/Qt/lib/libQt6VirtualKeyboardQml.so.6",
        "PySide6/Qt/bin/Qt6VirtualKeyboard.dll",
        "PySide6/Qt/bin/Qt6VirtualKeyboardQml.dll",
        "libQt6VirtualKeyboard.so.6",
        "libQt6VirtualKeyboardQml.so.6",
        "Qt6VirtualKeyboard.dll",
        "Qt6VirtualKeyboardQml.dll",
        # These libraries are collected only as the virtual-keyboard
        # dependency cluster in Hesiva's Qt Widgets/PDF/print build.
        "PySide6/Qt/lib/libQt6Qml.so.6",
        "PySide6/Qt/lib/libQt6QmlMeta.so.6",
        "PySide6/Qt/lib/libQt6QmlModels.so.6",
        "PySide6/Qt/lib/libQt6QmlWorkerScript.so.6",
        "PySide6/Qt/lib/libQt6Quick.so.6",
        "PySide6/Qt/bin/Qt6Qml.dll",
        "PySide6/Qt/bin/Qt6QmlMeta.dll",
        "PySide6/Qt/bin/Qt6QmlModels.dll",
        "PySide6/Qt/bin/Qt6QmlWorkerScript.dll",
        "PySide6/Qt/bin/Qt6Quick.dll",
        "libQt6Qml.so.6",
        "libQt6QmlMeta.so.6",
        "libQt6QmlModels.so.6",
        "libQt6QmlWorkerScript.so.6",
        "libQt6Quick.so.6",
        "Qt6Qml.dll",
        "Qt6QmlMeta.dll",
        "Qt6QmlModels.dll",
        "Qt6QmlWorkerScript.dll",
        "Qt6Quick.dll",
    )
    return [
        entry
        for entry in entries
        if not str(entry[0]).replace("\\", "/").endswith(excluded_suffixes)
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
