# Incident, telemetry, and disclosure baseline

**Status:** Design baseline — telemetry collection and public incident process are not approved

## Current rule

Do not add third-party analytics, session replay, source-content logging, or
visitor identity collection until P0-07 records a privacy/security decision,
retention period, legal basis/notice, security contact, and incident-disclosure
owner. The current implementation may emit local test output only; it must not
be represented as production observability.

## Minimum future event schema

Events must be minimized and redacted. They may include opaque run/release IDs,
timestamps, status/reason codes, artifact digest, source-revision decision ID,
and aggregate counts. They must not include raw source bytes, score text,
model/source strings unless approved, headers, cookies, tokens, query values,
database URLs, object-store paths, IP addresses, or visitor identifiers beyond
the approved policy.

| Event family | Required future purpose | Public-data boundary |
| --- | --- | --- |
| Source capture | Detect failed/blocked/revoked runner activity | Private runner only; redacted receipt. |
| Artifact build/verification | Detect digest/schema/policy failures | Private builder/CI only. |
| Release/promotion/rollback | Establish release and withdrawal timeline | No credentials or raw artifact fields. |
| Backup/restore | Prove RPO/RTO drill outcome | Private operations only. |
| Frontend failure/accessibility/performance | Detect user-impacting regressions | Aggregate/minimized, consent/notice reviewed. |

## Incident handling template

1. Contain: disable the affected runner/release path; do not delete evidence.
2. Preserve: record UTC time, commit/artifact/source-decision IDs, redacted
   reason code, owner, and evidence locations.
3. Assess: determine whether a source, artifact, preview, credential, cache,
   or UI truthfulness boundary was affected.
4. Communicate: use the approved security/correction contact and disclosure SLA.
   Do not promise notification timing before that policy exists.
5. Correct: append a decision/new artifact or deploy an explicit unavailable
   state. Never rewrite claims/snapshots or silently fall back to Demo under an
   Official label.
6. Review: record remediation, owner, due date, and whether source
   certification/release approval must be revoked or superseded.
