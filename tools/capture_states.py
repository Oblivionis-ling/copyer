"""Capture actual Qt import states using synthetic media and fault injection."""
from __future__ import annotations

import runpy
import argparse
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--compact', action='store_true', help='Capture the earlier compact layout at 427 x 267')
parser.add_argument('--approved-size', action='store_true', help='Capture the approved 700 x 526 layout')
args = parser.parse_args()
subfolder = '光学玻璃修订/' if args.approved_size else ('网格玻璃修订/' if args.compact else '')
sys.argv = ['capture_ui.py', '--output', subfolder+'state-ready.png']
if args.compact:
    sys.argv.extend(['--width', '427', '--height', '267'])
elif args.approved_size:
    sys.argv.extend(['--width', '700', '--height', '526'])
context = runpy.run_path(str(ROOT / 'tools' / 'capture_ui.py'))
window, app = context['window'], context['app']
output = context['output'] / subfolder
window.show()

import copyer_core as core
from copyer_ui import FileDetailsDialog
from PySide6 import QtCore, QtWidgets


def capture(name, widget=window):
    widget.grab().save(str(output / (name + '.png')))


def settle():
    deadline = time.monotonic() + 30
    while window.busy and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.005)
    if window.busy:
        raise RuntimeError('State capture timed out')
    app.processEvents()


with tempfile.TemporaryDirectory(dir=ROOT / '_work', prefix='capture-') as temporary:
    target = Path(temporary)
    window.set_target(str(target / 'complete'))
    captured = set()
    actual_progress = window.import_progress

    def observe_progress(value):
        actual_progress(value)
        if value.phase in {'copy', 'verify'} and value.done > value.total * .25 and value.phase not in captured:
            captured.add(value.phase)
            capture('state-' + value.phase)

    window.import_progress = observe_progress
    window.start_import()
    settle()
    capture('state-complete')
    window.import_progress = actual_progress

    real_import = core.run_import

    def cancel_after_first(job, cancel, progress):
        def observe(value):
            progress(value)
            if value.phase == 'verified':
                cancel.set()
        return real_import(job, cancel, observe)

    window.set_target(str(target / 'cancelled'))
    with patch.object(core, 'run_import', side_effect=cancel_after_first):
        window.start_import()
        settle()
    capture('state-cancelled')

    publish = core._publish_without_overwrite

    def fail_one(temporary_file, destination):
        if destination.name == 'IMG_0001.jpg':
            raise PermissionError('验收模拟：目标文件写入失败')
        return publish(temporary_file, destination)

    window.set_target(str(target / 'partial'))
    with patch.object(core, '_publish_without_overwrite', side_effect=fail_one):
        window.start_import()
        settle()
    capture('state-partial')
    window.primary_action()
    settle()
    assert window.phase == 'complete'

    window.set_target(str(target / 'preview'))
    dialog = FileDetailsDialog(window, '2026-10-27')
    dialog.show()
    dialog.table.selectRow(0)
    deadline = time.monotonic() + 5
    while dialog.preview.pixmap().isNull() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.01)
    capture('state-details', dialog)
    dialog.close()

    def capture_modal():
        modal = app.activeModalWidget()
        if modal:
            capture('state-settings', modal)
            modal.reject()

    QtCore.QTimer.singleShot(100, capture_modal)
    window.show_settings()

    window.resize(880, 680)
    app.processEvents()
    capture('state-compact')
    window.resize(427, 267) if args.compact else window.resize(700, 526) if args.approved_size else window.resize(1536, 1024)
    actual_scan_progress = window.scan_progress
    scanning_captured = False

    def observe_scan(value):
        global scanning_captured
        actual_scan_progress(value)
        if not scanning_captured:
            scanning_captured = True
            capture('state-scanning')

    window.scan_progress = observe_scan
    window.start_scan()
    settle()
    empty = target / 'empty'
    empty.mkdir()
    window.set_source(str(empty))
    window.start_scan()
    settle()
    capture('state-empty')

window.close()
print('State captures saved:', output)
