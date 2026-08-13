# LGPL Corresponding Source Delivery

Hesiva uses a side-by-side source-delivery mechanism, not a future written
offer. Every distributed Hesiva 0.1.0 binary archive or Debian package must be
published together with:

```text
hesiva-0.1.0-lgpl-corresponding-source.tar.xz
hesiva-0.1.0-lgpl-corresponding-source.tar.xz.sha256
```

The companion archive must contain the unmodified official 6.11.1 source
archives for every LGPL-covered Qt/PySide/Shiboken module recorded in
`packaging/lgpl-source-requirements.json`, which is the machine-readable manifest
containing the authoritative SHA-256 and byte size of every source member, and
the build/relinking information used for the release. It must also contain each
native source archive marked as required by the exact reviewed Debian-native
inventory. Qt
PDF requires the Qt WebEngine source archive because that is the upstream source
module containing Qt PDF/PDFium.

The release tooling verifies the companion archive and checksum before a Debian
package may be produced. Merely linking to an upstream web page does not satisfy
this project's release gate. If the companion archive is unavailable, does not
match the locked Qt/PySide versions and reviewed native-source inventory, or is
not distributed from the same release location, the binary artifact is **not
approved for redistribution**.

Hesiva currently carries no modifications to Qt, PySide6, or Shiboken6. If that
changes, the complete corresponding modified source and build material must be
added to the companion archive and this process must be reviewed again.

This document records the chosen engineering mechanism. It deliberately makes
no promise about a future written-offer duration. Counsel must review the final
release placement, availability, and wording before public distribution.

Official source locations are recorded in the requirements file and originate
under `https://download.qt.io/official_releases/`.
