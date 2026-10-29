"""Export only Copyer's existing glyph outlines; QtAwesome is needed at export time only."""
from __future__ import annotations

import json
import os
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6 import QtGui, QtWidgets
import qtawesome

ROOT = Path(__file__).resolve().parents[1]
FONTS = Path(qtawesome.__file__).parent / 'fonts'
FAMILIES = {
    'ph': ('phosphor-1.3.0.ttf', 'phosphor-charmap-1.3.0.json'),
    'ri': ('remixicon-2.5.0.ttf', 'remixicon-charmap-2.5.0.json'),
    'mdi': ('materialdesignicons5-webfont-5.9.55.ttf', 'materialdesignicons5-webfont-charmap-5.9.55.json'),
}
NAMES = {'sd':'ri.sd-card-line', 'folder-outline':'ph.folder', 'cog-outline':'ph.gear-six',
         'refresh':'ph.arrow-clockwise', 'chevron-down':'ph.caret-down', 'chevron-right':'ph.caret-right',
         'window-minimize':'ph.minus', 'window-maximize':'ph.square', 'close':'ph.x',
         'check':'mdi.check', 'minus':'mdi.minus', 'alert-outline':'mdi.alert-outline'}


def export():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    icons = {}
    for name, original in NAMES.items():
        prefix, character = original.split('.', 1)
        font_file, charmap_file = FAMILIES[prefix]
        charmap = json.loads((FONTS / charmap_file).read_text(encoding='utf-8'))
        raw = QtGui.QRawFont(str(FONTS / font_file), 1000)
        assert raw.isValid(), font_file
        glyph = raw.glyphIndexesForString(chr(int(charmap[character], 16)))[0]
        assert glyph, original
        path = raw.pathForGlyph(glyph)
        commands, index = [], 0
        while index < path.elementCount():
            element = path.elementAt(index)
            if element.isMoveTo() or element.isLineTo():
                commands.append(['M' if element.isMoveTo() else 'L', round(element.x, 4), round(element.y, 4)])
                index += 1
            else:
                points = [path.elementAt(index + offset) for offset in range(3)]
                commands.append(['C', *(round(value, 4) for point in points for value in (point.x, point.y))])
                index += 3
        icons[name] = dict(source=original, advance=raw.advancesForGlyphIndexes([glyph])[0].x(),
                           ascent=raw.ascent(), descent=raw.descent(), path=commands)
    destination = ROOT / 'assets' / 'ui-icons.json'
    destination.parent.mkdir(exist_ok=True)
    destination.write_text(json.dumps(icons, separators=(',', ':')) + '\n', encoding='utf-8')
    print(f'{len(icons)} icons, {destination.stat().st_size} bytes')


if __name__ == '__main__':
    export()
