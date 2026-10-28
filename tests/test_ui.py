from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path
from threading import Event
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PIL import Image
from PySide6 import QtCore, QtGui, QtTest, QtWidgets

import copyer_core as core
import copyer_ui as ui


class InterfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / 'source'
        self.source.mkdir()
        self.target = self.root / 'target'
        for name in ('a.cr3', 'b.cr3'):
            (self.source / name).write_bytes(name.encode() * 300)
        exif = Image.Exif()
        exif[36867] = '2026:10:27 08:00:00'
        Image.new('RGB', (64, 48), '#aaaaaa').save(self.source / 'c.jpg', exif=exif)
        self.settings = QtCore.QSettings(str(self.root / 'preferences.ini'), QtCore.QSettings.IniFormat)
        self.window = ui.MediaImporterWindow(settings=self.settings)
        self.window.notify = lambda title, message: self.fail(f'{title}: {message}')
        self.window.show()
        self.window.set_source(str(self.source))
        self.window.set_target(str(self.target))
        self.app.processEvents()

    def tearDown(self):
        if self.window.busy:
            self.window._cancel.set()
            self.wait(lambda: not self.window.busy)
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()
        QtCore.QThreadPool.globalInstance().waitForDone(5000)
        self.temp.cleanup()

    def wait(self, condition, timeout=5):
        deadline = time.monotonic() + timeout
        while not condition() and time.monotonic() < deadline:
            self.app.processEvents()
            QtTest.QTest.qWait(5)
        self.app.processEvents()
        self.assertTrue(condition(), 'asynchronous operation timed out')

    def scan(self):
        QtTest.QTest.mouseClick(self.window.scan_button, QtCore.Qt.MouseButton.LeftButton)
        self.wait(lambda: not self.window.busy)
        self.assertEqual(self.window.phase, 'ready')

    def test_version_style_keyboard_and_accessible_names(self):
        self.assertEqual(self.window.windowTitle(), 'Copyer 1.5.0')
        self.assertEqual(self.window.meta_label.text(), 'v1.5.0 · by Oblivionis-ling')
        self.assertEqual(self.app.palette().color(QtGui.QPalette.Window).name(), '#ffffff')
        self.assertEqual(self.window.window_controls[0].accessibleName(), '设置')
        self.scan()
        self.window.select_all.setFocus()
        QtTest.QTest.keyClick(self.window.select_all, QtCore.Qt.Key.Key_Space)
        self.assertEqual(len(self.window.selected), 0)
        self.assertFalse(self.window.import_button.isEnabled())
        QtTest.QTest.keyClick(self.window.select_all, QtCore.Qt.Key.Key_Space)
        self.assertEqual(len(self.window.selected), 3)

    def test_selected_font_has_chinese_glyphs(self):
        value = QtGui.QFont('Microsoft YaHei UI')
        raw = QtGui.QRawFont.fromFont(value)
        self.assertTrue(all(raw.glyphIndexesForString('Copyer 来源 导入 海边 城市 全选')))
        self.assertIn('Microsoft YaHei UI', self.app.font().families())

    def test_group_and_file_selection_propagate_mixed_state(self):
        self.scan()
        day = next(iter(self.window.rows))
        row = self.window.rows[day]
        row.check.click()
        self.assertEqual(row.check.checkState(), QtCore.Qt.CheckState.Unchecked)
        self.assertEqual(self.window.select_all.checkState(), QtCore.Qt.CheckState.PartiallyChecked)
        self.window.select_all.click()
        dialog = ui.FileDetailsDialog(self.window, day)
        dialog.model.setData(dialog.model.index(0, 0), QtCore.Qt.CheckState.Unchecked, QtCore.Qt.ItemDataRole.CheckStateRole)
        self.assertEqual(len(self.window.selected), 2)
        self.assertIn('2', self.window.import_button.text())
        dialog.show()
        self.app.processEvents()
        rect = dialog.table.visualRect(dialog.model.index(0, 0))
        QtTest.QTest.mouseClick(dialog.table.viewport(), QtCore.Qt.MouseButton.LeftButton, pos=rect.center())
        self.assertEqual(len(self.window.selected), 3)
        dialog.close()

    def test_suffix_validation_and_real_import(self):
        self.scan()
        day = next(iter(self.window.rows))
        row = self.window.rows[day]
        row.suffix.setText('../bad')
        self.assertFalse(self.window.import_button.isEnabled())
        row.suffix.setText('海边')
        self.assertTrue(self.window.import_button.isEnabled())
        self.window.import_button.click()
        self.assertFalse(self.window.source_card.isEnabled())
        self.assertFalse(row.suffix.isEnabled())
        self.wait(lambda: not self.window.busy)
        self.assertEqual(self.window.phase, 'complete')
        self.assertEqual(self.window.progress_bar.value(), 1000)
        self.assertEqual(len(list(self.target.rglob('*.*'))), 3)
        self.assertTrue((self.target / (day+'-海边')).is_dir())
        with patch.object(QtGui.QDesktopServices, 'openUrl', return_value=True) as opened:
            self.window.import_button.click()
            self.assertEqual(Path(opened.call_args.args[0].toLocalFile()), self.target)

    def test_changing_source_or_format_invalidates_previous_plan(self):
        self.scan()
        self.window.raw_checkbox.click()
        self.assertIsNone(self.window.scan_result)
        self.assertFalse(self.window.import_button.isEnabled())
        self.assertEqual(len(self.window.rows), 0)
        self.scan()
        self.assertEqual(len(self.window.selected), 1)
        self.window.set_source(str(self.source / 'new'))
        self.assertIsNone(self.window.scan_result)

    def test_no_matching_media_has_clear_empty_state(self):
        empty = self.root / 'empty'
        empty.mkdir()
        self.window.set_source(str(empty))
        self.scan()
        self.assertEqual(self.window.status_label.text(), '未找到符合条件的文件')
        self.assertFalse(self.window.import_button.isEnabled())

    def test_first_launch_empty_message_tracks_the_viewport(self):
        fresh = QtCore.QSettings(str(self.root / 'fresh.ini'), QtCore.QSettings.IniFormat)
        other = ui.MediaImporterWindow(settings=fresh)
        other.show()
        self.app.processEvents()
        self.assertEqual(other.empty_label.geometry(), other.scroll.viewport().rect())
        other.resize(880, 680)
        self.app.processEvents()
        self.assertEqual(other.empty_label.geometry(), other.scroll.viewport().rect())
        other.close()
        other.deleteLater()

    def test_cancel_import_and_resume_only_unfinished(self):
        self.scan()
        real_import = core.run_import
        def cancel_after_first(job, cancel, progress):
            def observe(value):
                progress(value)
                if value.phase == 'verified':
                    cancel.set()
            return real_import(job, cancel, observe)
        with patch.object(core, 'run_import', side_effect=cancel_after_first):
            self.window.import_button.click()
            self.wait(lambda: not self.window.busy)
        self.assertEqual(self.window.phase, 'cancelled')
        copied = [r.destination for r in self.window.results.values() if r.status == 'copied']
        self.assertEqual(len(copied), 1)
        with patch.object(core, 'run_import', wraps=real_import) as retried:
            self.window.import_button.click()
            self.wait(lambda: not self.window.busy)
            self.assertEqual(len(retried.call_args.args[0].items), 2)
        self.assertEqual(self.window.phase, 'complete')
        self.assertEqual(len([p for p in self.target.rglob('*') if p.is_file()]), 3)
        self.assertTrue(all(p.exists() for p in copied))

    def test_partial_failure_can_retry_without_recopying_successes(self):
        self.scan()
        publish = core._publish_without_overwrite
        def fail_a(temp, destination):
            if destination.name == 'a.cr3':
                raise PermissionError('read only test')
            publish(temp, destination)
        with patch.object(core, '_publish_without_overwrite', side_effect=fail_a):
            self.window.import_button.click()
            self.wait(lambda: not self.window.busy)
        self.assertEqual(self.window.phase, 'partial')
        self.assertEqual(sum(r.status == 'failed' for r in self.window.results.values()), 1)
        self.assertTrue(self.window.issues_button.isVisible())
        self.window.import_button.click()
        self.wait(lambda: not self.window.busy)
        self.assertEqual(self.window.phase, 'complete')
        self.assertEqual(len([p for p in self.target.rglob('*') if p.is_file()]), 3)

    def test_close_waits_for_worker_and_cancels_safely(self):
        entered = Event()
        def slow_scan(source, extensions, cancel, progress):
            entered.set()
            cancel.wait(3)
            return core.ScanResult(self.source, core.identity(self.source), cancelled=True)
        with patch.object(core, 'scan', side_effect=slow_scan):
            self.window.start_scan()
            self.wait(entered.is_set)
            with patch.object(ui.MessageDialog, 'exec', return_value=QtWidgets.QDialog.DialogCode.Accepted):
                self.window.close()
            self.assertTrue(self.window.busy)
            self.wait(lambda: not self.window.busy)
        self.assertFalse(self.window.isVisible())

    def test_settings_dialog_cancel_then_save(self):
        def cancel_changes():
            dialog = self.app.activeModalWidget()
            dialog.duplicate.setChecked(False)
            QtTest.QTest.keyClick(dialog, QtCore.Qt.Key.Key_Escape)
        QtCore.QTimer.singleShot(0, cancel_changes)
        self.window.show_settings()
        self.assertTrue(self.window.skip_identical)

        def save_changes():
            dialog = self.app.activeModalWidget()
            dialog.duplicate.setChecked(False)
            QtTest.QTest.mouseClick(dialog.accept_button, QtCore.Qt.MouseButton.LeftButton)
        QtCore.QTimer.singleShot(0, save_changes)
        self.window.show_settings()
        self.assertFalse(self.window.skip_identical)
        self.assertFalse(self.settings.value('copy/skip_identical', True, type=bool))

    def test_custom_dialog_keyboard_defaults_and_title_drag(self):
        dialog = ui.MessageDialog(self.window, '任务正在进行', '停止当前任务后关闭？', question=True)
        dialog.show()
        self.app.processEvents()
        # Enter must keep the task running unless the destructive choice is explicit.
        QtTest.QTest.keyClick(dialog, QtCore.Qt.Key.Key_Return)
        self.assertEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Rejected)
        self.assertFalse(dialog.isVisible())
        dialog.deleteLater()

        notice = ui.MessageDialog(self.window, '无法扫描', '请选择文件夹，路径不能为空。')
        notice.show()
        self.app.processEvents()
        before = notice.pos()
        point = QtCore.QPointF(12, 12)
        start = QtCore.QPointF(notice.header.mapToGlobal(point.toPoint()))
        delta = QtCore.QPointF(24, 18)
        for kind, current, button, buttons in (
            (QtCore.QEvent.Type.MouseButtonPress, start, QtCore.Qt.MouseButton.LeftButton, QtCore.Qt.MouseButton.LeftButton),
            (QtCore.QEvent.Type.MouseMove, start+delta, QtCore.Qt.MouseButton.NoButton, QtCore.Qt.MouseButton.LeftButton),
            (QtCore.QEvent.Type.MouseButtonRelease, start+delta, QtCore.Qt.MouseButton.LeftButton, QtCore.Qt.MouseButton.NoButton),
        ):
            self.app.sendEvent(notice.header, QtGui.QMouseEvent(kind, point, current, button, buttons, QtCore.Qt.KeyboardModifier.NoModifier))
        self.assertEqual(notice.pos(), before+delta.toPoint())
        QtTest.QTest.keyClick(notice, QtCore.Qt.Key.Key_Return)
        self.assertEqual(notice.result(), QtWidgets.QDialog.DialogCode.Accepted)
        self.assertFalse(notice.isVisible())
        notice.deleteLater()

    def test_jpeg_preview_is_loaded_asynchronously(self):
        self.scan()
        day = next(day for day, files in self.window.scan_result.groups.items() if any(f.path.suffix == '.jpg' for f in files))
        dialog = ui.FileDetailsDialog(self.window, day)
        dialog.show()
        index = next(i for i, f in enumerate(dialog.model.files) if f.path.suffix == '.jpg')
        dialog.table.selectRow(index)
        self.wait(lambda: dialog.preview.pixmap() is not None and not dialog.preview.pixmap().isNull())
        dialog.close()

    def test_settings_preserve_old_format_and_path_keys(self):
        self.window.video_checkbox.setChecked(False)
        self.window.skip_identical = False
        self.window.save_settings()
        other = ui.MediaImporterWindow(settings=self.settings)
        self.assertEqual(other.source, str(self.source))
        self.assertEqual(other.target, str(self.target))
        self.assertFalse(other.video_checkbox.isChecked())
        self.assertFalse(other.skip_identical)
        other.close()
        other.deleteLater()

    def test_minimum_window_keeps_footer_and_controls_visible(self):
        self.scan()
        for width, height in ((700, 526), (427, 267), (360, 230), (640, 480), (880, 680), (1536, 1024)):
            with self.subTest(size=(width, height)):
                self.window.resize(width, height)
                self.app.processEvents()
                for widget in (self.window.source_card, self.window.target_card, self.window.scan_button,
                               self.window.progress_bar, self.window.import_button, self.window.scroll,
                               *self.window.format_boxes, *self.window.window_controls):
                    self.assertTrue(self.window.canvas.rect().contains(widget.geometry()), str(widget))
                self.assertLess(self.window.scroll.geometry().bottom(), self.window.status_label.y())
                self.assertLess(self.window.target_card.geometry().bottom(), self.window.raw_checkbox.y())
                self.assertFalse(self.window.scan_button.geometry().intersects(self.window.video_checkbox.geometry()))
                for row in self.window.rows.values():
                    for widget in (row.check, row.date_label, row.suffix, row.count, row.detail):
                        self.assertTrue(row.rect().contains(widget.geometry()))
                    self.assertLess(row.date_label.geometry().right(), row.suffix.x())
                    self.assertLess(row.suffix.geometry().right(), row.count.x())
                    self.assertGreaterEqual(row.date_label.width(), row.date_label.fontMetrics().horizontalAdvance(row.day))

    def test_default_window_matches_approved_size_and_fits_small_screens(self):
        screen = QtGui.QGuiApplication.screenAt(QtGui.QCursor.pos()) or self.window.screen()
        self.assertEqual(self.window.size(), ui.default_window_size(screen))
        for screen_size, expected in (((1280, 752), (700, 526)), ((1920, 1040), (700, 526)),
                                      ((3840, 2112), (700, 526)), ((640, 480), (616, 456))):
            screen = Mock()
            screen.availableGeometry.return_value = QtCore.QRect(0, 0, *screen_size)
            self.assertEqual(ui.default_window_size(screen), QtCore.QSize(*expected))

    def test_resizing_preserves_suffix_selection_and_controls(self):
        self.scan()
        row = next(iter(self.window.rows.values()))
        row.suffix.setText('海边')
        self.window.resize(427, 267)
        self.app.processEvents()
        row.check.click()
        selected = self.window.selected.copy()
        self.assertEqual(self.window.source_card.choose_button.text(), '')
        self.window.resize(1536, 1024)
        self.app.processEvents()
        self.assertEqual(self.window.source_card.choose_button.text(), '选择文件夹')
        self.assertEqual(self.window.selected, selected)
        self.assertEqual(row.suffix.text(), '海边')
        self.assertEqual(row.suffix.styleSheet(), '')
        self.window.resize(427, 267)
        self.app.processEvents()
        self.assertTrue(row.suffix.isEnabled())
        with patch.object(QtWidgets.QFileDialog, 'getExistingDirectory', return_value='') as choose:
            self.window.source_card.choose_button.click()
            choose.assert_called_once()

    def test_glass_frame_is_translucent_and_has_opaque_fallback(self):
        self.window.resize(427, 267)
        self.window.reduce_transparency = False
        self.window.apply_material_preferences()
        self.app.processEvents()
        rendered = self.window.grab().toImage()
        self.assertEqual(rendered.pixelColor(0, 0).alpha(), 0)
        self.assertLess(rendered.pixelColor(200, 5).alpha(), 255)
        self.assertGreater(rendered.pixelColor(200, 5).alpha(), 0)
        self.assertEqual(rendered.pixelColor(200, 205).alpha(), 255)
        self.window.reduce_transparency = True
        self.window.apply_material_preferences()
        self.app.processEvents()
        self.assertEqual(self.window.grab().toImage().pixelColor(200, 5).alpha(), 255)

    def test_translucent_frame_moves_resizes_and_preserves_minimum(self):
        self.window.resize(427, 267)
        self.app.processEvents()
        def drag(start, delta):
            canvas = self.window.canvas
            QtTest.QTest.mousePress(canvas, QtCore.Qt.MouseButton.LeftButton, pos=start)
            destination = start+delta
            event = QtGui.QMouseEvent(QtCore.QEvent.Type.MouseMove, QtCore.QPointF(destination),
                                     QtCore.QPointF(canvas.mapToGlobal(destination)), QtCore.Qt.MouseButton.NoButton,
                                     QtCore.Qt.MouseButton.LeftButton, QtCore.Qt.KeyboardModifier.NoModifier)
            QtWidgets.QApplication.sendEvent(canvas, event)
            QtTest.QTest.mouseRelease(canvas, QtCore.Qt.MouseButton.LeftButton, pos=destination)
            self.app.processEvents()
        position = self.window.pos()
        drag(QtCore.QPoint(260, 20), QtCore.QPoint(30, 15))
        self.assertEqual(self.window.pos(), position+QtCore.QPoint(30, 15))
        drag(QtCore.QPoint(423, 100), QtCore.QPoint(-40, 0))
        self.assertEqual(self.window.width(), 387)
        drag(QtCore.QPoint(383, 100), QtCore.QPoint(-200, 0))
        self.assertEqual(self.window.width(), self.window.minimumWidth())
        self.assertIsNone(self.window._frame_gesture)

    def test_compact_progress_exposes_speed_without_stealing_row_space(self):
        self.window.resize(427, 267)
        self.app.processEvents()
        value = core.Progress('copy', str(self.source / 'a.cr3'), 512, 2048, 1, 3, 2)
        self.window.import_progress(value)
        self.assertEqual(self.window.percent_label.text(), '25%')
        self.assertFalse(self.window.speed_label.isVisible())
        self.assertIn('/s', self.window.progress_bar.toolTip())
        self.assertEqual(self.window.context_label.width(), self.window.progress_bar.width())


if __name__ == '__main__':
    unittest.main()
