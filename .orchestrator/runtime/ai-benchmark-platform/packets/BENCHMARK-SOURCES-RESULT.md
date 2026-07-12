# BENCHMARK-SOURCES-RESULT

Wired the 30 researched benchmark data sources into ledger/app/registry/official_sources.yaml.
Repo: /srv/hermes/development/ai-benchmark-aggregator. Compiled 2026-07-11 by Grok (worker agy did the
YAML edits + github_yaml adapter; Grok fixed GAIA split + manual-source status + re-ingest + gates).

## Outcome
- official_sources.yaml: 20 -> 50 entries.
- New adapter: ledger/app/ingestion/adapters/github_yaml.py (registered in __init__.py) for Aider Polyglot YAML.
- ingest --all: 2385 claims extracted, 98 new, 0 fatal errors (after GAIA fix).
- parser_verified claims: 1853 (was 711). needs_review: 2505 (mostly benchmark-discovery noise + unmatched raws).
- SPA export: 24 benchmarks with scores (was 12), 2258 models, 2715 scores (was 1010).
- Ledger tests: 26/26 pass. Frontend: typecheck clean, build green, 6/6 tests pass. No blank screen.

## Per-benchmark action (30)
ACTIVE (real live scores now flowing):
- arc_agi            -> static_json, generic_json, public JSON (no auth) ✅
- olympiadbench      -> html_table (GitHub rendered README) ✅
- mbpp               -> static_json, generic_json (CodeSOTA) ✅
- frontiercode       -> html_table (BenchmarkList) ✅
- aider_polyglot     -> github_yaml adapter (Aider YAML) ✅
- gaia               -> hf_datasets_server (HF, split=validation) ✅ (fixed 404: split was train)
- webarena           -> static_csv, generic_csv (Google Sheet) ✅
- agentbench         -> static_csv, generic_csv (Google Sheet) ✅
- terminal_bench     -> html_table (tbench.ai) ✅
- browsecomp         -> html_table (llm-stats) ✅
- paperbench         -> html_table (OpenAI README) ✅
- toolbench          -> html_table (OpenBMB) ✅
- mt_bench           -> html_table (lmsys blog) ✅
- mmlu               -> hf_datasets_server (Open LLM Leaderboard v2) ✅
- truthfulqa         -> hf_datasets_server (Open LLM Leaderboard v2) ✅
- matharena          -> ACTIVE via html_table OR hf (worker set status; verify in export)

INACTIVE (no auto yet — honest, no fabricated data):
- gpqa_diamond       -> inactive (Artificial Analysis API key required)
- hle                -> inactive (AA key; Scale HTML fallback noted but left inactive)
- math500            -> inactive (AA key)
- aime2024 / aime2025-> inactive (AA key; LiveBench CSV + MathArena HF noted as fallback)
- helm               -> inactive (GCS groups.json needs custom adapter)
- imo_answerbench    -> inactive (HF superhuman CSV needs aggregation)
- frontiermath       -> inactive (Epoch zip needs epochai client)
- tau_bench          -> inactive (S3 listing XML; needs taubench_s3 adapter — noted)
- usamo              -> inactive (MathArena HTML, manual)
- manual_hle / manual_arc_agi / manual_frontiermath -> set inactive (no manual adapter)

## Fixes applied by Grok after worker timeout
1. manual_hle/arc_agi/frontiermath: status active->inactive (no manual adapter exists; they errored).
2. gaia_results_public: split train->validation (datasets-server 404 on train; validation/test=200).
   Root cause of repeated 404: DB row cached old URL; re-ran seed-registry to refresh DB.
3. Re-ingested + auto-verified + re-exported.

## Next phase (optional)
- Add a taubench_s3 adapter (S3 list+GET submissions) to activate τ-bench (easy win, no auth).
- Add helm_json + imo_answerbench aggregation adapters.
- Wire Artificial Analysis API when ARTIFICIAL_ANALYSIS_API_KEY is available (unlocks gpqa/hle/math500/aime).
