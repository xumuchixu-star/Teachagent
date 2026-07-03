# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['app/desktop_app.py'],
    pathex=['/Users/xumuchi/Desktop/TeachAgent', '/Users/xumuchi/Desktop/TeachAgent/app'],
    binaries=[],
    datas=[('app/static', 'app/static'), ('app/data', 'app/data'), ('docs/rag_inventory', 'docs/rag_inventory'), ('docs/rag_samples', 'docs/rag_samples'), ('scratch/student_annotation_merged', 'scratch/student_annotation_merged'), ('scratch/teachagent_system_overview', 'scratch/teachagent_system_overview')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='TeachAgent',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='TeachAgent',
)
app = BUNDLE(
    coll,
    name='TeachAgent.app',
    icon=None,
    bundle_identifier=None,
)
