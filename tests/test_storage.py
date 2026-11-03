"""Windows filesystem regression cases derived from the actual migration failures."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from codex_relocate import windows as win
from codex_relocate.engine import MigrationError, content, exists, identity, is_link, snapshot
from codex_relocate.storage import StorageEngine


@unittest.skipUnless(os.name == 'nt', 'Windows NTFS integration tests')
class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='storage-archive-test-')
        self.root = Path(self.temp.name).resolve()
        self.source = self.root / 'source'
        self.source.mkdir()
        self.dest = self.root / 'destination'
        self.archive = self.root / 'independent'
        self.engine = StorageEngine(self.root / 'jobs')
        (self.source / 'data.txt').write_text('old', encoding='utf-8')

    def tearDown(self):
        self.temp.cleanup()

    def move(self):
        return self.engine.migrate(self.source, self.dest, self.archive)

    def test_new_live_data_survives_accepted_cleanup(self):
        job = self.move()
        (self.dest / 'data.txt').write_text('new')
        (self.dest / 'new-chat.txt').write_text('new conversation')
        self.engine.accept(job['id'])
        with patch('codex_relocate.engine.win.app_processes',
                   side_effect=AssertionError('Do not stop or inspect active app for frozen cleanup')):
            result = self.engine.release(job['id'])
        self.assertEqual(result['phase'], 'released')
        self.assertEqual((self.source / 'data.txt').read_text(), 'new')
        self.assertEqual((self.dest / 'new-chat.txt').read_text(), 'new conversation')
        self.assertEqual((self.archive / 'data.txt').read_text(), 'old')
        self.assertFalse(exists(job['backup']))
        self.assertEqual(self.engine.release(job['id'])['phase'], 'released')

    def test_release_requires_explicit_user_acceptance(self):
        job = self.move()
        with self.assertRaisesRegex(MigrationError, 'accept'):
            self.engine.release(job['id'])
        self.assertTrue(Path(job['backup']).exists())

    def test_changed_archive_refuses_cleanup(self):
        job = self.move()
        self.engine.accept(job['id'])
        (self.archive / 'data.txt').write_text('corrupt')
        with self.assertRaisesRegex(MigrationError, 'backup changed'):
            self.engine.release(job['id'])
        self.assertTrue(Path(job['backup']).exists())

    def test_changed_frozen_original_refuses_cleanup(self):
        job = self.move()
        self.engine.accept(job['id'])
        (Path(job['backup']) / 'unexpected.txt').write_text('must keep')
        with self.assertRaisesRegex(MigrationError, 'new/changed'):
            self.engine.release(job['id'])
        self.assertTrue((Path(job['backup']) / 'unexpected.txt').exists())

    def test_ordinary_mode_keeps_upstream_changed_data_guard(self):
        job = self.engine.migrate(self.source, self.dest)
        (self.dest / 'data.txt').write_text('new')
        for action in (self.engine.release, self.engine.rollback):
            with self.assertRaises(MigrationError):
                action(job['id'])
        self.assertTrue(Path(job['backup']).exists())

    def test_verified_backup_replaced_by_root_junction_refused(self):
        job = self.move()
        self.engine.accept(job['id'])
        saved = self.root / 'saved'
        os.rename(self.archive, saved)
        win.make_junction(self.archive, saved)
        with self.assertRaises(MigrationError):
            self.engine.release(job['id'])
        self.assertTrue(Path(job['backup']).exists())

    def test_hardlinked_fake_backup_refused(self):
        job = self.move()
        target = self.archive / 'data.txt'
        target.unlink()
        os.link(self.dest / 'data.txt', target)
        with self.assertRaisesRegex(MigrationError, 'hard-linked'):
            self.engine.accept(job['id'])

    def test_interrupted_archive_copy_resumes(self):
        original_copy = win.copy_file
        calls = [0]
        def fail_backup(source, destination, **kwargs):
            calls[0] += 1
            if '.storage-archive-part-' in str(destination):
                Path(destination).write_bytes(b'partial')
                raise OSError('injected copy interruption')
            return original_copy(source, destination, **kwargs)
        with patch('codex_relocate.windows.copy_file', side_effect=fail_backup):
            with self.assertRaisesRegex(MigrationError, 'incomplete'):
                self.move()
        job = self.engine.jobs()[0]
        self.assertEqual(job['phase'], 'migrated')
        self.assertEqual(job['archive']['state'], 'copying')
        self.assertTrue(is_link(self.source))
        resumed = self.engine.resume(job['id'])
        self.assertEqual(resumed['archive']['state'], 'verified')
        self.assertEqual((self.archive / 'data.txt').read_text(), 'old')

    def test_interrupted_cleanup_resumes_without_reverting_new_data(self):
        (self.source / 'second.txt').write_text('second')
        job = self.move()
        self.engine.accept(job['id'])
        (self.dest / 'data.txt').write_text('new')
        unlink = os.unlink
        calls = [0]
        def interrupted(path, *args, **kwargs):
            if '.relocate-' in str(path):
                calls[0] += 1
                if calls[0] == 2:
                    raise OSError('injected cleanup interruption')
            return unlink(path, *args, **kwargs)
        with patch('codex_relocate.storage.os.unlink', side_effect=interrupted):
            with self.assertRaises(OSError):
                self.engine.release(job['id'])
        self.assertEqual(self.engine.load(job['id'])['phase'], 'releasing_archive')
        self.assertEqual(self.engine.resume(job['id'])['phase'], 'released')
        self.assertEqual((self.source / 'data.txt').read_text(), 'new')
        self.assertTrue((self.archive / 'second.txt').exists())

    def test_backup_lost_mid_cleanup_is_not_ignored(self):
        job = self.move()
        self.engine.accept(job['id'])
        self.engine.save(job, 'releasing_archive')
        (self.archive / 'data.txt').unlink()
        with self.assertRaises(MigrationError):
            self.engine.resume(job['id'])
        self.assertTrue(Path(job['backup']).exists())

    def test_named_streams_and_external_link_survive_cleanup(self):
        external = self.root / 'external'
        external.mkdir()
        (external / 'keep.txt').write_text('keep')
        win.make_junction(self.source / 'external', external)
        with open(str(self.source / 'data.txt') + ':metadata', 'wb') as stream:
            stream.write(b'NTFS named stream')
        job = self.move()
        expected = content(snapshot(self.archive))
        self.engine.accept(job['id'])
        (self.dest / 'new.txt').write_text('live')
        self.engine.release(job['id'])
        self.assertEqual(content(snapshot(self.archive)), expected)
        self.assertEqual((external / 'keep.txt').read_text(), 'keep')

    def test_existing_backup_and_overlapping_backup_refused_before_switch(self):
        self.archive.mkdir()
        with self.assertRaises(MigrationError):
            self.move()
        self.assertFalse(self.dest.exists())
        with self.assertRaises(MigrationError):
            self.engine.migrate(self.source, self.dest, self.source / 'inside')
        self.assertFalse(is_link(self.source))

    def test_combined_budget_checks_two_copies_before_switch(self):
        import shutil
        usage = shutil.disk_usage(self.root)
        fake = type(usage)(usage.total, usage.used, 80 * 1024 * 1024)
        with patch('codex_relocate.copying.shutil.disk_usage', return_value=fake):
            with self.assertRaisesRegex(MigrationError, 'destination AND'):
                self.move()
        self.assertFalse(self.dest.exists())

    def test_verify_reports_only_identity_for_live_target(self):
        job = self.move()
        (self.dest / 'data.txt').write_text('new')
        result = self.engine.verify(job['id'])
        self.assertIn('identity', result['checks']['active_path'])
        self.assertEqual(result['checks']['independent_backup'], 'verified')
        self.assertEqual(result['checks']['acceptance']['type'], 'pending')

    def test_new_writes_still_prevent_rollback_with_archive(self):
        job = self.move()
        (self.dest / 'data.txt').write_text('new')
        with self.assertRaises(MigrationError):
            self.engine.rollback(job['id'])
        self.assertTrue(is_link(self.source))

    def test_archive_can_be_created_after_app_has_written(self):
        job = self.engine.migrate(self.source, self.dest)
        (self.dest / 'data.txt').write_text('new')
        sealed = self.engine.seal(job['id'], self.archive)
        self.assertEqual(sealed['archive']['state'], 'verified')
        self.assertEqual((self.archive / 'data.txt').read_text(), 'old')

    def test_changed_archive_stream_refuses_release(self):
        job = self.move()
        self.engine.accept(job['id'])
        with open(str(self.archive / 'data.txt') + ':extra', 'w') as stream:
            stream.write('changed')
        with self.assertRaises(MigrationError):
            self.engine.release(job['id'])

    def test_manifest_traversal_is_rejected(self):
        import json
        job = self.move()
        path = self.engine.state_dir / (job['id'] + '.manifest')
        value = json.loads(path.read_text())
        value['..\\outside.txt'] = value.pop('data.txt')
        path.write_text(json.dumps(value))
        with self.assertRaisesRegex(MigrationError, 'relative path'):
            self.engine.load(job['id'])

    def test_backup_root_acl_interruption_can_resume_known_directory(self):
        original = win.copy_acl
        def fail_once(source, target):
            if Path(target) == self.archive:
                raise OSError("injected before archive root ACL")
            return original(source, target)
        with patch("codex_relocate.windows.copy_acl", side_effect=fail_once):
            with self.assertRaises(MigrationError):
                self.move()
        job = self.engine.jobs()[0]
        self.assertEqual(job["archive"]["state"], "planned")
        self.assertIn("identity", job["archive"])
        self.assertEqual(self.engine.resume(job["id"])["archive"]["state"], "verified")

    def test_direct_move_already_mapped_is_non_mutating(self):
        os.rename(self.source, self.dest)
        win.make_junction(self.source, self.dest)
        result = self.engine.migrate(self.source, self.dest)
        self.assertFalse(result["data_changed"])
        self.assertEqual(self.engine.jobs(), [])

    def test_encrypted_empty_root_refused_before_enumeration(self):
        from types import SimpleNamespace
        fake = SimpleNamespace(st_file_attributes=0x4010)
        with patch("codex_relocate.engine.attrs", return_value=fake), \
             patch("codex_relocate.engine.os.scandir", side_effect=AssertionError("No encrypted enumeration")):
            with self.assertRaisesRegex(MigrationError, "EFS"):
                snapshot(self.source)

    def test_encrypted_empty_child_directory_is_refused(self):
        from types import SimpleNamespace
        import stat
        child = self.source / "encrypted-empty"
        child.mkdir()
        lstat = os.lstat
        def attributes(path, *args, **kwargs):
            if Path(path).name == child.name:
                return SimpleNamespace(st_file_attributes=0x4010, st_mode=stat.S_IFDIR)
            return lstat(path, *args, **kwargs)
        with patch("codex_relocate.engine.os.lstat", side_effect=attributes):
            with self.assertRaisesRegex(MigrationError, "EFS"):
                snapshot(self.source)

    def test_managed_package_parent_cannot_be_an_archive_target(self):
        parent = self.root / "WpSystem"
        parent.mkdir()
        with self.assertRaisesRegex(MigrationError, "Windows-managed"):
            self.engine.migrate(self.source, self.dest, parent / "new-backup")
        self.assertFalse(self.dest.exists())

    def test_archive_parent_physical_alias_is_refused_before_copy(self):
        with patch("codex_relocate.physical.directory", return_value=r"D:\WpSystem\example\LocalCache"):
            with self.assertRaisesRegex(MigrationError, "physical package"):
                self.engine.migrate(self.source, self.dest, self.archive)
        self.assertFalse(self.dest.exists())


if __name__ == '__main__':
    unittest.main()
