import os
from pathlib import Path


def sync_file(file_path: Path) -> None:
    """Flush one completed file to durable storage where supported."""
    with file_path.open("rb") as file_handle:
        os.fsync(file_handle.fileno())


def sync_parent_directory(file_path: Path) -> None:
    """Persist a published directory entry on POSIX; Windows keeps native behavior."""
    if os.name != "posix":
        return

    open_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0)
    directory_descriptor = os.open(file_path.parent, open_flags)
    try:
        os.fsync(directory_descriptor)
    finally:
        os.close(directory_descriptor)
