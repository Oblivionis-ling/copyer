"""GitHub stable releases and a staged Windows portable updater."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from threading import Event
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
import zipfile

from copyer_metadata import Cancelled
from copyer_version import APP_VERSION

REPOSITORY = 'Oblivionis-ling/copyer'
API_URL = f'https://api.github.com/repos/{REPOSITORY}/releases/latest'
RELEASES_URL = f'https://github.com/{REPOSITORY}/releases/latest'
MAX_PACKAGE = 1024 * 1024 * 1024


class UpdateError(Exception):
    pass


@dataclass(frozen=True)
class Release:
    version: str
    page_url: str
    asset_url: str = ''
    size: int = 0
    sha256: str = ''


@dataclass(frozen=True)
class PreparedUpdate:
    workspace: Path
    package: Path
    version: str


def version_tuple(value: str) -> tuple[int, int, int]:
    match = re.fullmatch(r'v?(\d+)\.(\d+)\.(\d+)', value)
    if not match:
        raise UpdateError('发布版本号无效。')
    return tuple(int(part) for part in match.groups())


def _cancelled(cancel: Event):
    if cancel.is_set():
        raise Cancelled()


def _request(url: str):
    return urlopen(Request(url, headers={'User-Agent': f'Copyer/{APP_VERSION}',
                                        'Accept': 'application/vnd.github+json'}), timeout=15)


def check_update(current: str = APP_VERSION, cancel: Event | None = None) -> Release | None:
    cancel = cancel or Event()
    _cancelled(cancel)
    try:
        with _request(API_URL) as response:
            raw = response.read(2 * 1024 * 1024 + 1)
        _cancelled(cancel)
        if len(raw) > 2 * 1024 * 1024:
            raise UpdateError('发布信息过大，请稍后重试。')
        payload = json.loads(raw)
        if not isinstance(payload, dict) or payload.get('draft') or payload.get('prerelease'):
            raise UpdateError('GitHub 未返回有效的正式版本。')
        tag = payload.get('tag_name', '')
        version = version_tuple(tag)
        if version <= version_tuple(current):
            return None
        normalized = '.'.join(map(str, version))
        page = f'https://github.com/{REPOSITORY}/releases/tag/{tag}'
        name = f'Copyer-v{normalized}-Windows-x64.zip'
        for asset in payload.get('assets', []):
            if asset.get('name') != name or asset.get('state') != 'uploaded':
                continue
            url = asset.get('browser_download_url', '')
            expected = f'https://github.com/{REPOSITORY}/releases/download/{tag}/{name}'
            if url != expected:
                raise UpdateError('更新包地址不属于 Copyer 官方发布。')
            digest = asset.get('digest') or ''
            sha256 = digest[7:] if re.fullmatch(r'sha256:[0-9a-fA-F]{64}', digest) else ''
            size = asset.get('size', 0)
            if not isinstance(size, int) or not 0 < size <= MAX_PACKAGE:
                raise UpdateError('更新包大小无效。')
            return Release(normalized, page, url, size, sha256.lower())
        return Release(normalized, page)
    except HTTPError as exc:
        reason = 'GitHub 请求过于频繁，请稍后再试。' if exc.code in {403, 429} else f'GitHub 返回错误（{exc.code}），请稍后重试。'
        raise UpdateError(reason) from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise UpdateError('无法连接 GitHub，请检查网络后重试。') from exc
    except (ValueError, TypeError, AttributeError) as exc:
        raise UpdateError('GitHub 发布信息无法解析，请稍后重试。') from exc


def extract_package(archive: Path, output: Path, version: str, cancel: Event) -> Path:
    """Strictly extract only the portable application's two owned entries."""
    version_tuple(version)
    expected_root = f'copyer-{version}'
    with zipfile.ZipFile(archive) as package:
        entries = package.infolist()
        if len(entries) > 20000 or sum(item.file_size for item in entries) > 2 * MAX_PACKAGE:
            raise UpdateError('更新包解压大小异常。')
        seen = set()
        for item in entries:
            _cancelled(cancel)
            name = item.filename
            relative = PurePosixPath(name)
            parts = relative.parts
            if (not parts or parts[0] != expected_root or relative.is_absolute()
                    or '\\' in name or any(part in {'.', '..'} or ':' in part or part.endswith((' ', '.')) for part in parts)
                    or stat.S_ISLNK(item.external_attr >> 16)):
                raise UpdateError('更新包包含不安全的路径。')
            if len(parts) > 1 and parts[1] not in {'Copyer.exe', '_internal'}:
                raise UpdateError('更新包包含非程序文件。')
            if len(parts) > 2 and parts[1] == 'Copyer.exe':
                raise UpdateError('更新包结构无效。')
            key = str(relative).casefold()
            if key in seen:
                raise UpdateError('更新包包含重复路径。')
            seen.add(key)
            destination = output.joinpath(*parts)
            if item.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                with package.open(item) as source, destination.open('xb') as target:
                    while block := source.read(1024 * 1024):
                        _cancelled(cancel)
                        target.write(block)
    root = output / expected_root
    for name in ('Copyer.exe', '_internal/python311.dll', '_internal/PySide6/Qt6Core.dll',
                 '_internal/PySide6/Qt6Gui.dll', '_internal/PySide6/Qt6Widgets.dll',
                 '_internal/PySide6/plugins/platforms/qwindows.dll',
                 '_internal/exiftool/exiftool_files/perl.exe'):
        if not (root / name).is_file():
            raise UpdateError('更新包缺少必要运行文件。')
    with (root / 'Copyer.exe').open('rb') as stream:
        if stream.read(2) != b'MZ':
            raise UpdateError('更新包的程序文件无效。')
    return root


def prepare_update(release: Release, cancel: Event, progress=None) -> PreparedUpdate:
    expected_prefix = f'https://github.com/{REPOSITORY}/releases/download/'
    if not release.asset_url.startswith(expected_prefix) or urlsplit(release.asset_url).scheme != 'https':
        raise UpdateError('此版本没有可用的 Windows 更新包。')
    if not re.fullmatch(r'[0-9a-f]{64}', release.sha256):
        raise UpdateError('GitHub 未提供更新包校验值，请前往发布页下载。')
    workspace = Path(tempfile.mkdtemp(prefix='copyer-update-')).resolve()
    try:
        archive = workspace / 'download.zip'
        digest = hashlib.sha256()
        received = 0
        with _request(release.asset_url) as response, archive.open('xb') as target:
            while True:
                _cancelled(cancel)
                block = response.read(1024 * 1024)
                if not block:
                    break
                received += len(block)
                if received > release.size or received > MAX_PACKAGE:
                    raise UpdateError('更新包大小与发布信息不符。')
                target.write(block)
                digest.update(block)
                if progress:
                    progress((received, release.size))
        if received != release.size or digest.hexdigest() != release.sha256:
            raise UpdateError('更新包完整性校验失败，请重试。')
        _cancelled(cancel)
        package = extract_package(archive, workspace / 'unpacked', release.version, cancel)
        archive.unlink()
        return PreparedUpdate(workspace, package, release.version)
    except BaseException:
        shutil.rmtree(workspace)
        raise


# Paths are JSON data, never interpolated into PowerShell source. The helper only
# replaces Copyer.exe and _internal; extra user files in the install folder survive.
INSTALL_SCRIPT = r'''
param([string]$Manifest)
$ErrorActionPreference = 'Stop'
$config = Get-Content -LiteralPath $Manifest -Raw -Encoding UTF8 | ConvertFrom-Json
$install = [IO.Path]::GetFullPath($config.install)
$package = [IO.Path]::GetFullPath($config.package)
$workspace = [IO.Path]::GetFullPath($PSScriptRoot)
$backup = Join-Path $install ('.copyer-backup-' + [Guid]::NewGuid().ToString('N'))
$moved = @()
$placed = @()
try {
    if (!(Test-Path -LiteralPath $install -PathType Container) -or
        !$package.StartsWith($workspace + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Invalid update directories'
    }
    $parent = Get-Process -Id $config.pid -ErrorAction SilentlyContinue
    Set-Content -LiteralPath (Join-Path $workspace 'installer-ready') -Value 'ready'
    if ($parent) { $parent.WaitForExit() }
    New-Item -ItemType Directory -Path $backup | Out-Null
    foreach ($name in @('Copyer.exe', '_internal')) {
        $old = Join-Path $install $name
        if (Test-Path -LiteralPath $old) {
            Move-Item -LiteralPath $old -Destination (Join-Path $backup $name)
            $moved += $name
        }
        $destination = Join-Path $install $name
        $placed += $name
        Move-Item -LiteralPath (Join-Path $package $name) -Destination $destination
    }
    # New process acknowledges a working Qt window before the backup is removed.
    $receipt = Join-Path $workspace 'started'
    $executable = Join-Path $install 'Copyer.exe'
    $child = Start-Process -FilePath $executable -WorkingDirectory $install -WindowStyle Normal -PassThru `
        -ArgumentList @('--update-receipt', ('"' + $receipt + '"'))
    $deadline = [DateTime]::UtcNow.AddSeconds(45)
    while (!(Test-Path -LiteralPath $receipt)) {
        if ($child.HasExited -or [DateTime]::UtcNow -gt $deadline) { throw 'New version failed to start' }
        Start-Sleep -Milliseconds 200
    }
    # All recursively removed paths are validated children of the explicit roots.
    if ($backup.StartsWith($install + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        Remove-Item -LiteralPath $backup -Recurse -Force -ErrorAction SilentlyContinue
    }
} catch {
    $failure = $_.Exception.Message
    $restored = $false
    if ($child -and !$child.HasExited) { $child.Kill(); $child.WaitForExit() }
    try {
        foreach ($name in $placed) {
            $destination = [IO.Path]::GetFullPath((Join-Path $install $name))
            if ($destination.StartsWith($install + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase) -and
                (Test-Path -LiteralPath $destination)) {
                Remove-Item -LiteralPath $destination -Recurse -Force
            }
        }
        foreach ($name in $moved) {
            Move-Item -LiteralPath (Join-Path $backup $name) -Destination (Join-Path $install $name)
        }
        $restored = Test-Path -LiteralPath (Join-Path $install 'Copyer.exe')
        if ((Test-Path -LiteralPath $backup) -and !(Get-ChildItem -LiteralPath $backup)) {
            Remove-Item -LiteralPath $backup
        }
    } catch { $failure += "`nRollback: " + $_.Exception.Message + "`nBackup: $backup" }
    $errorLog = Join-Path $workspace 'update-error.txt'
    Set-Content -LiteralPath $errorLog -Value $failure -Encoding UTF8
    if ($restored) {
        try {
            Start-Process -FilePath (Join-Path $install 'Copyer.exe') -WorkingDirectory $install -WindowStyle Normal `
                -ArgumentList @('--update-error', ('"' + $errorLog + '"'))
            exit 1
        } catch { $failure += "`nRestart: " + $_.Exception.Message }
    }
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.MessageBox]::Show("更新未完成。请保留原程序并重试。`n日志：$workspace`n$failure", 'Copyer') | Out-Null
    exit 1
}
$tempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\')
if ($workspace.StartsWith($tempRoot + '\', [StringComparison]::OrdinalIgnoreCase) -and
    ([IO.Path]::GetFileName($workspace)).StartsWith('copyer-update-')) {
    Remove-Item -LiteralPath $workspace -Recurse -Force -ErrorAction SilentlyContinue
}
'''


def launch_installer(prepared: PreparedUpdate) -> None:
    if os.name != 'nt' or not getattr(sys, 'frozen', False):
        raise UpdateError('源码运行不支持自动替换，请使用 Windows 便携版。')
    install = Path(sys.executable).resolve().parent
    if prepared.workspace not in prepared.package.parents:
        raise UpdateError('更新目录无效。')
    # Check write permission while the running version is still intact.
    with tempfile.TemporaryFile(dir=install):
        pass
    manifest = prepared.workspace / 'install.json'
    manifest.write_text(json.dumps({'install': str(install), 'package': str(prepared.package),
                                    'pid': os.getpid()}), encoding='utf-8')
    script = prepared.workspace / 'install.ps1'
    script.write_text(INSTALL_SCRIPT, encoding='utf-8-sig')
    shell = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    helper = subprocess.Popen([str(shell), '-NoProfile', '-NonInteractive', '-WindowStyle', 'Hidden',
                      '-ExecutionPolicy', 'Bypass', '-File', str(script), str(manifest)],
                     creationflags=subprocess.CREATE_NO_WINDOW, cwd=install)
    deadline = time.monotonic() + 10
    while not (prepared.workspace / 'installer-ready').is_file():
        if helper.poll() is not None or time.monotonic() > deadline:
            if helper.poll() is None:
                helper.terminate()
                helper.wait(timeout=5)
            raise UpdateError('无法启动更新程序，当前版本保持不变。请稍后重试。')
        time.sleep(.05)


def acknowledge_update() -> None:
    if '--update-receipt' not in sys.argv:
        return
    index = sys.argv.index('--update-receipt')
    if index + 1 >= len(sys.argv):
        return
    receipt = Path(sys.argv[index + 1]).resolve()
    temporary = Path(tempfile.gettempdir()).resolve()
    if (receipt.name == 'started' and receipt.parent.parent == temporary
            and receipt.parent.name.startswith('copyer-update-') and receipt.parent.is_dir()):
        receipt.write_text(APP_VERSION, encoding='ascii')


def update_failure() -> str:
    if '--update-error' not in sys.argv:
        return ''
    index = sys.argv.index('--update-error')
    if index + 1 >= len(sys.argv):
        return ''
    path = Path(sys.argv[index+1]).resolve()
    if (path.name != 'update-error.txt' or path.parent.parent != Path(tempfile.gettempdir()).resolve()
            or not path.parent.name.startswith('copyer-update-')):
        return ''
    try:
        with path.open(encoding='utf-8-sig') as stream:
            detail = stream.read(4000)
        return f'更新未完成，已恢复原程序。\n{detail}\n日志：{path}'
    except OSError:
        return '更新未完成，已恢复原程序。请稍后重试。'
