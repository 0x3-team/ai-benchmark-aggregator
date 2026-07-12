# Contributing to AI Benchmark Aggregator

Thanks for contributing to **0x3-team/ai-benchmark-aggregator**!

This repo has two components:
- **Frontend** (`src/`) — React SPA, Vite, TypeScript strict, Tailwind
- **Ledger** (`ledger/`) — Python CLI (Typer + SQLAlchemy + Pydantic) for official benchmark claims

---

## Quick Start

### Frontend
```bash
npm install
npm run dev          # dev server
npm run typecheck    # tsc --noEmit (must pass)
npm run test         # vitest
npm run build        # tsc -b && vite build (must pass)
```

### Ledger
```bash
cd ledger
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
benchmark-ledger init-db
benchmark-ledger seed-registry
benchmark-ledger ingest --all
benchmark-ledger review auto-verify-matched
benchmark-ledger export-official-json
pytest -q            # 49 tests must pass
```

---

## Development Rules (from AGENTS.md)

### Ledger (CLI)
- **Preserve raw source values exactly** — `model_raw`, `benchmark_raw`, `score_raw`, etc.
- **Never overwrite claims** — source changes create new snapshots + new claims
- **Snapshot before extraction** — every claim needs `source_snapshot_id`
- **Idempotent ingestion** — running twice on same snapshot = no duplicate claims
- **Model matching uncertainty** → keep `model_raw`, leave `model_entity_id` null, mark `needs_review`
- **No paid APIs / cloud services** in ledger

### Frontend (SPA)
- `getValue(modelId, benchmarkId)` is the **only** score accessor
- Use `cn(...)` for conditional classes; glass utilities from `src/index.css`
- Sticky columns: `overflow-x-auto` + `position: sticky; left: 0` — never `ScrollArea`
- SOTA indicator = `.sota-cell` gold ring (not Star icon)
- Null scores render as `—` (dashed), placeholder bars, no-data state
- Model colors from `modelColor(i)` — consistent across radar/bars/heatmap
- `npm run typecheck && npm run build && npm test` **must stay green**

---

## Pull Request Checklist

Before opening a PR, ensure:

- [ ] **Ledger tests pass**: `cd ledger && pytest -q`
- [ ] **Frontend gates pass**: `npm run typecheck && npm run build && npm test`
- [ ] **Export sanity**: `src/data/official/export.from-ledger.json` has ≥1000 models, ≥20 benchmarks, ≥2000 scores (if data pipeline changed)
- [ ] **New adapters**: Fixture test added in `ledger/tests/`
- [ ] **New benchmark source**: Added to `ledger/app/registry/official_sources.yaml` with correct `parser_config`
- [ ] **Docs updated**: `README.md` if architecture changed; `docs/adr/` for new decisions
- [ ] **No secrets committed** — `.env`, tokens, keys

---

## Issue Templates

Use the templates in `.github/ISSUE_TEMPLATE/`:
- **Bug Report** — for defects in ledger, frontend, or pipeline
- **Feature Request** — for new sources, adapters, UI features, workflow changes

---

## Code Owners

See `.github/CODEOWNERS` — reviews auto-assigned to:
- `@0x3-team/core` — global, CI, docs
- `@0x3-team/ledger` — `ledger/**`
- `@0x3-team/frontend` — `src/**`, `package.json`, `vite.config.ts`

---

## Branching & Merging

- **Main branch**: `main` (protected)
- **Feature branches**: `feat/<short-desc>`, `fix/<short-desc>`
- **PRs**: Require `verify` workflow + 1 review from CODEOWNERS
- **Commits**: Conventional commits (`feat:`, `fix:`, `chore:`, `docs:`, `refactor:`)

---

## Adding a New Benchmark Source

1. **Find the official source** — API, structured file (JSON/CSV/Parquet), or scrapeable HTML table
2. **Choose adapter** — `generic_json`, `generic_csv`, `hf_datasets_server`, `artificial_analysis_api`, `github_yaml`, `taubench_s3`, `frontiermath_epoch`, `imo_answerbench`, `helm_json`, or write new
3. **Add to `official_sources.yaml`** — include `benchmark_id`, `source_url`, `parser_config`, `adapter_type`
4. **Write fixture test** — `ledger/tests/test_adapter_<name>.py` with real sample data
5. **Run pipeline** — `seed-registry` → `ingest --source <id>` → `review auto-verify-matched` → `export-official-json`
6. **Verify in UI** — switch to Official mode, confirm benchmark appears with scores

---

## License

By contributing, you agree your contributions are licensed under the MIT License.