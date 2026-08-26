# ADR-003: Ledger-to-UI data feed

**Status:** Superseded in part by ADR-005 (containment baseline)
**Date:** 2026-07-11  
**Decision ID:** DEC-003

## Context

The SPA must support synthetic demo data and official ledger-backed claims without mixing trust levels silently.

## Decision

**CLI JSON export first, with a fail-closed availability boundary:**

1. A future governed `benchmark-ledger export-official-json --out <path>` writes a versioned, schema-validated, provenance-complete release artifact.
2. Until that gate exists, the frontend imports only the tracked `export.unavailable.json` artifact and keeps Official mode unavailable.
3. Ignored local `export.from-ledger.json` files and sample fixtures are operator/test inputs only. They are never runtime fallback data and never prove a release.
4. Optional local HTTP API is deferred.

Trust labels: UI must show **Demo (synthetic)** and must make an unavailable Official state explicit. It must not silently substitute demo/sample data under an Official label.

Cross-benchmark averages remain **presentation-only** and must never be written back as ledger claims.

## UI-01 / UI-02 dataset and published-parser boundaries (2026-07-13)

All data-dependent React components receive an immutable, provider-scoped
snapshot. `getValue(modelId, benchmarkId)` is the only numeric score accessor;
the accompanying provenance lookup deliberately excludes `value`. This removes
the former module-global active-data switch, so a render cannot read models or
provenance from one snapshot and scores from another.

`selectDataset(...)` now implements that discriminated selection above the
provider. A requested Official mode receives an Official snapshot only after a
validated `availability: "published"` result; all unavailable results retain
the Demo snapshot and Demo label in the same React commit.

The
[`official-release-artifact-v2.schema.json`](../contracts/official-release-artifact-v2.schema.json)
is a **future-only** contract, not a public release. Its activation seam requires
exact shapes, complete UI metadata, finite values, raw claim fields, closed
typed evidence, exact source-manifest links, six-part identity ordering, one
two-key UI cell, a canonical Web Crypto digest, and an external authorization
pin for artifact ID, release decision, policy, and digest. `loadOfficialData()`
continues to import only the tracked unavailable v1 artifact. Its optional v2
input is callable only with canonical bytes and the exact external pin; no v2
document, authorization, sample, candidate projection, report, or ignored local
export is imported by the runtime. REL-05 still requires an accountable owner
to issue and connect a real authorization and immutable artifact.

## UI-03 trust-state interaction (2026-07-13)

The current unavailable state is a first-class, keyboard-operable explanation:
it explicitly says that visible values remain **Demo (synthetic)** and announces
the reason when a user requests Official. It is not styled as a successful
verification state. In a future verified, selected release, the header shows
the artifact ID, recorded approval decision and timestamp, and policy version;
the language remains limited to source-reported ledger claims and says that the
UI does not recalculate benchmark scores.

Changing a selected data source atomically resets filters, sorting, comparison
selection, sheets, and the comparison view before rendering the new immutable
snapshot. Focus returns to the newly active data-source control after that
commit, so keyboard users do not remain in stale data-dependent UI.

## UI-04 claim evidence and source manifest (2026-07-14)

The future governed published path has a reusable, keyboard-operable claim
evidence disclosure. It is deliberately unavailable for Demo data and for any
entry that cannot be resolved against the immutable release source manifest.
For each individual Official score surface, the disclosure shows the verbatim
raw model, benchmark, and score fields; the claim ID; source URL; source and
snapshot IDs; capture/retrieval and reported timestamps; typed evidence
location; release policy and approval context; and the selected display
identity. A custom score-shaped trigger is given a descriptive accessible name
when it lacks one, and Escape returns focus to that trigger.

Resolution is fail-closed even at the UI boundary: the entry must be marked
published, agree with its display identity and top-level source/snapshot IDs,
and exactly match its source-manifest record. A missing or mismatched manifest
entry renders no evidence control rather than presenting potentially mixed
provenance. Links are emitted only for credential-free HTTPS URLs; malformed
or empty URLs render as text/no link.

The future Official header consumes the same release source manifest through a
separate disclosure listing source, manifest key, revision and revision
decision, snapshot, retrieval timestamp, and source type. These disclosures
are popovers, not Sheets, so the model and benchmark Sheets remain independent
roots and are never nested.

## Consequences

- No runtime coupling between Python and Vite in MVP.
- Operators control when a separately approved official artifact is prepared.
- A clean checkout can build without ledger data or any ignored generated export.
- The artifact contract and publication decision are governed by ADR-005 and later feed work, not by the presence of local JSON.

## LDR-08 candidate projection (2026-07-13)

The ledger now has an internal, offline-only candidate projection contract at
[`official-feed-candidate-v1.schema.json`](../contracts/official-feed-candidate-v1.schema.json).
It is intentionally **not** the release artifact described above:

1. `project_official_feed(session)` is pure/read-only and returns only
   `availability: "candidate"`; it has no output-path API.
2. A selected cell requires the capture-time source revision's single current
   certified decision and matching policy, an immutable snapshot, all-pass
   validations, one effective `validation_reviewed` claim decision, and one
   effective `approved` publication decision referencing that review.
3. Capture-time provenance is retained even if the logical source catalog later
   advances to a newer revision. A revocation on the same captured revision is
   still disqualifying.
4. Cells are ordered and unique by `(model, benchmark, metric, split, setting,
   evaluation version)`. More than one eligible claim for a cell raises a
   deterministic `FeedConflictError` report; it does not return partial data.
5. The candidate includes source/snapshot/review/publication provenance and a
   canonical SHA-256 manifest. It has no generated-at timestamp, so identical
   inputs produce identical bytes and digest. Ineligible claims are retained as
   deterministic `excludedClaims` reason records; LDR-09 owns the fuller legacy
   inventory rather than treating a captured status as implicit approval.

`export-official-json` remains disabled until FEED-01 defines immutable artifact
ownership and REL-05 authorizes publication. The current frontend parser accepts
only the tracked unavailable fixture and cannot consume this candidate shape.

## LDR-09 legacy inventory (2026-07-13)

[`legacy-inventory-v1.schema.json`](../contracts/legacy-inventory-v1.schema.json)
defines a second offline-only read model for reconciliation:

1. `benchmark-ledger reports legacy-inventory` writes one deterministic JSON
   document to stdout and does not append a review/publication decision, update
   a captured field, read snapshot bytes, or create an artifact file.
2. It inventories **every** `ResultClaim` and `SourceSnapshot`, including
   snapshots with zero claims. Each claim records a report-only disposition:
   `candidate`, `omitted`, or `conflicted`; this is an explanation, never a
   replacement for a stored ledger status.
3. Omission reason codes reuse the LDR-08 candidate gates. Eligible duplicate
   cells become `conflicted` with `DISPLAY_CELL_CONFLICT`, while the candidate
   projection itself remains strict and returns no partial feed.
4. The report retains raw claim fields, evidence-location hashes, source and
   decision references, plus clearly labelled observed legacy risk signals
   (for example derived, synthetic, discovery, provisional, or explicit
   quarantine evidence). Signals do not promote or rewrite evidence.
5. Its canonical self-hash has no generated-at field, so repeat reads of the
   same database have identical bytes. It is useful during copied-DB recovery
   rehearsals, but it is not a release artifact and does not re-enable public
   export or frontend Official mode.

## LDR-10 bounded coverage census (2026-07-15)

The coverage contracts add an earlier, configuration-level read model without
widening the feed boundary:

1. [`coverage-universe-v1.schema.json`](../contracts/coverage-universe-v1.schema.json)
   defines a versioned product scope. Its explicit benchmark set and source
   classes define bounded completeness; they do not claim internet-wide
   completeness, source certification, reuse authority, or publication.
2. `benchmark-ledger coverage status --format json|markdown` accounts for every
   raw benchmark, source, and model registry row. It preserves duplicates,
   collisions, unknown references, and omissions as blockers instead of
   resolving them by file or row order.
3. The SQLite input is quarantined evidence. Current, invalid, and absent local
   targets are inspected without ORM initialization, migration, repair, or
   writes; a valid blocked report exits `1`, while malformed inputs exit `2`.
4. The canonical census excludes mutable generation time from content identity,
   binds every input-file digest, and renders JSON and Markdown from one
   validated payload.
5. Universe approval is projected explicitly. A `draft_unapproved` revision
   must carry a blocking `UNIVERSE_REVISION_UNAPPROVED` issue; the census cannot
   create or infer its own owner approval.
6. Census readiness means reconciliation integrity only. Coverage freshness is
   `not_assessed`; time-relative staleness belongs to a future immutable
   scheduled-cycle receipt with an explicit deterministic slot/as-of binding.
7. Coverage census, discovery target, and discovery candidate records remain
   report/proposal-only. They cannot create or promote a source revision,
   snapshot, claim, review/publication decision, release artifact, or frontend
   Official dataset.
