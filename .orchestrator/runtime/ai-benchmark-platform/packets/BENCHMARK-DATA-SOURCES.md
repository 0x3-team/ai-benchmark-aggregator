# Benchmark Data-Source Map — 30 benchmarks needing automated collection

Compiled from deep-research agents (one per benchmark family). Goal: for each
benchmark that currently has NO automated scores in the ledger, know EXACTLY
where + how to gather its data (URL, method, metric, draft YAML source entry).

Legend: source_type ∈ {api, html_table, csv, json, dataset_card, manual}
officialness_level O1(low)..O5(high). machine_readable bool.

---

## Wave 1 (GPQA/HLE/ARC-AGI, MATH500/AIME, OlympiadBench/MathArena/FrontierMath) — DONE

### gpqa_diamond
- Best source: Artificial Analysis API `https://artificialanalysis.ai/api/v2/language/models` (field `evaluations.gpqa`), Pro key required. Official HF dataset `Idavidrein/gpqa` is questions-only (no scores).
- Method: api (JSON), machine_readable, requires_auth (Pro key).
- Metric: GPQA Diamond accuracy %.
```yaml
- id: gpqa_diamond_aa
  benchmark_id: gpqa_diamond
  source_name: Artificial Analysis
  source_url: https://artificialanalysis.ai/api/v2/language/models
  source_type: api
  officialness_level: O2
  machine_readable: true
  requires_auth: true
  parser_name: null
  update_cadence: weekly
  parser_config: {dataset_id: null, model_field: slug, score_field: evaluations.gpqa, metric_field: accuracy}
```

### hle
- Best source: Scale/CAIS leaderboard `https://labs.scale.com/leaderboard/humanitys_last_exam` (HTML table) OR Artificial Analysis API `evaluations.hle`.
- Method: html_table (Scale) / api (AA); machine_readable=false for Scale.
- Metric: accuracy %.
```yaml
- id: hle_scale
  benchmark_id: hle
  source_name: Scale / Center for AI Safety
  source_url: https://labs.scale.com/leaderboard/humanitys_last_exam
  source_type: html_table
  officialness_level: O1
  machine_readable: false
  requires_auth: false
  parser_name: generic_html_table
  update_cadence: on_release
  parser_config: {dataset_id: null, model_field: Model, score_field: Accuracy, metric_field: accuracy}
```

### arc_agi
- Best source: ARC Prize official public JSON (verified HTTP 200, no auth): `https://arcprize.org/media/data/leaderboard/v2.json` (v1/v2/v3 available).
- Method: json, machine_readable=true, no auth. EASIEST auto-source.
- Metric: score (0–1 accuracy).
```yaml
- id: arc_agi_official
  benchmark_id: arc_agi
  source_name: ARC Prize (official)
  source_url: https://arcprize.org/media/data/leaderboard/v2.json
  source_type: json
  officialness_level: O1
  machine_readable: true
  requires_auth: false
  parser_name: generic_json
  update_cadence: on_release
  parser_config: {dataset_id: null, model_field: modelDisplayName, score_field: score, metric_field: accuracy}
```

### math500
- Best source: Artificial Analysis free API `https://artificialanalysis.ai/api/v2/data/llms/models` (field `evaluations.math_500`) + HF dataset `HuggingFaceH4/MATH-500` (questions; scores via eval).
- Method: api (JSON, keyed) / dataset.
- Metric: math_500 accuracy.
```yaml
- id: math500_aa
  benchmark_id: math-500
  source_name: Artificial Analysis (Math-500)
  source_url: https://artificialanalysis.ai/api/v2/data/llms/models
  source_type: api
  officialness_level: O3
  machine_readable: true
  requires_auth: true
  parser_name: artificial_analysis_llm
  update_cadence: daily
  parser_config: {metric_field: evaluations.math_500, id_field: slug}
```

### aime2024
- Best source: Artificial Analysis API `evaluations.aime_2024` + LiveBench CSV `https://raw.githubusercontent.com/LiveBench/livebench.github.io/main/public/table_2026_01_08.csv` (col `math_comp`) + MathArena HF `datasets/MathArena/aime_2024_I`.
- Method: api / csv / dataset.
- Metric: aime_2024 accuracy (avg 15).
```yaml
- id: aime2024_aa
  benchmark_id: aime-2024
  source_name: Artificial Analysis (AIME 2024)
  source_url: https://artificialanalysis.ai/api/v2/data/llms/models
  source_type: api
  officialness_level: O3
  machine_readable: true
  requires_auth: true
  parser_name: artificial_analysis_llm
  update_cadence: daily
  parser_config: {metric_field: evaluations.aime_2024, id_field: slug}
- id: aime2024_livebench
  benchmark_id: aime-2024
  source_name: LiveBench Math (official)
  source_url: https://raw.githubusercontent.com/LiveBench/livebench.github.io/main/public/table_2026_01_08.csv
  source_type: csv
  officialness_level: O2
  machine_readable: true
  requires_auth: false
  parser_name: livebench_csv
  update_cadence: 6 months
  parser_config: {metric_field: math_comp, id_field: model}
```

### aime2025
- Best source: Artificial Analysis API `evaluations.aime_2025` + MathArena HF `datasets/MathArena/aime_2025`.
- Metric: aime_2025 accuracy (avg 30).
```yaml
- id: aime2025_aa
  benchmark_id: aime-2025
  source_name: Artificial Analysis (AIME 2025)
  source_url: https://artificialanalysis.ai/api/v2/data/llms/models
  source_type: api
  officialness_level: O3
  machine_readable: true
  requires_auth: true
  parser_name: artificial_analysis_llm
  update_cadence: daily
  parser_config: {metric_field: evaluations.aime_2025, id_field: slug}
```

### olympiadbench
- Best source: GitHub README markdown table `https://raw.githubusercontent.com/OpenBMB/OlympiadBench/main/README.md` (no API; HF dataset is problems not scores).
- Method: github_readme markdown scrape.
- Metric: accuracy % (avg Math+Physics).
```yaml
- id: olympiadbench_readme
  benchmark_id: olympiadbench
  source_name: OpenBMB OlympiadBench README
  source_url: https://raw.githubusercontent.com/OpenBMB/OlympiadBench/main/README.md
  source_type: github_readme
  officialness_level: O1
  machine_readable: false
  requires_auth: false
  parser_name: null
  update_cadence: weekly
  parser_config: {table: "Experiment with full benchmark", columns: [model, math, physics, avg]}
```

### matharena
- Best source: MathArena HF outputs `https://huggingface.co/datasets/MathArena/aime_2026_I_outputs` (parquet, derive accuracy) or raw zip `https://files.sri.inf.ethz.ch/matharena/matharena_data.zip`.
- Method: huggingface_dataset (parquet), machine_readable.
- Metric: accuracy (canonical; "Elo" is aggregator-derived, not the field).
```yaml
- id: matharena_hf
  benchmark_id: matharena
  source_name: MathArena (ETH SRI) HuggingFace outputs
  source_url: https://huggingface.co/datasets/MathArena/aime_2026_I_outputs
  source_type: huggingface_dataset
  officialness_level: O1
  machine_readable: true
  requires_auth: false
  parser_name: null
  update_cadence: monthly
  parser_config: {metric: accuracy, group_by: model_name, field: correct}
```

### frontiermath
- Best source: Epoch AI CSV bundle `https://epoch.ai/data/benchmark_data.zip` (no auth) or `pip install epochai`.
- Method: csv_download, machine_readable.
- Metric: accuracy = proportion solved (mean_score), per tier.
```yaml
- id: frontiermath_epoch
  benchmark_id: frontiermath
  source_name: Epoch AI FrontierMath
  source_url: https://epoch.ai/data/benchmark_data.zip
  source_type: csv_download
  officialness_level: O1
  machine_readable: true
  requires_auth: false
  parser_name: null
  update_cadence: on_release
  parser_config: {sheets: [frontiermath_tiers_1_3, frontiermath_tier_4], score_field: mean_score}
```

## Wave 2 (USAMO/IMO-AnswerBench/HumanEval, MBPP/FrontierCode/Aider, τ-bench/GAIA/BFCL) — DONE

### usamo
- Best source: MathArena `matharena.ai/usamo/` (HTML leaderboard) + HF `hf:MathArena/usamo_2026` responses dataset (cross-check).
- Method: html leaderboard (partial machine-readable via HF responses).
- Metric: mean proof points /42 (%).
```yaml
- id: usamo_matharena
  benchmark_id: usamo
  source_name: MathArena USAMO
  source_url: https://matharena.ai/usamo/
  source_type: html_table
  officialness_level: O1
  machine_readable: false
  requires_auth: false
  parser_name: null
  update_cadence: on_release
  parser_config: {model_field: Model, score_field: Score, metric_field: score}
```

### imo_answerbench
- Best source: IMO-Bench (Google DeepMind) `imobench.github.io/` + `google-deepmind/superhuman` `answerbench_v2.csv`; llm-stats.com mirrors as fallback.
- Method: csv (HF) / html (paper Table 4).
- Metric: accuracy % over 400 short-answer problems.
```yaml
- id: imo_answerbench_deepmind
  benchmark_id: imo_answerbench
  source_name: IMO-Bench (Google DeepMind)
  source_url: https://huggingface.co/datasets/google-deepmind/superhuman
  source_type: dataset
  officialness_level: O1
  machine_readable: true
  requires_auth: false
  parser_name: null
  update_cadence: on_release
  parser_config: {metric_field: answerbench_v2, group_by: model}
```

### humaneval
- Best source: EvalPlus leaderboard `evalplus.github.io/leaderboard` (HTML) + EvalPlus v0.1.0 release assets (raw pass@1).
- Method: html_table (leaderboard) / csv (release assets).
- Metric: Pass@1 (greedy, temp 0.0).
- NOTE: Artificial Analysis API v2 DROPPED HumanEval — do NOT route through AA.
```yaml
- id: humaneval_evalplus
  benchmark_id: humaneval
  source_name: EvalPlus Leaderboard
  source_url: https://evalplus.github.io/leaderboard.html
  source_type: html_table
  officialness_level: O2
  machine_readable: false
  requires_auth: false
  parser_name: generic_html_table
  update_cadence: on_release
  parser_config: {model_field: model, score_field: pass@1, metric_field: Pass@1}
```

### mbpp
- Best source: CodeSOTA `/data/benchmarks.json` (no auth, CORS-open, field `pass@1`) + EvalPlus leaderboard (MBPP+ 399-task subset).
- Method: json (CodeSOTA) / html_table (EvalPlus).
- Metric: Pass@1 (pin subset: raw 974 vs MBPP+ 399).
```yaml
- id: mbpp_codesota
  benchmark_id: mbpp
  source_name: CodeSOTA
  source_url: https://www.codesota.com/data/benchmarks.json
  source_type: json
  officialness_level: O3
  machine_readable: true
  requires_auth: false
  parser_name: generic_json
  update_cadence: daily
  parser_config: {model_field: model, score_field: pass@1, metric_field: Pass@1}
```

### frontiercode
- Best source: BenchmarkList mirror `benchmarklist.com/benchmarks/frontiercode/` (structured HTML) — Cognition blog is text-only, no API, tasks unreleased.
- Method: html_table (aggregator mirror).
- Metric: Main Score % (not "Pass@1" — official phrasing is Main/Diamond/Extended Score %).
```yaml
- id: frontiercode_benchmarklist
  benchmark_id: frontiercode
  source_name: BenchmarkList (FrontierCode mirror)
  source_url: https://benchmarklist.com/benchmarks/frontiercode/
  source_type: html_table
  officialness_level: O3
  machine_readable: false
  requires_auth: false
  parser_name: generic_html_table
  update_cadence: on_release
  parser_config: {model_field: Model, score_field: main_score, metric_field: main_score}
```

### aider_polyglot
- Best source: Aider's own YAML `https://raw.githubusercontent.com/Aider-AI/aider/main/aider/website/_data/polyglot_leaderboard.yml` (machine-readable, no auth, updates on commit).
- Method: yaml (self-published).
- Metric: pass_rate_2 (full = "Percent correct").
```yaml
- id: aider_polyglot_yaml
  benchmark_id: aider_polyglot
  source_name: Aider Polyglot Leaderboard (official YAML)
  source_url: https://raw.githubusercontent.com/Aider-AI/aider/main/aider/website/_data/polyglot_leaderboard.yml
  source_type: yaml
  officialness_level: O1
  machine_readable: true
  requires_auth: false
  parser_name: null
  update_cadence: on_commit
  parser_config: {model_field: model, score_field: pass_rate_2, metric_field: pass_rate_2}
```

### tau_bench
- Best source: LIVE S3 bucket `sierra-tau-bench-public` (taubench.com backend) — per-submission `submissions/*/submission.json` (fields `results.<domain>.pass_{1..4}`). The `sierra-research/tau-bench` README leaderboard is DEPRECATED.
- Method: json (S3 list+GET), machine_readable, no auth.
- Metric: task_completion = Pass^k across domains.
```yaml
- id: taubench_live_s3
  benchmark_id: tau_bench
  source_name: tau-bench Live S3
  source_url: https://sierra-tau-bench-public.s3.amazonaws.com/
  source_type: json
  officialness_level: O1
  machine_readable: true
  requires_auth: false
  parser_name: null
  update_cadence: on_release
  parser_config: {model_field: model, score_field: results.*.pass_1, metric_field: task_completion}
```

### gaia
- Best source: HF `gaia-benchmark/results_public` (rendered by `spaces/gaia-benchmark/leaderboard`). datasets-server rows API (config `2023`, splits validation/test; 3,557 rows, fields `score`, `score_level1..3`).
- Method: dataset (HF datasets-server), machine_readable, no auth.
- Metric: score (avg %).
```yaml
- id: gaia_results_public
  benchmark_id: gaia
  source_name: GAIA Results Public (HF)
  source_url: https://huggingface.co/datasets/gaia-benchmark/results_public
  source_type: dataset
  officialness_level: O1
  machine_readable: true
  requires_auth: false
  parser_name: hf_datasets_server
  update_cadence: on_release
  parser_config: {dataset_id: gaia-benchmark/results_public, config: 2023, model_field: model, score_field: score, metric_field: score}
```

### bfcl
- Best source: `gorilla.cs.berkeley.edu/leaderboard.html` (V4). Probed `/leaderboard_data.json` → 404; HTML scrape required. Test cases on HF (`gorilla-llm/Berkeley-Function-Calling-Leaderboard`); published scores live only on HTML.
- Method: html_table (scrape).
- Metric: overall_accuracy (unweighted avg of sub-categories).
```yaml
- id: bfcl_leaderboard_html
  benchmark_id: bfcl
  source_name: Berkeley Function Calling Leaderboard
  source_url: https://gorilla.cs.berkeley.edu/leaderboard.html
  source_type: html_table
  officialness_level: O1
  machine_readable: false
  requires_auth: false
  parser_name: generic_html_table
  update_cadence: on_release
  parser_config: {model_field: Model, score_field: overall_accuracy, metric_field: accuracy}
```

## Wave 3 (WebArena/AgentBench/Terminal-Bench, BrowseComp/APEX/PaperBench, ToolBench/MMLU/TruthfulQA) — DONE

### webarena
- Best source: official Google Sheet CSV (webarena.dev has no leaderboard; `/leaderboard` 404). Verified CSV export works.
- URL: `https://docs.google.com/spreadsheets/d/1M801lEpBbKSNwP-vDBkC_pF7LdyGU1f_ufZb_NWNBZQ/export?format=csv`
- Method: csv (Google Sheets export), machine_readable, no auth.
- Metric: Success Rate (%).
```yaml
- id: webarena_official_sheet
  benchmark_id: webarena
  source_name: WebArena Official Leaderboard (Google Sheet)
  source_url: https://docs.google.com/spreadsheets/d/1M801lEpBbKSNwP-vDBkC_pF7LdyGU1f_ufZb_NWNBZQ/export?format=csv
  source_type: csv
  officialness_level: O1
  machine_readable: true
  requires_auth: false
  parser_name: null
  update_cadence: weekly
  parser_config: {metric_field: "Success Rate (%)", model_field: Model, date_field: Date}
```

### agentbench
- Best source: THUDM official Google Sheet CSV (linked from AgentBench README "Leaderboard (new)"). Verified public CSV.
- URL: `https://docs.google.com/spreadsheets/d/e/2PACX-1vRR3Wl7wsCgHpwUw1_eUXW_fptAPLL3FkhnW_rua0O1Ji_GIVrpTjY5LaKAhwO-WeARjnY_KNw0SYNJ/pub?output=csv`
- Method: csv, machine_readable, no auth.
- Metric: AVG (mean success_rate/pass@1 across ALFWorld/DB/KG/OS/WebShop).
```yaml
- id: agentbench_official_sheet
  benchmark_id: agentbench
  source_name: AgentBench Official Leaderboard (THUDM Google Sheet)
  source_url: https://docs.google.com/spreadsheets/d/e/2PACX-1vRR3Wl7wsCgHpwUw1_eUXW_fptAPLL3FkhnW_rua0O1Ji_GIVrpTjY5LaKAhwO-WeARjnY_KNw0SYNJ/pub?output=csv
  source_type: csv
  officialness_level: O1
  machine_readable: true
  requires_auth: false
  parser_name: null
  update_cadence: weekly
  parser_config: {score_field: AVG, model_field: Model, per_env: [ALFWorld, DB, KG, OS, WebShop]}
```

### terminal_bench
- Best source: official leaderboard `https://www.tbench.ai/leaderboard/terminal-bench/2.1` (repo README directs here). No JSON/CSV confirmed (API probes 404).
- Method: html_table (scrape only), machine_readable=false.
- Metric: Accuracy (pass_rate, ±CI).
```yaml
- id: terminal_bench_tbench_leaderboard
  benchmark_id: terminal-bench
  source_name: Terminal-Bench Official Leaderboard (tbench.ai)
  source_url: https://www.tbench.ai/leaderboard/terminal-bench/2.1
  source_type: html_table
  officialness_level: O1
  machine_readable: false
  requires_auth: false
  parser_name: generic_html_table
  update_cadence: daily
  parser_config: {pass_rate_field: Accuracy, table_selector: table, model_field: Model, agent_field: Agent}
```

### browsecomp
- Best source: aggregators only (official `openai/simple-evals` deprecated Jul 2025, no leaderboard). llm-stats.com/benchmarks/browsecomp (52 models), benchmarklist.com, ai-stats.phaseo.app.
- Method: html_table (scrape), machine_readable=false.
- Metric: score (fraction 0–1, e.g. 0.901 = 90.1%).
```yaml
- id: browsecomp_llmstats
  benchmark_id: browsecomp
  source_name: LLM-Stats BrowseComp Leaderboard
  source_url: https://llm-stats.com/benchmarks/browsecomp
  source_type: html_table
  officialness_level: O3
  machine_readable: false
  requires_auth: false
  parser_name: generic_html_table
  update_cadence: weekly
  parser_config: {table_selector: table, score_column: Score, scale: "0-1"}
```

### apex_agents
- Best source: Mercor official leaderboard `https://www.mercor.com/apex/apex-agents-leaderboard/`. NOTE: HF `mercor/apex-agents` is GATED + forbids crawling — do NOT use.
- Method: html_table (scrape), machine_readable=false.
- Metric: Pass@1 (%).
```yaml
- id: apex_agents_mercor
  benchmark_id: apex-agents
  source_name: Mercor APEX-Agents Leaderboard
  source_url: https://www.mercor.com/apex/apex-agents-leaderboard/
  source_type: html_table
  officialness_level: O1
  machine_readable: false
  requires_auth: false
  parser_name: generic_html_table
  update_cadence: on_release
  parser_config: {table_selector: table, score_column: Pass@1, scale: percent}
```

### paperbench
- Best source: OpenAI frontier-evals README `https://github.com/openai/frontier-evals/tree/main/project/paperbench` (leaderboard table) + `openai.com/index/paperbench/`. Mirror: openreward.ai/GeneralReasoning/PaperBench.
- Method: github_readme (markdown scrape), machine_readable=false.
- Metric: Score (% replication; also code_dev_score for Code-Dev variant).
```yaml
- id: paperbench_frontier_evals
  benchmark_id: paperbench
  source_name: OpenAI frontier-evals PaperBench README
  source_url: https://github.com/openai/frontier-evals/tree/main/project/paperbench
  source_type: github_readme
  officialness_level: O1
  machine_readable: false
  requires_auth: false
  parser_name: null
  update_cadence: on_release
  parser_config: {table_header: "PaperBench Results", score_column: "Score (%)", variants: [full, code_dev]}
```

### toolbench
- Best source: `openbmb.github.io/ToolBench` + `github.com/OpenBMB/ToolBench` README (HTML only, manual PR/email updates).
- Method: html_table (scrape), machine_readable=false.
- Metric: pass_rate (Average).
```yaml
- id: toolbench_openbmb
  benchmark_id: toolbench
  source_name: OpenBMB ToolBench
  source_url: https://github.com/OpenBMB/ToolBench
  source_type: html_table
  officialness_level: O2
  machine_readable: false
  requires_auth: false
  parser_name: generic_html_table
  update_cadence: on_release
  parser_config: {model_field: Model, score_field: pass_rate, metric_field: pass_rate}
```

### mmlu
- Best source: HF Open LLM Leaderboard v2 results JSON (`open-llm-leaderboard/results`, archived but dataset live) field `results.mmlu.acc,none`. Official github.com/hendrycks/test is README HTML (manual).
- Method: dataset (HF datasets-server JSON), machine_readable, no auth.
- Metric: accuracy.
```yaml
- id: mmlu_openllm_v2
  benchmark_id: mmlu
  source_name: Open LLM Leaderboard v2 (MMLU)
  source_url: https://huggingface.co/datasets/open-llm-leaderboard/results
  source_type: dataset
  officialness_level: O5
  machine_readable: true
  requires_auth: false
  parser_name: hf_datasets_server
  update_cadence: daily
  parser_config: {dataset_id: open-llm-leaderboard/results, model_field: fullname, score_field: "results.mmlu.acc,none", metric_field: accuracy}
```

### truthfulqa
- Best source: HF Open LLM Leaderboard v2 results JSON field `results.truthfulqa.mc2`. Official github.com/sylinrl/TruthfulQA is README HTML (manual). Use mc2 (standard auto metric; README "% true" is human-judged).
- Method: dataset (HF datasets-server JSON), machine_readable, no auth.
- Metric: accuracy (mc2).
```yaml
- id: truthfulqa_openllm_v2
  benchmark_id: truthfulqa
  source_name: Open LLM Leaderboard v2 (TruthfulQA)
  source_url: https://huggingface.co/datasets/open-llm-leaderboard/results
  source_type: dataset
  officialness_level: O5
  machine_readable: true
  requires_auth: false
  parser_name: hf_datasets_server
  update_cadence: daily
  parser_config: {dataset_id: open-llm-leaderboard/results, model_field: fullname, score_field: "results.truthfulqa.mc2", metric_field: accuracy}
```

---

## SUMMARY — 30 benchmarks, where to gather data

Machine-readable (api/json/csv/dataset/yaml) — AUTO-SOURCES (no key unless noted):
- arc_agi: public JSON (no auth) ✅ EASIEST
- tau_bench: live S3 JSON (no auth) ✅
- gaia: HF dataset (no auth) ✅
- aider_polyglot: Aider YAML (no auth) ✅
- mmmu: HF dataset (no auth) ✅
- webarena: Google Sheet CSV (no auth) ✅
- agentbench: Google Sheet CSV (no auth) ✅
- matharena: HF parquet (no auth) ✅
- frontiermath: Epoch CSV (no auth) ✅
- mmlu: HF Open LLM Leaderboard v2 JSON (no auth) ✅
- truthfulqa: HF Open LLM Leaderboard v2 JSON (no auth) ✅
- math500 / aime2024 / aime2025: Artificial Analysis API (KEY) or LiveBench CSV / MathArena HF
- gpqa_diamond / hle: Artificial Analysis API (KEY) or Scale-HLE HTML
- helm: official JSON groups.json (no auth) ✅
- imo_answerbench: HF google-deepmind/superhuman CSV (no auth) ✅
- mbpp: CodeSOTA JSON (no auth) ✅

HTML-scrape only (need generic_html_table / github_readme parser):
- hle (Scale), olympiadbench (GitHub README), frontiercode (BenchmarkList), bfcl, humaneval (EvalPlus), terminal_bench, browsecomp, apex_agents (Mercor), paperbench (OpenAI README), toolbench, mt_bench, opencompass

Manual / no-auto (catalog-only, manual entry):
- usamo (MathArena HTML), livebench (already wired)

KEY INSIGHT: 16 of 30 are machine-readable auto-sources; 12 need HTML/markdown scrape; 2 are manual-only.
Next phase: wire the machine-readable ones into official_sources.yaml (real scores); build a generic
github_readme + html_table scraper adapter for the scrape group; mark manual ones catalog-only.

- mmmu: HF datasets-server `MMMU/MMMU` (Val accuracy). machine-readable.
- mt_bench: LMSYS FastChat llm_judge jsonl — no hosted API, manual/CLI import.
- helm: official JSON groups.json via GCS/latest — clean machine-readable.
- opencompass: JS SPA, needs headless scrape, no stable API.

(Waiting on waves 1-3: 9 more agents covering the remaining 26 benchmarks.)
