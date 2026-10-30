"""Keep installed dependency license notices with the portable distribution."""
from importlib.metadata import PackageNotFoundError, distribution
import json
from pathlib import Path
import shutil
import sys

root = Path(__file__).resolve().parents[1]
destination = Path(sys.argv[1]) / '_internal' / 'licenses'
destination.mkdir(parents=True, exist_ok=True)
versions = []
for package in ('PySide6_Essentials', 'shiboken6', 'Pillow', 'PyInstaller'):
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
shutil.copytree(root / 'assets' / 'licenses', destination / 'icons', dirs_exist_ok=True)
shutil.copy2(root / 'THIRD_PARTY.md', destination / 'NOTICE.md')
python_license = next(path for name in ('LICENSE_PYTHON.txt', 'LICENSE.txt')
                      if (path := Path(sys.base_prefix) / name).is_file())
shutil.copy2(python_license, destination / 'Python-LICENSE.txt')
shutil.copytree(root / 'licenses', destination, dirs_exist_ok=True)

# Native libraries come from this project's Conda runtime. Preserve their
# notices without shipping their manuals, headers or development packages.
native_packages = {'bzip2', 'libexpat', 'libffi', 'libzlib', 'openssl', 'ucrt', 'vc14_runtime', 'xz'}
for metadata_path in (Path(sys.base_prefix) / 'conda-meta').glob('*.json'):
    metadata = json.loads(metadata_path.read_text(encoding='utf-8'))
    package = metadata['name']
    if package not in native_packages:
        continue
    source = Path(metadata['link']['source']) / 'info' / 'licenses'
    notices = [path for path in source.rglob('*') if path.is_file() and path.suffix.lower() != '.rtf']
    if not notices:
        raise RuntimeError(f'License notices unavailable for {package}: restore the Conda package cache.')
    for path in notices:
        target = destination / 'native' / package / path.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    versions.append(f'{package} {metadata["version"]}')
shutil.copy2(Path(sys.base_prefix) / 'Library/share/doc/xz/COPYING.0BSD', destination / 'native/xz/COPYING.0BSD')
(destination / 'dependencies.txt').write_text('\n'.join(versions) + '\n', encoding='utf-8')
