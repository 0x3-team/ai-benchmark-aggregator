# Launch charter and decision record

**Status:** Partially decided — Official-claims milestone and Cloudflare Pages
are selected; accountable owners and all release gates remain unresolved.  
**Last reviewed:** 2026-07-15

Complete this record before provider configuration, live ingestion, source
certification, or Official-mode activation. `UNDECIDED` is an intentional stop
state, not approval.

| Decision | Current value | Accountable owner | Evidence / date |
| --- | --- | --- | --- |
| Launch milestone: Demo-only beta, Official-claims launch, or both | Official-claims production launch selected. This is not Official-mode activation or release authorization. | UNASSIGNED | User direction, 2026-07-15 |
| Public-host operator and host (Cloudflare Pages or Vercel) | Cloudflare Pages selected for the static public frontend. No public Worker/API, account, DNS, preview, or deployment is authorized. | UNASSIGNED | User direction, 2026-07-15 |
| Database, object store, private runner, region, cost authority | UNDECIDED | UNASSIGNED | — |
| RPO, RTO, retention/legal hold, update cadence, withdrawal SLA | User direction: lose no more than one scheduled source-capture cycle. Proposed operating target while cadence/owner are chosen: daily sources imply RPO no greater than 24 hours; RTO no greater than one business day; retain release artifacts/evidence for two years; withdraw an incorrect public artifact within four hours. Legal hold, exact cadence, and operational owner remain undecided. | UNASSIGNED | User direction, 2026-07-15; proposed target, not provider/deploy approval |
| First official source, terms/license, allowed dimensions, review authority | No source selected or certified. Current technical preparation sequence: BigCodeBench, then SWE-bench Verified, with ARC-AGI deferred; see the [source candidate inventory](../audits/2026-07-15-source-launch-candidate-inventory.md) and [initial preparation runbook](initial-source-certification-preparation.md). | UNASSIGNED | Primary-source/terms research, 2026-07-15; product/governance approval still required |
| Artifact approval/revocation/release signers | UNDECIDED | UNASSIGNED | — |
| Privacy/security telemetry policy, incident contact, disclosure process | UNDECIDED | UNASSIGNED | — |
| Supported browser/E2E and assistive-technology matrix | User direction: support as broad a range as practical. Proposed matrix below is intentionally specific enough to test; owner and final support commitment remain undecided. | UNASSIGNED | User direction, 2026-07-15 |

## Scope statement

State the exact public claim the launch is allowed to make:

```text
Official-claims milestone selected, but the exact public claim remains
**UNDECIDED** until a governed artifact ID/digest and publication decision are
approved under REL-05.
```

For a Demo-only beta, this statement must say that visible values are synthetic
and that Official claims are unavailable. For an Official launch, it must name
the governed artifact ID/digest and approval decision; a candidate feed,
legacy report, fixture, or local export is never a substitute.

## Required sign-off record

Record each sign-off as an append-only dated entry with the relevant commit,
artifact/source identifiers, exception expiry, and rollback owner. Do not edit
historical entries to simulate approval.

| Date | Decision ID | Signer / role | Scope | Expiry / review date | Evidence link |
| --- | --- | --- | --- | --- | --- |
| — | — | — | — | — | — |
| 2026-07-15 | P0-01 | User — product direction | Selected the Official-claims production track; no source, artifact, or frontend activation approved. | Review when accountable product/release owner is named. | Current Codex task instruction |
| 2026-07-15 | P0-02 (platform only) | User — product direction | Selected Cloudflare Pages for the static public frontend; no provider account, DNS, deploy, Worker, or public API approved. | Review when accountable host operator and cost authority are named. | Current Codex task instruction |
| 2026-07-15 | P0-04 (recovery intent) | User — product direction | Requested that a recovery event lose no more than one scheduled source-capture cycle. The proposed 24-hour/daily RPO, one-business-day RTO, two-year retention, and four-hour withdrawal targets still need an operational owner and provider-capability proof. | Review when source cadence, data-plane provider, and owner are named. | Current Codex task instruction |
| 2026-07-15 | P0-05 (technical recommendation only) | Codex — engineering recommendation | Recommended a staged certification order of ARC-AGI, SWE-bench Verified, then BigCodeBench. No source, terms, dimensions, source revision, or certification decision was approved. | Expires when product/data-governance owner selects a source or rejects the recommendation. | [Source candidate inventory](../audits/2026-07-15-source-launch-candidate-inventory.md) |
| 2026-07-15 | P0-08 (access intent) | User — product direction | Requested broad browser and assistive-technology access; the proposed test matrix remains awaiting a concrete support/owner decision. | Review when browser/AT infrastructure and owner are named. | Current Codex task instruction |
| 2026-07-15 | P0-05 correction (technical recommendation only) | Codex — engineering recommendation | Primary-source/terms research supersedes the earlier technical sequence: prepare BigCodeBench first, then SWE-bench Verified; defer ARC-AGI pending written permission. No source, terms, dimensions, source revision, or certification decision was approved. | Expires when product/data-governance owner selects a source or rejects the recommendation. | [Initial preparation runbook](initial-source-certification-preparation.md) |

## Proposed broad access matrix

This is a proposed product support commitment, not a claim that the checks have
already run. It separates required release evidence from best-effort coverage
so that “as much as possible” does not become an untestable promise.

| Level | Browsers and platforms | Assistive/interaction checks |
| --- | --- | --- |
| Required before Official release | Current stable Chrome, Edge, and Firefox on Windows; current stable Chrome, Firefox, and Safari on macOS; Safari on current iOS/iPadOS; Chrome on current Android. Test keyboard-only operation, narrow viewport, 200% and 400% zoom where applicable, reduced motion, and forced-colors/high-contrast behavior. | NVDA with Firefox on Windows; VoiceOver with Safari on macOS and iOS; TalkBack with Chrome on Android. Verify keyboard/focus restoration, source selection, independent sheets, evidence/provenance surface, no-data state, and error recovery. |
| Extended/best effort | Previous stable releases where vendor support permits; JAWS with Chrome on Windows; alternate mobile-browser combinations. | Record regressions and fixes, but do not claim completed coverage until the relevant device, browser, and assistive technology have been exercised. |

P0-08 remains open until the accountable owner accepts this matrix or records a
narrower one, browser automation is installed, and dated manual
assistive-technology receipts exist.

## Stop conditions

- Missing owner, budget, region, RPO/RTO, source, or release authority stops
  provider work and live capture.
- Missing browser/assistive-technology decision stops a claim of browser launch
  readiness.
- A proposed recovery or accessibility target is not a provider capability
  guarantee. It must be demonstrated by backup/restore, withdrawal, browser,
  and assistive-technology evidence before a release claims it.
- A provider capability statement does not authorize paid operations or imply
  retention/backup coverage; record a separate approved decision first.
