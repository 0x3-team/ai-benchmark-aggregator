# benchmark-ledger

Official benchmark result capture system (CLI-first). Captures immutable source-backed claims from official sources. Does **not** run evaluations or recalculate scores.

## Setup

```bash
cd ledger
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

## Safe local setup

```bash
benchmark-ledger init-db
benchmark-ledger seed-registry
benchmark-ledger claims list
benchmark-ledger review queue
pytest -q
```

With the default `DATABASE_URL=sqlite:///./data/benchmark_ledger.db`,
`init-db` creates at most the one missing direct `data/` parent under the
existing `ledger/` directory, then applies the versioned migrations to a fresh
SQLite file. It is idempotent at the migration head, refuses populated
unversioned or otherwise unsupported databases, and never upgrades an existing
claim-bearing database. `ingest` does not initialize or migrate a database;
run `init-db` first and confirm the database is current.

This is only for a new, disposable local database. Official publication is
currently disabled: `ingest`, including `--dry-run`, bulk auto-verification,
and `export-official-json` are not operational workflows during remediation.
`seed-registry` is never a reset: it appends source revisions and retirement
decisions while retaining claims, snapshots, and runs. Read the
[evidence-preservation runbook](../docs/runbooks/official-publication-and-evidence-preservation.md)
before any migration work.

The current contained routes require and authorize no source credentials. The
central safe-fetch client also defaults to **no outbound network transport**.
It requires a source-revision-bound plan and a future reviewed private-runner
transport that can prove egress/peer controls. Do not restore adapter-local
HTTP, redirects, URL rewriting, or source credentials to make a source run.
See the [safe-fetch runbook](../docs/runbooks/source-certification-and-safe-fetch.md).

CI uses the exact reviewed Python 3.11 constraints in
[`requirements-ci.lock`](requirements-ci.lock). They are intentionally updated
only through a reviewed dependency-change PR; they do not authorize a provider,
source, or Official release.

`benchmark-ledger review map-model CLAIM_ID MODEL_ENTITY_ID` is the one
available manual correction command. It appends an `identity_resolved` review
decision (with its actor and raw model name); it does **not** rewrite the
captured claim, mark a validation passed, change `capture_status`, or make a
claim publishable. `review auto-verify-matched` and
`review mark-human-verified` intentionally fail closed.

## Read-only coverage baseline

The bounded Coverage Universe and deterministic census replace ad hoc source,
benchmark, and model counting:

```bash
benchmark-ledger coverage status --format json
benchmark-ledger coverage status --format markdown
```

Both formats come from the same canonical payload and write only to stdout.
The command reads every raw row in `benchmarks*.yaml`, `models*.yaml`, and
`official_sources.yaml`, retains duplicate/collision facts instead of choosing
by file or row order, and reports the configured SQLite target as quarantined
evidence. It may inspect a current or invalid file-backed SQLite database in
read-only mode; a missing path stays missing. It never initializes, migrates,
repairs, seeds, fetches, creates a claim/decision, or reads snapshot bytes.

Exit `0` means the bounded baseline has no blocking issue, exit `1` means a
valid complete report was emitted with blockers, and exit `2` means an input or
report contract was invalid. `active`, `configured`, `in_scope`, and
`discovered` are inventory facts only—not certification or publication. The
Coverage Universe is the explicit product boundary rather than a claim to have
found every benchmark on the internet. Its checked-in revision remains
`draft_unapproved`; the report binds that state to a blocking issue until an
external accountable-owner decision creates an approved revision. The
`summary.statusCounts` ladder is source-route-scoped: `known` accounts for
unique bounded configured routes, while zeroes in later states mean
`not_assessed` in this baseline—not zero certified or published sources.
Freshness is also `not_assessed`: the pure manifest/census path has no wall
clock, and a future scheduled-cycle receipt must bind the deterministic slot or
as-of value used to apply the staleness threshold.

The immutable scope is
[`app/registry/coverage_universe.yaml`](app/registry/coverage_universe.yaml).
Versioned contracts are
[`coverage-universe-v1`](../docs/contracts/coverage-universe-v1.schema.json),
[`coverage-census-v1`](../docs/contracts/coverage-census-v1.schema.json),
[`discovery-target-v1`](../docs/contracts/discovery-target-v1.schema.json), and
[`discovery-candidate-v1`](../docs/contracts/discovery-candidate-v1.schema.json).
None is a release artifact or frontend input.

## Continuous-operations contracts and inert persistence

Phase 0/1 wire contracts now describe the records a future automated service
must produce for source checks, immutable benchmark editions, typed evaluated
systems, append-only identity decisions, deterministic UTC cycles/jobs,
leases/fencing, incidents, review work, and notification intent/receipt chains.
They have pure standard-library semantic validators and synthetic examples.
The forward-only `0010_operational_persistence` revision now provides durable
cycle/job intent and completion, attempts, guarded leases/fencing,
source-contract/check/extraction evidence, discovery and identity facts,
incident/work histories, and notification outbox/receipt records on fresh or
explicitly disposable targets. Operational history is append-only; the sole
mutable coordination projection is the guarded current job lease.
The supplied recheck composition validators additionally require one
deterministic receipt per attempt and exact slot, source, job, attempt, fencing,
terminal, execution, snapshot, incident-denominator, and output-digest
agreement. Persistence resolves those identities to exact immutable records;
unsupported terminal referent types fail closed instead of accepting opaque
IDs. A source attempt and its receipt commit atomically through the reviewed
deferred-reference posture, and accepted-current work is checked against both
an injected trusted clock and database time.

See the [contract catalog](../docs/contracts/README.md),
[ADR-008](../docs/adr/ADR-008-continuous-collection-contract-boundaries.md),
the [contract rehearsal](../docs/runbooks/continuous-discovery-recheck-contract-rehearsal.md),
[ADR-009](../docs/adr/ADR-009-operational-persistence-and-inert-runtime-composition.md),
and the [persistence/runtime rehearsal](../docs/runbooks/operational-persistence-and-runtime-composition-rehearsal.md).
Runtime eligibility must later resolve exact effective owner/certification
decisions and contract digests at the scheduled slot. A valid contract fixture
is not a source certification, claim, incident acknowledgement, notification
delivery, publication approval, or Official artifact.

`RuntimeDependencies` is the single ingestion composition root for transport,
storage, clock, scheduler repository, incident service, and rate limiter.
Defaults are disabled or no-op, side-effecting products require explicit
code-level capabilities, adapters do not own HTTP, and dry-run touches none of
those dependencies or an ingestion-run row. This is not an active scheduler,
discovery controller, recheck service, watchdog, delivery adapter, or provider
configuration. Live source access, external alerts, source/identity authority,
publication, and Official mode remain blocked.

## Provider-neutral recovery evidence

DATA-10 adds immutable per-cycle checkpoints spanning both the relational
ledger and every retained `SourceSnapshot` byte, plus new-target-only restore
receipts. SQLite uses the standard backup API. PostgreSQL uses fixed real
PostgreSQL 16 custom-archive tools, a separate fresh inspection database, and a
second fresh final target. Both paths recompute exact schema/table/row/lineage,
cycle, and object denominators before emitting success.

```bash
benchmark-ledger recovery --help
benchmark-ledger recovery checkpoint-sqlite --help
benchmark-ledger recovery restore-sqlite --help
benchmark-ledger recovery checkpoint-postgresql --help
benchmark-ledger recovery restore-postgresql --help
```

All database and object paths are explicit. These commands never consult the
configured `DATABASE_URL`, overwrite an evidence file, clean/reset a target,
or authorize runtime cutover. PostgreSQL DSNs are read only from the fixed
`LEDGER_RECOVERY_POSTGRESQL_SOURCE_URL`,
`LEDGER_RECOVERY_POSTGRESQL_INSPECTION_URL`, and
`LEDGER_RECOVERY_POSTGRESQL_RESTORE_URL` environments; they are never accepted
on argv or written to a receipt. Failures retain partial state and emit no
success receipt. A PostgreSQL target is permanently consumed by a
shared-catalog comment before restore and must never be reused.

Manifest and receipt paths must resolve outside all primary, recovery, and
restore object roots named by the command; a SQLite receipt cannot reuse the
database target path. The CLI rejects those relationships before reserving an
output or invoking recovery work.

PostgreSQL freshness is a canonical database-scope census as well as a strict
`public` schema census. Fresh targets must match the reviewed stock PG16
database/public-schema posture and contain no unsupported database-scoped
publications, subscriptions, event triggers, large objects, role settings,
foreign-data objects, default ACLs, labels, policies, prepared transactions, or
logical slots. The driver checks the census before its permanent marker,
immediately before `pg_restore`, and after restore. Provider-managed source
database ACL/routing and `public` owner/ACL posture are deliberate nonclaims;
other unsupported source database-scoped facts fail closed.

The desired loss of at most one completed collection cycle remains
`target_only_unproven`. A local measured restore duration is not an accepted
RTO, different local roots are not provider-independence evidence, and the
custom archive deliberately does not restore roles, owners, grants, or ACLs.
See [ADR-010](../docs/adr/ADR-010-provider-neutral-recovery-evidence.md) and the
[checkpoint/restore runbook](../docs/runbooks/provider-neutral-recovery-checkpoint-and-restore.md).

## Read-only legacy reconciliation

To explain what the strict LDR-08 candidate projection would omit without
changing evidence, run the read-only report command against an existing ledger:

```bash
benchmark-ledger reports legacy-inventory
```

It writes canonical JSON to stdout only. It inventories every historical claim
and snapshot (including unreferenced snapshots), labels each claim as a
report-only `candidate`, `omitted`, or `conflicted`, and lists stable omission
reasons, decision references, evidence hashes, and observed legacy risk
signals. It never creates an approval, quarantines a row in place, selects a
conflict winner, fetches a source, reads snapshot bytes, or re-enables
`export-official-json`/frontend Official mode.

For a copied-DB rehearsal, an operator may redirect stdout to a separately
managed report location and compare its SHA-256 manifest across runs. Do not
write a report into the snapshot root or use it as a frontend artifact. The
contract is [`docs/contracts/legacy-inventory-v1.schema.json`](../docs/contracts/legacy-inventory-v1.schema.json).

## Migration rehearsal and PostgreSQL portability

Schema changes are versioned with Alembic. `init-db` creates only an empty
database; it intentionally refuses a populated unversioned ledger. To inspect
a candidate without writing it:

```bash
benchmark-ledger db status
benchmark-ledger db preflight
```

Only after the preservation runbook has been followed, point `DATABASE_URL` at
a verified **disposable copy**, never the evidence original, and run:

```bash
benchmark-ledger db migrate --backup-dir /safe/separate/backup-directory
```

The command creates a SQLite backup, migrates a staged sibling, validates
integrity/foreign keys, then atomically replaces that supplied copy. It accepts
the exact legacy baseline or a known older ledger revision—not an unknown or
malformed schema. There is no downgrade command: restore the verified backup
if a rehearsal fails. Do not invoke raw `alembic` against the default database;
it requires an explicit `DATABASE_URL` for a disposable target.

PostgreSQL is a separate path; it is never treated as a SQLite file and the
quarantined SQLite ledger is never migrated merely because PostgreSQL support
exists. `init-db` accepts an empty PostgreSQL schema. A populated known revision
requires an exact read-only preflight followed by the explicit command below,
after independent backup/recovery evidence has been retained:

```bash
benchmark-ledger db preflight
benchmark-ledger db upgrade-postgresql \
  --expected-revision '<exact revision reported by db status>'
```

The PostgreSQL path takes a session advisory lock, refuses an unknown or stale expected
revision, and validates executable head state—not just object names. It binds
table persistence/RLS/rules/ownership, constraint placement and usability,
required index state, trigger bindings, reviewed function bodies/owners,
internal FK enforcement-trigger state, column defaults/nullability/generated
state, JSONB, and TIMESTAMPTZ. Five
distinct `NOLOGIN NOINHERIT NOBYPASSRLS` group-role contracts separate
migration, ingestion, governance, artifact building, and audit. Their renderer
removes stale runtime grants and fails closed on existing memberships or
runtime-role ownership; login identities and explicit migrator `SET ROLE`
remain operator responsibilities. The public SPA receives no database role.

CI runs the target-specific suite against a digest-pinned disposable PostgreSQL
16.14 service. Locally, those tests skip unless both `TEST_POSTGRESQL_URL` and
`TEST_POSTGRESQL_ALLOW_RESET=1` are supplied; the database name must contain a
test/disposable marker because the harness drops only its `public` schema.
DATA-09 target acceptance additionally runs
`tests/test_operational_persistence_postgresql.py`; see the
[operational persistence runbook](../docs/runbooks/operational-persistence-and-runtime-composition-rehearsal.md).

## Architecture

- Claims and snapshots are retained evidence; registry refresh is non-destructive and never disables foreign keys or deletes evidence.
- Logical sources have immutable source revisions; snapshots record the exact revision used for capture. A complete CLI registry manifest is idempotent, changes append a quarantined revision, and removals append a revoked retirement revision. Review and publication decisions are append-only, and legacy evidence is quarantined rather than rewritten.
- A captured claim's admitted identity and capture-status projection are immutable after insertion. Manual identity corrections extend one linear `ClaimReviewDecision` chain and are resolved as a read-only projection; a stale review decision cannot receive a publication decision.
- Adapters return candidate observations only. The runner admits a new claim only after one immutable source-revision certification decision, a single verbatim approved fetch artifact, typed evidence that matches the exact raw source record, declared dimensions, and a finite declared numeric lexeme. The admission decision ID is stored with the new claim; direct unbound inserts are rejected by the database. Ambiguous or unknown models retain their raw name with a null entity ID and `needs_review` rather than a guessed mapping.
- Snapshot/artifact storage is injected through a delete/admin-free runner
  protocol. Local filesystem objects under `SNAPSHOT_LOCAL_ROOT` and the
  R2-compatible adapter use full-SHA-256 keys, no-overwrite publication, full
  read-back verification, byte-free factory-only deterministic receipts, and
  exact provider-page/orphan accounting. Historic root-contained local paths are retained and verified
  in place; a missing, linked, substituted, or hash-mismatched object fails
  closed. The R2 adapter constructs conditional S3-compatible operations only;
  it does not create a client, read credentials, provision a bucket, configure
  locks/lifecycle, or expose delete. Real bucket-lock/token/retention evidence
  remains an external release gate.
- Production ingestion is opt-in and currently has **zero certified sources**
  and no enabled peer-pinning transport. O-level metadata alone is not approval.
- The LDR-08 `project_official_feed(session)` helper is an offline, read-only
  candidate projection for fixture validation. It selects only a finite numeric
  claim with complete capture-time source/snapshot provenance, all passing
  validation, an effective `validation_reviewed` review decision, and an
  effective `approved` publication decision. It is sorted and unique by the
  full display identity; a duplicate raises a deterministic conflict report.
  The versioned candidate contract is
  [`docs/contracts/official-feed-candidate-v1.schema.json`](../docs/contracts/official-feed-candidate-v1.schema.json).
  It is not an export command or release artifact: `export-official-json`
  remains disabled until the later immutable-artifact release gate.
- The LDR-09 `reports legacy-inventory` command is a deterministic
  reconciliation view, not an assessment writer. It accounts for all claims
  and snapshots while retaining their raw values and decision history; report
  labels explain candidate omissions/conflicts but never mutate status. Its
  schema is [`docs/contracts/legacy-inventory-v1.schema.json`](../docs/contracts/legacy-inventory-v1.schema.json).

## Tests

```bash
pytest -q
```

## CLI-only MVP

No ledger web UI in MVP (see AGENTS.md and ADR-001).

## Registry

Seeded from app/registry/*.yaml. Run benchmark-ledger seed-registry only with a
complete reviewed manifest. It never erases claim-bearing history: a changed
source appends a source revision and an absent registry-managed source receives
a retirement revision. The library helper defaults to no retirement so partial
programmatic manifests cannot mass-retire sources.

The registry currently contains 53 configured routes (23 active and 30
inactive), but production ingestion has zero certified sources. The YAML is the
executable status authority; do not infer readiness from an abbreviated README
table or an O-level label. See the current [source launch candidate
inventory](../docs/audits/2026-07-15-source-launch-candidate-inventory.md) for
the full active/retired grouping, collection constraints, and recommended
certification order.

**Containment note:** Registry status is not certification. Every existing
source remains denied until a governed immutable source revision, direct
evidence semantics, fixture coverage, and explicit certification decision
exist. The fake adapter remains for offline tests only.
