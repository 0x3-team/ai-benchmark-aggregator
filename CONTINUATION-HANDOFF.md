# CONTINUATION-HANDOFF — 2026-07-12

## What we were doing
Phase A of the benchmark adapters plan: wiring 4 new adapters (τ-bench, HELM, IMO-AnswerBench, FrontierMath) to lift the ledger from 24 → 28 live-score benchmarks.

## What succeeded (verified)
- 4 new adapters built by workers (`taubench_s3`, `helm_json`, `imo_answerbench`, `frontiermath_epoch`) — files exist, registered, 49 ledger tests pass.
- τ-bench adapter fixed for S3 pagination → extracts **47 real claims** from live S3.
- `seed-registry` idempotency fix: truncates source-derived tables + reloads from YAML to prevent stale-row collisions.

## The open problem (blocked)
IMO-AnswerBench's public CSV (`answerbench_v2.csv`) is the **problem set** (Problem ID, Problem, Short Answer…), NOT per-model scores. No public per-model score file exists → IMO cannot be auto-wired. It's set `inactive` with an honest note.

HELM and FrontierMath URLs 404'd during discovery; adapters built but sources remain `inactive` pending live endpoint rediscovery.

## Next concrete step
- Re-run full ingest (`--all`) after the seed fix to repopulate all claims (seed truncates + reloads, so all prior claims were wiped).
- Verify export ≥ 24 benchmarks, > 2,715 scores.
- Then wire the remaining 30 benchmarks' sources (Phase B/C of the plan).

## Files changed since last green state
- `ledger/app/db/repositories.py` — `upsert_official_source` now also matches on (benchmark_id, source_url) to prevent collisions.
- `ledger/app/registry/seed_loader.py` — truncates source-derived tables before re-seeding to guarantee idempotency.
- `ledger/app/registry/official_sources.yaml` — removed stale `taubench_live_s3` duplicate; set `imo_answerbench_github` to `inactive` with accurate note.
- `ledger/app/ingestion/adapters/taubench_s3.py` — worker-built adapter (pagination fix pending).
- `ledger/app/ingestion/adapters/helm_json.py` — worker-built adapter.
- `ledger/app/ingestion/adapters/imo_answerbench.py` — worker-built adapter.
- `ledger/app/ingestion/adapters/frontiermath_epoch.py` — worker-built adapter.

## Verification gates last run
- Ledger tests: 49/49 passed
- FE typecheck: clean
- FE build: green
- FE tests: 6/6 passed
- Export: 24 benchmarks, 2,258 models, 2,715 scores (pre-truncate; needs re-ingest)

## How to resume
```bash
cd /srv/hermes/development/ai-benchmark-aggregator/ledger
source .venv/bin/activate
benchmark-ledger seed-registry
benchmark-ledger ingest --all
benchmark-ledger review auto-verify-matched
benchmark-ledger export-official-json
cd ..
npm run typecheck && npm run build && npm test
```
Then confirm export ≥ 24 benchmarks, > 2,715 scores.
