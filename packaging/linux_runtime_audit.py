"""Validate the native dependency closure of a frozen Linux onedir runtime."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUNTIME = REPOSITORY_ROOT / "dist" / "Hesiva"

# These stable platform ABIs deliberately remain host-provided. The Debian package
# names that own their resolved paths are derived on the Debian-family build host.
ALLOWED_HOST_SONAMES = frozenset(
    {
        "ld-linux-x86-64.so.2",
        "libEGL.so.1",
        "libGL.so.1",
        "libGLX.so.0",
        "libGLdispatch.so.0",
        "libbrotlicommon.so.1",
        "libbrotlidec.so.1",
        "libbz2.so.1",
        "libc.so.6",
        "libcrypto.so.3",
        "libdl.so.2",
        "libdrm.so.2",
        "libhogweed.so.6",
        "liblzma.so.5",
        "libm.so.6",
        "libnettle.so.8",
        "libpng16.so.16",
        "libpthread.so.0",
        "libresolv.so.2",
        "libsqlite3.so.0",
        "libssl.so.3",
        "libwayland-client.so.0",
        "libwayland-cursor.so.0",
        "libwayland-egl.so.1",
        "libxcb.so.1",
        "libz.so.1",
        "libzstd.so.1",
    }
)

REQUIRED_RUNTIME_PATHS = (
    Path("Hesiva"),
    Path("_internal/libxcb-cursor.so.0"),
    Path("_internal/libcups.so.2"),
    Path("_internal/PySide6/Qt/plugins/platforms/libqxcb.so"),
    Path("_internal/PySide6/Qt/plugins/platforms/libqwayland.so"),
    Path("_internal/PySide6/Qt/plugins/printsupport/libcupsprintersupport.so"),
)

FORBIDDEN_PATH_PATTERNS = (
    re.compile(r"virtualkeyboard", re.IGNORECASE),
    re.compile(r"(?:^|/)libqt6qml(?:meta|models|workerscript)?\.so", re.IGNORECASE),
    re.compile(r"(?:^|/)libqt6quick\.so", re.IGNORECASE),
    re.compile(r"(?:^|/)qt6qml(?:meta|models|workerscript)?\.dll$", re.IGNORECASE),
    re.compile(r"(?:^|/)qt6quick\.dll$", re.IGNORECASE),
    re.compile(r"(?:^|/)libreadline(?:\.so|$)", re.IGNORECASE),
    re.compile(r"(?:^|/)readline[^/]*\.(?:so|pyd)$", re.IGNORECASE),
    re.compile(r"(?:^|/)libqtiff\.(?:so|dll)", re.IGNORECASE),
)

NEEDED_PATTERN = re.compile(r"\(NEEDED\).*\[([^]]+)]")
SEARCH_PATH_PATTERN = re.compile(r"\((RPATH|RUNPATH)\).*\[([^]]*)]")
LDD_RESOLVED_PATTERN = re.compile(r"^\s*(\S+)\s+=>\s+(/\S+)\s+\(0x[0-9a-fA-F]+\)\s*$")
LDD_MISSING_PATTERN = re.compile(r"^\s*(\S+)\s+=>\s+not found\s*$")
LDD_DIRECT_PATTERN = re.compile(r"^\s*(/\S+)\s+\(0x[0-9a-fA-F]+\)\s*$")
PACKAGE_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9+.-]*$")


class RuntimeAuditError(RuntimeError):
    """Raised when a frozen runtime violates the Linux release policy."""


@dataclass(frozen=True, slots=True)
class Resolution:
    soname: str
    path: str | None
    location: str


@dataclass(frozen=True, slots=True)
class ElfRecord:
    path: str
    needed: tuple[str, ...]
    rpath: tuple[str, ...]
    runpath: tuple[str, ...]
    resolutions: tuple[Resolution, ...]


@dataclass(frozen=True, slots=True)
class RuntimeReport:
    runtime: str
    elf_files: tuple[ElfRecord, ...]
    bundled_sonames: tuple[str, ...]
    host_sonames: tuple[str, ...]
    host_paths: tuple[tuple[str, str], ...]


def _run(command: list[str], *, environment: dict[str, str] | None = None) -> str:
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            env=environment,
        )
    except OSError as error:
        raise RuntimeAuditError(f"Required release tool could not run: {command[0]}") from error
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or f"status {result.returncode}"
        raise RuntimeAuditError(f"{command[0]} failed for {command[-1]}: {detail}")
    return result.stdout


def _is_elf(path: Path) -> bool:
    try:
        with path.open("rb") as source:
            return source.read(4) == b"\x7fELF"
    except OSError as error:
        raise RuntimeAuditError(f"Frozen runtime file is unreadable: {path}") from error


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _inspect_dynamic_section(
    path: Path,
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    output = _run(["readelf", "--dynamic", "--wide", str(path)])
    needed: list[str] = []
    rpath: list[str] = []
    runpath: list[str] = []
    for line in output.splitlines():
        if match := NEEDED_PATTERN.search(line):
            needed.append(match.group(1))
            continue
        if match := SEARCH_PATH_PATTERN.search(line):
            values = tuple(value for value in match.group(2).split(":") if value)
            if match.group(1) == "RPATH":
                rpath.extend(values)
            else:
                runpath.extend(values)
    return tuple(needed), tuple(rpath), tuple(runpath)


def _parse_ldd(output: str, *, runtime_root: Path) -> tuple[Resolution, ...]:
    resolutions: list[Resolution] = []
    for line in output.splitlines():
        if not line.strip() or line.lstrip().startswith("linux-vdso.so"):
            continue
        if match := LDD_MISSING_PATTERN.match(line):
            resolutions.append(Resolution(match.group(1), None, "missing"))
            continue
        if match := LDD_RESOLVED_PATTERN.match(line):
            soname, raw_path = match.groups()
        elif match := LDD_DIRECT_PATTERN.match(line):
            raw_path = match.group(1)
            soname = Path(raw_path).name
        else:
            # ldd may print non-dependency diagnostics. They are not silently
            # accepted when a DT_NEEDED entry is missing from parsed output.
            continue
        resolved_path = Path(raw_path).resolve(strict=False)
        location = "bundled" if _is_within(resolved_path, runtime_root) else "host"
        resolutions.append(Resolution(soname, str(resolved_path), location))
    return tuple(resolutions)


def _inspect_resolutions(path: Path, *, runtime_root: Path) -> tuple[Resolution, ...]:
    environment = {
        **os.environ,
        "LC_ALL": "C",
        # PyInstaller's Linux bootloader prepends this directory before it
        # transfers control to Python. Suppress a developer's custom value.
        "LD_LIBRARY_PATH": str(runtime_root / "_internal"),
    }
    output = _run(["ldd", str(path)], environment=environment)
    return _parse_ldd(output, runtime_root=runtime_root)


def _validate_tree(runtime_root: Path) -> None:
    if runtime_root.is_symlink() or not runtime_root.is_dir():
        raise RuntimeAuditError(f"Frozen runtime directory is unavailable: {runtime_root}")
    resolved_root = runtime_root.resolve(strict=True)
    for path in sorted(runtime_root.rglob("*")):
        relative = path.relative_to(runtime_root).as_posix()
        if any(pattern.search(relative) for pattern in FORBIDDEN_PATH_PATTERNS):
            raise RuntimeAuditError(f"Forbidden release component is present: {relative}")
        if path.is_symlink():
            try:
                target = path.resolve(strict=True)
            except OSError as error:
                raise RuntimeAuditError(
                    f"Frozen runtime contains a dangling link: {relative}"
                ) from error
            if not _is_within(target, resolved_root):
                raise RuntimeAuditError(f"Frozen runtime link escapes the onedir tree: {relative}")
    for relative in REQUIRED_RUNTIME_PATHS:
        path = runtime_root / relative
        if not path.is_file():
            raise RuntimeAuditError(f"Required frozen runtime component is unavailable: {relative}")


def audit_runtime(runtime_path: Path = DEFAULT_RUNTIME) -> RuntimeReport:
    """Inspect every ELF using the same library root as the PyInstaller bootloader."""
    runtime_root = runtime_path.resolve(strict=False)
    _validate_tree(runtime_root)
    if shutil.which("readelf") is None or shutil.which("ldd") is None:
        raise RuntimeAuditError("Linux dependency auditing requires both readelf and ldd.")

    records: list[ElfRecord] = []
    bundled_sonames: set[str] = set()
    host_paths: set[tuple[str, str]] = set()
    unresolved: list[tuple[str, str]] = []
    for path in sorted(runtime_root.rglob("*")):
        if not path.is_file() or not _is_elf(path):
            continue
        needed, rpath, runpath = _inspect_dynamic_section(path)
        directly_needed = set(needed)
        resolutions = _inspect_resolutions(path, runtime_root=runtime_root)
        resolved_names = {resolution.soname for resolution in resolutions}
        for resolution in resolutions:
            if resolution.location == "missing":
                unresolved.append((path.relative_to(runtime_root).as_posix(), resolution.soname))
            elif resolution.soname not in directly_needed:
                # ldd reports the recursive closure. It remains useful for
                # detecting an unresolved transitive edge, but Debian Depends
                # must be derived only from direct DT_NEEDED edges. Every
                # bundled ELF is inspected separately, so a host edge of a
                # bundled transitive library is still captured as a direct
                # edge when that ELF becomes the current record.
                continue
            elif resolution.location == "bundled":
                bundled_sonames.add(resolution.soname)
            elif resolution.path is not None:
                host_paths.add((resolution.soname, resolution.path))
        missing_from_ldd = set(needed) - resolved_names
        unresolved.extend(
            (path.relative_to(runtime_root).as_posix(), soname)
            for soname in sorted(missing_from_ldd)
        )
        records.append(
            ElfRecord(
                path=path.relative_to(runtime_root).as_posix(),
                needed=needed,
                rpath=rpath,
                runpath=runpath,
                resolutions=resolutions,
            )
        )

    if not records:
        raise RuntimeAuditError("Frozen runtime contains no ELF files.")
    if unresolved:
        detail = ", ".join(f"{consumer}: {soname}" for consumer, soname in unresolved[:10])
        raise RuntimeAuditError(f"Frozen runtime has unresolved ELF dependencies: {detail}")

    host_sonames = {soname for soname, _path in host_paths}
    unexpected_host = host_sonames - ALLOWED_HOST_SONAMES
    if unexpected_host:
        raise RuntimeAuditError(
            "Frozen runtime introduced unreviewed host dependencies: "
            + ", ".join(sorted(unexpected_host))
        )
    required_bundled = {"libxcb-cursor.so.0", "libcups.so.2"}
    missing_bundled = required_bundled - bundled_sonames
    if missing_bundled:
        raise RuntimeAuditError(
            "Required build-host-sensitive libraries are not resolved from the bundle: "
            + ", ".join(sorted(missing_bundled))
        )

    return RuntimeReport(
        runtime=str(runtime_root),
        elf_files=tuple(records),
        bundled_sonames=tuple(sorted(bundled_sonames)),
        host_sonames=tuple(sorted(host_sonames)),
        host_paths=tuple(sorted(host_paths)),
    )


def _installed_debian_owner(path: str) -> str:
    candidates: set[str] = set()
    for candidate_path in {path, str(Path(path).resolve(strict=False))}:
        result = subprocess.run(
            ["dpkg-query", "--search", candidate_path],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            continue
        output = result.stdout
        for line in output.splitlines():
            if ": " not in line:
                continue
            package_with_arch = line.rsplit(": ", maxsplit=1)[0]
            package = package_with_arch.split(":", maxsplit=1)[0]
            if PACKAGE_NAME_PATTERN.fullmatch(package):
                candidates.add(package)
    installed: list[str] = []
    for package in sorted(candidates):
        result = subprocess.run(
            ["dpkg-query", "--show", "--showformat=${db:Status-Status}", package],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and result.stdout.strip() == "installed":
            installed.append(package)
    if len(installed) != 1:
        raise RuntimeAuditError(
            f"Host library must have exactly one installed Debian package owner: {path}"
        )
    return installed[0]


def debian_dependencies(report: RuntimeReport) -> tuple[str, ...]:
    """Map the report's direct host paths to installed Debian binary packages."""
    if shutil.which("dpkg-query") is None:
        raise RuntimeAuditError(
            "Debian dependency generation requires dpkg-query on the build host."
        )
    return tuple(sorted({_installed_debian_owner(path) for _soname, path in report.host_paths}))


def _text_report(report: RuntimeReport, packages: tuple[str, ...] | None = None) -> str:
    runtime_root = Path(report.runtime)

    def display_path(resolution: Resolution) -> str:
        if resolution.path is None:
            return "(unresolved)"
        if resolution.location != "bundled":
            return resolution.path
        try:
            relative = Path(resolution.path).relative_to(runtime_root)
        except ValueError as error:
            raise RuntimeAuditError(
                "Bundled dependency resolution escaped the recorded runtime root."
            ) from error
        return f"<runtime>/{relative.as_posix()}"

    lines = [
        f"runtime root: {Path(report.runtime).name} (PyInstaller onedir)",
        f"ELF files: {len(report.elf_files)}",
        "bundled SONAMEs:",
        *(f"  {soname}" for soname in report.bundled_sonames),
        "host SONAMEs:",
        *(f"  {soname}\t{path}" for soname, path in report.host_paths),
    ]
    if packages is not None:
        lines.extend(("Debian direct dependencies:", *(f"  {package}" for package in packages)))
    lines.append("ELF resolution detail:")
    for record in report.elf_files:
        lines.extend(
            (
                f"  [{record.path}]",
                "    DT_NEEDED: " + (", ".join(record.needed) or "(none)"),
                "    RPATH: " + (": ".join(record.rpath) or "(none)"),
                "    RUNPATH: " + (": ".join(record.runpath) or "(none)"),
            )
        )
        lines.extend(
            f"    {resolution.soname}: {resolution.location} -> {display_path(resolution)}"
            for resolution in record.resolutions
        )
    return "\n".join(lines) + "\n"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("verify", "report", "debian-depends"))
    parser.add_argument("--runtime", type=Path, default=DEFAULT_RUNTIME)
    parser.add_argument("--json", action="store_true", help="Emit the full report as JSON.")
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _build_parser().parse_args(argv)
    try:
        report = audit_runtime(arguments.runtime)
        if arguments.command == "verify":
            print(
                f"Verified Linux ELF closure: {len(report.elf_files)} ELF files, "
                f"{len(report.host_sonames)} host SONAMEs."
            )
        elif arguments.command == "debian-depends":
            print(", ".join(debian_dependencies(report)))
        elif arguments.json:
            print(json.dumps(asdict(report), indent=2, sort_keys=True))
        else:
            packages = debian_dependencies(report) if shutil.which("dpkg-query") else None
            print(_text_report(report, packages), end="")
    except RuntimeAuditError as error:
        print(f"Linux runtime dependency audit failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
