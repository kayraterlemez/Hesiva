# -*- mode: python ; coding: utf-8 -*-

import sys

sys.path.insert(0, SPECPATH)

from pyinstaller_support import (
    DEVELOPMENT_EXCLUDES,
    MIGRATION_HIDDEN_IMPORTS,
    SOURCE_ROOT,
    hesiva_datas,
    with_baseline_linux_libraries,
    without_unused_qt_plugins,
)


analysis = Analysis(
    [str(SOURCE_ROOT / "hesiva" / "__main__.py")],
    pathex=[str(SOURCE_ROOT)],
    binaries=[],
    datas=hesiva_datas(),
    hiddenimports=list(MIGRATION_HIDDEN_IMPORTS),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=list(DEVELOPMENT_EXCLUDES),
    noarchive=False,
    optimize=0,
)
analysis.binaries = with_baseline_linux_libraries(
    without_unused_qt_plugins(analysis.binaries)
)
pyz = PYZ(analysis.pure)

executable = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="Hesiva",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

collection = COLLECT(
    executable,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Hesiva",
)
