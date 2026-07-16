# AGENTS.md

## Project

This repository is the **AI Benchmark Platform**:

1. **Frontend** (`src/*`) — React SPA for model benchmark comparison (demo synthetic data + planned official mode).
2. **Ledger** (`ledger/*`) — Python CLI that captures official benchmark results as immutable source-backed claims.

The ledger does **not** run benchmarks and does **not** recalculate scores.

## Core ledger rules

- Preserve raw source values exactly (`model_raw`, `benchmark_raw`, `score_raw`, …).
- Do not overwrite result claims; source changes create new snapshots and new claims.
- Snapshot official source content before extraction.
- Every new result claim needs `source_snapshot_id`, `official_source_id`, the exact source-revision certification decision, raw fields, and a typed `evidence_location` that re-resolves those raw values in the immutable snapshot.
- Reject uncertified/unsafe source revisions, mock/fallback/derived fetch artifacts, unapproved dimensions, and non-finite or nonnumeric score lexemes before a claim is written. Never coerce a raw source value to make it admissible.
- Prefer official APIs and structured files before scraping.
- Do not ingest articles, vendor blogs, newsletters, or social posts into the official result ledger (O0).
- If model matching is uncertain: keep `model_raw`, leave `model_entity_id` null, mark `needs_review`.
- Manual identity corrections append a `ClaimReviewDecision`; they never rewrite a captured claim or promote validation, capture status, or publication.
- Running ingestion twice on the same source snapshot must not create duplicate claims.
- The LDR-08 candidate feed is an offline read model only. It may select a cell
  only when capture-time source certification/policy, snapshot provenance,
  all-pass validation, effective `validation_reviewed` review, and effective
  `approved` publication decision are all present. Use all six display
  dimensions as the identity; duplicate eligible cells must fail with a report,
  never select by order. Do not enable public export or frontend Official mode
  merely because a candidate projection exists.
- The LDR-09 `reports legacy-inventory` command is also read-only. Its
  candidate/omitted/conflicted labels are report-only reconciliation facts; do
  not write them back to claims or decisions, use them as a frontend artifact,
  or resolve conflicts by row order.
- The COV-01/02 `coverage status` command is a bounded, report-only census. It
  must account for every raw registry row, preserve duplicate/collision facts,
  and inspect absent/current/invalid SQLite only through a no-create read-only
  path. A Coverage Universe revision defines product scope, not "all of the
  internet"; configured, active, discovered, or in-scope never means certified,
  approved, publishable, or Official. Coverage JSON/Markdown and discovery
  candidate records are never frontend inputs. A `draft_unapproved` universe
  must remain an explicit blocking report fact; the census cannot approve it.
  Census readiness is reconciliation-only and never establishes freshness;
  time-relative freshness requires a separate deterministic scheduled receipt.
- DATA-10 recovery manifests and receipts are recovery evidence only. They must
  bind one exact terminal-cycle backup to every retained snapshot byte, restore
  only into fresh relational and object targets, and re-resolve exact schema,
  row, lineage, cycle, and object denominators before success. Never clean,
  repair, overwrite, or reuse an attempted target. Local roots and disposable
  PostgreSQL prove mechanics only; they do not prove provider independence,
  retention, production RPO/RTO, cutover authority, publication, or Official
  frontend eligibility. The at-most-one-completed-cycle-loss value remains a
  target until approved provider drills prove it. Recovery evidence outputs
  must resolve outside every primary, recovery, and restore object root. A
  PostgreSQL target must match the exact reviewed PG16 database/public-schema
  baseline before it is marked, immediately before restore, and after restore;
  database-scoped publications, subscriptions, event triggers, large objects,
  settings, foreign-data objects, default ACLs, labels, policies, or other
  unsupported state fail closed rather than being omitted from freshness.
- All durable schema changes use the versioned Alembic path. `init-db` is only for an empty database; preflight and migrate only a verified disposable copy, retain its SQLite backup, and never use downgrade/delete as recovery.
- A logical source is not its mutable configuration: preserve immutable source revisions, bind snapshots to their exact revision, and record review/publication outcomes as append-only decisions. Legacy evidence stays quarantined until a new decision path approves it.
- Do not deploy to paid cloud services or trigger paid operations.
- Ledger MVP is **CLI-only** (no ledger web UI).

## Frontend rules

- `getValue(modelId, benchmarkId)` is the only score accessor.
- Dataset state must come from an immutable `DatasetProvider`; do not add a
  module-global active registry or a default Demo fallback. Context provenance
  is value-free, so consumers cannot bypass `getValue` with a raw score entry.
- Use `cn(...)` for conditional classes; glass utilities from `index.css`.
- Sticky columns: plain `overflow-x-auto` + sticky left; never Radix ScrollArea.
- SOTA indicator is `.sota-cell` gold ring (not Star icon).
- Model and Benchmark sheets are independent roots; never nest Sheet in Sheet.
- Selected model colors from `modelColor(i)`.
- Null scores render as no-data (—, dashed, placeholder).
- `npm run build` / `npm run typecheck` must stay green.
- Toast may remain on Radix per ADR-002; other primitives migrate toward Base UI.
- During FEED-01 containment, `src/data/official/export.unavailable.json` is the
  only frontend artifact. Its immutable release-artifact schema and canonical
  digest must pass `npm run verify:official-artifact`; candidate projections,
  legacy reports, samples, and ignored local exports are never accepted as
  frontend inputs.
- The v2 published-artifact parser is dormant. Do not import a v2 artifact or
  turn Official on until REL-05 supplies a governed authorization that pins the
  artifact ID, publication decision, policy, and verified digest. Any future
  mode change must use `selectDataset(...)` above `DatasetProvider`, so its
  mode label and immutable snapshot change as one discriminated render.
- Data-source status must state whether visible values remain Demo (synthetic).
  A future Official display may show artifact, approval, timestamp, and policy
  metadata without implying a stronger per-claim verification guarantee.
  Switching a selected source clears data-dependent filters, sorting,
  comparison/sheet state, and returns keyboard focus to the active source
  control.

## Trust boundary

- Ledger stores **claims**: “source X reported score Z”.
- UI rankings/averages are presentation-only and must not be stored as official claims.
- Dual mode: demo synthetic vs official ledger export.

## Development workflow

- Keep changes small and testable.
- Fixture tests for every adapter.
- Run ledger tests: `cd ledger && pytest -q`.
- Run frontend: `npm run typecheck` and `npm run build`.
- Update README/AGENTS when CLI or trust UI changes.

## Local model orchestration

- Before delegating project work across local model harnesses, consult `docs/local-model-guideline-ledger.md` and record the routing decision.
- Treat the guideline ledger as local operational evidence only; it is never an official benchmark claim or frontend data source.
- The parent agent must review every delegated result, run the relevant verification, and append the task outcome and lesson to the guideline ledger.
