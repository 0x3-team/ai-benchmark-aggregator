# ADR-009: Operational persistence and inert runtime composition

**Status:** Accepted for local/disposable implementation; operational activation remains unapproved  
**Date:** 2026-07-15  
**Decision ID:** DEC-009

## Context

ADR-008 froze the continuous-collection wire contracts without making them
durable or runnable. A production-shaped collector needs persistent intent,
attempt, lease, source-check, extraction, discovery, identity, incident,
review-work, and notification evidence. It also needs one explicit composition
root so ordinary construction cannot silently acquire network, storage,
scheduler, incident, or delivery authority.

The persistence layer must not create a second route around source revision
certification, immutable snapshots, claim admission, review, publication, or
the frontend release boundary. It must also remain safe under duplicate
delivery, worker expiry, concurrent PostgreSQL writers, process interruption,
and partial operational progress.

## Decision

1. The forward-only `0010_operational_persistence` Alembic revision is the
   durable relational shape for the Phase 1 operational contracts. It may be
   applied only to fresh or explicitly disposable targets during this phase.
   The quarantined legacy SQLite database is not a migration target.
2. Pre-dispatch cycle/job intent is distinct from terminal evidence. Intent is
   persisted before work without predicting attempts or outcomes. A terminal
   scheduled-cycle receipt may be appended only after its complete, exact
   attempt and output denominator exists.
3. Operational history is append-only. The sole mutable coordination
   projection is `scheduled_job_leases`; immutable lease events retain the
   history. Lease acquisition, takeover, heartbeat, attempts, and completion
   require the current fencing token. Accepted-current work is checked against
   both an injected trusted clock and the database clock at commit, so a caller
   cannot backdate work past lease expiry.
4. A source attempt and its immutable source-check receipt are one composed
   transaction. Their reciprocal references use the reviewed deferred foreign
   key posture, and database guards bind the exact receipt ID/digest, job,
   attempt, fencing token, execution interval, source revision, effective
   certification decision, contract envelope, definition digest, snapshot,
   and extraction facts. Raw and canonical payload identities must agree with
   the relational columns.
5. Source contracts, benchmark revisions, evaluated-subject revisions,
   identity decisions, incidents/events, review-work events, notification
   intents/receipts, and outbox completion denominators have stable identities
   and linear histories. Stale, branched, underfilled, late-appended, or direct
   mutation paths fail closed. A zero-intent notification batch uses an
   explicit sentinel rather than an ambiguous empty denominator.
6. A terminal output type is accepted only when DATA-09 has an exact typed,
   durable referent for it. Unsupported discovery, maintenance, or schedule
   terminal referents fail explicitly; opaque or generic receipt identifiers
   are not persistence evidence.
7. `RuntimeDependencies` is the ingestion composition root. Fetch transport,
   storage factory, clock, scheduler repository, incident service, and rate
   limiter are injected. Non-default side-effecting products require explicit
   code-level capabilities. Environment values cannot grant capabilities,
   adapters do not own HTTP clients, the default transport is disabled, and
   dry-run does not touch network, DNS, storage, scheduler state, incidents,
   rate limits, or ingestion-run rows.
8. PostgreSQL status is executable-state verification, not name matching. It
   verifies exact constraints and their deferral posture, required indexes,
   user triggers/functions, and the normally enabled internal referential-
   integrity triggers backing every reviewed foreign key. A disabled internal
   RI trigger makes status invalid.
9. Capability groups remain separate. Ingestion has only the bounded
   operational/evidence writes required by a runner and cannot govern source,
   claim-review, or publication decisions. Governance can append bounded
   benchmark/subject/identity/review-work facts but cannot certify source
   revisions, review claims, approve publication, or alter evidence. Artifact
   builders cannot read the private operational plane; audit is read-only.

## Authority and activation boundary

This decision supplies persistence and composition mechanics, not an active
service. It does not authorize or implement:

- a scheduler, discovery controller, recheck worker service, watchdog, or
  notification delivery adapter;
- live source access, source certification, benchmark activation, identity
  resolution, external recipients, or alert acknowledgement;
- Cloudflare, database, object-store, secret, DNS, deployment, or paid
  resources;
- a legacy-database migration, provider cutover, recovery claim, publication
  decision, release artifact, or frontend Official mode.

Those capabilities require their later plan items and governed decisions.
Supplying a protocol-shaped object or passing a fixture test is not authority.

## Consequences

- A crash after intent but before work leaves an honest, nonterminal record
  that a future controller can reconcile.
- Duplicate replay may return the exact existing immutable record; conflicting
  replay, stale fencing, expired acceptance, and branching fail.
- SQLite proves local constraints and PostgreSQL 16.14 proves target-specific
  concurrency, trigger, role, and strict-status behavior. Neither proves a
  managed provider, TLS/pooling, retention, backup, restore, or production
  operation.
- Future services must use the injected boundary and durable repositories;
  they may not add adapter-local networking, in-memory schedule truth, mutable
  evidence, or an alternate operational database path.
- ADR-008 remains the semantic contract decision. This ADR records the later
  durable representation and inert runtime composition.

## Rejected alternatives

- Persisting a terminal receipt as the pre-dispatch work request.
- Treating Queue/Cron delivery or an in-memory lock as durable schedule truth.
- Checking lease validity only against caller-supplied payload timestamps.
- Storing opaque digests without durable exact referents.
- Letting source attempts and source receipts commit independently.
- Making all operational tables mutable for convenience.
- Considering `pg_constraint` rows sufficient while FK enforcement triggers
  are disabled.
- Enabling network or provider behavior from environment configuration alone.
- Treating governance as source-certification, claim-review, or publication
  authority.
