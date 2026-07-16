# Official publication and evidence-preservation runbook

**Status:** Containment procedure — Official publication disabled  
**Applies to:** local SQLite ledger databases, snapshot roots, and candidate frontend exports  
**Authority:** an authorized operator and independent reviewer must approve any migration rehearsal.

## Do not run these commands against a claim-bearing ledger

Until the migration and deterministic-feed gates are complete, do not run:

- `benchmark-ledger ingest`, including `--dry-run`;
- `benchmark-ledger review auto-verify-matched`;
- `benchmark-ledger export-official-json`;
- any legacy version of `benchmark-ledger seed-registry` that deletes records;
- `init-db` as if it were a schema migration.

Do not invoke raw `alembic` without an explicit disposable `DATABASE_URL`.
The migration environment refuses an implicit URL so a rehearsal cannot fall
through to the configured default ledger.

The current containment CLI blocks the first three. A historical `--dry-run` is
not evidence-preserving by itself: older runner code could create an ingestion
run and snapshot bytes before its dry-run branch. No live source fetch belongs
in CI or a migration preflight.

`benchmark-ledger reports legacy-inventory` is the exception: it is a
read-only, offline reconciliation view. It prints deterministic JSON to stdout
and makes no decision or evidence change. It may be run against a verified
copy to account for all historical claims/snapshots and explain report-only
candidate omissions. It does **not** make that copy publishable or authorize a
production migration/cutover.

`benchmark-ledger coverage status --format json|markdown` is a second
read-only exception. It inventories executable registry configuration and may
report an invalid or absent SQLite target as quarantined evidence; unlike a
migration preflight, that invalidity is expected report content rather than a
reason to open the database through the ORM. A valid report with blockers exits
`1`. This includes the checked-in Coverage Universe's explicit
`draft_unapproved` state; only a separate accountable-owner decision may approve
a future revision. `ready` would mean only that census reconciliation passed;
freshness stays `not_assessed` until a separate scheduled-cycle receipt applies
the threshold at a pinned cycle/as-of value. The command does not fetch, seed, initialize, migrate,
repair, read snapshot bytes, or create source/claim/decision/publication state,
and its output must never be used as a frontend artifact.

New snapshot storage is full-SHA-256 content addressed and verifies persisted
bytes before reuse. A safely root-contained historic path is verified in place.
If an artifact is missing, linked, or hash-mismatched, stop and preserve it for
investigation; do not overwrite it to make a snapshot row appear valid.

## Read-only preflight inventory

Before a future migration, create a JSON manifest outside the ledger data root.
The manifest must include:

1. UTC timestamp, operator, repository commit, and complete `git status --short`. Do not reset, clean, or discard a dirty worktree.
2. A redacted database locator/type, schema/tool version, and snapshot-root locator.
3. SHA-256 and size for the database file(s), every snapshot file, and each candidate export/manifest.
4. Row counts by source and status for sources, snapshots, claims, validations, and ingestion runs; plus the source-registry file hash.
5. Snapshot file count/total size plus an orphan/missing-reference report.
6. SQLite integrity and foreign-key results from a read-only opened copy.
7. The exact candidate migration version and its planned input/output artifact identifiers.

For a current, copied ledger, retain the LDR-09 report beside that manifest:

```bash
benchmark-ledger reports legacy-inventory > /separate/verified-reports/legacy-inventory.json
```

The command itself only writes stdout; the shell redirection is an explicit
operator choice. Verify the report's canonical manifest digest on repeat runs.
Treat `candidate`, `omitted`, and `conflicted` as report-only explanations—not
new claim statuses. A non-empty `conflicts` list keeps the strict candidate
projection blocked; do not hand-pick a row in the report.

Use a copy of the database for integrity checks and all rehearsal work. The
inventory command must never open the production database in a writable mode,
write snapshot files, or call network adapters. Record a separate receipt if a
future inventory helper is added; it is not part of this containment change.

## Implemented SQLite copy-only migration helper

The CLI now provides an evidence-preserving migration rehearsal path. First,
run its read-only inspection against the candidate:

```bash
benchmark-ledger db status
benchmark-ledger db preflight
```

Only if preflight reports `legacy_unversioned` or a known
`versioned_but_not_head` revision with `integrity_ok: true` and no foreign-key
violations, set `DATABASE_URL` to a separately created disposable copy and run:

```bash
benchmark-ledger db migrate --backup-dir /separate/verified-backups
```

It creates the backup through SQLite's backup API, migrates a staged sibling,
performs postflight integrity checks, and only then atomically replaces the
supplied copy. Unknown, malformed, or FK-broken databases fail closed. This
command does not authorize a production cutover.

PostgreSQL uses a separate empty-init/strict-preflight/expected-revision path;
it never routes through this SQLite file replacement. The provider-neutral
commands, disposable target harness, five-role contract, and real R2 evidence
gates are documented in the
[PostgreSQL and object-storage rehearsal runbook](provider-neutral-postgresql-and-object-storage-rehearsal.md).

## Backup, rehearsal, and stop conditions

1. Create two independently stored copies of the source database, snapshot root, and inventory manifest.
2. Verify every hash, then restore one copy into a disposable location.
3. Run a candidate migration only against that restored copy.
4. Re-run the inventory. Historic claims, snapshots, and runs must remain queryable; additions must be attributable to a new migration or claim event.
5. Have an independent reviewer compare manifests before any production cutover.

Stop immediately if any hash is missing, integrity/foreign-key validation fails,
claim or snapshot counts fall, a source is unexpectedly reclassified, or a
supposed dry run mutates state. Do not use destructive reseeding or a downgrade
to repair immutable evidence. Restore the verified pre-migration backup and
keep Official publication unavailable.

## Release-artifact rule

A local build with `export.from-ledger.json` does not demonstrate a reproducible
Official release. A future release must instead use an approved, content-hashed
artifact plus provenance manifest and pass a fresh `git archive HEAD` build.
Until then, the tracked unavailable fixture is the only frontend Official input.
