"""Neutral graph-paper backdrop and optical glass surfaces for the native UI."""
from __future__ import annotations

import math

from PIL import Image
from PySide6 import QtCore, QtGui, QtWidgets

GRID_STEP = 24


def draw_grid(painter, rect, origin=QtCore.QPointF(), *, alpha=18, refract=False):
    """Keep the grid phase continuous; bend it only inside a glass lens."""
    painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
    painter.setPen(QtGui.QPen(QtGui.QColor(45, 45, 45, alpha), .55))
    first_x = math.floor((rect.left()+origin.x())/GRID_STEP)*GRID_STEP-origin.x()
    first_y = math.floor((rect.top()+origin.y())/GRID_STEP)*GRID_STEP-origin.y()
    x, y = first_x, first_y
    bend = min(10.0, rect.height()/3)
    while x <= rect.right()+GRID_STEP:
        if refract:
            shift = (x-rect.center().x())/max(1, rect.width()/2)*2.5
            path = QtGui.QPainterPath(QtCore.QPointF(x+shift, rect.top()))
            path.quadTo(x, rect.top()+bend*.4, x, rect.top()+bend)
            path.lineTo(x, rect.bottom()-bend)
            path.quadTo(x, rect.bottom()-bend*.4, x+shift, rect.bottom())
            painter.drawPath(path)
        else:
            painter.drawLine(QtCore.QLineF(x, rect.top(), x, rect.bottom()))
        x += GRID_STEP
    while y <= rect.bottom()+GRID_STEP:
        if refract:
            shift = (y-rect.center().y())/max(1, rect.height()/2)*2.5
            path = QtGui.QPainterPath(QtCore.QPointF(rect.left(), y+shift))
            path.quadTo(rect.left()+bend*.4, y, rect.left()+bend, y)
            path.lineTo(rect.right()-bend, y)
            path.quadTo(rect.right()-bend*.4, y, rect.right(), y+shift)
            painter.drawPath(path)
        else:
            painter.drawLine(QtCore.QLineF(rect.left(), y, rect.right(), y))
        y += GRID_STEP


def rounded_path(rect, radius):
    path = QtGui.QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    return path


def lens_sample(x, y, geometry):
    """Inverse lens map: a rounded volume bends rays near its curved wall."""
    cx, cy, half_width, half_height, radius, thickness = geometry
    dx, dy = x-cx, y-cy
    qx, qy = abs(dx)-(half_width-radius), abs(dy)-(half_height-radius)
    ax, ay = max(qx, 0), max(qy, 0)
    length = math.hypot(ax, ay)
    distance = length+min(max(qx, qy), 0)-radius
    if length > .0001:
        nx, ny = ax/length, ay/length
    else:
        nx, ny = (1, 0) if qx > qy else (0, 1)
    nx, ny = math.copysign(nx, dx), math.copysign(ny, dy)
    depth = max(0, -distance)
    bend = thickness*.82*max(0, 1-depth/thickness)**2
    return x-nx*bend, y-ny*bend


def refracted_backdrop(widget, rect, radius, thickness):
    """Resample the app's actual grid plane; never capture the desktop or text.

    A bounded mesh is rasterized by Pillow once per geometry/grid phase. Hover
    lighting uses QPainter, so mouse movement does not rebuild this image.
    """
    canvas = getattr(widget.window(), 'canvas', widget.window())
    origin = widget.mapTo(canvas, QtCore.QPoint())
    dpr = widget.devicePixelRatioF()
    key = (widget.width(), widget.height(), dpr, origin.x()%GRID_STEP, origin.y()%GRID_STEP,
           rect.x(), rect.y(), rect.width(), rect.height(), radius, thickness)
    cached = getattr(widget, '_lens_cache', None)
    if cached and cached[0] == key:
        return cached[1]
    padding = math.ceil(thickness+3)
    width, height = math.ceil(widget.width()*dpr), math.ceil(widget.height()*dpr)
    source = QtGui.QImage(math.ceil((widget.width()+padding*2)*dpr),
                          math.ceil((widget.height()+padding*2)*dpr), QtGui.QImage.Format.Format_RGBA8888)
    source.setDevicePixelRatio(dpr)
    source.fill(QtGui.QColor('#ffffff'))
    background = QtGui.QPainter(source)
    background.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    draw_grid(background, QtCore.QRectF(0, 0, source.width()/dpr, source.height()/dpr),
              QtCore.QPointF(origin.x()-padding, origin.y()-padding), alpha=32)
    background.end()
    pixels = Image.frombytes('RGBA', (source.width(), source.height()), bytes(source.constBits()),
                             'raw', 'RGBA', source.bytesPerLine())
    mesh = []
    step = max(4, round(3*dpr))
    columns, rows = [*range(0, width, step), width], [*range(0, height, step), height]
    geometry = (rect.center().x(), rect.center().y(), rect.width()/2, rect.height()/2, radius, thickness)
    samples = []
    for py in rows:
        line = []
        for px in columns:
            sx, sy = lens_sample(px/dpr, py/dpr, geometry)
            line.append(((sx+padding)*dpr, (sy+padding)*dpr))
        samples.append(line)
    for iy, (top, bottom) in enumerate(zip(rows, rows[1:])):
        for ix, (left, right) in enumerate(zip(columns, columns[1:])):
            quad = samples[iy][ix]+samples[iy+1][ix]+samples[iy+1][ix+1]+samples[iy][ix+1]
            mesh.append(((left, top, right, bottom), quad))
    warped = pixels.transform((width, height), Image.Transform.MESH, mesh, Image.Resampling.BICUBIC)
    image = QtGui.QImage(warped.tobytes(), width, height, width*4, QtGui.QImage.Format.Format_RGBA8888).copy()
    image.setDevicePixelRatio(dpr)
    widget._lens_cache = (key, image)
    return image


def paint_control_glass(widget, painter, scale, *, pressed=False, hover=0):
    painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    rect = QtCore.QRectF(widget.rect()).adjusted(3*scale, 3*scale, -3*scale, -3*scale)
    if pressed:
        rect.adjust(.6, .8, -.6, -.3)
    radius = min(38*scale, rect.height()*.46)
    path = rounded_path(rect, radius)
    focused = widget.hasFocus()
    reduced = bool(QtWidgets.QApplication.instance().property('reduceTransparency'))
    if reduced:
        painter.fillPath(path, QtGui.QColor('#e8e8e8' if focused else '#f7f7f7'))
        painter.setPen(QtGui.QPen(QtGui.QColor('#b3b3b3'), .8))
        painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        painter.drawPath(path)
        return
    thickness = min(rect.height()*.30, 18*scale)
    painter.save()
    painter.setClipPath(path)
    painter.drawImage(QtCore.QPointF(), refracted_backdrop(widget, rect, radius, thickness))
    # A quiet neutral environment reflection gives the clear volume depth.
    body = QtGui.QLinearGradient(rect.topLeft(), rect.bottomRight())
    for stop, gray, alpha in ((0, 150, 12), (.22, 90, 7), (.60, 65, 22), (.86, 60, 8), (1, 255, 65)):
        body.setColorAt(stop, QtGui.QColor(gray, gray, gray, alpha))
    painter.fillPath(path, body)
    if focused:
        painter.fillPath(path, QtGui.QColor(0, 0, 0, 13))
    # Continuous shaded bevel, not several concentric outline strokes.
    for index in range(math.ceil(thickness*2)):
        inset = index*.5
        outer = rect.adjusted(inset, inset, -inset, -inset)
        inner = outer.adjusted(.55, .55, -.55, -.55)
        band = rounded_path(outer, max(0, radius-inset)).subtracted(rounded_path(inner, max(0, radius-inset-.55)))
        strength = math.exp(-((inset-1.3*scale)/(1.8*scale))**2)
        shade = QtGui.QLinearGradient(rect.topLeft(), rect.bottomLeft())
        for stop, gray, opacity in ((0, 145, 35), (.20, 90, 46), (.50, 85, 50),
                                    (.80, 135, 40), (1, 255, 190)):
            shade.setColorAt(stop, QtGui.QColor(gray, gray, gray, round(opacity*strength)))
        painter.fillPath(band, shade)
    if hover or pressed:
        point = getattr(widget, '_light_position', QtCore.QPointF(rect.width()*.28, rect.height()*.2))
        light = QtGui.QRadialGradient(point, max(rect.width()*.65, rect.height()*2))
        light.setColorAt(0, QtGui.QColor(255, 255, 255, round(90*(1 if pressed else hover))))
        light.setColorAt(1, QtCore.Qt.GlobalColor.transparent)
        painter.fillPath(path, light)
    painter.restore()
    # One thin Fresnel edge changes brightness around the curved silhouette.
    edge = QtGui.QLinearGradient(rect.topLeft(), rect.bottomLeft())
    for stop, gray, alpha in ((0, 255, 255), (.23, 180, 100), (.5, 135, 105), (.7, 190, 65), (1, 255, 255)):
        edge.setColorAt(stop, QtGui.QColor(gray, gray, gray, alpha))
    painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
    painter.setPen(QtGui.QPen(edge, max(.8, scale)))
    painter.drawPath(path)


class PaperGlassCanvas(QtWidgets.QWidget):
    """Opaque white content pane inside a genuinely translucent window rim."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMouseTracking(True)

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        painter.setCompositionMode(QtGui.QPainter.CompositionMode.CompositionMode_Source)
        painter.fillRect(self.rect(), QtCore.Qt.GlobalColor.transparent)
        painter.setCompositionMode(QtGui.QPainter.CompositionMode.CompositionMode_SourceOver)
        outer = QtCore.QRectF(self.rect()).adjusted(2, 2, -2, -2)
        radius = 18 if self.width() < 800 else 24
        outer_path = rounded_path(outer, radius)
        reduced = bool(QtWidgets.QApplication.instance().property('reduceTransparency'))
        tint = QtGui.QLinearGradient(outer.topLeft(), outer.bottomRight())
        for position, alpha in ((0, 220), (.35, 125), (.65, 155), (1, 210)):
            tint.setColorAt(position, QtGui.QColor(255, 255, 255, 255 if reduced else alpha))
        painter.fillPath(outer_path, tint)
        inner = outer.adjusted(7, 7, -7, -7)
        inner_path = rounded_path(inner, radius-7)
        painter.fillPath(inner_path, QtGui.QColor('#ffffff'))
        painter.save()
        painter.setClipPath(inner_path)
        draw_grid(painter, inner)
        painter.restore()
        if not reduced:
            rim_path = outer_path.subtracted(inner_path)
            painter.save()
            painter.setClipPath(rim_path)
            draw_grid(painter, outer, alpha=48, refract=True)
            painter.restore()
        painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        for inset, color, width in ((0, QtGui.QColor(145,145,145,95), .8),
                                    (1.3, QtGui.QColor(255,255,255,240), 1.4),
                                    (3.8, QtGui.QColor(165,165,165,70), .7),
                                    (6.3, QtGui.QColor(255,255,255,230), 1.4)):
            edge = outer.adjusted(inset, inset, -inset, -inset)
            painter.setPen(QtGui.QPen(color, width))
            painter.drawRoundedRect(edge, radius-inset, radius-inset)
