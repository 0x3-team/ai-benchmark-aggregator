# Packet BENCHMARK-LEDGER — Build the comprehensive, current benchmark catalog

Repo: /srv/hermes/development/ai-benchmark-aggregator
Ledger: ledger/ (Python 3.11 venv at ledger/.venv). DB seeded, models ledger done (1386 entities).
Frontend: src/ (React/Vite/TS). Do BOTH ledger benchmark seed + frontend benchmark browser.

## Context (why)
The benchmark catalog is stuck at 2024-era academic sets. Current benchmark_entities: hf_official_benchmarks, swe_bench_verified, livecodebench, mteb, helm, opencompass, bigcodebench, chatbot_arena, artificial_analysis (9 entities; 7 appear in claims). The 2026 landscape is far richer and MUST be covered:
- Reasoning: GPQA Diamond, HLE (Humanity's Last Exam), ARC-AGI
- Math: MATH, AIME 2024/2025, OlympiadBench, MathArena, FrontierMath, USAMO, IMO-AnswerBench
- Coding: HumanEval+, MBPP+, LiveCodeBench (v5/v6/Pro), BigCodeBench, SWE-bench Verified, FrontierCode, Aider Polyglot
- Agentic/Tool-use: tau-bench (τ-bench), GAIA, BFCL v3/v4, WebArena, AgentBench, Terminal-Bench, BrowseComp, APEX-Agents, PaperBench, ToolBench
- Knowledge: MMLU-Pro, MMLU, BBH, TruthfulQA
- Live/contamination-resistant leaderboards: LiveBench, LMArena (Chatbot Arena), Artificial Analysis, Open LLM Leaderboard v2, OpenCompass, Helm
- Embedding: MTEB
These are REAL, current benchmarks confirmed via web (llm-stats.com 600+ benchmarks, awesome-llm-benchmarks 2026, codesota, livebench.ai, arena.ai). Do NOT invent — only include benchmarks confirmed by these public sources.

## Task A — Benchmark registry expansion
Edit `ledger/app/registry/benchmarks.yaml` (and/or add `benchmarks_extra.yaml` — seed_loader globs `benchmarks*.yaml`? CHECK: seed_loader currently takes a single benchmarks_path. Look at cli.py seed-registry_cmd: it passes benchmarks=benchmarks.yaml only. EITHER add benchmarks to the same file, OR extend cli.py/seed_loader to glob benchmarks*.yaml like it does for models*.yaml. Prefer: extend seed_loader + cli.py to glob `benchmarks*.yaml` for symmetry with models, then create `benchmarks_curated.yaml` with the new entries. Keep existing 9.)
For EACH benchmark entry include fields (match existing schema in benchmarks.yaml): id, canonical_name, display_name, benchmark_family (use: reasoning, math, coding, agentic, knowledge, embedding, live_leaderboard, holistic_evaluation, human_evaluation, aggregator, platform), owner_name, official_home_url, official_leaderboard_url (if any), has_official_leaderboard (bool), primary_metric, known_metrics (list), known_splits (list), status (active), aliases (list of common raw names seen in claims: e.g. gpqa -> [GPQA, gpqa_diamond, GPQA Diamond], mmlu_pro -> [MMLU-Pro, mmlu-pro, MMLU Pro], aime2024 -> [AIME 2024, aime_2024]).
Target: >=30 benchmark entities total (existing 9 + ~25 new).

## Task B — Live benchmark sources + adapters
The ledger already has adapters: fake, generic_csv, generic_html_table, generic_json, hf_benchmark_api, hf_datasets_server, lmsys_arena_api, artificial_analysis_api, swe_bench_adapter, livecodebench_adapter. 
Add/update `official_sources.yaml` so new benchmarks have active sources where a real endpoint exists:
- livebench (api or html_table): https://livebench.ai/ — has a leaderboard; parse model+overall.
- open_llm_leaderboard_v2 already exists (hf_datasets_server). Ensure its benchmark coverage maps to gpqa/mmlu_pro/math/bbh.
- opencompass (api/html): https://rank.opencompass.org.cn/home
- artificial_analysis already exists.
- chatbot_arena already exists.
For benchmarks WITHOUT a clean scrapeable source (HLE, ARC-AGI, FrontierMath, USAMO), set status=active but source_type that notes "manual"/"no-auto-source" — the entity still exists for display + manual claim entry; do NOT fabricate a source that 404s. It is FINE for an entity to have no automated source yet.
Do NOT break existing working sources. Add new ones only with real URLs.

## Task C — Benchmark alias matching
Claims carry benchmark_raw like: gpqa, mmlu_pro, aime2024, math500, swe_bench_verified, humaneval, mbpp, truthfulqa, bbh, arc_agi, mmmu, mtbench, livecodebench, bigcodebench, mteb, chatbot_arena, artificial_analysis, hf_official_benchmarks.
Ensure each maps to an entity via aliases. Verify with `benchmark-ledger review auto-verify-matched` (re-run after adding benchmark aliases) that MORE claims verify. The auto-verify command matches BOTH model and benchmark; adding benchmark aliases should lift the 209 remaining needs_review claims where the model also matches.
Also check `match_benchmark(session, benchmark_raw, source_benchmark_id)` in ledger/app/matching/aliases.py handles alias matching (it does exact + canonical + display). Add aliases so short raws resolve.

## Task D — Frontend: searchable benchmark browser
Mirror the model browser work: make benchmarks findable/filterable in the SPA.
- Official mode must render the LEDGER benchmarks (the export already carries them: src/data/official/export.from-ledger.json -> benchmarks[]). Add a client-side search box + category filter (reasoning/math/coding/agentic/knowledge/embedding/live) so users can "find all benchmarks, current ones".
- Keep demo mode using the 17-item src/data/benchmarks.ts (synthetic) for offline.
- Do NOT break the blank-screen fix: no setActiveData during render; lazy registry pattern in src/data/registry.ts stays.
- Match existing Base UI component style (src/components/ui/*). Add a "category" filter chip set.
- Wire the benchmark detail/category views to show per-benchmark model coverage (which models are scored on it) where data exists.

## Constraints
- No invented benchmarks — only public 2026 sources listed above.
- Python 3.11 / PyYAML / SQLAlchemy. Match seed_loader.py + cli.py style.
- Frontend: TS strict, must pass `npm run typecheck`, `npm run build`, `npm test`.
- Don't touch src/data/scores.ts TDZ fix.

## Verification (run before finishing)
```
cd ledger && source .venv/bin/activate
benchmark-ledger seed-registry                # prints benchmark count (should be >=30)
benchmark-ledger review auto-verify-matched    # report verified/total of 574 (target: >365)
python -m pytest -q                            # all pass
cd ..
npm run typecheck && npm run build && npm test
python3 -c "import json;d=json.load(open('src/data/official/export.from-ledger.json'));print('benchmarks',len(d['benchmarks']),'models',len(d['models']),'scores',len(d['scores']))"
```
Write result to /srv/hermes/development/ai-benchmark-aggregator/.orchestrator/runtime/ai-benchmark-platform/packets/BENCHMARK-LEDGER-RESULT.md: benchmark entity count, new sources added, claims verified after re-run, export benchmark count, gate outputs.
