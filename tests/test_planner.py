import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from codex_relocate import windows as win
from codex_relocate.engine import MigrationError
from codex_relocate.planner import apply_plan, make_plan, save_plan, load_plan


@unittest.skipUnless(os.name == 'nt', 'Windows planning tests')
class PlanTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='storage-plan-test-')
        self.root = Path(self.temp.name)
        self.source = self.root / 'source'
        self.source.mkdir()
        (self.source / 'data').write_text('hello')
        self.dest = self.root / 'destination'
        self.archive = self.root / 'archive'
        self.state = self.root / 'jobs'

    def tearDown(self):
        self.temp.cleanup()

    def plan(self, **kwargs):
        return make_plan(self.source, self.dest, self.archive, self.state,
                         include_packages=False, **kwargs)

    def test_plan_reads_metadata_without_writing_directories(self):
        result = self.plan()
        self.assertTrue(result['can_apply'], result)
        self.assertEqual(result['estimate']['bytes'], 5)
        self.assertEqual(result['space_budget'][0]['required_bytes'], 2 * (64 * 1024 * 1024 + 5))
        self.assertFalse(self.dest.exists())
        self.assertFalse(self.archive.exists())
        self.assertFalse(self.state.exists())

    def test_plan_save_and_apply_revalidates(self):
        path = self.root / 'review.json'
        save_plan(self.plan(), path)
        result = apply_plan(load_plan(path))
        self.assertEqual(result['phase'], 'migrated')
        self.assertEqual(result['archive']['state'], 'verified')
        self.assertEqual((self.dest / 'data').read_text(), 'hello')

    def test_replaced_source_root_refused(self):
        plan = self.plan()
        renamed = self.root / 'old-source'
        os.rename(self.source, renamed)
        self.source.mkdir()
        (self.source / 'data').write_text('same length but another root')
        with self.assertRaisesRegex(MigrationError, 'replaced'):
            apply_plan(plan)
        self.assertFalse(self.dest.exists())

    def test_plan_existing_destination_blocks_execution(self):
        plan = self.plan()
        self.dest.mkdir()
        (self.dest / 'keep').write_text('precious')
        with self.assertRaises(MigrationError):
            apply_plan(plan)
        self.assertEqual((self.dest / 'keep').read_text(), 'precious')

    def test_already_moved_source_is_a_noop(self):
        os.rename(self.source, self.dest)
        win.make_junction(self.source, self.dest)
        result = make_plan(self.source, self.dest, state_dir=self.state, include_packages=False)
        self.assertEqual(result['action'], 'reuse_already_on_target')
        applied = apply_plan(result)
        self.assertFalse(applied['data_changed'])
        self.assertFalse(self.state.exists())

    def test_user_can_preview_while_app_writers_are_reported(self):
        with patch('codex_relocate.planner.check_apps', side_effect=MigrationError('running')):
            result = self.plan()
        self.assertFalse(result['can_apply'])
        self.assertEqual(result['blockers'][0]['code'], 'applications_running')
        self.assertFalse(self.state.exists())

    def test_plan_cannot_be_written_inside_the_source(self):
        with self.assertRaises(MigrationError):
            save_plan(self.plan(), self.source / 'plan.json')
        self.assertFalse((self.source / 'plan.json').exists())

    def test_unsupported_plan_schema_is_rejected(self):
        path = self.root / 'invalid.json'
        path.write_text(json.dumps({'schema': 999}))
        with self.assertRaises(MigrationError):
            load_plan(path)

    def test_access_denied_is_an_explicit_blocker(self):
        error = PermissionError('fixture denied')
        error.winerror = 5
        with patch('codex_relocate.planner.snapshot', side_effect=error):
            result = self.plan()
        self.assertFalse(result['can_apply'])
        self.assertEqual(result['blockers'][0]['code'], 'access_denied')
        self.assertFalse(self.dest.exists())

    def test_existing_relocation_does_not_pretend_to_create_requested_backup(self):
        os.rename(self.source, self.dest)
        win.make_junction(self.source, self.dest)
        result = make_plan(self.source, self.dest, self.archive, self.state, include_packages=False)
        self.assertFalse(result["can_apply"])
        self.assertEqual(result["blockers"][0]["code"], "backup_requires_known_job")
        self.assertFalse(self.archive.exists())

    def test_network_path_is_refused_before_filesystem_resolution(self):
        from codex_relocate.engine import full
        with patch("codex_relocate.windows.long_path", side_effect=AssertionError("No network probe")):
            with self.assertRaises(ValueError):
                full(r"\\server\share\data")

    def test_tool_source_tree_is_refused_even_from_another_working_directory(self):
        import codex_relocate.engine as module
        project = Path(module.__file__).resolve().parent.parent
        fake_python = self.root / "external-python.exe"
        fake_python.touch()
        with patch("codex_relocate.engine.Path.cwd", return_value=self.root), \
             patch("codex_relocate.engine.sys.executable", str(fake_python)):
            with self.assertRaisesRegex(MigrationError, "Tool"):
                module.validate_paths(project, self.dest, self.state, check_processes=False)
        self.assertFalse(self.dest.exists())

    def test_managed_package_trees_are_refused_on_any_local_drive(self):
        from codex_relocate.engine import validate_paths
        paths = [self.root / "WindowsApps", self.root / "WpSystem",
                 self.root / "AppData" / "Local" / "Packages" / "Example"]
        for index, source in enumerate(paths):
            source.mkdir(parents=True)
            (source / "synthetic").write_text("keep")
            destination = self.root / ("package-destination-" + str(index))
            with self.subTest(source=source):
                with self.assertRaisesRegex(MigrationError, "Windows-managed"):
                    validate_paths(source, destination, self.state, check_processes=False)
                self.assertFalse(destination.exists())

    def test_saved_plan_beside_job_records_is_not_mistaken_for_a_job(self):
        from codex_relocate.storage import StorageEngine
        self.state.mkdir()
        path = self.state / "plan.json"
        save_plan(self.plan(), path)
        job = apply_plan(load_plan(path))
        listed = StorageEngine(self.state).jobs()
        self.assertEqual([item["id"] for item in listed], [job["id"]])
        self.assertTrue(path.exists())

    def test_managed_physical_alias_is_refused_even_with_an_ordinary_visible_name(self):
        from codex_relocate.engine import validate_paths
        with patch("codex_relocate.physical.directory", return_value=r"D:\WpSystem\example\LocalCache"):
            with self.assertRaisesRegex(MigrationError, "physical package"):
                validate_paths(self.source, self.dest, self.state, check_processes=False)
        self.assertFalse(self.dest.exists())


if __name__ == '__main__':
    unittest.main()
