# Provider-neutral checkpoint and new-target restore runbook

## Purpose and authority boundary

This runbook covers DATA-10 recovery mechanics for the ledger database and the
immutable snapshot bytes referenced by that database. It produces canonical
`recovery-checkpoint-v1` and `recovery-restore-receipt-v1` evidence.

These records do **not** certify a source, authorize capture or publication,
enable frontend Official mode, change a runtime database locator, prove that
two provider accounts are independent, or prove a production RPO/RTO. The
current at-most-one-completed-cycle-loss objective is a target only. It becomes
an operating promise only after an accountable owner approves the cadence and
repeated provider drills demonstrate it.

The commands below use only caller-supplied SQLite paths or fixed PostgreSQL
environment variables. They never consult the application's configured
`DATABASE_URL`, initialize a database, create/drop a PostgreSQL database,
overwrite an output, use `pg_restore --clean`, or repair/reuse a failed target.

## What one checkpoint contains

One checkpoint binds all of the following to the exact immutable database
backup bytes:

- the latest unambiguous terminal scheduled cycle in the selected lane and a
  census of every terminal cycle in the database;
- the exact Alembic head, executable-schema digest, all 36 table denominators,
  typed row-set digests, and all seven append-only decision/event lineages;
- the relational backup archive and its independently read-back SHA-256;
- every retained `SourceSnapshot` raw-byte reference, including snapshots with
  no claim, plus immutable recovery copies verified by full SHA-256; and
- explicit authority ceilings and `external_evidence_required` provider and
  retention facts.

The canonical checkpoint is also published into the immutable recovery
artifact namespace. A retry may replay only exact bytes for the same trigger.
A competing or changed manifest fails; insertion order never chooses one.

## Preconditions

Before any checkpoint:

1. Use a current Alembic 0010 database with passing integrity, foreign-key,
   executable-schema, and lineage checks.
2. Supply the exact terminal `scheduled-cycle-v1` JSON already stored in that
   database. It must be the sole latest completed cycle in its lane.
3. Confirm that the primary object root contains every `raw_content_uri` named
   by retained `SourceSnapshot` rows.
4. Allocate a distinct recovery object root and a stable lowercase domain ID.
   Different local roots are test routing, not provider-independence proof.
5. Allocate a new output filename in an existing, non-symlink directory. The
   CLI creates it mode `0600` with create-exclusive/no-follow semantics before
   target work starts. Its resolved path must be outside every primary,
   recovery, and restore object root used by that command, and a receipt path
   must not alias the SQLite relational target. Rejection occurs before output
   reservation or target work.

For PostgreSQL, also require real PostgreSQL 16 `pg_dump` and `pg_restore` at
the reviewed fixed paths and allocate a new empty inspection database. The
connecting identity must own that database. It must be non-template, have one
empty `public` schema, have no other non-system schema, and have no database
comment. Network connections require verified TLS; a local disposable drill
may use an explicit Unix socket.

## Create a SQLite checkpoint

```bash
cd ledger
.venv/bin/benchmark-ledger recovery checkpoint-sqlite \
  --database-source /absolute/disposable/source.db \
  --trigger /absolute/evidence/terminal-cycle.json \
  --primary-root /absolute/private/primary-objects \
  --primary-domain-id primary-local \
  --recovery-root /absolute/private/recovery-objects \
  --recovery-domain-id recovery-local \
  --manifest-output /absolute/evidence/checkpoint.json
```

Use an explicit copy or authorized source path. Do not point this command at
`ledger/data/benchmark_ledger.db` during development or a rehearsal. The
source is opened read-only through SQLite's backup API; the command does not
use the configured application database.

On success, stdout contains only bounded JSON telemetry: checkpoint ID,
manifest digest, trigger cycle ID, object-reference count, and explicit false
authority facts. Paths and source bytes are not logged. The canonical manifest
is the durable evidence.

## Create a PostgreSQL checkpoint

Deliver connection URLs through the approved secret mechanism into exactly
these environment variables; never put a DSN or password in command arguments,
logs, issue text, or the manifest:

```bash
export LEDGER_RECOVERY_POSTGRESQL_SOURCE_URL='postgresql+psycopg://...'
export LEDGER_RECOVERY_POSTGRESQL_INSPECTION_URL='postgresql+psycopg://...'

cd ledger
.venv/bin/benchmark-ledger recovery checkpoint-postgresql \
  --trigger /absolute/evidence/terminal-cycle.json \
  --primary-root /absolute/private/primary-objects \
  --primary-domain-id primary-pg \
  --recovery-root /absolute/private/recovery-objects \
  --recovery-domain-id recovery-pg \
  --inspection-target-id inspection-20260716-001 \
  --manifest-output /absolute/evidence/checkpoint-pg.json
```

Checkpoint inspection restores the custom archive into the fresh inspection
database. Before `pg_restore`, a shared-catalog database comment permanently
binds that target ID and archive digest. An attempted or failed inspection
database is consumed forever. Allocate another database; do not clear its
comment, drop/recreate `public`, or reuse it.

The archive excludes owners, grants, ACLs, memberships, database definitions,
extensions, large objects, publications, and subscriptions. The restore path
applies only a literal `REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA public FROM
PUBLIC` safety floor. This is not role or access-control recovery evidence.

Source ACL/routing and `public` owner/ACL posture may be provider-managed and
therefore differ from a restore target; the archive does not claim to recover
them. The source must otherwise have the canonical supported database scope:
the stock procedural-language/extension baseline and no publications,
subscriptions, event triggers, large objects, database role settings,
foreign-data objects, default ACLs, security labels, transforms, user-defined
casts/access methods/rewrites, row-security policies, prepared transactions, or
logical slots. Any such fact makes the checkpoint incomplete and fails closed.

## Restore a SQLite checkpoint

The recovery root must contain the exact immutable checkpoint publication,
relational archive, and object copies. The database target must not exist. The
restore object root must be exactly empty or absent and have a regular existing
parent.

```bash
cd ledger
.venv/bin/benchmark-ledger recovery restore-sqlite \
  --checkpoint-manifest /absolute/evidence/checkpoint.json \
  --recovery-root /absolute/private/recovery-objects \
  --recovery-domain-id recovery-local \
  --restore-root /absolute/private/restored-objects \
  --restore-domain-id restore-local \
  --database-target /absolute/disposable/restored.db \
  --target-id restore-20260716-001 \
  --receipt-output /absolute/evidence/restore-receipt.json
```

The measured start is sampled before target-store inventory or relational
mutation. The finish is sampled only after schema/row/lineage/cycle comparison,
all object copies, read-back verification, and exact no-extra inventory pass.
Timestamps are canonical UTC seconds and `durationMs` derives from those exact
receipt values. This local measurement is not an accepted RTO.

## Restore a PostgreSQL checkpoint

Allocate a second new empty database; the inspection database used during
checkpoint creation is not a restore target.

```bash
export LEDGER_RECOVERY_POSTGRESQL_RESTORE_URL='postgresql+psycopg://...'

cd ledger
.venv/bin/benchmark-ledger recovery restore-postgresql \
  --checkpoint-manifest /absolute/evidence/checkpoint-pg.json \
  --recovery-root /absolute/private/recovery-objects \
  --recovery-domain-id recovery-pg \
  --restore-root /absolute/private/restored-objects \
  --restore-domain-id restore-pg \
  --target-id restore-20260716-001 \
  --receipt-output /absolute/evidence/restore-receipt-pg.json
```

The target is fenced by its own permanent shared database comment before
`pg_restore`. The restore uses a filtered TOC, `--schema=public`,
`--no-owner`, `--no-privileges`, `--single-transaction`, and
`--exit-on-error`; it never creates or drops a database. After restore, the
same strict catalog, schema, row, lineage, cycle, and object denominators are
recomputed from the new target.

Before that marker, immediately before `pg_restore`, and after restore, the
driver also requires the exact reviewed PG16 fresh-database scope: null
database ACL, connections allowed, connection limit `-1`, stock `public`
ownership/expanded ACL, the stock procedural-language/extension baseline, and
zero unsupported database-scoped facts listed above. Each canonical census is
SHA-256 bound into the semantic proof. A publication, event trigger, large
object, setting, or other contaminant therefore rejects the target before
archive mutation; retain it as a failed attempted target and allocate another.

## Validate retained evidence

Run the pure semantic validators and targeted tests:

```bash
cd ledger
.venv/bin/pytest -q \
  tests/test_recovery_foundations.py \
  tests/test_recovery_adversarial.py \
  tests/test_recovery_cli.py \
  tests/test_recovery_postgresql.py
```

The PostgreSQL target test skips unless all three explicit disposable test
URLs are supplied. CI provisions a fresh source, inspection target, and final
restore target; it must never point that test at a persistent or production
database.

The PostgreSQL adversarial gate uses three additional single-use disposable
URLs: one migrated source, one fresh target contaminated with a publication,
and one fresh target contaminated with a large object. It proves both targets
are rejected before marker or `pg_restore`, retain their contaminants, and
produce no success evidence. Those databases are never reused by the clean
integration drill.

For an operator drill, retain together:

- exact commit and tool/server versions;
- checkpoint and receipt files plus SHA-256 values;
- trigger cycle ID and scheduled time;
- redacted source/inspection/restore target IDs;
- start, finish, duration, object/table/cycle denominators;
- failure receipts/alerts and every permanently consumed target ID; and
- the external provider, retention, region, account, owner, and access-control
  evidence that the application contracts deliberately cannot assert.

Do not use a restore receipt as a frontend input. `cutoverAuthorized` remains
false, and changing a runtime locator requires a separate, governed rehearsal
and authorization.

## Failure and alert handling

Any error exits nonzero and emits bounded `failed_closed` JSON with a stable
reason code, phase, completed-object count, and whether a relational target may
exist. It never includes paths, DSNs, credentials, provider exception text, or
raw source bytes. No success receipt is emitted.

An empty or partial output file, immutable object copies, a SQLite target, or a
PostgreSQL consumed-target comment may remain. Preserve them for diagnosis.
Never delete, repair, overwrite, downgrade, clean, or retry into that target.
Allocate a new output path, restore object root, and relational target.

Alert at minimum on:

- missing checkpoint for a completed scheduled cycle;
- replay conflict or competing trigger publication;
- source/backup schema or lineage mismatch;
- missing, substituted, or extra object bytes;
- PostgreSQL tool timeout/failure or target already consumed;
- clock failure/non-monotonic duration after target mutation; and
- repeated drill duration or cycle-loss reconciliation outside approved
  thresholds once owners approve those thresholds.

Alerts and run receipts are operations evidence only. They cannot certify a
source or publish a claim.

## Production follow-on for Cloudflare

Before this local mechanism can support the selected Cloudflare architecture,
approve and prove all of the following separately:

- managed PostgreSQL provider, region, backup/PITR capability, owner, RTO,
  retention, and cost authority;
- private Cloudflare R2 source/recovery/restore account or bucket boundaries,
  object lock/lifecycle behavior, least-privilege identities, and independent
  full-byte restore;
- a private scheduled runner that emits one checkpoint for each completed
  collection cycle and alerts through an independent path;
- secrets/TLS/private-connectivity posture and reviewed role convergence after
  data restore; and
- repeated loss-of-primary drills that reconcile completed cycles and measure
  recovery time without authorizing cutover automatically.

Until those gates are approved and demonstrated, the manifest must continue to
say `maximumCompletedCyclesLost: 1` with `status: target_only_unproven`, and the
receipt must continue to say `rpoStatus: target_not_proven` and
`rtoStatus: target_not_proven`.
