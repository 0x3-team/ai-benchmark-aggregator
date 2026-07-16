# Source certification and safe-fetch runbook

**Status:** Containment procedure — zero sources are certified and live fetch is disabled  
**Applies to:** the private ledger control plane only

## Current boundary

All network-capable adapters now inherit the central `SafeFetchClient`; they
cannot fetch unless the ingestion runner binds an immutable `FetchPlan` from a
certified source-revision admission decision. The client enforces HTTPS,
source/final URL allowlists, manual redirect-by-redirect validation,
non-public DNS rejection, timeout/size/content-type limits, fixed safe request
headers, response-header allowlisting, and redacted fetch metadata.

The default transport intentionally refuses every outbound request. A future
private runner must supply a reviewed transport that can prove the connected
peer after DNS validation and enforce egress/rate/concurrency policy. Do not
replace this with adapter-local `httpx`, redirects, `HF_TOKEN`, URL rewriting,
or a permissive proxy setting.

This means a source may not be fetched merely because it has O-level metadata,
a parser, a registry row, or a policy-shaped fixture. It must have the approved
certification workflow below, and a provider/runner decision, first.

## Prerequisites

1. The launch charter records P0-03 through P0-05 decisions: runner/provider,
   region/cost authority, retention, source terms, dimensions, and review
   authority.
2. The proposed source is one direct official reported-result artifact, not an
   article, blog, vendor newsletter, social post, third-party aggregate,
   discovery API, mock/fallback, or derived calculation.
3. The source revision names its real endpoint. An adapter may not synthesize,
   rewrite, or choose a different URL. Every permitted redirect URL is explicit
   in the immutable certification decision.
4. A parser fixture proves extraction of the raw source lexemes and a typed
   evidence locator that re-resolves model, benchmark, score, and approved
   dimensions in the captured bytes.
5. An independent reviewer is named before a capture can be used for a release.

## Certification record contents

Append a source-revision decision; do not edit a logical source into approval.
The decision must bind at least:

- exact source-revision definition hash, parser name/version, and direct source
  URL;
- `approved_source_urls` and `approved_final_urls`, including every allowed
  redirect hop;
- expected MIME type(s), byte/time/redirect limits, and the approved runner
  transport/egress policy version;
- source type/terms/license review, source owner, update cadence, and revocation
  condition;
- allowed benchmark, metric, split, setting, evaluation-version, and numeric
  lexeme/unit policy;
- typed evidence locator contract and fixture digest;
- reviewer, decision ID, timestamp, and supersession/revocation path.

The present admission schema supplies the immutable URL and evidence policy.
If the selected source needs richer fetch policy fields, append a new governed
decision/schema version—never reinterpret a historical decision in place.

## Controlled dry-run protocol

Only after the prerequisites and an approved runner transport are present:

1. Create a separate disposable control-plane environment with no public
   ingress and no browser credentials.
2. Record commit, source-revision and decision IDs, runner identity, redacted
   endpoint, policy version, and planned stop/rollback owner.
3. Perform one controlled capture. Preserve one verbatim snapshot before
   extraction; do not calculate replacement scores or combine artifacts.
4. Verify content digest, typed evidence re-resolution, raw lexical fields,
   all-pass validation, duplicate/idempotency behavior, and ambiguous-model
   quarantine behavior.
5. Record a run receipt with counts/rejection codes only. Do not place raw
   protected content, authorization headers, cookies, query tokens, or source
   credentials in logs, telemetry, issue trackers, or the public artifact.
6. Stop on URL/MIME/size/redirect/DNS mismatch, source terms uncertainty,
   unexpected schema drift, unresolved evidence, or any attempt to publish.

The dry run does not approve a claim, publication decision, release artifact,
or Official frontend mode.

## Revocation and incident response

- Append a revoking/superseding source decision; do not alter existing source
  revisions, snapshots, or claims.
- Disable the runner schedule/identity through the approved provider procedure.
- Quarantine future use of affected snapshots/artifacts and begin the separate
  release-withdrawal flow if anything was published.
- Preserve the evidence and redacted incident receipt for review. Never delete
  the historical record as a remediation shortcut.
