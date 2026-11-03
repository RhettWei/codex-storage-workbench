"""Independent, resumable archival copies using the upstream Windows copy boundary."""
import os
from pathlib import Path
import shutil
import stat
import sys

from . import windows as win
from .engine import (MigrationError, content, digest, exists, full, identity,
                     inside, is_link, no_link_ancestors, snapshot, JUNCTION)


def validate_backup_path(path, source, destination, state_dir):
    path = full(path)
    if win.package_storage_path(path):
        raise MigrationError('Windows-managed package storage cannot be an ordinary backup destination.')
    no_link_ancestors(path)
    if not path.parent.is_dir():
        raise MigrationError('Independent-backup parent folder must already exist.')
    from .physical import directory as physical_directory
    if win.package_storage_path(physical_directory(path.parent)):
        raise MigrationError('Windows-managed physical package storage cannot hold an ordinary backup.')
    volume = win.volume(path)
    if not volume['fixed'] or volume['filesystem'] != 'NTFS':
        raise MigrationError('Independent backup requires a fixed local NTFS volume.')
    protected = [full(source), full(destination), full(state_dir),
                 Path.cwd(), full(sys.executable), full(__file__).parent.parent]
    # Also prevent overlap with the sibling that will retain the original.
    for other in protected:
        if inside(path, other) or inside(other, path):
            raise MigrationError('Independent backup overlaps data, tool or journal.')
    if path == Path(path.anchor) or path == Path.home():
        raise MigrationError('Independent backup cannot be a drive or user root.')
    for name in ('WINDIR', 'ProgramFiles', 'ProgramFiles(x86)', 'ProgramData'):
        if os.environ.get(name) and inside(path, os.environ[name]):
            raise MigrationError('Independent backup cannot be in a system directory.')
    return path


def space_budget(destinations, size):
    groups = {}
    for path in destinations:
        path = full(path)
        device = os.stat(win.extended(path.parent)).st_dev
        if device not in groups:
            groups[device] = {'drive': path.drive, 'drives': [], 'volume_device': device,
                              'required_bytes': 0, 'available_bytes': shutil.disk_usage(path.parent).free}
        if path.drive not in groups[device]['drives']:
            groups[device]['drives'].append(path.drive)
        groups[device]['required_bytes'] += size + max(64 * 1024 * 1024, size // 100)
    for row in groups.values():
        row['enough'] = row['available_bytes'] >= row['required_bytes']
    return list(groups.values())


def ensure_independent(archive, original, destination, manifest):
    """Reject linked ancestors and regular files hard-linked to either active tree."""
    no_link_ancestors(archive)
    roots = [root for root in (original, destination) if root is not None]
    if identity(archive) in [identity(root) for root in roots]:
        raise MigrationError('Independent-backup root aliases another copy.')
    for rel, item in manifest.items():
        if item['kind'] != 'file':
            continue
        backup_file = archive / rel
        backup_id = identity(backup_file)
        for root in roots:
            candidate = root / rel
            if exists(candidate):
                info = os.lstat(win.extended(candidate))
                if stat.S_ISREG(info.st_mode) and not info.st_file_attributes & 0x400:
                    if backup_id == identity(candidate):
                        raise MigrationError('Backup is hard-linked to another copy: ' + rel)


def copy_archive(engine, job):
    archive = job['archive']
    root = full(archive['path'])
    original = full(job['backup'])
    baseline = content(job['manifest'])
    engine._assert_directory(original, job['source_identity'])
    if content(snapshot(original, progress=engine.progress)) != baseline:
        raise MigrationError('Retained original changed; independent backup stopped.')
    no_link_ancestors(root)
    if archive['state'] == 'planned':
        if exists(root):
            if 'identity' not in archive:
                raise MigrationError('Backup path appeared; unknown data was preserved.')
            engine._assert_directory(root, archive['identity'])
        else:
            os.mkdir(win.extended(root))
            archive['identity'] = identity(root)
            engine.save(job)
        win.copy_acl(original, root)
        archive['state'] = 'copying'
        engine.save(job)
    engine._assert_directory(root, archive['identity'])
    partial = root.parent / ('.storage-archive-part-' + job['id'])
    if exists(partial):
        if is_link(partial) or identity(partial) != archive.get('partial_identity'):
            raise MigrationError('Unrecognized backup partial file preserved.')
        os.chmod(win.extended(partial), stat.S_IWRITE | stat.S_IREAD)
        os.unlink(win.extended(partial))
    archive.pop('partial_identity', None)
    win.copy_acl(original, root)
    for rel, item in sorted(job['manifest'].items(),
                            key=lambda kv: (len(Path(kv[0]).parts), kv[0])):
        source, target = original / rel, root / rel
        if exists(target):
            if item['kind'] == 'dir' and not is_link(target) and target.is_dir():
                continue
            if item['kind'] == 'link' and is_link(target) and os.readlink(win.extended(target)) == item['target']:
                continue
            if item['kind'] == 'file' and not is_link(target) and digest(target) == item['sha256']:
                continue
            raise MigrationError('Conflicting independent-backup entry preserved: ' + rel)
        if item['kind'] == 'dir':
            os.mkdir(win.extended(target))
            win.copy_acl(source, target)
        elif item['kind'] == 'link':
            if item['tag'] == JUNCTION:
                win.make_junction(target, item['target'].removeprefix('\\\\?\\'))
            else:
                os.symlink(item['target'], win.extended(target),
                           target_is_directory=item['directory'])
        else:
            with open(win.extended(partial), 'xb'):
                pass
            archive['partial_identity'] = identity(partial)
            engine.save(job)
            win.copy_acl(source, partial)
            win.copy_file(source, partial, overwrite=True)
            if digest(partial) != item['sha256']:
                raise MigrationError('Independent-backup file hash mismatch: ' + rel)
            os.rename(win.extended(partial), win.extended(target))
            archive.pop('partial_identity', None)
            engine.save(job)
    if content(snapshot(root, progress=engine.progress)) != baseline or \
       content(snapshot(original, progress=engine.progress)) != baseline:
        raise MigrationError('Independent backup does not match frozen original.')
    ensure_independent(root, original, full(job['destination']), job['manifest'])
    archive['state'] = 'verified'
    archive['verified_at'] = engine.now()
    archive['integrity'] = 'file contents, named streams, empty directories and links'
    engine.save(job)
    engine.progress('Independent backup verified. Reopen the app, then acknowledge acceptance.')
    return job
