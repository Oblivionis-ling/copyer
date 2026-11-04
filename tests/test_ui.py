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
        self.assertEqual(self.window.windowTitle(), f'Copyer {ui.APP_VERSION}')
        self.assertEqual(self.window.meta_label.text(), f'v{ui.APP_VERSION} · by Oblivionis-ling')
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

    def test_group_selection_and_select_all_propagate_state(self):
        self.scan()
        day = next(iter(self.window.rows))
        row = self.window.rows[day]
        row.check.click()
        self.assertEqual(row.check.checkState(), QtCore.Qt.CheckState.Unchecked)
        self.assertEqual(self.window.select_all.checkState(), QtCore.Qt.CheckState.PartiallyChecked)
        self.window.select_all.click()
        self.assertEqual(len(self.window.selected), 3)
        self.assertIn('3', self.window.import_button.text())

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

    def test_verified_cleanup_button_confirmation_and_source_invalidation(self):
        self.assertFalse(self.window.cleanup_button.isVisible())
        self.scan()
        self.window.import_button.click()
        self.wait(lambda: not self.window.busy)
        self.assertTrue(self.window.cleanup_button.isVisible())
        self.assertIn('校验通过', self.window.status_label.text())
        for width, height in ((360, 230), (700, 526), (1536, 1024)):
            self.window.resize(width, height)
            self.app.processEvents()
            self.assertTrue(self.window.canvas.rect().contains(self.window.cleanup_button.geometry()))
            self.assertFalse(self.window.cleanup_button.geometry().intersects(self.window.import_button.geometry()))
            self.assertLess(self.window.scroll.geometry().bottom(), self.window.status_label.y())
        with patch.object(ui.ThemedDialog, 'exec', return_value=QtWidgets.QDialog.DialogCode.Rejected):
            self.window.cleanup_button.click()
        self.assertEqual(len(list(self.source.iterdir())), 3)
        with patch.object(ui.ThemedDialog, 'exec', return_value=QtWidgets.QDialog.DialogCode.Accepted):
            self.window.cleanup_button.click()
        self.wait(lambda: not self.window.busy)
        self.assertFalse(self.window.cleanup_button.isVisible())
        self.assertEqual(list(self.source.iterdir()), [])
        self.assertEqual(len(list(self.target.rglob('*.*'))), 3)
        self.assertTrue(all(entry.status == 'deleted' for entry in self.window.results.values()))
        self.window.set_source(str(self.root / 'another'))
        self.assertFalse(self.window.cleanup_button.isVisible())

    def test_cleanup_retains_changed_files_and_reports_reason(self):
        self.scan()
        self.window.import_button.click()
        self.wait(lambda: not self.window.busy)
        (self.source / 'a.cr3').write_bytes(b'changed source')
        with patch.object(ui.ThemedDialog, 'exec', return_value=QtWidgets.QDialog.DialogCode.Accepted):
            self.window.cleanup_button.click()
        self.wait(lambda: not self.window.busy)
        self.assertEqual([path.name for path in self.source.iterdir()], ['a.cr3'])
        self.assertEqual(len(self.window.cleanup_issues), 1)
        self.assertTrue(self.window.issues_button.isVisible())

    def test_update_check_latest_newer_error_and_cancel(self):
        settings = self.window.settings_page
        self.window.show_settings()
        self.assertEqual(settings.update_button.text(), '检查更新')
        for response in (None, ui.updater.Release('1.5.4', ui.updater.RELEASES_URL)):
            with patch.object(ui.updater, 'check_update', return_value=response):
                dialog = ui.UpdateDialog(self.window)
                dialog.show()
                self.wait(lambda: dialog.worker is None)
                self.assertIn('目前已是最新版本' if response is None else '发现新版本', dialog.label.text())
                dialog.reject()
                dialog.deleteLater()
        with patch.object(ui.updater, 'check_update', side_effect=ui.updater.UpdateError('无法连接 GitHub')):
            dialog = ui.UpdateDialog(self.window)
            dialog.show()
            self.wait(lambda: dialog.worker is None)
            self.assertIn('无法连接 GitHub', dialog.label.text())
            dialog.accept()
            dialog.deleteLater()
        entered = Event()
        def wait_for_cancel(**kwargs):
            entered.set()
            kwargs['cancel'].wait(3)
            raise core.Cancelled()
        with patch.object(ui.updater, 'check_update', side_effect=wait_for_cancel):
            dialog = ui.UpdateDialog(self.window)
            dialog.show()
            self.wait(entered.is_set)
            dialog.reject()
            self.assertIsNotNone(dialog.worker)
            self.wait(lambda: dialog.worker is None)
            self.assertFalse(dialog.isVisible())
            dialog.deleteLater()
        self.window.show_home()

    def test_new_update_requires_click_and_download_failure_can_retry(self):
        settings = self.window.settings_page
        self.window.show_settings()
        release = ui.updater.Release('1.5.4', ui.updater.RELEASES_URL, 'https://github.com/package.zip', 10, 'a'*64)
        with patch.object(ui.sys, 'frozen', True, create=True), \
                patch.object(ui.updater, 'check_update', return_value=release), \
                patch.object(ui.updater, 'prepare_update', side_effect=ui.updater.UpdateError('校验失败')) as download:
            dialog = ui.UpdateDialog(self.window)
            dialog.show()
            self.wait(lambda: dialog.worker is None)
            download.assert_not_called()
            self.assertEqual(dialog.accept_button.text(), '更新并重启')
            dialog.accept_button.click()
            self.wait(lambda: dialog.worker is None)
            self.assertIn('校验失败', dialog.label.text())
            self.assertEqual(dialog.accept_button.text(), '重试更新')
            dialog.reject()
            dialog.deleteLater()
        self.window.show_home()

    def test_download_finishes_before_installer_and_restart(self):
        settings = self.window.settings_page
        self.window.show_settings()
        release = ui.updater.Release('1.5.4', ui.updater.RELEASES_URL, 'https://github.com/package.zip', 10, 'a'*64)
        prepared = ui.updater.PreparedUpdate(self.root, self.root / 'package', '1.5.4')
        with patch.object(ui.sys, 'frozen', True, create=True), \
                patch.object(ui.updater, 'check_update', return_value=release), \
                patch.object(ui.updater, 'prepare_update', return_value=prepared), \
                patch.object(ui.updater, 'launch_installer') as install, patch.object(self.app, 'quit') as quit_app:
            dialog = ui.UpdateDialog(self.window)
            dialog.show()
            self.wait(lambda: dialog.worker is None)
            install.assert_not_called()
            dialog.accept_button.click()
            self.wait(lambda: dialog.worker is None)
            install.assert_called_once_with(prepared)
            self.app.processEvents()
            quit_app.assert_called_once()
            self.assertFalse(dialog.isVisible())
            dialog.deleteLater()
        self.window.show_home()

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
        def slow_scan(source, extensions, cancel, progress, **options):
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

    def test_settings_page_saves_immediately_and_returns_without_losing_selection(self):
        self.scan()
        day = next(iter(self.window.rows))
        self.window.rows[day].suffix.setText('海边')
        self.window.rows[day].check.click()
        selection = self.window.selected.copy()
        scanned = self.window.scan_result
        self.window.show_settings()
        page = self.window.settings_page
        self.assertTrue(page.isVisible())
        self.assertFalse(page.isWindow())
        self.assertIsNone(self.app.activeModalWidget())
        self.assertFalse(self.window.home_page.isVisible())
        page.duplicate.click()
        self.assertFalse(self.window.skip_identical)
        self.assertFalse(self.settings.value('copy/skip_identical', True, type=bool))
        page.motion.click()
        self.assertEqual(self.settings.value('display/reduce_motion', type=bool), page.motion.isChecked())
        page.back_button.click()
        self.assertTrue(self.window.home_page.isVisible())
        self.assertEqual(self.window.selected, selection)
        self.assertIs(self.window.scan_result, scanned)
        self.assertEqual(self.window.rows[day].suffix.text(), '海边')
        self.window.show_settings()
        page.video_time.click()
        self.assertFalse(self.settings.value('dates/video_time_utc', True, type=bool))
        self.assertIsNone(self.window.scan_result)
        QtTest.QTest.keyClick(page.back_button, QtCore.Qt.Key.Key_Escape)
        self.app.processEvents()
        self.assertTrue(self.window.home_page.isVisible())
        self.assertEqual(self.window.phase, 'empty')

    def test_photo_selection_includes_heif(self):
        self.assertTrue({'.jpg', '.jpeg', '.heic', '.heif', '.hif'} <= self.window.selected_extensions())
        self.window.jpeg_checkbox.setChecked(False)
        self.assertNotIn('.heic', self.window.selected_extensions())

    def test_large_windows_preserve_compact_control_sizes(self):
        self.scan()
        self.window.resize(700, 526)
        self.app.processEvents()
        row = next(iter(self.window.rows.values()))
        sizes = (self.window.source_card.height(), self.window.import_button.size(), row.height(),
                 self.window.title_label.font().pixelSize(), self.window.raw_checkbox.font().pixelSize())
        list_top = self.window.scroll.y()
        for width, height in ((1100, 658), (1536, 1024), (2200, 1312)):
            self.window.resize(width, height)
            self.app.processEvents()
            self.assertEqual(sizes, (self.window.source_card.height(), self.window.import_button.size(), row.height(),
                                    self.window.title_label.font().pixelSize(), self.window.raw_checkbox.font().pixelSize()))
            self.assertEqual(self.window.source_card.choose_button.text(), '')
            self.assertEqual(self.window.scroll.y(), list_top)
        self.window.show_settings()
        for width, height in ((360, 230), (700, 526), (1536, 1024)):
            self.window.resize(width, height)
            self.app.processEvents()
            page = self.window.settings_page
            self.assertTrue(self.window.canvas.rect().contains(page.geometry()))
            self.assertTrue(page.rect().contains(page.back_button.geometry()))
            page.scroll.verticalScrollBar().setValue(page.scroll.verticalScrollBar().maximum())
            self.assertLessEqual(page.scroll.mapTo(page, QtCore.QPoint()).y()+page.scroll.height(), page.height())
        self.window.show_home()

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
                    for widget in (row.check, row.date_label, row.suffix, row.count):
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
        self.assertEqual(self.window.source_card.choose_button.text(), '')
        self.assertEqual(self.window.selected, selected)
        self.assertEqual(row.suffix.text(), '海边')
        self.assertIn('padding:0px', row.suffix.styleSheet())
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
