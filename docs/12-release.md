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
TIFF content and the development host does not provide its required ABI. The GPL-only Qt Virtual
Keyboard module, its unused QML/Quick dependency cluster, and optional GNU Readline are excluded
because the Widgets application uses none of them. Other Qt plugin families remain until
clean-machine testing proves a narrower set safe.

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

## Release Identity and License

The locked release identity is:

```text
Product: Hesiva
Python/distribution package: hesiva
Debian package: hesiva
Maintainer: Kayra Terlemez <kayraterlemez2@gmail.com>
License: MIT
Master icon: assets/hesiva-icon.png
```

`LICENSE` contains the standard MIT text with `Copyright (c) 2026 Kayra Terlemez`.
`pyproject.toml` identifies the same SPDX license and includes `LICENSE` in distribution metadata.
About uses the concise **MIT Lisansı** label; it does not duplicate the legal text or add a
publisher, support URL, or website.

MIT describes Hesiva's own source, not the complete frozen distribution. The authoritative
third-party component, LGPL and release-notice audit is `docs/13-third-party-licensing.md`. A release
artifact must contain Hesiva's `LICENSE`, `THIRD_PARTY_NOTICES.md`, the exact authoritative license
corpus, and the reviewed Qt/PySide/Shiboken corresponding-source/source-offer and relinking
information. The current artifact does not yet meet that requirement and is not distributable.

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

Immediately before PyInstaller starts, the build helper records a SHA-256 digest over the complete
production source/resource/spec input set and invalidates any prior provenance record. After the
build, it accepts the output only if those inputs are unchanged, then records both that source
digest and a digest covering every runtime file, mode, and symbolic-link target in
`dist/Hesiva.provenance.json`. This ignored build artifact is integrity/provenance metadata, not a
signature. Release staging and smoke validation reject a missing record, source drift, or runtime
drift; they therefore cannot silently reuse an old `dist/Hesiva` after the repository changes.

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
The offscreen Qt backing-store diagnostic must confirm that a top-level UI surface was actually
created; a process that merely remains alive after database setup is not sufficient.
The database created by that production executable must pass SQLite integrity checking, contain the
complete current model table set, and carry the current Alembic head. The production tree is also
checked against its build provenance before and after smoke execution.
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

`assets/hesiva-icon.png` is the immutable 2000×2000 RGBA master. Run:

```bash
scripts/generate_icons.sh
```

to deterministically create 16, 32, 48, 64, 128, 256, and 512 pixel hicolor PNGs plus the
multi-resolution Windows-preparation ICO in `packaging/icons/`. The PNG is bundled for the Qt
application/window icon and installed separately in the freedesktop hicolor hierarchy. The Linux
desktop entry is `packaging/linux/hesiva.desktop` and resolves `Exec=hesiva`, `Icon=hesiva`, and
`Terminal=false` without a developer-specific path.

The Debian build uses the existing PyInstaller `onedir` output and this conventional immutable
layout:

```text
/opt/hesiva/             complete PyInstaller onedir runtime
/usr/bin/hesiva          POSIX launcher to /opt/hesiva/Hesiva
/usr/share/applications/hesiva.desktop
/usr/share/icons/hicolor/<size>x<size>/apps/hesiva.png
/usr/share/doc/hesiva/LICENSE
```

On an amd64 build host with `dpkg-deb`, run:

```bash
scripts/build_deb.sh
```

The script obtains the version through `hesiva.version.get_application_version()`, requires the
existing `onedir` tree to match both its recorded source and runtime digests, uses a private
temporary package root, and writes `dist/hesiva_<version>_amd64.deb`. It verifies the copied
`/opt/hesiva` tree again before publication, so a missing, stale, concurrently changed, or partially
copied runtime fails closed with an instruction to rebuild rather than being silently packaged.
Current control metadata uses package `hesiva`, architecture `amd64`, section `utils`, priority
`optional`, the locked maintainer, and currently declares only `libc6`/`libgl1` runtime
dependencies. That dependency declaration is not yet release-validated: inspection of the frozen
Qt GUI/XCB libraries on the development host still shows external EGL, font, X11, xkbcommon, GLib,
and XCB-family native requirements. Their authoritative Debian package mapping must be derived and
tested on the selected clean release baseline before the `.deb` is distributable; PyInstaller
bundling must not be treated as proof that these host libraries are present. The helper never
installs build tools or the package automatically.
When `dpkg-deb` is unavailable, `scripts/build_deb.sh --stage-only /absolute/new/directory` may be
used to inspect the exact package root without fabricating a `.deb`; the destination must not exist.

Install and remove on a compatible test system with the normal Debian tools:

```bash
sudo apt install ./dist/hesiva_0.1.0_amd64.deb
sudo apt remove hesiva
```

There are no package lifecycle scripts. Ordinary removal or purge removes package-managed runtime,
launcher, desktop, icon, and license files only. It neither enumerates home directories nor removes
`$XDG_DATA_HOME/hesiva` or `~/.local/share/hesiva`; reinstall and upgrade therefore preserve the
user-owned database, configuration, and backups.

This development host does not currently provide `dpkg-deb` or a disposable Debian install root.
Consequently the build helper and package-root mappings are reviewable and tested, while actual
`.deb` construction, `dpkg-deb --info`/`--contents`, and isolated install/remove/reinstall remain a
release-environment gate. No system package is installed automatically to bypass that gate.

Any `.deb` produced from the current openSUSE Tumbleweed/glibc 2.43 runtime is a
development/validation package only. Wrapping the runtime in Debian metadata does not lower its
glibc symbol requirements or establish universal Debian/Ubuntu compatibility. The final package
must be rebuilt and tested on the selected older supported glibc baseline.

## Windows Build Foundation

The same spec uses platform-specific PyInstaller hooks and names the executable `Hesiva`; on Windows
the expected result is `dist\\Hesiva\\Hesiva.exe`. Build in a clean Windows x86_64 environment:

```powershell
py -3.13 -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\python -m pytest
.venv\Scripts\python -m ruff check .
.venv\Scripts\python -m ruff format --check .
.venv\Scripts\python packaging\artifact_provenance.py invalidate
$sourceDigest = .venv\Scripts\python packaging\artifact_provenance.py source-digest
.venv\Scripts\python -m PyInstaller --clean --noconfirm packaging\Hesiva.spec
.venv\Scripts\python packaging\artifact_provenance.py record `
    --expected-source-sha256 $sourceDigest
.venv\Scripts\python packaging\artifact_provenance.py verify
```

This is the same source/runtime provenance contract used by the Linux helper. It includes the
Windows `packaging\icons\hesiva.ico`, Linux hicolor release icons, desktop/package metadata, MIT
license, application sources/resources, spec/support code, and project metadata. Consequently an
ICO/resource change or source change during the Windows build invalidates publication. The
provenance record establishes local build identity and integrity only; it is not Authenticode and
does not replace a future Windows signing decision.

Windows has not been built or validated by the Linux milestone. A clean Windows VM test must verify
the qwindows plugin, `%LOCALAPPDATA%\\Hesiva`, first-run/login/password change, business CRUD,
Turkish text, PDF and native print dialog, backup/restore, synthetic legacy import, Settings/About
version, reopen, clean shutdown, and install/remove data preservation. Installer technology is a
later Windows-specific decision; NSIS or Inno Setup is not selected here.

`packaging/icons/hesiva.ico` prepares 16, 24, 32, 48, 64, 128, and 256 pixel frames and is selected
by the Windows branch of `packaging/Hesiva.spec`. This is configuration preparation only, not a
claim that the Windows executable icon has been validated.

## Release Gate

Before any stable V1 claim:

- full tests, Ruff, and `git diff --check` pass
- a clean `onedir` build succeeds
- packaged smoke succeeds without install-directory writes
- no `ldd` dependency is unresolved in the final onedir tree
- a compatible old-glibc build and representative-hardware check pass
- native Windows build/smoke passes before Windows support is claimed
- authoritative icon, MIT license, maintainer, and distribution metadata remain consistent
- `.deb` is built and inspected with `dpkg-deb` on a compatible Debian-family build host
- `.deb` install/remove/reinstall and user-data preservation are tested in a disposable environment
- UI, printer, PDF, backup/restore, import, and recovery rehearsals pass on target systems

Generated `build/`, `dist/`, `.deb`, and `.tar.gz` outputs remain untracked. Source desktop entries,
packaging scripts, the master icon, generated release-resource icons, and their tests remain tracked.
V1 is not final until the older-glibc build and target-environment checks are completed.
