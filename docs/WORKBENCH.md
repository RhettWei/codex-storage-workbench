# Workbench extensions and invariants

## Architecture

The upstream Engine remains the ordinary copy / verify / switch / release path.
StorageEngine extends it with an independently verified frozen copy and a
user-reported acceptance record. GUI and CLI both call the same class.

doctor, physical and packages are read-only adapters. They return unknown or
incomplete results rather than treating inaccessible paths or failed package
queries as success. The package adapter never executes a Windows deployment
operation or copies an encrypted package cache.

planner does not instantiate Engine or create a journal directory. It estimates
source content and file streams, combines destination and backup budgets per
volume, and records source-root identity. apply revalidates before creating a job.

## Independent-backup sequence

1. Upstream copy and hash checks finish before the original is renamed.
2. The original is retained as a uniquely named sibling.
3. A new independent directory is copied from that frozen original. The source,
   destination and archive trees cannot overlap the journal/tool.
4. Entire archive content (including named streams and links) is checked against
   the original manifest. Archive directory identity is pinned. Regular hard
   links to original or live files are rejected.
5. The user may reopen the application and create new data. Acceptance is recorded
   only by an explicit user operation.
6. Release checks the active root identity and junction, then verifies the complete
   independent archive and the frozen original. It never compares changing active
   contents with old contents as a reason to overwrite them.
7. Releasing is journaled before deletion. On resume, remaining old entries must be
   a subset of the old manifest. Added or changed entries stop deletion.
8. The independent archive remains after release. Rollback still refuses changed
   active data and is not offered after release has started.

This does not create an ACID filesystem snapshot or protect against adversarial
concurrent mutation. Stop writers during migration. Do not modify the retained
sibling, archive or journal. An unknown object created before an identity was
journaled is preserved for inspection.

## Actual failure cases captured by tests

- A directory handle prevents rename despite readable contents.
- A purported backup is a junction or hard link to live content.
- Cache/install paths retain logical C: spellings while physically on D:.
- The installed package and protected cache are already on the requested drive.
- File or named-stream content changes; rollback and unsafe cleanup must stop.
- New live application data survives independently backed cleanup.
- Archive copy and old-copy release are interrupted and resumed.
- JSON serialization is interrupted, or readers overlap a large UTF-8 publication.
- Destination and archive need combined space on the same volume.
- Both .db and .sqlite files, including WAL state, are checked in disposable copies.
- Read-only diagnosis reports access failures and scan caps without altering ACLs.
- Reviewed plans refuse replaced source roots and newly occupied destinations.

## Deliberately blocked in this version

No automatic SYSTEM broker, ownership transfer, service pause/resume, package move,
EFS decryption, cloud placeholder hydration or live whole-application migration.

A future privileged broker needs a reviewed allowlist, per-job authorization,
short lifetime, security-descriptor comparisons and dedicated system-level tests.
Adding those capabilities should not weaken the default user's access rules.

## Support information

Never upload authentication, chat databases or complete manifests to public issues.
Use doctor --redact for a starting summary and preview it before sharing.
