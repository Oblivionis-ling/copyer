"""Render the real Qt widgets with isolated, reproducible media fixtures.

Use --interactive for manual desktop QA. Reference labels are for visual comparison
only: all filesystem operations still use generated files under _work/.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
parser = argparse.ArgumentParser()
parser.add_argument('--interactive', action='store_true')
parser.add_argument('--details', action='store_true', help='Open the details dialog for native rendering QA')
parser.add_argument('--reference-labels', action='store_true')
parser.add_argument('--native-default', action='store_true', help='Keep the production 700 x 526 default size')
parser.add_argument('--output', default='implementation-ready.png')
parser.add_argument('--width', type=int, default=1536)
parser.add_argument('--height', type=int, default=1024)
args = parser.parse_args()
if not args.interactive:
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'

from PIL import Image
from PySide6 import QtCore, QtWidgets
from copyer_ui import MediaImporterWindow

work = ROOT / '_work' / 'ui-fixture'
source = work / 'EOS_DIGITAL' / 'DCIM'
source.mkdir(parents=True, exist_ok=True)
for day, count in [('2026-10-27', 62), ('2026-10-26', 44), ('2026-10-25', 22)]:
    folder = source / day
    folder.mkdir(exist_ok=True)
    for index in range(count):
        path = folder / f'IMG_{index+1:04d}.jpg'
        if not path.exists():
            exif = Image.Exif()
            exif[36867] = day.replace('-', ':') + ' 12:00:00'
            Image.new('RGB', (640, 480), (190 + index % 35,) * 3).save(path, exif=exif)
        stamp = datetime.fromisoformat(day).timestamp()
        os.utime(path, (stamp, stamp))

app = QtWidgets.QApplication([])
settings = QtCore.QSettings(str(work / 'qa-settings.ini'), QtCore.QSettings.IniFormat)
settings.setValue('display/reduce_transparency', False)
settings.setValue('display/reduce_motion', True)
for key in ('raw', 'jpg', 'mp4'):
    settings.setValue('formats/' + key, True)
window = MediaImporterWindow(settings=settings)
if not args.native_default:
    window.resize(args.width, args.height)
window.show()
window.set_source(str(source))
window.set_target(str(work / '影像库'))
window.start_scan()
deadline = time.monotonic() + 30
while window.busy and time.monotonic() < deadline:
    app.processEvents()
    time.sleep(.01)
if window.busy:
    raise RuntimeError('Fixture scan timed out')
window.rows['2026-10-27'].suffix.setText('海边')
window.rows['2026-10-26'].suffix.setText('城市')
window.rows['2026-10-26'].suffix.setFocus()
if args.reference_labels:
    window.source_card.main_text.setText('EOS_DIGITAL  (E:)')
    window.source_card.secondary.setText('E:\\DCIM')
    window.target_card.main_text.setText('F:\\影像库')
    if not window._compact:
        card = window.source_card
        arrow_x = min(card.main_text.geometry().right(), card.main_text.x()+card.main_text.fontMetrics().horizontalAdvance(card.main_text.text())+round(12*window._scale))
        card.arrow.move(arrow_x, card.arrow.y())
app.processEvents()
output = ROOT / '_work' / 'ui'
capture_path = output / args.output
capture_path.parent.mkdir(parents=True, exist_ok=True)
window.grab().save(str(capture_path))
print(str(capture_path), flush=True)
print(f'Window: {window.width()} x {window.height()}, DPR {window.devicePixelRatioF()}', flush=True)
if args.interactive:
    if args.details:
        QtCore.QTimer.singleShot(200, lambda: window.show_details('2026-10-27'))
    sys.exit(app.exec())
window.close()
