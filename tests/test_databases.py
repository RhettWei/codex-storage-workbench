import os
from pathlib import Path
import sqlite3
import tempfile
import unittest

from codex_relocate.databases import check_cold_databases


@unittest.skipUnless(os.name == 'nt', 'Windows frozen-copy checks')
class SQLiteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='storage-sqlite-test-')
        self.root = Path(self.temp.name)
        (self.root / 'sqlite').mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def test_both_extensions_and_nested_databases_are_checked(self):
        for path in (self.root / 'state.sqlite', self.root / 'sqlite' / 'codex.db'):
            conn = sqlite3.connect(path)
            conn.execute('create table messages (value text)')
            conn.execute("insert into messages values ('fixture')")
            conn.commit()
            conn.close()
        before = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        result = check_cold_databases(self.root)
        self.assertEqual(result['status'], 'ok', result)
        self.assertEqual(len(result['databases']), 2)
        self.assertFalse(result['source_writes'])
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()})

    def test_wal_is_copied_and_source_is_not_checkpointed(self):
        path = self.root / 'wal.sqlite'
        conn = sqlite3.connect(path)
        try:
            conn.execute('pragma journal_mode=wal')
            conn.execute('pragma wal_autocheckpoint=0')
            conn.execute('create table values_table (value integer)')
            conn.executemany('insert into values_table values (?)', [(x,) for x in range(17)])
            conn.commit()
            before = {p.name: p.read_bytes() for p in self.root.iterdir() if p.is_file()}
            result = check_cold_databases(self.root)
            self.assertEqual(result['status'], 'ok', result)
            self.assertEqual(before, {p.name: p.read_bytes() for p in self.root.iterdir() if p.is_file()})
        finally:
            conn.close()

    def test_corrupt_database_fails_without_modifying_it(self):
        path = self.root / 'bad.db'
        path.write_bytes(b'not a sqlite database' * 80)
        result = check_cold_databases(self.root)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(path.read_bytes(), b'not a sqlite database' * 80)


if __name__ == '__main__':
    unittest.main()
