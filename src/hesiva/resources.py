"""Read-only application resource lookup for source and frozen execution."""

from pathlib import Path

APPLICATION_ICON_FILENAME = "hesiva-icon.png"


def get_application_icon_path(
    *,
    package_directory: Path | None = None,
    repository_root: Path | None = None,
) -> Path | None:
    """Return the packaged or source-tree application icon without writing files."""
    package_root = (
        Path(__file__).resolve().parent if package_directory is None else package_directory
    )
    source_root = (
        Path(__file__).resolve().parents[2] if repository_root is None else repository_root
    )
    candidates = (
        package_root / "assets" / APPLICATION_ICON_FILENAME,
        source_root / "assets" / APPLICATION_ICON_FILENAME,
    )
    return next((candidate for candidate in candidates if candidate.is_file()), None)
