# AI Benchmark Aggregator

A single-page **AI model benchmark comparison dashboard**. It ranks models across ~17 benchmarks
organized into 8 capability categories, and lets you compare several models side by side with a
set of glassmorphic charts.

> **Status:** Demo / synthetic data by default (`Demo (synthetic)` badge).  
> **Ledger:** `ledger/` is a Python CLI that captures **official source-backed claims**.  
> UI rankings/averages are presentation-only and are never stored as ledger claims (see ADRs).

## Architecture (unified)

```text
Official sources → ledger CLI (snapshots + claims) → export-official-json
                                                      ↓
Frontend SPA  ← demo synthetic data (src/data) OR official export sample
```

See `docs/adr/` and `AGENTS.md` for trust boundary and development rules.

## Features

- **Leaderboard table** — models ranked and grouped by category, heatmap-colored cells, sortable,
  with per-benchmark detail popovers and a "best in column" footer.
- **Heatmap** — compact color-graded view of every model × benchmark score.
- **Compare view** — select up to 6 models and see them side by side as five stacked glass cards:
  1. Capability **radar** chart (SVG, hover-to-highlight)
  2. **By-category** averaged bars
  3. **Score heatmap** matrix
  4. **Per-benchmark** grouped bars
  5. **Specs** comparison table with "leads in N" badges
- **SOTA indicator** — best-in-column cells pulse with an animated gold ring.
- **Trust note** in glossary; header shows data mode label.

## Tech stack

- Vite 5 + React 18 + TypeScript (strict)
- Tailwind CSS 3 + tailwind-merge + clsx
- Radix UI primitives in `src/components/ui/*` (Toast kept on Radix per ADR-002; Base UI migration planned)
- lucide-react icons
- Hand-rolled SVG charts (no charting library)
- Python ledger under `ledger/` (Typer + SQLAlchemy + Pydantic)

## Quick start (frontend)

```bash
npm install
npm run dev        # Vite dev server
npm run typecheck  # tsc --noEmit
npm run test       # vitest unit tests
npm run build      # tsc -b && vite build — MUST stay green
```

If local `tsc` binary lacks execute bit: `./node_modules/.bin/tsc --noEmit`.

## Quick start (ledger)

```bash
cd ledger
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
benchmark-ledger init-db
benchmark-ledger seed-registry
benchmark-ledger ingest --source fake_local_fixture
benchmark-ledger claims list
benchmark-ledger review queue
pytest -q
```

## Project structure

```
src/                 # React SPA
ledger/              # Official claim capture CLI
docs/adr/            # Architecture decisions
contracts/           # Shared export schemas (growing)
.orchestrator/       # Task corpus for software orchestration
AGENTS.md            # Agent rules for both systems
```

## Notes for developers

- `getValue(modelId, benchmarkId)` (in `src/data/scores.ts`) is the **only** way to read a score.
- Sticky table columns: plain `overflow-x-auto` + sticky left — never ScrollArea.
- Ledger MVP is CLI-only (no ledger web UI).
- Secrets (`HF_TOKEN`) must never be logged or committed.
