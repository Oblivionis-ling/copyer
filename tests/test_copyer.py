from __future__ import annotations

import itertools
import os
import shutil
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from threading import Event
from unittest.mock import patch

from PIL import Image

import copyer_core as core


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / 'source'
        self.target = self.root / 'target'
        self.source.mkdir()

    def media(self, name='photo.cr3', content=b'camera data', day='2026-10-27'):
        path = self.source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        stamp = datetime.fromisoformat(day).timestamp()
        os.utime(path, (stamp, stamp))
        return path

    def job(self, **options):
        scanned = core.scan(str(self.source), core.RAW_EXTENSIONS | core.JPEG_EXTENSIONS | core.VIDEO_EXTENSIONS)
        return core.build_job(scanned, str(self.target), {f.path for f in scanned.files}, {}, **options)

    def test_folder_names_reject_traversal_and_invalid_dates(self):
        self.assertEqual(core.build_destination_folder_name('2026-10-27', ' 海边 '), '2026-10-27-海边')
        self.assertEqual(core.build_destination_folder_name('2026-10-27', ''), '2026-10-27')
        for suffix in ('../escape', r'..\escape', 'bad:name', 'x.', 'x\x00'):
            with self.subTest(suffix=suffix), self.assertRaises(ValueError):
                core.build_destination_folder_name('2026-10-27', suffix)
        with self.assertRaises(ValueError):
            core.build_destination_folder_name('2026-02-31', '')
        for name in ('CON', 'NUL.txt', 'LPT1', '..'):
            with self.assertRaises(ValueError):
                core.validate_component(name)

    def test_empty_paths_never_resolve_to_working_directory(self):
        with self.assertRaises(ValueError):
            core.scan('', core.RAW_EXTENSIONS)
        self.media()
        job = self.job()
        scanned = core.scan(str(self.source), core.RAW_EXTENSIONS)
        with self.assertRaises(ValueError):
            core.build_job(scanned, '  ', {f.path for f in scanned.files}, {})
        self.assertNotEqual(job.target, Path.cwd())

    def test_source_and_descendant_targets_rejected(self):
        self.media()
        scanned = core.scan(str(self.source), core.RAW_EXTENSIONS)
        for target in (self.source, self.source / 'nested'):
            with self.assertRaises(ValueError):
                core.build_job(scanned, str(target), {f.path for f in scanned.files}, {})

    def test_recursive_scan_filters_and_orders_newest_first(self):
        a = self.media('first.CR3', day='2026-10-26')
        b = self.media('DCIM/second.MP4')
        self.media('ignored.txt')
        result = core.scan(str(self.source), core.RAW_EXTENSIONS | core.VIDEO_EXTENSIONS)
        self.assertEqual(list(result.groups), ['2026-10-27', '2026-10-26'])
        self.assertEqual({f.path for f in result.files}, {a, b})
        self.assertEqual(result.issues, [])

    def test_real_nested_exif_and_invalid_primary_fallback(self):
        path = self.source / 'photo.jpg'
        exif = Image.Exif()
        exif[34665] = {36867: 'invalid', 36868: '2024:05:06 07:08:09'}
        exif[306] = '2023:01:01 00:00:00'
        Image.new('RGB', (4, 4), 'white').save(path, exif=exif)
        self.assertEqual(core.get_file_date(path).isoformat(), '2024-05-06')
        self.assertEqual(core.MediaFile.inspect(path).date_source, 'EXIF 数字化时间')

    def test_corrupt_jpeg_falls_back_to_mtime(self):
        path = self.media('broken.jpg', b'not a jpeg')
        self.assertEqual(core.get_file_date(path).isoformat(), '2026-10-27')

    def test_scan_error_is_reported_and_other_files_survive(self):
        bad, good = self.media('bad.cr3'), self.media('good.cr3')
        original = core.MediaFile.inspect
        def inspect(path, reader=None):
            if path == bad:
                raise PermissionError('denied')
            return original(path, reader)
        with patch.object(core.MediaFile, 'inspect', side_effect=inspect):
            result = core.scan(str(self.source), core.RAW_EXTENSIONS)
        self.assertEqual([f.path for f in result.files], [good])
        self.assertEqual(result.issues[0].path, bad)

    def test_cancelled_scan_cannot_build_import_plan(self):
        self.media()
        cancel = Event()
        cancel.set()
        result = core.scan(str(self.source), core.RAW_EXTENSIONS, cancel)
        self.assertTrue(result.cancelled)
        with self.assertRaises(ValueError):
            core.build_job(result, str(self.target), set(), {})

    def test_copy_checks_content_and_preserves_mtime(self):
        source = self.media(content=b'original photo' * 150000)
        events = []
        result = core.run_import(self.job(), progress=events.append)
        entry = result.files[0]
        self.assertEqual(entry.status, 'copied')
        self.assertEqual(entry.destination.read_bytes(), source.read_bytes())
        self.assertEqual(entry.destination.stat().st_mtime_ns, source.stat().st_mtime_ns)
        self.assertEqual(events[-1].done, len(source.read_bytes()) * 2)
        self.assertEqual(events[-1].total, events[-1].done)
        self.assertEqual({p.phase for p in events}, {'copy', 'verify', 'verified'})
        self.assertEqual(list(self.target.rglob('*.part')), [])

    def test_same_content_skips_and_different_content_gets_number(self):
        self.media()
        job = self.job()
        first = core.run_import(job).files[0]
        second = core.run_import(job).files[0]
        self.assertEqual(second.status, 'skipped')
        self.assertEqual(first.destination, second.destination)
        first.destination.write_bytes(b'other data')
        third = core.run_import(job).files[0]
        self.assertEqual(third.status, 'copied')
        self.assertEqual(third.destination.name, 'photo_1.cr3')
        self.assertEqual(first.destination.read_bytes(), b'other data')
        self.assertEqual(core.run_import(job).files[0].status, 'skipped')

    def test_duplicate_detection_can_be_disabled(self):
        self.media()
        job = self.job(skip_identical=False)
        core.run_import(job)
        self.assertEqual(core.run_import(job).files[0].destination.name, 'photo_1.cr3')

    def test_scan_snapshot_rejects_changed_source(self):
        source = self.media()
        job = self.job()
        source.write_bytes(b'changed after scan')
        result = core.run_import(job)
        self.assertEqual(result.files[0].status, 'failed')
        self.assertFalse(any(self.target.rglob('*.cr3')))

    def test_source_changed_during_copy_is_not_published(self):
        source = self.media()
        job = self.job()
        def progress(value):
            if value.phase == 'copy':
                source.write_bytes(b'changed during copy')
        result = core.run_import(job, progress=progress)
        self.assertEqual(result.files[0].status, 'failed')
        self.assertFalse(any(self.target.rglob('*.cr3')))
        self.assertFalse(any(self.target.rglob('*.part')))

    def test_destination_readback_corruption_rejected(self):
        self.media()
        job = self.job()
        def corrupt(value):
            if value.phase == 'verify':
                next(self.target.rglob('*.part')).write_bytes(b'corrupt')
        result = core.run_import(job, progress=corrupt)
        self.assertEqual(result.files[0].status, 'failed')
        self.assertIn('校验失败', result.files[0].error)
        self.assertFalse(any(self.target.rglob('*.cr3')))
        self.assertFalse(any(self.target.rglob('*.part')))

    def test_one_failed_file_does_not_abort_later_files(self):
        self.media('a.cr3')
        self.media('b.cr3')
        job = self.job()
        publish = core._publish_without_overwrite
        def fail_first(temporary, destination):
            if destination.name == 'a.cr3':
                raise PermissionError('simulated permission error')
            publish(temporary, destination)
        with patch.object(core, '_publish_without_overwrite', side_effect=fail_first):
            result = core.run_import(job)
        self.assertEqual([f.status for f in result.files], ['failed', 'copied'])
        self.assertFalse(any(self.target.rglob('*.part')))
        retry = core.ImportJob(job.source, job.source_identity, job.target,
                               tuple(f.item for f in result.files if f.status == 'failed'))
        self.assertEqual(core.run_import(retry).files[0].status, 'copied')
        self.assertEqual(len(list(self.target.rglob('*.cr3'))), 2)

    def test_chunk_cancellation_keeps_successes_and_removes_partial(self):
        self.media('a.cr3', b'first')
        self.media('b.cr3', b'x' * (core.CHUNK_SIZE * 3))
        self.media('c.cr3', b'third')
        cancel = Event()
        def progress(value):
            if Path(value.path).name == 'b.cr3' and value.phase == 'copy' and value.done > 10:
                cancel.set()
        clock = itertools.count(1, .1)
        with patch.object(core.time, 'monotonic', side_effect=lambda: next(clock)):
            result = core.run_import(self.job(), cancel, progress)
        self.assertTrue(result.cancelled)
        self.assertEqual([f.status for f in result.files], ['copied', 'pending', 'pending'])
        self.assertEqual([p.name for p in self.target.rglob('*.cr3')], ['a.cr3'])
        self.assertFalse(any(self.target.rglob('*.part')))
        self.assertTrue(all(f.item.media.path.exists() for f in result.files))

    def test_cancel_during_verification_never_publishes(self):
        self.media()
        cancel = Event()
        def progress(value):
            if value.phase == 'verify':
                cancel.set()
        result = core.run_import(self.job(), cancel, progress)
        self.assertTrue(result.cancelled)
        self.assertEqual(result.files[0].status, 'pending')
        self.assertFalse(any(self.target.rglob('*.cr3')))
        self.assertFalse(any(self.target.rglob('*.part')))

    def test_publish_race_never_overwrites_existing_file(self):
        self.media()
        publish = core._publish_without_overwrite
        raced = False
        def race(temporary, destination):
            nonlocal raced
            if not raced:
                raced = True
                destination.write_bytes(b'created concurrently')
            publish(temporary, destination)
        with patch.object(core, '_publish_without_overwrite', side_effect=race):
            result = core.run_import(self.job())
        self.assertEqual(result.files[0].destination.name, 'photo_1.cr3')
        self.assertEqual((result.files[0].destination.parent / 'photo.cr3').read_bytes(), b'created concurrently')

    def test_low_space_is_reported_before_copy(self):
        self.media()
        with patch.object(core.shutil, 'disk_usage', return_value=shutil._ntuple_diskusage(100, 100, 0)):
            result = core.run_import(self.job())
        self.assertIn('空间不足', result.files[0].error)
        self.assertFalse(any(self.target.rglob('*.cr3')))

    def test_existing_identical_file_does_not_require_copy_capacity(self):
        self.media()
        job = self.job()
        core.run_import(job)
        with patch.object(core.shutil, 'disk_usage', return_value=shutil._ntuple_diskusage(100, 100, 0)):
            self.assertEqual(core.run_import(job).files[0].status, 'skipped')

    def make_link(self, path, target, is_directory=False):
        try:
            path.symlink_to(target, target_is_directory=is_directory)
        except OSError as exc:
            self.skipTest(f'Windows symlink permission unavailable: {exc}')

    def test_broken_symlink_counts_as_occupied_filename(self):
        self.media()
        job = self.job()
        directory = self.target / job.items[0].folder
        directory.mkdir(parents=True)
        self.make_link(directory / 'photo.cr3', self.root / 'missing')
        self.assertEqual(core.ensure_unique_path(directory, 'photo.cr3').name, 'photo_1.cr3')
        result = core.run_import(job)
        self.assertEqual(result.files[0].destination.name, 'photo_1.cr3')

    def test_destination_link_cannot_escape_selected_target(self):
        self.media()
        job = self.job()
        self.target.mkdir()
        outside = self.root / 'outside'
        outside.mkdir()
        self.make_link(self.target / job.items[0].folder, outside, True)
        result = core.run_import(job)
        self.assertEqual(result.files[0].status, 'failed')
        self.assertEqual(list(outside.iterdir()), [])

    def test_scan_does_not_follow_links(self):
        real = self.media('real.cr3')
        self.make_link(self.source / 'link.cr3', real)
        result = core.scan(str(self.source), core.RAW_EXTENSIONS)
        self.assertEqual(len(result.files), 1)
        self.assertEqual(len(result.issues), 1)

    def test_zero_byte_file_completes(self):
        self.media(content=b'')
        events = []
        result = core.run_import(self.job(), progress=events.append)
        self.assertEqual(result.files[0].status, 'copied')
        self.assertEqual(events[-1].done, events[-1].total)


if __name__ == '__main__':
    unittest.main()
