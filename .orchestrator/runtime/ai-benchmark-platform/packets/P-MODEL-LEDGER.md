# Packet MODEL-LEDGER — Build the canonical, current, findable model catalog

Repo: /srv/hermes/development/ai-benchmark-aggregator
Ledger: ledger/ (Python 3.11 venv at ledger/.venv). DB already initialized + seeded.
Frontend: src/ (React/Vite/TS). Do BOTH ledger seed + frontend search in this packet.

## Context (why this exists)
The app currently cannot "show all models / find all good models". Root causes found:
- The model entity registry (ledger/app/registry/models.yaml) has only 2 real models + fakes; the frontend src/data/models.ts is a 2024 hand-picked snapshot of 23.
- Ingestion pulls 574 real benchmark claims, but they attach to raw strings (e.g. `01-ai/Yi-1.5-34B`) that don't resolve to canonical ModelEntities because the registry is empty. So 0 claims verify.
- Web check (2026-07-11) CONFIRMS current real models: OpenAI GPT-5.6 (Jul 9 2026), Anthropic Claude Fable 5 / Mythos 5 / Opus 4.8, Google Gemini 3.5, xAI Grok 4.5, DeepSeek-V4, Alibaba Qwen3.7-Max, Meta Llama 4, Z.ai GLM-5.2. HF Hub has a FREE keyless JSON API.

## Task A — Live HF seed (comprehensive, no invention)
Create `ledger/scripts/seed_models_from_hf.py`:
- Calls `https://huggingface.co/api/models?sort=downloads&direction=-1&limit=2000&full=false` (keyless; set User-Agent header).
- For each model: id = HF id (e.g. `meta-llama/Llama-3.1-8B`), canonical_name = last path segment, provider = namespace (before `/`), access_type = `open_weights` (HF models are open-weight/downloadable), status=active.
- Store metadata: downloads, likes, pipeline_tag, createdAt (HF field `createdAt`).
- Add aliases: the HF id, and a normalized display form.
- Filter to "good": keep models with `downloads >= 50000 OR likes >= 200` (tune so the set is comprehensive but not noise). This yields a few thousand real models — that IS "all good models".
- Output: write/append to `ledger/app/registry/models.yaml` (MERGE with existing entries, do not clobber the curated frontier tier from Task B — dedupe by id). Print counts.
- Make it idempotent: re-running replaces the generated block. Easiest: the script writes a SEPARATE file `models_hf_seed.yaml` and the registry loader (seed_loader.py) should load BOTH models.yaml + models_hf_seed.yaml. Check seed_loader.py and extend it to glob `models*.yaml` if needed.
Run it, then `benchmark-ledger seed-registry` to load. Verify model count jumps into the thousands.

## Task B — Curated frontier tier (guaranteed current flagships)
Add a `ledger/app/registry/models_frontier.yaml` with ~60 hand-vetted CURRENT flagship/strong models across vendors (grounded in the 2026-07-11 web check; do NOT invent — only include models confirmed by the timeline: GPT-5.6, GPT-5.4, GPT-5.3-Codex, Claude Fable 5, Claude Mythos 5, Claude Opus 4.8, Claude Opus 4.7, Claude Sonnet 4.6, Claude Opus 4.6, Claude Haiku 4.5, Gemini 3.5 Flash, Gemini 3.1 Flash-Lite, Gemini 3, Gemini 2.5 Flash, Grok 4.5, Grok 4.3, Grok 4.20, DeepSeek-V4, DeepSeek-V3.2, Llama 4 (405B/70B/8B), Qwen3.7-Max, Qwen3.6-Plus, Qwen3.5, GLM-5.2, Mistral Medium 3.5, Gemma 4, Kimi K2.6, Phi-4). For each: id (api-style slug), canonical_name, display_name, provider, access_type (api or open_weights), release_date (from timeline where known), aliases = [HF id if exists, common api name, display name]. status=active. seed_loader must include this file too.
These are "featured" so the UI can surface a curated tier even before HF seed loads.

## Task C — Alias matching so ingestion verifies
Ensure merge gives every frontier model an alias equal to its HF id and its common API name, so existing 574 raw claims (e.g. `01-ai/Yi-1.5-34B`, `openai/...`) resolve. After seeding, run `benchmark-ledger review auto-verify-matched` (command exists in cli.py) and report how many of the 574 claims now become parser_verified. Target: majority verify.

## Task D — Frontend: searchable model catalog
In the SPA, make models findable:
- The current model browser (find src/components for model list/grid — likely ModelGrid or similar in src/components) currently renders the 23-item demo `models.ts`. Official mode must render the LEDGER models (thousands). Wire Official mode's model list to the ledger export (src/data/official/export.from-ledger.json already has 462 models). Add a client-side search box + vendor/category filters so users can "find all existing, at least good models".
- Keep demo mode using src/data/models.ts (23 synthetic) for offline.
- DO NOT break the blank-screen fix: never call setActiveData during render; lazy registry pattern already in place (src/data/registry.ts). Match existing Base UI component style (src/components/ui/*).
- Add a "Featured / Frontier" filter chip backed by a `featured: true` flag you add to the frontier models in the export (extend export_official_json.py to mark models whose id is in a frontier set, OR add a `tags` field). Keep it simple.

## Constraints
- Keyless, no API keys. No invented model names — only HF API + the confirmed 2026 timeline.
- Python 3.11 / PyYAML / SQLAlchemy. Match seed_loader.py style.
- Frontend: TS strict, must pass `npm run typecheck`, `npm run build`, `npm test`.
- Don't touch the demo scoring logic in src/data/scores.ts (TDZ fix must stay).

## Verification (run before finishing)
```
cd ledger && source .venv/bin/activate
python scripts/seed_models_from_hf.py        # prints "seeded N HF models"
benchmark-ledger seed-registry               # prints model count (should be >> 10)
benchmark-ledger review auto-verify-matched  # report verified/total of 574
python -m pytest -q                          # all pass
cd ..
npm run typecheck && npm run build && npm test
# confirm export has many models:
python3 -c "import json;d=json.load(open('src/data/official/export.from-ledger.json'));print('models',len(d['models']))"
```
Write result to /srv/hermes/development/ai-benchmark-aggregator/.orchestrator/runtime/ai-benchmark-platform/packets/MODEL-LEDGER-RESULT.md: HF seed count, frontier count, claims verified after auto-verify, export model count, gate outputs.
