# OFFICIAL-FRONTEND-RESULT — Verification and Handoff

## Summary of Changes

1. **Provenance UI in Cells**:
   - Updated `src/components/ScoreTable.tsx` and `src/components/ScoreHeatmap.tsx` to detect official scores using `getScoreEntry` (checking for presence of `captureStatus` or `officialSourceId`).
   - Added a small, styled emerald dot indicator (`bg-emerald-400 shadow-[0_0_4px_#34d399] opacity-75`) in the top-right corner of official cells.
   - Updated tooltips for these cells and the dot to follow the exact format: `Source: <officialSourceId>, captured <date>, status <captureStatus>`. Demo cells display nothing.

2. **Official Data Banner**:
   - Modified `src/components/Header.tsx` to wrap the header layout in a container, rendering a clean, glassy banner at the bottom when `dataMode === 'official'`.
   - Notes that values are source-backed claims from the benchmark ledger, matching the existing dark/glass aesthetics.
   - Computes unique sources dynamically in `src/App.tsx` and displays external links to source URLs (e.g. Hugging Face, SWE-bench) in the banner.

3. **Data Flow & Switch Stability**:
   - Confirmed `loadOfficialData` normalizes unknown benchmark categories to `"other"` and handles missing properties with neutral defaults.
   - Toggling between Demo and Official modes works seamlessly without UI crashes.

---

## Verification Output

### 1. Build and Test Suite Results
Executing `npm run typecheck && npm run build && npm test`:
```bash
> ai-benchmark-aggregator@0.1.0 typecheck
> node ./node_modules/typescript/bin/tsc --noEmit

> ai-benchmark-aggregator@0.1.0 build
> node ./node_modules/typescript/bin/tsc -b && node ./node_modules/vite/bin/vite.js build

vite v5.4.21 building for production...
✓ 1903 modules transformed.
dist/index.html                   0.41 kB │ gzip:   0.27 kB
dist/assets/index-DblqUFpl.css   35.76 kB │ gzip:   7.40 kB
dist/assets/index-BSvrBwRA.js   436.54 kB │ gzip: 137.89 kB
✓ built in 5.13s

> ai-benchmark-aggregator@0.1.0 test
> node ./node_modules/vitest/vitest.mjs run

 RUN  v2.1.9 /srv/hermes/development/ai-benchmark-aggregator

 ✓ src/lib/color.test.ts (3)
 ✓ src/lib/palette.test.ts (1)
 ✓ src/data/registry.test.ts (2)

 Test Files  3 passed (3)
      Tests  6 passed (6)
   Duration  1.24s
```

### 2. Official Ledger Export Data Verification
```bash
$ python3 -c "import json;d=json.load(open('src/data/official/export.from-ledger.json'));print('models',len(d['models']),'benchmarks',len(d['benchmarks']),'scores',len(d['scores']))"
models 1 benchmarks 1 scores 1
```
The export currently contains a placeholder test fixture (`fake_model_1` with `hf_official_benchmarks`). The UI plumbs this verified fixture data cleanly when switched to **Official** mode.
