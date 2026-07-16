# ADR-006: Versioned, evidence-preserving ledger migrations

**Status:** Accepted  
**Date:** 2026-07-13  
**Decision ID:** DEC-006

## Context

The original ledger initialized its schema with `Base.metadata.create_all()`.
That is suitable for an empty disposable database, but it cannot record or
validate an evolution of an existing claim-bearing SQLite file. The current
schema also stored source configuration in a mutable logical source row and
represented review/publication state in mutable claim fields.

## Decision

1. Use Alembic for durable ledger schema versions. The initial chain is a
   hand-authored legacy baseline, source/review/publication history, then
   snapshot-to-source-revision identity.
2. `benchmark-ledger init-db` initializes only an empty database through that
   chain. It refuses populated unversioned, partial, invalid, or non-head
   databases rather than applying a guessed migration.
3. A legacy SQLite database or known older ledger revision may be rehearsed
   only through `benchmark-ledger db preflight` and `benchmark-ledger db
   migrate --backup-dir …` on a verified disposable copy. Preflight is
   read-only; migration uses SQLite's backup API, upgrades a staged sibling,
   validates `integrity_check` and foreign keys, and atomically replaces the
   supplied copy only after success.
4. Source configuration now has a stable logical source plus an immutable
   source revision. Snapshots bind the exact source revision. Existing evidence
   is backfilled with `legacy_backfill` revisions and append-only
   `legacy_unassessed` quarantine decisions; raw claim values are not rewritten.
5. Source-revision, snapshot, review-decision, and publication-decision tables
   are append-only. SQLite triggers block their update/delete operations and
   block raw evidence changes or deletion on legacy result claims. New claims
   carry the source-revision decision that admitted their snapshot and an
   immutable raw evaluation-version field; a database trigger rejects a future
   claim whose decision is absent or belongs to another source revision.
   During containment, repository APIs can append only quarantined/revoked
   source and publication decisions; they cannot certify or approve an
   Official result.
6. Downgrades are deliberately refused. Recovery is restoration of the
   verified pre-migration backup, never a schema/data rollback that could erase
   evidence.
7. New local snapshot artifacts are full-SHA-256 content-addressed objects.
   Their completed bytes are fsynced and published without replacement; an
   existing object and every database-row reuse must hash to the recorded full
   digest. A missing, linked, or mismatched artifact fails closed and is not
   overwritten or rewritten as a repair.

## Consequences

- `Base.metadata.create_all()` is no longer the application migration path.
- Registry source IDs must be unique. A complete CLI manifest reconciles a
  changed source by appending a quarantined revision, and reconciles a removed
  registry-managed source by appending a revoked retirement revision; it never
  rewrites evidence or disables foreign keys.
- SQLite administrative access can always alter a local file; that authority is
  outside the application-level immutability boundary and cannot itself confer
  source certification or publication approval.
- Historic snapshot rows and files retain their URI and bytes. A safely
  root-contained legacy path may be re-verified in place; an artifact that
  cannot verify against its recorded hash blocks ingestion rather than being
  mutated to make the historical evidence appear healthy.
- A source-revision decision is necessary but not sufficient for ingestion:
  central admission also requires a certified typed evidence policy, one
  verbatim approved fetch artifact, exact raw-record resolution, declared
  dimensions, finite numeric semantics, and ambiguity-safe model matching.
- Official mode remains unavailable. This ADR establishes durability seams; it
  does not authorize ingestion, export, live-source access, or a release.
