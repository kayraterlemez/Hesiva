# -*- mode: python ; coding: utf-8 -*-

import sys

sys.path.insert(0, SPECPATH)

from pyinstaller_support import (
    DEVELOPMENT_EXCLUDES,
    MIGRATION_HIDDEN_IMPORTS,
    REPOSITORY_ROOT,
    SOURCE_ROOT,
    executable_icon,
    hesiva_datas,
    with_baseline_linux_libraries,
    without_unused_qt_plugins,
)


analysis = Analysis(
    [str(REPOSITORY_ROOT / "packaging" / "runtime_smoke.py")],
    pathex=[str(SOURCE_ROOT), str(REPOSITORY_ROOT / "tests")],
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
    name="HesivaRuntimeSmoke",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=executable_icon(),
)

collection = COLLECT(
    executable,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="HesivaRuntimeSmoke",
)
