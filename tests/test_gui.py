import os
from pathlib import Path
import tempfile
import time
import tkinter as tk
import unittest
from unittest.mock import patch

from codex_relocate.gui import App, TEXT


@unittest.skipUnless(os.name == 'nt', 'Windows Tk interface integration')
class InterfaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='storage-ui-test-')
        self.root = Path(self.temp.name)
        self.window = tk.Tk()
        self.window.withdraw()
        self.app = App(self.window, self.root / 'jobs')
        self.dialog_errors = []
        self.error_patch = patch('codex_relocate.gui.messagebox.showerror',
                                 side_effect=lambda *args: self.dialog_errors.append(args))
        self.error_patch.start()
        self.yes_patch = patch('codex_relocate.gui.messagebox.askyesno', return_value=True)
        self.yes_patch.start()

    def tearDown(self):
        self.wait()
        self.error_patch.stop()
        self.yes_patch.stop()
        self.app.close()
        self.temp.cleanup()

    def wait(self):
        deadline = time.monotonic() + 30
        while self.app.busy and time.monotonic() < deadline:
            self.window.update()
            time.sleep(0.01)
        self.window.update()
        self.assertFalse(self.app.busy, 'Interface worker did not finish')

    def test_translated_controls_cover_new_workflow(self):
        keys = {key for widget, key in self.app.translated}
        self.assertTrue({'doctor', 'plan', 'save_plan', 'backup', 'accept', 'verify'} <= keys)
        for language in ('English', '中文'):
            self.app.language.set(language)
            self.app.translate()
            for widget, key in self.app.translated:
                self.assertEqual(widget.cget('text'), TEXT[key][language == '中文'])

    def test_ui_backup_accept_verify_and_cleanup_preserves_new_work(self):
        source = self.root / 'source'
        source.mkdir()
        (source / 'data.txt').write_text('old')
        destination, archive = self.root / 'destination', self.root / 'archive'
        self.app.source.set(str(source))
        self.app.destination.set(str(destination))
        self.app.archive.set(str(archive))
        self.app.move()
        self.wait()
        self.assertFalse(self.dialog_errors, self.dialog_errors)
        self.assertEqual(self.app.job_list[0]['archive']['state'], 'verified')
        (destination / 'data.txt').write_text('new')
        self.app.job_action('accept')
        self.wait()
        self.app.check_sqlite.set(True)
        self.app.job_action('verify')
        self.wait()
        self.app.job_action('release')
        self.wait()
        self.assertFalse(self.dialog_errors, self.dialog_errors)
        self.assertEqual((source / 'data.txt').read_text(), 'new')
        self.assertEqual((archive / 'data.txt').read_text(), 'old')
        self.assertEqual(self.app.job_list[0]['phase'], 'released')

    def test_doctor_button_reads_and_displays_without_mutating_data(self):
        result = {'mode': 'read_only', 'locations': [
            {'kind': 'fixture', 'path': r'C:\Example', 'physical_path': r'D:\Example', 'exists': True}],
                  'packages': {'complete': True, 'packages': []}}
        with patch('codex_relocate.gui.storage_report', return_value=result):
            self.app.storage_doctor()
            self.wait()
        self.assertIn(r'D:\Example', self.app.output.get('1.0', 'end'))
        self.assertFalse(self.dialog_errors, self.dialog_errors)

    def test_actions_fit_the_actual_window_in_both_languages(self):
        self.window.deiconify()
        for language in ("中文", "English"):
            self.app.language.set(language)
            self.app.translate()
            self.window.update()
            left, top = self.window.winfo_rootx(), self.window.winfo_rooty()
            right = left + self.window.winfo_width()
            bottom = top + self.window.winfo_height()
            for widget in self.app.actions:
                self.assertGreaterEqual(widget.winfo_rootx(), left)
                self.assertGreaterEqual(widget.winfo_rooty(), top)
                self.assertLessEqual(widget.winfo_rootx()+widget.winfo_width(), right)
                self.assertLessEqual(widget.winfo_rooty()+widget.winfo_height(), bottom)


if __name__ == '__main__':
    unittest.main()
