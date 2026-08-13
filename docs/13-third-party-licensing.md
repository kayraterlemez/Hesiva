# Third-Party Licensing and Runtime Dependency Audit

## Status and scope

This is the engineering compliance record for the Hesiva 0.1.0 release candidate. It is not legal
advice. Hesiva's own source remains MIT licensed; every redistributed third-party component remains
under its own license.

The exact-version repository corpus is now `THIRD_PARTY_NOTICES.md`, `SOURCE-OFFER.md`,
`RELINKING.md`, and `licenses/`. `packaging/license-policy.json` locks the Python/Qt/PyInstaller
versions whose notices were reviewed. `packaging/license_inventory.py` rejects version drift,
stages the corpus, maps every native file copied from the Debian-family build host to authoritative
Debian copyright metadata, and binds the resulting inventory to the frozen payload digest.

The last Mint-built artifact predates this corpus and now correctly fails current source
provenance. It remains dependency evidence only. A fresh artifact must be built on the selected
Debian-family baseline so the exact native copyright corpus and runtime inventory can be
regenerated. Windows requires a separate native inventory.

## Python component inventory

`pyproject.toml` directly requires Alembic, argon2-cffi, PySide6 and SQLAlchemy. PyInstaller freezes
the following runtime components in the reference artifact:

| Component | Reference version | Distribution role | Authoritative license |
| --- | --- | --- | --- |
| CPython runtime and standard library | 3.13.14 | bundled | PSF License Agreement |
| PySide6, PySide6 Essentials/Addons | 6.11.1 | bundled | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only |
| Shiboken6 | 6.11.1 | bundled | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only |
| SQLAlchemy | 2.0.51 | bundled | MIT |
| Alembic | 1.19.0 | bundled | MIT |
| argon2-cffi | 25.1.0 | bundled | MIT |
| argon2-cffi-bindings | 25.1.0 | bundled | MIT; vendored Argon2/encoding/BLAKE2 code is CC0 |
| cffi / `_cffi_backend` | 2.1.1 | bundled transitively | MIT-0 |
| greenlet | 3.5.4 | bundled transitively | MIT AND PSF-2.0 |
| Mako | 1.4.1 | bundled transitively through Alembic | MIT |
| MarkupSafe | 3.0.3 | bundled transitively through Mako | BSD-3-Clause |
| packaging | 26.3 | bundled through Alembic/setuptools paths | Apache-2.0 OR BSD-2-Clause |
| Pygments | 2.20.0 | bundled through Alembic | BSD-2-Clause |
| setuptools and its actually frozen vendors | 84.0.0 | bundled through runtime hook | MIT plus each vendored component's license |
| typing_extensions | 4.16.0 | bundled | PSF-2.0 |
| PyInstaller bootloader/runtime hooks | 6.22.0 | bootloader/hooks bundled | GPL-2.0-or-later with bootloader exception; runtime hooks Apache-2.0 |

The frozen setuptools vendor paths observed include importlib_metadata, zipp, more-itertools,
jaraco helpers, backports.tarfile, packaging, platformdirs, tomli and wheel. Their exact installed
license files are preserved under `licenses/Python-packages/setuptools-vendored/`; the release
version check prevents silently reusing them after an upgrade.

PyInstaller, pyinstaller-hooks-contrib and build tooling are otherwise build-time dependencies.
pytest, Ruff, iniconfig, pluggy, the test suite, fixtures and documentation are not frozen runtime
content. GNU Readline is optional interactive-console functionality that Hesiva does not use and is
explicitly excluded from the windowed build.

## Qt/PySide inventory and license result

Application imports require PySide QtCore, QtGui, QtWidgets, QtPdf and QtPrintSupport. Hook analysis
also includes QtNetwork and QtDBus. The fresh reference tree contains these PySide extensions:

```text
QtCore QtDBus QtGui QtNetwork QtPdf QtPrintSupport QtWidgets
```

It contains these Qt/ICU shared-library families:

```text
Qt6Core Qt6DBus Qt6EglFSDeviceIntegration Qt6EglFsKmsSupport Qt6Gui Qt6Network
Qt6OpenGL Qt6Pdf Qt6PrintSupport Qt6Svg Qt6WaylandClient Qt6Widgets
Qt6WlShellIntegration Qt6XcbQpa ICU data/i18n/uc 73
```

The exact plugin files in the reference Linux build are:

```text
egldeviceintegrations: qeglfs-emu, qeglfs-kms-egldevice, qeglfs-x11
generic: qevdevkeyboard, qevdevmouse, qevdevtablet, qevdevtouch, qtuiotouch
iconengines: qsvgicon
imageformats: qgif, qicns, qico, qjpeg, qpdf, qsvg, qtga, qwbmp, qwebp
networkinformation: qconnman, qglib, qnetworkmanager
platforminputcontexts: compose, ibus
platforms: eglfs, linuxfb, minimal, minimalegl, offscreen, vkkhrdisplay, vnc, wayland, xcb
platformthemes: gtk3, xdgdesktopportal
printsupport: cups
tls: certonly, openssl
wayland-decoration-client: adwaita, bradient
wayland-graphics-integration-client: dmabuf, drm-egl, qt-wayland-egl, shm-emulation, vulkan
wayland-shell-integration: fullscreen-shell-v1, ivi-shell, qt-shell, wl-shell, xdg-shell
xcbglintegrations: egl, glx
```

Qt's official module matrix identifies Qt Virtual Keyboard as GPL-only for open-source users. The
application does not use it. The build now excludes its plugin, Qt6VirtualKeyboard libraries and
the otherwise unused QML/Quick dependency cluster on Linux and Windows. A clean reference rebuild
confirmed that no matching binaries or dangling symbolic links remain. GNU Readline is likewise
absent. No GPL-only Qt module was found in the resulting reference runtime. Qt PDF is available
under an LGPL-compatible Qt license, but carries substantial third-party notices through PDFium,
Chromium-derived code, FreeType, ICU, JPEG/PNG and related libraries.

The authoritative Qt 6.11.1 third-party-code report identifies notices/licenses used by Core,
D-Bus, GUI, image formats, network, PDF, SVG and Wayland. The official module-level pages are
preserved verbatim under `licenses/Qt-6.11.1/third-party/`. This is intentionally a conservative
module-level corpus because the official PySide wheel does not contain a finer binary-level SBOM.
The excluded TIFF notice is not included.

## LGPL redistribution requirements

The packaging plan elects the LGPL-3.0 path for LGPL-capable Qt/PySide/Shiboken components; it does
not claim the GPL alternative. The practical release requirements are:

1. give recipients prominent notice that Qt/PySide/Shiboken are used under LGPL-3.0 and include the
   complete LGPL-3.0 license text;
2. preserve copyright and license notices, including applicable Qt third-party notices;
3. provide the complete corresponding source for the exact LGPL libraries, including build scripts
   and any modifications, or a legally sufficient durable written offer/source-access mechanism;
4. provide information sufficient to rebuild/replace/relink those libraries and run the modified
   libraries with Hesiva;
5. do not prohibit reverse engineering for debugging modifications to the LGPL components;
6. do not use installer, signatures, runtime checks or contractual terms to prevent replacement of
   the LGPL libraries.

PyInstaller `onedir` uses separate `.so`/DLL files, which is technically compatible with user
replacement. Hesiva's artifact provenance is a build/staging verification mechanism and is not
checked at application runtime, so it does not prevent replacement after distribution. Hesiva has
not modified Qt/PySide/Shiboken. Counsel should approve the final source-offer duration/delivery
text and end-user terms; this audit does not provide legal advice.

Hesiva's application source can remain MIT licensed. Dynamic use of LGPL libraries does not, by
itself, replace the application's license. Third-party components and any modifications to them
remain governed by their own terms. The project must not describe the entire frozen distribution as
solely MIT.

PyInstaller's official license gives unlimited permission, through its bootloader exception, to
embed/distribute the bootloader as part of generated programs without imposing PyInstaller's GPL on
the generated application. Runtime hooks are Apache-2.0. Shipping PyInstaller's complete
`COPYING.txt` is the clear compliance choice.

CPython's PSF license permits redistribution with its notices/terms. SQLite is public domain; a
courtesy attribution is recommended but not a copyright-license condition. SQLAlchemy, Alembic,
Argon2, cffi and the other permissively licensed packages permit MIT application licensing while
requiring their respective notice/license preservation where specified.

## Required artifact notice structure

Every portable Linux and Windows `onedir` must place the following at its visible top level:

```text
LICENSE                         Hesiva MIT license
THIRD_PARTY_NOTICES.md          exact component/version/source/notice index
SOURCE-OFFER.md                 corresponding-source delivery mechanism
RELINKING.md                    LGPL replacement/relinking information
licenses/
    Qt-6.11.1/                  LGPL/GPL texts and official Qt module notices
    CPython-3.13.14/            exact CPython license
    PyInstaller-6.22.0/         exact PyInstaller COPYING and exception
    Python-packages/            exact installed license files listed above
    Native-Debian/              build-derived Debian copyright files
third-party-runtime-inventory.json
```

Names may be normalized, but content must be verbatim from the authoritative exact-version upstream
source/wheel/package. `THIRD_PARTY_NOTICES.md` is an index, not a substitute for required full
license texts.

The Debian package installs the same material under `/usr/share/doc/hesiva/` and also retains it at
the `/opt/hesiva` onedir root. The Windows onedir requires the platform-independent corpus plus a
new inventory/license mapping for the actual Windows DLL/PYD payload.
Microsoft runtime-library redistribution, if the native build copies it, must be checked against the
applicable Visual C++ Redistributable terms on the actual Windows builder.

## Corresponding source and relinking gate

The selected mechanism is side-by-side delivery of
`hesiva-0.1.0-lgpl-corresponding-source.tar.xz` and its SHA-256 sidecar, not a promise to deliver
source later. `packaging/lgpl-source-requirements.json` records official Qt download URLs, exact
sizes and authoritative SHA-256 values for Qt Base, Image Formats, SVG, Translations, Wayland,
WebEngine (which contains Qt PDF/PDFium), and PySide setup 6.11.1. The package build refuses to
proceed until `packaging/license_inventory.py verify-source-bundle` validates every member.
The fresh build also generates the exact Debian-native package set. Every package must have a
reviewed entry in `packaging/native-license-approvals.json`; if its review requires corresponding
source, the exact approved native source archive is added under `native-sources/` and checked by
the same source-bundle gate. The committed approval list is intentionally empty until the fresh
Mint inventory exists, so it cannot bless an inferred native set.

`RELINKING.md` documents the replaceable Linux onedir library/plugin layout and the equivalent
Windows principle. Artifact provenance identifies an official build during production/staging; it
is not checked at application runtime and does not prohibit a recipient from installing compatible
modified LGPL libraries. Hesiva adds no reverse-engineering restriction for debugging those
modifications. Counsel must still review the final distribution placement and legal wording.

Prepare the source companion in a private release workspace by downloading each exact URL in
`packaging/lgpl-source-requirements.json`, then run:

```bash
python packaging/license_inventory.py build-source-bundle \
    --source-directory /absolute/path/to/downloaded-official-sources \
    --release-directory dist \
    --runtime dist/Hesiva
python packaging/license_inventory.py verify-source-bundle \
    --release-directory dist --runtime dist/Hesiva
```

The builder checks every official archive's recorded size and SHA-256, produces deterministic tar
metadata, writes the checksum sidecar, and reopens/verifies the finished companion. It does not
download sources or treat a filename as proof of identity.

## Linux native-library reference inventory

The current openSUSE reference build copied these non-Qt native families transitively. This is an
inventory of the observed artifact, not a recommendation to copy or strip any item:

```text
X11/Xau/XCB and XCB helper libraries; xkbcommon; GLib/GObject/GIO/GModule; GTK3/GDK;
ATK/AT-SPI; Cairo/Pixman; Pango; Fontconfig/FreeType/HarfBuzz/Graphite2/Fribidi;
DBus; Avahi; CUPS; systemd; blkid/mount/uuid; SELinux; seccomp; krb5/GSSAPI;
OpenSSL; GnuTLS/nettle/hogweed/GMP/p11-kit/tasn1/unistring/idn2; libffi;
libstdc++/libgcc; SQLite; zlib/zstd/bzip2/xz/Brotli; libpng; lcms2;
ncurses/tinfo; expat; Thai/datrie; Python; mpdecimal; glycin/leancrypto/jitterentropy
```

The corresponding exact top-level native filenames in this reference build are:

```text
_cffi_backend.cpython-313-x86_64-linux-gnu.so
libX11-xcb.so.1 libX11.so.6 libXau.so.6 libXcomposite.so.1 libXcursor.so.1
libXdamage.so.1 libXext.so.6 libXfixes.so.3 libXi.so.6 libXinerama.so.1
libXrandr.so.2 libXrender.so.1 libatk-1.0.so.0 libatk-bridge-2.0.so.0 libatspi.so.0
libavahi-client.so.3 libavahi-common.so.3 libblkid.so.1 libbrotlicommon.so.1.2.0
libbrotlidec.so.1.2.0 libbz2.so.1.0.6 libcairo-gobject.so.2 libcairo.so.2
libcom_err.so.2 libcrypto.so.3.5.3 libcups.so.2 libdatrie.so.1 libdbus-1.so.3
libeconf.so.0 libepoxy.so.0 libexpat.so.1 libffi.so.8 libfontconfig.so.1
libfreetype.so.6 libfribidi.so.0 libgcc_s.so.1 libgdk-3.so.0
libgdk_pixbuf-2.0.so.0 libgio-2.0.so.0 libglib-2.0.so.0 libglycin-2.so.0
libgmodule-2.0.so.0 libgmp.so.10 libgnutls.so.30 libgobject-2.0.so.0
libgraphite2.so.3 libgssapi_krb5.so.2 libgthread-2.0.so.0 libgtk-3.so.0
libharfbuzz.so.0 libhogweed.so.6.11 libidn2.so.0 libjitterentropy.so.3
libk5crypto.so.3 libkeyutils.so.1 libkrb5.so.3 libkrb5support.so.0 liblcms2.so.2
libleancrypto.so.1 liblzma.so.5.8.3 libmount.so.1 libmpdec.so.4 libncursesw.so.6
libnettle.so.8.11 libp11-kit.so.0 libpango-1.0.so.0 libpangocairo-1.0.so.0
libpangoft2-1.0.so.0 libpcre2-8.so.0 libpixman-1.so.0 libpng16.so.16.58.0
libpython3.13.so.1.0 libseccomp.so.2 libselinux.so.1 libsqlite3.so.3.53.2
libssl.so.3.5.3 libstdc++.so.6 libsystemd.so.0 libtasn1.so.6 libthai.so.0
libtinfo.so.6 libunistring.so.5 libuuid.so.1 libxcb-cursor.so.0 libxcb-glx.so.0
libxcb-icccm.so.4 libxcb-image.so.0 libxcb-keysyms.so.1 libxcb-randr.so.0
libxcb-render-util.so.0 libxcb-render.so.0 libxcb-shape.so.0 libxcb-shm.so.0
libxcb-sync.so.1 libxcb-util.so.1 libxcb-xfixes.so.0 libxcb-xkb.so.1
libxkbcommon-x11.so.0 libxkbcommon.so.0 libz.so.1.3.1 libzstd.so.1.5.7
```

The artifact also contains Python extension modules and the Qt/PySide files listed above; the
complete authoritative path/source mapping is in PyInstaller `COLLECT-00.toc`. Final compliance
must inventory the fresh Mint build by source Debian package and copy that source package's
authoritative copyright/license material. Libraries supplied only by the user's operating system
are runtime dependencies and are not redistributed by Hesiva; their license text is not part of
Hesiva's artifact solely because the loader uses them.

Potentially unnecessary copied libraries must be decided from clean X11, Wayland, printing and PDF
tests, not removed for size or licensing convenience. The current build intentionally removed only
the unused TIFF plugin, GPL-only Qt Virtual Keyboard cluster and GNU Readline. Some copied system
libraries have versioned filenames that do not satisfy the Qt/plugin `DT_NEEDED` SONAME and may be
dead payload on this host; this must be resolved on the Debian-family build, not guessed here.

## Debian dependency closure

The former static `Depends: libc6, libgl1` was conclusively incomplete. It has been replaced by an
artifact-derived placeholder populated only on the Debian-family build host. The reference
openSUSE artifact resolved these SONAMEs outside its onedir tree:

```text
ld-linux-x86-64.so.2   libEGL.so.1        libGL.so.1        libbrotlicommon.so.1
libbrotlidec.so.1      libbz2.so.1        libc.so.6         libcrypto.so.3
libdl.so.2             libdrm.so.2        libhogweed.so.6   liblzma.so.5
libm.so.6              libnettle.so.8     libpng16.so.16    libpthread.so.0
libresolv.so.2         libsqlite3.so.0    libssl.so.3       libwayland-client.so.0
libwayland-cursor.so.0 libwayland-egl.so.1 libxcb.so.1      libz.so.1
libzstd.so.1
```

This proves direct host use of EGL, DRM, Wayland, XCB, TLS/crypto, compression, PNG and SQLite
families in addition to libc/GL. It does **not** make them all manual package declarations: the
release tool maps resolved paths to direct installed binary-package owners and deduplicates them;
Debian resolves transitive dependencies normally.

`dpkg-shlibdeps` is not an accurate whole-tree model for this PyInstaller layout. The original
documented command first failed because `packaging/debian/control.in` is a binary control template,
not a source+binary `debian/control`. With a synthetic source stanza it then failed because private
bundled Qt libraries such as `libQt6XcbQpa.so.6` have no Debian shlibs/symbols metadata. Suppressing
that error would risk classifying bundled libraries as missing host packages.

`packaging/linux_runtime_audit.py` now provides the reproducible boundary. It records every ELF's
`DT_NEEDED`, RPATH/RUNPATH and actual `ldd` resolution with `LD_LIBRARY_PATH` set exactly to the
PyInstaller `_internal` root. It rejects unresolved libraries, runtime-escaping/dangling symlinks,
forbidden payloads and any new host SONAME outside the reviewed policy. `libxcb-cursor.so.0` and
`libcups.so.2` are explicitly required and resolved from the bundle so their presence cannot depend
silently on build-host discovery. `debian-depends` maps only external resolved paths with
`dpkg-query`, which naturally selects Noble's `t64` package names where applicable.

For the locked Noble/Mint 22.3 baseline, install the dependency-audit tool and the two explicitly
bundled build inputs before freezing:

```bash
sudo apt update
sudo apt install binutils libxcb-cursor0 libcups2t64
```

`dpkg` supplies `dpkg-query` and `dpkg-deb` on this baseline. The audit verifies the recursive ELF
closure, but the generated Debian `Depends` contains only owners of direct host `DT_NEEDED` edges;
dependencies of those Debian packages remain Debian's responsibility.

On the final Linux Mint/Ubuntu build machine:

```bash
scripts/build_linux.sh
scripts/smoke_packaged_linux.sh
HESIVA_SMOKE_QPA_PLATFORM=xcb scripts/smoke_packaged_linux.sh
python packaging/linux_runtime_audit.py verify
python packaging/linux_runtime_audit.py report
python packaging/linux_runtime_audit.py debian-depends
scripts/build_deb.sh
```

Inspect the generated dependency report and control metadata, then verify:

```bash
scripts/build_deb.sh
dpkg-deb --info dist/hesiva_0.1.0_amd64.deb
dpkg-deb --contents dist/hesiva_0.1.0_amd64.deb
sudo apt install ./dist/hesiva_0.1.0_amd64.deb
ldd /opt/hesiva/Hesiva
find /opt/hesiva -type f -name '*.so*' -exec ldd '{}' \;
```

Exercise X11, intended Wayland, CUPS/native print, PDF, GTK portal/file dialogs, Turkish text and
KDE/Kvantum. Hash the user data directory before remove, purge, reinstall and upgrade; confirm it is
unchanged. Repeat in a clean minimal supported VM so developer packages cannot hide missing
dependencies.

## Windows release gate

Build natively on Windows, inventory every DLL/PYD/plugin and run `dumpbin /DEPENDENTS` (or an
equivalent trusted PE dependency inspector) recursively. Confirm Qt Virtual Keyboard/QML/Quick and
GNU Readline are absent. Identify whether the Universal CRT/Visual C++ runtime is system-provided or
redistributed, and apply Microsoft's official redistribution terms to copied runtime DLLs. Copy the
same Hesiva/third-party notice layout, adjusted to the exact Windows native inventory. Test user
replacement of Qt DLLs, startup/login, backup/restore/import, PDF and native printer dialog on a
clean Windows 11 VM. Linux evidence does not establish Windows dependency closure.

## Release blockers and legal review

The following still block distribution of V1 artifacts:

1. a fresh Mint/Noble build must regenerate the exact Debian native copyright inventory, after
   which every exact package/version/license/source obligation must be reviewed and recorded;
2. the official source archives must be downloaded, verified, assembled into the exact companion
   source archive, and published alongside the binary; this large bundle is intentionally not
   committed to Git;
3. human/legal review must approve the final corpus, source placement and distribution terms;
4. Windows native contents/dependencies and Microsoft runtime terms have not been inspected.

The release build rejects any drift from the exact Python/Qt/PyInstaller versions in
`packaging/license-policy.json`; an intentional upgrade requires updating and re-reviewing the
corpus. This is a release inventory lock, not a general dependency resolver.

Human/legal review is needed for the side-by-side source placement/delivery wording, end-user terms
(especially reverse-engineering rights), and the final notice corpus. The technical conclusion is
not that Hesiva is “legally safe”; it is that MIT licensing of Hesiva's code is compatible with the
planned separate LGPL/permissive components if all applicable obligations are actually satisfied.

## Primary references

- Qt for Python licensing: <https://doc.qt.io/qtforpython-6/>
- Qt open-source LGPL obligations: <https://www.qt.io/development/open-source-lgpl-obligations>
- Qt module license matrix: <https://doc.qt.io/qt-6/licensing.html>
- Qt 6.11.1 third-party licenses: <https://doc.qt.io/qt-6/licenses-used-in-qt.html>
- Qt SBOM documentation: <https://doc.qt.io/qt-6/sbom.html>
- PyInstaller 6.22.0 license: <https://github.com/pyinstaller/pyinstaller/blob/v6.22.0/COPYING.txt>
- CPython 3.13 license: <https://docs.python.org/3.13/license.html>
- SQLite public-domain dedication: <https://www.sqlite.org/copyright.html>
- SQLAlchemy: <https://www.sqlalchemy.org/download.html>
- Alembic: <https://github.com/sqlalchemy/alembic>
- argon2-cffi-bindings: <https://github.com/hynek/argon2-cffi-bindings>
