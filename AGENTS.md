# AGENTS.md

## Project

This repository is the **AI Benchmark Platform**:

1. **Frontend** (`src/*`) — React SPA that shows a governed Official release or an honest awaiting-publication state.
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
- All durable schema changes use the versioned Alembic path. `init-db` is only for an empty database; preflight and migrate only a verified disposable copy, retain its SQLite backup, and never use downgrade/delete as recovery.
- A logical source is not its mutable configuration: preserve immutable source revisions, bind snapshots to their exact revision, and record review/publication outcomes as append-only decisions. Legacy evidence stays quarantined until a new decision path approves it.
- Do not deploy to paid cloud services or trigger paid operations.
- Ledger MVP is **CLI-only** (no ledger web UI).

## Frontend rules

- `getValue(modelId, benchmarkId)` is the only score accessor.
- Overall ranking is UI-only: use the complete immutable active benchmark cohort,
  require at least 60% published-score coverage for eligibility, and give every
  missing cohort cell the deterministic `models.length + 1` rank penalty before
  averaging across that full cohort. Keep raw coverage visible and never store
  this derived ranking as a ledger claim.
- `benchmark.category` in the governed Official artifact is the sole comparison
  class truth. `embedding` is its own class; all other categories are general.
  General and embedding rankings use independent complete benchmark and active
  model cohorts. A model with scores in both classes participates independently.
- Dataset state must come from an immutable `DatasetProvider`; do not add a
  module-global active registry or a default Demo fallback. Context provenance
  is value-free, so consumers cannot bypass `getValue` with a raw score entry.
- Use `cn(...)` for conditional classes; glass utilities from `index.css`.
- Charts: EvilCharts (Recharts 3 + Motion), vendored read-only at
  `src/components/evilcharts/`; app adapters in `src/components/charts/`;
  data builders in `src/lib/chartData.ts`. All new charts MUST use EvilCharts;
  hand-rolled SVG/div charts are forbidden. Heatmap tables (ScoreTable,
  ScoreHeatmap, ModelDetail dots) are data tables, not charts, and remain on
  `heatmapColor()`.
- Sticky columns: plain `overflow-x-auto` + sticky left; never Radix ScrollArea.
- SOTA indicator is `.sota-cell` gold ring (not Star icon).
- Model and Benchmark sheets are independent roots; never nest Sheet in Sheet.
- Selected model colors from `modelColor(i)`.
- Null scores render as no-data (—, dashed, placeholder).
- `npm run build` / `npm run typecheck` must stay green.
- Toast may remain on Radix per ADR-002; other primitives migrate toward Base UI.
- Data-source status must state whether visible data is awaiting publication
  or from a governed Official release. Switching a selected source clears
  data-dependent filters, sorting, comparison/sheet state, and returns
  keyboard focus to the active source control.

## Trust boundary

- Ledger stores **claims**: “source X reported score Z”.
- UI rankings/averages are presentation-only and must not be stored as official claims.
- Dual mode: awaiting data vs official ledger export.

## Development workflow

- Keep changes small and testable.
- Fixture tests for every adapter.
- Run ledger tests: `cd ledger && pytest -q`.
- Run frontend: `npm run typecheck` and `npm run build`.
- This repository is public. Keep it public; do not change visibility as a CI workaround. Treat any future CI failure as a workflow, runner, or account issue and diagnose the exact check evidence.
- Update README/AGENTS when CLI or trust UI changes.

## Local model orchestration

- Before delegating project work across local model harnesses, record the routing decision and review every delegated result.
- Treat local operational evidence as internal only; it is never an official benchmark claim or frontend data source.

## Stable local development origin

- `npm run dev:portless` is an opt-in local-development path. Keep `npm run dev` unchanged as the direct fallback.
- Use the URL returned by `portless get ai-benchmark-aggregator`; never guess a port or hostname.
- Do not use Portless `--force`, LAN, wildcard, tunnel, service, trust, or hosts-sync modes in this repository.
- A Portless page is local runtime evidence only. It is not CI, Preview, deployment, production, or official benchmark evidence.
