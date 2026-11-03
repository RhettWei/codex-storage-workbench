import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from codex_relocate import doctor, physical, packages
from codex_relocate import windows as win


@unittest.skipUnless(os.name == 'nt', 'Windows metadata tests')
class DoctorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='storage-doctor-test-')
        self.root = Path(self.temp.name)
        self.home = self.root / 'profile'
        self.codex = self.home / '.codex'
        self.docs = self.home / 'Documents'
        self.local = self.home / 'AppData' / 'Local'
        for path in (self.codex, self.docs, self.local):
            path.mkdir(parents=True)
        self.env = {'LOCALAPPDATA': str(self.local), 'CODEX_HOME': str(self.codex)}

    def tearDown(self):
        self.temp.cleanup()

    def test_sqlite_config_precedes_environment_without_exposing_secrets(self):
        database = self.root / 'database'
        config = self.codex / 'config.toml'
        config.write_text('sqlite_home = "' + str(database).replace('\\', '/') +
                          '"\napi_key = "PRIVATE_VALUE"\n', encoding='utf-8')
        self.env['CODEX_SQLITE_HOME'] = str(self.root / 'other')
        paths, errors = doctor.locations(self.env, self.home, self.docs)
        self.assertFalse(errors)
        self.assertEqual(dict(paths)['sqlite_home'], database)
        result = doctor.report(False, False, env=self.env, home=self.home, documents=self.docs)
        self.assertNotIn('PRIVATE_VALUE', str(result))

    def test_relative_sqlite_location_uses_working_directory(self):
        (self.codex / 'config.toml').write_text('sqlite_home = "relative-sqlite"\n')
        paths, errors = doctor.locations(self.env, self.home, self.docs)
        self.assertFalse(errors)
        self.assertEqual(dict(paths)['sqlite_home'], Path.cwd() / 'relative-sqlite')

    def test_invalid_config_is_reported_without_configuration_content(self):
        (self.codex / 'config.toml').write_text('api_key = "PRIVATE_VALUE\n')
        result = doctor.report(False, False, env=self.env, home=self.home, documents=self.docs)
        self.assertTrue(result['config_issues'])
        self.assertNotIn('PRIVATE_VALUE', str(result))

    def test_physical_alias_and_duplicate_storage_counted_once(self):
        actual = self.root / 'actual'
        actual.mkdir()
        (actual / 'data.txt').write_bytes(b'12345')
        win.make_junction(self.home / '.cache', actual)
        self.codex.rmdir()
        win.make_junction(self.codex, actual)
        result = doctor.report(True, False, env=self.env, home=self.home, documents=self.docs)
        home = next(x for x in result['locations'] if x['kind'] == 'codex_home')
        sqlite = next(x for x in result['locations'] if x['kind'] == 'sqlite_home')
        self.assertEqual(home['physical_path'], str(actual))
        self.assertEqual(sqlite['same_storage_as'], str(self.codex))
        self.assertEqual(result['metadata_bytes_unique_roots'], 5)

    def test_metadata_walk_does_not_follow_external_links(self):
        external = self.root / 'outside'
        external.mkdir()
        (external / 'keep').write_bytes(b'x' * 100)
        (self.codex / 'inside').write_bytes(b'123')
        win.make_junction(self.codex / 'external', external)
        result = doctor.metadata_walk(self.codex)
        self.assertEqual(result['bytes'], 3)
        self.assertEqual(result['links'], 1)
        self.assertEqual((external / 'keep').read_bytes(), b'x' * 100)

    def test_metadata_limit_is_explicitly_incomplete(self):
        for name in ('a', 'b'):
            (self.codex / name).write_text('x')
        result = doctor.metadata_walk(self.codex, limit=1)
        self.assertFalse(result['complete'])
        self.assertEqual(result['issues'][0]['code'], 'scan_limit_reached')

    def test_access_denied_does_not_trigger_acl_mutation(self):
        failure = PermissionError('denied')
        failure.winerror = 5
        with patch('codex_relocate.doctor.os.scandir', side_effect=failure), \
             patch('codex_relocate.windows.copy_acl', side_effect=AssertionError('No ACL writes')):
            result = doctor.metadata_walk(self.codex)
        self.assertFalse(result['complete'])
        self.assertEqual(result['issues'][0]['code'], 'access_denied')

    def test_physical_security_descriptor_is_read_only(self):
        before = (self.codex.stat().st_ino, self.codex.stat().st_mode)
        result = physical.security(self.codex)
        self.assertTrue(result['read_control'])
        self.assertTrue(result['owner'])
        self.assertEqual(before, (self.codex.stat().st_ino, self.codex.stat().st_mode))

    def test_redaction_removes_profile_root_owner_and_sid(self):
        payload = {'locations': [{'path': str(self.codex), 'physical_path': str(self.codex),
                                  'security': {'owner': 'S-1-5-21-1-2-3-1001'}}],
                   'error': str(self.codex / 'blocked')}
        redacted = str(doctor.redact(payload))
        self.assertNotIn(str(self.codex), redacted)
        self.assertNotIn('S-1-5-21', redacted)
        self.assertIn('<owner>', redacted)

    def test_unreadable_root_is_not_misreported_as_nonexistent(self):
        failure = PermissionError("private root")
        failure.winerror = 5
        with patch("codex_relocate.doctor.os.lstat", side_effect=failure):
            result = doctor.inspect_location("fixture", self.codex)
        self.assertIsNone(result["exists"])
        self.assertEqual(result["issue"]["code"], "access_denied")

    def test_nonlocal_configured_home_fails_before_any_file_open(self):
        self.env["CODEX_HOME"] = r"\\server\share"
        with patch("builtins.open", side_effect=AssertionError("No remote read")):
            with self.assertRaises(ValueError):
                doctor.locations(self.env, self.home, self.docs)


class PackageTests(unittest.TestCase):
    def test_already_moved_package_and_cache_are_reused_without_copy(self):
        raw = {'complete': True, 'packages': [{'name': 'OpenAI.Codex', 'family': 'OpenAI.Codex_family',
                                             'install_path': r'C:\Program Files\WindowsApps\pkg'}]}
        with patch('codex_relocate.physical.directory', side_effect=[
                r'D:\WindowsApps\pkg', r'D:\WpSystem\user\LocalCache']), \
             patch('codex_relocate.windows.copy_file', side_effect=AssertionError('No cache copies')):
            result = packages.inspect('D:', raw)
        self.assertEqual(result['packages'][0]['action'], 'reuse_already_on_target')
        self.assertFalse(result['packages'][0]['copy_encrypted_cache'])
        self.assertFalse(result['automatic_package_move'])

    def test_move_required_is_advisory_only(self):
        raw = {'complete': True, 'packages': [{'name': 'OpenAI.Codex', 'family': 'OpenAI.Codex_family',
                                             'install_path': r'C:\WindowsApps\pkg'}]}
        with patch('codex_relocate.physical.directory', side_effect=[
                r'C:\WindowsApps\pkg', r'C:\Users\profile\LocalCache']):
            result = packages.inspect('D:', raw)
        self.assertEqual(result['packages'][0]['action'], 'windows_native_move_required')
        self.assertFalse(result['automatic_package_move'])

    def test_package_query_failure_is_not_success(self):
        result = packages.inspect('D:', {'complete': False, 'packages': [], 'error': 'timeout'})
        self.assertFalse(result['complete'])

    def test_invalid_package_family_is_not_joined_to_filesystem(self):
        raw = {'complete': True, 'packages': [{'family': '..\\outside'}]}
        with patch('codex_relocate.physical.directory', side_effect=AssertionError('No path resolution')):
            result = packages.inspect('D:', raw)
        self.assertEqual(result['packages'][0]['action'], 'manual_review')

    def test_empty_install_path_is_not_interpreted_as_working_directory(self):
        raw = {"complete": True, "packages": [{"family": "OpenAI.Codex_family", "install_path": ""}]}
        with patch("codex_relocate.physical.directory", side_effect=AssertionError("No path resolution")):
            result = packages.inspect("D:", raw)
        self.assertEqual(result["packages"][0]["action"], "manual_review")


if __name__ == '__main__':
    unittest.main()
