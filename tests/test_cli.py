import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


@unittest.skipUnless(os.name == 'nt', 'Windows command workflow')
class CLITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='storage-cli-test-')
        self.root = Path(self.temp.name)
        self.source = self.root / 'source'
        self.source.mkdir()
        (self.source / '中文.txt').write_text('old', encoding='utf-8')
        self.dest = self.root / 'destination'
        self.archive = self.root / 'archive'
        self.state = self.root / 'jobs'

    def tearDown(self):
        self.temp.cleanup()

    def run_cli(self, *args, expected=0):
        result = subprocess.run([sys.executable, '-m', 'codex_relocate',
                                 '--state-dir', str(self.state), *map(str, args)],
                                capture_output=True, encoding='utf-8', timeout=30)
        self.assertEqual(result.returncode, expected, result.stderr + result.stdout)
        return json.loads(result.stdout) if result.stdout else result.stderr

    def test_reviewed_plan_backup_accept_and_cleanup_round_trip(self):
        plan = self.root / 'plan.json'
        self.run_cli('plan', self.source, self.dest, '--archive', self.archive,
                     '--no-packages', '--output', plan)
        job = self.run_cli('apply', plan, '--yes')
        self.assertNotIn('manifest', job)
        (self.dest / '中文.txt').write_text('new', encoding='utf-8')
        self.run_cli('accept', job['id'], '--yes')
        checked = self.run_cli('verify', job['id'], '--sqlite')
        self.assertEqual(checked['sqlite']['status'], 'ok')
        result = self.run_cli('cleanup', job['id'], '--yes')
        self.assertEqual(result['phase'], 'released')
        self.assertEqual((self.source / '中文.txt').read_text(encoding='utf-8'), 'new')
        self.assertEqual((self.archive / '中文.txt').read_text(encoding='utf-8'), 'old')

    def test_read_only_selected_doctor_does_not_create_state(self):
        result = self.run_cli('doctor', '--source', self.source, '--deep', '--no-packages', '--redact')
        self.assertEqual(result['mode'], 'read_only')
        self.assertNotIn(str(self.source), str(result))
        self.assertFalse(self.state.exists())

    def test_redacted_report_still_refuses_output_inside_inspected_source(self):
        result = self.run_cli('doctor', '--source', self.source, '--no-packages',
                              '--redact', '--output', self.source / 'report.json', expected=1)
        self.assertIn('outside', result)
        self.assertFalse((self.source / 'report.json').exists())

    def test_confirmation_is_required_for_cleanup(self):
        self.run_cli('cleanup', '0' * 32, expected=2)


if __name__ == '__main__':
    unittest.main()
