# ADR-008: Continuous collection contract boundaries

**Status:** Accepted for contract design; runtime and provider activation remain unapproved  
**Date:** 2026-07-15  
**Decision ID:** DEC-008

## Context

The ledger can preserve source-backed claims, but it does not yet have a
durable production scheduler, discovery service, incident registry, or alert
delivery service. A twice-daily operating system needs those concepts without
creating a second path around source certification, immutable snapshots,
claim admission, review, publication, or the frontend release boundary.

Checked-in JSON Schema alone cannot prove identities, append-only lineage,
canonical digests, exact retry arithmetic, fencing, or authority separation.
Conversely, introducing database tables or a cloud runtime before the owner,
provider, region, retention, recipient, and source decisions are approved
would turn a design exercise into an unauthorized production change.

## Decision

1. The Phase 0/1 domain is specified first as versioned JSON wire contracts,
   synthetic examples, and deterministic standard-library semantic
   validators. Both schema and semantic validation are required.
2. A source contract is a definition, not its own certification. A future
   external certification decision must bind the exact definition digest; the
   final immutable envelope then binds that decision and has its own digest.
   A source-check receipt records what happened under that exact pair and does
   not retroactively authorize a request.
3. Benchmark definitions are immutable edition revisions. Evaluated subjects
   are typed systems—base models, endpoints, agents, ensembles, or
   submissions—with exact raw source identity. Append-only identity decisions
   may affect an identity read projection, but never rewrite claim/raw fields
   or promote capture, validation, publication, or release state.
4. Schedule identity is derived from an environment, lane, exact UTC slot,
   target revision, and schedule-policy revision. Cron, Workflow, Queue, and
   manual wakeups are observations only. Durable cycle/job/attempt receipts,
   exact output references, bounded retry windows, and current fencing tokens
   are the future source of truth. When a recheck attempt and source-check
   receipts are supplied together, pure composition validators require exactly
   one deterministic source receipt per attempt and reconcile their slot,
   source revision, job, attempt, fencing token, execution interval, terminal
   semantics, receipt ID/digest, new/reused snapshot reference, incident
   denominator, cycle mode, and final cycle disposition.
5. Incidents, review work, notification intents, and notification receipts are
   append-only operational evidence. Their state machines cannot acknowledge
   one another implicitly and cannot change source, claim, review,
   publication, or frontend state. External delivery remains blocked until
   recipient and privacy authority is recorded.
6. The contracts remain persistence-neutral in this phase. Any durable models,
   constraints, roles, or coordination projections will be added only through
   the forward-only Alembic path and must preserve the PostgreSQL/private-plane
   requirements in ADR-007. That later local/disposable implementation is
   recorded separately in ADR-009; it does not retroactively activate these
   contracts.

## Contract families

- Source definition and checks: `source-contract-v2` and
  `source-check-receipt-v1`.
- Benchmark/system identity: `benchmark-definition-revision-v1`,
  `evaluation-subject-v1`, and `identity-decision-v1`.
- Scheduling: `scheduled-cycle-v1` and `scheduled-job-attempt-v1`.
- Operations: `ops-incident-v1`, `review-work-item-v1`,
  `notification-intent-v1`, and `notification-receipt-v1`.

The authoritative catalog and validation boundary are documented in
[`docs/contracts/README.md`](../contracts/README.md).

## Consequences

- A valid fixture demonstrates a contract, not a live source, scheduled job,
  incident acknowledgement, alert delivery, database record, or approval.
- Tests may exercise effective/production-shaped branches using synthetic
  data, but checked-in examples and default construction remain inert.
- The local composition validator checks exact supplied documents; future
  persistence must additionally resolve those IDs/digests from immutable
  storage. Selecting records by insertion order or accepting a stale/branched
  lineage is invalid.
- The public SPA remains Demo-only and reads only the tracked unavailable
  Official artifact. None of these contracts is a frontend input.
- Real acceptance still requires approved owners and providers, disposable
  PostgreSQL/object-storage proofs, shadow cycles, failure drills, alert-route
  receipts, recovery evidence, and the separate REL-05 release authorization.

## Rejected alternatives

- Treating Cron/Queue delivery as schedule truth.
- Letting a source contract certify itself or omitting failed fetch attempts.
- Using browser/agent extraction as the authoritative claim path.
- Mutating claims when identity is reviewed or choosing ambiguous identities by
  order.
- Making an incident acknowledgement acknowledge a work item or delivery.
- Wiring draft contracts directly into SQLAlchemy, Cloudflare, or the SPA.
