# Packet BENCHMARK-SOURCES-WIRE — Wire the 30 researched data sources into the ledger

Repo: /srv/hermes/development/ai-benchmark-aggregator
Ledger: ledger/ (Python 3.11 venv at ledger/.venv). DB seeded. Reference map:
  .orchestrator/runtime/ai-benchmark-platform/packets/BENCHMARK-DATA-SOURCES.md (has the 30 findings + draft YAML)
Goal: add real `official_sources.yaml` entries for the 30 benchmarks so `benchmark-ledger ingest --all`
pulls LIVE scores. Then re-ingest + re-export + verify.

## CRITICAL: adapter contract (read before writing source_type/parser_name)
The registry uses THESE source_type/parser_name values (see ledger/app/ingestion/adapters/__init__.py):
- JSON endpoint  -> source_type: "static_json",  parser_name: "generic_json"      (fields: records_path/row_path, model_field, score_field, metric_field)
- CSV endpoint    -> source_type: "static_csv",   parser_name: "generic_csv"       (fields: model_field, score_field)
- HF datasets-server -> source_type: "hf_datasets_server", parser_name: null       (fields: dataset_id, config, split, records_path, row_field, model_field, score_field, metric_field)
- HTML table      -> source_type: "html_table",   parser_name: "generic_html_table" (fields: model_column, score_column, table_index, table_hint)  <-- NOTE: generic_html_table uses model_COLUMN/score_COLUMN (NOT model_field!)
- No adapter yet for github_readme / yaml / s3-json / gdocs -> you MUST either (a) map them to an existing adapter, or (b) add a small new adapter + register it in adapters/__init__.py.

## Task 1 — Add machine-readable auto-sources (16) to official_sources.yaml
Append entries to ledger/app/registry/official_sources.yaml (keep existing 20). For each, translate the
research draft (in BENCHMARK-DATA-SOURCES.md) to the registry's real schema. Sources to add:

1. arc_agi   -> static_json, generic_json. url: https://arcprize.org/media/data/leaderboard/v2.json
               parser_config: {records_path: null, model_field: modelDisplayName, score_field: score, metric_field: accuracy}
2. tau_bench -> static_json, generic_json. url: https://sierra-tau-bench-public.s3.amazonaws.com/  (NOTE: S3 list is XML; if generic_json can't parse, add a NEW tiny adapter `taubench_s3` that lists + fetches submissions/*/submission.json and emits claims. Register it in adapters/__init__.py under source_type "taubench_s3". If too complex, set status: inactive and note it.)
3. gaia      -> hf_datasets_server. url: https://huggingface.co/datasets/gaia-benchmark/results_public
               parser_config: {dataset_id: gaia-benchmark/results_public, config: "2023", split: train, records_path: rows, row_field: row, model_field: model, score_field: score, metric_field: score}
4. aider_polyglot -> static_json, generic_json OR a NEW adapter for raw YAML. Prefer: source_type "static_json" only if the URL returns JSON; the Aider URL is YAML (https://raw.githubusercontent.com/Aider-AI/aider/main/aider/website/_data/polyglot_leaderboard.yml). ADD a small `github_yaml` adapter (fetch YAML -> list of dicts with model_field/pass_rate_2) OR set status: inactive. If adding adapter, register source_type "github_yaml".
5. mmmu      -> hf_datasets_server. url: https://huggingface.co/datasets/MMMU/MMMU  (dataset card; if no rows API, set status: inactive and note)
6. webarena  -> static_csv, generic_csv. url: https://docs.google.com/spreadsheets/d/1M801lEpBbKSNwP-vDBkC_pF7LdyGU1f_ufZb_NWNBZQ/export?format=csv
               parser_config: {model_field: Model, score_field: "Success Rate (%)"}
7. agentbench-> static_csv, generic_csv. url: https://docs.google.com/spreadsheets/d/e/2PACX-1vRR3Wl7wsCgHpwUw1_eUXW_fptAPLL3FkhnW_rua0O1Ji_GIVrpTjY5LaKAhwO-WeARjnY_KNw0SYNJ/pub?output=csv
               parser_config: {model_field: Model, score_field: AVG}
8. matharena -> hf_datasets_server OR status: inactive (parquet needs aggregation). If dataset-server has a results dataset, use it; else status: inactive + note.
9. frontiermath -> status: inactive (zip download, needs epochai client) OR add a NEW adapter. Set status: inactive + note if not doing the adapter.
10. mmlu      -> hf_datasets_server. url: https://huggingface.co/datasets/open-llm-leaderboard/results
               parser_config: {dataset_id: open-llm-leaderboard/results, config: default, split: train, records_path: rows, row_field: row, model_field: fullname, score_field: "results.mmlu.acc,none", metric_field: accuracy}
11. truthfulqa-> hf_datasets_server. same dataset, score_field: "results.truthfulqa.mc2"
12. helm      -> status: inactive (GCS JSON needs discovery) OR add a NEW adapter that fetches the groups.json. If adding, source_type "helm_json". Else status: inactive + note.
13. imo_answerbench -> hf_datasets_server OR status: inactive (HF dataset is problems+answers; per-model scores need the superhuman CSV). If a rows API exists for google-deepmind/superhuman use hf_datasets_server; else status: inactive + note.
14. mbpp      -> static_json, generic_json. url: https://www.codesota.com/data/benchmarks.json (verify it's JSON; if HTML, status: inactive). parser_config: {model_field: model, score_field: pass@1}
15. math500 / aime2024 / aime2025 -> Artificial Analysis API requires a KEY (ARTIFICIAL_ANALYSIS_API_KEY) which we DO NOT have. Set these status: inactive with notes: "requires AA API key; wire when key available". Do NOT set requires_auth without the key present. (Benchmark entities stay; just no auto-source yet.)
16. gpqa_diamond / hle -> same as above: Artificial Analysis API key needed. Set status: inactive + note. (hle also has Scale HTML fallback — you MAY add hle_scale as html_table source if you want; optional.)

## Task 2 — Add HTML-scrape sources (12) — these need generic_html_table
Add these WITH status: active (the adapter exists). Translate model_field->model_column, score_field->score_column:
- olympiadbench: html_table, github_readme style. The source is a GitHub README markdown table. generic_html_table parses HTML <table>; GitHub renders markdown as HTML. url: https://raw.githubusercontent.com/OpenBMB/OlympiadBench/main/README.md — BUT raw.githubusercontent returns markdown text, not HTML, so generic_html_table can't parse it. Two options: (a) use the rendered URL https://github.com/OpenBMB/OlympiadBench#readme (HTML) with table_hint "Experiment with full benchmark", model_column: Model, score_column: avg; or (b) status: inactive. Prefer (a).
- frontiercode: html_table, url: https://benchmarklist.com/benchmarks/frontiercode/, model_column: Model, score_column: "Main Score" (verify exact header via fetch; use table_hint "FrontierCode")
- bfcl: html_table, url: https://gorilla.cs.berkeley.edu/leaderboard.html, model_column: Model, score_column: "Overall Accuracy" (verify)
- humaneval: html_table, url: https://evalplus.github.io/leaderboard.html, model_column: model, score_column: pass@1 (verify)
- terminal_bench: html_table, url: https://www.tbench.ai/leaderboard/terminal-bench/2.1, model_column: Model, score_column: Accuracy (verify)
- browsecomp: html_table, url: https://llm-stats.com/benchmarks/browsecomp, model_column: Model, score_column: Score (verify; scale 0-1)
- apex_agents: html_table, url: https://www.mercor.com/apex/apex-agents-leaderboard/, model_column: Model, score_column: "Pass@1" (verify; do NOT use HF gated dataset)
- paperbench: html_table (rendered README), url: https://github.com/openai/frontier-evals/tree/main/project/paperbench (HTML), model_column: Model, score_column: "Score (%)" (verify; table_hint "PaperBench Results")
- toolbench: html_table, url: https://github.com/OpenBMB/ToolBench (HTML), model_column: Model, score_column: pass_rate (verify)
- mt_bench: html_table, url: https://lmsys.org/blog/2023-06-22-leaderboard/ (HTML), model_column: Model, score_column: score (verify; table_hint "MT-Bench")
- opencompass: html_table, url: https://rank.opencompass.org.cn/home (JS SPA — may not render server-side; if fetch returns empty, set status: inactive + note)

For EACH html_table source, before setting active, actually fetch the URL (python urllib/httpx) and confirm a <table> with the model+score columns exists. If it doesn't, set status: inactive and record why in notes. This prevents silent 0-claim sources.

## Task 3 — Manual-only (2): usamo, livebench
- usamo: status: inactive, note "MathArena HTML, manual entry only".
- livebench: already has a source (livebench_leaderboard) — leave it.

## Task 4 — verify (run, do not skip)
```
cd ledger && source .venv/bin/activate
benchmark-ledger seed-registry | tail -1
benchmark-ledger ingest --all --dry-run 2>&1 | tail -20   # see claims_extracted per source, 0 errors
benchmark-ledger ingest --all 2>&1 | tail -5
benchmark-ledger review auto-verify-matched 2>&1 | tail -1
python -m pytest -q 2>&1 | tail -2
benchmark-ledger export-official-json 2>&1 | tail -1
cd ..
python3 -c "import json;d=json.load(open('src/data/official/export.from-ledger.json'));print('benchmarks',len(d['benchmarks']),'models',len(d['models']),'scores',len(d['scores']))"
npm run typecheck && npm run build && npm test
```
Targets: ingest --all dry-run shows claims_extracted>0 for the active new sources; 0 errors; ledger tests 25/25;
frontend gates green; export benchmark count > 12.

## Verification notes / honesty
- If a source fetches but yields 0 claims (wrong column name, JS SPA), set it status: inactive and note — do NOT leave broken active sources.
- Artificial Analysis keyed sources (gpqa/hle/math500/aime) stay inactive until the key exists.
- Write results to .orchestrator/runtime/ai-benchmark-platform/packets/BENCHMARK-SOURCES-RESULT.md:
  list each of 30 with: action (added active/added inactive), source_id, claims extracted (from dry-run), notes.
