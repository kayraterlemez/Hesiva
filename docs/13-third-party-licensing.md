# Third-Party Licensing and Runtime Dependency Audit

## Status and scope

This is the engineering compliance record for the Hesiva 0.1.0 release candidate. It is not legal
advice. Hesiva's own source remains MIT licensed; every redistributed third-party component remains
under its own license.

The reference inventory below was produced on 2026-08-13 from a provenance-verified PyInstaller
6.22.0 `onedir` build on openSUSE x86_64, Python 3.13.14, glibc 2.43, PySide6/Qt 6.11.1. The tree
contained 381 regular files and occupied 199,460,644 bytes. This is useful evidence, but it is not
the Linux release candidate: the final artifact must be rebuilt on the selected Debian-family
baseline and inventoried again. Windows requires its own native inventory.

The reference artifact does **not** contain a complete license/notice/source-offer payload and must
not be distributed. A partial notice file would create false assurance, so one is not committed by
this audit.

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
jaraco helpers, backports.tarfile, packaging, platformdirs, tomli and wheel. Their exact license
files must be copied from the exact installed release used to build, rather than inferred from this
list.

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

The authoritative Qt 6.11.1 third-party-code report also identifies notices/licenses used by GUI,
image formats, network, PDF, Wayland and other shipped modules. Those notices are part of the
required final inventory; the PySide wheel installed on this host does not itself contain a
complete license/SBOM payload.

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
licenses/
    LGPL-3.0.txt
    Qt-PySide-Shiboken-6.11.1/  authoritative Qt for Python/Qt notices
    Qt-6.11.1-third-party/      exact module/plugin notices or generated SPDX SBOM material
    Python-3.13.14-LICENSE.txt
    PyInstaller-6.22.0-COPYING.txt
    Python-packages/            exact installed license files listed above
    Native-libraries/           licenses/notices for every native library actually copied
    SOURCE-OFFER.md             reviewed LGPL source/relinking instructions
```

Names may be normalized, but content must be verbatim from the authoritative exact-version upstream
source/wheel/package. `THIRD_PARTY_NOTICES.md` is an index, not a substitute for required full
license texts.

The Debian package must install the same material under `/usr/share/doc/hesiva/` (using a Debian
`copyright` file if desired) and should also keep the portable top-level material in `/opt/hesiva`
so the onedir remains self-describing. The current Debian staging installs only Hesiva's MIT
`LICENSE`; it is therefore not redistributable yet. The Windows onedir requires the same material.
Microsoft runtime-library redistribution, if the native build copies it, must be checked against the
applicable Visual C++ Redistributable terms on the actual Windows builder.

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

`Depends: libc6, libgl1` is conclusively incomplete for the current reference artifact. Reading the
`DT_NEEDED` entries of every ELF file and subtracting basenames actually present in the onedir leaves:

```text
ld-linux-x86-64.so.2  libEGL.so.1       libGL.so.1       libbrotlicommon.so.1
libbrotlidec.so.1     libbz2.so.1       libc.so.6        libcrypto.so.3
libdl.so.2            libdrm.so.2       libhogweed.so.6  liblzma.so.5
libm.so.6             libnettle.so.8    libpng16.so.16   libpthread.so.0
libresolv.so.2        libsqlite3.so.0   libssl.so.3      libwayland-client.so.0
libwayland-cursor.so.0 libwayland-egl.so.1 libxcb.so.1   libz.so.1
libzstd.so.1
```

This proves missing EGL, DRM, Wayland, XCB, TLS/crypto, compression, PNG and SQLite families in
addition to libc/GL. It does **not** prove final Debian package names: ABI transitions (for example
`t64`) and the chosen baseline determine those names. Do not paste guessed package names into
`control.in` on this openSUSE host.

On the final Linux Mint/Ubuntu build machine:

```bash
scripts/build_linux.sh
scripts/smoke_packaged_linux.sh

find dist/Hesiva -type f -print0 |
  xargs -0 -n1 sh -c 'readelf -h "$1" >/dev/null 2>&1 && readelf -d "$1"' sh

mkdir -p build/dependency-audit/debian
sed -e 's/@VERSION@/0.1.0/g' -e 's/@INSTALLED_SIZE@/0/g' \
  packaging/debian/control.in >build/dependency-audit/debian/control

mapfile -d '' elf_files < <(find "$PWD/dist/Hesiva" -type f -print0)
args=()
for file in "${elf_files[@]}"; do
    readelf -h "$file" >/dev/null 2>&1 && args+=("-e$file")
done
(cd build/dependency-audit && dpkg-shlibdeps -O \
  -l"$PWD/../../dist/Hesiva/_internal" \
  -l"$PWD/../../dist/Hesiva/_internal/PySide6/Qt/lib" \
  "${args[@]}")
```

Review `dpkg-shlibdeps` warnings rather than suppressing unresolved libraries. Map every copied
native file to its source package/version/license, generate the complete notice payload, update
`Depends` from the measured closure, rebuild, then verify:

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

The following block distribution of V1 artifacts:

1. the complete exact-version `THIRD_PARTY_NOTICES.md`, verbatim license corpus and Qt third-party
   notices are not yet assembled into the artifact;
2. an approved LGPL corresponding-source/source-offer and relinking-information mechanism is not
   yet packaged;
3. Debian native dependency/package closure is not established on the intended baseline and the
   current two-package `Depends` is incomplete;
4. Windows native contents/dependencies and Microsoft runtime terms have not been inspected;
5. the release build environment is not locked to an exact resolved dependency set, so a later
   rebuild can silently require a different license corpus unless the environment is locked or the
   inventory/notices are regenerated and compared for every build.

Human/legal review is needed for the LGPL source-offer duration/delivery wording, end-user terms
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
