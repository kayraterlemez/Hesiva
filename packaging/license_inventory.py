"""Stage and verify the exact third-party redistribution corpus."""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.metadata
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = REPOSITORY_ROOT / "packaging" / "license-policy.json"
SOURCE_REQUIREMENTS_PATH = REPOSITORY_ROOT / "packaging" / "lgpl-source-requirements.json"
NATIVE_APPROVALS_PATH = REPOSITORY_ROOT / "packaging" / "native-license-approvals.json"
DEFAULT_RUNTIME = REPOSITORY_ROOT / "dist" / "Hesiva"
DEFAULT_COLLECT_TOC = REPOSITORY_ROOT / "build" / "Hesiva" / "COLLECT-00.toc"
RUNTIME_INVENTORY = "third-party-runtime-inventory.json"
LEGAL_ROOT_ENTRIES = (
    "LICENSE",
    "THIRD_PARTY_NOTICES.md",
    "SOURCE-OFFER.md",
    "RELINKING.md",
    "licenses",
)
FORBIDDEN_RUNTIME_NAMES = ("virtualkeyboard", "libqt6qml", "qt6qml", "libqt6quick", "qt6quick")


class LicenseInventoryError(RuntimeError):
    """Raised when legal material does not match the frozen runtime."""


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise LicenseInventoryError(f"License metadata is unreadable: {path}") from error
    if not isinstance(payload, dict):
        raise LicenseInventoryError(f"License metadata has an unsupported structure: {path}")
    return payload


def load_policy(repository_root: Path = REPOSITORY_ROOT) -> dict[str, Any]:
    """Load the exact-version redistribution policy."""
    return _load_json(repository_root / "packaging" / "license-policy.json")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _tree_digest(root: Path, *, excluded_top_level: set[str]) -> str:
    digest = hashlib.sha256()
    if root.is_symlink() or not root.is_dir():
        raise LicenseInventoryError(f"Frozen runtime directory is unavailable: {root}")
    for path in sorted(root.rglob("*"), key=lambda value: value.relative_to(root).as_posix()):
        relative = path.relative_to(root)
        if relative.parts and relative.parts[0] in excluded_top_level:
            continue
        entry_stat = path.lstat()
        mode = stat.S_IMODE(entry_stat.st_mode)
        if path.is_symlink():
            kind = "link"
            payload = os.readlink(path).encode("utf-8", errors="surrogateescape")
        elif path.is_dir():
            kind = "directory"
            payload = b""
        elif path.is_file():
            kind = "file"
            payload = path.read_bytes()
        else:
            raise LicenseInventoryError(f"Unsupported runtime entry: {path}")
        digest.update(f"{kind}\0{relative.as_posix()}\0{mode:o}\0{len(payload)}\0".encode())
        digest.update(payload)
        digest.update(b"\0")
    return digest.hexdigest()


def runtime_payload_digest(runtime: Path) -> str:
    """Hash the frozen payload while excluding the staged legal corpus."""
    return _tree_digest(runtime, excluded_top_level={*LEGAL_ROOT_ENTRIES, RUNTIME_INVENTORY})


def legal_corpus_digest(root: Path) -> str:
    """Hash the platform-independent legal corpus, excluding generated native notices."""
    digest = hashlib.sha256()
    for entry_name in LEGAL_ROOT_ENTRIES:
        entry = root / entry_name
        if not entry.exists() and not entry.is_symlink():
            raise LicenseInventoryError(f"Legal corpus entry is unavailable: {entry_name}")
        paths = [entry]
        if entry.is_dir() and not entry.is_symlink():
            paths.extend(sorted(entry.rglob("*")))
        for path in paths:
            relative = path.relative_to(root)
            if relative.parts[:2] == ("licenses", "Native-Debian"):
                continue
            entry_stat = path.lstat()
            mode = stat.S_IMODE(entry_stat.st_mode)
            if path.is_symlink():
                kind = "link"
                payload = os.readlink(path).encode("utf-8", errors="surrogateescape")
            elif path.is_dir():
                kind = "directory"
                payload = b""
            elif path.is_file():
                kind = "file"
                payload = path.read_bytes()
            else:
                raise LicenseInventoryError(f"Unsupported legal corpus entry: {path}")
            digest.update(f"{kind}\0{relative.as_posix()}\0{mode:o}\0{len(payload)}\0".encode())
            digest.update(payload)
            digest.update(b"\0")
    return digest.hexdigest()


def verify_repository_corpus(repository_root: Path = REPOSITORY_ROOT) -> dict[str, Any]:
    """Verify all exact-version, authoritative repository legal inputs."""
    policy = load_policy(repository_root)
    if policy.get("format_version") != 1:
        raise LicenseInventoryError("Unsupported license policy format.")
    for relative in policy.get("required_legal_entries", []):
        path = repository_root / relative
        if path.is_symlink() or not path.is_file():
            raise LicenseInventoryError(f"Required legal material is unavailable: {relative}")
        if path.stat().st_size == 0:
            raise LicenseInventoryError(f"Required legal material is empty: {relative}")
    third_party_pages = list(
        (repository_root / "licenses" / f"Qt-{policy['qt_version']}" / "third-party").glob("*.html")
    )
    if len(third_party_pages) < 2:
        raise LicenseInventoryError("Qt third-party notice corpus is incomplete.")
    return policy


def verify_build_environment(repository_root: Path = REPOSITORY_ROOT) -> dict[str, Any]:
    """Reject a build environment whose runtime versions outgrew its notices."""
    policy = verify_repository_corpus(repository_root)
    if ".".join(map(str, sys.version_info[:3])) != policy["cpython_version"]:
        raise LicenseInventoryError("CPython version does not match the approved notice corpus.")
    for component in policy["distributions"]:
        try:
            installed_version = importlib.metadata.version(component["name"])
        except importlib.metadata.PackageNotFoundError as error:
            raise LicenseInventoryError(
                f"Required release distribution is unavailable: {component['name']}"
            ) from error
        if installed_version != component["version"]:
            raise LicenseInventoryError(
                f"License inventory version drift: {component['name']} "
                f"is {installed_version}, expected {component['version']}."
            )
    return policy


def _collect_entries(path: Path) -> list[tuple[str, str, str]]:
    try:
        payload = ast.literal_eval(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, SyntaxError, ValueError) as error:
        raise LicenseInventoryError("PyInstaller collection inventory is unreadable.") from error
    if isinstance(payload, tuple) and len(payload) == 1 and isinstance(payload[0], list):
        payload = payload[0]
    if not isinstance(payload, (list, tuple)):
        raise LicenseInventoryError("PyInstaller collection inventory has an unsupported shape.")
    entries: list[tuple[str, str, str]] = []
    for row in payload:
        if (
            not isinstance(row, (list, tuple))
            or len(row) != 3
            or not all(isinstance(value, str) for value in row)
        ):
            raise LicenseInventoryError("PyInstaller collection inventory contains an invalid row.")
        entries.append((row[0], row[1], row[2]))
    return entries


def _resolve_collect_destination(runtime: Path, destination: str) -> Path:
    candidates = (runtime / destination, runtime / "_internal" / destination)
    matches = [path for path in candidates if path.exists() or path.is_symlink()]
    if len(matches) > 1:
        raise LicenseInventoryError(
            f"PyInstaller collection entry is ambiguous in frozen runtime: {destination}"
        )
    if not matches:
        raise LicenseInventoryError(
            f"PyInstaller collection entry is absent from frozen runtime: {destination}"
        )
    return matches[0]


def _debian_owner(source_path: Path) -> dict[str, str]:
    search = subprocess.run(
        ["dpkg-query", "--search", str(source_path)],
        check=False,
        capture_output=True,
        text=True,
    )
    candidates = {
        line.rsplit(": ", maxsplit=1)[0] for line in search.stdout.splitlines() if ": " in line
    }
    if search.returncode != 0 or len(candidates) != 1:
        raise LicenseInventoryError(
            f"Bundled native file has no unique Debian package owner: {source_path}"
        )
    package_with_arch = candidates.pop()
    package = package_with_arch.split(":", maxsplit=1)[0]
    shown = subprocess.run(
        [
            "dpkg-query",
            "--show",
            "--showformat=${binary:Package}\t${Version}\t${source:Package}\t${source:Version}",
            package_with_arch,
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    fields = shown.stdout.strip().split("\t")
    if shown.returncode != 0 or len(fields) != 4 or not fields[0] or not fields[1]:
        raise LicenseInventoryError(f"Debian package metadata is unavailable: {package_with_arch}")
    copyright_path = Path("/usr/share/doc") / package / "copyright"
    if copyright_path.is_symlink():
        copyright_path = copyright_path.resolve(strict=True)
    if not copyright_path.is_file():
        raise LicenseInventoryError(f"Debian copyright metadata is unavailable: {package}")
    return {
        "binary_package": fields[0],
        "binary_version": fields[1],
        "source_package": fields[2] or fields[0],
        "source_version": fields[3] or fields[1],
        "copyright_path": str(copyright_path),
    }


def _native_debian_inventory(
    entries: list[tuple[str, str, str, Path]], repository_root: Path, runtime: Path
) -> tuple[list[dict[str, Any]], dict[str, Path]]:
    if shutil.which("dpkg-query") is None:
        raise LicenseInventoryError(
            "Redistributable Linux staging requires dpkg-query on the Debian-family build host."
        )
    root = repository_root.resolve()
    environment_root = Path(sys.prefix).resolve()
    package_sources: dict[str, dict[str, Any]] = {}
    copyright_files: dict[str, Path] = {}
    for _destination, raw_source, entry_type, runtime_path in entries:
        source = Path(raw_source)
        if entry_type == "SYMLINK" or not source.is_absolute():
            continue
        resolved_source = source.resolve(strict=False)
        if any(
            _is_relative_to(resolved_source, excluded_root)
            for excluded_root in (root, environment_root)
        ):
            continue
        owner = _debian_owner(source)
        package_name = owner["binary_package"].replace(":", "_")
        record = package_sources.setdefault(
            package_name,
            {
                key: owner[key]
                for key in ("binary_package", "binary_version", "source_package", "source_version")
            }
            | {"runtime_entries": []},
        )
        record["runtime_entries"].append(runtime_path.relative_to(runtime).as_posix())
        copyright_files[package_name] = Path(owner["copyright_path"])
    if not package_sources:
        raise LicenseInventoryError("No Debian-owned bundled native files were identified.")
    records = []
    for package_name in sorted(package_sources):
        record = package_sources[package_name]
        record["runtime_entries"] = sorted(set(record["runtime_entries"]))
        records.append(record)
    return records, copyright_files


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _copy_legal_corpus(repository_root: Path, runtime: Path) -> None:
    for filename in LEGAL_ROOT_ENTRIES[:-1]:
        shutil.copy2(repository_root / filename, runtime / filename)
    shutil.copytree(repository_root / "licenses", runtime / "licenses", dirs_exist_ok=True)


def _native_approval_state(
    native_packages: list[dict[str, Any]], repository_root: Path
) -> tuple[bool, list[dict[str, Any]], str]:
    approvals_path = repository_root / "packaging" / "native-license-approvals.json"
    payload = _load_json(approvals_path)
    approvals = payload.get("approvals")
    if payload.get("format_version") != 1 or not isinstance(approvals, list):
        raise LicenseInventoryError("Native-library license approvals have an unsupported format.")
    identity_fields = ("binary_package", "binary_version", "source_package", "source_version")

    def identity(record: dict[str, Any]) -> tuple[Any, ...]:
        return tuple(record.get(field) for field in identity_fields)

    complete = (
        payload.get("status") == "reviewed"
        and len(approvals) == len(native_packages)
        and {identity(record) for record in approvals}
        == {identity(record) for record in native_packages}
        and all(
            isinstance(record, dict)
            and isinstance(record.get("license_conclusion"), str)
            and bool(record["license_conclusion"].strip())
            and isinstance(record.get("corresponding_source_required"), bool)
            and isinstance(record.get("review_reference"), str)
            and bool(record["review_reference"].strip())
            for record in approvals
        )
    )
    return complete, approvals, _sha256(approvals_path)


def stage_linux_runtime(
    runtime: Path,
    collect_toc: Path,
    *,
    repository_root: Path = REPOSITORY_ROOT,
) -> dict[str, Any]:
    """Stage a self-describing legal corpus from the exact Debian build inputs."""
    policy = verify_build_environment(repository_root)
    entries = _collect_entries(collect_toc)
    resolved_entries = [
        (*entry, _resolve_collect_destination(runtime, entry[0])) for entry in entries
    ]
    relative_runtime_files = {
        path.relative_to(runtime).as_posix().lower()
        for path in runtime.rglob("*")
        if path.is_file() or path.is_symlink()
    }
    forbidden = sorted(
        name
        for name in relative_runtime_files
        if any(token in name for token in FORBIDDEN_RUNTIME_NAMES)
    )
    if forbidden:
        raise LicenseInventoryError(f"Forbidden GPL-only/unused Qt payload: {forbidden[0]}")
    native_packages, copyright_files = _native_debian_inventory(
        resolved_entries, repository_root, runtime
    )
    native_review_complete, native_approvals, approvals_digest = _native_approval_state(
        native_packages, repository_root
    )
    _copy_legal_corpus(repository_root, runtime)
    native_root = runtime / "licenses" / "Native-Debian"
    native_root.mkdir(parents=True, exist_ok=True)
    for package_name, source in copyright_files.items():
        destination = native_root / package_name / "copyright"
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    policy_bytes = (repository_root / "packaging" / "license-policy.json").read_bytes()
    inventory = {
        "application_version": policy["application_version"],
        "build_platform": "linux-debian-family",
        "cpython_version": policy["cpython_version"],
        "distributions": policy["distributions"],
        "format_version": 1,
        "legal_corpus_sha256": legal_corpus_digest(repository_root),
        "native_debian_packages": native_packages,
        "native_license_approvals": native_approvals,
        "native_license_approvals_sha256": approvals_digest,
        "native_license_review_complete": native_review_complete,
        "payload_sha256": runtime_payload_digest(runtime),
        "policy_sha256": hashlib.sha256(policy_bytes).hexdigest(),
        "qt_version": policy["qt_version"],
    }
    (runtime / RUNTIME_INVENTORY).write_text(
        json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    verify_runtime(runtime, repository_root=repository_root)
    return inventory


def verify_runtime(
    runtime: Path = DEFAULT_RUNTIME,
    *,
    repository_root: Path = REPOSITORY_ROOT,
    require_redistribution: bool = False,
) -> dict[str, Any]:
    """Verify that a runtime and its notice inventory are exact and complete."""
    policy = verify_repository_corpus(repository_root)
    for entry in LEGAL_ROOT_ENTRIES:
        path = runtime / entry
        if path.is_symlink() or not path.exists():
            raise LicenseInventoryError(f"Frozen legal material is missing: {entry}")
    inventory = _load_json(runtime / RUNTIME_INVENTORY)
    expected = {
        "application_version": policy["application_version"],
        "cpython_version": policy["cpython_version"],
        "distributions": policy["distributions"],
        "format_version": 1,
        "legal_corpus_sha256": legal_corpus_digest(repository_root),
        "policy_sha256": _sha256(repository_root / "packaging" / "license-policy.json"),
        "qt_version": policy["qt_version"],
    }
    for key, value in expected.items():
        if inventory.get(key) != value:
            raise LicenseInventoryError(f"Frozen legal inventory does not match policy: {key}")
    if inventory.get("payload_sha256") != runtime_payload_digest(runtime):
        raise LicenseInventoryError(
            "Frozen legal inventory belongs to a different runtime payload."
        )
    if inventory.get("legal_corpus_sha256") != legal_corpus_digest(runtime):
        raise LicenseInventoryError("Frozen legal corpus differs from approved repository inputs.")
    native_packages = inventory.get("native_debian_packages")
    if not isinstance(native_packages, list) or not native_packages:
        raise LicenseInventoryError("Frozen native-library license inventory is incomplete.")
    for package in native_packages:
        if not isinstance(package, dict) or not isinstance(package.get("binary_package"), str):
            raise LicenseInventoryError("Frozen native-library inventory has an invalid entry.")
        package_directory = package["binary_package"].replace(":", "_")
        notice = runtime / "licenses" / "Native-Debian" / package_directory / "copyright"
        if notice.is_symlink() or not notice.is_file() or notice.stat().st_size == 0:
            raise LicenseInventoryError(
                f"Frozen Debian copyright material is missing: {package['binary_package']}"
            )
    if require_redistribution:
        approvals_path = repository_root / "packaging" / "native-license-approvals.json"
        if inventory.get("native_license_approvals_sha256") != _sha256(approvals_path):
            raise LicenseInventoryError("Frozen native-license approvals are stale.")
        if inventory.get("native_license_review_complete") is not True:
            raise LicenseInventoryError(
                "Bundled native-library license/source review is incomplete for this runtime."
            )
    return inventory


def verify_source_bundle(
    release_directory: Path,
    *,
    repository_root: Path = REPOSITORY_ROOT,
    runtime: Path | None = None,
) -> Path:
    """Verify the side-by-side exact LGPL corresponding-source companion."""
    requirements_path = repository_root / "packaging" / "lgpl-source-requirements.json"
    requirements = _load_json(requirements_path)
    version = requirements["application_version"]
    archive = release_directory / f"hesiva-{version}-lgpl-corresponding-source.tar.xz"
    sidecar = archive.with_name(f"{archive.name}.sha256")
    if (
        archive.is_symlink()
        or not archive.is_file()
        or sidecar.is_symlink()
        or not sidecar.is_file()
    ):
        raise LicenseInventoryError("Exact LGPL corresponding-source companion is unavailable.")
    expected_sidecar = f"{_sha256(archive)}  {archive.name}\n"
    if sidecar.read_text(encoding="ascii") != expected_sidecar:
        raise LicenseInventoryError("LGPL corresponding-source checksum is invalid.")
    expected_files = {
        f"sources/{entry['filename']}": (entry["sha256"], entry["size"])
        for entry in requirements["required_archives"]
    }
    expected_files["packaging/lgpl-source-requirements.json"] = (
        _sha256(requirements_path),
        requirements_path.stat().st_size,
    )
    relinking_path = repository_root / "RELINKING.md"
    expected_files["RELINKING.md"] = (_sha256(relinking_path), relinking_path.stat().st_size)
    if runtime is not None:
        inventory = verify_runtime(
            runtime,
            repository_root=repository_root,
            require_redistribution=True,
        )
        for approval in inventory["native_license_approvals"]:
            if not approval["corresponding_source_required"]:
                continue
            required_fields = (
                "source_archive_filename",
                "source_archive_sha256",
                "source_archive_size",
            )
            if not all(field in approval for field in required_fields):
                raise LicenseInventoryError(
                    "Native source approval lacks exact archive identity: "
                    f"{approval['source_package']}"
                )
            expected_files[f"native-sources/{approval['source_archive_filename']}"] = (
                approval["source_archive_sha256"],
                approval["source_archive_size"],
            )
    seen: dict[str, str] = {}
    with tarfile.open(archive, mode="r:xz") as source:
        for member in source:
            pure_name = PurePosixPath(member.name)
            if pure_name.is_absolute() or ".." in pure_name.parts:
                raise LicenseInventoryError("LGPL source bundle contains an unsafe path.")
            if not member.isfile():
                raise LicenseInventoryError("LGPL source bundle may contain regular files only.")
            if member.name not in expected_files:
                raise LicenseInventoryError(f"Unexpected LGPL source bundle member: {member.name}")
            if member.size != expected_files[member.name][1]:
                raise LicenseInventoryError(
                    f"LGPL source bundle member size is invalid: {member.name}"
                )
            extracted = source.extractfile(member)
            if extracted is None:
                raise LicenseInventoryError("LGPL source bundle member is unreadable.")
            digest = hashlib.sha256()
            while chunk := extracted.read(1024 * 1024):
                digest.update(chunk)
            seen[member.name] = digest.hexdigest()
    expected_hashes = {name: value[0] for name, value in expected_files.items()}
    if seen != expected_hashes:
        missing = sorted(set(expected_files) - set(seen))
        if missing:
            raise LicenseInventoryError(f"LGPL source bundle member is missing: {missing[0]}")
        mismatched = sorted(name for name in expected_files if seen[name] != expected_hashes[name])
        raise LicenseInventoryError(
            f"LGPL source bundle member checksum is invalid: {mismatched[0]}"
        )
    return archive


def build_source_bundle(
    source_directory: Path,
    release_directory: Path,
    *,
    repository_root: Path = REPOSITORY_ROOT,
    runtime: Path | None = None,
) -> Path:
    """Build a deterministic companion from pre-downloaded official sources."""
    requirements_path = repository_root / "packaging" / "lgpl-source-requirements.json"
    requirements = _load_json(requirements_path)
    source_members: list[tuple[str, Path]] = []
    for entry in requirements["required_archives"]:
        path = source_directory / entry["filename"]
        if path.is_symlink() or not path.is_file():
            raise LicenseInventoryError(f"Official LGPL source archive is unavailable: {path.name}")
        if path.stat().st_size != entry["size"] or _sha256(path) != entry["sha256"]:
            raise LicenseInventoryError(
                f"Official LGPL source archive does not match Qt metadata: {path.name}"
            )
        source_members.append((f"sources/{path.name}", path))
    if runtime is not None:
        inventory = verify_runtime(
            runtime,
            repository_root=repository_root,
            require_redistribution=True,
        )
        for approval in inventory["native_license_approvals"]:
            if not approval["corresponding_source_required"]:
                continue
            filename = approval.get("source_archive_filename")
            path = source_directory / filename if isinstance(filename, str) else None
            if (
                path is None
                or path.is_symlink()
                or not path.is_file()
                or path.stat().st_size != approval.get("source_archive_size")
                or _sha256(path) != approval.get("source_archive_sha256")
            ):
                raise LicenseInventoryError(
                    "Reviewed native corresponding source is unavailable: "
                    f"{approval['source_package']}"
                )
            source_members.append((f"native-sources/{path.name}", path))
    source_members = sorted(dict(source_members).items())
    release_directory.mkdir(parents=True, exist_ok=True)
    version = requirements["application_version"]
    archive = release_directory / f"hesiva-{version}-lgpl-corresponding-source.tar.xz"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{archive.name}.", suffix=".tmp", dir=release_directory
    )
    os.close(descriptor)
    temporary = Path(temporary_name)

    def add_bytes(output: tarfile.TarFile, name: str, payload: bytes, mode: int = 0o644) -> None:
        info = tarfile.TarInfo(name)
        info.size = len(payload)
        info.mode = mode
        info.mtime = 0
        info.uid = 0
        info.gid = 0
        info.uname = ""
        info.gname = ""
        output.addfile(info, io.BytesIO(payload))

    def add_path(output: tarfile.TarFile, name: str, path: Path) -> None:
        info = tarfile.TarInfo(name)
        info.size = path.stat().st_size
        info.mode = 0o644
        info.mtime = 0
        info.uid = 0
        info.gid = 0
        info.uname = ""
        info.gname = ""
        with path.open("rb") as source:
            output.addfile(info, source)

    try:
        with tarfile.open(temporary, mode="w:xz", format=tarfile.PAX_FORMAT) as output:
            for name, path in source_members:
                add_path(output, name, path)
            add_bytes(
                output,
                "packaging/lgpl-source-requirements.json",
                requirements_path.read_bytes(),
            )
            add_bytes(output, "RELINKING.md", (repository_root / "RELINKING.md").read_bytes())
        os.replace(temporary, archive)
    finally:
        temporary.unlink(missing_ok=True)
    sidecar = archive.with_name(f"{archive.name}.sha256")
    sidecar.write_text(f"{_sha256(archive)}  {archive.name}\n", encoding="ascii")
    verify_source_bundle(release_directory, repository_root=repository_root)
    return archive


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("verify-policy")
    stage = subparsers.add_parser("stage-linux")
    stage.add_argument("--runtime", type=Path, default=DEFAULT_RUNTIME)
    stage.add_argument("--collect-toc", type=Path, default=DEFAULT_COLLECT_TOC)
    verify = subparsers.add_parser("verify-runtime")
    verify.add_argument("--runtime", type=Path, default=DEFAULT_RUNTIME)
    source = subparsers.add_parser("verify-source-bundle")
    source.add_argument("--release-directory", type=Path, default=REPOSITORY_ROOT / "dist")
    source.add_argument("--runtime", type=Path)
    build_source = subparsers.add_parser("build-source-bundle")
    build_source.add_argument("--source-directory", type=Path, required=True)
    build_source.add_argument("--release-directory", type=Path, default=REPOSITORY_ROOT / "dist")
    build_source.add_argument("--runtime", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        if arguments.command == "verify-policy":
            policy = verify_build_environment()
            print(f"Verified exact legal policy for Qt {policy['qt_version']}.")
        elif arguments.command == "stage-linux":
            inventory = stage_linux_runtime(arguments.runtime, arguments.collect_toc)
            print(
                "Staged exact Linux legal corpus for "
                f"{len(inventory['native_debian_packages'])} Debian packages."
            )
        elif arguments.command == "verify-runtime":
            inventory = verify_runtime(arguments.runtime, require_redistribution=True)
            print(
                "Verified frozen legal inventory for "
                f"{len(inventory['native_debian_packages'])} Debian packages."
            )
        elif arguments.command == "verify-source-bundle":
            archive = verify_source_bundle(
                arguments.release_directory,
                runtime=arguments.runtime,
            )
            print(f"Verified LGPL corresponding source: {archive}")
        else:
            archive = build_source_bundle(
                arguments.source_directory,
                arguments.release_directory,
                runtime=arguments.runtime,
            )
            print(f"Built verified LGPL corresponding source: {archive}")
    except (LicenseInventoryError, OSError, UnicodeError, tarfile.TarError) as error:
        print(f"License inventory verification failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
