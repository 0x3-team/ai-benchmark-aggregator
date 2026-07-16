# Provider-neutral PostgreSQL and immutable object-storage rehearsal

**Status:** local/disposable implementation proof only  
**Last updated:** 2026-07-15  
**Applies to:** DATA-07 and DATA-08 foundations; DATA-09 extends the relational head  

This runbook does not authorize a managed database, Cloudflare R2 bucket,
credential, deployment, source fetch, ingestion, publication, or paid
operation. It explains the provider-neutral proofs that may run locally and
the additional evidence a later authorized provider candidate must produce.

## Containment first

- Never point these commands at `ledger/data/benchmark_ledger.db` or migrate
  that quarantined file merely because PostgreSQL support exists.
- Use a PostgreSQL database whose name visibly contains `test`, `disposable`,
  or `phase2a`. The test harness refuses other names.
- Keep PostgreSQL local/socket-only when rehearsing locally. Do not put a test
  password, R2 credential, provider DSN, or TLS key in a command transcript,
  issue, receipt, or committed file.
- The public frontend receives no database or object-store credential and
  continues to consume only the tracked unavailable Official artifact.

## PostgreSQL local proof

The persistent target test deliberately drops and recreates only its `public`
schema. Both variables are required:

```bash
export TEST_POSTGRESQL_URL='postgresql+psycopg://USER@/benchmark_disposable_phase2b?host=/absolute/socket&port=PORT'
export TEST_POSTGRESQL_ALLOW_RESET=1
cd ledger
.venv/bin/pytest -q \
  tests/test_postgresql_portability.py \
  tests/test_operational_persistence_postgresql.py
```

The suite must prove all of the following on a real PostgreSQL target:

1. Fresh empty schema to Alembic head.
2. Populated legacy `0001` rows to head without changing raw claim lexemes.
3. Exact expected-revision upgrade and stale-revision refusal under the
   session advisory lock.
4. Exact head table kind/persistence/RLS/rule/owner posture; constraint owning
   table, definition, validation/deferrability, and backing-index usability;
   required index signature/validity/readiness/liveness; enabled user-trigger
   bindings and normally enabled internal FK RI triggers; reviewed function
   body/signature/security/owner; column types,
   nullability, defaults, generated/identity state; JSONB; and TIMESTAMPTZ.
5. Direct raw update/delete, source mismatch, branched decision, stale
   certification, and duplicate-chain bypass rejection.
6. One-commit/one-rejection behavior for concurrent decision successors.
7. Five distinct `NOLOGIN NOINHERIT NOBYPASSRLS` capability groups: migrator, ingestion, governance,
   artifact builder, and audit. Ingestion cannot govern; governance cannot
   create claims; artifact and audit identities cannot write. Reapplying the
   contract removes stale runtime grants; duplicate names, pre-existing role
   memberships, and runtime-role ownership fail closed. Only the migrator owns
   ledger relations/functions and can alter them.
8. Wrong `search_path`, forged Alembic head, relocated/missing constraint,
   disabled/reordered/extra trigger, changed function body/owner, fixed audit
   default, nullable raw field, unlogged evidence table, forced RLS, and an
   invalid/unready/dead operational index all report `invalid`, never
   `current`.
9. Cleanup leaves no public tables or temporary test roles.

CI runs the same target tests against the digest-pinned PostgreSQL service in
`.github/workflows/verify.yml`; an unset local target may skip, but CI must not.

For an authorized, populated PostgreSQL candidate, first retain independent
backup/recovery evidence and run read-only preflight. Then use the exact
observed revision:

```bash
benchmark-ledger db preflight
benchmark-ledger db upgrade-postgresql \
  --expected-revision '<exact revision reported by db status>'
```

The command is an in-place forward migration under a lock. It is not a backup,
SQLite import, restore drill, provider cutover, or permission to use a durable
target. A failed run emits no success receipt; restore uses the independently
verified recovery copy, never downgrade/delete.

The first bootstrap to the role-contract head runs under the reviewed schema
owner because the NOLOGIN migrator group does not yet exist. Immediately after
that bootstrap, execute the reviewed role SQL as the role administrator, then
assign separately managed login identities. Every later schema evolution must
use a direct/session-pooled connection and explicitly `SET ROLE` to the
migrator owner. The role contract intentionally fails if any managed group has
an existing membership; review/revoke assignments before convergence, reapply
the contract, then restore only the approved login-to-group assignments. Never
collapse two capability groups to one identifier.

The operational extension at `0010_operational_persistence` is rehearsed in
the [DATA-09/CFG-01 runbook](operational-persistence-and-runtime-composition-rehearsal.md).
It adds durable operational evidence and guarded leases, not a scheduler,
provider, live source, notification-delivery, publication, or Official-mode
activation.

DATA-10's implemented local/disposable checkpoint, immutable object-copy, and
new-target restore workflow is specified separately in the
[provider-neutral recovery runbook](provider-neutral-recovery-checkpoint-and-restore.md)
and [ADR-010](../adr/ADR-010-provider-neutral-recovery-evidence.md). Those
receipts retain `external_evidence_required` and `target_not_proven`; they do
not satisfy the real-provider evidence below.

## Immutable storage local proof

Run the provider-neutral contract and adapters without credentials:

```bash
cd ledger
.venv/bin/pytest -q \
  tests/test_storage_contracts.py \
  tests/test_snapshot_storage.py \
  tests/test_r2_storage.py
```

These tests prove application behavior only: full-SHA-256 snapshot/artifact
keys, local atomic no-replace, R2-compatible `IfNoneMatch: *`, deterministic
byte-free factory-only receipts with self-validated IDs, full-byte and metadata
read-back, missing/tamper/collision failure, pagination cursor and `KeyCount`
consistency, exact orphan/present/missing denominators, and the absence of
delete/retention administration from the runner protocol.

The injected fake client is not Cloudflare evidence. Every application receipt
therefore reports provider retention evidence as
`external_evidence_required`.

## Required real R2 candidate evidence

After explicit account/cost/region/retention authority, capture redacted,
dated receipts for one disposable bucket:

1. Exact account, bucket, jurisdiction/region choice, and approved retention
   window; no secret values.
2. A bucket-lock rule applied before evidence upload, plus a negative
   overwrite/delete test showing retained bytes cannot be changed even if a
   credential or SDK attempts it.
3. Separate administrator and runner identities. The injected runner surface
   remains object put/get/list only and cannot change locks, lifecycle,
   credentials, or bucket policy.
4. A real SDK/client call proving wildcard conditional upload behavior,
   unambiguous HTTP 412 reuse, full read-back SHA-256, exact user metadata, and
   multi-page listing.
5. Tamper/substitution/missing-object and malformed-pagination failure receipts
   without logging object bytes or credentials.
6. An independently restorable copy in a separate failure domain and a new-
   target restore that re-resolves every database-referenced digest. This is a
   later DATA-10 gate, not satisfied by a bucket-lock screenshot.

## Required managed PostgreSQL candidate evidence

- Direct or session-pooled connection for migrations/backups; measured bounded
  runtime pooling. If a transaction pooler is selected, disable named prepared
  statements and prove the exact driver configuration.
- TLS verification against the provider CA, secret-manager injection, redacted
  connection receipts, and no browser/public-worker access.
- Role grants reproduced from the reviewed five-role contract and negative
  `SET ROLE` probes under the actual provider identities. Record relation and
  function ownership, role attributes, memberships, and schema/database owner;
  a successful grant statement alone is not separation proof.
- Measured connection, storage, egress, backup, and free-tier limits with stop
  thresholds. A free plan is not a recovery guarantee.
- Per-cycle export/backup, independently retained copy, and timed new-target
  restore meeting the approved loss of at most one completed collection cycle.

## Stop conditions

Stop and preserve evidence if a raw value changes, a required constraint or
object is missing, a role crosses its capability boundary, a receipt contains
bytes/secrets, provider retention cannot be proven, a quota approaches its
approved threshold, or cleanup cannot account for every disposable resource.
Do not weaken a trigger, choose a duplicate by row order, repair the quarantined
ledger, or enable Official mode to make a rehearsal pass.
