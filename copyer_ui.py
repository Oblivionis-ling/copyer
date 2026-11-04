"""Native Qt interface for the approved Copyer 1.5 design."""
from __future__ import annotations

import ctypes
import os
import sys
import time
from collections import Counter
from dataclasses import replace
from pathlib import Path
from threading import Event

from PySide6 import QtCore, QtGui, QtWidgets

import copyer_core as core
import copyer_update as updater
from copyer_version import APP_AUTHOR, APP_VERSION
from copyer_materials import PaperGlassCanvas, paint_control_glass
from copyer_icons import ui_icon

APP_ORGANIZATION = "copyer"
APP_NAME = "copyer"
WINDOW_TITLE = f"Copyer {APP_VERSION}"
# Codex's Windows default uses the system UI stack (Segoe UI), with CJK fallback.
UI_FONT_CANDIDATES = ("Segoe UI", "Microsoft YaHei UI", "Microsoft YaHei", "Noto Sans SC")


def default_window_size(screen) -> QtCore.QSize:
    available = screen.availableGeometry()
    return QtCore.QSize(min(700, available.width()-24), min(526, available.height()-24))


def resource_path(name: str) -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / name


def font(widget: QtWidgets.QWidget, pixels: float, *, bold: bool = False, medium: bool = False) -> None:
    value = QtGui.QFont(widget.font())
    value.setPixelSize(max(11, round(pixels)))
    value.setWeight(QtGui.QFont.Weight.DemiBold if bold else (QtGui.QFont.Weight.Medium if medium else QtGui.QFont.Weight.Normal))
    widget.setFont(value)


def configure_application_font() -> str:
    app = QtWidgets.QApplication.instance()
    available = set(QtGui.QFontDatabase.families())
    # Qt's offscreen platform on Windows does not enumerate system fonts.
    # Explicitly register the same Windows families for captures and UI tests.
    if os.name == "nt" and "Microsoft YaHei UI" not in available:
        directory = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
        for filename in ("msyh.ttc", "msyhbd.ttc", "segoeui.ttf", "segoeuib.ttf"):
            path = directory / filename
            if path.exists():
                QtGui.QFontDatabase.addApplicationFont(str(path))
        available = set(QtGui.QFontDatabase.families())
    family = next((name for name in UI_FONT_CANDIDATES if name in available), "Segoe UI")
    value = QtGui.QFont(family)
    value.setFamilies([name for name in UI_FONT_CANDIDATES if name in available])
    value.setPixelSize(16)
    value.setStyleStrategy(QtGui.QFont.StyleStrategy.PreferAntialias)
    app.setFont(value)
    return family


def configure_qt_translations() -> None:
    app = QtWidgets.QApplication.instance()
    if hasattr(app, "_copyer_translators"):
        return
    app._copyer_translators = []
    for catalog in ("qt_zh_CN", "qtbase_zh_CN"):
        translator = QtCore.QTranslator(app)
        if translator.load(catalog, QtCore.QLibraryInfo.path(QtCore.QLibraryInfo.LibraryPath.TranslationsPath)):
            app.installTranslator(translator)
            app._copyer_translators.append(translator)


def system_reduce_transparency() -> bool:
    if os.name == "nt":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
                return not bool(winreg.QueryValueEx(key, "EnableTransparency")[0])
        except OSError:
            pass
    return False


def system_reduce_motion() -> bool:
    if os.name == "nt":
        enabled = ctypes.c_int(1)
        if ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(enabled), 0):
            return not bool(enabled.value)
    return False


def apply_theme() -> None:
    app = QtWidgets.QApplication.instance()
    app.setStyle("Fusion")
    configure_application_font()
    configure_qt_translations()
    palette = QtGui.QPalette()
    for role, color in ((QtGui.QPalette.Window, "#ffffff"), (QtGui.QPalette.Base, "#ffffff"),
                        (QtGui.QPalette.WindowText, "#151515"), (QtGui.QPalette.Text, "#151515"),
                        (QtGui.QPalette.Button, "#ffffff"), (QtGui.QPalette.ButtonText, "#151515"),
                        (QtGui.QPalette.Highlight, "#e9e9e9"), (QtGui.QPalette.HighlightedText, "#151515")):
        palette.setColor(role, QtGui.QColor(color))
    app.setPalette(palette)
    app.setStyleSheet("""
        QWidget { color: #151515; }
        QMainWindow, QDialog { background: white; }
        QPushButton, QToolButton { border: 0; outline: 0; background: transparent; padding: 5px; border-radius: 5px; }
        QPushButton:hover, QToolButton:hover { background: rgba(0,0,0,9); border-radius: 5px; }
        QPushButton:focus, QToolButton:focus { outline: 0; border: 0; background: rgba(0,0,0,18); }
        QPushButton:pressed, QToolButton:pressed { background: rgba(0,0,0,28); }
        QPushButton:disabled, QToolButton:disabled, QLabel:disabled, QLineEdit:disabled { color: #929292; }
        QLineEdit { background: transparent; border: 0; border-bottom: 1px solid #d0d0d0; padding: 4px 10px 8px; selection-background-color: #dedede; }
        QLineEdit:focus { border-bottom: 2px solid #656565; }
        QLineEdit[invalid="true"] { border-bottom: 2px dashed #333; }
        QScrollArea, QTableView { background: transparent; border: 0; outline: 0; }
        QTableView { gridline-color: #e8e8e8; selection-background-color: #ededed; }
        QTableView::item:focus { outline: 0; }
        QHeaderView::section { background: white; border: 0; border-bottom: 1px solid #ddd; padding: 12px; }
        QScrollBar:vertical { background: transparent; width: 8px; margin: 0; }
        QScrollBar::handle:vertical { background: #d0d0d0; border-radius: 4px; min-height: 28px; }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        QMenu { background: white; border: 1px solid #ddd; padding: 6px; }
        QMenu::item { padding: 8px 20px; }
        QMenu::item:selected { background: #eeeeee; }
        QToolTip { color: #222; background: #fafafa; border: 1px solid #ddd; padding: 6px; }
        QDialog QPushButton { border: 0; border-radius: 7px; padding: 7px 16px; }
        QComboBox { background: white; border: 1px solid #ccc; padding: 8px; border-radius: 5px; }
    """)


def detect_removable_drives() -> list[str]:
    if os.name != "nt":
        return []
    drives = ctypes.windll.kernel32.GetLogicalDrives()
    return [root for index in range(26) if drives & (1 << index)
            for root in [f"{chr(65 + index)}:\\"]
            if ctypes.windll.kernel32.GetDriveTypeW(ctypes.c_wchar_p(root)) == 2]


def source_name(path: str) -> str:
    if not path:
        return "选择来源"
    value = Path(path)
    if os.name == "nt" and value.drive:
        label = ctypes.create_unicode_buffer(261)
        if ctypes.windll.kernel32.GetVolumeInformationW(ctypes.c_wchar_p(value.anchor), label, 261, None, None, None, None, 0) and label.value:
            return f"{label.value} ({value.drive})"
    return value.name or value.drive or str(value)


def format_bytes(amount: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if amount < 1024 or unit == "TB":
            return f"{amount:.0f} {unit}" if amount >= 100 or unit == "B" else f"{amount:.1f} {unit}"
        amount /= 1024
    return "0 B"


class ElidedLabel(QtWidgets.QLabel):
    def setText(self, text: str) -> None:
        super().setText(text)
        self.setToolTip(text)

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        painter = QtGui.QPainter(self)
        color = self.palette().color(QtGui.QPalette.ColorGroup.Active if self.isEnabled() else QtGui.QPalette.ColorGroup.Disabled,
                                     QtGui.QPalette.ColorRole.WindowText)
        painter.setPen(color)
        painter.setFont(self.font())
        text = self.fontMetrics().elidedText(self.text(), QtCore.Qt.TextElideMode.ElideMiddle, self.width())
        painter.drawText(self.rect(), self.alignment() | QtCore.Qt.AlignmentFlag.AlignVCenter, text)


glass_paint = paint_control_glass

def install_shadow(widget: QtWidgets.QWidget) -> None:
    shadow = QtWidgets.QGraphicsDropShadowEffect(widget)
    shadow.setColor(QtGui.QColor(0, 0, 0, 32))
    shadow.setBlurRadius(24)
    shadow.setOffset(0, 6)
    widget.setGraphicsEffect(shadow)


class GlassSurface(QtWidgets.QWidget):
    scale = 1.0

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)
        install_shadow(self)

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        glass_paint(self, painter, self.scale)


class GlassButton(QtWidgets.QPushButton):
    scale = 1.0

    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self._hover = 0.0
        self._animation = QtCore.QPropertyAnimation(self, b"hoverAmount", self)
        self._animation.setDuration(130)
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName(text)
        self.setMouseTracking(True)
        self._light_position = QtCore.QPointF()
        install_shadow(self)

    def setText(self, value):
        super().setText(value)
        self.setAccessibleName(value)
        self.setToolTip(value)

    def get_hover(self):
        return self._hover

    def set_hover(self, value):
        self._hover = value
        self.update()

    hoverAmount = QtCore.Property(float, get_hover, set_hover)

    def _animate(self, value):
        self._animation.stop()
        if QtWidgets.QApplication.instance().property("reduceMotion"):
            self.set_hover(value)
        else:
            self._animation.setStartValue(self._hover)
            self._animation.setEndValue(value)
            self._animation.start()

    def enterEvent(self, event):
        self._animate(1)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._animate(0)
        super().leaveEvent(event)

    def mouseMoveEvent(self, event):
        if not QtWidgets.QApplication.instance().property("reduceMotion"):
            self._light_position = event.position()
            self.update()
        super().mouseMoveEvent(event)

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        glass_paint(self, painter, self.scale, pressed=self.isDown(), hover=self._hover)
        painter.setFont(self.font())
        painter.setPen(QtGui.QColor("#151515" if self.isEnabled() else "#929292"))
        text_rect = self.rect().adjusted(8, 0, -8, 0).translated(0, 1 if self.isDown() else 0)
        text = self.fontMetrics().elidedText(self.text(), QtCore.Qt.TextElideMode.ElideMiddle, text_rect.width())
        painter.drawText(text_rect, QtCore.Qt.AlignmentFlag.AlignCenter, text)


class SmallCheckBox(QtWidgets.QCheckBox):
    scale = 1.0

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self._check_icon = ui_icon("check", "#ffffff")
        self._mixed_icon = ui_icon("minus", "#ffffff")
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)

    def nextCheckState(self):
        self.setCheckState(QtCore.Qt.CheckState.Unchecked if self.checkState() == QtCore.Qt.CheckState.Checked else QtCore.Qt.CheckState.Checked)

    def hitButton(self, point):
        return self.rect().contains(point)

    def sizeHint(self):
        return QtCore.QSize(self.text_offset() + self.fontMetrics().horizontalAdvance(self.text()) + 5,
                            max(30, self.fontMetrics().height() + 12))

    def text_offset(self):
        return 2 + max(15, round(22*self.scale)) + max(5, round(6*self.scale))

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        if self.hasFocus():
            painter.setPen(QtCore.Qt.PenStyle.NoPen)
            painter.setBrush(QtGui.QColor(0, 0, 0, 15))
            painter.drawRoundedRect(self.rect().adjusted(0, 1, -1, -1), 4, 4)
        size = max(15, round(22 * self.scale))
        box = QtCore.QRectF(2, (self.height() - size) / 2, size, size)
        selected = self.checkState() != QtCore.Qt.CheckState.Unchecked
        ink = QtGui.QColor("#181818" if self.isEnabled() else "#999999")
        painter.setPen(QtGui.QPen(ink if selected else QtGui.QColor("#b0b0b0"), 1))
        painter.setBrush(ink if selected else QtCore.Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(box, 1, 1)
        if selected:
            icon = self._mixed_icon if self.checkState() == QtCore.Qt.CheckState.PartiallyChecked else self._check_icon
            icon.paint(painter, box.adjusted(1, 1, -1, -1).toRect())
        if self.text():
            painter.setPen(QtGui.QColor("#151515" if self.isEnabled() else "#999999"))
            painter.setFont(self.font())
            painter.drawText(self.rect().adjusted(self.text_offset(), 0, 0, 0), QtCore.Qt.AlignmentFlag.AlignVCenter, self.text())


class ImportProgressBar(QtWidgets.QProgressBar):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._clock = QtCore.QElapsedTimer()
        self._clock.start()
        self._animation_timer = QtCore.QTimer(self)
        self._animation_timer.setInterval(33)
        self._animation_timer.timeout.connect(self.update)

    def setRange(self, minimum, maximum):
        super().setRange(minimum, maximum)
        if minimum == maximum == 0 and not QtWidgets.QApplication.instance().property("reduceMotion"):
            self._animation_timer.start()
        else:
            self._animation_timer.stop()
        self.update()

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        rect = QtCore.QRectF(self.rect())
        radius = rect.height()/2
        path = QtGui.QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        painter.fillPath(path, QtGui.QColor("#e6e6e6"))
        painter.setClipPath(path)
        if self.minimum() == self.maximum() == 0:
            width = rect.width()*.28
            x = (rect.width()-width)/2 if not self._animation_timer.isActive() else (self._clock.elapsed()%1400)/1400*(rect.width()+width)-width
        else:
            ratio = max(0, (self.value()-self.minimum())/max(1, self.maximum()-self.minimum()))
            x, width = 0, rect.width()*min(1, ratio)
        if width > 0:
            painter.setPen(QtCore.Qt.PenStyle.NoPen)
            painter.setBrush(QtGui.QColor("#555555"))
            painter.drawRoundedRect(QtCore.QRectF(x, 0, width, rect.height()), min(radius, width/2), radius)


class PathCard(QtWidgets.QWidget):
    choose_requested = QtCore.Signal()
    devices_requested = QtCore.Signal()

    def __init__(self, source: bool, parent=None):
        super().__init__(parent)
        self.source = source
        self.caption = QtWidgets.QLabel("来源" if source else "导入到", self)
        self.surface = GlassSurface(self)
        self.path_icon = QtWidgets.QLabel(self.surface)
        self.main_text = ElidedLabel("选择来源" if source else "选择目标", self.surface)
        self.arrow = QtWidgets.QToolButton(self.surface)
        self.arrow.setIcon(ui_icon("chevron-down"))
        self.arrow.setAccessibleName("选择来源设备")
        self.arrow.setToolTip("选择来源设备")
        self.arrow.clicked.connect(self.devices_requested)
        self.arrow.setVisible(source)
        self.choose_button = QtWidgets.QPushButton("选择文件夹", self.surface)
        self.choose_button.setIcon(ui_icon("folder-outline"))
        self.choose_button.setAccessibleName("选择来源文件夹" if source else "选择目标文件夹")
        self.choose_button.clicked.connect(self.choose_requested)
        self.separator = QtWidgets.QFrame(self.surface)
        self.separator.setStyleSheet("background:#d5d5d5")
        self.path = ""
        self.scale = 1.0
        self.choose_button.setToolTip(self.choose_button.accessibleName())

    def set_path(self, value: str):
        self.path = value
        self.main_text.setText(source_name(value) if self.source else (value or "选择目标"))
        self.relayout(self.scale)

    def relayout(self, scale: float):
        self.scale = scale
        self.surface.scale = scale
        self.choose_button.setText("")
        self.choose_button.setStyleSheet("padding:0;")
        self.arrow.setStyleSheet("padding:0;")
        if self.path:
            self.main_text.setText(source_name(self.path) if self.source else (Path(self.path).name or self.path))
            self.main_text.setToolTip(self.path)
            self.main_text.setAccessibleDescription(self.path)
        shadow = self.surface.graphicsEffect()
        shadow.setBlurRadius(11)
        shadow.setOffset(0, 3)
        caption_height = 13
        body_height = self.height()-caption_height-5
        self.caption.setGeometry(8, 0, self.width()-16, caption_height)
        font(self.caption, 11)
        self.surface.setGeometry(0, caption_height, self.width(), body_height)
        w, h = self.surface.width(), self.surface.height()
        self.path_icon.setGeometry(8, (h-22)//2, 22, 22)
        self.path_icon.setPixmap(ui_icon("sd" if self.source else "folder-outline").pixmap(22, 22))
        self.choose_button.setGeometry(w-34, 3, 29, h-6)
        self.choose_button.setIconSize(QtCore.QSize(21, 21))
        self.separator.setGeometry(w-39, 8, 1, max(8, h-16))
        self.main_text.setGeometry(34, 2, max(10, w-78-(21 if self.source else 0)), h-4)
        font(self.main_text, 12, medium=True)
        if self.source:
            self.arrow.setGeometry(w-62, 3, 21, h-6)
            self.arrow.setIconSize(QtCore.QSize(15, 15))
        self.surface.update()


class GroupRow(QtWidgets.QWidget):
    selection_changed = QtCore.Signal(str, bool)
    suffix_changed = QtCore.Signal(str, str)

    def __init__(self, day: str, files: list[core.MediaFile], parent=None):
        super().__init__(parent)
        self.day, self.files = day, files
        self.check = SmallCheckBox(parent=self)
        self.check.setTristate(True)
        self.check.setAccessibleName(f"选择 {day} 的文件")
        self.check.clicked.connect(lambda checked: self.selection_changed.emit(self.day, checked))
        self.date_label = QtWidgets.QLabel(day, self)
        self.suffix = QtWidgets.QLineEdit(self)
        self.suffix.setPlaceholderText("添加后缀")
        self.suffix.setAccessibleName(f"{day} 的自定义后缀，可选")
        self.suffix.setStyleSheet("QLineEdit { padding:0px 3px 2px; }")
        self.suffix.setMaxLength(120)
        self.suffix.textChanged.connect(lambda value: self.suffix_changed.emit(self.day, value))
        self.count = QtWidgets.QLabel(str(len(files)), self)
        self.count.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.warning = QtWidgets.QLabel(self)
        self.warning.hide()
        self.scale = 1.0

    def relayout(self, scale: float):
        self.scale = s = scale
        height = round(48*s)
        self.setFixedHeight(height)
        self.check.scale = s
        self.check.setGeometry(1, 0, 25, height)
        field_x = 118 if self.width() >= 310 else 101
        self.date_label.setGeometry(30, 0, field_x-34, height)
        self.suffix.setGeometry(field_x, 0, max(25, self.width()-field_x-92), height-1)
        self.count.setGeometry(self.width()-64, 0, 64, height)
        self.warning.setGeometry(self.width()-86, (height-14)//2, 14, 14)
        self.warning.setPixmap(ui_icon("alert-outline").pixmap(14, 14))
        for widget in (self.date_label, self.suffix, self.count):
            font(widget, 22*s, medium=True)
        self.update()

    def resizeEvent(self, event):
        self.relayout(self.scale)

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setPen(QtGui.QColor("#d9d9d9"))
        painter.drawLine(0, self.height()-1, self.width(), self.height()-1)


class TaskWorker(QtCore.QThread):
    progress = QtCore.Signal(object)
    result = QtCore.Signal(object)
    error = QtCore.Signal(str)

    def __init__(self, operation, cancel: Event, parent=None):
        super().__init__(parent)
        self.operation, self.cancel = operation, cancel

    @QtCore.Slot()
    def run(self):
        try:
            self.result.emit(self.operation(self.cancel, self.progress.emit))
        except Exception as exc:
            self.error.emit(str(exc))


class SelectionDelegate(QtWidgets.QStyledItemDelegate):
    """Keep the row's gray selection fill without a native dotted focus frame."""
    def paint(self, painter, option, index):
        styled = QtWidgets.QStyleOptionViewItem(option)
        styled.state &= ~QtWidgets.QStyle.StateFlag.State_HasFocus
        super().paint(painter, styled, index)


class ThemedDialog(QtWidgets.QDialog):
    """Shared app-owned dialog chrome, typography, keyboard actions and dragging."""
    def __init__(self, parent, title, size=(500, 400)):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setWindowFlags(QtCore.Qt.WindowType.Dialog | QtCore.Qt.WindowType.FramelessWindowHint)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setObjectName("copyerDialog")
        self.setStyleSheet("QDialog#copyerDialog { background:transparent; }")
        font(self, 16)
        self.canvas = PaperGlassCanvas(self)
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.canvas)
        self.body = QtWidgets.QVBoxLayout(self.canvas)
        self.body.setContentsMargins(24, 16, 24, 18)
        self.body.setSpacing(12)
        self.header = QtWidgets.QWidget(self.canvas)
        header_layout = QtWidgets.QHBoxLayout(self.header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        self.heading = QtWidgets.QLabel(title, self.header)
        font(self.heading, 16, medium=True)
        header_layout.addWidget(self.heading, 1)
        self.close_button = QtWidgets.QToolButton(self.header)
        self.close_button.setIcon(ui_icon("close"))
        self.close_button.setIconSize(QtCore.QSize(20, 20))
        self.close_button.setFixedSize(30, 30)
        self.close_button.setAccessibleName("关闭" + title)
        self.close_button.setToolTip("关闭")
        self.close_button.clicked.connect(self.reject)
        header_layout.addWidget(self.close_button)
        self.body.addWidget(self.header)
        self.content_layout = QtWidgets.QVBoxLayout()
        self.content_layout.setSpacing(10)
        self.body.addLayout(self.content_layout, 1)
        self._drag_offset = None
        self._positioned = False
        self.header.installEventFilter(self)
        self.heading.installEventFilter(self)
        available = self.screen().availableGeometry()
        self.resize(min(size[0], available.width()-24), min(size[1], available.height()-24))

    def add_actions(self, accept_text="确定", cancel_text=None, *, default_accept=True):
        row = QtWidgets.QHBoxLayout()
        row.setContentsMargins(0, 4, 0, 6)
        row.setSpacing(10)
        row.addStretch()
        self.cancel_button = None
        if cancel_text:
            self.cancel_button = QtWidgets.QPushButton(cancel_text, self.canvas)
            self.cancel_button.setAutoDefault(False)
            self.cancel_button.setMinimumSize(84, 38)
            self.cancel_button.clicked.connect(self.reject)
            row.addWidget(self.cancel_button)
        self.accept_button = GlassButton(accept_text, self.canvas)
        self.accept_button.scale = .75
        self.accept_button.setMinimumSize(100, 42)
        self.accept_button.setAutoDefault(False)
        self.accept_button.clicked.connect(self.accept)
        row.addWidget(self.accept_button)
        self.body.addLayout(row)
        default = self.accept_button if default_accept or self.cancel_button is None else self.cancel_button
        default.setDefault(True)
        default.setFocus()

    def showEvent(self, event):
        super().showEvent(event)
        if not self._positioned:
            available = self.screen().availableGeometry()
            center = self.parentWidget().frameGeometry().center() if self.parentWidget() else available.center()
            position = center-QtCore.QPoint(self.width()//2, self.height()//2)
            position.setX(max(available.left(), min(position.x(), available.right()-self.width()+1)))
            position.setY(max(available.top(), min(position.y(), available.bottom()-self.height()+1)))
            self.move(position)
            self._positioned = True

    def eventFilter(self, watched, event):
        if watched in (self.header, self.heading):
            if event.type() == QtCore.QEvent.Type.MouseButtonPress and event.button() == QtCore.Qt.MouseButton.LeftButton:
                self._drag_offset = event.globalPosition().toPoint()-self.pos()
                return True
            if event.type() == QtCore.QEvent.Type.MouseMove and self._drag_offset is not None and event.buttons() & QtCore.Qt.MouseButton.LeftButton:
                self.move(event.globalPosition().toPoint()-self._drag_offset)
                return True
            if event.type() == QtCore.QEvent.Type.MouseButtonRelease:
                self._drag_offset = None
                return True
        return super().eventFilter(watched, event)


class MessageDialog(ThemedDialog):
    def __init__(self, parent, title, message, *, question=False):
        super().__init__(parent, title, (440, 205))
        label = QtWidgets.QLabel(message, self.canvas)
        label.setWordWrap(True)
        label.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
        self.content_layout.addWidget(label)
        self.add_actions("停止并关闭" if question else "确定", "继续任务" if question else None,
                         default_accept=not question)


class SettingsPage(QtWidgets.QWidget):
    """Settings stay inside the main window and persist when changed."""
    def __init__(self, owner):
        super().__init__(owner.canvas)
        self.owner = owner
        font(self, 13)
        self.setStyleSheet("QLabel, QPushButton, QCheckBox { font-size:13px; } "
                          "QLabel#settingsHeading { font-size:14px; }")
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(8, 0, 8, 6)
        outer.setSpacing(12)
        header = QtWidgets.QHBoxLayout()
        self.back_button = QtWidgets.QPushButton("← 返回")
        self.back_button.setAccessibleName("返回主页面")
        self.back_button.setMinimumSize(70, 32)
        self.back_button.clicked.connect(owner.show_home)
        header.addWidget(self.back_button)
        heading = QtWidgets.QLabel("设置")
        heading.setObjectName("settingsHeading")
        font(heading, 14, medium=True)
        header.addWidget(heading)
        header.addStretch()
        outer.addLayout(header)
        self.scroll = QtWidgets.QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet("QScrollArea, QScrollArea > QWidget > QWidget { background:transparent; }")
        self.scroll.viewport().setAutoFillBackground(False)
        content = QtWidgets.QWidget()
        content.setAutoFillBackground(False)
        columns = QtWidgets.QHBoxLayout(content)
        columns.setContentsMargins(0, 0, 0, 0)
        self.form = QtWidgets.QWidget()
        self.form.setMaximumWidth(660)
        layout = QtWidgets.QVBoxLayout(self.form)
        layout.setContentsMargins(0, 0, 8, 12)
        layout.setSpacing(12)
        def section(title):
            label = QtWidgets.QLabel(title)
            font(label, 13, medium=True)
            layout.addWidget(label)
        section("导入")
        layout.addWidget(QtWidgets.QLabel("同名文件自动重命名，已有文件不会被覆盖。"))
        self.duplicate = SmallCheckBox("跳过内容完全相同的文件")
        self.video_time = SmallCheckBox("视频容器时间按 UTC 转为本机时间")
        self.video_time.setToolTip("仅影响未标注时区的视频容器日期。设备若直接写入本地时间，请关闭；带时区的拍摄字段始终优先。")
        layout.addWidget(self.duplicate)
        layout.addWidget(self.video_time)
        section("显示")
        appearance = QtWidgets.QHBoxLayout()
        self.transparency = SmallCheckBox("减少透明度")
        self.motion = SmallCheckBox("减少动态效果")
        appearance.addWidget(self.transparency)
        appearance.addWidget(self.motion)
        appearance.addStretch()
        layout.addLayout(appearance)
        section("版本")
        update_row = QtWidgets.QHBoxLayout()
        update_row.addWidget(QtWidgets.QLabel(f"当前版本  v{APP_VERSION}"))
        update_row.addStretch()
        self.update_button = QtWidgets.QPushButton("检查更新")
        self.update_button.setMinimumHeight(34)
        self.update_button.clicked.connect(self.check_updates)
        update_row.addWidget(self.update_button)
        layout.addLayout(update_row)
        section("支持格式")
        formats = QtWidgets.QGridLayout()
        formats.setHorizontalSpacing(12)
        formats.setVerticalSpacing(8)
        for row, (name, extensions) in enumerate((("RAW", core.RAW_EXTENSIONS),
                                                  ("照片", core.PHOTO_EXTENSIONS),
                                                  ("视频", core.VIDEO_EXTENSIONS))):
            label = QtWidgets.QLabel(name)
            label.setStyleSheet("color:#666666")
            values = QtWidgets.QLabel(" ".join(sorted(extensions)))
            values.setWordWrap(True)
            values.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
            formats.addWidget(label, row, 0, alignment=QtCore.Qt.AlignmentFlag.AlignTop)
            formats.addWidget(values, row, 1)
        formats.setColumnStretch(1, 1)
        layout.addLayout(formats)
        date_help = QtWidgets.QLabel("日期优先使用拍摄时间，其次为内容创建时间；缺失时使用修改时间。")
        date_help.setStyleSheet("color:#666666")
        date_help.setWordWrap(True)
        layout.addWidget(date_help)
        layout.addStretch()
        columns.addWidget(self.form, 1)
        columns.addStretch()
        self.scroll.setWidget(content)
        outer.addWidget(self.scroll, 1)
        self.load_preferences()
        for box in (self.duplicate, self.video_time, self.transparency, self.motion):
            box.scale = .72
            font(box, 13)
            box.toggled.connect(owner.apply_settings)

    def load_preferences(self):
        for box, value in ((self.duplicate, self.owner.skip_identical),
                           (self.video_time, self.owner.video_time_utc),
                           (self.transparency, self.owner.reduce_transparency),
                           (self.motion, self.owner.reduce_motion)):
            with QtCore.QSignalBlocker(box):
                box.setChecked(value)

    def check_updates(self):
        dialog = UpdateDialog(self.owner)
        dialog.exec()
        dialog.deleteLater()


class UpdateDialog(ThemedDialog):
    def __init__(self, owner):
        super().__init__(owner, "检查更新", (470, 250))
        self.worker = None
        self.cancel = Event()
        self.release = None
        self.prepared = None
        self.close_when_finished = False
        self.label = QtWidgets.QLabel("正在连接 GitHub，检查最新版本…")
        self.label.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        self.label.setWordWrap(True)
        self.content_layout.addWidget(self.label)
        self.progress = ImportProgressBar()
        self.progress.setRange(0, 0)
        self.content_layout.addWidget(self.progress)
        self.add_actions("检查中…", "取消", default_accept=False)
        self.accept_button.setEnabled(False)
        self.start(lambda cancel, emit: updater.check_update(cancel=cancel), self.checked)

    def start(self, operation, handler):
        self.cancel = Event()
        self.worker = TaskWorker(operation, self.cancel, self)
        self.worker.result.connect(handler)
        self.worker.error.connect(self.failed)
        self.worker.progress.connect(self.download_progress)
        self.worker.finished.connect(self.finished_work)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker.start()
        self.accept_button.setEnabled(False)

    def checked(self, release):
        if self.cancel.is_set():
            return
        self.release = release
        self.progress.hide()
        if release is None:
            self.label.setText(f"目前已是最新版本（v{APP_VERSION}）。")
            self.accept_button.setText("确定")
            self.cancel_button.hide()
        elif self.can_install():
            self.label.setText(f"发现新版本 v{release.version}（当前 v{APP_VERSION}）。\n是否下载并更新？完成后 Copyer 会自动重启。")
            self.accept_button.setText("更新并重启")
            self.cancel_button.setText("暂不更新")
        else:
            reason = "源码运行请使用便携版更新。" if not getattr(sys, 'frozen', False) else "此版本暂不提供可自动校验的 Windows 更新包。"
            self.label.setText(f"发现新版本 v{release.version}。\n{reason}")
            self.accept_button.setText("打开发布页")
            self.cancel_button.setText("暂不更新")

    def can_install(self):
        return (self.release and self.release.asset_url and self.release.sha256
                and os.name == 'nt' and getattr(sys, 'frozen', False))

    def accept(self):
        if self.worker is not None:
            return
        if self.can_install():
            self.label.setText(f"正在下载 v{self.release.version}，完成后将校验更新包…")
            self.accept_button.setText("正在更新…")
            self.cancel_button.setText("取消")
            self.progress.setRange(0, 1000)
            self.progress.setValue(0)
            self.progress.show()
            release = self.release
            self.start(lambda cancel, emit: updater.prepare_update(release, cancel, emit), self.downloaded)
        elif self.release:
            if QtGui.QDesktopServices.openUrl(QtCore.QUrl(self.release.page_url)):
                super().accept()
            else:
                self.label.setText("无法打开浏览器，请稍后重试。")
        else:
            super().accept()

    def download_progress(self, values):
        received, total = values
        self.progress.setValue(round(received/total*1000))
        self.label.setText(f"正在下载更新：{format_bytes(received)} / {format_bytes(total)}" if received < total
                           else "下载完成，正在校验并准备更新…")

    def downloaded(self, prepared):
        self.prepared = prepared

    def failed(self, message):
        if not self.cancel.is_set():
            self.label.setText("更新未完成：" + (message or "请稍后重试。"))
            self.progress.hide()
            self.accept_button.setText("重试更新" if self.release else "关闭")

    def finished_work(self):
        self.worker = None
        self.accept_button.setEnabled(True)
        if self.close_when_finished:
            if self.prepared:
                import shutil
                shutil.rmtree(self.prepared.workspace, ignore_errors=True)
            super().reject()
            return
        if self.prepared:
            try:
                updater.launch_installer(self.prepared)
            except (OSError, updater.UpdateError) as exc:
                import shutil
                shutil.rmtree(self.prepared.workspace, ignore_errors=True)
                self.prepared = None
                self.failed(str(exc))
                return
            self.parentWidget().save_settings()
            super().accept()
            QtCore.QTimer.singleShot(0, QtWidgets.QApplication.instance().quit)

    def reject(self):
        if self.worker is not None:
            self.close_when_finished = True
            self.cancel.set()
            self.label.setText("正在取消，请稍候…")
            self.cancel_button.setEnabled(False)
            return
        super().reject()

    def closeEvent(self, event):
        if self.worker is not None:
            self.reject()
            event.ignore()
        else:
            super().closeEvent(event)


class MediaImporterWindow(QtWidgets.QMainWindow):
    def __init__(self, *, settings: QtCore.QSettings | None = None):
        super().__init__()
        apply_theme()
        self.setWindowFlags(QtCore.Qt.WindowType.Window | QtCore.Qt.WindowType.FramelessWindowHint)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet("QMainWindow { background:transparent; }")
        self.setWindowTitle(WINDOW_TITLE)
        self.setWindowIcon(QtGui.QIcon(str(resource_path("app_icon.ico"))))
        self.settings = settings if settings is not None else QtCore.QSettings(APP_ORGANIZATION, APP_NAME)
        self.source = str(self.settings.value("paths/source", ""))
        self.target = str(self.settings.value("paths/target", str(Path.home() / "Pictures")))
        self.skip_identical = self.settings.value("copy/skip_identical", True, type=bool)
        self.video_time_utc = self.settings.value("dates/video_time_utc", True, type=bool)
        self.reduce_transparency = self.settings.value("display/reduce_transparency", system_reduce_transparency(), type=bool)
        self.reduce_motion = self.settings.value("display/reduce_motion", system_reduce_motion(), type=bool)
        self.apply_material_preferences()
        self.phase = "empty"
        self.scan_result: core.ScanResult | None = None
        self.metadata_cache: dict = {}
        self.selected: set[Path] = set()
        self.suffixes: dict[str, str] = {}
        self.rows: dict[str, GroupRow] = {}
        self.results: dict[Path, core.FileResult] = {}
        self.cleanup_issues: list[core.FileIssue] = []
        self.last_job: core.ImportJob | None = None
        self.last_progress: core.Progress | None = None
        self._thread = None
        self._worker = None
        self._cancel = Event()
        self._close_after_task = False
        self._loading = True
        self._scale = 1.0
        self._settings_open = False
        self._frame_gesture = None
        self._build_ui()
        screen = QtGui.QGuiApplication.screenAt(QtGui.QCursor.pos()) or self.screen()
        initial_size = default_window_size(screen)
        self.setMinimumSize(min(360, initial_size.width()), min(230, initial_size.height()))
        self.resize(initial_size)
        self.move(screen.availableGeometry().center()-QtCore.QPoint(initial_size.width()//2, initial_size.height()//2))
        self._loading = False
        if not self.source:
            drives = detect_removable_drives()
            if drives:
                self.source = drives[0]
        self.source_card.set_path(self.source)
        self.target_card.set_path(self.target)
        self.relayout()
        self.refresh_selection()

    @property
    def busy(self):
        return self._thread is not None

    def apply_material_preferences(self):
        app = QtWidgets.QApplication.instance()
        app.setProperty("reduceTransparency", self.reduce_transparency)
        app.setProperty("reduceMotion", self.reduce_motion)
        self.update()
        if hasattr(self, "canvas"):
            self.canvas.update()
        for surface in self.findChildren(GlassSurface) + self.findChildren(GlassButton):
            surface.update()

    def _build_ui(self):
        self.canvas = PaperGlassCanvas()
        self.canvas.setObjectName("copyerCanvas")
        self.setCentralWidget(self.canvas)
        self.canvas.installEventFilter(self)
        self.home_page = QtWidgets.QWidget(self.canvas)
        self.home_page.installEventFilter(self)
        self.title_label = QtWidgets.QLabel("Copyer", self.canvas)
        self.meta_label = ElidedLabel(f"v{APP_VERSION} · by {APP_AUTHOR}", self.canvas)
        self.meta_label.setStyleSheet("color:#666666")
        self.window_controls = []
        for name, tip, callback in (("cog-outline", "设置", self.show_settings),
                                    ("window-minimize", "最小化", self.showMinimized),
                                    ("window-maximize", "最大化或还原", self.toggle_maximized),
                                    ("close", "关闭", self.close)):
            button = QtWidgets.QToolButton(self.canvas)
            button.setObjectName("windowIconButton")
            button.setIcon(ui_icon(name))
            button.setToolTip(tip)
            button.setAccessibleName(tip)
            button.clicked.connect(callback)
            self.window_controls.append(button)
        self.source_card = PathCard(True, self.home_page)
        self.target_card = PathCard(False, self.home_page)
        self.source_card.choose_requested.connect(self.choose_source)
        self.target_card.choose_requested.connect(self.choose_target)
        self.source_card.devices_requested.connect(self.show_devices)
        self.raw_checkbox = SmallCheckBox("RAW", self.home_page)
        self.jpeg_checkbox = SmallCheckBox("照片", self.home_page)
        self.jpeg_checkbox.setToolTip("JPEG / HEIC / HEIF；RAW 使用左侧选项")
        self.video_checkbox = SmallCheckBox("视频", self.home_page)
        self.format_boxes = [self.raw_checkbox, self.jpeg_checkbox, self.video_checkbox]
        for box, key in zip(self.format_boxes, ("raw", "jpg", "mp4")):
            box.setChecked(self.settings.value("formats/"+key, True, type=bool))
            box.toggled.connect(self.parameters_changed)
        self.scan_button = QtWidgets.QPushButton("重新扫描", self.home_page)
        self.scan_button.setIcon(ui_icon("refresh"))
        self.scan_button.clicked.connect(self.start_scan)
        self.select_all = SmallCheckBox("全选", self.home_page)
        self.select_all.setTristate(True)
        self.select_all.setAccessibleName("全选导入文件")
        self.select_all.clicked.connect(self.toggle_all)
        self.count_heading = QtWidgets.QLabel("文件", self.home_page)
        self.count_heading.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.header_line = QtWidgets.QFrame(self.home_page)
        self.header_line.setStyleSheet("background:#d9d9d9")
        self.scroll = QtWidgets.QScrollArea(self.home_page)
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.row_container = QtWidgets.QWidget()
        self.row_layout = QtWidgets.QVBoxLayout(self.row_container)
        self.row_layout.setContentsMargins(0, 0, 0, 0)
        self.row_layout.setSpacing(0)
        self.row_layout.addStretch()
        self.scroll.setWidget(self.row_container)
        self.row_container.setAutoFillBackground(False)
        self.scroll.viewport().setAutoFillBackground(False)
        self.scroll.setStyleSheet("QScrollArea, QScrollArea > QWidget > QWidget { background:transparent; }")
        self.empty_label = QtWidgets.QLabel("选择来源后扫描文件", self.scroll.viewport())
        self.empty_label.setStyleSheet("color:#8a8a8a")
        self.empty_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.scroll.viewport().installEventFilter(self)
        self.status_label = ElidedLabel("待扫描", self.home_page)
        self.percent_label = QtWidgets.QLabel("", self.home_page)
        self.percent_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter)
        self.percent_label.setStyleSheet("color:#666666")
        self.progress_bar = ImportProgressBar(self.home_page)
        self.progress_bar.setRange(0, 1000)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setAccessibleName("导入进度，包含复制与校验")
        self.progress_bar.setToolTip("按复制与校验实际处理的字节推进")
        self.context_label = ElidedLabel("", self.home_page)
        self.context_label.setStyleSheet("color:#666666")
        self.speed_label = QtWidgets.QLabel("", self.home_page)
        self.speed_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter)
        self.speed_label.setStyleSheet("color:#666666")
        self.issues_button = QtWidgets.QPushButton("查看失败文件", self.home_page)
        self.issues_button.setStyleSheet("padding:0;")
        self.issues_button.clicked.connect(self.show_issues)
        self.issues_button.hide()
        self.import_button = GlassButton("导入", self.home_page)
        self.import_button.clicked.connect(self.primary_action)
        self.cleanup_button = QtWidgets.QPushButton("删除已校验的源文件", self.home_page)
        self.cleanup_button.setStyleSheet("padding:0;")
        self.cleanup_button.setToolTip("删除前重新校验来源和目标；只删除本次已完整导入的源文件")
        self.cleanup_button.clicked.connect(self.start_cleanup)
        self.cleanup_button.hide()
        self.settings_page = SettingsPage(self)
        self.settings_page.hide()
        self.settings_back = QtGui.QShortcut(QtGui.QKeySequence("Escape"), self)
        self.settings_back.activated.connect(self.show_home)
        self.size_grip = QtWidgets.QSizeGrip(self.canvas)
        self.canvas.setStyleSheet("""
            QToolButton#windowIconButton { border:0; background:transparent; }
            QToolButton#windowIconButton:focus { border:0; background:rgba(0,0,0,14); border-radius:5px; }
            QToolButton#windowIconButton:hover { border:0; background:rgba(0,0,0,10); border-radius:5px; }
            QToolButton#windowIconButton:pressed { border:0; background:rgba(0,0,0,20); border-radius:5px; }
        """)

    def relayout(self):
        if not hasattr(self, "settings_page"):
            return
        w, h = self.canvas.width(), self.canvas.height()
        self.home_page.setGeometry(self.canvas.rect())
        page_top = 36 if h < 360 or w < 480 else 48
        self.settings_page.setGeometry(8, page_top, w-16, max(1, h-page_top-8))
        dense = h < 360 or w < 480
        s = .55 if dense else .7
        self._scale = s
        margin = 14 if w >= 360 else 11
        title_height = 25 if dense else 34
        title_size = 16 if dense else 20
        self.title_label.setGeometry(margin, 7, 61 if dense else 78, title_height)
        font(self.title_label, title_size, medium=True)
        control_width = 23 if dense else 30
        controls_x = w-margin-control_width*4
        for i, button in enumerate(self.window_controls):
            button.setStyleSheet("padding:2px;")
            button.setGeometry(controls_x+i*control_width, 8, control_width, title_height-2)
            button.setIconSize(QtCore.QSize(17 if dense else 21, 17 if dense else 21))
        meta_x = margin+(64 if dense else 83)
        self.meta_label.setGeometry(meta_x, 7, max(10, controls_x-meta_x-4), title_height)
        font(self.meta_label, 11 if dense else 13)
        cards_y = 34 if dense else 48
        card_height = 47 if dense else 61
        card_width = (w-margin*2-10)//2
        self.source_card.setGeometry(margin-2, cards_y, card_width+2, card_height)
        self.target_card.setGeometry(margin+card_width+8, cards_y, card_width+2, card_height)
        for card in (self.source_card, self.target_card):
            card.relayout(s)
        formats_y = cards_y+card_height+1
        format_x = margin
        for box in self.format_boxes:
            box.scale = s
            font(box, 12 if dense else 14, medium=True)
            width = box.sizeHint().width()
            box.setGeometry(format_x, formats_y, width, 22 if dense else 28)
            format_x += width+(12 if dense else 18)
        scan_width = 78 if w >= 360 else 25
        self.scan_button.setText("重新扫描" if w >= 360 else "")
        self.scan_button.setStyleSheet("padding:0;")
        self.scan_button.setToolTip("重新扫描")
        self.scan_button.setAccessibleName("重新扫描")
        self.scan_button.setGeometry(w-margin-scan_width, formats_y, scan_width, 22 if dense else 28)
        self.scan_button.setIconSize(QtCore.QSize(18 if dense else 22, 18 if dense else 22))
        font(self.scan_button, 12 if dense else 14, medium=True)
        header_y = formats_y+(24 if dense else 36)
        self.select_all.scale = s
        self.select_all.setGeometry(margin, header_y, 90, 20 if dense else 27)
        font(self.select_all, 12 if dense else 14, medium=True)
        self.count_heading.setGeometry(w-margin-64, header_y, 64, 20 if dense else 27)
        font(self.count_heading, 12 if dense else 14)
        scroll_y = header_y+(22 if dense else 31)
        self.header_line.setGeometry(margin, scroll_y-1, w-margin*2, 1)
        cleanup_visible = not self.cleanup_button.isHidden()
        footer_y = h-(59 if dense else 78)-(22 if dense else 28)*cleanup_visible
        self.scroll.setGeometry(margin, scroll_y, w-margin*2, max(18, footer_y-scroll_y-2))
        self.empty_label.setGeometry(self.scroll.viewport().rect())
        font(self.empty_label, 11 if dense else 14)
        for row in self.rows.values():
            row.relayout(s)
        action_width = 116 if dense else 155
        action_x = w-margin-action_width
        track_width = max(70, action_x-margin-12)
        self.status_label.setGeometry(margin, footer_y, max(40, track_width-38), 17 if dense else 23)
        self.percent_label.setGeometry(margin+track_width-38, footer_y, 38, 17 if dense else 23)
        font(self.status_label, 11 if dense else 14, medium=True)
        font(self.percent_label, 11 if dense else 14)
        self.progress_bar.setGeometry(margin, footer_y+(20 if dense else 29), track_width, 5 if dense else 7)
        self.context_label.setGeometry(margin, footer_y+(29 if dense else 42), max(40, track_width-(90 if not self.issues_button.isHidden() else 0)), 16 if dense else 20)
        self.speed_label.setVisible(False)
        self.issues_button.setGeometry(margin+track_width-88, footer_y+(28 if dense else 40), 88, 18 if dense else 24)
        font(self.context_label, 11 if dense else 12)
        font(self.issues_button, 11 if dense else 12)
        self.import_button.setGeometry(action_x, footer_y+4, action_width, 37 if dense else 49)
        self.import_button.scale = s
        self.import_button.graphicsEffect().setBlurRadius(10)
        self.import_button.graphicsEffect().setOffset(0, 3)
        font(self.import_button, 12 if dense else 15, medium=True)
        self.cleanup_button.setGeometry(action_x-4, footer_y+(43 if dense else 58), action_width+8, 22 if dense else 27)
        font(self.cleanup_button, 11 if dense else 13)
        self.size_grip.setGeometry(w-18, h-18, 10, 10)
        self.canvas.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.relayout()

    def eventFilter(self, watched, event):
        if hasattr(self, "empty_label") and watched is self.scroll.viewport() and event.type() == QtCore.QEvent.Type.Resize:
            self.empty_label.setGeometry(watched.rect())
        if watched in (getattr(self, "canvas", None), getattr(self, "home_page", None)):
            if event.type() == QtCore.QEvent.Type.MouseButtonPress:
                self.mousePressEvent(event)
                return True
            if event.type() == QtCore.QEvent.Type.MouseButtonDblClick:
                self.mouseDoubleClickEvent(event)
                return True
            if event.type() == QtCore.QEvent.Type.MouseButtonRelease:
                self.mouseReleaseEvent(event)
                return True
            if event.type() == QtCore.QEvent.Type.MouseMove and self._frame_gesture:
                self.mouseMoveEvent(event)
                return True
        if watched is getattr(self, "canvas", None) and event.type() == QtCore.QEvent.Type.MouseMove:
            edges = self.resize_edges(event.position())
            cursors = {QtCore.Qt.Edge.LeftEdge: QtCore.Qt.CursorShape.SizeHorCursor,
                       QtCore.Qt.Edge.RightEdge: QtCore.Qt.CursorShape.SizeHorCursor,
                       QtCore.Qt.Edge.TopEdge: QtCore.Qt.CursorShape.SizeVerCursor,
                       QtCore.Qt.Edge.BottomEdge: QtCore.Qt.CursorShape.SizeVerCursor}
            if edges in cursors:
                self.canvas.setCursor(cursors[edges])
            elif edges:
                diagonal = edges in (QtCore.Qt.Edge.LeftEdge | QtCore.Qt.Edge.TopEdge, QtCore.Qt.Edge.RightEdge | QtCore.Qt.Edge.BottomEdge)
                self.canvas.setCursor(QtCore.Qt.CursorShape.SizeFDiagCursor if diagonal else QtCore.Qt.CursorShape.SizeBDiagCursor)
            else:
                self.canvas.unsetCursor()
        return super().eventFilter(watched, event)

    def resize_edges(self, position):
        edges = QtCore.Qt.Edge(0)
        if self.isMaximized():
            return edges
        if position.x() < 9:
            edges |= QtCore.Qt.Edge.LeftEdge
        elif position.x() >= self.width()-9:
            edges |= QtCore.Qt.Edge.RightEdge
        if position.y() < 9:
            edges |= QtCore.Qt.Edge.TopEdge
        elif position.y() >= self.height()-9:
            edges |= QtCore.Qt.Edge.BottomEdge
        return edges

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.MouseButton.LeftButton and not self.isMaximized():
            edges = self.resize_edges(event.position())
            if edges or event.position().y() < 34:
                self._frame_gesture = (event.globalPosition().toPoint(), self.geometry(), edges)
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._frame_gesture and event.buttons() & QtCore.Qt.MouseButton.LeftButton:
            start, original, edges = self._frame_gesture
            delta = event.globalPosition().toPoint()-start
            rect = QtCore.QRect(original)
            if edges:
                if edges & QtCore.Qt.Edge.LeftEdge:
                    rect.setLeft(min(original.left()+delta.x(), original.right()-self.minimumWidth()+1))
                if edges & QtCore.Qt.Edge.RightEdge:
                    rect.setRight(max(original.right()+delta.x(), original.left()+self.minimumWidth()-1))
                if edges & QtCore.Qt.Edge.TopEdge:
                    rect.setTop(min(original.top()+delta.y(), original.bottom()-self.minimumHeight()+1))
                if edges & QtCore.Qt.Edge.BottomEdge:
                    rect.setBottom(max(original.bottom()+delta.y(), original.top()+self.minimumHeight()-1))
                self.setGeometry(rect)
            else:
                self.move(original.topLeft()+delta)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._frame_gesture = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        self._frame_gesture = None
        if event.button() == QtCore.Qt.MouseButton.LeftButton and event.position().y() < 34:
            self.toggle_maximized()

    def toggle_maximized(self):
        self.showNormal() if self.isMaximized() else self.showMaximized()

    def save_settings(self):
        self.settings.setValue("paths/source", self.source)
        self.settings.setValue("paths/target", self.target)
        for key, box in zip(("raw", "jpg", "mp4"), self.format_boxes):
            self.settings.setValue("formats/"+key, box.isChecked())
        self.settings.setValue("copy/skip_identical", self.skip_identical)
        self.settings.setValue("dates/video_time_utc", self.video_time_utc)
        self.settings.sync()

    def selected_extensions(self):
        result = set()
        for box, extensions in zip(self.format_boxes, (core.RAW_EXTENSIONS, core.PHOTO_EXTENSIONS, core.VIDEO_EXTENSIONS)):
            if box.isChecked():
                result.update(extensions)
        return result

    def set_source(self, path: str):
        if self.busy:
            return
        if path != self.source:
            self.metadata_cache.clear()
        self.source = path
        self.source_card.set_path(path)
        self.parameters_changed()

    def set_target(self, path: str):
        if self.busy:
            return
        self.target = path
        self.target_card.set_path(path)
        self.results.clear()
        self.last_job = None
        if self.scan_result and not self.scan_result.cancelled:
            self.phase = "ready"
        self.reset_progress()
        self.refresh_selection()
        self.save_settings()

    def choose_source(self):
        path = QtWidgets.QFileDialog.getExistingDirectory(self, "选择读卡器或源文件夹", self.source)
        if path:
            self.set_source(path)

    def choose_target(self):
        path = QtWidgets.QFileDialog.getExistingDirectory(self, "选择目标文件夹", self.target)
        if path:
            self.set_target(path)

    def show_devices(self):
        menu = QtWidgets.QMenu(self)
        drives = detect_removable_drives()
        for drive in drives:
            action = menu.addAction(ui_icon("sd"), source_name(drive))
            action.triggered.connect(lambda checked=False, path=drive: self.set_source(path))
        if not drives:
            menu.addAction("未发现可移动设备").setEnabled(False)
        menu.addSeparator()
        menu.addAction("选择文件夹…", self.choose_source)
        menu.exec(self.source_card.arrow.mapToGlobal(QtCore.QPoint(0, self.source_card.arrow.height())))

    def parameters_changed(self, *args):
        if self._loading or self.busy:
            return
        self.scan_result = None
        self.selected.clear()
        self.suffixes.clear()
        self.results.clear()
        self.last_job = None
        self.phase = "empty"
        self.populate_rows()
        self.reset_progress()
        self.refresh_selection()
        self.save_settings()

    def reset_progress(self):
        self.cleanup_issues.clear()
        self.cleanup_button.hide()
        self.progress_bar.setRange(0, 1000)
        self.progress_bar.setValue(0)
        self.percent_label.clear()
        self.context_label.clear()
        self.speed_label.clear()
        self.issues_button.hide()
        self.progress_bar.setToolTip("按复制与校验实际处理的字节推进")
        self.relayout()

    def populate_rows(self):
        for row in self.rows.values():
            self.row_layout.removeWidget(row)
            row.deleteLater()
        self.rows = {}
        if self.scan_result:
            for day, files in self.scan_result.groups.items():
                row = GroupRow(day, files)
                row.suffix.setText(self.suffixes.get(day, ""))
                row.selection_changed.connect(self.toggle_group)
                row.suffix_changed.connect(self.change_suffix)
                self.row_layout.insertWidget(self.row_layout.count()-1, row)
                self.rows[day] = row
        self.empty_label.setVisible(not self.rows)
        self.relayout()

    def toggle_all(self, checked):
        if self.phase != "ready" or self.busy or not self.scan_result:
            return
        self.selected = {media.path for media in self.scan_result.files} if checked else set()
        self.refresh_selection()

    def toggle_group(self, day, checked):
        if self.phase != "ready" or self.busy:
            return
        paths = {media.path for media in self.scan_result.groups[day]}
        self.selected.update(paths) if checked else self.selected.difference_update(paths)
        self.refresh_selection()

    def change_suffix(self, day, value):
        self.suffixes[day] = value
        row = self.rows[day]
        try:
            name = core.build_destination_folder_name(day, value)
            row.suffix.setProperty("invalid", False)
            row.suffix.setToolTip(str(Path(self.target) / name) if self.target else name)
        except ValueError as exc:
            row.suffix.setProperty("invalid", True)
            row.suffix.setToolTip(str(exc))
        row.suffix.style().unpolish(row.suffix)
        row.suffix.style().polish(row.suffix)
        self.refresh_selection()

    def refresh_selection(self):
        total = len(self.scan_result.files) if self.scan_result else 0
        count = len(self.selected)
        state = QtCore.Qt.CheckState.Checked if total and count == total else (QtCore.Qt.CheckState.PartiallyChecked if count else QtCore.Qt.CheckState.Unchecked)
        self.select_all.setCheckState(state)
        editable = self.phase == "ready" and not self.busy
        self.select_all.setEnabled(editable and total > 0)
        for day, row in self.rows.items():
            chosen = sum(media.path in self.selected for media in row.files)
            row.check.setCheckState(QtCore.Qt.CheckState.Checked if chosen == len(row.files) else (QtCore.Qt.CheckState.PartiallyChecked if chosen else QtCore.Qt.CheckState.Unchecked))
            row.check.setEnabled(editable)
            row.suffix.setEnabled(editable)
            row.warning.setVisible(any(self.results.get(media.path) and self.results[media.path].status == "failed" for media in row.files))
        for control in (self.source_card, self.target_card, self.scan_button, *self.format_boxes, self.window_controls[0]):
            control.setEnabled(not self.busy)
        self.cleanup_button.setVisible(not self.busy and self.phase in {"complete", "partial", "cancelled"}
                                       and bool(core.cleanup_candidates(self.results.values())))
        self.relayout()
        if self.busy:
            self.import_button.setText("取消")
            self.import_button.setEnabled(not self._cancel.is_set())
        elif self.phase == "complete":
            self.import_button.setText("打开文件夹")
            self.import_button.setEnabled(True)
        elif self.phase in {"partial", "cancelled"} and self.last_job:
            self.import_button.setText("继续未完成" if self.phase == "cancelled" else "重试失败项")
            self.import_button.setEnabled(True)
        else:
            self.import_button.setText(f"导入 {count} 个文件" if count else "导入")
            invalid = any(row.suffix.property("invalid") and any(media.path in self.selected for media in row.files) for row in self.rows.values())
            self.import_button.setEnabled(editable and bool(count) and bool(self.target.strip()) and not invalid)
            if self.phase == "ready":
                self.status_label.setText(("待导入" if count else "选择需要导入的文件") if total else "未找到符合条件的文件")
            elif self.phase == "empty":
                self.status_label.setText("待扫描")

    def _start_worker(self, operation, result_handler, progress_handler):
        self._cancel = Event()
        self._worker = TaskWorker(operation, self._cancel, self)
        self._thread = self._worker
        self._worker.progress.connect(progress_handler)
        self._worker.result.connect(result_handler)
        self._worker.error.connect(self.task_error)
        self._thread.finished.connect(self._thread_finished)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()
        self.refresh_selection()

    @QtCore.Slot()
    def _thread_finished(self):
        self._thread = None
        self._worker = None
        self.refresh_selection()
        if self._close_after_task:
            self.close()

    def start_scan(self):
        if self.busy:
            return
        try:
            core.directory_path(self.source, must_exist=True)
            extensions = self.selected_extensions()
            if not extensions:
                raise ValueError("至少选择一种文件类型。")
        except ValueError as exc:
            self.notify("无法扫描", str(exc))
            return
        source = self.source
        self.parameters_changed()
        self.phase = "scanning"
        self.status_label.setText("正在扫描")
        self.progress_bar.setRange(0, 0)
        self.empty_label.setText("正在查找媒体文件…")
        video_time_utc = self.video_time_utc
        self._start_worker(lambda cancel, emit: core.scan(source, extensions, cancel, lambda count, path, groups: emit((count, path, groups)), quicktime_utc=video_time_utc, metadata_cache=self.metadata_cache), self.scan_finished, self.scan_progress)

    def scan_progress(self, data):
        count, path, groups = data
        self.context_label.setText(f"{path} · 已发现 {count} 个文件")
        self.empty_label.setText(f"已发现 {count} 个文件")

    def scan_finished(self, result: core.ScanResult):
        self.scan_result = result
        self.selected = {media.path for media in result.files} if not result.cancelled else set()
        self.phase = "cancelled_scan" if result.cancelled else "ready"
        self.reset_progress()
        self.populate_rows()
        if result.cancelled:
            self.status_label.setText("扫描已取消")
        elif not result.files:
            self.status_label.setText("未找到符合条件的文件")
        else:
            self.status_label.setText("待导入")
        self.empty_label.setText("未找到符合条件的文件" if not result.cancelled else "重新扫描以继续")
        if result.issues:
            self.context_label.setText(f"{len(result.issues)} 项扫描问题")
            self.issues_button.setText("查看扫描问题")
            self.issues_button.show()
            self.relayout()
        self.refresh_selection()

    def primary_action(self):
        if self.busy:
            self.request_cancel()
        elif self.phase == "complete" and self.last_job:
            QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(self.last_job.target)))
        elif self.phase in {"partial", "cancelled"} and self.last_job:
            retry = tuple(item for item in self.last_job.items if self.results.get(item.media.path) is None or self.results[item.media.path].status in {"failed", "pending"})
            job = core.ImportJob(self.last_job.source, self.last_job.source_identity, self.last_job.target, retry, self.last_job.skip_identical)
            self.begin_import(job, retry=True)
        else:
            self.start_import()

    def start_import(self):
        if self.busy or self.phase != "ready" or not self.scan_result:
            return
        try:
            job = core.build_job(self.scan_result, self.target, self.selected, self.suffixes, self.skip_identical)
        except ValueError as exc:
            self.notify("无法导入", str(exc))
            return
        self.begin_import(job)

    def begin_import(self, job, *, retry=False):
        if not job.items:
            return
        if not retry:
            self.results.clear()
            self.last_job = job
        self.last_progress = None
        self.phase = "importing"
        self.reset_progress()
        self.status_label.setText("准备导入")
        self._start_worker(lambda cancel, emit: core.run_import(job, cancel, emit), self.import_finished, self.import_progress)

    def import_progress(self, progress: core.Progress):
        self.last_progress = progress
        if self._cancel.is_set():
            return
        self.status_label.setText({"copy": "正在导入", "verify": "正在校验", "compare": "正在比较", "verified": "正在导入", "failed": "正在导入", "cleanup_verify": "删除前校验"}.get(progress.phase, "正在导入"))
        ratio = min(.999, progress.done / progress.total) if progress.total else 0
        self.progress_bar.setValue(round(ratio*1000))
        self.percent_label.setText(f"{int(ratio*100)}%")
        self.context_label.setText(f"{Path(progress.path).name} · {progress.completed} / {progress.files}")
        if progress.elapsed > 1 and progress.done > 0:
            speed = progress.done / progress.elapsed
            seconds = max(0, round((progress.total-progress.done)/speed))
            remaining = f"约{seconds}秒" if seconds < 60 else f"约{(seconds+59)//60}分钟"
            self.speed_label.setText(f"{format_bytes(speed)}/s · {remaining}")
        else:
            self.speed_label.setText("估算中")
        self.progress_bar.setToolTip(f"{self.context_label.text()}\n{self.speed_label.text()}\n进度包含复制与校验")

    def import_finished(self, result: core.ImportResult):
        self.results.update({entry.item.media.path: entry for entry in result.files})
        counts = Counter(entry.status for entry in self.results.values())
        self.phase = "cancelled" if result.cancelled else ("partial" if counts["failed"] or counts["pending"] else "complete")
        self.progress_bar.setRange(0, 1000)
        self.speed_label.clear()
        total = sum(max(item.media.size, 1) for item in self.last_job.items)
        verified = sum(max(entry.item.media.size, 1) for entry in self.results.values() if entry.status in {"copied", "skipped", "deleted"})
        percent = round(verified/total*1000) if total else 0
        self.progress_bar.setValue(percent)
        self.percent_label.setText(f"{percent//10}%")
        if self.phase == "complete":
            self.status_label.setText("导入完成，校验通过")
            self.context_label.setText(f"{counts['copied']} 个文件已导入" + (f" · {counts['skipped']} 个相同文件已跳过" if counts["skipped"] else ""))
        else:
            self.status_label.setText("已取消" if result.cancelled else "部分失败")
            self.context_label.setText(f"{counts['copied']+counts['skipped']} 个完成 · {counts['failed']} 个失败" + (f" · {counts['pending']} 个未完成" if counts["pending"] else ""))
            self.issues_button.setText("查看未完成文件" if result.cancelled else "查看失败文件")
            self.issues_button.show()
        self.progress_bar.setToolTip(self.context_label.text())
        self.relayout()
        self.refresh_selection()

    def start_cleanup(self):
        if self.busy or not self.last_job:
            return
        candidates = core.cleanup_candidates(self.results.values())
        if not candidates:
            return
        dialog = ThemedDialog(self, "删除已校验的源文件", (530, 360))
        label = QtWidgets.QLabel(f"将从以下来源永久删除 {len(candidates)} 个已校验文件：\n{self.last_job.source}\n\n"
                                "删除前会再次逐个核对源文件和目标文件。未导入、校验失败或已变化的文件会保留；文件夹会保留。此操作不经过回收站。")
        label.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        label.setWordWrap(True)
        dialog.content_layout.addWidget(label)
        listing = QtWidgets.QPlainTextEdit()
        listing.setReadOnly(True)
        listing.setPlainText("\n".join(str(entry.item.media.path.relative_to(self.last_job.source)) for entry in candidates))
        dialog.content_layout.addWidget(listing)
        dialog.add_actions("删除源文件", "保留", default_accept=False)
        accepted = dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted
        dialog.deleteLater()
        if not accepted:
            return
        self._phase_before_cleanup = self.phase
        self.phase = "cleaning"
        self.reset_progress()
        self.status_label.setText("删除前校验")
        job = self.last_job
        self._start_worker(lambda cancel, emit: core.run_cleanup(job, candidates, cancel, emit),
                           self.cleanup_finished, self.import_progress)

    def cleanup_finished(self, result: core.CleanupResult):
        for path in result.deleted:
            self.results[path] = replace(self.results[path], status="deleted")
        self.cleanup_issues = result.issues
        self.phase = self._phase_before_cleanup
        self.progress_bar.setValue(1000 if not result.cancelled else self.progress_bar.value())
        self.percent_label.setText("" if result.cancelled else "100%")
        self.speed_label.clear()
        self.status_label.setText("删除已停止" if result.cancelled else "源文件清理完成")
        self.context_label.setText(f"已删除 {len(result.deleted)} 个源文件 · {len(core.cleanup_candidates(self.results.values()))} 个保留")
        self.progress_bar.setToolTip(self.context_label.text())
        if result.issues:
            self.issues_button.setText("查看保留原因")
            self.issues_button.show()
        self.refresh_selection()

    def request_cancel(self):
        self._cancel.set()
        self.status_label.setText("正在停止…")
        self.import_button.setEnabled(False)

    def task_error(self, message):
        self.phase = "error"
        self.reset_progress()
        self.status_label.setText("任务未完成")
        self.context_label.setText(message)
        self.context_label.setToolTip(message)
        self.empty_label.setText("重新扫描以继续")

    def show_issues(self):
        issues = [(str(item.path), item.message) for item in self.cleanup_issues]
        issues += [(str(entry.item.media.path), entry.error) for entry in self.results.values() if entry.status in {"failed", "pending"}]
        if not issues and self.scan_result:
            issues = [(str(item.path), item.message) for item in self.scan_result.issues]
        dialog = ThemedDialog(self, "本次任务问题", (900, 480))
        dialog.setSizeGripEnabled(True)
        layout = dialog.content_layout
        table = QtWidgets.QTableWidget(len(issues), 2)
        table.setItemDelegate(SelectionDelegate(table))
        table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        table.setHorizontalHeaderLabels(["文件", "原因"])
        table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.Stretch)
        for row, values in enumerate(issues):
            for col, value in enumerate(values):
                item = QtWidgets.QTableWidgetItem(value)
                item.setToolTip(value)
                table.setItem(row, col, item)
        layout.addWidget(table)
        dialog.add_actions("关闭")
        dialog.exec()
        dialog.deleteLater()

    def show_settings(self):
        if self.busy:
            return
        self._settings_open = True
        self.settings_page.load_preferences()
        self.home_page.hide()
        self.settings_page.show()
        self.window_controls[0].hide()
        self.settings_page.back_button.setFocus()
        self.relayout()

    def show_home(self):
        if not self._settings_open:
            return
        self._settings_open = False
        self.settings_page.hide()
        self.home_page.show()
        self.window_controls[0].show()
        self.refresh_selection()
        self.window_controls[0].setFocus()

    def apply_settings(self):
        page = self.settings_page
        date_policy_changed = self.video_time_utc != page.video_time.isChecked()
        self.video_time_utc = page.video_time.isChecked()
        self.skip_identical = page.duplicate.isChecked()
        self.reduce_transparency = page.transparency.isChecked()
        self.reduce_motion = page.motion.isChecked()
        self.settings.setValue("display/reduce_transparency", self.reduce_transparency)
        self.settings.setValue("display/reduce_motion", self.reduce_motion)
        self.apply_material_preferences()
        self.save_settings()
        if date_policy_changed:
            self.parameters_changed()

    def notify(self, title, message):
        dialog = MessageDialog(self, title, message)
        dialog.exec()
        dialog.deleteLater()

    def closeEvent(self, event):
        if self.busy:
            if not self._close_after_task:
                dialog = MessageDialog(self, "任务正在进行", "停止当前任务后关闭？已完成的文件会保留。", question=True)
                answer = dialog.exec()
                dialog.deleteLater()
                if answer == QtWidgets.QDialog.DialogCode.Accepted:
                    self._close_after_task = True
                    self.request_cancel()
            event.ignore()
            return
        self.save_settings()
        super().closeEvent(event)
