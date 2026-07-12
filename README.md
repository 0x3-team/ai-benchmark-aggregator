# AI Benchmark Aggregator

**Organization:** 0x3-team  
**Repository:** `0x3-team/ai-benchmark-aggregator`  
**Status:** Private — Production-ready dual-mode benchmark platform

A single-page **AI model benchmark comparison dashboard** with a **dual-mode data architecture**:

| Mode | Source | Purpose |
|------|--------|---------|
| **Demo (Synthetic)** | `src/data/scores.ts` — curated demo fixtures | Instant UI development, zero dependencies |
| **Official (Ledger)** | `ledger/` CLI → `src/data/official/export.from-ledger.json` | Source-backed, immutable claims from official results |

> **Trust boundary:** Ledger stores *claims* ("source X reported score Z"). UI rankings/averages are **presentation-only** — never persisted as official claims.

---

## Quick Start

### Frontend (React SPA)

```bash
npm install
npm run dev          # Vite dev server
npm run typecheck    # tsc --noEmit (must pass)
npm run test         # vitest unit tests
npm run build        # tsc -b && vite build (must pass)
```

### Ledger (Python CLI)

```bash
cd ledger
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
benchmark-ledger init-db
benchmark-ledger seed-registry
benchmark-ledger ingest --all           # Pulls from all 50+ official sources
benchmark-ledger review auto-verify-matched
benchmark-ledger export-official-json  # Writes src/data/official/export.from-ledger.json
pytest -q                               # 49 tests must pass
```

---

## Project Structure

```
ai-benchmark-aggregator/
├── .github/                    # GitHub org config
│   ├── workflows/verify.yml    # CI: ledger tests + frontend typecheck/build/test + export sanity
│   ├── ISSUE_TEMPLATE/         # Bug report & feature request templates
│   ├── dependabot.yml          # Weekly dependency updates (npm, pip, actions)
│   └── CODEOWNERS              # Auto-review assignment
├── src/                        # React SPA (Vite + TS + Tailwind)
│   ├── components/             # UI components (glassmorphism, charts, tables)
│   ├── data/                   # Data access layer
│   │   ├── official/           # Ledger export (git-ignored, regenerated)
│   │   ├── registry.ts         # Benchmark/model catalog
│   │   └── scores.ts           # getValue() — single score accessor
│   ├── lib/                    # Utilities (colors, aggregation, categories)
│   └── types.ts                # Shared TypeScript types
├── ledger/                     # Python CLI (Typer + SQLAlchemy + Pydantic)
│   ├── app/
│   │   ├── cli.py              # Typer commands
│   │   ├── db/                 # SQLAlchemy models, engine, repositories
│   │   ├── ingestion/          # Adapters (official_sources.yaml → claims)
│   │   ├── matching/           # Model/benchmark alias resolution
│   │   ├── registry/           # official_sources.yaml + seed_loader
│   │   ├── export/             # export-official-json
│   │   └── schemas/            # Pydantic boundaries
│   ├── tests/                  # 49 pytest fixtures + tests
│   └── pyproject.toml
├── docs/adr/                   # Architecture Decision Records (ADR-001..004)
├── AGENTS.md                   # Agent rules for both systems
├── CONTINUATION-HANDOFF.md     # Session continuity notes
├── package.json
├── tsconfig.json
└── vite.config.ts
```

---

## CI / CD

**GitHub Actions** (`.github/workflows/verify.yml`) runs on every PR:

1. **Ledger tests** — `pytest -q` (49 tests)
2. **Frontend** — `npm run typecheck && npm run build && npm test`
3. **Export sanity** — verifies `export.from-ledger.json` has ≥1000 models, ≥20 benchmarks

**Branch protection** recommended: require `verify` workflow + code review from `CODEOWNERS`.

---

## Data Pipeline

```
Official Sources (API/CSV/JSON/HTML/S3/GCS)
         ↓
ledger/official_sources.yaml   # 50+ source definitions (active/inactive)
         ↓
benchmark-ledger seed-registry # Upserts sources + benchmark/model catalogs
         ↓
benchmark-ledger ingest --all  # Snapshots source → extracts claims (idempotent)
         ↓
benchmark-ledger review auto-verify-matched  # Parser-verified → human review queue
         ↓
benchmark-ledger export-official-json        # Frontend-consumable JSON
         ↓
src/data/official/export.from-ledger.json    # Committed, powers Official mode
```

**Key adapters (50+ sources):**

| Adapter | Sources |
|---------|---------|
| `generic_json` | MMLU, GPQA, MATH, HumanEval, MBPP, LiveBench, LiveCodeBench, LMSYS, SWE-Bench, PaperBench, BFCL, GAIA, AgentBench, Terminal-Bench, WebArena, APEX-Agents, ToolBench, BrowseComp, TruthfulQA, FrontierCode, Aider Polyglot, τ-bench (S3) |
| `generic_csv` | HELM (JSON→CSV), IMO AnswerBench |
| `hf_datasets_server` | MMLU-Pro, GPQA Diamond, HLE |
| `artificial_analysis_api` | GPQA Diamond (AA), MATH-500 (AA), AIME 2024/2025 (AA) — *requires API key* |
| `github_yaml` | Aider Polyglot (YAML in repo) |
| `taubench_s3` | τ-bench (S3 paginated) |
| `frontiermath_epoch` | FrontierMath (Epoch AI) |
| `imo_answerbench` | IMO AnswerBench (GitHub CSV — inactive, no model scores) |
| `helm_json` | HELM (GCS — URL 404, needs rediscovery) |

---

## Environment Variables

| Variable | Required For | Notes |
|----------|--------------|-------|
| `HF_TOKEN` | HF datasets server sources | Read token, never log |
| `ARTIFICIAL_ANALYSIS_API_KEY` | AA API sources | [REDACTED] in .env.example |

Copy `ledger/.env.example` → `ledger/.env` and fill.

---

## Development Rules (from AGENTS.md)

- **Ledger:** Preserve raw source values exactly. No recalculation. Idempotent ingestion (rerun = no dup claims).
- **Frontend:** `getValue(modelId, benchmarkId)` is the **only** score accessor. Null scores render as `—` (dashed).
- **UI:** Glassmorphism via `cn(...)` + Tailwind. Sticky columns = `overflow-x-auto` + sticky left. SOTA = gold ring (`.sota-cell`).
- **Quality gates:** `npm run typecheck && npm run build && npm test` + `cd ledger && pytest -q` **must pass** before merge.

---

## ADRs (Architecture Decisions)

| ID | Title | Summary |
|----|-------|---------|
| ADR-001 | Monorepo Layout | `src/` + `ledger/` at root, shared `AGENTS.md` |
| ADR-002 | Toast Strategy | Radix Toast retained; other primitives → Base UI |
| ADR-003 | Data Feed | Dual-mode: demo synthetic + ledger export |
| ADR-004 | Python Stack | Typer, SQLAlchemy 2.0, Pydantic v2, Typer CLI |

See `docs/adr/` for full records.

---

## License

MIT — see `LICENSE`.

---

## Team & Contacts

| Role | GitHub Team | Slack |
|------|-------------|-------|
| Core / Infra | `@0x3-team/core` | #0x3-core |
| Ledger | `@0x3-team/ledger` | #0x3-ledger |
| Frontend | `@0x3-team/frontend` | #0x3-frontend |

For questions, open an issue using the templates in `.github/ISSUE_TEMPLATE/`.