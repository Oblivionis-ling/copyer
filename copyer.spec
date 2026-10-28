# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files

version_scope = {}
exec((Path(SPECPATH) / 'copyer_version.py').read_text(encoding='utf-8'), version_scope)
name = 'copyer-' + version_scope['APP_VERSION']

a = Analysis(
    ['copyer.py'], pathex=[], binaries=[],
    datas=[('app_icon.ico', '.')] + collect_data_files('qtawesome'),
    hiddenimports=['qtawesome', 'qtpy'], hookspath=[], hooksconfig={},
    runtime_hooks=[], excludes=['PyQt5', 'PyQt6', 'PySide2'],
    noarchive=False, optimize=0,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True, name=name,
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
    console=False, disable_windowed_traceback=False, icon=['app_icon.ico'],
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name=name)
