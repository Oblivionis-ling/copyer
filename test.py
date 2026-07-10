from __future__ import annotations

import ctypes
import os
import shutil
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

try:
    from PySide6 import QtCore, QtGui, QtWidgets
except ImportError as exc:  # noqa: F401
    raise SystemExit(
        "未找到 PySide6，请先安装：pip install PySide6"
    ) from exc

try:
    from PIL import Image  # type: ignore
except ImportError:
    Image = None


RAW_EXTS = {".cr2", ".cr3", ".nef", ".arw", ".raf", ".orf", ".rw2", ".dng"}
JPEG_EXTS = {".jpg", ".jpeg"}
VIDEO_EXTS = {".mp4", ".mov", ".m4v"}
ICON_FILES = ("app_icon.ico",)


def _resource_base_dir() -> Path:
    bundled_dir = getattr(sys, "_MEIPASS", None)
    if bundled_dir:
        return Path(bundled_dir)
    return Path(__file__).resolve().parent


def load_app_icon() -> QtGui.QIcon | None:
    base_dir = _resource_base_dir()
    for name in ICON_FILES:
        path = base_dir / name
        if path.exists():
            return QtGui.QIcon(str(path))
    return None


def detect_removable_drives() -> List[str]:
    """返回当前可移动磁盘根路径列表（Windows）。"""
    drives: List[str] = []
    if os.name != "nt":
        return drives

    bitmask = ctypes.windll.kernel32.GetLogicalDrives()
    for i in range(26):
        if bitmask & (1 << i):
            root = f"{chr(65 + i)}:\\"
            dtype = ctypes.windll.kernel32.GetDriveTypeW(ctypes.c_wchar_p(root))
            if dtype == 2:  # DRIVE_REMOVABLE
                drives.append(root)
    return drives


def read_exif_datetime(path: Path) -> datetime | None:
    """优先用 EXIF DateTimeOriginal，失败则返回 None。仅对 JPG 尝试。"""
    if Image is None or path.suffix.lower() not in JPEG_EXTS:
        return None
    try:
        with Image.open(path) as img:
            exif = img.getexif()
            if not exif:
                return None
            for tag in (36867, 306):  # DateTimeOriginal, DateTime
                value = exif.get(tag)
                if value:
                    return datetime.strptime(str(value), "%Y:%m:%d %H:%M:%S")
    except Exception:
        return None
    return None


def get_file_date(path: Path) -> datetime.date:
    """获取图片/视频日期，EXIF 优先，失败用修改时间兜底。"""
    exif_dt = read_exif_datetime(path)
    if exif_dt:
        return exif_dt.date()
    mtime = path.stat().st_mtime
    return datetime.fromtimestamp(mtime).date()


def ensure_unique_path(dest_dir: Path, filename: str) -> Path:
    """同名文件自动递增后缀，避免漏传。"""
    base = dest_dir / filename
    if not base.exists():
        return base

    stem = base.stem
    suffix = base.suffix
    idx = 1
    while True:
        candidate = dest_dir / f"{stem}_{idx}{suffix}"
        if not candidate.exists():
            return candidate
        idx += 1


class CopyWorker(QtCore.QObject):
    progress = QtCore.Signal(int, int, str)
    finished = QtCore.Signal(list)
    failed = QtCore.Signal(str)

    def __init__(self, plan: List[Tuple[str, List[Path]]], target_root: Path):
        super().__init__()
        self.plan = plan
        self.target_root = target_root

    @QtCore.Slot()
    def run(self) -> None:
        total = sum(len(files) for _, files in self.plan)
        done = 0
        copied: List[Path] = []
        try:
            for folder_name, files in self.plan:
                dest_dir = self.target_root / folder_name
                dest_dir.mkdir(parents=True, exist_ok=True)
                for src in files:
                    dest_path = ensure_unique_path(dest_dir, src.name)
                    shutil.copy2(src, dest_path)
                    copied.append(src)
                    done += 1
                    self.progress.emit(done, total, str(src))
            self.finished.emit(copied)
        except Exception as exc:
            self.failed.emit(str(exc))


class ImporterWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("读卡器照片/视频导入工具")
        self.resize(1100, 720)
        icon = load_app_icon()
        if icon is not None:
            self.setWindowIcon(icon)
        self.grouped_files: Dict[str, List[Path]] = {}
        self.suffix_inputs: Dict[int, QtWidgets.QLineEdit] = {}
        self.copied_files: List[Path] = []
        self.copy_thread: QtCore.QThread | None = None
        self.copy_worker: CopyWorker | None = None

        self.settings = QtCore.QSettings("copyer", "copyer")
        self._loading_settings = True

        self._build_ui()
        self._apply_palette()
        self._load_settings()
        self._setup_persistence_signals()
        self._loading_settings = False
        if not self.source_path_edit.text().strip():
            self._auto_detect_card()

    def _build_ui(self) -> None:
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        root_layout = QtWidgets.QVBoxLayout(central)
        root_layout.setSpacing(12)

        # 源路径选择
        source_group = QtWidgets.QGroupBox("读卡器 / 源路径")
        src_layout = QtWidgets.QHBoxLayout(source_group)
        self.source_path_edit = QtWidgets.QLineEdit()
        self.source_path_edit.setPlaceholderText("自动识别读卡器，或手动选择文件夹")
        btn_detect = QtWidgets.QPushButton("自动识别")
        btn_browse = QtWidgets.QPushButton("手动选择")
        btn_detect.clicked.connect(self._auto_detect_card)
        btn_browse.clicked.connect(self._choose_source)
        src_layout.addWidget(self.source_path_edit)
        src_layout.addWidget(btn_detect)
        src_layout.addWidget(btn_browse)
        root_layout.addWidget(source_group)

        # 目标路径
        target_group = QtWidgets.QGroupBox("导入到")
        tgt_layout = QtWidgets.QHBoxLayout(target_group)
        self.target_path_edit = QtWidgets.QLineEdit(str(Path.home() / "Pictures"))
        btn_target = QtWidgets.QPushButton("选择文件夹")
        btn_target.clicked.connect(self._choose_target)
        tgt_layout.addWidget(self.target_path_edit)
        tgt_layout.addWidget(btn_target)
        root_layout.addWidget(target_group)

        # 格式选择
        format_group = QtWidgets.QGroupBox("选择格式")
        fmt_layout = QtWidgets.QHBoxLayout(format_group)
        self.checkbox_raw = QtWidgets.QCheckBox("RAW (.cr2/.cr3/...)")
        self.checkbox_jpg = QtWidgets.QCheckBox("JPEG (.jpg)")
        self.checkbox_mp4 = QtWidgets.QCheckBox("视频 (.mp4/.mov)")
        self.checkbox_raw.setChecked(True)
        self.checkbox_jpg.setChecked(True)
        btn_all_formats = QtWidgets.QPushButton("全选格式")
        btn_all_formats.clicked.connect(self._select_all_formats)
        fmt_layout.addWidget(self.checkbox_raw)
        fmt_layout.addWidget(self.checkbox_jpg)
        fmt_layout.addWidget(self.checkbox_mp4)
        fmt_layout.addStretch()
        fmt_layout.addWidget(btn_all_formats)
        root_layout.addWidget(format_group)

        # 操作按钮
        actions_layout = QtWidgets.QHBoxLayout()
        self.btn_scan = QtWidgets.QPushButton("扫描文件")
        self.btn_import = QtWidgets.QPushButton("开始导入")
        self.btn_open_target = QtWidgets.QPushButton("打开目标文件夹")
        self.btn_delete_source = QtWidgets.QPushButton("删除存储卡已复制文件")
        actions_layout.addWidget(self.btn_scan)
        actions_layout.addWidget(self.btn_import)
        actions_layout.addStretch()
        actions_layout.addWidget(self.btn_open_target)
        actions_layout.addWidget(self.btn_delete_source)
        root_layout.addLayout(actions_layout)

        self.btn_scan.clicked.connect(self._scan_files)
        self.btn_import.clicked.connect(self._start_import)
        self.btn_open_target.clicked.connect(self._open_target_folder)
        self.btn_delete_source.clicked.connect(self._delete_copied_sources)

        # 分组表格
        self.table = QtWidgets.QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["日期", "数量", "自定义后缀", "生成的文件夹名"])
        self.table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QtWidgets.QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QtWidgets.QHeaderView.ResizeToContents)
        root_layout.addWidget(self.table, stretch=1)

        # 进度与日志
        progress_layout = QtWidgets.QHBoxLayout()
        self.progress_bar = QtWidgets.QProgressBar()
        self.progress_label = QtWidgets.QLabel("未开始")
        progress_layout.addWidget(self.progress_bar, stretch=1)
        progress_layout.addWidget(self.progress_label)
        root_layout.addLayout(progress_layout)

        self.log_box = QtWidgets.QPlainTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setPlaceholderText("执行日志...")
        root_layout.addWidget(self.log_box, stretch=1)

    def _apply_palette(self) -> None:
        QtWidgets.QApplication.setStyle("Fusion")
        palette = QtGui.QPalette()
        palette.setColor(QtGui.QPalette.Window, QtGui.QColor(30, 33, 38))
        palette.setColor(QtGui.QPalette.WindowText, QtGui.QColor(240, 240, 240))
        palette.setColor(QtGui.QPalette.Base, QtGui.QColor(24, 26, 31))
        palette.setColor(QtGui.QPalette.AlternateBase, QtGui.QColor(36, 40, 46))
        palette.setColor(QtGui.QPalette.Text, QtGui.QColor(230, 230, 230))
        palette.setColor(QtGui.QPalette.Button, QtGui.QColor(52, 56, 63))
        palette.setColor(QtGui.QPalette.ButtonText, QtGui.QColor(240, 240, 240))
        palette.setColor(QtGui.QPalette.Highlight, QtGui.QColor(64, 132, 214))
        palette.setColor(QtGui.QPalette.HighlightedText, QtGui.QColor(255, 255, 255))
        QtWidgets.QApplication.instance().setPalette(palette)
        source_palette = self.source_path_edit.palette()
        source_palette.setColor(QtGui.QPalette.PlaceholderText, QtGui.QColor(200, 200, 200))
        self.source_path_edit.setPalette(source_palette)

    def _load_settings(self) -> None:
        source_path = self.settings.value("paths/source", "", type=str)
        target_path = self.settings.value("paths/target", "", type=str)
        raw_checked = self.settings.value("formats/raw", True, type=bool)
        jpg_checked = self.settings.value("formats/jpg", True, type=bool)
        mp4_checked = self.settings.value("formats/mp4", False, type=bool)

        if source_path:
            self.source_path_edit.setText(source_path)
        if target_path:
            self.target_path_edit.setText(target_path)
        self.checkbox_raw.setChecked(raw_checked)
        self.checkbox_jpg.setChecked(jpg_checked)
        self.checkbox_mp4.setChecked(mp4_checked)

    def _save_settings(self) -> None:
        if self._loading_settings:
            return
        self.settings.setValue("paths/source", self.source_path_edit.text().strip())
        self.settings.setValue("paths/target", self.target_path_edit.text().strip())
        self.settings.setValue("formats/raw", self.checkbox_raw.isChecked())
        self.settings.setValue("formats/jpg", self.checkbox_jpg.isChecked())
        self.settings.setValue("formats/mp4", self.checkbox_mp4.isChecked())

    def _setup_persistence_signals(self) -> None:
        self.source_path_edit.textChanged.connect(self._save_settings)
        self.target_path_edit.textChanged.connect(self._save_settings)
        self.checkbox_raw.stateChanged.connect(self._save_settings)
        self.checkbox_jpg.stateChanged.connect(self._save_settings)
        self.checkbox_mp4.stateChanged.connect(self._save_settings)

    def _log(self, msg: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_box.appendPlainText(f"[{timestamp}] {msg}")

    def _select_all_formats(self) -> None:
        self.checkbox_raw.setChecked(True)
        self.checkbox_jpg.setChecked(True)
        self.checkbox_mp4.setChecked(True)

    def _auto_detect_card(self) -> None:
        drives = detect_removable_drives()
        if drives:
            self.source_path_edit.setText(drives[0])
            self._log(f"已识别读卡器: {drives[0]}")
        else:
            self._log("未发现读卡器，请手动选择文件夹。")

    def _choose_source(self) -> None:
        path = QtWidgets.QFileDialog.getExistingDirectory(self, "选择读卡器或源文件夹")
        if path:
            self.source_path_edit.setText(path)

    def _choose_target(self) -> None:
        path = QtWidgets.QFileDialog.getExistingDirectory(self, "选择目标文件夹", self.target_path_edit.text())
        if path:
            self.target_path_edit.setText(path)

    def _selected_exts(self) -> Iterable[str]:
        exts: set[str] = set()
        if self.checkbox_raw.isChecked():
            exts |= RAW_EXTS
        if self.checkbox_jpg.isChecked():
            exts |= JPEG_EXTS
        if self.checkbox_mp4.isChecked():
            exts |= VIDEO_EXTS
        return exts

    def _scan_files(self) -> None:
        source = Path(self.source_path_edit.text().strip())
        if not source.exists():
            QtWidgets.QMessageBox.warning(self, "提示", "源路径不存在，请先选择读卡器或文件夹。")
            return
        exts = {ext.lower() for ext in self._selected_exts()}
        if not exts:
            QtWidgets.QMessageBox.warning(self, "提示", "请至少选择一种格式。")
            return

        self._log("开始扫描文件...")
        groups: Dict[str, List[Path]] = defaultdict(list)
        for root, _, files in os.walk(source):
            for name in files:
                ext = Path(name).suffix.lower()
                if ext not in exts:
                    continue
                full_path = Path(root) / name
                date_str = get_file_date(full_path).strftime("%Y-%m-%d")
                groups[date_str].append(full_path)

        if not groups:
            QtWidgets.QMessageBox.information(self, "结果", "未找到符合条件的文件。")
            self.table.setRowCount(0)
            self.grouped_files = {}
            return

        self.grouped_files = dict(sorted(groups.items(), key=lambda kv: kv[0]))
        self._populate_table()
        self._log(f"扫描完成，共 {sum(len(v) for v in groups.values())} 个文件，{len(groups)} 天。")

    def _populate_table(self) -> None:
        self.table.setRowCount(0)
        self.suffix_inputs.clear()
        for row, (date_str, files) in enumerate(self.grouped_files.items()):
            self.table.insertRow(row)
            self.table.setItem(row, 0, QtWidgets.QTableWidgetItem(date_str))
            self.table.setItem(row, 1, QtWidgets.QTableWidgetItem(str(len(files))))
            suffix_edit = QtWidgets.QLineEdit()
            suffix_edit.setPlaceholderText("可选：输入后缀")
            suffix_edit.textChanged.connect(lambda text, r=row: self._update_preview(r, text))
            self.table.setCellWidget(row, 2, suffix_edit)
            preview_item = QtWidgets.QTableWidgetItem(date_str)
            preview_item.setFlags(QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsSelectable)
            self.table.setItem(row, 3, preview_item)
            self.suffix_inputs[row] = suffix_edit
        self.table.resizeRowsToContents()

    def _update_preview(self, row: int, text: str) -> None:
        base = self.table.item(row, 0).text()
        suffix = text.strip()
        folder_name = f"{base}-{suffix}" if suffix else base
        self.table.item(row, 3).setText(folder_name)

    def _collect_plan(self) -> List[Tuple[str, List[Path]]]:
        plan: List[Tuple[str, List[Path]]] = []
        for row in range(self.table.rowCount()):
            date_str = self.table.item(row, 0).text()
            suffix_edit = self.table.cellWidget(row, 2)
            suffix = suffix_edit.text().strip() if isinstance(suffix_edit, QtWidgets.QLineEdit) else ""
            folder_name = f"{date_str}-{suffix}" if suffix else date_str
            files = self.grouped_files.get(date_str, [])
            plan.append((folder_name, files))
        return plan

    def _start_import(self) -> None:
        if not self.grouped_files:
            QtWidgets.QMessageBox.warning(self, "提示", "请先扫描文件。")
            return
        target_root = Path(self.target_path_edit.text().strip())
        if not target_root.exists():
            try:
                target_root.mkdir(parents=True, exist_ok=True)
            except Exception as exc:
                QtWidgets.QMessageBox.critical(self, "错误", f"无法创建目标目录：{exc}")
                return

        plan = self._collect_plan()
        total_files = sum(len(files) for _, files in plan)
        if total_files == 0:
            QtWidgets.QMessageBox.information(self, "提示", "没有可导入的文件。")
            return

        self.progress_bar.setMaximum(total_files)
        self.progress_bar.setValue(0)
        self.progress_label.setText("导入中...")
        self._set_buttons_enabled(False)

        self.copy_thread = QtCore.QThread()
        self.copy_worker = CopyWorker(plan, target_root)
        self.copy_worker.moveToThread(self.copy_thread)
        self.copy_thread.started.connect(self.copy_worker.run)
        self.copy_worker.progress.connect(self._on_progress)
        self.copy_worker.finished.connect(self._on_copy_finished)
        self.copy_worker.failed.connect(self._on_copy_failed)
        self.copy_worker.finished.connect(self.copy_thread.quit)
        self.copy_worker.failed.connect(self.copy_thread.quit)
        self.copy_thread.finished.connect(self.copy_worker.deleteLater)
        self.copy_thread.finished.connect(lambda: setattr(self, "copy_thread", None))
        self.copy_thread.start()
        self._log("开始导入...")

    def _on_progress(self, done: int, total: int, src: str) -> None:
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(done)
        self.progress_label.setText(f"{done}/{total}")
        self._log(f"复制: {src}")

    def _on_copy_finished(self, copied: List[Path]) -> None:
        self.copied_files = copied
        self.progress_label.setText("完成")
        self._set_buttons_enabled(True)
        self._log(f"导入完成，共复制 {len(copied)} 个文件。")

    def _on_copy_failed(self, err: str) -> None:
        self.progress_label.setText("失败")
        self._set_buttons_enabled(True)
        QtWidgets.QMessageBox.critical(self, "导入失败", err)
        self._log(f"导入失败：{err}")

    def _set_buttons_enabled(self, enabled: bool) -> None:
        self.btn_scan.setEnabled(enabled)
        self.btn_import.setEnabled(enabled)
        self.btn_open_target.setEnabled(enabled)
        self.btn_delete_source.setEnabled(enabled)

    def _open_target_folder(self) -> None:
        target = self.target_path_edit.text().strip()
        if not target:
            return
        if os.name == "nt":
            os.startfile(target)
        else:
            QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(target))

    def _delete_copied_sources(self) -> None:
        if not self.copied_files:
            QtWidgets.QMessageBox.information(self, "提示", "当前没有记录可删除的已复制文件。")
            return
        confirm = QtWidgets.QMessageBox.question(
            self,
            "删除确认",
            f"确认删除存储卡中已复制的 {len(self.copied_files)} 个文件吗？此操作不可撤销。",
        )
        if confirm != QtWidgets.QMessageBox.Yes:
            return

        success = 0
        skipped = 0
        fail = 0
        for path in self.copied_files:
            try:
                if path.exists():
                    path.unlink()
                    success += 1
                else:
                    skipped += 1
            except Exception:
                fail += 1
        self._log(f"删除完成：成功 {success}，跳过 {skipped}，失败 {fail}。")
        QtWidgets.QMessageBox.information(self, "结果", f"删除完成：成功 {success}，跳过 {skipped}，失败 {fail}。")


def main() -> None:
    app = QtWidgets.QApplication(sys.argv)
    window = ImporterWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
