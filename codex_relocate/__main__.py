"""CLI and desktop entry point for the local storage workbench."""
import argparse
import json
import sys

from . import __version__


def public_job(value):
    if isinstance(value, dict):
        return {k: v for k, v in value.items() if k != 'manifest'}
    if isinstance(value, list):
        return [public_job(x) for x in value]
    return value


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if stream and hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description='Codex Storage Workbench — verified Windows storage workflows')
    parser.add_argument('--version', action='version', version=__version__)
    parser.add_argument('--state-dir', help='Local job journal; keep it outside every selected tree')
    sub = parser.add_subparsers(dest='command')
    sub.add_parser('gui')
    doctor = sub.add_parser('doctor', help='Read-only locations, security and physical-package diagnosis')
    doctor.add_argument('--source', help='Inspect one explicit folder instead of discovering user locations')
    doctor.add_argument('--deep', action='store_true', help='Enumerate metadata, without reading file content')
    doctor.add_argument('--no-packages', action='store_true')
    doctor.add_argument('--target-drive', help='For example D:')
    doctor.add_argument('--redact', action='store_true', help='Mask location paths and owner identities')
    doctor.add_argument('--output', help='Explicit local JSON output, outside the scanned source')
    plan = sub.add_parser('plan', help='Read-only preflight and combined copy/backup space budget')
    plan.add_argument('source')
    plan.add_argument('destination')
    plan.add_argument('--archive', help='NEW independent-backup folder')
    plan.add_argument('--no-packages', action='store_true')
    plan.add_argument('--output', help='Save a reviewable JSON plan outside the selected trees')
    apply = sub.add_parser('apply', help='Revalidate and execute a reviewed plan')
    apply.add_argument('plan_file')
    apply.add_argument('--yes', action='store_true', required=True)
    scan = sub.add_parser('scan', help='Upstream read-only discovery or size scan')
    scan.add_argument('source', nargs='?')
    for name in ('diagnose', '_handles'):
        item = sub.add_parser(name, help='Read-only open-handle evidence')
        item.add_argument('source')
    for name in ('move', 'migrate'):
        item = sub.add_parser(name, help='Copy, verify, switch and retain original')
        item.add_argument('source')
        item.add_argument('destination')
        item.add_argument('--archive', help='Also create a NEW independent backup before returning')
    backup = sub.add_parser('backup', help='Create/resume an independent copy of a retained original')
    backup.add_argument('job_id')
    backup.add_argument('destination')
    for name in ('resume', 'release', 'cleanup', 'rollback', 'accept', 'verify'):
        item = sub.add_parser(name)
        item.add_argument('job_id')
        if name in ('release', 'cleanup', 'rollback', 'accept'):
            item.add_argument('--yes', action='store_true', required=True)
        if name == 'verify':
            item.add_argument('--sqlite', action='store_true', help='Check frozen .sqlite/.db copies')
    sub.add_parser('jobs')
    args = parser.parse_args(argv)
    if args.command in (None, 'gui'):
        from .gui import launch
        launch(args.state_dir)
        return 0
    from . import windows, doctor as diagnosis
    from .discovery import candidates, scan as size_scan
    from .engine import atomic_json, full, inside, MigrationError
    from .planner import make_plan, save_plan, load_plan, apply_plan
    from .storage import StorageEngine
    try:
        exit_code = 0
        if args.command == 'doctor':
            if args.source:
                result = {'schema': 1, 'mode': 'read_only',
                          'locations': [diagnosis.inspect_location('selected', full(args.source), args.deep)]}
            else:
                result = diagnosis.report(args.deep, not args.no_packages, args.target_drive)
            roots = ([args.source] if args.source else [
                root for item in result.get('locations', [])
                for root in (item['path'], item.get('physical_path')) if root])
            if args.redact:
                result = diagnosis.redact(result)
            if args.output:
                target = full(args.output)
                if any(root and inside(target, root) for root in roots):
                    raise MigrationError('Save the report outside the inspected source.')
                atomic_json(target, result)
        elif args.command == 'plan':
            result = make_plan(args.source, args.destination, args.archive,
                               args.state_dir, not args.no_packages)
            if args.output:
                save_plan(result, args.output)
            exit_code = 0 if result['can_apply'] else 2
        elif args.command == 'apply':
            plan = load_plan(args.plan_file)
            if args.state_dir and full(args.state_dir) != full(plan['state_dir']):
                raise MigrationError('State directory must match the reviewed plan.')
            result = apply_plan(plan)
        elif args.command == '_handles':
            result = windows.directory_handles(args.source)
        elif args.command == 'diagnose':
            result = windows.diagnose(args.source)
        elif args.command == 'scan':
            result = size_scan(args.source) if args.source else candidates()
        else:
            engine = StorageEngine(args.state_dir,
                                   lambda message: print(message, file=sys.stderr, flush=True))
            if args.command in ('move', 'migrate'):
                result = engine.migrate(args.source, args.destination, args.archive)
            elif args.command == 'backup':
                result = engine.seal(args.job_id, args.destination)
            elif args.command == 'jobs':
                result = engine.jobs()
            elif args.command == 'verify':
                result = engine.verify(args.job_id, args.sqlite)
            else:
                action = 'release' if args.command == 'cleanup' else args.command
                result = getattr(engine, action)(args.job_id)
        print(json.dumps(public_job(result), ensure_ascii=False, indent=2))
        return exit_code
    except Exception as exc:
        print(json.dumps({'error': type(exc).__name__, 'message': str(exc)},
                         ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
