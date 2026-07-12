# Packet OFFICIAL-REGISTRY — Expand ledger source registry with real official sources

Repo: /srv/hermes/development/ai-benchmark-aggregator
Ledger package: ledger/ (Python 3.11 venv at ledger/.venv; activate then run `benchmark-ledger ...`)
DB already initialized + seeded (run: `cd ledger && source .venv/bin/activate && benchmark-ledger seed-registry`).

## Context
The app is a dual-mode AI benchmark aggregator. Demo mode = synthetic 2024 snapshot (src/data/models.ts, benchmarks.ts, scores.ts). Official mode = ledger-backed claims, currently only a fixture (fake_model_1). Goal: make Official mode show REAL, CURRENT model/benchmark claims from live sources.

The ledger already has:
- Adapters: fake, generic_csv, generic_html_table, generic_json, hf_benchmark_api (registered in ledger/app/ingestion/adapters/__init__.py via get_adapter())
- Source registry: ledger/app/registry/official_sources.yaml (8 sources: 1 fake, 1 hf_benchmark_api, 2 html_table, 2 hf_datasets_server [BROKEN - adapter missing], 1 web_js_spa [inactive], 1 web_ui [inactive])
- Benchmarks registered: 7 (hf_official_benchmarks, swe_bench_verified, livecodebench, mteb, helm, bigcodebench, +1)

Proven working source: `hf_official_benchmark_discovery` (hf_benchmark_api) extracts 38 real claims (benchmark names from HF). Model entities are NOT yet captured (model_id extraction needs work).

## Your tasks (edit ONLY ledger registry + add adapters; do NOT touch src/ frontend)

1. **Add new official sources to ledger/app/registry/official_sources.yaml.** Add real, current sources with ids, source_type matching an existing adapter OR a new adapter you create:
   - Hugging Face Open LLM Leaderboard v2 (html_table or hf_benchmark_api): top models across MMLU/MMLU-Pro/GPQA/etc. source_url: https://huggingface.co/spaces/open-llm-leaderboard/blog
   - LMSYS Chatbot Arena (api, NEW adapter lmsys_arena_api): Elo + model org. source_url: https://lmarena.ai/leaderboard
   - Artificial Analysis (api, NEW adapter artificial_analysis_api): aggregated scores. source_url: https://artificialanalysis.ai/
   - Keep existing: swe_bench_verified_official_leaderboard, livecodebench_official_leaderboard, mteb_leaderboard, bigcodebench_leaderboard, helm_leaderboard (make active if you add parser), opencompass_leaderboard (make active if you add parser).
   Each source entry fields (match existing schema): id, benchmark_id, source_name, source_url, source_type, officialness_level (O4/O5), machine_readable, requires_auth (false unless API key needed), supports_history, update_cadence, parser_name, status (active/inactive), parser_config (dict; for html_table: table_hint, table_index, model_column, score_column, optional_columns; for api: endpoint/params).
   For sources that need an API key, set requires_auth: true and document the env var in parser_config (e.g. api_key_env: LMSYS_API_KEY). Do NOT hardcode keys.

2. **Create missing adapters if referenced:**
   - `ledger/app/ingestion/adapters/hf_datasets_server.py` (referenced by mteb + bigcodebench) — fetch from Hugging Face datasets-server first-rows API, extract rows.
   - `ledger/app/ingestion/adapters/lmsys_arena_api.py` — fetch LMSYS leaderboard JSON (try https://lmarena.ai/api/leaderboard or public data; if no key, fetch best-effort public endpoint; return normalized claims).
   - `ledger/app/ingestion/adapters/artificial_analysis_api.py` — fetch Artificial Analysis public API/JSON; normalized claims.
   Register all new adapters in `ledger/app/ingestion/adapters/__init__.py` get_adapter().
   Each adapter must implement the SourceAdapter ABC (base.py): fetch(source) -> FetchResult, snapshot(source, fetch_result) -> SnapshotInput, extract_claims(source, snapshot, raw_bytes) -> list[dict], validate_claim(claim, raw_bytes) -> list.

3. **Model entity capture:** ensure adapters populate model_id/model_raw so claims resolve to real models (not just benchmark names). The registry models.yaml currently has 2 fake models — you may add a seed of real model entities (e.g. from HF leaderboard top models) to ledger/app/registry/models.yaml OR rely on alias matching. Keep it honest: only add models actually seen in sources.

## Constraints
- Python 3.11, SQLAlchemy 2, Pydantic v2, Typer. Match existing code style (see base.py, generic_html_table.py).
- No external network assumptions that break offline: adapters must degrade gracefully (empty claims, logged error) if fetch fails.
- Do NOT modify src/ (frontend). Do NOT modify tests unless adding new adapter tests under ledger/tests/ (recommended: add tests for new adapters using a saved fixture HTML/JSON in ledger/tests/fixtures/).

## Verification (you MUST run before finishing)
```
cd /srv/hermes/development/ai-benchmark-aggregator/ledger && source .venv/bin/activate
benchmark-ledger seed-registry
python -m pytest -q          # all existing tests must still pass
# dry-run each new active source, confirm it extracts >=1 real claim or logs a clean error (no crash):
benchmark-ledger ingest --source <each new id> --dry-run   # report claims count per source
```
Final report: list each source id, claims extracted (dry-run), adapter used, any errors. Target: >=5 sources extracting real claims, total >=100 real claims across all sources.

## Handoff
Write a short summary to /srv/hermes/development/ai-benchmark-aggregator/.orchestrator/runtime/ai-benchmark-platform/packets/OFFICIAL-REGISTRY-RESULT.md with the per-source claim counts and any failures.
