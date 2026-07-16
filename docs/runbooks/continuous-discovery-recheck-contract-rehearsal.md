# Continuous discovery and recheck contract rehearsal

**Status:** Local contract rehearsal only — no live scheduler, source fetch,
database persistence, external alert route, or Official release is enabled  
**Applies to:** Phase 0/1 synthetic contract validation

## Current capability

The repository can describe and fail-closed validate the records a future
twice-daily discovery/recheck system must produce. The validators are pure:
they do not read a clock, filesystem, environment, network, database, or cloud
provider. Checked-in examples are synthetic evidence for tests only.

The current executable boundary does **not**:

- discover or recheck a live source;
- certify a source revision or benchmark definition;
- create a durable cycle, lease, incident, or notification;
- send email, chat, webhook, or provider messages;
- prove the one-cycle recovery objective; or
- build, authorize, or activate an Official artifact.

## Local rehearsal

From the repository root, validate the contract suites with:

```bash
cd ledger
.venv/bin/pytest -q \
  tests/test_source_contracts.py \
  tests/test_domain_identity_contracts.py \
  tests/test_operations_contracts.py \
  tests/test_continuous_contracts.py \
  tests/test_incident_contracts.py
```

Also validate every schema against Draft 2020-12 and every matching example
with format checking. A semantic validator success never substitutes for the
schema check, and a schema success never substitutes for semantic validation.

## Future cycle protocol

This protocol is descriptive until persistence and runner work is separately
approved.

1. Derive one logical cycle and job per exact UTC slot, lane, target revision,
   environment, and schedule-policy revision. Treat duplicate provider
   wakeups as observations of the same work.
2. Reconcile every expected target as due, not due, or blocked. A missing
   dispatch is explicit; it is not silently omitted from counts.
3. Before any recheck request, re-resolve the exact effective source-revision
   certification and its bound source-contract definition digest. Expired,
   stale, unsafe, or uncertified work stops before network access.
4. Acquire a bounded lease and fencing token. Only the current token may
   commit. A replacement attempt binds the prior token; a stale worker records
   rejection and cannot publish output references.
5. Retry only allowlisted transient failures, inside the same cycle completion
   window and before the next scheduled slot. Non-retryable policy, terms,
   identity, schema, evidence, integrity, and security failures quarantine or
   require review.
6. For a changed successful response, commit immutable bytes and verify their
   digest before extraction. For a valid `304`, bind the exact prior snapshot
   content digest and prior successful verification receipt. Record failures at
   their actual DNS/connect/TLS/redirect/header/body stage.
7. Account for every source record and every emitted claim candidate. Preserve
   raw lexemes exactly; unexplained loss, duplicate locators, unapproved
   dimensions, nonnumeric/non-finite scores, or failed evidence re-resolution
   writes no unsafe claim.
8. Before accounting a recheck cycle, resolve exactly one deterministic source
   receipt for every attempt—not only the final attempt. Cross-check exact slot,
   source revision, job, attempt number/ID, fencing token, contained execution
   interval, compatible terminal outcome/stage/cause, receipt ID/digest, new or
   reused snapshot ID/content digest, and incident-reference denominator. A
   blocked source still has exactly one admission attempt and receipt. Make the
   cycle terminal only when every attempt and exact final output reference
   reconcile without row-order selection.

## Problem handling

- Derive a stable incident fingerprint from allowlisted identifiers and reason
  codes, not raw source-controlled text. Repeated open occurrences deduplicate;
  a later recurrence after resolution reopens through an append-only event.
- Create review work with an explicit owner role and SLA. Timeout or delivery
  does not approve, reject, certify, publish, or acknowledge it.
- Render notification intents from a fixed, redacted field allowlist. Store a
  local/blocked receipt until recipient, privacy, secret, and route authority
  exists. A notification receipt never acknowledges the incident.
- Preserve all evidence on containment. Pause future eligible work through the
  later governed control path; do not update/delete historical receipts.
- Detect missed cycles with an independent watchdog outside the scheduler's
  failure domain. A scheduler cannot be its own proof of health.

## Preconditions for shadow operation

Before a real shadow cycle, record named owners and decisions for source terms
and certification, identity review, incident response, alert recipients,
retention, region, provider, cost ceiling, and the private runner. Implement
the forward-only persistence/role constraints, approved transport, private
object storage, local notification sink, and watchdog. Then prove duplicate,
missed-slot, stale-lease, DNS/redirect, schema-drift, storage-failure,
notification-failure, backup, and restore cases in a disposable environment.

The desired recovery objective is at most one scheduled capture cycle lost.
It becomes a production promise only after repeated restore/reconciliation
drills produce dated receipts within the approved recovery time.
