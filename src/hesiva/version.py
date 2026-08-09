"""Runtime access to the application version defined by project metadata."""

import tomllib
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

_DISTRIBUTION_NAME = "hesiva"


def get_application_version() -> str:
    """Return the version generated from pyproject metadata, including in source checkouts."""
    try:
        return version(_DISTRIBUTION_NAME)
    except PackageNotFoundError:
        return _read_source_project_version()


def _read_source_project_version() -> str:
    project_path = Path(__file__).resolve().parents[2] / "pyproject.toml"
    try:
        payload = tomllib.loads(project_path.read_text(encoding="utf-8"))
        project_version = payload["project"]["version"]
    except (OSError, KeyError, TypeError, tomllib.TOMLDecodeError) as error:
        raise RuntimeError("The Hesiva application version could not be resolved.") from error
    if not isinstance(project_version, str) or not project_version.strip():
        raise RuntimeError("The Hesiva application version is invalid.")
    return project_version
