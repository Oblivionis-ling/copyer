"""Keep installed dependency license notices with the portable distribution."""
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path
import shutil
import sys

destination = Path(sys.argv[1]) / '_internal' / 'licenses'
destination.mkdir(parents=True, exist_ok=True)
versions = []
for package in ('PySide6', 'PySide6_Essentials', 'PySide6_Addons', 'shiboken6',
                'Pillow', 'QtAwesome', 'QtPy', 'packaging'):
    try:
        installed = distribution(package)
    except PackageNotFoundError:
        continue
    versions.append(f'{package} {installed.version}')
    for item in installed.files or ():
        if 'license' in str(item).lower() or 'copying' in str(item).lower():
            source = Path(installed.locate_file(item))
            if source.is_file():
                target = destination / package / source.name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
(destination / 'dependencies.txt').write_text('\n'.join(versions) + '\n', encoding='utf-8')
