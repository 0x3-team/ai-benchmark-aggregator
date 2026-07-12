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
- Every result claim needs `source_snapshot_id`, `official_source_id`, raw fields, and `evidence_location`.
- Prefer official APIs and structured files before scraping.
- Do not ingest articles, vendor blogs, newsletters, or social posts into the official result ledger (O0).
- If model matching is uncertain: keep `model_raw`, leave `model_entity_id` null, mark `needs_review`.
- Running ingestion twice on the same source snapshot must not create duplicate claims.
- Do not deploy to paid cloud services or trigger paid operations.
- Ledger MVP is **CLI-only** (no ledger web UI).

## Frontend rules

- `getValue(modelId, benchmarkId)` is the only score accessor.
- Use `cn(...)` for conditional classes; glass utilities from `index.css`.
- Sticky columns: plain `overflow-x-auto` + sticky left; never Radix ScrollArea.
- SOTA indicator is `.sota-cell` gold ring (not Star icon).
- Model and Benchmark sheets are independent roots; never nest Sheet in Sheet.
- Selected model colors from `modelColor(i)`.
- Null scores render as no-data (—, dashed, placeholder).
- `npm run build` / `npm run typecheck` must stay green.
- Toast may remain on Radix per ADR-002; other primitives migrate toward Base UI.

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
