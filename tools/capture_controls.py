"""Capture focused controls and app-owned dialogs with disposable media/config."""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ.setdefault('QT_SCALE_FACTOR', '2')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from PIL import Image
from PySide6 import QtCore, QtWidgets
from copyer_ui import MediaImporterWindow, SettingsDialog, MessageDialog, FileDetailsDialog

output = ROOT / 'docs/v1.5.0/验收/控件与弹窗修订'
output.mkdir(parents=True, exist_ok=True)
app = QtWidgets.QApplication([])


def settle(condition=lambda: True):
    deadline = time.monotonic()+10
    while time.monotonic() < deadline:
        app.processEvents()
        if condition():
            return
        time.sleep(.01)
    raise RuntimeError('Capture timed out')


def capture(widget, name):
    app.processEvents()
    widget.grab().save(str(output / (name+'.png')))


with tempfile.TemporaryDirectory(prefix='copyer-controls-') as temporary:
    root = Path(temporary)
    source = root / 'EOS_DIGITAL'
    source.mkdir()
    for day in (25, 26, 27):
        exif = Image.Exif()
        exif[36867] = f'2026:10:{day} 12:00:00'
        Image.new('RGB', (64, 48), '#b9b9b9').save(source / f'IMG_{day}.jpg', exif=exif)
    settings = QtCore.QSettings(str(root / 'preferences.ini'), QtCore.QSettings.Format.IniFormat)
    settings.setValue('display/reduce_motion', True)
    settings.setValue('display/reduce_transparency', False)
    window = MediaImporterWindow(settings=settings)
    window.resize(700, 526)
    window.show()
    window.set_source(str(source))
    window.set_target(str(root / '影像库'))
    window.start_scan()
    settle(lambda: not window.busy)
    window.rows['2026-10-27'].suffix.setText('海边')
    window.rows['2026-10-26'].suffix.setText('城市')
    window.rows['2026-10-26'].suffix.setFocus()
    capture(window, 'main-ready')
    for name, widget in [('focus-source', window.source_card.choose_button),
                         ('focus-scan', window.scan_button),
                         ('focus-checkbox', window.raw_checkbox),
                         ('focus-import', window.import_button)]:
        widget.setFocus(QtCore.Qt.FocusReason.TabFocusReason)
        capture(window, name)
    dialog = SettingsDialog(window)
    # Offscreen's synthetic screen is 400 x 400 at DPR 2; capture native sizes.
    dialog.resize(520, 430)
    dialog.show()
    dialog.duplicate.setFocus(QtCore.Qt.FocusReason.TabFocusReason)
    capture(dialog, 'settings')
    print('Settings:', dialog.size().width(), dialog.size().height(), 'font', dialog.font().pixelSize())
    dialog.reject()
    dialog.deleteLater()
    for name, question in [('warning', False), ('close-confirmation', True)]:
        dialog = MessageDialog(window, '任务正在进行' if question else '无法扫描',
                               '停止当前任务后关闭？已完成的文件会保留。' if question else '请选择文件夹，路径不能为空。',
                               question=question)
        dialog.resize(440, 205)
        dialog.show()
        capture(dialog, name)
        dialog.reject()
        dialog.deleteLater()
    dialog = FileDetailsDialog(window, '2026-10-27')
    dialog.resize(1020, 620)
    dialog.show()
    dialog.table.selectRow(0)
    dialog.table.setFocus()
    settle(lambda: dialog.preview.pixmap() is not None and not dialog.preview.pixmap().isNull())
    capture(dialog, 'details')
    dialog.reject()
    dialog.deleteLater()
    window.close()
    window.deleteLater()
    app.processEvents()
    QtCore.QThreadPool.globalInstance().waitForDone(5000)
print(output)
