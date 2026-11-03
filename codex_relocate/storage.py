"""Codex-specific workflows layered on the MIT upstream transaction engine."""
from datetime import datetime, timezone
import os
from pathlib import Path
import shutil
import stat

from . import windows as win
from .copying import (copy_archive, ensure_independent, space_budget,
                      validate_backup_path)
from .engine import (Engine, MigrationError, content, exists, full, identity,
                     inside, is_link, snapshot, summary)


class StorageEngine(Engine):
    def __init__(self, state_dir=None, progress=None):
        default = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / \
            'CodexStorageWorkbench' / 'jobs'
        super().__init__(state_dir or default, progress)

    @staticmethod
    def now():
        return datetime.now(timezone.utc).isoformat()

    def migrate(self, source, destination, archive_path=None):
        if exists(source) and is_link(source):
            from .physical import directory, key
            if key(directory(source)) == key(full(destination)):
                if archive_path:
                    raise MigrationError('Already relocated. Inspect the original job before creating a backup.')
                return {'phase': 'already_on_target', 'source': str(full(source)),
                        'destination': str(full(destination)), 'data_changed': False}
        if archive_path:
            archive = validate_backup_path(archive_path, source, destination, self.state_dir)
            if exists(archive):
                raise MigrationError('Independent backup must be a NEW folder.')
            size = summary(snapshot(source, hashes=False))['bytes']
            if not all(row['enough'] for row in space_budget([destination, archive], size)):
                raise MigrationError('Not enough space for destination AND independent backup.')
        job = super().migrate(source, destination)
        if archive_path:
            try:
                return self.seal(job['id'], archive_path)
            except Exception as exc:
                raise MigrationError('Migration switched and original was retained; independent backup '
                                     'is incomplete. Inspect jobs / resume before cleanup. ' + str(exc)) from exc
        return job

    def seal(self, job_id, archive_path):
        with self.locked():
            job = self.load(job_id)
            if job['phase'] != 'migrated':
                raise MigrationError('Create an independent backup only for a switched, retained job.')
            self._check_switched(job)
            path = validate_backup_path(archive_path, job['backup'],
                                        job['destination'], self.state_dir)
            # Also reject the old logical source and any ancestor containing it.
            if inside(path, job['source']) or inside(job['source'], path):
                raise MigrationError('Independent backup overlaps the source entry.')
            if job.get('archive'):
                if full(job['archive']['path']) != path:
                    raise MigrationError('This job already has a different backup path.')
                if job['archive']['state'] == 'verified':
                    self._validate_archive(job)
                    return job
            else:
                if exists(path):
                    raise MigrationError('Independent backup must be a NEW folder.')
                size = job['summary']['bytes']
                if not all(x['enough'] for x in space_budget([path], size)):
                    raise MigrationError('Insufficient independent-backup space.')
                job['archive'] = {'path': str(path), 'state': 'planned'}
                self.save(job)
            return copy_archive(self, job)

    def _validate_archive(self, job):
        archive = job.get('archive', {})
        if archive.get('state') != 'verified':
            raise MigrationError('No verified independent backup. Use backup / resume first.')
        path = validate_backup_path(archive['path'], job['backup'],
                                    job['destination'], self.state_dir)
        if inside(path, job['source']) or inside(job['source'], path):
            raise MigrationError('Independent backup overlaps the source entry.')
        self._assert_directory(path, archive['identity'])
        if content(snapshot(path, progress=self.progress)) != content(job['manifest']):
            raise MigrationError('Independent backup changed; cleanup refused.')
        original = full(job['backup'])
        # Original may be partly/fully removed only after journaled cleanup started.
        ensure_independent(path, original if exists(original) else None,
                           full(job['destination']), job['manifest'])
        return path

    def accept(self, job_id):
        """Record USER-reported acceptance, never claim an automated UI check."""
        with self.locked():
            job = self.load(job_id)
            if job['phase'] != 'migrated':
                raise MigrationError('Acceptance requires a switched job with originals retained.')
            self._check_switched(job)
            self._validate_archive(job)
            if content(snapshot(job['backup'], progress=self.progress)) != content(job['manifest']):
                raise MigrationError('Retained original changed; acceptance stopped.')
            job['acceptance'] = {'type': 'user_reported', 'at': self.now(),
                                 'scope': 'User confirmed app/history/tools before cleanup.'}
            self.save(job)
            return job

    def _resume(self, job):
        if job['phase'] == 'releasing_archive':
            return self._release_archive(job)
        if job['phase'] == 'migrated' and job.get('archive', {}).get('state') in ('planned', 'copying'):
            self._check_switched(job)
            return copy_archive(self, job)
        return super()._resume(job)

    def release(self, job_id):
        job = self.load(job_id)
        if job.get('archive'):
            with self.locked():
                return self._release_archive(self.load(job_id))
        return super().release(job_id)

    def _release_archive(self, job):
        if job['phase'] == 'released':
            return job
        if job['phase'] not in ('migrated', 'releasing_archive'):
            raise MigrationError('Independent-backup cleanup is not available in this phase.')
        if job.get('acceptance', {}).get('type') != 'user_reported':
            raise MigrationError('Confirm app/history/tools with accept before cleanup.')
        source, destination, original = self._check_switched(job)
        archive = self._validate_archive(job)
        baseline = content(job['manifest'])
        remaining = snapshot(original, progress=self.progress) if exists(original) else {}
        actual = content(remaining)
        if any(baseline.get(rel) != value for rel, value in actual.items()):
            raise MigrationError('Original contains new/changed entries; cleanup refused.')
        if job['phase'] == 'migrated' and actual != baseline:
            raise MigrationError('Original is incomplete before cleanup; inspect manually.')
        if job['phase'] != 'releasing_archive':
            job['cleanup_free_before'] = shutil.disk_usage(source.anchor).free
        job['release_mode'] = 'verified_independent_backup'
        self.save(job, 'releasing_archive')
        # Never read/write active file contents. Remove only the frozen sibling.
        for rel in sorted(remaining, key=lambda x: len(Path(x).parts), reverse=True):
            path = original / rel
            if path == original or not inside(path, original):
                raise MigrationError('Cleanup path escaped its retained root.')
            item = remaining[rel]
            if item['kind'] == 'link':
                if not is_link(path) or os.readlink(win.extended(path)) != item['target']:
                    raise MigrationError('Retained link changed during cleanup.')
                (os.rmdir if item['directory'] else os.unlink)(win.extended(path))
            elif item['kind'] == 'dir':
                if is_link(path):
                    raise MigrationError('Retained directory became a link.')
                os.rmdir(win.extended(path))
            else:
                if is_link(path):
                    raise MigrationError('Retained file became a link.')
                if item['readonly']:
                    os.chmod(win.extended(path), stat.S_IWRITE | stat.S_IREAD)
                os.unlink(win.extended(path))
        if exists(original):
            os.rmdir(win.extended(original))
        self._check_switched(job)
        self._assert_directory(archive, job['archive']['identity'])
        job['free_after'] = shutil.disk_usage(source.anchor).free
        job['observed_free_change'] = job['free_after'] - job['cleanup_free_before']
        job['cleanup_checks'] = {'independent_backup': 'verified',
                                  'active_target': 'identity and junction only; contents left untouched'}
        self.save(job, 'released')
        return job

    def verify(self, job_id, sqlite=False):
        with self.locked():
            job = self.load(job_id)
            result = {'id': job_id, 'phase': job['phase'], 'source': job['source'],
                      'destination': job['destination'], 'summary': job['summary'], 'checks': {}}
            if job['phase'] not in ('migrated', 'releasing_archive', 'released'):
                result['next_step'] = 'Resume or inspect the pending migration first.'
                return result
            source, destination, original = self._check_switched(job)
            result['checks']['active_path'] = 'expected junction and directory identity'
            if exists(original):
                actual = content(snapshot(original, progress=self.progress))
                expected = content(job['manifest'])
                if job['phase'] == 'migrated' and actual != expected or \
                   any(expected.get(k) != v for k, v in actual.items()):
                    raise MigrationError('Retained original does not match its frozen manifest.')
                result['checks']['retained_original'] = 'verified'
            if job.get('archive'):
                archive = self._validate_archive(job)
                result['checks']['independent_backup'] = 'verified'
            else:
                archive = None
            result['checks']['acceptance'] = job.get('acceptance', {'type': 'pending'})
            if sqlite:
                from .databases import check_cold_databases
                if job['phase'] != 'migrated' and not archive:
                    raise MigrationError('SQLite checks require a complete frozen copy.')
                result['sqlite'] = check_cold_databases(archive or original)
                if result['sqlite']['status'] != 'ok':
                    raise MigrationError('SQLite integrity check failed: ' + str(result['sqlite']['databases']))
            return result
