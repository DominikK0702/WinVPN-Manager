# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

project_root = Path.cwd()
app_dir = project_root / "app"
logo_png = app_dir / "logo.png"
logo_ico = app_dir / "logo.ico"

datas = []
if logo_png.exists():
    datas.append((str(logo_png), "."))

icon_path = str(logo_ico) if logo_ico.exists() else None

a = Analysis(
    ["app/main.py"],
    pathex=[str(project_root), str(app_dir)],
    binaries=[],
    datas=datas,
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
    [],
    name="WinVPN-Manager",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    exclude_binaries=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_path,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="WinVPN-Manager",
)
