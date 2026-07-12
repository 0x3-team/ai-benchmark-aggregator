# benchmark-ledger

Official benchmark result capture system (CLI-first). Captures immutable source-backed claims from official sources. Does **not** run evaluations or recalculate scores.

## Setup

```bash
cd ledger
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

## Quick start

```bash
benchmark-ledger init-db
benchmark-ledger seed-registry
benchmark-ledger ingest --source fake_local_fixture --dry-run
benchmark-ledger ingest --source fake_local_fixture
benchmark-ledger claims list
benchmark-ledger review queue
benchmark-ledger export-official-json --out ../src/data/official/export.sample.json
```

## Architecture

- Append-only ledgers (benchmarks, models, sources, snapshots, claims, validations, relationships, runs)
- Adapters return typed objects; runner persists
- Local filesystem snapshots under `SNAPSHOT_LOCAL_ROOT`
- Trusted officialness: O5–O1 only

## Tests

```bash
pytest -q
```

## CLI-only MVP

No ledger web UI in MVP (see AGENTS.md and ADR-001).

## Registry

Seeded from `app/registry/*.yaml`. Run `benchmark-ledger seed-registry` after `init-db`.

| Source ID | Benchmark | Level | Status | Notes |
|---|---|---|---|---|
| fake_local_fixture | hf_official_benchmarks | O5 | active | Test fixture |
| hf_official_benchmark_discovery | hf_official_benchmarks | O5 | active | HF dataset discovery API |
| swe_bench_verified_official_leaderboard | swe_bench_verified | O4 | active | HTML table parser |
| livecodebench_official_leaderboard | livecodebench | O4 | active | HTML table parser |
| mteb_leaderboard | mteb | O4 | active | HF Datasets Server API (`mteb/results`) |
| bigcodebench_leaderboard | bigcodebench | O4 | active | HF Datasets Server API (`bigcode/bigcodebench-results`) |
| helm_leaderboard | helm | O1 | inactive | No structured endpoint found (verified 2026-07) |
| opencompass_leaderboard | opencompass | O1 | inactive | No structured endpoint found (verified 2026-07) |

**Adapter gap:** MTEB and BigCodeBench use the HF Datasets Server API (`rows[].row` nested JSON). The current `GenericJSONAdapter` does not support nested row extraction. A `hf_datasets_server` adapter is needed before ingestion runs against these sources.
