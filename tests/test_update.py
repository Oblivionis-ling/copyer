from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import tempfile
from threading import Event
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError
import zipfile

import copyer_update as update
from copyer_metadata import Cancelled


class UpdateTests(unittest.TestCase):
    def release_payload(self, version='1.5.4'):
        name = f'Copyer-v{version}-Windows-x64.zip'
        return {'tag_name': 'v'+version, 'prerelease': False, 'draft': False, 'assets': [{
            'name': name, 'state': 'uploaded', 'size': 100, 'digest': 'sha256:'+'a'*64,
            'browser_download_url': f'https://github.com/{update.REPOSITORY}/releases/download/v{version}/{name}',
        }]}

    def check(self, payload, current='1.5.3'):
        with patch.object(update, '_request', return_value=io.BytesIO(json.dumps(payload).encode())):
            return update.check_update(current)

    def package(self):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as archive:
            for name in ('Copyer.exe', '_internal/python311.dll', '_internal/PySide6/Qt6Core.dll',
                         '_internal/PySide6/Qt6Gui.dll', '_internal/PySide6/Qt6Widgets.dll',
                         '_internal/PySide6/plugins/platforms/qwindows.dll',
                         '_internal/exiftool/exiftool_files/perl.exe'):
                archive.writestr('copyer-1.5.4/'+name, b'MZfixture')
        return stream.getvalue()

    def test_numeric_versions_handle_patch_minor_and_major(self):
        for version in ('1.5.4', '1.5.10', '1.10.0', '2.0.0'):
            self.assertEqual(self.check(self.release_payload(version)).version, version)
        for version in ('1.5.2', '1.5.3', '1.4.99'):
            self.assertIsNone(self.check(self.release_payload(version)))

    def test_invalid_or_preview_release_is_not_reported_as_latest(self):
        for payload in ({}, [], self.release_payload('1.6.0-rc1'),
                        dict(self.release_payload(), prerelease=True)):
            with self.assertRaises(update.UpdateError):
                self.check(payload)

    def test_foreign_asset_url_is_rejected(self):
        payload = self.release_payload()
        payload['assets'][0]['browser_download_url'] = 'https://example.org/update.zip'
        with self.assertRaises(update.UpdateError):
            self.check(payload)

    def test_missing_asset_or_digest_leaves_manual_release_link(self):
        payload = self.release_payload()
        payload['assets'] = []
        self.assertFalse(self.check(payload).asset_url)
        payload = self.release_payload()
        del payload['assets'][0]['digest']
        release = self.check(payload)
        self.assertFalse(release.sha256)
        with self.assertRaises(update.UpdateError):
            update.prepare_update(release, Event())

    def test_network_and_rate_limit_failures_are_visible(self):
        for error in (URLError('offline'), TimeoutError(), HTTPError(update.API_URL, 403, 'rate limit', {}, None)):
            with patch.object(update, '_request', side_effect=error), self.assertRaises(update.UpdateError):
                update.check_update()

    def test_cancelled_check_does_not_access_network(self):
        cancel = Event(); cancel.set()
        with patch.object(update, '_request') as request, self.assertRaises(Cancelled):
            update.check_update(cancel=cancel)
        request.assert_not_called()

    def test_download_hash_and_extract_valid_package(self):
        data = self.package()
        payload = self.release_payload()
        payload['assets'][0].update(size=len(data), digest='sha256:'+hashlib.sha256(data).hexdigest())
        release = self.check(payload)
        with tempfile.TemporaryDirectory() as temporary:
            staging = Path(temporary) / 'staging'
            staging.mkdir()
            events = []
            with patch.object(update.tempfile, 'mkdtemp', return_value=str(staging)), \
                    patch.object(update, '_request', return_value=io.BytesIO(data)):
                prepared = update.prepare_update(release, Event(), events.append)
            self.assertTrue((prepared.package / 'Copyer.exe').is_file())
            self.assertEqual(events[-1], (len(data), len(data)))
            self.assertFalse((staging / 'download.zip').exists())

    def test_corrupt_incomplete_and_cancelled_downloads_remove_staging(self):
        data = self.package()
        release = self.check(self.release_payload())
        for mode in ('bad_hash', 'short', 'cancel'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temporary:
                staging = Path(temporary) / 'staging'; staging.mkdir()
                from dataclasses import replace
                candidate = replace(release, size=len(data))
                cancel = Event()
                payload = data[:-1] if mode == 'short' else data
                def progress(_):
                    if mode == 'cancel':
                        cancel.set()
                with patch.object(update.tempfile, 'mkdtemp', return_value=str(staging)), \
                        patch.object(update, '_request', return_value=io.BytesIO(payload)), \
                        self.assertRaises((update.UpdateError, Cancelled)):
                    update.prepare_update(candidate, cancel, progress)
                self.assertFalse(staging.exists())

    def test_traversal_links_duplicates_and_extra_files_are_rejected(self):
        for name in ('../escape', 'copyer-1.5.4/../../escape', 'copyer-1.5.4/_internal/C:evil',
                     'copyer-1.5.4/other.txt', 'copyer-1.5.4\\_internal\\evil'):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                archive = Path(temporary) / 'test.zip'
                with zipfile.ZipFile(archive, 'w') as package:
                    package.writestr(name, b'x')
                with self.assertRaises(update.UpdateError):
                    update.extract_package(archive, Path(temporary) / 'output', '1.5.4', Event())

    def test_missing_runtime_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / 'test.zip'
            with zipfile.ZipFile(archive, 'w') as package:
                package.writestr('copyer-1.5.4/Copyer.exe', b'MZtest')
            with self.assertRaises(update.UpdateError):
                update.extract_package(archive, Path(temporary) / 'output', '1.5.4', Event())

    def test_zip_links_and_case_collisions_are_rejected(self):
        for mode in ('link', 'collision'):
            with tempfile.TemporaryDirectory() as temporary:
                archive = Path(temporary) / 'test.zip'
                with zipfile.ZipFile(archive, 'w') as package:
                    if mode == 'link':
                        info = zipfile.ZipInfo('copyer-1.5.4/_internal/link')
                        info.create_system = 3
                        info.external_attr = 0o120777 << 16
                        package.writestr(info, '../../outside')
                    else:
                        package.writestr('copyer-1.5.4/_internal/data', b'a')
                        package.writestr('copyer-1.5.4/_internal/DATA', b'b')
                with self.assertRaises(update.UpdateError):
                    update.extract_package(archive, Path(temporary) / 'output', '1.5.4', Event())


if __name__ == '__main__':
    unittest.main()
