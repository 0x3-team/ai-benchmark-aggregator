# ADR-010: Provider-neutral recovery evidence and new-target restore

- **Status:** Accepted for local/disposable recovery mechanics
- **Date:** 2026-07-16
- **Scope:** DATA-10 recovery foundation only

## Context

The ledger keeps immutable source snapshots, claims, decisions, and operational
history in a relational database while retained snapshot bytes live in a
separate object store. A database backup alone cannot prove that a restored
ledger can re-resolve every retained byte. Conversely, copying objects without
the exact relational denominator can silently omit snapshots or select a
conflicting decision chain.

The product direction is to lose at most one completed collection cycle. That
is a proposed operating target, not a production claim. No accountable recovery
owner, accepted RTO, provider, region, retention policy, or provider-independent
failure-domain evidence exists yet. The current implementation therefore needs
to prove portable mechanics without implying Cloudflare R2, managed PostgreSQL,
or production recovery readiness.

## Decision

### One backup-byte-derived checkpoint

Each checkpoint is bound to one exact, terminal `scheduled-cycle-v1` document.
The trigger must be the unambiguous latest completed cycle in its lane inside
the immutable relational backup. Inspection is performed from backup bytes,
never by querying a racing source database after capture.

The canonical `recovery-checkpoint-v1` manifest records:

- the exact trigger and complete terminal-cycle census with per-lane
  watermarks;
- the producer and inspection engine/tool versions;
- the exact reviewed schema revision and executable-schema digest;
- every table's column denominator, row count, and order-independent typed
  row-set digest;
- all seven append-only decision/event lineage audits;
- every retained `SourceSnapshot` raw-byte reference, including snapshots with
  no claim, and an explicit zero denominator when none exist;
- a full-byte SHA-256-verified relational archive copy and independently
  restorable snapshot-byte copies in the declared recovery domain; and
- a self-digest and authority ceiling that explicitly denies source
  certification, capture, publication, frontend loading, cutover, provider
  independence, and production RPO/RTO claims.

Opaque model hashes and screenshot locations do not become governed recovery
objects. A non-null object reference without a typed, digest-re-resolvable
contract fails closed.

### Immutable publication and replay

Checkpoint bytes are canonical ASCII JSON and are themselves stored through
the immutable recovery artifact path. A retry may reuse only one exact
full-byte manifest for the same trigger identity. A changed, missing, invalid,
or competing same-trigger publication is a conflict; insertion or inventory
order never selects a winner. CLI copies are created with no-follow,
create-exclusive mode `0600` and are never overwritten. Before reservation,
the CLI resolves the admitted output parent and rejects a manifest or receipt
inside any primary, recovery, or restore object root; a SQLite receipt also
cannot alias its relational target. Evidence output must never mutate its own
immutable input domain.

The scheduler/lease boundary remains responsible for ensuring one checkpoint
publisher per cycle. The immutable replay fence is not a replacement for the
DATA-09 fencing contract.

### Separate copies, cautious terminology

The runner-facing storage capability can conditionally create, read back,
verify, and inventory immutable objects. It has no delete, overwrite, lifecycle,
retention-admin, bucket-admin, or provider-client surface. Source, recovery, and
restore domains require distinct stable identifiers; local roots must not
alias, overlap, or contain one another.

Different identifiers or local directories are routing assertions only. Every
manifest and receipt says `external_evidence_required` for actual provider
failure-domain and retention independence.

### New-target-only restoration

Restore accepts only a valid checkpoint that re-resolves to its exact immutable
publication. Before relational mutation it validates the target ID and timing,
domain identities, database locator, archive copy, and an exactly empty object
target. The relational driver must consume a fresh target before restoring.
Old, source, recovery, nested, nonempty, symlinked, previously attempted, or
partially restored targets are never repaired or reused.

After restoration, inspection recomputes schema, table, typed row-set, cycle,
lineage, and object denominators from the new target. Every object is copied
from recovery bytes into the new restore domain, read back by full SHA-256, and
reconciled against an exact no-extra inventory. Only then may a canonical
`recovery-restore-receipt-v1` be emitted. It is a recovery-map receipt with
`cutoverAuthorized=false`, not a runtime locator change.

Failure or cancellation emits no success receipt. Partial immutable objects,
an empty reserved receipt file, a SQLite target, or a PostgreSQL consumed-target
marker may remain. Recovery proceeds with another fresh target; it never uses
downgrade, delete, reset, `pg_restore --clean`, or in-place repair.

### Relational drivers

SQLite uses the standard backup API and accepts only the exact reviewed 0010
executable schema. Restore creates a new private file and rejects the original
resolved source locator.

PostgreSQL uses fixed real PostgreSQL 16 `pg_dump`/`pg_restore` binaries and a
custom archive. Inspection itself restores into an explicit fresh database;
cached or live-source inventories are not accepted. Tools receive a closed
libpq environment, bounded execution, process-group cancellation, and no DSN
on argv. Restore uses a filtered TOC, one transaction, `--no-owner`, and
`--no-privileges`; it never creates or drops a database.

Before `pg_restore`, a durable shared-catalog database comment binds the target
ID and archive digest. Admission and read-back use PostgreSQL
`shobj_description`, because database descriptions are shared objects; the
marker is never cleared. Archive owner, membership, ACL, and grant
posture is deliberately excluded. A literal post-restore
`REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA public FROM PUBLIC` establishes only
the minimum executable-state safety floor needed by strict schema inspection;
it is not role convergence or access-control recovery evidence.

Freshness includes a typed, canonical database-scope census, not merely a
count of relations in `public`. A target must have the reviewed stock PG16
database ACL/routing fields, stock `public` owner and expanded ACL, only the
stock procedural-language/extension baseline, and no database-scoped
publication/subscription state, event triggers, large objects, role settings,
foreign-data objects, default ACLs, security labels, transforms, user-defined
casts/access methods/rewrites, row-security policies, prepared transactions, or
logical slots. The census and its canonical SHA-256 are checked before the
permanent marker, again immediately before `pg_restore`, and again after
restore; the semantic samples and safety-floor proof bind the same digest.

The source may have provider-managed database ACL/routing and `public`
owner/ACL posture that differs from the fresh-target baseline. Those facts are
intentionally outside the owner/ACL-excluding archive and are not recovery
claims. All other unsupported database-scoped source facts must be at the
canonical empty baseline, because silently excluding them would make the
archive incomplete. Cluster roles/memberships, parameter ACLs, physical slots,
replication origins, tablespaces, locale/frozen-XID state, active sessions, and
locks remain explicit provider/runtime nonclaims rather than freshness facts.

## Consequences

- Local SQLite and disposable PostgreSQL drills can prove exact relational and
  object-byte recovery semantics without touching an old target.
- Recovery manifests and receipts are durable, deterministic evidence suitable
  for later scheduler/incident telemetry, but they are not frontend inputs.
- The `benchmark-ledger recovery` CLI exposes explicit SQLite and PostgreSQL
  checkpoint/restore commands. PostgreSQL connection material is accepted only
  through fixed environment variables, and success output contains no locator.
- PostgreSQL recovery needs two fresh targets per checkpoint drill: one for
  archive inspection and another for the actual recovery map.
- A relation-only emptiness check is insufficient. Database-scoped state is
  canonically censused and fail-closed at source inspection and at every target
  boundary; a contaminated target is consumed without running `pg_restore`.
- A failed or cancelled target is intentionally consumed. Operators need a
  target-allocation process; cleanup is test-resource administration outside
  the recovery driver.
- Role membership, ownership policy, provider backup guarantees, R2 retention
  lock, object-store/account independence, secret delivery, connection path,
  cost, and regional posture need separate provider evidence.
- The at-most-one-cycle-loss target remains unproven until scheduled
  per-cycle checkpoints and a provider-approved timed drill demonstrate it.
  The local duration is a measurement, not an accepted RTO.

## Rejected alternatives

- **Backup the database only:** cannot re-resolve retained snapshot bytes.
- **Inventory the live source after backup:** mixes two points in time.
- **Restore over or clean an old target:** destroys forensic and rollback
  evidence and makes partial failure ambiguous.
- **Trust a store/restore success code:** does not prove full-byte identity,
  exact denominators, lineage, or absence of extra objects.
- **Select the first/latest manifest:** hides conflicts and makes ordering an
  authority decision.
- **Treat local roots or different bucket names as independent:** configuration
  labels are not failure-domain or retention proof.
- **Carry PostgreSQL owners and ACLs in the archive:** couples data recovery to
  provider-specific identities and can reintroduce unsafe access posture.
- **Represent a successful local drill as RPO/RTO compliance:** neither cadence
  nor approved production targets and owners are present.

## Follow-on gates

Provider selection must add approved owners, RTO and retention decisions, exact
Cloudflare R2/managed-PostgreSQL failure domains, provider lock and role
evidence, secrets/TLS/connectivity proof, scheduled checkpoint receipts, an
independent alert path, and a timed loss-of-primary drill. Runtime cutover and
Official publication remain separately governed.
