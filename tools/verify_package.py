"""Fail the build if a consumer package is incomplete or includes development files."""
from pathlib import Path
import os
import sys

import pefile


def verify(directory: Path) -> dict:
    assert {p.name for p in directory.iterdir()} == {'Copyer.exe', '_internal'}, 'Unexpected top-level files'
    internal = directory / '_internal'
    required = (
        'app_icon.ico', 'assets/ui-icons.json', 'python311.dll',
        'PySide6/Qt6Core.dll', 'PySide6/Qt6Gui.dll', 'PySide6/Qt6Widgets.dll',
        'PySide6/plugins/platforms/qwindows.dll', 'PySide6/plugins/imageformats/qjpeg.dll',
        'PySide6/plugins/imageformats/qico.dll', 'PySide6/translations/qtbase_zh_CN.qm',
        'exiftool/exiftool_files/perl.exe', 'exiftool/exiftool_files/exiftool.pl',
        'exiftool/exiftool_files/LICENSE', 'exiftool/exiftool_files/Licenses_Strawberry_Perl.zip',
        'licenses/NOTICE.md', 'licenses/Python-LICENSE.txt', 'licenses/icons/SOURCES.md',
        'licenses/Qt/LGPL-3.0-only.txt', 'licenses/Qt/GPL-3.0-only.txt',
        'licenses/native/openssl/LICENSE.txt',
    )
    for name in required:
        assert (internal / name).is_file(), f'Missing runtime file: {name}'
    forbidden = {'qtawesome', 'qtpy', 'tests', 'tools', 'docs', '__pycache__', '.git'}
    files = [p for p in directory.rglob('*') if p.is_file()]
    for path in files:
        relative = path.relative_to(directory)
        assert not (set(relative.parts) & forbidden), f'Development files: {relative}'
        assert path.suffix.lower() not in {'.pod', '.ttf', '.otf', '.ps1', '.bat', '.py'}, f'Unexpected payload: {relative}'
        assert path.name not in {'Geolocation.dat', 'opengl32sw.dll', 'exiftool(-k).exe'}, f'Unused payload: {relative}'

    # Validate native imports after filtering. No dependency may come from the
    # Conda environment or PATH; only the bundle and Windows system are allowed.
    system = Path(os.environ['SystemRoot']) / 'System32'
    search = [internal, internal / 'PySide6', internal / 'shiboken6',
              internal / 'exiftool/exiftool_files', system]
    missing = set()
    for path in files:
        if path.suffix.lower() not in {'.exe', '.dll', '.pyd'}:
            continue
        with pefile.PE(str(path), fast_load=True) as pe:
            pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_IMPORT']])
            for entry in getattr(pe, 'DIRECTORY_ENTRY_IMPORT', ()):
                name = entry.dll.decode('ascii')
                if name.lower().startswith(('api-ms-', 'ext-ms-')):
                    continue
                if not any((folder / name).is_file() for folder in [path.parent, *search]):
                    missing.add(f'{path.relative_to(directory)} -> {name}')
    assert not missing, 'Missing native dependencies:\n' + '\n'.join(sorted(missing))
    return {'files': len(files), 'bytes': sum(p.stat().st_size for p in files), 'native_imports': 'ok'}


if __name__ == '__main__':
    print(verify(Path(sys.argv[1]).resolve()))
