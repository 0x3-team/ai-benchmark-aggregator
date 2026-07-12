# Packet OFFICIAL-FRONTEND — Wire SPA Official mode to real ledger export + polish

Repo: /srv/hermes/development/ai-benchmark-aggregator
Frontend: React 18 + Vite + TypeScript, src/.
Ledger export the SPA reads: src/data/official/export.from-ledger.json (produced by `benchmark-ledger export-official-json`).
The data layer: src/data/official.ts loads export + sample; src/data/registry.ts is the swappable registry with getValue() sole accessor; src/App.tsx has a Demo/Official toggle (dataMode state + useEffect that calls setActiveData()).

## Current state
- Official mode loads export.from-ledger.json which currently has only a fixture (fake_model_1, 1 benchmark). After the ledger worker populates real claims, this file will contain real models/benchmarks/scores.
- The SPA already renders Official mode; proven it works (jsdom probe ROOT_HTML_LEN 194k).
- Benchmarks registry in frontend (src/data/benchmarks.ts) has 17; models.ts has 23 (2024 synthetic). Official mode should show REAL models from the export, not the synthetic 23.

## Your tasks (frontend ONLY; do NOT touch ledger/ Python)

1. **Audit Official-mode data flow.** In src/data/official.ts, confirm loadOfficialData() correctly maps the ledger export schema (models[].id/name/vendor/family, benchmarks[].id/name/category/higherIsBetter/scaleMax, scores[].modelId/benchmarkId/value/scoreRaw/date/captureStatus/officialSourceId/claimId) into the registry's ActiveData shape. The export schema is defined in ledger/app/export/official_json.py and the sample in src/data/official/export.sample.json. Align types if mismatched.

2. **Add provenance UI** so Official mode is visibly different from Demo and trustworthy:
   - In ScoreTable / heatmap cells, when a score has `captureStatus`/`officialSourceId` (official), show a small provenance affordance (e.g. a dot or title tooltip: "Source: <officialSourceId>, captured <date>, status <captureStatus>"). Demo cells (no provenance) show nothing.
   - Add a small "Official data" banner in Header when dataMode==='official' noting it's source-backed claims, with a link to the source if available. Keep it minimal, match glass/dark theme (see existing components).
   - Ensure the Demo/Official toggle in Header is clearly labeled and functional (it exists; verify it actually switches the dataset — setValue/getScoreEntry read from registry which setActiveData populates).

3. **Graceful empty/official mismatch:** if Official export has models/benchmarks not in the synthetic catalogs used for layout (categories), ensure render doesn't crash (registry already buckets unknown categories as "other"). Confirm no blank screen when switching modes.

4. Do NOT hardcode model lists. Official mode reads entirely from the export file.

## Constraints
- Keep KISS/DRY, match existing component style (src/components/ui/* are Base UI wrappers; use them). Tailwind classes already configured.
- No new dependencies unless unavoidable; if needed, note in report.
- TypeScript strict; must pass `npm run typecheck` and `npm run build`.

## Verification (run before finishing)
```
cd /srv/hermes/development/ai-benchmark-aggregator
npm run typecheck
npm run build
npm test
# Confirm official export file is valid JSON with expected shape:
python3 -c "import json;d=json.load(open('src/data/official/export.from-ledger.json'));print('models',len(d['models']),'benchmarks',len(d['benchmarks']),'scores',len(d['scores']))"
```
If the export file is still the fixture (ledger worker not done), you may generate a temporary realistic sample by copying export.sample.json structure with a few real models so the UI plumbing is verifiable; but note it's a placeholder.

## Handoff
Write summary to /srv/hermes/development/ai-benchmark-aggregator/.orchestrator/runtime/ai-benchmark-platform/packets/OFFICIAL-FRONTEND-RESULT.md: what you changed, verification output, and whether Official mode renders real data (or placeholder).
