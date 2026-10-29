# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

version_scope = {}
exec((Path(SPECPATH) / 'copyer_version.py').read_text(encoding='utf-8'), version_scope)
name = 'copyer-' + version_scope['APP_VERSION']
metadata_runtime = Path(SPECPATH) / 'vendor' / 'exiftool'
if not (metadata_runtime / 'exiftool_files' / 'perl.exe').is_file():
    raise RuntimeError('Run tools/fetch_exiftool.py before building.')

# Keep ExifTool's parser and Perl runtime intact. Standalone manuals and the
# reverse-geocoding database are not used by read-only capture-date extraction.
metadata_files = []
for source in metadata_runtime.rglob('*'):
    if not source.is_file():
        continue
    if source.suffix.lower() in ('.pod', '.txt') or source.name in ('Geolocation.dat', 'exiftool(-k).exe'):
        continue
    metadata_files.append((str(source), str(Path('exiftool') / source.relative_to(metadata_runtime).parent)))

a = Analysis(
    ['copyer.py'], pathex=[], binaries=[],
    datas=[('app_icon.ico', '.'), ('assets/ui-icons.json', 'assets')] + metadata_files,
    hiddenimports=[], hookspath=[str(Path(SPECPATH) / 'tools' / 'hooks')], hooksconfig={},
    runtime_hooks=[], excludes=[
        'PyQt5', 'PyQt6', 'PySide2', 'qtawesome', 'qtpy',
        'PySide6.QtQml', 'PySide6.QtQuick', 'PySide6.QtNetwork',
        'PySide6.QtOpenGL', 'PySide6.QtOpenGLWidgets', 'PySide6.QtPdf',
        'PySide6.QtSvg', 'PySide6.QtDataVisualization',
        'PIL.AvifImagePlugin', 'PIL.WebPImagePlugin', 'PIL._avif', 'PIL._webp',
    ],
    noarchive=False, optimize=0,
)

# Qt hooks collect plugins for many products. Copyer paints raster QWidget
# surfaces and only previews JPEG; it does not create an OpenGL context.
plugins = {'platforms/qwindows.dll', 'imageformats/qjpeg.dll', 'imageformats/qico.dll'}
qt_libraries = {'qt6core.dll', 'qt6gui.dll', 'qt6widgets.dll'}
perl_duplicates = {'perl532.dll', 'libstdc++-6.dll', 'libgcc_s_seh-1.dll',
                   'libwinpthread-1.dll', 'liblzma-5__.dll'}

def keep_runtime(entry):
    path = entry[0].replace('\\', '/').lower()
    if path.startswith('pyside6/plugins/'):
        return path.removeprefix('pyside6/plugins/') in plugins
    if path.startswith('pyside6/translations/'):
        return Path(path).name in {'qt_zh_cn.qm', 'qtbase_zh_cn.qm'}
    if path.startswith('pyside6/qt6') and path.endswith('.dll'):
        return Path(path).name in qt_libraries
    if Path(path).name in {'opengl32sw.dll', 'd3dcompiler_47.dll'}:
        return False
    # The Perl runtime lives together in its own directory; the binary scanner
    # also places copies at the root. Python/Qt do not import these DLLs.
    if '/' not in path and path in perl_duplicates:
        return False
    return True

a.binaries = [entry for entry in a.binaries if keep_runtime(entry)]
a.datas = [entry for entry in a.datas if keep_runtime(entry)]
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True, name='Copyer',
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
    console=False, disable_windowed_traceback=False, icon=['app_icon.ico'],
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name=name)
