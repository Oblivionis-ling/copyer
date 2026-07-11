from __future__ import annotations

import os
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PySide6 import QtCore, QtGui, QtWidgets

import copyer


class FileOrganizationTests(unittest.TestCase):
    def test_build_destination_folder_name(self) -> None:
        self.assertEqual(
            copyer.build_destination_folder_name("2026-07-12", ""), "2026-07-12"
        )
        self.assertEqual(
            copyer.build_destination_folder_name("2026-07-12", "  海边  "),
            "2026-07-12-海边",
        )

    def test_ensure_unique_path_uses_incrementing_suffix(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            destination = Path(temporary_directory)
            (destination / "photo.jpg").touch()
            (destination / "photo_1.jpg").touch()

            unique_path = copyer.ensure_unique_path(destination, "photo.jpg")

            self.assertEqual(unique_path, destination / "photo_2.jpg")

    def test_get_file_date_prefers_jpeg_exif(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            image_path = Path(temporary_directory) / "photo.jpg"
            exif = Image.Exif()
            exif[36867] = "2024:05:06 07:08:09"
            Image.new("RGB", (2, 2), "white").save(image_path, exif=exif)

            self.assertEqual(copyer.get_file_date(image_path).isoformat(), "2024-05-06")

    def test_scan_media_files_filters_and_groups_recursively(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory)
            nested = source / "nested"
            nested.mkdir()
            first_file = source / "first.cr3"
            second_file = nested / "second.MP4"
            ignored_file = source / "notes.txt"
            first_file.write_bytes(b"raw")
            second_file.write_bytes(b"video")
            ignored_file.write_text("ignore", encoding="utf-8")
            os.utime(first_file, (datetime(2024, 1, 2).timestamp(),) * 2)
            os.utime(second_file, (datetime(2024, 1, 3).timestamp(),) * 2)

            groups = copyer.scan_media_files(
                source,
                copyer.RAW_EXTENSIONS | copyer.VIDEO_EXTENSIONS,
            )

            self.assertEqual(list(groups), ["2024-01-02", "2024-01-03"])
            self.assertEqual(groups["2024-01-02"], [first_file])
            self.assertEqual(groups["2024-01-03"], [second_file])


class CopyWorkerTests(unittest.TestCase):
    def test_copy_worker_copies_metadata_and_avoids_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source_file = root / "photo.jpg"
            source_file.write_bytes(b"new photo")
            target = root / "target"
            destination = target / "2026-07-12"
            destination.mkdir(parents=True)
            (destination / "photo.jpg").write_bytes(b"existing photo")
            progress_events: list[tuple[int, int, str]] = []
            copied_results: list[list[Path]] = []
            errors: list[str] = []
            worker = copyer.CopyWorker([("2026-07-12", [source_file])], target)
            worker.progress_updated.connect(
                lambda completed, total, path: progress_events.append(
                    (completed, total, path)
                )
            )
            worker.succeeded.connect(copied_results.append)
            worker.failed.connect(errors.append)

            worker.run()

            self.assertEqual(errors, [])
            self.assertEqual(copied_results, [[source_file]])
            self.assertEqual(progress_events, [(1, 1, str(source_file))])
            self.assertEqual(
                (destination / "photo.jpg").read_bytes(), b"existing photo"
            )
            self.assertEqual((destination / "photo_1.jpg").read_bytes(), b"new photo")


class InterfaceCompatibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._settings_directory = tempfile.TemporaryDirectory()
        QtCore.QSettings.setDefaultFormat(QtCore.QSettings.IniFormat)
        QtCore.QSettings.setPath(
            QtCore.QSettings.IniFormat,
            QtCore.QSettings.UserScope,
            cls._settings_directory.name,
        )
        cls.application = QtWidgets.QApplication.instance() or QtWidgets.QApplication(
            []
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls._settings_directory.cleanup()

    def test_window_matches_release_1_3_3_interface_baseline(self) -> None:
        window = copyer.MediaImporterWindow()
        self.addCleanup(window.close)

        self.assertEqual(window.windowTitle(), "读卡器照片/视频导入工具")
        self.assertEqual((window.width(), window.height()), (1100, 720))
        self.assertEqual(
            [group.title() for group in window.findChildren(QtWidgets.QGroupBox)],
            ["读卡器 / 源路径", "导入到", "选择格式"],
        )
        self.assertEqual(
            [button.text() for button in window.findChildren(QtWidgets.QPushButton)],
            [
                "自动识别",
                "手动选择",
                "选择文件夹",
                "全选格式",
                "扫描文件",
                "开始导入",
                "打开目标文件夹",
                "删除存储卡已复制文件",
            ],
        )
        self.assertEqual(
            [
                (checkbox.text(), checkbox.isChecked())
                for checkbox in window.findChildren(QtWidgets.QCheckBox)
            ],
            [
                ("RAW (.cr2/.cr3/...)", True),
                ("JPEG (.jpg)", True),
                ("视频 (.mp4/.mov)", False),
            ],
        )
        self.assertEqual(
            [
                window.groups_table.horizontalHeaderItem(column).text()
                for column in range(window.groups_table.columnCount())
            ],
            ["日期", "数量", "自定义后缀", "生成的文件夹名"],
        )
        self.assertEqual(window.progress_label.text(), "未开始")
        self.assertEqual(window.log_output.placeholderText(), "执行日志...")
        self.assertEqual(self.application.style().objectName(), "fusion")

        palette = self.application.palette()
        self.assertEqual(palette.color(QtGui.QPalette.Window).name(), "#1e2126")
        self.assertEqual(palette.color(QtGui.QPalette.WindowText).name(), "#f0f0f0")
        self.assertEqual(palette.color(QtGui.QPalette.Base).name(), "#181a1f")
        self.assertEqual(palette.color(QtGui.QPalette.Button).name(), "#34383f")
        self.assertEqual(palette.color(QtGui.QPalette.Highlight).name(), "#4084d6")

    def test_group_suffix_updates_preview_and_import_plan(self) -> None:
        window = copyer.MediaImporterWindow()
        self.addCleanup(window.close)
        sample_file = Path("sample.jpg")
        window.file_groups = {"2026-07-12": [sample_file]}
        window._populate_groups_table()

        window.suffix_inputs[0].setText("海边")

        self.assertEqual(window.groups_table.item(0, 3).text(), "2026-07-12-海边")
        self.assertEqual(
            window._build_import_plan(), [("2026-07-12-海边", [sample_file])]
        )

    def test_start_import_completes_through_worker_thread(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source_file = root / "source.jpg"
            source_file.write_bytes(b"photo")
            target_directory = root / "target"
            window = copyer.MediaImporterWindow()
            self.addCleanup(window.close)
            window.file_groups = {"2026-07-12": [source_file]}
            window._populate_groups_table()
            window.target_path_input.setText(str(target_directory))

            window._start_import()
            deadline = time.monotonic() + 5
            while window._copy_thread is not None and time.monotonic() < deadline:
                self.application.processEvents()
                time.sleep(0.01)

            self.assertIsNone(window._copy_thread)
            self.assertEqual(window.progress_label.text(), "完成")
            self.assertEqual(window.copied_source_files, [source_file])
            self.assertEqual(
                (target_directory / "2026-07-12" / "source.jpg").read_bytes(),
                b"photo",
            )
            self.assertTrue(window.scan_button.isEnabled())
            self.assertTrue(window.import_button.isEnabled())


if __name__ == "__main__":
    unittest.main()
