# License Corpus Provenance

These files are redistribution evidence, not Hesiva-authored license terms.

- `Qt-6.11.1/` comes from the official Qt 6.11.1 / Qt for Python 6.11.1
  repositories and the official Qt 6.11.1 “Licenses Used in Qt” pages. The
  `package-metadata/` files are the unmodified metadata from the installed
  official 6.11.1 wheels. The third-party directory is a conservative corpus
  for the Qt module families present in the frozen runtime; the excluded TIFF
  page is intentionally absent.
- `CPython-3.13.14/LICENSE.txt` is the unmodified license installed with CPython
  3.13.14.
- `PyInstaller-6.22.0/COPYING.txt` is the unmodified COPYING file installed with
  PyInstaller 6.22.0.
- `Python-packages/` contains unmodified exact-version license files from the
  installed distributions. The argon2-cffi-bindings metadata is included
  because it carries its vendored CC0 copyright notices.
- `SQLite/copyright.html` is SQLite's official public-domain dedication page.
- `Native-Debian/` is absent from Git. It is generated inside each Linux frozen
  artifact from the exact Debian binary packages that supplied copied native
  files. Its package/version/source mapping is in
  `third-party-runtime-inventory.json`. The exact package set must be reviewed
  in `packaging/native-license-approvals.json`; corresponding source is added to
  the release companion whenever that review requires it.

Do not edit upstream legal text for style. An intentional dependency upgrade
requires replacing the authoritative material, updating
`packaging/license-policy.json`, and repeating engineering and legal review.
