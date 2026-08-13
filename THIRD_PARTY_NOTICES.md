# Hesiva Third-Party Notices

Hesiva's own source code is licensed under the MIT License in `LICENSE`.
The frozen application also redistributes the third-party components below. Those
components remain under their own licenses; the frozen distribution is not "MIT
only". Full license and notice texts are in `licenses/`.

This inventory is locked to the Hesiva 0.1.0 release environment. The release
tool refuses dependency-version drift and records the exact frozen/native
inventory. A newly built artifact is redistributable only after that artifact's
inventory and corresponding-source companion have passed the release checks.

## Qt for Python and Qt

Hesiva uses the LGPL-3.0 option for PySide6 6.11.1, PySide6 Essentials 6.11.1,
PySide6 Addons 6.11.1, Shiboken6 6.11.1, and the LGPL-capable Qt 6.11.1 libraries
they distribute. The LGPL-3.0 and incorporated GPL-3.0 texts are in
`licenses/Qt-6.11.1/`. The official Qt 6.11.1 module-level third-party notices
for the bundled Core, D-Bus, GUI, Image Formats (WebP), Network, PDF, SVG, and
Wayland families are in `licenses/Qt-6.11.1/third-party/`.

The Linux runtime uses dynamically loaded shared libraries and plugins. See
`RELINKING.md` for replacement/relinking information and `SOURCE-OFFER.md` for
the exact corresponding-source delivery mechanism. Hesiva has not modified
Qt, PySide6, or Shiboken6. Hesiva imposes no additional prohibition on reverse
engineering needed to debug modifications to those LGPL-covered components.

Qt Virtual Keyboard, the unused Qt QML/Quick cluster, GNU Readline, and the Qt
TIFF image plugin are excluded from the frozen runtime. They are not covered by
this distribution notice. The release audit fails if those forbidden payloads
appear.

## Python runtime and packaging

| Component | Version | Role | License material |
| --- | --- | --- | --- |
| CPython | 3.13.14 | bundled interpreter/standard library | `licenses/CPython-3.13.14/LICENSE.txt` |
| PyInstaller | 6.22.0 | bundled bootloader/runtime hooks | `licenses/PyInstaller-6.22.0/COPYING.txt` |
| SQLite | build-recorded | bundled CPython SQLite runtime when present | `licenses/SQLite/copyright.html` |

PyInstaller's `COPYING.txt` contains the bootloader exception applicable to
generated programs and identifies the Apache-2.0 licensing of its runtime
hooks. It does not change the license of Hesiva's own code.

SQLite makes a public-domain dedication rather than using a conventional
copyright license. The included page is the official SQLite statement.

## Bundled Python packages

| Component | Version | License family | License material |
| --- | --- | --- | --- |
| SQLAlchemy | 2.0.51 | MIT | `licenses/Python-packages/SQLAlchemy/` |
| Alembic | 1.19.0 | MIT | `licenses/Python-packages/Alembic/` |
| argon2-cffi | 25.1.0 | MIT | `licenses/Python-packages/argon2-cffi/` |
| argon2-cffi-bindings | 25.1.0 | MIT; vendored Argon2/encoding/BLAKE2 notices include CC0 | `licenses/Python-packages/argon2-cffi-bindings/` |
| cffi / `_cffi_backend` | 2.1.1 | MIT-0 | `licenses/Python-packages/cffi/` |
| greenlet | 3.5.4 | MIT AND PSF-2.0 | `licenses/Python-packages/greenlet/` |
| Mako | 1.4.1 | MIT | `licenses/Python-packages/Mako/` |
| MarkupSafe | 3.0.3 | BSD-3-Clause | `licenses/Python-packages/MarkupSafe/` |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause | `licenses/Python-packages/packaging/` |
| Pygments | 2.20.0 | BSD-2-Clause | `licenses/Python-packages/Pygments/` |
| setuptools | 84.0.0 | MIT plus frozen-vendor licenses | `licenses/Python-packages/setuptools/` and `setuptools-vendored/` |
| typing_extensions | 4.16.0 | PSF-2.0 | `licenses/Python-packages/typing_extensions/` |

The exact machine-readable list shipped in each artifact is
`third-party-runtime-inventory.json`. It also records exact Debian package
owners and copyright files for native libraries copied from the Linux build
host. Libraries resolved only from the recipient's operating system are listed
as host dependencies in `runtime-dependencies.txt`; they are not redistributed
merely because the loader uses them.

## Native libraries

PySide6 wheels contain Qt and ICU libraries covered by the Qt corpus above.
PyInstaller can also copy native libraries from the Linux build host, including
the CPython runtime and libraries used for X11/XCB, fonts/graphics, CUPS,
compression, TLS, and SQLite. Their exact set is build-specific. A Debian-family
release build must include the authoritative Debian `copyright` file for every
binary package from which such a file was copied, under
`licenses/Native-Debian/`, and record package/version/source ownership in the
runtime inventory. Packaging also requires an exact reviewed entry in
`packaging/native-license-approvals.json` for every captured package. If that
review concludes that corresponding source must accompany a copied native
library, the exact approved native source archive becomes a required member of
the source companion. Packaging fails closed when mapping, review, notices, or
required source are incomplete.

Windows must generate a separate DLL/PYD inventory and add authoritative
notices for any Microsoft or other native runtime actually redistributed. A
Linux inventory is not evidence for Windows.

This notice is an engineering attribution index, not legal advice. The final
corpus, LGPL delivery mechanism, and distribution terms require human/legal
review before public release.
