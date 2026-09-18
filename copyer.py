from __future__ import annotations

import ctypes
import os
import shutil
import sys
from collections import defaultdict
from collections.abc import Iterable
from datetime import date, datetime
from pathlib import Path
from typing import TypeAlias

try:
    from PySide6 import QtCore, QtGui, QtWidgets
except ImportError as exc:
    raise SystemExit("未找到 PySide6，请先安装：pip install PySide6") from exc

try:
    from PIL import Image
except ImportError:
    Image = None


APP_ORGANIZATION = "copyer"
APP_NAME = "copyer"
WINDOW_TITLE = "读卡器照片/视频导入工具"
WINDOW_WIDTH = 1100
WINDOW_HEIGHT = 720

RAW_EXTENSIONS = frozenset(
    {".cr2", ".cr3", ".nef", ".arw", ".raf", ".orf", ".rw2", ".dng"}
)
JPEG_EXTENSIONS = frozenset({".jpg", ".jpeg"})
VIDEO_EXTENSIONS = frozenset({".mp4", ".mov", ".m4v"})
APP_ICON_FILENAMES = ("app_icon.ico",)

FileGroups: TypeAlias = dict[str, list[Path]]
ImportPlan: TypeAlias = list[tuple[str, list[Path]]]

UI_FONT_CANDIDATES = (
    "Microsoft YaHei UI",
    "Microsoft YaHei",
    "Noto Sans SC",
    "Noto Sans CJK SC",
    "Source Han Sans SC",
    "SimHei",
)
UI_FONT_FILES = (
    Path("C:/Windows/Fonts/msyh.ttc"),
    Path("C:/Windows/Fonts/NotoSansSC-VF.ttf"),
)


def get_resource_directory() -> Path:
    """Return the directory containing bundled or source resources."""
    bundled_directory = getattr(sys, "_MEIPASS", None)
    if bundled_directory:
        return Path(bundled_directory)
    return Path(__file__).resolve().parent


def load_app_icon() -> QtGui.QIcon | None:
    """Load the first available application icon."""
    resource_directory = get_resource_directory()
    for filename in APP_ICON_FILENAMES:
        icon_path = resource_directory / filename
        if icon_path.exists():
            return QtGui.QIcon(str(icon_path))
    return None


def detect_removable_drives() -> list[str]:
    """Return the root paths of removable Windows drives."""
    if os.name != "nt":
        return []

    drive_bitmask = ctypes.windll.kernel32.GetLogicalDrives()
    removable_drives: list[str] = []
    for drive_index in range(26):
        if not drive_bitmask & (1 << drive_index):
            continue
        drive_root = f"{chr(65 + drive_index)}:\\"
        drive_type = ctypes.windll.kernel32.GetDriveTypeW(ctypes.c_wchar_p(drive_root))
        if drive_type == 2:  # DRIVE_REMOVABLE
            removable_drives.append(drive_root)
    return removable_drives


def read_exif_datetime(file_path: Path) -> datetime | None:
    """Read the preferred capture datetime from a JPEG's EXIF metadata."""
    if Image is None or file_path.suffix.lower() not in JPEG_EXTENSIONS:
        return None

    try:
        with Image.open(file_path) as image:
            exif = image.getexif()
            if not exif:
                return None
            for tag in (36867, 306):  # DateTimeOriginal, DateTime
                value = exif.get(tag)
                if value:
                    return datetime.strptime(str(value), "%Y:%m:%d %H:%M:%S")
    except Exception:
        return None
    return None


def get_file_date(file_path: Path) -> date:
    """Return capture date when available, falling back to modification date."""
    exif_datetime = read_exif_datetime(file_path)
    if exif_datetime:
        return exif_datetime.date()
    return datetime.fromtimestamp(file_path.stat().st_mtime).date()


def ensure_unique_path(destination_directory: Path, filename: str) -> Path:
    """Return a non-existing path by adding an incrementing numeric suffix."""
    destination_path = destination_directory / filename
    if not destination_path.exists():
        return destination_path

    stem = destination_path.stem
    suffix = destination_path.suffix
    duplicate_index = 1
    while True:
        candidate_path = destination_directory / f"{stem}_{duplicate_index}{suffix}"
        if not candidate_path.exists():
            return candidate_path
        duplicate_index += 1


def build_destination_folder_name(date_text: str, suffix: str) -> str:
    """Build a date-based destination folder name with an optional suffix."""
    normalized_suffix = suffix.strip()
    return f"{date_text}-{normalized_suffix}" if normalized_suffix else date_text


def scan_media_files(source_directory: Path, extensions: Iterable[str]) -> FileGroups:
    """Scan a directory recursively and group matching media files by date."""
    normalized_extensions = {extension.lower() for extension in extensions}
    grouped_files: defaultdict[str, list[Path]] = defaultdict(list)

    for current_directory, _, filenames in os.walk(source_directory):
        for filename in filenames:
            if Path(filename).suffix.lower() not in normalized_extensions:
                continue
            file_path = Path(current_directory) / filename
            date_text = get_file_date(file_path).strftime("%Y-%m-%d")
            grouped_files[date_text].append(file_path)

    return dict(sorted(grouped_files.items()))


class CopyWorker(QtCore.QObject):
    progress_updated = QtCore.Signal(int, int, str)
    succeeded = QtCore.Signal(list)
    failed = QtCore.Signal(str)

    def __init__(self, import_plan: ImportPlan, target_directory: Path) -> None:
        super().__init__()
        self._import_plan = import_plan
        self._target_directory = target_directory

    @QtCore.Slot()
    def run(self) -> None:
        total_files = sum(len(files) for _, files in self._import_plan)
        completed_files = 0
        copied_source_files: list[Path] = []

        try:
            for folder_name, source_files in self._import_plan:
                destination_directory = self._target_directory / folder_name
                destination_directory.mkdir(parents=True, exist_ok=True)
                for source_file in source_files:
                    destination_path = ensure_unique_path(
                        destination_directory, source_file.name
                    )
                    shutil.copy2(source_file, destination_path)
                    copied_source_files.append(source_file)
                    completed_files += 1
                    self.progress_updated.emit(
                        completed_files, total_files, str(source_file)
                    )
            self.succeeded.emit(copied_source_files)
        except Exception as exc:
            self.failed.emit(str(exc))


def configure_application_font() -> str:
    """Use a complete Simplified Chinese UI font with antialiasing."""
    application = QtWidgets.QApplication.instance()
    available_families = set(QtGui.QFontDatabase.families())
    if not any(family in available_families for family in UI_FONT_CANDIDATES):
        for font_path in UI_FONT_FILES:
            if not font_path.exists():
                continue
            font_id = QtGui.QFontDatabase.addApplicationFont(str(font_path))
            if font_id >= 0:
                available_families.update(
                    QtGui.QFontDatabase.applicationFontFamilies(font_id)
                )
    family = next(
        (candidate for candidate in UI_FONT_CANDIDATES if candidate in available_families),
        QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.GeneralFont).family(),
    )
    font = QtGui.QFont(family, 10)
    font.setStyleStrategy(
        QtGui.QFont.StyleStrategy.PreferAntialias
        | QtGui.QFont.StyleStrategy.PreferQuality
    )
    application.setFont(font)
    return family


def configure_qt_translations() -> None:
    """Install Qt's Simplified Chinese translations for standard dialogs."""
    application = QtWidgets.QApplication.instance()
    if getattr(application, "_copyer_qt_translators", None):
        return
    translation_directory = QtCore.QLibraryInfo.path(
        QtCore.QLibraryInfo.LibraryPath.TranslationsPath
    )
    translators: list[QtCore.QTranslator] = []
    for catalog in ("qt_zh_CN", "qtbase_zh_CN"):
        translator = QtCore.QTranslator(application)
        if translator.load(catalog, translation_directory):
            application.installTranslator(translator)
            translators.append(translator)
    application._copyer_qt_translators = translators


class FramelessTitleBar(QtWidgets.QWidget):
    """Compact shared title bar for frameless windows and dialogs."""

    def __init__(
        self,
        window: QtWidgets.QWidget,
        title: str,
        *,
        allow_minimize: bool = False,
        allow_maximize: bool = False,
    ) -> None:
        super().__init__(window)
        self._window = window
        self._allow_maximize = allow_maximize
        self._drag_offset: QtCore.QPoint | None = None
        self.setObjectName("titleBar")
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedHeight(38)

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(14, 0, 0, 0)
        layout.setSpacing(0)

        title_label = QtWidgets.QLabel(title)
        title_label.setObjectName("titleLabel")
        layout.addWidget(title_label)
        layout.addStretch()

        self.minimize_button: QtWidgets.QToolButton | None = None
        self.maximize_button: QtWidgets.QToolButton | None = None
        if allow_minimize:
            self.minimize_button = self._make_control("windowMinimizeButton", "—")
            self.minimize_button.setToolTip("最小化")
            self.minimize_button.clicked.connect(window.showMinimized)
            layout.addWidget(self.minimize_button)
        if allow_maximize:
            self.maximize_button = self._make_control("windowMaximizeButton", "□")
            self.maximize_button.setToolTip("最大化")
            self.maximize_button.clicked.connect(self.toggle_maximized)
            layout.addWidget(self.maximize_button)

        self.close_button = self._make_control("windowCloseButton", "×")
        self.close_button.setToolTip("关闭")
        self.close_button.clicked.connect(window.close)
        layout.addWidget(self.close_button)

    def _make_control(self, object_name: str, text: str) -> QtWidgets.QToolButton:
        button = QtWidgets.QToolButton(self)
        button.setObjectName(object_name)
        button.setProperty("windowControl", True)
        button.setText(text)
        button.setAutoRaise(True)
        button.setFixedSize(42, 38)
        return button

    def toggle_maximized(self) -> None:
        if not self._allow_maximize:
            return
        if self._window.isMaximized():
            self._window.showNormal()
        else:
            self._window.showMaximized()
        self.sync_maximize_button()

    def sync_maximize_button(self) -> None:
        if self.maximize_button is not None:
            self.maximize_button.setText("❐" if self._window.isMaximized() else "□")
            self.maximize_button.setToolTip(
                "还原" if self._window.isMaximized() else "最大化"
            )

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self._drag_offset = (
                event.globalPosition().toPoint() - self._window.frameGeometry().topLeft()
            )
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:
        if (
            self._drag_offset is not None
            and event.buttons() & QtCore.Qt.MouseButton.LeftButton
            and not self._window.isMaximized()
        ):
            self._window.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        self._drag_offset = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() == QtCore.Qt.MouseButton.LeftButton and self._allow_maximize:
            self.toggle_maximized()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class FramelessMessageDialog(QtWidgets.QDialog):
    """Frameless replacement for informational and confirmation message boxes."""

    def __init__(
        self,
        parent: QtWidgets.QWidget,
        title: str,
        message: str,
        *,
        kind: str = "info",
        confirmation: bool = False,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("messageDialog")
        self.setWindowTitle(title)
        self.setWindowFlags(
            QtCore.Qt.WindowType.Dialog | QtCore.Qt.WindowType.FramelessWindowHint
        )
        self.setModal(True)
        self.setMinimumWidth(420)
        self.setMaximumWidth(580)

        outer_layout = QtWidgets.QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)
        self.title_bar = FramelessTitleBar(self, title)
        outer_layout.addWidget(self.title_bar)

        content = QtWidgets.QWidget()
        content.setObjectName("dialogContent")
        content_layout = QtWidgets.QVBoxLayout(content)
        content_layout.setContentsMargins(22, 18, 22, 20)
        content_layout.setSpacing(16)

        marker_text = {
            "info": "信息",
            "warning": "注意",
            "error": "错误",
            "danger": "危险操作",
        }.get(kind, "信息")
        marker = QtWidgets.QLabel(marker_text)
        marker.setObjectName("dangerMarker" if kind in {"error", "danger"} else "dialogMarker")
        content_layout.addWidget(marker)

        message_label = QtWidgets.QLabel(message)
        message_label.setObjectName("dialogMessage")
        message_label.setWordWrap(True)
        message_label.setTextInteractionFlags(
            QtCore.Qt.TextInteractionFlag.TextSelectableByMouse
        )
        content_layout.addWidget(message_label)

        button_layout = QtWidgets.QHBoxLayout()
        button_layout.addStretch()
        if confirmation:
            cancel_button = QtWidgets.QPushButton("取消")
            cancel_button.clicked.connect(self.reject)
            button_layout.addWidget(cancel_button)
            confirm_button = QtWidgets.QPushButton("确认删除")
            confirm_button.setObjectName("dangerConfirmAction")
            confirm_button.clicked.connect(self.accept)
            button_layout.addWidget(confirm_button)
            confirm_button.setDefault(True)
        else:
            confirm_button = QtWidgets.QPushButton("确定")
            confirm_button.setObjectName("primaryAction")
            confirm_button.clicked.connect(self.accept)
            button_layout.addWidget(confirm_button)
            confirm_button.setDefault(True)
        content_layout.addLayout(button_layout)
        outer_layout.addWidget(content)


class FramelessDirectoryDialog(QtWidgets.QFileDialog):
    """Qt directory chooser with the same frameless title bar as the application."""

    def __init__(
        self,
        parent: QtWidgets.QWidget,
        title: str,
        directory: str = "",
    ) -> None:
        super().__init__(parent, title, directory)
        self.setObjectName("directoryDialog")
        self.setWindowFlags(
            QtCore.Qt.WindowType.Dialog | QtCore.Qt.WindowType.FramelessWindowHint
        )
        self.setOption(QtWidgets.QFileDialog.Option.DontUseNativeDialog, True)
        self.setOption(QtWidgets.QFileDialog.Option.ShowDirsOnly, True)
        self.setFileMode(QtWidgets.QFileDialog.FileMode.Directory)
        self.setAcceptMode(QtWidgets.QFileDialog.AcceptMode.AcceptOpen)
        self.setLabelText(QtWidgets.QFileDialog.DialogLabel.LookIn, "位置：")
        self.setLabelText(QtWidgets.QFileDialog.DialogLabel.FileName, "文件夹：")
        self.setLabelText(QtWidgets.QFileDialog.DialogLabel.FileType, "文件类型：")
        self.setLabelText(QtWidgets.QFileDialog.DialogLabel.Accept, "选择此文件夹")
        self.setLabelText(QtWidgets.QFileDialog.DialogLabel.Reject, "取消")
        self.resize(820, 540)

        dialog_layout = self.layout()
        if isinstance(dialog_layout, QtWidgets.QGridLayout):
            layout_items: list[
                tuple[QtWidgets.QLayoutItem, int, int, int, int]
            ] = []
            for index in reversed(range(dialog_layout.count())):
                row, column, row_span, column_span = dialog_layout.getItemPosition(index)
                item = dialog_layout.takeAt(index)
                layout_items.append((item, row, column, row_span, column_span))
            for item, row, column, row_span, column_span in reversed(layout_items):
                dialog_layout.addItem(item, row + 1, column, row_span, column_span)
            self.title_bar = FramelessTitleBar(self, title)
            dialog_layout.addWidget(
                self.title_bar,
                0,
                0,
                1,
                max(1, dialog_layout.columnCount()),
            )


def show_message(
    parent: QtWidgets.QWidget,
    title: str,
    message: str,
    *,
    kind: str = "info",
) -> None:
    FramelessMessageDialog(parent, title, message, kind=kind).exec()


def ask_delete_confirmation(
    parent: QtWidgets.QWidget,
    title: str,
    message: str,
) -> bool:
    dialog = FramelessMessageDialog(
        parent,
        title,
        message,
        kind="danger",
        confirmation=True,
    )
    return dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted


def choose_directory(
    parent: QtWidgets.QWidget,
    title: str,
    directory: str = "",
) -> str:
    dialog = FramelessDirectoryDialog(parent, title, directory)
    if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
        return ""
    selected_files = dialog.selectedFiles()
    return selected_files[0] if selected_files else ""


class MediaImporterWindow(QtWidgets.QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowFlags(
            QtCore.Qt.WindowType.Window | QtCore.Qt.WindowType.FramelessWindowHint
        )
        self.setWindowTitle(WINDOW_TITLE)
        self.resize(WINDOW_WIDTH, WINDOW_HEIGHT)

        app_icon = load_app_icon()
        if app_icon is not None:
            self.setWindowIcon(app_icon)

        self.file_groups: FileGroups = {}
        self.suffix_inputs: dict[int, QtWidgets.QLineEdit] = {}
        self.copied_source_files: list[Path] = []
        self._copy_thread: QtCore.QThread | None = None
        self._copy_worker: CopyWorker | None = None

        self.settings = QtCore.QSettings(APP_ORGANIZATION, APP_NAME)
        self._is_loading_settings = True

        self._build_interface()
        self._apply_theme()
        self._restore_settings()
        self._connect_settings_persistence()
        self._is_loading_settings = False

        if not self.source_path_input.text().strip():
            self._auto_detect_card()

    def _build_interface(self) -> None:
        central_widget = QtWidgets.QWidget()
        central_widget.setObjectName("applicationRoot")
        self.setCentralWidget(central_widget)
        outer_layout = QtWidgets.QVBoxLayout(central_widget)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)
        self.title_bar = FramelessTitleBar(
            self,
            WINDOW_TITLE,
            allow_minimize=True,
            allow_maximize=True,
        )
        outer_layout.addWidget(self.title_bar)

        content_widget = QtWidgets.QWidget()
        content_widget.setObjectName("applicationContent")
        root_layout = QtWidgets.QVBoxLayout(content_widget)
        root_layout.setContentsMargins(16, 14, 16, 16)
        root_layout.setSpacing(12)
        outer_layout.addWidget(content_widget, stretch=1)

        source_group = QtWidgets.QGroupBox("读卡器 / 源路径")
        source_layout = QtWidgets.QHBoxLayout(source_group)
        self.source_path_input = QtWidgets.QLineEdit()
        self.source_path_input.setPlaceholderText("自动识别读卡器，或手动选择文件夹")
        detect_card_button = QtWidgets.QPushButton("自动识别")
        choose_source_button = QtWidgets.QPushButton("手动选择")
        detect_card_button.clicked.connect(self._auto_detect_card)
        choose_source_button.clicked.connect(self._choose_source_directory)
        source_layout.addWidget(self.source_path_input)
        source_layout.addWidget(detect_card_button)
        source_layout.addWidget(choose_source_button)
        root_layout.addWidget(source_group)

        target_group = QtWidgets.QGroupBox("导入到")
        target_layout = QtWidgets.QHBoxLayout(target_group)
        self.target_path_input = QtWidgets.QLineEdit(str(Path.home() / "Pictures"))
        choose_target_button = QtWidgets.QPushButton("选择文件夹")
        choose_target_button.clicked.connect(self._choose_target_directory)
        target_layout.addWidget(self.target_path_input)
        target_layout.addWidget(choose_target_button)
        root_layout.addWidget(target_group)

        format_group = QtWidgets.QGroupBox("选择格式")
        format_layout = QtWidgets.QHBoxLayout(format_group)
        self.raw_checkbox = QtWidgets.QCheckBox("RAW (.cr2/.cr3/...)")
        self.jpeg_checkbox = QtWidgets.QCheckBox("JPEG (.jpg)")
        self.video_checkbox = QtWidgets.QCheckBox("视频 (.mp4/.mov)")
        self.raw_checkbox.setChecked(True)
        self.jpeg_checkbox.setChecked(True)
        select_all_formats_button = QtWidgets.QPushButton("全选格式")
        select_all_formats_button.clicked.connect(self._select_all_formats)
        format_layout.addWidget(self.raw_checkbox)
        format_layout.addWidget(self.jpeg_checkbox)
        format_layout.addWidget(self.video_checkbox)
        format_layout.addStretch()
        format_layout.addWidget(select_all_formats_button)
        root_layout.addWidget(format_group)

        actions_layout = QtWidgets.QHBoxLayout()
        self.scan_button = QtWidgets.QPushButton("扫描文件")
        self.import_button = QtWidgets.QPushButton("开始导入")
        self.open_target_button = QtWidgets.QPushButton("打开目标文件夹")
        self.delete_sources_button = QtWidgets.QPushButton("删除存储卡已复制文件")
        self.import_button.setObjectName("primaryAction")
        self.delete_sources_button.setObjectName("dangerAction")
        actions_layout.addWidget(self.scan_button)
        actions_layout.addWidget(self.import_button)
        actions_layout.addStretch()
        actions_layout.addWidget(self.open_target_button)
        actions_layout.addWidget(self.delete_sources_button)
        root_layout.addLayout(actions_layout)

        self.scan_button.clicked.connect(self._scan_files)
        self.import_button.clicked.connect(self._start_import)
        self.open_target_button.clicked.connect(self._open_target_directory)
        self.delete_sources_button.clicked.connect(self._delete_copied_sources)

        self.groups_table = QtWidgets.QTableWidget(0, 4)
        self.groups_table.setHorizontalHeaderLabels(
            ["日期", "数量", "自定义后缀", "生成的文件夹名"]
        )
        table_header = self.groups_table.horizontalHeader()
        table_header.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeToContents)
        table_header.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeToContents)
        table_header.setSectionResizeMode(2, QtWidgets.QHeaderView.Stretch)
        table_header.setSectionResizeMode(3, QtWidgets.QHeaderView.ResizeToContents)
        root_layout.addWidget(self.groups_table, stretch=1)

        progress_layout = QtWidgets.QHBoxLayout()
        self.progress_bar = QtWidgets.QProgressBar()
        self.progress_label = QtWidgets.QLabel("未开始")
        progress_layout.addWidget(self.progress_bar, stretch=1)
        progress_layout.addWidget(self.progress_label)
        root_layout.addLayout(progress_layout)

        self.log_output = QtWidgets.QPlainTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setPlaceholderText("执行日志...")
        root_layout.addWidget(self.log_output, stretch=1)

    def _apply_theme(self) -> None:
        QtWidgets.QApplication.setStyle("Fusion")
        configure_application_font()
        configure_qt_translations()
        palette = QtGui.QPalette()
        palette.setColor(QtGui.QPalette.Window, QtGui.QColor("#E2E2DE"))
        palette.setColor(QtGui.QPalette.WindowText, QtGui.QColor("#222424"))
        palette.setColor(QtGui.QPalette.Base, QtGui.QColor("#F2F2EE"))
        palette.setColor(QtGui.QPalette.AlternateBase, QtGui.QColor("#D5D6D2"))
        palette.setColor(QtGui.QPalette.Text, QtGui.QColor("#222424"))
        palette.setColor(QtGui.QPalette.Button, QtGui.QColor("#E8E8E4"))
        palette.setColor(QtGui.QPalette.ButtonText, QtGui.QColor("#243746"))
        palette.setColor(QtGui.QPalette.Highlight, QtGui.QColor("#243746"))
        palette.setColor(QtGui.QPalette.HighlightedText, QtGui.QColor(255, 255, 255))
        palette.setColor(QtGui.QPalette.PlaceholderText, QtGui.QColor("#676B69"))
        palette.setColor(QtGui.QPalette.Disabled, QtGui.QPalette.Text, QtGui.QColor("#898D8A"))
        palette.setColor(
            QtGui.QPalette.Disabled, QtGui.QPalette.ButtonText, QtGui.QColor("#898D8A")
        )
        QtWidgets.QApplication.instance().setPalette(palette)
        QtWidgets.QApplication.instance().setStyleSheet(
            """
            QWidget { color: #222424; }
            QWidget#applicationRoot, QWidget#applicationContent,
            QDialog#messageDialog, QFileDialog#directoryDialog { background: #E2E2DE; }
            QWidget#titleBar {
                background: #243746;
                border: 0;
            }
            QLabel#titleLabel { color: #F2F2EE; font-weight: 600; }
            QToolButton[windowControl="true"] {
                background: transparent;
                color: #F2F2EE;
                border: 0;
                border-radius: 0;
                font-size: 17px;
            }
            QToolButton[windowControl="true"]:hover { background: #304A5D; }
            QToolButton#windowCloseButton:hover { background: #762F3D; color: #FFFFFF; }
            QGroupBox {
                background: transparent;
                border: 0;
                border-top: 1px solid #B8BAB6;
                margin-top: 10px;
                padding: 7px;
                padding-top: 14px;
                font-weight: 600;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 7px;
                padding: 0 4px;
                background: #E2E2DE;
                color: #243746;
            }
            QLineEdit, QPlainTextEdit, QTableWidget, QTreeView, QListView, QComboBox {
                background: #F2F2EE;
                border: 1px solid #B8BAB6;
                border-radius: 3px;
                selection-background-color: #243746;
                selection-color: #FFFFFF;
            }
            QLineEdit:focus, QPlainTextEdit:focus, QTableWidget:focus,
            QTreeView:focus, QListView:focus, QComboBox:focus {
                border: 2px solid #243746;
            }
            QHeaderView::section {
                background: #D5D6D2;
                color: #243746;
                border: 0;
                border-right: 1px solid #B8BAB6;
                border-bottom: 1px solid #B8BAB6;
                padding: 5px 7px;
                font-weight: 600;
            }
            QTableWidget::item { padding: 3px 6px; }
            QTableWidget::item:selected { background: #D5D6D2; color: #222424; }
            QPushButton {
                background: #E8E8E4;
                color: #243746;
                border: 1px solid #B8BAB6;
                border-radius: 3px;
                padding: 5px 10px;
            }
            QPushButton:hover { background: #D5D6D2; border-color: #243746; }
            QPushButton:focus { border: 2px solid #243746; }
            QPushButton:disabled { color: #898D8A; background: #D9DAD6; border-color: #C9CBC7; }
            QPushButton#primaryAction { background: #243746; color: #FFFFFF; border-color: #243746; }
            QPushButton#primaryAction:hover { background: #304A5D; border-color: #304A5D; }
            QPushButton#primaryAction:focus { border: 2px solid #762F3D; }
            QPushButton#dangerAction, QPushButton#dangerConfirmAction { color: #762F3D; border-color: #762F3D; }
            QPushButton#dangerAction:hover, QPushButton#dangerConfirmAction:hover { background: #762F3D; color: #FFFFFF; }
            QCheckBox { spacing: 6px; }
            QCheckBox::indicator { width: 14px; height: 14px; border: 1px solid #676B69; border-radius: 2px; background: #F2F2EE; }
            QCheckBox::indicator:checked { background: #243746; border-color: #243746; }
            QProgressBar { background: #D5D6D2; border: 1px solid #B8BAB6; border-radius: 3px; text-align: center; }
            QProgressBar::chunk { background: #243746; border-radius: 2px; }
            QWidget#dialogContent { background: #F2F2EE; }
            QLabel#dialogMarker { color: #243746; font-weight: 600; }
            QLabel#dangerMarker { color: #762F3D; font-weight: 600; }
            QLabel#dialogMessage { color: #222424; min-height: 34px; }
            QFileDialog QFrame { border: 0; }
            QFileDialog QToolButton { background: transparent; border: 0; color: #243746; padding: 4px; }
            QFileDialog QToolButton:hover { background: #D5D6D2; }
            QScrollBar:vertical {
                background: #D5D6D2;
                width: 7px;
                margin: 0;
            }
            QScrollBar:horizontal {
                background: #D5D6D2;
                height: 7px;
                margin: 0;
            }
            QScrollBar::handle:vertical, QScrollBar::handle:horizontal {
                background: #762F3D;
                border: 0;
                border-radius: 2px;
                min-height: 24px;
                min-width: 24px;
            }
            QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover {
                background: #68303A;
            }
            QScrollBar::add-line, QScrollBar::sub-line {
                width: 0;
                height: 0;
                background: transparent;
                border: 0;
            }
            QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
            """
        )

    def changeEvent(self, event: QtCore.QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QtCore.QEvent.Type.WindowStateChange:
            self.title_bar.sync_maximize_button()

    def _restore_settings(self) -> None:
        source_path = self.settings.value("paths/source", "", type=str)
        target_path = self.settings.value("paths/target", "", type=str)
        raw_selected = self.settings.value("formats/raw", True, type=bool)
        jpeg_selected = self.settings.value("formats/jpg", True, type=bool)
        video_selected = self.settings.value("formats/mp4", False, type=bool)

        if source_path:
            self.source_path_input.setText(source_path)
        if target_path:
            self.target_path_input.setText(target_path)
        self.raw_checkbox.setChecked(raw_selected)
        self.jpeg_checkbox.setChecked(jpeg_selected)
        self.video_checkbox.setChecked(video_selected)

    def _save_settings(self) -> None:
        if self._is_loading_settings:
            return
        self.settings.setValue("paths/source", self.source_path_input.text().strip())
        self.settings.setValue("paths/target", self.target_path_input.text().strip())
        self.settings.setValue("formats/raw", self.raw_checkbox.isChecked())
        self.settings.setValue("formats/jpg", self.jpeg_checkbox.isChecked())
        self.settings.setValue("formats/mp4", self.video_checkbox.isChecked())

    def _connect_settings_persistence(self) -> None:
        self.source_path_input.textChanged.connect(self._save_settings)
        self.target_path_input.textChanged.connect(self._save_settings)
        self.raw_checkbox.stateChanged.connect(self._save_settings)
        self.jpeg_checkbox.stateChanged.connect(self._save_settings)
        self.video_checkbox.stateChanged.connect(self._save_settings)

    def _log(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_output.appendPlainText(f"[{timestamp}] {message}")

    def _select_all_formats(self) -> None:
        self.raw_checkbox.setChecked(True)
        self.jpeg_checkbox.setChecked(True)
        self.video_checkbox.setChecked(True)

    def _auto_detect_card(self) -> None:
        removable_drives = detect_removable_drives()
        if removable_drives:
            self.source_path_input.setText(removable_drives[0])
            self._log(f"已识别读卡器: {removable_drives[0]}")
        else:
            self._log("未发现读卡器，请手动选择文件夹。")

    def _choose_source_directory(self) -> None:
        selected_path = choose_directory(self, "选择读卡器或源文件夹")
        if selected_path:
            self.source_path_input.setText(selected_path)

    def _choose_target_directory(self) -> None:
        selected_path = choose_directory(
            self,
            "选择目标文件夹",
            self.target_path_input.text(),
        )
        if selected_path:
            self.target_path_input.setText(selected_path)

    def _selected_extensions(self) -> set[str]:
        selected_extensions: set[str] = set()
        if self.raw_checkbox.isChecked():
            selected_extensions.update(RAW_EXTENSIONS)
        if self.jpeg_checkbox.isChecked():
            selected_extensions.update(JPEG_EXTENSIONS)
        if self.video_checkbox.isChecked():
            selected_extensions.update(VIDEO_EXTENSIONS)
        return selected_extensions

    def _scan_files(self) -> None:
        source_directory = Path(self.source_path_input.text().strip())
        if not source_directory.exists():
            show_message(
                self,
                "提示",
                "源路径不存在，请先选择读卡器或文件夹。",
                kind="warning",
            )
            return

        selected_extensions = self._selected_extensions()
        if not selected_extensions:
            show_message(self, "提示", "请至少选择一种格式。", kind="warning")
            return

        self._log("开始扫描文件...")
        file_groups = scan_media_files(source_directory, selected_extensions)
        if not file_groups:
            show_message(self, "结果", "未找到符合条件的文件。")
            self.groups_table.setRowCount(0)
            self.file_groups = {}
            return

        self.file_groups = file_groups
        self._populate_groups_table()
        total_files = sum(len(files) for files in file_groups.values())
        self._log(f"扫描完成，共 {total_files} 个文件，{len(file_groups)} 天。")

    def _populate_groups_table(self) -> None:
        self.groups_table.setRowCount(0)
        self.suffix_inputs.clear()

        for row_index, (date_text, files) in enumerate(self.file_groups.items()):
            self.groups_table.insertRow(row_index)
            self.groups_table.setItem(
                row_index, 0, QtWidgets.QTableWidgetItem(date_text)
            )
            self.groups_table.setItem(
                row_index, 1, QtWidgets.QTableWidgetItem(str(len(files)))
            )

            suffix_input = QtWidgets.QLineEdit()
            suffix_input.setPlaceholderText("可选：输入后缀")
            suffix_input.textChanged.connect(
                lambda text, current_row=row_index: self._update_folder_preview(
                    current_row, text
                )
            )
            self.groups_table.setCellWidget(row_index, 2, suffix_input)

            preview_item = QtWidgets.QTableWidgetItem(date_text)
            preview_item.setFlags(QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsSelectable)
            self.groups_table.setItem(row_index, 3, preview_item)
            self.suffix_inputs[row_index] = suffix_input

        self.groups_table.resizeRowsToContents()

    def _update_folder_preview(self, row_index: int, suffix: str) -> None:
        date_text = self.groups_table.item(row_index, 0).text()
        folder_name = build_destination_folder_name(date_text, suffix)
        self.groups_table.item(row_index, 3).setText(folder_name)

    def _build_import_plan(self) -> ImportPlan:
        import_plan: ImportPlan = []
        for row_index in range(self.groups_table.rowCount()):
            date_text = self.groups_table.item(row_index, 0).text()
            suffix_widget = self.groups_table.cellWidget(row_index, 2)
            suffix = (
                suffix_widget.text()
                if isinstance(suffix_widget, QtWidgets.QLineEdit)
                else ""
            )
            folder_name = build_destination_folder_name(date_text, suffix)
            import_plan.append((folder_name, self.file_groups.get(date_text, [])))
        return import_plan

    def _start_import(self) -> None:
        if not self.file_groups:
            show_message(self, "提示", "请先扫描文件。", kind="warning")
            return

        target_directory = Path(self.target_path_input.text().strip())
        if not target_directory.exists():
            try:
                target_directory.mkdir(parents=True, exist_ok=True)
            except Exception as exc:
                show_message(
                    self,
                    "错误",
                    f"无法创建目标目录：{exc}",
                    kind="error",
                )
                return

        import_plan = self._build_import_plan()
        total_files = sum(len(files) for _, files in import_plan)
        if total_files == 0:
            show_message(self, "提示", "没有可导入的文件。")
            return

        self.progress_bar.setMaximum(total_files)
        self.progress_bar.setValue(0)
        self.progress_label.setText("导入中...")
        self._set_action_buttons_enabled(False)

        copy_thread = QtCore.QThread()
        copy_worker = CopyWorker(import_plan, target_directory)
        copy_worker.moveToThread(copy_thread)
        copy_thread.started.connect(copy_worker.run)
        copy_worker.progress_updated.connect(self._on_copy_progress)
        copy_worker.succeeded.connect(self._on_copy_succeeded)
        copy_worker.failed.connect(self._on_copy_failed)
        copy_worker.succeeded.connect(copy_thread.quit)
        copy_worker.failed.connect(copy_thread.quit)
        copy_thread.finished.connect(copy_worker.deleteLater)
        copy_thread.finished.connect(self._clear_copy_task)

        self._copy_thread = copy_thread
        self._copy_worker = copy_worker
        copy_thread.start()
        self._log("开始导入...")

    def _on_copy_progress(self, completed: int, total: int, source_path: str) -> None:
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(completed)
        self.progress_label.setText(f"{completed}/{total}")
        self._log(f"复制: {source_path}")

    def _on_copy_succeeded(self, copied_source_files: list[Path]) -> None:
        self.copied_source_files = copied_source_files
        self.progress_label.setText("完成")
        self._set_action_buttons_enabled(True)
        self._log(f"导入完成，共复制 {len(copied_source_files)} 个文件。")

    def _on_copy_failed(self, error_message: str) -> None:
        self.progress_label.setText("失败")
        self._set_action_buttons_enabled(True)
        show_message(self, "导入失败", error_message, kind="error")
        self._log(f"导入失败：{error_message}")

    def _clear_copy_task(self) -> None:
        self._copy_worker = None
        self._copy_thread = None

    def _set_action_buttons_enabled(self, enabled: bool) -> None:
        self.scan_button.setEnabled(enabled)
        self.import_button.setEnabled(enabled)
        self.open_target_button.setEnabled(enabled)
        self.delete_sources_button.setEnabled(enabled)

    def _open_target_directory(self) -> None:
        target_path = self.target_path_input.text().strip()
        if not target_path:
            return
        if os.name == "nt":
            os.startfile(target_path)
        else:
            QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(target_path))

    def _delete_copied_sources(self) -> None:
        if not self.copied_source_files:
            show_message(self, "提示", "当前没有记录可删除的已复制文件。")
            return

        confirmation = ask_delete_confirmation(
            self,
            "删除确认",
            f"确认删除存储卡中已复制的 {len(self.copied_source_files)} 个文件吗？此操作不可撤销。",
        )
        if not confirmation:
            return

        deleted_count = 0
        skipped_count = 0
        failed_count = 0
        for source_path in self.copied_source_files:
            try:
                if source_path.exists():
                    source_path.unlink()
                    deleted_count += 1
                else:
                    skipped_count += 1
            except Exception:
                failed_count += 1

        result_message = f"删除完成：成功 {deleted_count}，跳过 {skipped_count}，失败 {failed_count}。"
        self._log(result_message)
        show_message(self, "结果", result_message)


def main() -> None:
    application = QtWidgets.QApplication(sys.argv)
    window = MediaImporterWindow()
    window.show()
    sys.exit(application.exec())


if __name__ == "__main__":
    main()
