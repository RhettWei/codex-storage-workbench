"""Read-only Codex storage discovery. Reads config paths, not chats or credentials."""
from datetime import datetime, timezone
import os
from pathlib import Path
import stat
import tomllib

from . import physical
from . import windows as win
from .discovery import documents_folder
from .engine import exists, full
from . import packages


def issue(code, path, exc=None):
    result = {'code': code, 'path': str(path)}
    if exc:
        result.update(error=type(exc).__name__, winerror=getattr(exc, 'winerror', None))
    if code == 'access_denied':
        result['next_step'] = 'Review the owner/access rules. No permissions were changed.'
    return result


def locations(env=None, home=None, documents=None):
    env = os.environ if env is None else env
    home = Path.home() if home is None else Path(home)
    docs = documents_folder() if documents is None else Path(documents)
    codex = full(env.get('CODEX_HOME') or home / '.codex')
    config = codex / 'config.toml'
    config_issues, sqlite = [], None
    if exists(config):
        try:
            if config.stat().st_size > 1024 * 1024:
                config_issues.append(issue('config_too_large', config))
            else:
                # Return only recognized path settings; never serialize config content.
                with config.open('rb') as stream:
                    value = tomllib.load(stream).get('sqlite_home')
                if value is not None:
                    if not isinstance(value, str) or not value:
                        config_issues.append(issue('invalid_sqlite_home', config))
                    else:
                        sqlite = full(value)
        except (OSError, ValueError) as exc:
            config_issues.append(issue('config_unreadable_or_invalid', config, exc))
    database = sqlite or full(env.get('CODEX_SQLITE_HOME') or codex)
    local = Path(env.get('LOCALAPPDATA') or home / 'AppData' / 'Local')
    install = full(env.get('CODEX_INSTALL_DIR') or local / 'Programs' / 'OpenAI' / 'Codex' / 'bin')
    paths = [('codex_home', codex), ('legacy_codex_home', home / '.codex'),
             ('sqlite_home', database), ('projects', docs / 'Codex'),
             ('projects', docs / 'ChatGPT'), ('openai_tools', local / 'OpenAI'),
             ('standalone_cli', install), ('runtime_cache', home / '.cache' / 'codex-runtimes')]
    return paths, config_issues


def metadata_walk(root, limit=200000):
    """No file-content reads, no recursion through child links; report incomplete scans."""
    stack, files, size, links, entries, issues = [str(root)], 0, 0, 0, 0, []
    while stack:
        directory = stack.pop()
        try:
            with os.scandir(win.extended(directory)) as it:
                children = list(it)
        except OSError as exc:
            issues.append(issue('access_denied' if getattr(exc, 'winerror', None) == 5
                                else 'enumeration_failed', directory, exc))
            continue
        for child in children:
            entries += 1
            if entries > limit:
                issues.append(issue('scan_limit_reached', root))
                return dict(files=files, bytes=size, links=links, complete=False, issues=issues)
            try:
                item = child.stat(follow_symlinks=False)
                attrs = item.st_file_attributes
                if attrs & 0x400:
                    links += 1
                    continue
                if attrs & 0x4000:
                    issues.append(issue('encrypted_entry', child.path))
                if stat.S_ISDIR(item.st_mode):
                    stack.append(child.path)
                elif stat.S_ISREG(item.st_mode):
                    files += 1
                    size += item.st_size
            except OSError as exc:
                issues.append(issue('metadata_unreadable', child.path, exc))
    return dict(files=files, bytes=size, links=links, complete=not issues, issues=issues)


def inspect_location(kind, path, deep=False):
    result = {'kind': kind, 'path': str(path), 'exists': False}
    try:
        info = os.lstat(win.extended(path))
    except FileNotFoundError:
        return result
    except OSError as exc:
        result['exists'] = None
        result['issue'] = issue('access_denied' if getattr(exc, 'winerror', None) == 5
                                else 'path_unavailable', path, exc)
        return result
    result['exists'] = True
    try:
        if not stat.S_ISDIR(info.st_mode):
            result['issue'] = issue('not_a_directory', path)
            return result
        result['linked'] = bool(info.st_file_attributes & 0x400)
        result['physical_path'] = physical.directory(path)
        result['encrypted_root'] = bool(os.stat(win.extended(result['physical_path'])).st_file_attributes & 0x4000)
        try:
            result['security'] = physical.security(result['physical_path'])
        except OSError as exc:
            result['security'] = issue('access_denied' if getattr(exc, 'winerror', None) == 5
                                       else 'security_unreadable', result['physical_path'], exc)
        if deep:
            result['scan'] = metadata_walk(result['physical_path'])
    except OSError as exc:
        result['issue'] = issue('access_denied' if getattr(exc, 'winerror', None) == 5
                                else 'path_unavailable', path, exc)
    return result


def report(deep=False, include_packages=True, target_drive=None, env=None,
           home=None, documents=None):
    paths, issues = locations(env, home, documents)
    records, seen = [], {}
    for kind, path in paths:
        row = inspect_location(kind, full(path), deep=False)
        if row.get('physical_path'):
            canonical = physical.key(row['physical_path'])
            duplicate = seen.get(canonical)
            if duplicate:
                row['same_storage_as'] = duplicate
            else:
                seen[canonical] = row['path']
                if deep:
                    row['scan'] = metadata_walk(row['physical_path'])
        records.append(row)
    # Do not add nested locations: sqlite_home is often inside codex_home.
    counted, known_bytes = [], 0
    for row in sorted(records, key=lambda r: len(r.get('physical_path', ''))):
        if 'physical_path' not in row or row.get('same_storage_as'):
            continue
        actual = physical.key(row['physical_path'])
        try:
            covered = any(os.path.commonpath([actual, parent]) == parent for parent in counted)
        except ValueError:
            covered = False
        if covered:
            row['included_in_parent_total'] = True
        elif deep and 'scan' in row:
            counted.append(actual)
            known_bytes += row['scan']['bytes']
    env = os.environ if env is None else env
    return {'schema': 1, 'checked_at': datetime.now(timezone.utc).isoformat(),
            'mode': 'read_only', 'locations': records, 'config_issues': issues,
            'metadata_bytes_unique_roots': known_bytes if deep else None,
            'size_note': 'Metadata estimate excludes followed links, named streams and allocation overhead; '
                         'incomplete scans are not complete size measurements.',
            'packages': packages.inspect(target_drive) if include_packages else
                        {'complete': False, 'packages': [], 'skipped': True},
            'temporary_paths': {'TEMP': env.get('TEMP'), 'TMP': env.get('TMP')},
            'privilege_policy': 'No process killing, service changes, decryption or ACL changes.'}



def redact(value):
    """Local support export: remove every discovered root and Windows owner identity."""
    import re
    import json
    mapping = {}
    for index, row in enumerate(value.get('locations', [])):
        for name in ('path', 'physical_path', 'same_storage_as'):
            if row.get(name):
                mapping[row[name]] = '<location-{}>'.format(index + 1)
    for name in ('USERPROFILE', 'LOCALAPPDATA', 'APPDATA', 'TEMP', 'TMP'):
        if os.environ.get(name):
            mapping[os.environ[name]] = '<{}>'.format(name.lower())
    def visit(item):
        if isinstance(item, dict):
            return {key: '<owner>' if key == 'owner' else visit(data)
                    for key, data in item.items()}
        if isinstance(item, list):
            return [visit(x) for x in item]
        if isinstance(item, str):
            for old, new in sorted(mapping.items(), key=lambda pair: len(pair[0]), reverse=True):
                item = re.sub(re.escape(old), lambda match: new, item, flags=re.IGNORECASE)
            return re.sub(r'S-1-5-21-(?:\d+-){2,3}\d+', '<user-sid>', item)
        return item
    return visit(value)
