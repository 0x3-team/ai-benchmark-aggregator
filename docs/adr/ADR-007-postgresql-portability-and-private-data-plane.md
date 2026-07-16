# ADR-007: PostgreSQL portability and private ledger data plane

**Status:** Accepted for provider-neutral implementation; provider provisioning remains blocked by P0-02/P0-03  
**Date:** 2026-07-14; implementation evidence updated 2026-07-15  
**Decision ID:** DEC-007

## Context

The durable ledger currently runs on local SQLite plus a local content-addressed
snapshot root. That is a useful containment baseline, not a PostgreSQL service
with a different connection string. The public SPA remains static and must not
receive a database, object-store, runner, or service-role credential.

Repository review identified these portability seams:

| Current seam | SQLite-specific behavior | PostgreSQL-safe replacement required |
| --- | --- | --- |
| Migration service | SQLite still uses backup, staged sibling files, `PRAGMA integrity_check`, `PRAGMA foreign_key_check`, and atomic replacement of a disposable copy. PostgreSQL now has separate strict status/empty-init/known-revision upgrade paths under a session advisory lock. | Provider-approved backup/export, new-target restore, count/digest comparison, and cutover authority remain separate gates. A PostgreSQL URL is never treated as a file or routed through SQLite copy migration. |
| Engine setup | SQLite installs `PRAGMA foreign_keys=ON` and uses `check_same_thread=False`. | PostgreSQL uses native foreign keys, explicit transaction/isolation settings, TLS/auth configuration, and narrowly scoped connection pools. No browser connection is allowed. |
| Alembic | Batch rendering and SQLite `RAISE(ABORT, ...)` triggers remain SQLite-only. | One forward-only lineage now branches by dialect and installs PostgreSQL-native trigger functions with `RAISE EXCEPTION`; real PostgreSQL tests exercise fresh and populated upgrade paths. |
| JSON columns/defaults | SQLite retains its current JSON/text representation. | PostgreSQL head converts governed document columns to JSONB and absolute timestamps to TIMESTAMPTZ with legacy wall-clock values interpreted explicitly as UTC; ORM variants match those physical types. |
| Append-only guarantees | SQLite triggers prevent updates/deletes to evidence rows and enforce source/snapshot identity. | Reproduce every trigger invariant in PostgreSQL, then layer least-privilege roles on top. Application checks and row-level policy are not substitutes for append-only database constraints. |
| Revision creation | Repository code derives source `revision_ordinal` with `MAX(...) + 1`; SQLite's current use is effectively local/serialized. | Lock the logical source row (`SELECT … FOR UPDATE`) or use an equally auditable per-source serialization mechanism before assigning the next ordinal; retain the unique constraint and add concurrent-writer tests. |
| Snapshot/artifact storage | `LocalSnapshotStorage` relies on local filesystem paths, fsync, no-replace publication, and SHA-256 re-verification. | Introduce a private object-store interface with full-digest addressing, conditional/no-replace write semantics, integrity re-read, retention/lifecycle rules, access logging, and independent restore tests. |

The ledger's immutable semantics are non-negotiable: raw claims and snapshots
are not overwritten; source, review, publication, and release decisions remain
append-only; a correction makes a new decision/artifact rather than changing
historical evidence.

## Decision

1. The production target is PostgreSQL behind a private control plane. Supabase
   is a candidate managed provider, not a selected provider or authorization to
   provision it. Cloudflare D1 is not the default target.
2. The public delivery plane remains a static Vite site. It consumes at most a
   governed immutable release artifact and never queries mutable ledger tables.
3. PostgreSQL support will be implemented as a tested port, not a fallback.
   Every revision and invariant must run on a disposable real PostgreSQL
   instance before a durable database is moved.
4. The Alembic migration history remains versioned and forward-only. A future
   revision may contain reviewed dialect branches; no downgrade/delete path is
   introduced as recovery.
5. PostgreSQL roles are separate at minimum for: schema migrator, ingestion
   runner, reviewer/publisher, artifact builder, and read-only audit. The
   browser gets none of them. Privilege grants must make unsafe writes fail in
   addition to trigger/constraint enforcement.
6. A SQLite-to-PostgreSQL move is a copy-only rehearsal: retain the verified
   SQLite backup, create a new PostgreSQL target, compare rows/digests/foreign
   keys/append-only invariants, and keep the old database read-only until a
   separately authorized cutover. No original evidence file is replaced.
7. Snapshot/artifact bytes are a separate recovery domain from the database.
   A database restore is not accepted until the referenced immutable bytes
   re-resolve by digest under the approved access policy.

## Required proof before provider work

- The accountable owner selects provider, region, cost authority, retention,
  RPO/RTO, and the private runner architecture (P0-02 through P0-04).
- A disposable PostgreSQL test environment runs fresh install and upgrade from
  every supported ledger revision. It includes negative tests for raw evidence
  updates/deletes, source-revision mismatch, stale review/publication paths,
  duplicate claim identity, and concurrent revision allocation.
- The PostgreSQL trigger functions are inspected alongside their SQLite
  counterparts and are tested using a role that attempts direct SQL bypasses.
- Object storage proves full-digest write/read, tamper/missing-object failure,
  access isolation, retention behavior, and independent restore evidence.
- A dated copy-only rehearsal records source backup/artifact digests, target
  counts, constraint results, elapsed restore time, owner, and a rollback to
  the old read-only system.

## Provider-neutral implementation evidence — 2026-07-15

- A disposable, Unix-socket-only PostgreSQL 16.14 target passed fresh-head and
  populated `0001`-to-head upgrades, exact expected-revision/stale-revision
  behavior, and strict executable-schema inventory. The latter binds table
  kind/persistence/RLS/rule/owner posture; constraint table/definition/state
  and backing-index usability; required index validity/readiness/liveness;
  exact enabled trigger bindings; reviewed function bodies, signatures,
  security posture, and owners; and column type/nullability/default/generated/
  identity state. Direct drift and bypass attempts, concurrent decision-chain
  contention, and five separated role probes fail closed.
- The migration harness is gated by an explicit disposable database name and
  reset acknowledgement. CI now supplies a digest-pinned PostgreSQL 16.14
  service so PostgreSQL tests do not silently degrade to SQLite-only proof.
- Local and injected R2-compatible storage implement full-SHA-256 addressing,
  conditional no-overwrite, full-byte/metadata read-back, deterministic typed
  receipts with factory-only construction and canonical receipt identities,
  exact provider-page/orphan accounting, and runner/admin capability
  separation.
- Real R2 bucket locks, token scopes, retention, SDK compatibility, provider
  PostgreSQL TLS/pooling/limits, backup restore, and failure-domain separation
  remain unproven external gates. Local fake-client tests are not provider
  evidence.
- The quarantined legacy SQLite database was not migrated, repaired, or opened
  for write during this work.

## Consequences

- `init-db` accepts only an empty SQLite or PostgreSQL target. `db status` and
  `db preflight` inspect both dialects; `db migrate` remains the SQLite
  disposable-copy path; `db upgrade-postgresql --expected-revision ...` is the
  separate explicit in-place PostgreSQL path and requires recovery evidence
  outside the command.
- The reviewed role renderer is declarative for runtime grants: it removes
  stale grants, transfers ledger relations/functions to one migrator owner,
  normalizes five distinct `NOLOGIN NOINHERIT NOBYPASSRLS` groups, and fails on
  pre-existing memberships or runtime-role ownership of the database/schema/
  ledger objects. PostgreSQL FK key-share compatibility grants only
  `UPDATE(id)` on referenced roots, whose identities are trigger-immutable.
  Managed login assignment and explicit `SET ROLE` remain operator actions;
  they are not inferred from a connection string.
- No database migration, storage provisioning, backup drill, or scheduled
  runner is performed by this decision record.
- Official mode remains unavailable. A successful PostgreSQL port is necessary
  but not sufficient for source certification, release-artifact publication,
  or frontend activation.
