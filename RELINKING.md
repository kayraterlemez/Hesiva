# Replacing LGPL-Covered Libraries

Hesiva is packaged with PyInstaller in `onedir` form. Qt, PySide6, and Shiboken6
remain separate dynamically loaded shared libraries rather than being linked
into one monolithic executable.

In the portable Linux tree the relevant files are primarily under:

```text
Hesiva/_internal/PySide6/
Hesiva/_internal/shiboken6/
Hesiva/_internal/PySide6/Qt/lib/
Hesiva/_internal/PySide6/Qt/plugins/
```

The Debian package installs the same tree below `/opt/hesiva`. A recipient may
copy the onedir tree to a writable location and replace compatible LGPL-covered
shared libraries or plugins with modified builds. The replacement must preserve
the filenames/SONAMEs and ABI expected by the exact PySide6 6.11.1 and CPython
3.13 runtime. Qt's normal plugin and dynamic-loader resolution then loads the
replacement. `third-party-runtime-inventory.json` identifies the exact original
files and versions; the source companion described in `SOURCE-OFFER.md` supplies
the sources and build material.

Hesiva does not perform a runtime signature, hash, or provenance check that
prevents modified LGPL libraries from loading. Build provenance verification is
only a producer/staging control: modification makes an artifact no longer an
official byte-for-byte Hesiva build, but does not cause the application itself
to reject replacement libraries.

Windows uses the same onedir principle with Qt/PySide/Shiboken DLLs and plugins
under `_internal`. Exact filenames and Microsoft/native runtime interactions
must be documented from the native Windows release candidate before Windows
redistribution.

Hesiva imposes no additional restriction on reverse engineering needed to
debug modifications to LGPL-covered components. Compatibility and security of
replacement libraries are the recipient's responsibility; this statement does
not reduce rights granted by the applicable licenses.
