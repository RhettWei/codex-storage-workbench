"""Integrity checks on disposable copies of frozen databases; never open live DBs."""
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile

from . import windows as win
from .engine import exists, full, is_link, no_link_ancestors


def check_cold_databases(root):
    root = full(root)
    no_link_ancestors(root)
    results = []
    candidates = []
    for directory in (root, root / 'sqlite'):
        if not exists(directory):
            continue
        if is_link(directory):
            results.append({'file': str(directory.relative_to(root)), 'status': 'unsupported_link'})
            continue
        with os.scandir(win.extended(directory)) as entries:
            for entry in entries:
                if entry.name.lower().endswith(('.db', '.sqlite')):
                    candidates.append(Path(entry.path))
    for source in sorted(candidates):
        relative = str(source.relative_to(Path(win.extended(root))))
        try:
            if is_link(source):
                raise ValueError('Database is a link')
            members = [source] + [Path(str(source) + suffix) for suffix in ('-wal', '-journal')
                                  if exists(str(source) + suffix)]
            before = {}
            for member in members:
                if is_link(member):
                    raise ValueError('Database sidecar is a link')
                info = os.stat(member, follow_symlinks=False)
                before[str(member)] = (info.st_ino, info.st_size, info.st_mtime_ns)
            with tempfile.TemporaryDirectory(prefix='codex-sqlite-check-') as temporary:
                target = Path(temporary) / source.name
                for member in members:
                    shutil.copyfile(member, Path(temporary) / member.name)
                for member in members:
                    info = os.stat(member, follow_symlinks=False)
                    if before[str(member)] != (info.st_ino, info.st_size, info.st_mtime_ns):
                        raise ValueError('Frozen database changed while copied')
                connection = sqlite3.connect(str(target))
                try:
                    rows = connection.execute('PRAGMA integrity_check').fetchall()
                    ok = rows == [('ok',)]
                finally:
                    connection.close()
            results.append({'file': relative, 'status': 'ok' if ok else 'integrity_failed'})
        except (OSError, ValueError, sqlite3.Error) as exc:
            results.append({'file': relative, 'status': 'failed', 'error': type(exc).__name__})
    return {'status': 'ok' if all(x['status'] == 'ok' for x in results) else 'failed',
            'databases': results, 'source_writes': False,
            'scope': 'Frozen .db/.sqlite files in root and sqlite/; WAL/journal copied, SHM regenerated in temp.'}
