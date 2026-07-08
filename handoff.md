# Handoff — AI Benchmark Aggregator

> This document is for the **next agent** taking over work on this project. It is the single
> source of truth for orientation, conventions, what was just changed, and the one pending
> task (a Radix → Base UI migration). Read it top to bottom before editing code.

---

## 1. What this project is

A single-page **AI model benchmark comparison dashboard**. It shows a leaderboard-style table of
models scored across ~17 benchmarks in 8 categories, plus a **Compare** view that renders
multiple selected models side by side as several glassmorphic charts.

- Synthetic/demo data (no backend). All data lives in `src/data/*`.
- Pure client-side React + Vite + TypeScript (strict). No router, no state library — `App.tsx`
  holds all view state with `useState`/`useMemo`.
- Dark "liquid-glass" visual theme via Tailwind + a few custom CSS utilities in `src/index.css`.

**Entry point:** `src/main.tsx` → `src/App.tsx`.
**Address (local path):** `/Users/stevmq/ai-benchmark-aggregator`

---

## 2. Stack

| Concern        | Choice                                            |
| -------------- | ------------------------------------------------- |
| Build          | Vite 5                                            |
| Language       | TypeScript (strict, `tsc -b`)                     |
| UI             | React 18                                          |
| Styling        | Tailwind CSS 3 + `tailwind-merge` + `clsx`        |
| Primitives     | **Radix UI** wrappers in `src/components/ui/*`    |
| Icons          | `lucide-react`                                    |
| Charts         | Hand-rolled SVG (`RadarChart`) — no chart lib     |

`npm` scripts: `dev`, `build` (`tsc -b && vite build`), `preview`, `typecheck`.

---

## 3. How to run / verify

```bash
cd /Users/stevmq/ai-benchmark-aggregator
npm install        # only if node_modules is missing
npm run dev        # dev server (Vite prints a Local: http://localhost:517x/ URL)
npm run build      # tsc strict + vite production build — MUST stay green
npm run typecheck  # tsc --noEmit, fastest correctness check
```

There is **no git repo** here. If the next agent needs history, `git init` first before committing.

---

## 4. Navigation / two views

`App.tsx` keeps a `view` state: `"table"` (default) or `"compare"`.

- **Table view** (`src/components/ScoreTable.tsx`): the leaderboard. Models are ranked
  (`computeRanking`), grouped into category columns, heatmap-colored, with sort + per-benchmark
  detail popovers and a "Column best" footer. Clicking a model name opens the **Model Sheet**
  (`ModelDetail.tsx`); clicking a benchmark header opens the **Benchmark Sheet**
  (`BenchmarkCard.tsx`).
- **Compare view** (`src/components/ModelComparison.tsx`): receives `selectedModelObjects` and a
  new `onOpenModel` callback from `App.tsx`. Renders **five stacked full-width glass cards**:
  1. Capability radar (`RadarChart`, outline-only, hover-to-highlight legend)
  2. By-category averaged bars
  3. **Score heatmap matrix** (`ScoreHeatmap.tsx`, NEW this session)
  4. **Per-benchmark grouped bars** (`BenchmarkBars.tsx`, NEW this session)
  5. Specs comparison table (models as columns, "Leads in N" badges)

Model selection for Compare happens in the **table view** via checkboxes (max `MAX_COMPARE = 6`,
enforced in `App.tsx`). Toasts confirm add/remove.

---

## 5. Directory map (what matters)

```
src/
  App.tsx                  # all view state, routing between views, two Sheets, Toaster
  main.tsx                 # React root
  index.css                # Tailwind + glass utilities + SOTA pulse animation
  types.ts                 # Model, Benchmark, BenchmarkCategory, CATEGORIES, CATEGORY_LABELS
  data/
    models.ts              # model catalog
    benchmarks.ts          # 17 benchmarks (id, name, category, scaleMax, higherIsBetter, ...)
    scores.ts              # getValue(modelId, benchmarkId) — the single score accessor
  lib/
    aggregate.ts           # ranking + averages: computeRanking, radarAverages,
                           #   categoryAverages, categoryLeader, bestModelId, sortModels
    color.ts               # columnStats, heatmapColor (blue→green glass gradient)
    categories.ts          # CATEGORY_COLORS, categoryTint, hexToRgba
    palette.ts             # MODEL_PALETTE + modelColor(i) — shared model colors
    utils.ts               # cn()
  components/
    ScoreTable.tsx         # leaderboard table
    ScoreHeatmap.tsx       # NEW — compare heatmap matrix
    BenchmarkBars.tsx      # NEW — compare per-benchmark bars
    RadarChart.tsx         # SVG radar; accepts activeId for hover highlight
    ModelComparison.tsx    # compare layout (restructured this session)
    ModelDetail.tsx        # model Sheet content
    BenchmarkCard.tsx      # benchmark Sheet content
    CategoryLeaders.tsx    # strip of per-category leaders
    Filters.tsx, Header.tsx, GlossaryDialog.tsx
    ui/                    # Radix-based primitives (see §9 for migration)
```

---

## 6. Data model & helpers (reuse these — do not reinvent)

- `getValue(modelId, benchmarkId)` (`src/data/scores.ts`) is the **only** way to read a score.
  Returns `number | null` (null = model has no score for that benchmark, e.g. non-vision models
  on vision benchmarks). Heatmap/bars/table all handle null as "no data".
- `benchmarks` / `models` are flat arrays; `CATEGORIES` is the ordered category list.
- Aggregation helpers in `lib/aggregate.ts`: `computeRanking`, `radarAverages`,
  `categoryAverages`, `categoryLeader`, `bestModelId`, `sortModels`.
- Color helpers: `heatmapColor(v, stats, b)` and `columnStats(values, b)` in `lib/color.ts`;
  `CATEGORY_COLORS` / `categoryTint` in `lib/categories.ts`; `modelColor(i)` in `lib/palette.ts`.

---

## 7. Conventions to follow

- **`cn(...)`** for all conditional class merging (never raw template strings with conditional
  classes).
- **Glass surfaces**: use `glass-strong` / `glass-inset` utility classes (defined in `index.css`),
  not ad-hoc backgrounds. Cards = the `Card` primitive in `ui/card.tsx`.
- **Sticky columns** in tables (ScoreTable, ScoreHeatmap): use plain `overflow-x-auto` +
  `position: sticky; left:0` with a solid-ish `background` (`STICKY_BG = "rgba(13,18,28,0.94)"`).
  **Do not use Radix `ScrollArea` for these** — it breaks `position: sticky`.
- **SOTA / "best in column" indicator** is now an **animated gold ring** (`.sota-cell` in
  `index.css`), not a star icon. Legends use the `.sota-swatch` chip. Do not reintroduce the
  `Star` icon for this.
- **Model Sheet inside Compare**: the Model Sheet is a single independent Radix `Dialog` rooted in
  `App.tsx`. Never nest a `Sheet` inside another `Sheet`.
- Colors for selected models must come from `modelColor(i)` (shared palette) so the radar,
  category bars, and benchmark bars stay consistent.

---

## 8. Work completed in the most recent session

Both items below are implemented and the production build is green.

### 8.1 Compare page redesign (multi-chart glass layout)
Plan file (reference only): `/Users/stevmq/.local/share/kilo/plans/1783378791076-compare-page-graphs-redesign.md`

- `RadarChart.tsx`: added `activeId` prop. When `activeId` is null, all series render as
  **outlines only** (no fill) so they don't superimpose into a blob. The active series gets a
  thicker stroke + faint fill; non-active ones dim to `opacity-0.3` (never hidden). Size default
  bumped to 420.
- `ScoreHeatmap.tsx` (NEW): models (rank-ordered) × benchmarks matrix, category sub-headers,
  `heatmapColor` cells, gold SOTA ring on column-best, dashed "no data" cells, clickable cells →
  `onOpenModel`.
- `BenchmarkBars.tsx` (NEW): per-benchmark horizontal bars grouped by category, one bar per model,
  `%` labels, dashed placeholder for missing, click → `onOpenModel`.
- `lib/palette.ts` (NEW): shared `MODEL_PALETTE` + `modelColor(i)`.
- `ModelComparison.tsx`: rewritten to **stacked full-width cards** (radar → by-category →
  heatmap → bars → specs table). Shared `activeId` hover drives both the radar and the
  category-bar dimming. Specs became a glass comparison **table** with "Leads in N" badges and
  clickable model-name headers. Added a 0-model empty state. Accepts `onOpenModel`.
- `App.tsx`: passes `onOpenModel={openModel}` to `<ModelComparison>`.

### 8.2 Replaced the SOTA star icon with an animated ring
- `src/index.css`: added `@keyframes sota-pulse` → `.sota-cell` (pulsing gold inset ring + soft
  glow) and `.sota-swatch` (static gold-ring chip for legends).
- `ScoreTable.tsx` & `ScoreHeatmap.tsx`: best-in-column cells use `.sota-cell` instead of an
  overlaid `Star`; removed the now-unused `Star` imports; legends use `.sota-swatch`.
- The number text is no longer obscured by an icon.

---

## 9. Open task: migrate Radix UI → Base UI  (NOT started — owner: next agent)

**Context:** shadcn has made **Base UI** (`@base-ui-components/react`) its official primitives
path. The current `src/components/ui/*` wrappers are all built on Radix. The maintainer wants to
move to Base UI.

**Important realities:**
- There is **no automated codemod**. This is a manual, file-by-file rewrite of each `ui/*.tsx`
  wrapper to wrap Base UI instead of Radix. Base UI's API is *close* to Radix (composable
  `Root`/`Trigger`/`Content` + `data-state` attributes) but **not a drop-in**: import paths, some
  prop names, and CSS-var hookups differ.
- shadcn can regenerate Base UI versions: `npx shadcn@latest add <component> --base-ui` (or set
  `baseUi: true` in `components.json`). That is the fastest starting point per primitive.
- **Breakage is localized to `src/components/ui/*`** — the consuming components
  (App, ScoreTable, ModelComparison, etc.) only use the wrapper component names/props, so most
  will keep working once the wrappers are rewritten.

### 9.1 Component mapping (current Radix deps → Base UI status)

| Current wrapper            | Radix dep                     | Base UI status / note                                  |
| -------------------------- | ----------------------------- | ------------------------------------------------------ |
| `ui/dialog.tsx` (→Sheet)   | `@radix-ui/react-dialog`      | ✅ Base UI has `Dialog`                                |
| `ui/popover.tsx`           | `@radix-ui/react-popover`     | ✅ Base UI has `Popover`                               |
| `ui/tooltip.tsx`           | `@radix-ui/react-tooltip`     | ✅ Base UI has `Tooltip`                               |
| `ui/tabs.tsx`              | `@radix-ui/react-tabs`        | ✅ Base UI has `Tabs`                                  |
| `ui/switch.tsx`            | `@radix-ui/react-switch`      | ✅ Base UI has `Switch`                                |
| `ui/separator.tsx`         | `@radix-ui/react-separator`   | ✅ Base UI has `Separator`                             |
| `ui/slot.tsx`              | `@radix-ui/react-slot`        | ✅ Base UI has `Slot`                                  |
| `ui/scroll-area.tsx`       | `@radix-ui/react-scroll-area` | ⚠️ **Drop it.** Base UI has no scroll-area primitive; and this project already avoids it (sticky columns need plain `overflow-x-auto`). Leave `scroll-area.tsx` unused or delete it. |
| `ui/toast.tsx` + `use-toast.ts` | `@radix-ui/react-toast`  | ⛔ **Blocker:** Base UI does **not** ship a Toast primitive yet (still on roadmap). Either (a) keep this one Radix piece until Base UI ships Toast, or (b) replace with a tiny custom toast. Decide before starting. |

### 9.2 Suggested execution order
1. Decide the Toast strategy (keep Radix Toast vs. custom). This gates a "100% Radix-free" goal.
2. Add `@base-ui-components/react`; regenerate the 1:1 primitives via shadcn `--base-ui` into a
   scratch dir, then port each into `src/components/ui/*` preserving the existing export names
   (`Card`, `Button`, `Dialog`/`Sheet`, `Popover`, `Tooltip`, `Tabs`, `Switch`, `Separator`,
   `Slot`, `Table`, `Badge`).
3. `ui/scroll-area.tsx`: remove it; ensure no import remains (grep).
4. `npm run build` after each primitive to catch prop/animation differences early.
5. Manually verify: Sheet open/close, popover (benchmark info), tooltip, tabs if used, toast
   notifications on model select, and **sticky column scroll** in ScoreTable + ScoreHeatmap.

---

## 10. Known gotchas / watch-outs

- **Radar dim**: non-active radar series stay at `opacity-0.3` (legible outline), never `opacity:0`.
- **Sticky columns + scroll**: plain `overflow-x-auto` only; never Radix `ScrollArea` (breaks
  `position: sticky`). Mirrored from `STICKY_BG` in ScoreTable.
- **Null scores**: always render as "no data" (dashed in heatmap, placeholder bar in bars, "—" in
  table). Non-vision models legitimately lack vision-benchmark scores.
- **Two Sheets**: Model Sheet and Benchmark Sheet are separate Radix `Dialog` roots in `App.tsx`;
  do not nest.
- **Build must stay green**: `npm run build` runs `tsc -b` (strict) then Vite. Unused imports fail
  under `noUnusedLocals`, so remove imports when you delete usages (e.g. `Star` was removed).

---

## 11. Quick validation checklist

- [ ] `npm run build` passes (tsc strict + vite).
- [ ] Table view: best-in-column cells show a pulsing gold ring (no star), legend shows gold swatch.
- [ ] Compare view: radar shows clean outlines; hovering a legend item highlights one model and
      dims others; heatmap ranks models top→bottom with category sub-headers and gold SOTA rings;
      clicking a heatmap/bar/spec cell opens the correct Model Sheet.
- [ ] Up to 6 models selectable; 0 models shows the empty state.
- [ ] (If doing §9) After migration: every UI primitive still works; no Radix `scroll-area`
      import remains; toast still fires on model select.
