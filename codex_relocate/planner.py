"""Read-only migration planning; execution always revalidates current conditions."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import uuid

from .copying import space_budget, validate_backup_path
from .engine import (MigrationError, atomic_json, check_apps, exists, full,
                     identity, inside, is_link, snapshot, summary, validate_paths)
from . import packages, physical


def default_state_dir():
    return Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'CodexStorageWorkbench' / 'jobs'


def make_plan(source, destination, archive_path=None, state_dir=None, include_packages=True):
    state = full(state_dir or default_state_dir())
    source, destination = full(source), full(destination)
    result = {'schema': 1, 'id': uuid.uuid4().hex,
              'created_at': datetime.now(timezone.utc).isoformat(), 'mode': 'read_only_plan',
              'source': str(source), 'destination': str(destination),
              'state_dir': str(state), 'archive_path': str(full(archive_path)) if archive_path else None,
              'action': 'copy_verify_switch_retain', 'blockers': [], 'warnings': []}
    try:
        if exists(source):
            result['physical_source'] = physical.directory(source)
            result['source_identity'] = identity(source)
            if is_link(source) and physical.key(result['physical_source']) == physical.key(destination):
                result['action'] = 'reuse_already_on_target'
                if archive_path:
                    result['blockers'].append({'code': 'backup_requires_known_job',
                        'message': 'Already relocated. Inspect its original job before creating a backup.'})
                result['can_apply'] = not result['blockers']
                result['packages'] = packages.inspect(destination.drive) if include_packages else None
                return result
        validate_paths(source, destination, state, check_processes=False)
        manifest = snapshot(source, hashes=False)
        result['estimate'] = summary(manifest)
        result['estimate']['entries'] = len(manifest)
        targets = [destination]
        if archive_path:
            archive = validate_backup_path(archive_path, source, destination, state)
            if exists(archive):
                raise MigrationError('Independent backup must be a NEW folder.')
            targets.append(archive)
        result['space_budget'] = space_budget(targets, result['estimate']['bytes'])
        if not all(x['enough'] for x in result['space_budget']):
            result['blockers'].append({'code': 'insufficient_space',
                                       'message': 'Destination and independent-backup budgets are combined per volume.'})
        try:
            check_apps(source)
        except MigrationError:
            result['blockers'].append({'code': 'applications_running',
                                       'message': 'Close app writers before execution; planning changed no files.'})
        if source.drive.casefold() == destination.drive.casefold():
            result['warnings'].append('Source and destination are on the same drive; moving will not free another drive.')
        if identity(source) != result['source_identity']:
            raise MigrationError('Source identity changed during planning.')
    except (OSError, ValueError, MigrationError) as exc:
        code = ('access_denied' if getattr(exc, 'winerror', None) == 5 else 'unsupported_or_unsafe_path')
        result['blockers'].append({'code': code, 'message': str(exc),
                                   'winerror': getattr(exc, 'winerror', None)})
    result['can_apply'] = not result['blockers']
    result['packages'] = packages.inspect(destination.drive) if include_packages else None
    result['scope'] = 'One ordinary folder transaction; Windows package entries are advisory and never copied.'
    return result


def save_plan(plan, path):
    path = full(path)
    for root in (plan['source'], plan['destination'], plan.get('archive_path')):
        if root and inside(path, root):
            raise MigrationError('Save the plan outside all migration and backup trees.')
    if not path.parent.is_dir():
        raise MigrationError('Plan output parent must already exist.')
    atomic_json(path, plan)


def load_plan(path):
    path = Path(path)
    if path.stat().st_size > 1024 * 1024:
        raise MigrationError('Plan exceeds the supported size.')
    data = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(data, dict) or data.get('schema') != 1 or data.get('mode') != 'read_only_plan':
        raise MigrationError('Unknown plan format.')
    for key in ('source', 'destination', 'state_dir'):
        if not isinstance(data.get(key), str) or not Path(data[key]).is_absolute():
            raise MigrationError('Plan paths must be absolute.')
    return data


def apply_plan(plan):
    from .storage import StorageEngine
    source = full(plan['source'])
    if not exists(source) or identity(source) != plan.get('source_identity'):
        raise MigrationError('Planned source was replaced; create and review a new plan.')
    fresh = make_plan(source, plan['destination'], plan.get('archive_path'),
                      plan['state_dir'], include_packages=False)
    if not fresh['can_apply']:
        raise MigrationError('Execution preflight blocked: ' + json.dumps(fresh['blockers'], ensure_ascii=False))
    if fresh['action'] == 'reuse_already_on_target':
        return {'phase': 'already_on_target', 'source': str(source),
                'physical_path': fresh['physical_source'], 'data_changed': False}
    return StorageEngine(plan['state_dir']).migrate(source, plan['destination'],
                                                   plan.get('archive_path'))
