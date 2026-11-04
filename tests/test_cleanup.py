from __future__ import annotations

import os
import tempfile
import subprocess
import unittest
from dataclasses import replace
from pathlib import Path
from threading import Event
from unittest.mock import patch

import copyer_core as core


class CleanupTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.source, self.target = self.root / 'source', self.root / 'target'
        self.source.mkdir()
        self.path = self.source / 'photo.cr3'
        self.path.write_bytes(b'camera contents')
        info = self.path.stat()
        media = core.MediaFile(self.path, '2026-11-04', info.st_size, info.st_mtime_ns,
                               info.st_dev, info.st_ino)
        self.job = core.ImportJob(self.source, core.identity(self.source), self.target,
                                  (core.PlannedFile(media, media.date_text),))
        self.receipt = core.run_import(self.job).files[0]
        self.assertEqual(self.receipt.status, 'copied')

    def clean(self, receipt=None, **kwargs):
        return core.run_cleanup(self.job, [receipt or self.receipt], **kwargs)

    def test_removes_only_verified_file_and_keeps_directory_and_other_files(self):
        other = self.source / 'unselected.cr3'
        other.write_bytes(b'keep me')
        result = self.clean()
        self.assertEqual(result.deleted, [self.path])
        self.assertEqual(result.issues, [])
        self.assertFalse(self.path.exists())
        self.assertTrue(self.source.is_dir())
        self.assertEqual(other.read_bytes(), b'keep me')
        self.assertEqual(self.receipt.destination.read_bytes(), b'camera contents')

    def test_identical_skipped_file_has_receipt_and_can_be_removed(self):
        receipt = core.run_import(self.job).files[0]
        self.assertEqual(receipt.status, 'skipped')
        self.assertEqual(self.clean(receipt).deleted, [self.path])

    def test_failed_pending_or_missing_hash_never_allow_deletion(self):
        for receipt in (replace(self.receipt, status='failed'), replace(self.receipt, status='pending'),
                        replace(self.receipt, verified_sha256='')):
            self.assertEqual(self.clean(receipt).deleted, [])
            self.assertTrue(self.path.exists())

    def test_source_changed_with_same_size_and_restored_mtime_is_preserved(self):
        original = self.path.stat()
        self.path.write_bytes(b'changed content')
        os.utime(self.path, ns=(original.st_atime_ns, original.st_mtime_ns))
        result = self.clean()
        self.assertTrue(self.path.exists())
        self.assertIn('校验记录', result.issues[0].message)

    def test_corrupt_or_missing_destination_preserves_source(self):
        self.receipt.destination.write_bytes(b'changed content')
        self.assertTrue(self.clean().issues)
        self.assertTrue(self.path.exists())
        self.receipt.destination.unlink()
        self.assertTrue(self.clean().issues)
        self.assertTrue(self.path.exists())

    def test_different_source_device_or_unrelated_receipt_is_rejected(self):
        bad_job = replace(self.job, source_identity=(-1, -1))
        self.assertTrue(core.run_cleanup(bad_job, [self.receipt]).issues)
        bad_job = replace(self.job, items=())
        self.assertTrue(core.run_cleanup(bad_job, [self.receipt]).issues)
        self.assertTrue(self.path.exists())

    def test_target_outside_job_and_same_inode_are_rejected(self):
        outside = self.root / 'outside.cr3'
        outside.write_bytes(self.path.read_bytes())
        self.assertTrue(self.clean(replace(self.receipt, destination=outside)).issues)
        self.receipt.destination.unlink()
        os.link(self.path, self.receipt.destination)
        self.assertTrue(self.clean().issues)
        self.assertTrue(self.path.exists())

    def test_cancel_before_or_during_hash_never_deletes_current_file(self):
        cancel = Event()
        cancel.set()
        self.assertTrue(self.clean(cancel=cancel).cancelled)
        cancel.clear()
        self.assertTrue(self.clean(cancel=cancel, progress=lambda _: cancel.set()).cancelled)
        self.assertTrue(self.path.exists())

    def test_permission_failure_is_reported_without_deletion(self):
        with patch.object(core, '_delete_open_source', side_effect=PermissionError('read only')):
            result = self.clean()
        self.assertIn('read only', result.issues[0].message)
        self.assertTrue(self.path.exists())

    @unittest.skipUnless(os.name == 'nt', 'Windows file sharing')
    def test_windows_locks_prevent_target_changes_during_final_verification(self):
        attempts = []
        def race(_):
            for path in (self.path, self.receipt.destination):
                try:
                    with path.open('r+b') as stream:
                        stream.write(b'x')
                except PermissionError:
                    attempts.append(path)
                else:
                    self.fail('Protected file was writable during deletion')
        result = self.clean(progress=race)
        self.assertEqual(result.deleted, [self.path])
        self.assertTrue(attempts)

    @unittest.skipUnless(os.name == 'nt', 'Windows directory junctions')
    def test_target_directory_replaced_by_junction_preserves_source(self):
        directory = self.receipt.destination.parent
        moved = self.target / 'moved'
        directory.rename(moved)
        quote = lambda path: "'" + str(path).replace("'", "''") + "'"
        shell = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
        subprocess.run([str(shell), '-NoProfile', '-NonInteractive', '-Command',
                        f'New-Item -ItemType Junction -Path {quote(directory)} -Target {quote(moved)} | Out-Null'],
                       check=True, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
        result = self.clean()
        self.assertTrue(self.path.exists())
        self.assertEqual(result.deleted, [])
        self.assertIn('重解析点', result.issues[0].message)


if __name__ == '__main__':
    unittest.main()
