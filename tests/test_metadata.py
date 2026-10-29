from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from threading import Event, Timer
import time
import unittest
from unittest.mock import patch

from PIL import Image

import copyer_core as core
import copyer_metadata as metadata

FIXTURES = Path(__file__).parent / 'fixtures/exiftool'


class DatePolicyTests(unittest.TestCase):
    def test_apple_explicit_timezone_preserves_shooting_day(self):
        result = metadata.choose_capture_date({
            'Keys:CreationDate': '2026:10:28 00:15:00+14:00',
            'QuickTime:CreateDate': '2026:10:27 10:15:00',
            'System:FileModifyDate': '2030:01:01 00:00:00+08:00',
        }, video=True)
        self.assertEqual(result.value.date().isoformat(), '2026-10-28')
        self.assertEqual(result.value.utcoffset(), timedelta(hours=14))
        self.assertEqual(result.source, '视频拍摄时间')

    def test_raw_original_date_beats_container_and_edit_dates(self):
        result = metadata.choose_capture_date({
            'Composite:SubSecDateTimeOriginal': '2024:06:30 23:58:59.123+09:00',
            'ExifIFD:DateTimeOriginal': '2024:06:30 23:58:59',
            'QuickTime:CreateDate': '2030:01:01 00:00:00',
            'IFD0:ModifyDate': '2029:01:01 00:00:00',
        }, video=False)
        self.assertEqual(result.value.isoformat(), '2024-06-30T23:58:59.123000+09:00')
        self.assertEqual(result.source, 'EXIF 拍摄时间')

    def test_quicktime_utc_policy_and_device_local_override(self):
        tags = {'QuickTime:CreateDate': '2025:04:30 23:50:00'}
        converted = metadata.choose_capture_date(tags, video=True)
        self.assertEqual(converted.value, datetime(2025, 4, 30, 23, 50, tzinfo=timezone.utc).astimezone())
        original = metadata.choose_capture_date(tags, video=True, quicktime_utc=False)
        self.assertEqual(original.value, datetime(2025, 4, 30, 23, 50))
        self.assertIn('按设备原值', original.detail)

    def test_dji_xmp_capture_date_beats_video_container(self):
        result = metadata.choose_capture_date({
            'XMP-exif:DateTimeOriginal': '2025:08:09 00:10:00+08:00',
            'XMP-xmp:CreateDate': '2025:08:09 00:10:00+08:00',
            'QuickTime:CreateDate': '2025:08:08 16:10:00',
        }, video=True)
        self.assertEqual(result.value.date().isoformat(), '2025-08-09')

    def test_missing_invalid_and_epoch_fields_do_not_become_capture_dates(self):
        for value in ('0000:00:00 00:00:00', '1904:01:01 00:00:00', '1970:01:01 00:00:00',
                      '2026:02:30 10:00:00', 'not a date', None, 0):
            with self.subTest(value=value):
                result = metadata.choose_capture_date({'QuickTime:CreateDate': value,
                    'System:FileCreateDate': '2026:10:28 10:00:00'}, video=True)
                self.assertIsNone(result.value)
                self.assertIn('无拍摄日期', result.source)

    def test_invalid_primary_falls_back_with_honest_source_label(self):
        result = metadata.choose_capture_date({'ExifIFD:DateTimeOriginal': 'invalid',
            'ExifIFD:CreateDate': '2024:05:06 07:08:09'}, video=False)
        self.assertEqual(result.value.date().isoformat(), '2024-05-06')
        self.assertEqual(result.source, 'EXIF 数字化时间')

    def test_track_date_is_used_only_after_invalid_movie_date(self):
        result = metadata.choose_capture_date({'QuickTime:CreateDate': '0000:00:00 00:00:00',
            'Track1:MediaCreateDate': '2025:05:06 10:20:30',
            'Track1:TrackCreateDate': '2020:01:01 00:00:00'}, video=True, quicktime_utc=False)
        self.assertEqual(result.value.date().isoformat(), '2025-05-06')
        self.assertEqual(result.source, '视频轨道创建时间')


class ReaderProcessTests(unittest.TestCase):
    def test_timeout_kills_process_and_exposes_fallback_reason(self):
        with metadata.MetadataReader(timeout=.2, command=[sys.executable, '-u', '-c',
                'import time; time.sleep(60)']) as reader:
            reader._start()
            process = reader.process
            started = time.monotonic()
            result = reader.read(Path('hung.cr3'))
            self.assertLess(time.monotonic() - started, 2)
            self.assertIsNotNone(process.poll())
            self.assertIn('超时', result.detail)
            self.assertIsNone(result.value)

    def test_cancellation_interrupts_wait_and_reaps_process(self):
        cancel = Event()
        with metadata.MetadataReader(cancel, command=[sys.executable, '-u', '-c',
                'import time; time.sleep(60)']) as reader:
            reader._start()
            process = reader.process
            timer = Timer(.15, cancel.set)
            timer.start()
            try:
                with self.assertRaises(core.Cancelled):
                    reader.read(Path('cancel.cr3'))
                self.assertIsNotNone(process.poll())
            finally:
                timer.cancel()

    def test_crashed_or_malformed_reader_does_not_hang_scan(self):
        programs = ['pass',
            'import sys\nfor line in sys.stdin:\n if line.startswith("-execute"):\n  print("bad JSON\\n{ready"+line.strip()[8:]+"}",flush=True)']
        for program in programs:
            with self.subTest(program=program), metadata.MetadataReader(timeout=1,
                    command=[sys.executable, '-u', '-c', program]) as reader:
                result = reader.read(Path('broken.mov'))
                self.assertIsNone(result.value)
                self.assertIn('读取失败', result.source)


class MetadataIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # This suite must fail (not silently skip) if the portable runtime is absent.
        metadata.runtime_command()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='copyer-metadata-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def fixture(self, name, target=None):
        path = self.root / (target or name)
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(FIXTURES / name, path)
        stamp = datetime(2030, 1, 2, 12).timestamp()
        os.utime(path, (stamp, stamp))
        return path

    def write_test_tags(self, path, *tags):
        env = os.environ.copy()
        env['LC_ALL'] = 'C'
        result = subprocess.run(metadata.runtime_command() + ['-config', '', '-overwrite_original',
            *tags, str(path)], capture_output=True, timeout=10, env=env,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8', errors='replace'))
        stamp = datetime(2030, 1, 2, 12).timestamp()
        os.utime(path, (stamp, stamp))

    def test_real_camera_metadata_across_ten_raw_formats(self):
        expected = {'CanonRaw.cr3':'2018-02-21', 'CanonRaw.cr2':'2005-08-03',
            'CanonRaw.crw':'2003-11-10', 'DNG.dng':'2005-08-03', 'Nikon.nef':'2004-06-09',
            'FujiFilm.raf':'2007-05-22', 'Panasonic.rw2':'2008-08-06',
            'Minolta.mrw':'2004-11-18', 'PhaseOne.iiq':'2013-06-19', 'Sigma.x3f':'2001-01-01'}
        with metadata.MetadataReader() as reader:
            pid = None
            for name, day in expected.items():
                with self.subTest(name=name):
                    path = self.fixture(name)
                    digest = hashlib.sha256(path.read_bytes()).hexdigest()
                    result = reader.read(path)
                    self.assertIsNotNone(result.value, result)
                    self.assertEqual(result.value.date().isoformat(), day)
                    self.assertNotIn('文件修改', result.source)
                    self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest)
                    pid = pid or reader.process.pid
                    self.assertEqual(reader.process.pid, pid)

    def test_cr3_unicode_scan_and_import_use_capture_date_not_mtime(self):
        source = self.root / '存储卡'
        path = self.fixture('CanonRaw.cr3', '存储卡/海边.CR3')
        scanned = core.scan(str(source), core.RAW_EXTENSIONS)
        self.assertEqual(list(scanned.groups), ['2018-02-21'])
        job = core.build_job(scanned, str(self.root / '影像库'), {path}, {'2018-02-21':'旅行'})
        copied = core.run_import(job).files[0]
        self.assertEqual(copied.status, 'copied')
        self.assertEqual(copied.destination.parent.name, '2018-02-21-旅行')
        self.assertEqual(copied.destination.read_bytes(), path.read_bytes())
        self.assertIn('2018-02-21', scanned.files[0].date_detail)

    def test_apple_heic_heif_and_hif_read_embedded_exif(self):
        for ext in ('.heic', '.heif', '.hif'):
            path = self.fixture('QuickTime.heic', '手机'+ext)
            self.write_test_tags(path, '-EXIF:DateTimeOriginal=2026:10:28 00:15:00',
                                 '-EXIF:OffsetTimeOriginal=+08:00')
        scanned = core.scan(str(self.root), core.PHOTO_EXTENSIONS)
        self.assertEqual(len(scanned.files), 3)
        self.assertEqual(list(scanned.groups), ['2026-10-28'])
        self.assertTrue(all('EXIF' in media.date_source for media in scanned.files))

    def test_apple_movie_keys_beat_utc_container_and_modified_date(self):
        path = self.fixture('QuickTime.mov', '手机.MOV')
        self.write_test_tags(path, '-Keys:CreationDate=2026:10:28 00:15:00+08:00',
                             '-QuickTime:CreateDate=2026:10:27 16:15:00')
        media = core.MediaFile.inspect(path)
        self.assertEqual(media.date_text, '2026-10-28')
        self.assertEqual(media.date_source, '视频拍摄时间')

    def test_dji_style_dng_and_video_xmp_creation(self):
        dng = self.fixture('DNG.dng', 'DJI_0001.DNG')
        self.write_test_tags(dng, '-DateTimeOriginal=2025:08:09 00:10:00')
        self.assertEqual(core.get_file_date(dng).isoformat(), '2025-08-09')
        movie = self.fixture('QuickTime.mov', 'DJI_0001.MP4')
        self.write_test_tags(movie, '-XMP-xmp:CreateDate=2025:08:09 00:10:00+08:00',
                             '-QuickTime:CreateDate=2025:08:08 16:10:00')
        media = core.MediaFile.inspect(movie)
        self.assertEqual(media.date_text, '2025-08-09')
        self.assertEqual(media.date_source, 'XMP 创建时间')

    def test_video_extensions_use_real_container_metadata(self):
        for ext in ('.mp4', '.mov', '.m4v'):
            path = self.fixture('QuickTime.mov', 'video'+ext)
            self.write_test_tags(path, '-QuickTime:CreateDate=2025:09:10 23:45:00')
        scanned = core.scan(str(self.root), core.VIDEO_EXTENSIONS, quicktime_utc=False)
        self.assertEqual(len(scanned.files), 3)
        self.assertEqual(list(scanned.groups), ['2025-09-10'])

    def test_expanded_raw_extension_filter_is_case_insensitive(self):
        expected = {'.crw','.cr2','.cr3','.nef','.nrw','.arw','.srf','.sr2','.raf','.orf',
                    '.rw2','.raw','.pef','.srw','.3fr','.fff','.rwl','.x3f','.mrw','.iiq',
                    '.mos','.dcr','.kdc','.k25','.dng'}
        self.assertEqual(core.RAW_EXTENSIONS, expected)
        for suffix in expected:
            (self.root / ('file'+suffix.upper())).write_bytes(b'extension filter fixture')
        (self.root / 'ignore.txt').write_text('not media')
        scanned = core.scan(str(self.root), core.RAW_EXTENSIONS)
        self.assertEqual(len(scanned.files), len(expected))
        self.assertTrue(all('文件修改时间' in file.date_source for file in scanned.files))

    def test_missing_runtime_is_visible_and_jpeg_keeps_exif_fallback(self):
        self.fixture('CanonRaw.cr3')
        exif = Image.Exif(); exif[36867] = '2024:01:02 03:04:05'
        Image.new('RGB',(4,4),'white').save(self.root/'photo.jpg', exif=exif)
        with patch.object(metadata, 'runtime_command', side_effect=metadata.MetadataError('读取器缺失')):
            scanned = core.scan(str(self.root), core.RAW_EXTENSIONS | core.PHOTO_EXTENSIONS)
        self.assertEqual(len(scanned.issues), 1)
        self.assertIn('读取器缺失', scanned.issues[0].message)
        by_name = {file.path.name:file for file in scanned.files}
        self.assertEqual(by_name['photo.jpg'].date_text, '2024-01-02')
        self.assertIn('读取失败', by_name['CanonRaw.cr3'].date_source)

    def test_absent_and_corrupt_metadata_fall_back_explicitly(self):
        path = self.fixture('QuickTime.heic')
        media = core.MediaFile.inspect(path)
        self.assertEqual(media.date_text, '2030-01-02')
        self.assertIn('无拍摄日期', media.date_source)
        path.write_bytes(b'corrupt media')
        self.assertIn('读取失败', core.MediaFile.inspect(path).date_source)


if __name__ == '__main__':
    unittest.main()
