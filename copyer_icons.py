"""The twelve UI icons, drawn directly from their existing vector outlines."""
from functools import lru_cache
import json
from pathlib import Path
import sys

from PySide6 import QtCore, QtGui


@lru_cache(maxsize=1)
def _icons():
    root = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
    items = json.loads((root / 'assets/ui-icons.json').read_text(encoding='utf-8'))
    for item in items.values():
        path = QtGui.QPainterPath()
        for command, *values in item['path']:
            if command == 'M': path.moveTo(*values)
            elif command == 'L': path.lineTo(*values)
            else: path.cubicTo(*values)
        path.setFillRule(QtCore.Qt.FillRule.WindingFill)
        item['path'] = path
    return items


class _IconEngine(QtGui.QIconEngine):
    def __init__(self, name, color):
        super().__init__()
        self.name, self.color = name, color

    def clone(self):
        return _IconEngine(self.name, self.color)

    def paint(self, painter, rect, mode, state):
        item = _icons()[self.name]
        scale = round(.875 * rect.height()) / 1000
        painter.save()
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        painter.translate(QtCore.QRectF(rect).center())
        painter.scale(scale, scale)
        painter.translate(-item['advance'] / 2, (item['ascent'] - item['descent']) / 2)
        color = '#909090' if mode == QtGui.QIcon.Mode.Disabled else self.color
        painter.fillPath(item['path'], QtGui.QColor(color))
        painter.restore()

    def pixmap(self, size, mode, state):
        pixmap = QtGui.QPixmap(size)
        pixmap.fill(QtCore.Qt.GlobalColor.transparent)
        painter = QtGui.QPainter(pixmap)
        self.paint(painter, QtCore.QRect(QtCore.QPoint(), size), mode, state)
        painter.end()
        return pixmap


def ui_icon(name: str, color: str = '#151515') -> QtGui.QIcon:
    return QtGui.QIcon(_IconEngine(name, color))
