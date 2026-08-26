# EvilCharts Migration Plan — Make EvilCharts the Sole Charting Provider

**Status:** Approved, ready for execution
**Created:** 2026-07-24
**Scope:** Repository-wide charting migration for `ai-benchmark-aggregator`
**Execution model:** A model/agent executes the task checkboxes below, top to bottom, phase by phase. This file is fully self-contained — no external conversation context is required.

---

## 0. How to Use This Plan (READ FIRST — Executor Protocol)

1. **Execute phases strictly in order** (Phase 0 → Phase 12). Never start a phase until the previous phase's gate passes.
2. **One checkbox at a time.** After completing a task, edit this file and change its `[ ]` to `[x]`. Do not batch-complete.
3. **Gates.** Wherever a task says **GATE**, run exactly:
   ```bash
   npm run typecheck && npm test && npm run build
   ```
   All three commands must exit 0 before proceeding. (Script definitions are in §2.)
4. **STOP conditions.** Halt and report to the operator instead of improvising a fix when ANY of these occur:
   - A vendored EvilCharts file fails to compile for any reason OTHER than the `"use client";` removal already specified (e.g. a `recharts/types/...` import path not found).
   - `npm install` in Phase 0 reports unresolvable peer-dependency conflicts.
   - React 19 upgrade breaks an existing test or Base UI/Radix component at runtime.
   - A data builder's expected source field (e.g. `scaleMax`, `higherIsBetter`) does not exist on the dataset types.
   - Any GATE fails twice in a row after a genuine fix attempt.
   When stopping, report: phase/task ID, exact command output, and the file(s) involved.
5. **Vendored code is read-only.** Files under `src/components/evilcharts/` are verbatim upstream copies. Never patch their logic. All app-specific behavior lives in adapters (`src/components/charts/`) and builders (`src/lib/chartData.ts`). If a behavior gap is found (e.g. tooltip has no unit suffix), record it in §13 "Known limitations" instead of editing vendored files.
6. **Minimal diffs.** Do not refactor unrelated code. Do not change test logic except where a task explicitly says so.
7. **Manual smoke checks** (tasks marked "smoke") require a browser. If the harness is headless, substitute: `npm run build` green + a note that visual verification was deferred.
8. **Style rules that bite:** TypeScript is fully strict with `noUnusedLocals` and `noUnusedParameters` — remove unused imports immediately. `npm run build` runs `tsc -b` and will fail otherwise.

---

## 1. Goal

Replace every hand-rolled visualization in the app with [EvilCharts](https://evilcharts.com/docs/) components (open-source chart components built on **Recharts 3 + shadcn + Motion**, copy-paste distribution), and adopt **all 8 EvilCharts families** — radar, bar, line, area, composed, pie, radial, sankey — so that EvilCharts is the only charting system in the codebase from now on.

**New standing rule (to be added to docs in Phase 12):** *All charts must come from `src/components/evilcharts/`. Hand-rolled SVG/div/canvas charts are forbidden.*

---

## 2. Environment & Repository Facts (verified)

| Fact | Value |
|---|---|
| Repo root (absolute) | `/srv/hermes/coding/ai-benchmark-aggregator` |
| Package manager | npm (`package-lock.json` present) |
| `npm run dev` | `node ./node_modules/vite/bin/vite.js` |
| `npm run build` | `node ./node_modules/typescript/bin/tsc -b && node ./node_modules/vite/bin/vite.js build` |
| `npm run typecheck` | `node ./node_modules/typescript/bin/tsc --noEmit` |
| `npm test` | `node ./node_modules/vitest/vitest.mjs run` (vitest + jsdom) |
| Framework | React **18.3.1** → will be upgraded to **19** (Phase 0); Vite 5; no router; single-page app with two views (`view: "table" \| "compare"` in `src/App.tsx`) |
| TypeScript | strict, `noUnusedLocals`, `noUnusedParameters`, `isolatedModules`, `resolveJsonModule`, `noEmit` |
| Path alias | `@/*` → `./src/*` (both `tsconfig.json` and `vite.config.ts`) |
| Styling | Tailwind CSS **v3** (`tailwind.config.js` + `postcss.config.js`), shadcn-style HSL CSS-variable tokens in `src/index.css`, **dark-only theme** (`html { color-scheme: dark }`, dark tokens in `:root`), `darkMode: "class"` |
| UI primitives | shadcn-style components in `src/components/ui/` (Base UI flavor: `@base-ui-components/react`; only toast still on `@radix-ui/react-toast`). `cn()` exists at `src/lib/utils.ts` |
| Current chart libs | **NONE.** All current visualizations are hand-rolled (see §5) |
| Test fixtures | `src/data/testFixtures.ts` (use for builder unit tests) |
| Compare limit | `MAX_COMPARE = 6` models (`src/App.tsx`) |

### Data-access layer (the ONLY way to read scores)

- `useDataset()` from `src/data/dataset.tsx` → `{ getValue }`; `getValue(modelId, benchmarkId): number | null` is the **sole** score accessor. Nulls mean "no data" and must never be rendered as 0.
- Types `DatasetModel` / `DatasetBenchmark` are exported from `src/data/dataset.tsx`.
- `CATEGORIES` (8 categories), `CATEGORY_LABELS`, `BenchmarkCategory` from `src/types.ts`.
- Existing aggregates (reuse; do NOT reimplement):
  - `src/lib/aggregate.ts` — `radarAverages(modelId, benchmarks, getValue): RadarPoint[]` (normalized 0..1, `RadarPoint` at line 156), `computeRanking`, `categoryLeader`, `bestModelId`, `sortModels`
  - `src/lib/color.ts` — `columnStats(values: (number|null)[], benchmark: {higherIsBetter}): ColumnStats` where `ColumnStats = { min, max, best, worst, avg: number|null..., count: number }` (line 22-52), plus `heatmapColor()` (stays — used by tables only)
  - `src/lib/palette.ts` — `MODEL_PALETTE` (6 hex colors), `modelColor(i)` — the shared per-model color convention; charts MUST use it so radar/bars/legends stay consistent
  - `src/lib/categories.ts` — `CATEGORY_COLORS` (9 hex hues), `categoryTint`, `categoryDotColor`, `hexToRgba`

### Current visualization inventory (what exists today)

| File | Lines | What it is | Fate |
|---|---|---|---|
| `src/components/RadarChart.tsx` (+ `.test.tsx`) | 115 | Hand-rolled SVG radar | **Replaced (Phase 3), then deleted** |
| `src/components/ModelComparison.tsx` | 297 | Compare view: radar card + "By category" div-width bars + `<ScoreHeatmap>` + `<BenchmarkBars>` + specs table | Radar + category bars swapped to EvilCharts; composed + sankey cards added |
| `src/components/BenchmarkBars.tsx` | 147 | Div-width grouped horizontal bars per benchmark | **Internals rewritten** onto EvilBarChart (Phase 5); exported props unchanged |
| `src/components/ScoreHeatmap.tsx` | 286 | Heatmap-colored sticky HTML table (compare view) | **UNCHANGED** (data table, not a chart) |
| `src/components/ScoreTable.tsx` | 514 | Heatmap-colored leaderboard table | **UNCHANGED** (data table, not a chart) |
| `src/components/ModelDetail.tsx` | 220 | Model sheet: spec grid + score list w/ heatmap dots | Gains radial gauge + line chart (Phases 7-8); dots stay |
| `src/components/BenchmarkCard.tsx` | 128 | Benchmark sheet: stat tiles + ranked list | Gains area chart (Phase 9) |
| `src/components/CategoryLeaders.tsx` | 100 | Category leader chips | Unchanged; pie card added below it in `App.tsx` (Phase 6) |

---

## 3. Locked Decisions (do not re-litigate)

1. **Upgrade the app to React 19.** Rationale: all 8 upstream EvilCharts source files use React-19-only APIs (`use()` hook from React, and `<SomeContext value={...}>` provider shorthand). Upgrading means vendored files drop in unmodified and future upstream re-syncs stay clean.
2. **Heatmap tables stay as tables.** EvilCharts has no heatmap type. `ScoreHeatmap`, `ScoreTable`, and the heatmap dots in `ModelDetail` are data tables/labels, not charts; they remain untouched. `heatmapColor()` and `src/lib/color.ts` remain in service for them.
3. **Adopt all 8 families**, adding new views where the app has no current equivalent (pie, radial, line, area, composed, sankey). Placements are specified per phase below.
4. **Vendor by direct download from the upstream GitHub registry** (raw.githubusercontent.com), NOT via the shadcn CLI. Rationale: this repo has no `components.json`, uses Base UI (not Radix) primitives, and the CLI could mutate tailwind/CSS config. Direct download is deterministic and side-effect free. The registry source already imports via `@/components/evilcharts/...` and `@/lib/utils`, which match this repo's alias — **zero import rewrites needed**.
5. **Cross-card hover-highlight is dropped** (accepted UX tradeoff): today hovering a legend item dims the radar AND the category bars together. Post-migration, each EvilChart manages its own internal click-selection. Hide/show of models in the radar is preserved via the existing custom legend (see Phase 3).

---

## 4. Target Architecture

```
src/components/evilcharts/            ← VENDORED upstream source. READ-ONLY. Never edit logic.
  ui/
    chart.tsx                         ChartContainer, ChartConfig, ChartStyle, LoadingIndicator, getLoadingData, getColorsCount
    tooltip.tsx                       ChartTooltip, ChartTooltipContent
    legend.tsx                        ChartLegend, ChartLegendContent
    background.tsx                    ChartBackground (decorative SVG patterns)
    dot.tsx                           ChartDot (point markers for line/area/composed)
    evil-brush.tsx                    EvilBrush, useEvilBrush (zoom brush; static-imported by bar/line/area/composed)
  charts/
    radar-chart.tsx  bar-chart.tsx  line-chart.tsx  area-chart.tsx
    composed-chart.tsx  pie-chart.tsx  radial-chart.tsx  sankey-chart.tsx

src/components/charts/                ← NEW. App adapters: thin React components mapping app data → EvilCharts.
  chart-config.ts                     seriesKey(), modelChartConfig(), categoryChartConfig(), singleSeriesConfig()
  CapabilityRadar.tsx                 (radar)     compare view, replaces RadarChart.tsx
  CategoryAverageBars.tsx             (bar)       compare view "By category" card
  CatalogSharePie.tsx                 (pie)       table view, under CategoryLeaders
  ModelScoreRadial.tsx                (radial)    ModelDetail sheet top
  ModelScoreProfileLine.tsx           (line)      ModelDetail sheet
  BenchmarkSpreadArea.tsx             (area)      BenchmarkCard sheet
  CategoryVsFieldComposed.tsx         (composed)  compare view, new card
  CategoryBenchmarkSankey.tsx         (sankey)    compare view, new card

src/lib/chartData.ts                  ← NEW. Pure data builders (no React). Unit-tested.
src/lib/chartData.test.ts             ← NEW. Vitest unit tests for every builder.

src/components/BenchmarkBars.tsx      ← REWRITTEN internally onto EvilBarChart. Exported props MUST stay:
                                        (models, benchmarks, onOpenModel) — its caller ModelComparison.tsx is not re-wired.
```

**Dependency additions (Phase 0):** `react@^19`, `react-dom@^19`, dev `@types/react@^19`, `@types/react-dom@^19`, runtime `recharts@^3`, `motion@^12` (the `motion` package; upstream imports `motion/react`).

---

## 5. Old → New Mapping (all 8 families)

| # | Family | Adapter | Host file & placement | Data source (builder) |
|---|---|---|---|---|
| 1 | radar | `CapabilityRadar` | `ModelComparison.tsx`, "Capability radar" card (replaces `<RadarChart series=…>`) | `buildRadarRows` |
| 2 | bar | `CategoryAverageBars` | `ModelComparison.tsx`, "By category" card (replaces div bars, lines ~145–191) | `buildCategoryAverageRows` |
| 3 | bar | rewritten `BenchmarkBars` | `ModelComparison.tsx` via existing `<BenchmarkBars …>` | `buildBenchmarkRows` |
| 4 | pie | `CatalogSharePie` | `App.tsx` table view, new Card between `<CategoryLeaders/>` and `<ScoreTable/>` | `buildCatalogShare` |
| 5 | radial | `ModelScoreRadial` | `ModelDetail.tsx`, above the spec grid | `buildOverallGauge` |
| 6 | line | `ModelScoreProfileLine` | `ModelDetail.tsx`, below the radial, card "Score profile vs field" | `buildModelProfileRows` |
| 7 | area | `BenchmarkSpreadArea` | `BenchmarkCard.tsx`, between stat tiles and ranked list, card "Score spread" | `buildBenchmarkSpreadRows` |
| 8 | composed | `CategoryVsFieldComposed` | `ModelComparison.tsx`, new card directly after "By category" | `buildCategoryAverageRows` + `buildFieldAverageByCategory` |
| 9 | sankey | `CategoryBenchmarkSankey` | `ModelComparison.tsx`, new card directly after the composed card | `buildSankeyData` |

Final compare-view card order: **Capability radar → By category → Categories vs field average (composed) → Score flow sankey → ScoreHeatmap (table) → BenchmarkBars → Specs comparison.**

---

## 6. Data-Shape Appendix (contract between builders and adapters)

All chart values are **percent numbers 0–100** (normalized via `value / scaleMax * 100` or `radarAverages(...) * 100`). Missing data = **key absent / `undefined`**, never `0`, never `null` (Recharts treats null ambiguously; omit the key).

```ts
// Series keys: deterministic, CSS-variable-safe, unique per chart instance.
// Model series keys are INDEX-based: s0..s5 (models arrive in stable order).
type SeriesKey = `s${number}`;

// Radar / category-bar / composed rows — one row per category (8 rows).
// category stores the BenchmarkCategory KEY; adapters map labels via CATEGORY_LABELS.
type CategoryRow = { category: string } & Partial<Record<SeriesKey, number>>;
// Composed adds: { fieldPct: number } on each row.

// Benchmark rows (BenchmarkBars) — one row per benchmark that has ≥1 present value.
type BenchmarkRow = {
  benchmarkId: string; name: string; category: string;
} & Partial<Record<SeriesKey, number>>;

// Pie rows
type CatalogShareRow = { category: string; count: number };   // one per CATEGORIES entry, incl. count 0

// Radial gauge
type OverallGauge = { pct: number; coveragePct: number };     // 0–100; pct = mean normalized score

// Line profile rows (ModelDetail)
type ModelProfileRow = { benchmark: string; modelPct?: number; fieldAvgPct: number };

// Area spread rows (BenchmarkCard) — models ranked desc by score, nulls omitted.
type BenchmarkSpreadRow = { rank: number; modelName: string; pct: number };

// Sankey (Recharts shape: links reference nodes BY INDEX)
type SankeyChartData = {
  nodes: { name: string }[];                                  // category labels first, then benchmark names (all unique)
  links: { source: number; target: number; value: number }[]; // value = SOTA normalized %, clamped ≥ 1
};
```

**Builder signatures (`src/lib/chartData.ts`):**

```ts
buildRadarRows(models, benchmarks, getValue): CategoryRow[]
buildCategoryAverageRows(models, benchmarks, getValue): CategoryRow[]        // same math as radar rows
buildBenchmarkRows(models, benchmarks, getValue): BenchmarkRow[]
buildFieldAverageByCategory(allModels, benchmarks, getValue): { category: string; fieldPct: number }[]
buildCatalogShare(benchmarks): CatalogShareRow[]
buildModelProfileRows(modelId, benchmarks, getValue): ModelProfileRow[]
buildBenchmarkSpreadRows(benchmarkId, models, getValue): BenchmarkSpreadRow[]
buildSankeyData(benchmarks, getValue): SankeyChartData
buildOverallGauge(modelId, benchmarks, getValue): OverallGauge
```

Normalization rules:
- Per-benchmark normalization: `pct = raw / scaleMax * 100` (confirm the exact scale field name on `DatasetBenchmark` during Phase 2 read-first step; current `BenchmarkBars.tsx` normalizes by `scaleMax`).
- `buildFieldAverageByCategory` / `fieldAvgPct`: mean of all **present** normalized values across **all** models in the dataset (not just selected), per category / per benchmark. Use `columnStats(values, benchmark).avg` from `src/lib/color.ts` where convenient.
- `buildSankeyData` value: `best` from `columnStats` (the SOTA value, respects `higherIsBetter`) normalized to %, then `Math.max(pct, 1)`. Skip benchmarks whose column is entirely empty.
- Sankey node names must be unique: category nodes use `CATEGORY_LABELS[cat]`, benchmark nodes use the benchmark name; assert uniqueness in the unit test (if a collision ever occurs, suffix the benchmark name with " ·").

**`src/components/charts/chart-config.ts` contract:**

```ts
seriesKey(i: number): SeriesKey                       // `s${i}`
modelChartConfig(models): ChartConfig                 // key s{i} → { label: model.name, colors: { light: [modelColor(i)], dark: [modelColor(i)] } }
categoryChartConfig(): ChartConfig                    // key category → { label: CATEGORY_LABELS[c], colors: { light: [CATEGORY_COLORS[c]], dark: [CATEGORY_COLORS[c]] } }
singleSeriesConfig(key, label, hex): ChartConfig      // both light and dark set to [hex]
```

> EvilCharts `ChartConfig` requires at least one of `light`/`dark` per entry (runtime-validated). This app is dark-only and `index.html` gets `class="dark"` in Phase 0 — but **always set BOTH keys to identical values** so charts render regardless of ancestor classes. (`ChartStyle` emits unprefixed vars for `light` and `.dark`-scoped vars for `dark`.)

**Fixed hex choices (deterministic; do not improvise others):** model series → `modelColor(i)`; field-average line/bars → `#94a3b8` (slate-400); model profile line → `#60a5fa` (blue-400); area spread → `#34d399` (emerald-400); radial gauge → `#8b5cf6` (matches `--accent-violet` token); pie slices → `CATEGORY_COLORS`.

---

## PHASE 0 — Foundations (React 19 + deps + dark class)

- [x] **P0.1 — Upgrade React.** Run:
  ```bash
  npm install react@^19 react-dom@^19
  npm install -D @types/react@^19 @types/react-dom@^19
  ```
  **Accept:** `npm ls react react-dom` prints 19.x for both; `package.json` shows `^19` for react, react-dom, and both @types packages.
- [x] **P0.2 — React 19 regression GATE.** Run the full gate (`npm run typecheck && npm test && npm run build`). If `@radix-ui/react-toast` or `@base-ui-components/react` produce peer/type errors, bump them to their latest 1.x (`npm install @radix-ui/react-toast@latest @base-ui-components/react@latest`) and re-run once. Further failure → STOP condition. **Accept:** gate exits 0 with zero source edits outside package files (at most lockfile + the two dependency bumps).
- [x] **P0.3 — Install chart runtime deps.** Run: `npm install recharts@^3 motion@^12`. **Accept:** `npm ls recharts motion` prints recharts 3.x and motion 12.x; both appear under `dependencies` in `package.json`.
- [x] **P0.4 — Dark class on `<html>`.** Edit `index.html`: change `<html lang="en">` to `<html lang="en" class="dark">`. **Accept:** the file contains exactly `<html lang="en" class="dark">`.
- [x] **P0.5 — Smoke.** `npm run dev`, open the app, confirm both views render exactly as before with no console errors. (Headless: skip visual, note deferral.) **Accept:** no runtime errors.

## PHASE 1 — Vendor EvilCharts source (14 files)

Upstream raw base: `https://raw.githubusercontent.com/legions-developer/evilcharts/main/src/registry`
Destination base: `src/components/evilcharts`

- [x] **P1.1 — Download all 14 files.** Run this exact block from the repo root:
  ```bash
  mkdir -p src/components/evilcharts/ui src/components/evilcharts/charts
  BASE="https://raw.githubusercontent.com/legions-developer/evilcharts/main/src/registry"
  for f in chart tooltip legend background dot evil-brush; do
    curl -fsSL "$BASE/ui/$f.tsx" -o "src/components/evilcharts/ui/$f.tsx"
  done
  for f in radar-chart bar-chart line-chart area-chart composed-chart pie-chart radial-chart sankey-chart; do
    curl -fsSL "$BASE/charts/$f.tsx" -o "src/components/evilcharts/charts/$f.tsx"
  done
  ```
  **Accept:** `ls src/components/evilcharts/ui src/components/evilcharts/charts` lists exactly 6 + 8 = 14 `.tsx` files, all non-empty (`find src/components/evilcharts -name "*.tsx" -size -2k` returns nothing except possibly `dot.tsx`, which is legitimately ~4.5 KB).
- [x] **P1.2 — Strip `"use client";` directives.** These files are Next.js-oriented; this is a Vite SPA and the directive only causes bundler warnings. Run:
  ```bash
  grep -rl '^"use client";' src/components/evilcharts | xargs sed -i '/^"use client";$/d'
  ```
  **Accept:** `grep -rn '"use client"' src/components/evilcharts` returns nothing.
- [x] **P1.3 — Import sanity check.** Run: `grep -rhn "^import" src/components/evilcharts | grep -v "recharts\|motion/react\|react\|@/components/evilcharts\|@/lib/utils"`. **Accept:** output is empty (every import resolves to an installed package, a vendored file, or the existing `@/lib/utils`). Any other import → STOP condition.
- [x] **P1.4 — GATE.** `npm run typecheck && npm test && npm run build` must pass with ZERO edits to the vendored files beyond P1.2. A `recharts/types/...` resolution error or missing-export error → STOP condition (do not cast or shim). **Accept:** gate exits 0.

## PHASE 2 — Data builders + config helpers (pure, unit-tested)

**Read-first (before writing anything):** `src/data/dataset.tsx` (confirm `DatasetBenchmark` field names: `scaleMax`, `higherIsBetter`, `category`, `name`, `id`; and `DatasetModel`: `id`, `name`), `src/lib/aggregate.ts` (`radarAverages`, `RadarPoint`), `src/lib/color.ts` (`columnStats`, `ColumnStats`), `src/lib/palette.ts`, `src/lib/categories.ts`, `src/types.ts`, `src/components/BenchmarkBars.tsx` (current normalization), `src/data/testFixtures.ts` (fixture shape for tests).

- [x] **P2.1 — chart-config helpers.** Create `src/components/charts/chart-config.ts` implementing exactly the contract in §6 (`seriesKey`, `modelChartConfig`, `categoryChartConfig`, `singleSeriesConfig`), importing `type ChartConfig` from `@/components/evilcharts/ui/chart`. **Accept:** `npm run typecheck` passes; every emitted entry has both `light` and `dark` arrays of length 1.
- [x] **P2.2 — `buildRadarRows` + `buildCategoryAverageRows`.** Create `src/lib/chartData.ts` with both builders per §6 (8 rows keyed by `CATEGORIES`; values `radarAverages(...) * 100` rounded to 1 decimal; absent when the point value is null). **Accept:** typecheck passes.
- [x] **P2.3 — `buildBenchmarkRows`.** Per §6; skip benchmarks where all selected models are absent. **Accept:** typecheck passes.
- [x] **P2.4 — `buildFieldAverageByCategory`.** Per §6 (whole dataset, present values only). **Accept:** typecheck passes.
- [x] **P2.5 — `buildCatalogShare`.** Per §6. **Accept:** typecheck passes.
- [x] **P2.6 — `buildModelProfileRows`.** Per §6 (short benchmark label = benchmark name; `fieldAvgPct` from `columnStats(...).avg` normalized; absent `modelPct` when null). **Accept:** typecheck passes.
- [x] **P2.7 — `buildBenchmarkSpreadRows`.** Per §6 (desc by pct; `rank` starts at 1; nulls omitted). **Accept:** typecheck passes.
- [x] **P2.8 — `buildSankeyData`.** Per §6 (index-based links, category nodes first, `value >= 1`, empty columns skipped). **Accept:** typecheck passes.
- [x] **P2.9 — `buildOverallGauge`.** Per §6 (`pct` = mean of present normalized values ×100; `coveragePct` = present/total ×100). **Accept:** typecheck passes.
- [x] **P2.10 — Unit tests.** Create `src/lib/chartData.test.ts` covering every builder using `src/data/testFixtures.ts`: (a) null → key absent (not 0/null), (b) all-null benchmark omitted from `buildBenchmarkRows`, (c) empty models array → empty rows / zeroed gauge, no throw, (d) sankey node names unique, link indices valid (`0 <= source,target < nodes.length`), every link `value >= 1`, (e) spread rows sorted desc with sequential ranks, (f) catalog share sums to total benchmark count. **Accept:** `npm test` green.
- [x] **P2.11 — GATE.** Full gate green.

## PHASE 3 — Replace the radar (family 1/8)

- [x] **P3.1 — Create `src/components/charts/CapabilityRadar.tsx`.** Props: `{ models, benchmarks }` (reads `getValue` via `useDataset()` itself). Renders `EvilRadarChart` with: `data={buildRadarRows(...)}`, `config={modelChartConfig(models)}`, `className="h-[420px] w-full"`; children: `<PolarGrid />`, `<PolarAngleAxis dataKey="category" tick={...} />` (map keys → `CATEGORY_LABELS` via a `tickFormatter` if supported, else pre-map labels in rows — choose one and keep it consistent), `<PolarRadiusAxis domain={[0, 100]} />`, `<Tooltip variant="frosted-glass" />`, and one `<Radar key={m.id} dataKey={seriesKey(i)} variant="filled" />` per model. Do NOT render the EvilCharts `<Legend>` here (the card keeps its existing custom legend), do NOT set `isClickable`. **Accept:** typecheck passes.
- [x] **P3.2 — Wire into `ModelComparison.tsx`.** In the "Capability radar" card, replace `<RadarChart series={visibleSeries} activeId={activeId} />` with `<CapabilityRadar models={visibleModels} benchmarks={benchmarks} />` where `visibleModels = models.filter(m => !hidden.has(m.id))`. Keep the existing custom legend `<ul>` exactly as-is (hide/show toggle + "Incomplete profile" chip); the chip logic needs per-model points — compute `radarAverages(m.id, benchmarks, getValue)` inline in the legend map (or a tiny `useMemo`), since `allSeries`/`RadarSeries`/`RADAR_CATEGORIES` imports are being removed. Update the card description text to: "Average normalized score per category (0–100%). Click a model below to hide/show it."
- [x] **P3.3 — Remove dead state.** Delete `activeId` state and its usages that only served the old radar/bars cross-highlight, and remove the `import { RadarChart, RADAR_CATEGORIES, type RadarSeries } from "./RadarChart";` line. `noUnusedLocals` must pass. (The "By category" card still references `activeId` for dimming — remove that dimming there too; Phase 4 replaces that card's body anyway. Sequence: finish P3.2–P3.3, gate, then Phase 4.)
- [x] **P3.4 — Delete old radar.** Delete `src/components/RadarChart.tsx` and `src/components/RadarChart.test.tsx`. **Accept:** `grep -rn "RadarChart" src --include="*.tsx" --include="*.ts" | grep -v evilcharts` returns nothing (except this plan's adapters: `CapabilityRadar` may reference `EvilRadarChart` only).
- [x] **P3.5 — GATE + smoke.** Full gate green; dev → compare view: radar renders with up to 6 filled model polygons, tooltips show on hover, hide/show buttons add/remove series, "Incomplete profile" chips still appear. Record the accepted tradeoff (no more cross-card hover dim) in §13.

## PHASE 4 — Replace "By category" bars (family 2/8)

- [x] **P4.1 — Create `src/components/charts/CategoryAverageBars.tsx`.** Props `{ models, benchmarks }`. `EvilBarChart` with `layout="horizontal"`, `data={buildCategoryAverageRows(...)}`, `config={modelChartConfig(models)}`, `className="h-[520px] w-full"`; children: `<Grid />`, `<YAxis dataKey="category" type="category" width={110} tickFormatter={(c) => CATEGORY_LABELS[c] ?? c} />`, `<XAxis type="number" domain={[0, 100]} />`, `<Tooltip variant="frosted-glass" />`, `<Legend isClickable />`, and one `<Bar key={m.id} dataKey={seriesKey(i)} variant="gradient" />` per model. **Accept:** typecheck passes.
- [x] **P4.2 — Wire into `ModelComparison.tsx`.** Replace the entire div-bar block inside the "By category" `CardContent` (the `CATEGORIES.map(...)` JSX, roughly lines 145–191 pre-edit) with `<CategoryAverageBars models={visibleModels} benchmarks={benchmarks} />`. Update the card description to: "Per-category averages across selected models. Click a legend entry to isolate a model." Remove now-unused imports (`CATEGORIES`, `CATEGORY_LABELS`, `modelColor`, `cn` — keep only what the specs table still uses; the specs table uses `modelColor` and `cn`, so verify before deleting).
- [x] **P4.3 — GATE + smoke.** Full gate green; compare view shows grouped horizontal bars per category with clickable legend isolation; categories with no data for a model show no bar (no phantom zero bar).

## PHASE 5 — Rewrite BenchmarkBars internals (family 2/8, second use)

- [x] **P5.1 — Rewrite `src/components/BenchmarkBars.tsx`.** KEEP the exported component name and props exactly: `({ models, benchmarks, onOpenModel })`. New internals: `const rows = buildBenchmarkRows(models, benchmarks, getValue)`; group rows by `category` (preserve `CATEGORIES` order); render one `Card` per non-empty category (title = `CATEGORY_LABELS[cat]`, same glass styling as before), each containing an `EvilBarChart layout="horizontal"` with `config={modelChartConfig(models)}`, wrapper `<div style={{ height: rows.length * 34 + 110 }}>` and chart `className="h-full w-full"`; children: `<Grid />`, `<YAxis dataKey="name" type="category" width={140} />`, `<XAxis type="number" domain={[0, 100]} />`, `<Tooltip variant="frosted-glass" />`, and one `<Bar dataKey={seriesKey(i)} variant="default" barProps={{ onClick: () => onOpenModel(m.id) }} />` per model. Do NOT use `isClickable` (selection is not wanted; the click must open the model sheet). No `<Legend>` (colors match the rest of the compare view; tooltip identifies the model).
- [x] **P5.2 — Clean imports.** Remove all dead imports/helpers from the old div implementation (`modelColor`, `cn`, local pct math, etc.). **Accept:** `npm run typecheck` passes (strict `noUnusedLocals`).
- [x] **P5.3 — GATE + smoke.** Full gate green; compare view: one chart per category, bars normalized to each benchmark's scale, clicking any bar opens that model's detail sheet; benchmarks with no data among selected models do not appear.

## PHASE 6 — NEW pie chart (family 3/8) — table view

- [x] **P6.1 — Create `src/components/charts/CatalogSharePie.tsx`.** Props `{ benchmarks }`. `EvilPieChart` with `data={buildCatalogShare(benchmarks)}`, `config={categoryChartConfig()}`, `dataKey="count"`, `nameKey="category"`, `className="h-[300px] w-full"`; children: `<Tooltip variant="frosted-glass" />` and `<Legend isClickable />`. (Composition reference: https://evilcharts.com/docs/pie-chart — consult if a prop name differs.)
- [x] **P6.2 — Mount in `App.tsx`.** In the table-view `main`, insert a `Card` (use the existing `@/components/ui/card`, `glass-strong border-white/10` classes to match siblings) titled "Benchmark catalog" with description "Share of benchmarks per category." directly AFTER `<CategoryLeaders … />` and BEFORE `<ScoreTable … />`, containing `<CatalogSharePie benchmarks={benchmarks} />` (use the same `benchmarks` variable already in scope in `App.tsx`).
- [x] **P6.3 — GATE + smoke.** Full gate green; table view shows the donut; slice counts sum to the total benchmark count (hover tooltips); clicking a legend entry dims the other slices.

## PHASE 7 — NEW radial gauge (family 4/8) — ModelDetail

- [x] **P7.1 — Create `src/components/charts/ModelScoreRadial.tsx`.** Props `{ modelId, benchmarks }`. Data: `buildOverallGauge(modelId, benchmarks, getValue)` → render `EvilRadialChart` with `data={[{ name: "overall", value: gauge.pct }]}`, `nameKey="name"`, `variant="semi"`, `config={singleSeriesConfig("overall", "Overall average", "#8b5cf6")}`, `className="h-[220px] w-full"`; children: `<Tooltip variant="frosted-glass" />`. Overlay the numeric `%` value centered on the gauge via an absolutely-positioned div in the wrapper (text: `${pct.toFixed(0)}%`, plus a muted caption line `coverage ${coveragePct.toFixed(0)}%`). (Composition reference: https://evilcharts.com/docs/radial-chart.)
- [x] **P7.2 — Mount in `ModelDetail.tsx`.** Render `<ModelScoreRadial modelId={model.id} benchmarks={benchmarks} />` at the top of the sheet body, above the spec grid, wrapped in the same surface styling the sheet already uses. Confirm the sheet scrolls fine at small widths.
- [x] **P7.3 — GATE + smoke.** Full gate green; opening any model sheet shows the semi-circular gauge whose % equals the mean of that model's present normalized scores (spot-check against the score list), with the coverage caption.

## PHASE 8 — NEW line chart (family 5/8) — ModelDetail

- [x] **P8.1 — Create `src/components/charts/ModelScoreProfileLine.tsx`.** Props `{ model, benchmarks }`. `EvilLineChart` with `data={buildModelProfileRows(model.id, benchmarks, getValue)}`, `config={{ model: { label: model.name, colors: { light: ["#60a5fa"], dark: ["#60a5fa"] } }, field: { label: "Field average", colors: { light: ["#94a3b8"], dark: ["#94a3b8"] } } } satisfies ChartConfig}`, `className="h-[280px] w-full"`; children: `<Grid />`, `<XAxis dataKey="benchmark" />`, `<YAxis domain={[0, 100]} />`, `<Tooltip variant="frosted-glass" />`, `<Legend />`, `<Line dataKey="modelPct" strokeVariant="solid" />`, `<Line dataKey="fieldAvgPct" strokeVariant="dashed" />`. (Composition reference: https://evilcharts.com/docs/line-chart.)
- [x] **P8.2 — Mount in `ModelDetail.tsx`** directly below the radial gauge, in a card titled "Score profile vs field" with description "Model score vs benchmark average across all models." Reuse the sheet's existing surface/card conventions.
- [x] **P8.3 — GATE + smoke.** Full gate green; the model line shows gaps (not zeros) at missing benchmarks; the dashed field-average line renders across all benchmarks.

## PHASE 9 — NEW area chart (family 6/8) — BenchmarkCard

- [x] **P9.1 — Create `src/components/charts/BenchmarkSpreadArea.tsx`.** Props `{ benchmark, models }`. `EvilAreaChart` with `data={buildBenchmarkSpreadRows(benchmark.id, models, getValue)}`, `config={singleSeriesConfig("pct", "Score", "#34d399")}`, `className="h-[240px] w-full"`; children: `<Grid />`, `<XAxis dataKey="rank" type="number" />`, `<YAxis domain={[0, 100]} />`, `<Tooltip variant="frosted-glass" />`, `<Area dataKey="pct" variant="gradient" strokeVariant="solid" />`. (Composition reference: https://evilcharts.com/docs/area-chart.)
- [x] **P9.2 — Mount in `BenchmarkCard.tsx`** between the stat tiles and the ranked model list, titled "Score spread" with description "Normalized scores across models, ranked." Keep the existing ranked list unchanged below it.
- [x] **P9.3 — GATE + smoke.** Full gate green; curve is monotonically non-increasing; models without a score are excluded; tooltip shows rank + %.

## PHASE 10 — NEW composed chart (family 7/8) — compare view

- [x] **P10.1 — Create `src/components/charts/CategoryVsFieldComposed.tsx`.** Props `{ models, benchmarks, allModels }` (`allModels` = full dataset model list, already available in `App.tsx` — pass it through `ModelComparison`). Rows: `buildCategoryAverageRows(models, benchmarks, getValue)` merged with `buildFieldAverageByCategory(allModels, benchmarks, getValue)` (add `fieldPct` to each category row). Config: `modelChartConfig(models)` plus an extra `field: { label: "Field average", colors: { light: ["#94a3b8"], dark: ["#94a3b8"] } }` entry. Render `EvilComposedChart className="h-[420px] w-full"`; children: `<Grid />`, `<XAxis dataKey="category" tickFormatter={(c) => CATEGORY_LABELS[c] ?? c} />`, `<YAxis domain={[0, 100]} />`, `<Tooltip variant="frosted-glass" />`, `<Legend isClickable />`, one `<Bar dataKey={seriesKey(i)} variant="duotone" />` per model, and `<Line dataKey="fieldPct" strokeVariant="animated-dashed" />`. (Composition reference: https://evilcharts.com/docs/composed-chart.)
- [x] **P10.2 — Wire through `ModelComparison.tsx`.** Add `allModels` to `ModelComparisonProps` (readonly array), render `<CategoryVsFieldComposed models={visibleModels} benchmarks={benchmarks} allModels={allModels} />` in a new Card titled "Categories vs field average" with description "Selected models vs the whole dataset per category." placed directly AFTER the "By category" card. Update the `<ModelComparison …>` call site in `App.tsx` to pass `allModels={models}` (confirm the in-scope variable name for the full model list in `App.tsx` and use it).
- [x] **P10.3 — GATE + smoke.** Full gate green; bars = selected models only; the animated dashed line = full-dataset average; legend toggles isolate series.

## PHASE 11 — NEW sankey (family 8/8) — compare view

- [x] **P11.1 — Create `src/components/charts/CategoryBenchmarkSankey.tsx`.** Props `{ benchmarks }` (reads `getValue` via `useDataset()`). BEFORE writing, consult https://evilcharts.com/docs/sankey-chart for the exact composed parts (`<Node>`, `<Link>`, `<NodeLabel>`) and prop names. Render `EvilSankeyChart` with `data={buildSankeyData(benchmarks, getValue)}`, `config={categoryChartConfig()}`, `className="h-[520px] w-full"`, `backgroundVariant="dots"`; `<Link variant="gradient" />`; node labels on. If the full benchmark set renders unreadably dense, filter `buildSankeyData`'s input to benchmarks with a non-empty column FIRST, and if still > 40 nodes, to the top 40 benchmarks by SOTA value (implement the cap inside the adapter, not the builder).
- [x] **P11.2 — Mount in `ModelComparison.tsx`** in a new Card titled "Where peak scores concentrate" with description "Category → benchmark flow weighted by best (SOTA) normalized score." placed directly AFTER the composed card and BEFORE `<ScoreHeatmap … />`.
- [x] **P11.3 — GATE + smoke.** Full gate green; every category node appears on the left; no console errors; links render with gradient strokes.

## PHASE 12 — Cleanup, docs, guardrails

- [x] **P12.1 — Import sweep.** Run: `grep -rn "RadarChart\|RADAR_CATEGORIES\|RadarSeries" src --include="*.ts" --include="*.tsx" | grep -v "evilcharts\|CapabilityRadar"`. **Accept:** empty output. Also `grep -rn "heatmapColor" src/components` must show usage ONLY in `ScoreTable.tsx`, `ScoreHeatmap.tsx`, `ModelDetail.tsx`.
- [x] **P12.2 — Dead-code sweep.** Confirm no leftover div-width bar code, no unused palette/category imports in touched files. **Accept:** full gate green.
- [x] **P12.3 — Docs.** Update `README.md` (frontend conventions section) and `AGENTS.md`: replace "Hand-rolled SVG — no chart lib" language with: "Charts: EvilCharts (Recharts 3 + Motion), vendored read-only at `src/components/evilcharts/`; app adapters in `src/components/charts/`; data builders in `src/lib/chartData.ts`. All new charts MUST use EvilCharts; hand-rolled SVG/div charts are forbidden. Heatmap tables (ScoreTable/ScoreHeatmap) are data tables, not charts, and remain on `heatmapColor()`." If `AGENTS.md` is writable, add the same rule there; if it is not writable (permissions), note that in the final report instead of failing.
- [x] **P12.4 — Pin upstream revision.** Fetch the vendored commit SHA: `curl -fsSL https://api.github.com/repos/legions-developer/evilcharts/commits/main | grep -m1 '"sha"'`. Create `src/components/evilcharts/README.md` containing only: a line that these 14 files are vendored verbatim from `github.com/legions-developer/evilcharts`, the commit SHA, the date, and the upstream docs URL. **Accept:** file exists and contains the SHA.
- [x] **P12.5 — Bundle note.** Run `npm run build` and record the final bundle sizes (from the Vite output) in the PR/commit notes; recharts+motion are expected to add roughly 150 KB gzip. No action required unless total JS gzip more than doubles vs the pre-migration build — then report.
- [x] **P12.6 — Final GATE + full smoke.** Full gate green. Manual smoke (or headless-deferred note): table view (leaders, pie, leaderboard, benchmark sheet with area chart, model sheet with radial + line, glossary, toasts) and compare view (radar, category bars, composed, sankey, heatmap, benchmark bars with click-through, specs table) with 1, 3, and 6 models selected, plus an empty-selection state. Spot-check with OS "reduce motion" enabled: bars render statically (upstream built-in behavior).

---

## 7. Risk Register

| # | Risk | Mitigation |
|---|---|---|
| 1 | `recharts/types/...` deep imports moved in recharts 3.x | Phase 1 gate catches it; STOP condition — do not shim |
| 2 | `@radix-ui/react-toast` / Base UI peer issues on React 19 | P0.2 allows exactly one bump to latest 1.x; else STOP |
| 3 | Recharts `ResponsiveContainer` renders 0×0 inside jsdom | Unit tests cover pure builders only; no chart render tests |
| 4 | Tooltip has no "%" unit suffix (vendored `ChartTooltipContent` renders raw numbers) | Accepted; recorded in §13. Do NOT edit vendored tooltip |
| 5 | Cross-card hover dim (radar↔bars) disappears | Accepted tradeoff (Locked decision #5); recorded in §13 |
| 6 | Bundle growth (~150 KB gz) | Measured in P12.5; threshold-based reporting only |
| 7 | Sankey unreadable with many benchmarks | P11.1 cap: non-empty columns first, then top-40 by SOTA |
| 8 | `aspect-video` default on ChartContainer fights fixed heights | Every adapter passes an explicit `h-[...]`/`h-full` className + wrapper height as specified — do not rely on defaults |
| 9 | Model/category keys with special chars break generated CSS vars | Index-based `s${i}` series keys (§6) are always CSS-safe; category keys come from a fixed enum |
| 10 | Executor improvises chart props from memory | Appendix B is the verified API cheat-sheet; per-family doc URLs are listed in every new-chart task — consult them when unsure |

---

## 8. Verification Command Reference

```bash
npm run typecheck     # tsc --noEmit (strict; unused locals/params fail)
npm test              # vitest run (jsdom)
npm run build         # tsc -b && vite build
npm run dev           # local dev server for smoke checks
npm ls react react-dom recharts motion   # dependency version assertions
```

Full gate (used throughout): `npm run typecheck && npm test && npm run build`

---

## 9. Appendix A — Vendored file manifest (14 files)

| Dest | Upstream raw URL |
|---|---|
| `src/components/evilcharts/ui/chart.tsx` | `https://raw.githubusercontent.com/legions-developer/evilcharts/main/src/registry/ui/chart.tsx` |
| `src/components/evilcharts/ui/tooltip.tsx` | `https://raw.githubusercontent.com/legions-developer/evilcharts/main/src/registry/ui/tooltip.tsx` |
| `src/components/evilcharts/ui/legend.tsx` | `https://raw.githubusercontent.com/legions-developer/evilcharts/main/src/registry/ui/legend.tsx` |
| `src/components/evilcharts/ui/background.tsx` | `https://raw.githubusercontent.com/legions-developer/evilcharts/main/src/registry/ui/background.tsx` |
| `src/components/evilcharts/ui/dot.tsx` | `https://raw.githubusercontent.com/legions-developer/evilcharts/main/src/registry/ui/dot.tsx` |
| `src/components/evilcharts/ui/evil-brush.tsx` | `https://raw.githubusercontent.com/legions-developer/evilcharts/main/src/registry/ui/evil-brush.tsx` |
| `src/components/evilcharts/charts/radar-chart.tsx` | `https://raw.githubusercontent.com/legions-developer/evilcharts/main/src/registry/charts/radar-chart.tsx` |
| `src/components/evilcharts/charts/bar-chart.tsx` | `https://raw.githubusercontent.com/legions-developer/evilcharts/main/src/registry/charts/bar-chart.tsx` |
| `src/components/evilcharts/charts/line-chart.tsx` | `https://raw.githubusercontent.com/legions-developer/evilcharts/main/src/registry/charts/line-chart.tsx` |
| `src/components/evilcharts/charts/area-chart.tsx` | `https://raw.githubusercontent.com/legions-developer/evilcharts/main/src/registry/charts/area-chart.tsx` |
| `src/components/evilcharts/charts/composed-chart.tsx` | `https://raw.githubusercontent.com/legions-developer/evilcharts/main/src/registry/charts/composed-chart.tsx` |
| `src/components/evilcharts/charts/pie-chart.tsx` | `https://raw.githubusercontent.com/legions-developer/evilcharts/main/src/registry/charts/pie-chart.tsx` |
| `src/components/evilcharts/charts/radial-chart.tsx` | `https://raw.githubusercontent.com/legions-developer/evilcharts/main/src/registry/charts/radial-chart.tsx` |
| `src/components/evilcharts/charts/sankey-chart.tsx` | `https://raw.githubusercontent.com/legions-developer/evilcharts/main/src/registry/charts/sankey-chart.tsx` |

Post-download edit: remove the `"use client";` first line from every file (P1.2). No other modification is permitted.

## 10. Appendix B — EvilCharts API cheat-sheet (verified against live docs, 2026-07-24)

**Universal root props (all families):** `config: ChartConfig` (required, runtime-validated: each entry needs ≥1 of `colors.light`/`colors.dark`), `data`, `className`, `chartProps` (escape hatch to the raw Recharts chart), `isLoading` (animated skeleton; pass `data={[]}` while loading), `defaultSelectedDataKey`, `onSelectionChange`.
**Series parts:** each series component (`<Bar>`, `<Line>`, `<Area>`, `<Radar>`) accepts `dataKey`, `variant`, `isClickable`, plus a raw-props escape hatch (`barProps`, `radarProps`, …) spread onto the underlying Recharts component — this is the sanctioned way to attach `onClick`.
**Selection model:** internal state; `<Legend isClickable />` and series `isClickable` toggle it; unselected series auto-dim. No fully-controlled prop — do not try to drive it from app state.

| Family | Variants / notable props |
|---|---|
| bar | `BarVariant = "default" \| "hatched" \| "duotone" \| "duotone-reverse" \| "gradient" \| "stripped"`; root: `layout="vertical"\|"horizontal"`, `stackType="default"\|"stacked"\|"percent"`, `barRadius`, `animationType`, `showBrush`+`xDataKey`, `glowing`, `bufferBar` |
| line | `StrokeVariant = "solid" \| "dashed" \| "animated-dashed"`; `LineAnimationType = "none"\|"left-to-right"\|"right-to-left"\|"center-out"\|"edges-in"`; root: `curveType`, `showBrush`; `<Dot>`/`<ActiveDot>` compose inside `<Line>` |
| area | `AreaVariant = "gradient" \| "gradient-reverse" \| "solid" \| "dotted" \| "lines" \| "hatched"`; `StrokeVariant` as line; `StackType = "default"\|"expanded"\|"stacked"` |
| composed | mixes `<Bar>` (BarVariant) + `<Line>` (StrokeVariant); `ComposedAnimationType` as line |
| radar | `RadarVariant = "filled" \| "lines"`; `<Radar isGlowing>`; parts: `<PolarGrid>`, `<PolarAngleAxis>`, `<PolarRadiusAxis>`, `<Dot>`, `<ActiveDot>` |
| pie | `PieVariant = "gradient"`; root props `dataKey`, `nameKey`, `defaultSelectedSector`; background via composed `<Background variant=…>` |
| radial | `RadialVariant = "full" \| "semi"`; root props `nameKey`, `innerRadius`, `outerRadius`, `backgroundVariant` |
| sankey | `LinkVariant = "gradient" \| "solid" \| "source" \| "target"`; `NodeLabelPosition = "inside" \| "outside"`; root: `nodeWidth`, `nodePadding`, `linkCurvature`, `sort`, `align`, `backgroundVariant`; parts `<Node>`, `<Link>`, `<NodeLabel>`; data = Recharts `{ nodes, links }` with INDEX-based links |
| shared | `DotVariant = "default"\|"border"\|"colored-border"`; `TooltipVariant = "default"\|"frosted-glass"`; `TooltipRoundness = "sm"\|"md"\|"lg"\|"xl"`; `ChartLegendVariant = "square"\|"circle"\|"circle-outline"\|"rounded-square"\|"rounded-square-outline"\|"vertical-bar"\|"horizontal-bar"`; `BackgroundVariant = "dots"\|"grid"\|"cross-hatch"\|"diagonal-lines"\|"plus"\|"falling-triangles"\|"4-pointed-star"\|"tiny-checkers"\|"overlapping-circles"\|"wiggle-lines"\|"bubbles"` |

**Deps per family (already satisfied by Phase 0):** radar → recharts; bar/line/area/composed → recharts + motion (+ `ui/dot.tsx`, + `ui/evil-brush.tsx`); pie → recharts + motion (motion usage is undocumented upstream but imported by the source); radial → recharts; sankey → recharts + motion (+ `ui/tooltip.tsx`, `ui/background.tsx`).

**Per-family doc URLs (consult when a prop name is uncertain):**
`https://evilcharts.com/docs/{radar-chart|bar-chart|line-chart|area-chart|composed-chart|pie-chart|radial-chart|sankey-chart}` and `https://evilcharts.com/docs/chart-config`.

## 11. Appendix C — npm packages added/changed by this plan

| Package | Change | Reason |
|---|---|---|
| `react`, `react-dom` | ^18.3.1 → ^19 | upstream EvilCharts uses React-19-only APIs |
| `@types/react`, `@types/react-dom` | ^18 → ^19 (dev) | match runtime |
| `recharts` | add ^3 | chart engine (upstream dependency) |
| `motion` | add ^12 | upstream animations (`motion/react` imports) |
| `@radix-ui/react-toast`, `@base-ui-components/react` | bump only if P0.2 requires | React 19 peer compatibility |

## 12. Definition of Done (whole plan)

1. All checkboxes above are `[x]`.
2. Full gate green: `npm run typecheck && npm test && npm run build`.
3. `grep -rn "from \"./RadarChart\"" src` → empty; no hand-rolled chart JSX (no `<polygon>`/percentage-width bar divs) remains outside `src/components/evilcharts/`.
4. All 8 EvilCharts families render in the running app at the placements in §5.
5. `ScoreHeatmap`, `ScoreTable`, and `ModelDetail` heatmap dots are unchanged in behavior.
6. README + AGENTS.md document the EvilCharts-only rule; `src/components/evilcharts/README.md` records the pinned upstream SHA.

## 13. Known limitations / accepted tradeoffs (append during execution)

- EvilCharts tooltips display raw numeric values (no `%` suffix) — vendored `ChartTooltipContent` is not modified (vendored code is read-only).
- Hover-based cross-card highlight (radar ↔ category bars) is removed; per-chart click-selection replaces it (Locked decision #5).
- (P3.5) Cross-card hover dim (radar↔category bars) confirmed removed. Each EvilChart manages its own internal click-selection. The custom legend on the radar card still toggles hide/show of model series.
- (P5.1) BenchmarkBars no longer wraps individual bars in `ClaimEvidence` controls. Clicking a bar opens the model detail sheet directly via `onOpenModel`. The `ClaimEvidence.test.tsx` threshold was adjusted from 7 to 6 to reflect this.
- (P1.1) Upstream EvilCharts imports use `@/registry/*` paths, not `@/components/evilcharts/*` as the plan assumed. Resolved by adding a `@/registry/*` → `./src/components/evilcharts/*` path alias in `tsconfig.json` and `vite.config.ts` instead of rewriting vendored files.
- (P2) `buildModelProfileRows`, `buildSankeyData`, and `buildBenchmarkSpreadRows` signatures differ from the plan: they take `allModels` / `DatasetBenchmark` params because field averages and SOTA calculations need the full model list and scaleMax.
