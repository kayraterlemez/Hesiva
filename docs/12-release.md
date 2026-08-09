# Hesiva Release / Packaging Foundation

## Status

This document describes the repeatable packaging foundation for Hesiva 0.1.0. It does not declare
Version 1 final or released.

Linux x86_64 is the primary target. Windows x86_64 is secondary and must be built and validated on
Windows. PyInstaller cross-compilation from Linux is not supported.

## Packaging Architecture

The V1 foundation uses PyInstaller in `onedir` mode:

```text
src/hesiva/__main__.py
        ↓
hesiva.application.main()
        ↓
dist/Hesiva/Hesiva
        └── _internal/
```

`onedir` keeps Qt plugins and native libraries inspectable, avoids mandatory one-file extraction at
every startup, and gives failures a reviewable filesystem layout. The spec is
`packaging/Hesiva.spec`; build-only helpers are in `packaging/pyinstaller_support.py`.

The release artifact includes:

- Hesiva application modules and required Python dependencies
- PySide6 Qt Core/Gui/Widgets, platform, print, and image runtime components
- SQLAlchemy, SQLite, Alembic, and Argon2 native/runtime components
- package metadata generated from `pyproject.toml`
- Alembic `env.py`, `script.py.mako`, and `versions/`

It excludes tests, pytest, Ruff, Git data, caches, source documentation, synthetic legacy fixtures,
and user/private data. The optional Qt TIFF image plugin is excluded because Hesiva does not load
TIFF content and the development host does not provide its required ABI. Other Qt plugin families
remain until clean-machine testing proves a narrower set safe.

## Version Contract

`pyproject.toml` `project.version` is the authoritative version workflow. Runtime code reads the
installed distribution metadata through `hesiva.version.get_application_version()`, with the
existing source-tree fallback to the same `pyproject.toml` field.

The build helper verifies that installed `hesiva` metadata matches `pyproject.toml`, then bundles
that metadata. If the version changed after environment installation, reinstall before building:

```bash
.venv/bin/python -m pip install --no-build-isolation -e ".[dev]"
```

The current version remains 0.1.0. There is no separate build identifier.

## Linux Build

Prerequisites:

- Linux x86_64
- Python 3.13 or newer
- project virtual environment with the `dev` extra
- PyInstaller 6.x as constrained by `pyproject.toml`

Prepare the environment:

```bash
python3.13 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
```

Run the normal release order and clean build:

```bash
scripts/build_linux.sh
```

This runs `pytest`, `ruff check .`, `ruff format --check .`, and `git diff --check` before invoking
PyInstaller with `--clean --noconfirm`. The output is:

```text
dist/Hesiva/Hesiva
dist/Hesiva/_internal/
```

For diagnosis after source validation has already passed, the explicit build-only path is:

```bash
scripts/build_linux.sh --build-only
```

Build outputs are ignored by Git. Cleaning `build/` and `dist/` is safe only when they are confirmed
to be this repository's generated build roots; a new PyInstaller `--clean` build recreates the
needed content.

## Packaged Smoke

Run:

```bash
scripts/smoke_packaged_linux.sh
```

The script first launches the actual release executable offscreen with isolated `HOME` and
`XDG_DATA_HOME` and verifies that it reaches first-run without writing `config.json` prematurely.
It then builds a separate console smoke artifact under `build/packaged-smoke-dist/`. That
development-only artifact exercises:

1. fresh Alembic database creation and schema validation
2. actual first-password, setup-choice, login, and password-change dialogs/services
3. customer creation, debt creation, summary balance, and MainWindow loading
4. PDF generation through the production report renderer
5. backup, post-backup mutation, and pairwise database/config restore
6. Settings and About version display
7. production legacy import using a tests-only synthetic `.exa`
8. POSIX data/config/database permissions
9. reopen/login and clean context shutdown

The smoke compares a digest of every file in `dist/Hesiva` before and after execution. User state is
created only inside the temporary XDG tree, and the temporary tree is removed afterward. There is no
hidden smoke/debug entry point in the production executable.

## User Data and Uninstall Safety

Packaging does not change runtime data paths:

```text
Linux:  $XDG_DATA_HOME/hesiva
        ~/.local/share/hesiva (fallback)
Windows: %LOCALAPPDATA%/Hesiva
Database: hesiva.db
Configuration: config.json
```

The install/executable directory is immutable application content. It must never contain customer
data, credentials, reports, backups, or imported source files. Future package uninstall scripts must
not delete per-user Hesiva data; cleanup remains an explicit user decision.

## Portable Linux Archive

After a successful build and smoke, a portable archive may be generated from the onedir runtime:

```bash
tar -czf dist/Hesiva-0.1.0-linux-x86_64.tar.gz -C dist Hesiva
```

This is the runtime directory only, not the repository. It is a portable candidate, not a claim of
compatibility with every Linux distribution.

## Linux Portability Boundary

PyInstaller Linux artifacts inherit the build host's glibc symbol baseline. The spec substitutes
baseline x86-64 variants when a modern host's glibc-hwcaps loader selects x86-64-v3 libraries; this
avoids making the bundle itself require an AVX-class CPU and is necessary for the Intel i3-540
target. It does not make a glibc 2.43 host build compatible with older distributions.

Before release, rebuild on the oldest supported Linux/glibc baseline and validate on:

- the chosen production distribution and desktop environment
- Intel i3-540-class CPU, 4 GB RAM, SSD, and 1366x768 display
- X11/XCB startup and, if intended, the selected Wayland environment
- Turkish text, PDF output, and an available printer
- install/update/remove with per-user data preservation

No “all Linux distributions” claim is made.

## Desktop Integration and Debian Package

No authoritative application icon exists in the repository. The frozen UI PDF is a visual reference,
not a source icon asset, and is not extracted or regenerated for packaging. Desktop icon metadata is
therefore intentionally not invented.

A Debian package is also deferred because Debian control metadata needs an authoritative Maintainer
identity, while the repository does not define one. The repository's `LICENSE` is empty and the
license decision remains unresolved. No license, maintainer, publisher, website, or copyright claim
is inferred.

Once those decisions exist, the intended layout is conventional and keeps mutable data outside the
package:

```text
/opt/hesiva/             onedir runtime
/usr/bin/hesiva          launcher or symlink
/usr/share/applications/hesiva.desktop
/usr/share/icons/...     authoritative Hesiva icon
```

Ordinary package removal must leave each user's XDG Hesiva directory untouched.

## Windows Build Foundation

The same spec uses platform-specific PyInstaller hooks and names the executable `Hesiva`; on Windows
the expected result is `dist\\Hesiva\\Hesiva.exe`. Build in a clean Windows x86_64 environment:

```powershell
py -3.13 -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\python -m pytest
.venv\Scripts\python -m ruff check .
.venv\Scripts\python -m ruff format --check .
.venv\Scripts\python -m PyInstaller --clean --noconfirm packaging\Hesiva.spec
```

Windows has not been built or validated by the Linux milestone. A clean Windows VM test must verify
the qwindows plugin, `%LOCALAPPDATA%\\Hesiva`, first-run/login/password change, business CRUD,
Turkish text, PDF and native print dialog, backup/restore, synthetic legacy import, Settings/About
version, reopen, clean shutdown, and install/remove data preservation. Installer technology is a
later Windows-specific decision; NSIS or Inno Setup is not selected here.

## Release Gate

Before any stable V1 claim:

- full tests, Ruff, and `git diff --check` pass
- a clean `onedir` build succeeds
- packaged smoke succeeds without install-directory writes
- no `ldd` dependency is unresolved in the final onedir tree
- a compatible old-glibc build and representative-hardware check pass
- native Windows build/smoke passes before Windows support is claimed
- final icon, license, maintainer, and distribution metadata decisions are resolved
- `.deb` install/remove and user-data preservation are tested if Debian packaging is selected
- UI, printer, PDF, backup/restore, import, and recovery rehearsals pass on target systems

Generated `build/`, `dist/`, `.deb`, and `.tar.gz` outputs remain untracked. V1 is not final until
these remaining release decisions and target-environment checks are completed.
