"""Record and verify the source provenance of the frozen release runtime."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import stat
import sys
import tempfile
import tomllib
from collections.abc import Iterable
from pathlib import Path
from typing import Any

FORMAT_VERSION = 1
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUNTIME = REPOSITORY_ROOT / "dist" / "Hesiva"
DEFAULT_MANIFEST = REPOSITORY_ROOT / "dist" / "Hesiva.provenance.json"
SOURCE_INPUTS = (
    Path("src"),
    Path("assets/hesiva-icon.png"),
    Path("packaging/Hesiva.spec"),
    Path("packaging/pyinstaller_support.py"),
    Path("packaging/icons"),
    Path("packaging/linux"),
    Path("packaging/debian"),
    Path("LICENSE"),
    Path("pyproject.toml"),
)
IGNORED_SOURCE_DIRECTORIES = {"__pycache__"}
IGNORED_SOURCE_SUFFIXES = {".pyc", ".pyo"}


class ProvenanceError(RuntimeError):
    """Raised when a frozen artifact cannot be tied to current source inputs."""


def _update_record(
    digest: Any,
    *,
    entry_type: str,
    relative_path: str,
    mode: int,
    payload: bytes = b"",
    payload_size: int | None = None,
    finalize: bool = True,
) -> None:
    recorded_size = len(payload) if payload_size is None else payload_size
    header = f"{entry_type}\0{relative_path}\0{mode:o}\0{recorded_size}\0".encode()
    digest.update(header)
    digest.update(payload)
    if finalize:
        digest.update(b"\0")


def _normalized_relative(path: Path, base: Path) -> str:
    relative = path.relative_to(base).as_posix()
    return "" if relative == "." else relative


def _hash_entry(digest: Any, path: Path, base: Path) -> None:
    entry_stat = path.lstat()
    mode = stat.S_IMODE(entry_stat.st_mode)
    relative = _normalized_relative(path, base)
    if stat.S_ISLNK(entry_stat.st_mode):
        _update_record(
            digest,
            entry_type="link",
            relative_path=relative,
            mode=mode,
            payload=os.readlink(path).encode("utf-8", errors="surrogateescape"),
        )
        return
    if stat.S_ISDIR(entry_stat.st_mode):
        _update_record(
            digest,
            entry_type="directory",
            relative_path=relative,
            mode=mode,
        )
        return
    if stat.S_ISREG(entry_stat.st_mode):
        _update_record(
            digest,
            entry_type="file",
            relative_path=relative,
            mode=mode,
            payload_size=entry_stat.st_size,
            finalize=False,
        )
        bytes_read = 0
        with path.open("rb") as input_file:
            opened_stat = os.fstat(input_file.fileno())
            if (opened_stat.st_dev, opened_stat.st_ino) != (
                entry_stat.st_dev,
                entry_stat.st_ino,
            ):
                raise ProvenanceError(f"Build input changed while it was being hashed: {path}")
            while chunk := input_file.read(1024 * 1024):
                digest.update(chunk)
                bytes_read += len(chunk)
            final_stat = os.fstat(input_file.fileno())
        if (
            bytes_read != entry_stat.st_size
            or final_stat.st_size != entry_stat.st_size
            or final_stat.st_mtime_ns != entry_stat.st_mtime_ns
        ):
            raise ProvenanceError(f"Build input changed while it was being hashed: {path}")
        digest.update(b"\0")
        return
    raise ProvenanceError(f"Unsupported build input file type: {path}")


def _iter_tree(root: Path, *, ignore_source_caches: bool) -> Iterable[Path]:
    for current, directory_names, file_names in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        directory_names.sort()
        file_names.sort()

        traversed_directories: list[str] = []
        for directory_name in directory_names:
            if ignore_source_caches and directory_name in IGNORED_SOURCE_DIRECTORIES:
                continue
            directory_path = current_path / directory_name
            yield directory_path
            if not directory_path.is_symlink():
                traversed_directories.append(directory_name)
        directory_names[:] = traversed_directories

        for file_name in file_names:
            file_path = current_path / file_name
            if ignore_source_caches and file_path.suffix in IGNORED_SOURCE_SUFFIXES:
                continue
            yield file_path


def _digest_paths(
    base: Path,
    relative_inputs: Iterable[Path],
    *,
    ignore_source_caches: bool,
) -> str:
    digest = hashlib.sha256()
    for relative_input in sorted(relative_inputs, key=lambda path: path.as_posix()):
        path = base / relative_input
        if not path.exists() and not path.is_symlink():
            raise ProvenanceError(f"Required build input is missing: {path}")
        _hash_entry(digest, path, base)
        if path.is_dir() and not path.is_symlink():
            for entry in _iter_tree(path, ignore_source_caches=ignore_source_caches):
                _hash_entry(digest, entry, base)
    return digest.hexdigest()


def source_digest(repository_root: Path = REPOSITORY_ROOT) -> str:
    """Hash every repository input used by the production PyInstaller build."""
    return _digest_paths(
        repository_root,
        SOURCE_INPUTS,
        ignore_source_caches=True,
    )


def runtime_digest(runtime_path: Path = DEFAULT_RUNTIME) -> str:
    """Hash all runtime contents, file modes, and symbolic-link targets."""
    if runtime_path.is_symlink() or not runtime_path.is_dir():
        raise ProvenanceError(f"Frozen runtime directory is unavailable: {runtime_path}")
    return _digest_paths(
        runtime_path,
        (Path("."),),
        ignore_source_caches=False,
    )


def _project_version(repository_root: Path) -> str:
    payload = tomllib.loads((repository_root / "pyproject.toml").read_text(encoding="utf-8"))
    return str(payload["project"]["version"])


def record_manifest(
    *,
    expected_source_sha256: str,
    repository_root: Path = REPOSITORY_ROOT,
    runtime_path: Path = DEFAULT_RUNTIME,
    manifest_path: Path = DEFAULT_MANIFEST,
) -> dict[str, Any]:
    """Record a runtime only when source stayed unchanged for the whole build."""
    current_source_sha256 = source_digest(repository_root)
    if current_source_sha256 != expected_source_sha256:
        raise ProvenanceError("Release source changed while PyInstaller was building the runtime.")
    current_runtime_sha256 = runtime_digest(runtime_path)
    application_version = _project_version(repository_root)
    if source_digest(repository_root) != expected_source_sha256:
        raise ProvenanceError("Release source changed while build provenance was being recorded.")
    payload: dict[str, Any] = {
        "format_version": FORMAT_VERSION,
        "application_version": application_version,
        "source_sha256": current_source_sha256,
        "runtime_sha256": current_runtime_sha256,
        "build_python": platform.python_version(),
        "build_platform": platform.platform(),
        "build_machine": platform.machine(),
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{manifest_path.name}.",
        suffix=".tmp",
        dir=manifest_path.parent,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(payload, output, ensure_ascii=True, indent=2, sort_keys=True)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary_path, manifest_path)
        if os.name == "posix":
            directory_descriptor = os.open(manifest_path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)
    finally:
        temporary_path.unlink(missing_ok=True)
    return payload


def load_manifest(manifest_path: Path = DEFAULT_MANIFEST) -> dict[str, Any]:
    """Load and minimally validate build provenance metadata."""
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ProvenanceError(f"Build provenance manifest is unavailable: {manifest_path}")
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ProvenanceError("Build provenance manifest is unreadable.") from error
    required = {
        "format_version",
        "application_version",
        "source_sha256",
        "runtime_sha256",
        "build_python",
        "build_platform",
        "build_machine",
    }
    if not isinstance(payload, dict) or set(payload) != required:
        raise ProvenanceError("Build provenance manifest has an unsupported structure.")
    if payload["format_version"] != FORMAT_VERSION:
        raise ProvenanceError("Build provenance manifest format is unsupported.")
    for hash_field in ("source_sha256", "runtime_sha256"):
        value = payload[hash_field]
        if (
            not isinstance(value, str)
            or len(value) != 64
            or any(character not in "0123456789abcdef" for character in value)
        ):
            raise ProvenanceError("Build provenance manifest contains an invalid digest.")
    return payload


def verify_manifest(
    *,
    repository_root: Path = REPOSITORY_ROOT,
    runtime_path: Path = DEFAULT_RUNTIME,
    manifest_path: Path = DEFAULT_MANIFEST,
) -> dict[str, Any]:
    """Reject a runtime that differs from either its source or recorded bytes."""
    payload = load_manifest(manifest_path)
    if payload["application_version"] != _project_version(repository_root):
        raise ProvenanceError("Frozen runtime version does not match current project metadata.")
    if payload["source_sha256"] != source_digest(repository_root):
        raise ProvenanceError("Frozen runtime was built from different or stale source inputs.")
    if payload["runtime_sha256"] != runtime_digest(runtime_path):
        raise ProvenanceError("Frozen runtime contents differ from their recorded build artifact.")
    return payload


def invalidate_manifest(manifest_path: Path = DEFAULT_MANIFEST) -> None:
    """Ensure a failed or interrupted build cannot reuse prior provenance."""
    if manifest_path.is_symlink() or manifest_path.is_file():
        manifest_path.unlink()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("source-digest")
    subparsers.add_parser("invalidate")
    record = subparsers.add_parser("record")
    record.add_argument("--expected-source-sha256", required=True)
    verify = subparsers.add_parser("verify")
    verify.add_argument("--runtime", type=Path, default=DEFAULT_RUNTIME)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        if arguments.command == "source-digest":
            print(source_digest())
        elif arguments.command == "invalidate":
            invalidate_manifest()
        elif arguments.command == "record":
            payload = record_manifest(expected_source_sha256=arguments.expected_source_sha256)
            print(
                "Recorded frozen runtime provenance: "
                f"source={payload['source_sha256']} runtime={payload['runtime_sha256']}"
            )
        elif arguments.command == "verify":
            payload = verify_manifest(runtime_path=arguments.runtime.resolve())
            print(
                "Verified frozen runtime provenance: "
                f"source={payload['source_sha256']} runtime={payload['runtime_sha256']}"
            )
    except ProvenanceError as error:
        print(f"Artifact provenance verification failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
