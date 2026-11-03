import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from codex_relocate.engine import atomic_json, Engine, MigrationError
from codex_relocate import windows as win


class AtomicTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='storage-json-test-')
        self.root = Path(self.temp.name)
        self.path = self.root / 'result.json'

    def tearDown(self):
        self.temp.cleanup()

    def test_failed_serialization_preserves_complete_previous_file(self):
        atomic_json(self.path, {'old': '完整'})
        def interrupted(value, stream, **kwargs):
            stream.write('{"partial":')
            raise OSError('injected interruption')
        with patch('codex_relocate.engine.json.dump', side_effect=interrupted):
            with self.assertRaises(OSError):
                atomic_json(self.path, {'new': 'value'})
        self.assertEqual(json.loads(self.path.read_text(encoding='utf-8')), {'old': '完整'})
        self.assertEqual(list(self.root.glob('*.writing-*')), [])

    def test_readers_never_observe_half_written_unicode_json(self):
        atomic_json(self.path, {'n': -1, 'payload': 'initial'})
        stop, started = threading.Event(), threading.Event()
        failures, observed = [], []
        def reader():
            while not stop.is_set():
                try:
                    value = json.loads(self.path.read_text(encoding='utf-8'))
                    observed.append(value['n'])
                    started.set()
                except PermissionError:
                    continue
                except Exception as exc:
                    failures.append(exc)
                    started.set()
        worker = threading.Thread(target=reader)
        worker.start()
        try:
            self.assertTrue(started.wait(3))
            for n in range(5):
                atomic_json(self.path, {'n': n, 'payload': '中文😀' * 20000})
        finally:
            stop.set()
            worker.join(5)
        self.assertFalse(worker.is_alive())
        self.assertFalse(failures)
        self.assertTrue(observed)
        self.assertEqual(json.loads(self.path.read_text(encoding='utf-8'))['n'], 4)

    @unittest.skipUnless(os.name == 'nt', 'Windows shared-read behavior')
    def test_transient_sharing_failure_is_retried(self):
        original = os.replace
        calls = [0]
        def replace(source, target):
            calls[0] += 1
            if calls[0] == 1:
                error = PermissionError('busy')
                error.winerror = 32
                raise error
            return original(source, target)
        with patch('codex_relocate.engine.os.replace', side_effect=replace):
            atomic_json(self.path, {'status': 'ok'})
        self.assertEqual(calls[0], 2)
        self.assertEqual(json.loads(self.path.read_text())['status'], 'ok')

    @unittest.skipUnless(os.name == 'nt', 'NTFS no-follow check')
    def test_linked_state_parent_refused_without_creating_directories(self):
        target = self.root / 'target'
        target.mkdir()
        alias = self.root / 'alias'
        win.make_junction(alias, target)
        with self.assertRaises(MigrationError):
            Engine(alias / 'jobs')
        self.assertFalse((target / 'jobs').exists())


if __name__ == '__main__':
    unittest.main()
