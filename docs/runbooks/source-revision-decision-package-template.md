# Source-revision decision-package template

**Authority ceiling:** candidate preparation only. Completing this template does
not certify a source, authorize a fetch, create a source revision or decision,
write a snapshot or claim, approve publication, enable a schedule or transport,
or make data frontend-loadable. Keep `decision outcome: not_assessed` until the
repository's append-only decision path binds the exact reviewed definition.

Use one package per logical source revision. Do not approve a cohort in bulk.
Every factual statement needs a primary-source URL and retrieval date; an
immutable URL is required where the fact can change. Record unknowns as
blockers rather than filling them by inference.

## Package identity

- Candidate package ID:
- Logical source ID:
- Benchmark revision ID:
- Proposed source revision ID:
- Repository base commit:
- Prepared by / prepared on:
- Decision outcome: `not_assessed`
- Lifecycle: `draft_unapproved`
- Supersedes package:

## Authority and reuse

- Primary result publisher and accountable owner:
- Evidence that the artifact is the publisher's reported-result source:
- Terms/license status: `unknown`, `blocked_terms`, `blocked_permission`, or
  `reviewed_permitted`
- Verbatim terms/license quote:
- Evidence URL and retrieval date:
- Scope question requiring owner decision:
- Attribution, notice, noncommercial, retention, and withdrawal obligations:
- Named data-governance approver:
- Named independent certification reviewer:
- Terms review due date:

Repository or task-code licensing is not result-data licensing unless the
publisher explicitly applies it to the candidate result artifact.

## Immutable artifact definition

- Exact immutable revision:
- Exact direct file URL(s), with no branch aliases or preview endpoints:
- Publisher-provided file digest(s), object ID(s), and byte sizes:
- Completeness mode: `complete_artifact`, `complete_manifest`, or
  `complete_endpoint_result`
- Exact artifact/shard denominator:
- Redirect behavior and stable final-URL feasibility:
- Accepted response media types, backed by observed headers:
- Per-file and aggregate byte bounds, backed by publisher metadata:
- Authentication requirement:

Do not record expiring signed redirect URLs, cookies, credentials, or live
fetch receipts in this package.

## Claim and evidence contract

- Source-reported score field(s):
- Source-reported identity field(s):
- Candidate accepted raw dimensions:
  - `benchmark_raw`:
  - `metric_raw`:
  - `split_raw`:
  - `setting_raw`:
  - `evaluation_version_raw`:
- Explicitly excluded fields/rows and the owner decision authorizing each:
- Numeric lexeme and score-unit policy:
- Typed locator family and exact field map:
- Complete-accounting equation and expected row/claim bounds:
- Ambiguous identity treatment:

The locator must re-resolve `model_raw`, `score_raw`, and every evidence-backed
dimension in immutable bytes. A rank, average, preview row, calculated value,
or UI rendering is not a substitute for a source-reported score.

## Freshness, correction, and withdrawal

- Publisher freshness signal:
- Cadence claim and evidence:
- Correction intake route:
- Source withdrawal/revocation route:
- Drift conditions requiring pause and a new revision:
- Historical revision retention evidence:

## Fixture rehearsal

- Fixture origin and digest:
- Schema represented:
- Exact raw-lexeme coverage:
- Null/missing-field coverage:
- Duplicate-locator/identity coverage:
- Non-finite/nonnumeric coverage:
- Complete-artifact/shard accounting coverage:
- Typed evidence re-resolution coverage:
- Unresolved/ambiguous identity coverage:
- Known differences from the candidate artifact:

A fixture pass proves parser behavior only. It is never a live receipt,
certification decision, terms approval, or complete-artifact observation.

## Gate verdicts and blockers

Record `pass`, `stop`, or `not_assessed` with evidence for every row.

| Gate | Verdict | Evidence / exact blocker | Required owner/action |
| --- | --- | --- | --- |
| Primary-source authority |  |  |  |
| Result-data reuse/display |  |  |  |
| Immutable complete artifact |  |  |  |
| Stable URL and media type |  |  |  |
| Bounded bytes/resources |  |  |  |
| Approved dimensions |  |  |  |
| Source-specific parser |  |  |  |
| Typed evidence contract |  |  |  |
| Fixture and drift rehearsal |  |  |  |
| Identity model |  |  |  |
| Freshness and corrections |  |  |  |
| Connected-peer transport |  |  |  |
| Append-only certification |  |  |  |

## Decision handoff

The handoff must name the exact immutable source definition digest, terms
decision, reviewer, outcome, effective/expiry dates, and supersession route.
Until that exists, the only permitted conclusion is **candidate / not
certified / capture ineligible / publication ineligible**.
