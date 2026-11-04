"""Exercise the real PowerShell replacement/rollback helper on disposable apps."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from copyer_update import INSTALL_SCRIPT


def main():
    shell = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    compiler = Path(os.environ['SystemRoot']) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    with tempfile.TemporaryDirectory(prefix='copyer-installer-test-') as temporary:
        root = Path(temporary).resolve()
        for name, code in (
            ('good', '''using System; using System.IO; using System.Threading;
class App { static void Main(string[] args) {
 if (args.Length == 2 && args[0] == "--update-receipt") {
  File.WriteAllText(args[1], "1.5.3"); Thread.Sleep(500);
 } else if (args.Length == 2 && args[0] == "--update-error") {
  File.WriteAllText(Path.Combine(AppDomain.CurrentDomain.BaseDirectory,"restored.txt"),args[1]);
 }
} }'''),
            ('broken', 'class App { static int Main() { return 7; } }')):
            source = root / (name+'.cs')
            source.write_text(code)
            subprocess.run([str(compiler), '/nologo', '/target:winexe', '/out:'+str(root/(name+'.exe')),
                            str(source)], check=True, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
        for mode in ('success', 'startup_failure', 'partial_move_failure'):
            install = root / (mode+" 中文 ' 空格")
            install.mkdir()
            shutil.copyfile(root/'good.exe', install/'Copyer.exe')
            (install/'_internal').mkdir()
            (install/'_internal/version.txt').write_text('old')
            (install/'user-file.txt').write_text('preserve')
            with tempfile.TemporaryDirectory(prefix='copyer-update-') as staging:
                workspace = Path(staging).resolve()
                package = workspace/'package'
                package.mkdir()
                shutil.copyfile(root/('broken.exe' if mode == 'startup_failure' else 'good.exe'), package/'Copyer.exe')
                if mode != 'partial_move_failure':
                    (package/'_internal').mkdir()
                    (package/'_internal/version.txt').write_text('new')
                script, manifest = workspace/'install.ps1', workspace/'install.json'
                script.write_text(INSTALL_SCRIPT, encoding='utf-8-sig')
                parent = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(.5)'],
                                          creationflags=subprocess.CREATE_NO_WINDOW)
                manifest.write_text(json.dumps({'install':str(install), 'package':str(package), 'pid':parent.pid}), encoding='utf-8')
                result = subprocess.run([str(shell), '-NoProfile', '-NonInteractive', '-WindowStyle', 'Hidden',
                                         '-ExecutionPolicy', 'Bypass', '-File', str(script), str(manifest)],
                                        capture_output=True, timeout=60, creationflags=subprocess.CREATE_NO_WINDOW)
                parent.wait(timeout=5)
                expected = 'new' if mode == 'success' else 'old'
                assert (install/'_internal/version.txt').read_text() == expected, (mode, result.stderr)
                assert (install/'user-file.txt').read_text() == 'preserve'
                assert (install/'Copyer.exe').read_bytes() == (root/'good.exe').read_bytes()
                assert result.returncode == (0 if mode == 'success' else 1), (mode, result.stderr)
                assert not list(install.glob('.copyer-backup-*'))
                if mode == 'success':
                    assert not workspace.exists(), 'Successful update left temporary files'
                if mode != 'success':
                    deadline = time.monotonic()+5
                    while not (install/'restored.txt').exists() and time.monotonic() < deadline:
                        time.sleep(.05)
                    assert (install/'restored.txt').exists(), mode
                    assert (workspace/'update-error.txt').exists()
                print(mode+': passed', flush=True)
        time.sleep(.5)  # Let the tiny disposable child processes finish before cleanup.


if __name__ == '__main__':
    main()
