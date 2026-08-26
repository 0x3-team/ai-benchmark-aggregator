# ADR-011: Vendor-reported claims and exact release authorization

**Status:** Proposed bounded candidate; no release is authorized  
**Date:** 2026-08-26  
**Decision ID:** DEC-011-CANDIDATE

## Context

The ledger records what a source reported. Some direct, structured sources are
owned by a benchmark operator; others are first-party model-vendor result
feeds. Calling both “official benchmark results” erases a material trust
difference: a vendor can be authoritative about what it reported without being
the benchmark owner or an independent evaluator.

The pre-existing v2 frontend parser seam also needs a release-control boundary that is
independent of artifact contents. An artifact cannot authorize itself merely by
containing an approval-looking identifier and a valid self-digest.

## Decision

### Vendor-reported is a distinct claim class

`vendor_reported` means only: a model vendor directly reported the preserved
raw result in a certified, immutable source snapshot. It is distinct from
`benchmark_owned_reported`, where the benchmark owner directly published the
result. Neither class says that the platform reran the benchmark, independently
verified the score, or agrees with the vendor's methodology.

The class is orthogonal to the legacy `O0`–`O5` source metadata. Those labels
remain historical source descriptors and do not by themselves classify,
certify, review, publish, or release a claim. This candidate does not remap
existing rows or infer a claim class from a hostname, model provider, source
name, or officialness level.

A future durable claim-class field or decision must be append-only, bind the
exact source revision, and use an accountable decision. Until that shared
contract exists, vendor-reported evidence must not be represented as
benchmark-owned evidence, and absence of a class remains unresolved rather
than defaulting upward.

### Release authorization is external and exact

The release artifact retains its release-approval reference and canonical
self-digest, but a separate `official-release-authorization-v1` record is the
only release pin consumed by the activation seam. It contains exactly:

- `artifactId`;
- `contentSha256`;
- `releaseApprovalDecisionId`; and
- `policyVersion`.

All four values must exactly match the validated v2 artifact. The
authorization record is not embedded in the artifact, and neither a release
artifact nor an authorization-looking fixture authorizes itself. Missing,
malformed, extra, or mismatched authorization fails closed to the existing
Official-unavailable behavior.

The ledger builder in this candidate is pure and output-path-free. It accepts
only the validated eligible-feed contract plus explicit public display and
evidence metadata, returns deterministic canonical v2 bytes, and creates no
decision, durable artifact record, authorization, or publication. The shipped
runtime imports neither v2 bytes nor an authorization record, so its mode and
availability do not change.

Canonicalization remains contract-specific. Official-feed candidate v1 keeps
its existing compact, key-sorted, ASCII-escaped Python serialization and
digest behavior byte-for-byte. The release builder does not reuse or redefine
that helper: it has a separate v2 serializer matching the pre-existing browser
`JSON.stringify`/Web Crypto parser, including unescaped Unicode and JSON's
single-number representation. Both remain under their already published
artifact labels; this candidate does not reinterpret an existing v1 digest.
The sealed v2 document must then validate against the checked-in v2 JSON Schema
with format checks before the builder returns it.

`reportedAt` is copied verbatim from the claim's preserved `date_raw`; a
date-only or otherwise non-RFC3339 value is rejected rather than coerced. The
only timestamp representation change is release-local: the ledger's internal
UTC `snapshotCapturedAt` projection receives an explicit `Z` in v2 while
candidate v1 retains its historical timezone-free bytes.

## Consequences

- Vendor-reported claims can be described truthfully without promotion to
  benchmark-owned or independently verified results.
- A valid artifact digest and an approval ID inside an artifact remain
  necessary but insufficient for frontend selection.
- Byte-level verification requires canonical v2 bytes. Reformatting or
  reordering an otherwise equivalent JSON document is rejected rather than
  treated as the authorized artifact representation.
- The existing unavailable v1 artifact remains the only tracked runtime input.
- This ADR does not certify a source, classify an existing claim, create a
  release approval, authorize an artifact, publish data, deploy, or enable
  Official mode.

## Open contract decisions

The accountable contract owners still need to decide where append-only claim
class decisions live and who may issue them. They also need to version the
public display-metadata and evidence-envelope inputs required to bridge the
eligible ledger projection to v2, and decide whether a later authorization
record must additionally pin frontend build identity, decision time, signer,
expiry, and revocation lineage.
