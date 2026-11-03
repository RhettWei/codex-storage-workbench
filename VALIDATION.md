# Validation record

Version: 0.2.0.dev1
Date: 2026-11-03
Environment: Windows 11, build 26300; x64 Python 3.12.14; Tk 8.6.

## Source tests

Command: python -m unittest discover -s tests -v

- 97 tests ran.
- 96 passed; 1 skipped because Developer Mode/symbolic-link creation privilege is unavailable.
- No failures.
- Includes 27 upstream tests plus new filesystem, archive, CLI, GUI, doctor, planning,
  JSON-publication and SQLite cases.
- Both Chinese and English action controls were checked against actual Tk window bounds.
- GUI flow exercised migration, independent backup, new live writes, user acceptance,
  frozen-database verification and release on temporary synthetic data.
- Filesystem tests used real local NTFS directories, junctions, named streams, SQLite
  WAL state, injected failures and interrupted cleanup.

## Read-only local smoke

The doctor command discovered eight configured/known locations, marked two duplicate
entries, and completed the Windows package query. The existing Codex package and
private cache were physically on D: and received reuse_already_on_target, with
copy_encrypted_cache=false. No source data migration or cleanup was executed.

## Scope of evidence

This is one Windows machine/version, not acceptance across all Windows 10/11,
Codex versions or storage configurations. The inherited GitHub workflow was updated
for Python 3.11/3.12/3.13; the derivative's remote CI has not been run.

The desktop-control helper could not start due to the host's existing
CreateProcessSecurityEnvironment / 0x80070020 error. Automated Tk widget/workflow
and geometry tests passed; a separate screenshot-based visual review was unavailable.

A packaged EXE completed a real C: -> D: synthetic-data workflow: reviewed plan,
copy, independent backup, frozen SQLite checks, user acceptance and cleanup.
New live files, database rows and named streams survived; frozen backups stayed intact.
The packaged desktop window started successfully. Archive-level validation is also
recorded in the accompanying delivery verification file. Unsupported EFS, protected ownership,
package-moving and service-control operations remain blocked/advisory.
