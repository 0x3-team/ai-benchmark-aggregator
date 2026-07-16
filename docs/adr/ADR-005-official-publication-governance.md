# ADR-005: Official publication governance and containment

**Status:** Accepted for the remediation containment phase  
**Date:** 2026-07-13  
**Decision ID:** DEC-005

## Context

The ledger currently contains routes that can treat fixtures, discovery metadata,
blogs, fallback values, and derived aggregates as Official results. Its generated
frontend export is ignored by Git, and registry reseeding previously deleted
source-derived evidence. A score must not become public merely because a parser
or local build accepted it.

## Decisions

| Topic | Decision for this phase |
| --- | --- |
| Publication decision | Official publication is disabled. A future public claim requires an explicit, recorded human publication decision; `parser_verified` and `human_verified` alone are not publication approval. |
| Source eligibility | Only deliberately certified, direct, structured official result sources may enter the future production path. O0 articles, vendor blogs, newsletters, social posts, mock/fake/fallback data, discovery metadata, and locally derived scores are never Official claims. |
| Display identity | The MVP will publish at most one approved metric, split, setting/configuration, and evaluation version per benchmark. The UI may not silently choose among alternatives. |
| Conflicts | A future deterministic export fails and reports the conflict; it never resolves duplicate display cells by array order or a last-write-wins map. |
| Build artifact | The repository tracks a schema-valid unavailable artifact for normal builds. A future published artifact must be immutable, versioned, content-hashed, provenance-complete, and approved outside a local ignored export. |
| Legacy evidence | Existing claims and snapshots remain queryable but unpublished/quarantined. They are neither deleted nor rewritten to look approved. |

## Consequences

- Demo remains visibly synthetic and is the only selectable dataset in this release.
- No currently registered source is certified by the temporary governance declaration, so default ingestion fails before fetching or writing evidence.
- `review auto-verify-matched`, the legacy `review mark-human-verified` shortcut, and `export-official-json` are disabled. `review map-model` may only append an identity decision; it cannot promote validation, capture status, or publication.
- Registry refresh is non-destructive; source identity collisions fail instead of remapping historic evidence.
- This ADR does not authorize live ingestion, schema migration, benchmark execution, data deletion, or an Official release.

## Executable examples

| Case | Expected result |
| --- | --- |
| Active O5 API with no governance declaration | Rejected before fetch/write. |
| Fake fixture, even if marked O5 | Rejected in production; allowed only through test monkeypatching in temporary test databases. |
| Discovery endpoint or `/blog` source | Rejected. |
| Existing legacy claim | Still queryable; cannot be exported or presented as Official. |
| Missing/invalid Official artifact | Frontend remains in Demo and shows an unavailable explanation. |

## Follow-up

LDR-01 onward replace the temporary registry declaration with source revisions,
append-only publication decisions, validation evidence, deterministic projection,
and a release-artifact manifest. Official mode may be re-enabled only by the
release gate in the remediation plan.

### LDR-08 implementation note (2026-07-13)

The deterministic projection portion is now available for offline fixtures as a
candidate-only, canonical-digest contract. It does **not** change this ADR's
publication decision: the public exporter, frontend Official parser, and
availability state remain contained. The projection requires a hypothetical
`approved` publication record in fixtures, but no production approval writer is
enabled during containment.

### FEED-01 containment artifact (2026-07-13)

The tracked `src/data/official/export.unavailable.json` is now a versioned
`official-release-artifact` with a canonical SHA-256 self-digest, an artifact
identity, and an explicit zero-data provenance manifest. The offline
`npm run verify:official-artifact` gate validates the exact shape, canonical
digest, unavailable-only policy, zero counts, and empty source/claim arrays.
It accepts no input or output paths, so a local LDR-08 candidate, LDR-09
report, sample, or ignored export cannot be repackaged by this containment
command. Both normal frontend CI and the fresh `git archive` build run it.

This proves the safe baseline, not a published feed. A later approved release
preparation contract must define the published artifact shape and provenance
requirements separately, then pass REL-05 before the frontend parser changes.

### UI-02 future parser seam (2026-07-13)

`official-release-artifact-v2` now records that future shape without changing
the containment decision. Its frontend parser is dormant and accepts a document
only when Web Crypto verifies the canonical content digest **and** a separately
supplied release authorization pins the artifact ID, publication-decision ID,
policy, and digest. The app supplies neither a v2 document nor that
authorization; `loadOfficialData()` remains fixed to v1 unavailable content.

This is intentionally stricter than the ledger's candidate feed: the v2
artifact must include complete current UI metadata, a closed evidence envelope,
all raw fields, one full six-part display identity, exact source-manifest
cross-links, deterministic ordering, and no duplicate `(modelId, benchmarkId)`
pair. Matching schema or digest alone is not publication approval. REL-05 owns
the controlled authorization source, immutable artifact retention, release
verification, and the explicit decision to connect this seam to the UI.

### UI-03 visible trust boundary (2026-07-13)

The containment build exposes an available-on-request explanation rather than a
disabled-looking success control: requesting Official announces that the
visible dataset remains Demo (synthetic). A future published result may show
artifact, approval, timestamp, and policy metadata, but those facts describe a
governed release decision; they do not imply that every displayed claim has
been independently reverified by the UI. Data-source changes also clear
data-dependent UI state and restore focus to the active source control.
