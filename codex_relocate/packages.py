"""Read-only MSIX discovery and planning. No package moves or encrypted-cache copies."""
import json
import os
from pathlib import Path
import subprocess

from . import physical

QUERY = r"""
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
$items=@(Get-AppxPackage -ErrorAction Stop |
    Where-Object {$_.Name -match '^OpenAI\.(Codex|ChatGPT)'} |
    ForEach-Object {
        [pscustomobject]@{name=$_.Name;full_name=$_.PackageFullName;
            family=$_.PackageFamilyName;install_path=$_.InstallLocation;
            status=[string]$_.Status}
    })
ConvertTo-Json -InputObject $items -Depth 3 -Compress
"""


def query():
    executable = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32' / \
        'WindowsPowerShell' / 'v1.0' / 'powershell.exe'
    try:
        result = subprocess.run([str(executable), '-NoProfile', '-NonInteractive',
                                 '-Command', QUERY], capture_output=True, encoding='utf-8',
                                errors='replace', timeout=20, creationflags=0x08000000)
        if result.returncode:
            return {'complete': False, 'packages': [], 'error': 'Package query failed',
                    'returncode': result.returncode}
        data = json.loads(result.stdout.lstrip('\ufeff'))
        if not isinstance(data, list):
            raise ValueError('Expected package array')
        return {'complete': True, 'packages': data}
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        return {'complete': False, 'packages': [], 'error': type(exc).__name__}


def inspect(target_drive=None, raw=None):
    raw = query() if raw is None else raw
    records = []
    target = (target_drive or '').rstrip('\\/').casefold()
    local = Path(os.environ.get('LOCALAPPDATA', str(Path.home() / 'AppData' / 'Local')))
    for package in raw.get('packages', []):
        record = dict(package)
        record['action'] = 'inspect_only'
        family = record.get('family', '')
        if not family or any(x in family for x in ('/', '\\', ':')) or family in ('.', '..'):
            record.update(action='manual_review', error='Invalid package family')
            records.append(record)
            continue
        install = record.get('install_path')
        if not isinstance(install, str) or not install or not Path(install).is_absolute():
            record.update(action='manual_review', error='Missing absolute install path')
            records.append(record)
            continue
        cache = local / 'Packages' / family / 'LocalCache'
        record['cache_path'] = str(cache)
        try:
            install_real = physical.directory(record['install_path'])
            cache_real = physical.directory(cache)
            record.update(physical_install=install_real, physical_cache=cache_real)
            if target:
                drives = [Path(p).drive.casefold() for p in (install_real, cache_real)]
                record['action'] = ('reuse_already_on_target' if all(d == target for d in drives)
                                    else 'windows_native_move_required')
        except (OSError, ValueError) as exc:
            record.update(action='manual_review', error=type(exc).__name__,
                          winerror=getattr(exc, 'winerror', None))
        record['copy_encrypted_cache'] = False
        records.append(record)
    return {'complete': raw.get('complete', False), 'packages': records,
            'error': raw.get('error'), 'automatic_package_move': False,
            'note': 'Windows package moves use Windows Settings or its deployment APIs; '
                    'this tool never copies WindowsApps or protected package caches.'}
