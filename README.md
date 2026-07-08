# AI Benchmark Aggregator

A single-page **AI model benchmark comparison dashboard**. It ranks models across ~17 benchmarks
organized into 8 capability categories, and lets you compare several models side by side with a
set of glassmorphic charts.

> **Status:** Demo / synthetic data only. There is **no backend** — all data lives in `src/data/*`.
> This is a client-only SPA meant for local exploration and as a reference front-end.

## Features

- **Leaderboard table** — models ranked and grouped by category, heatmap-colored cells, sortable,
  with per-benchmark detail popovers and a "best in column" footer.
- **Heatmap** — compact color-graded view of every model × benchmark score.
- **Compare view** — select up to 6 models and see them side by side as five stacked glass cards:
  1. Capability **radar** chart (SVG, hover-to-highlight)
  2. **By-category** averaged bars
  3. **Score heatmap** matrix
  4. **Per-benchmark** grouped bars
  5. **Specs** comparison table with "leads in N" badges
- **SOTA indicator** — best-in-column cells pulse with an animated gold ring.

## Tech stack

- [Vite 5](https://vitejs.dev/) + [React 18](https://react.dev/) + [TypeScript](https://www.typescriptlang.org/) (strict)
- [Tailwind CSS 3](https://tailwindcss.com/) + `tailwind-merge` + `clsx`
- [Radix UI](https://www.radix-ui.com/) primitives in `src/components/ui/*`
- [lucide-react](https://lucide.dev/) icons
- Hand-rolled SVG charts (no charting library)

The `@/*` path alias (`@/...` → `./src/...`) is configured in both `vite.config.ts` and
`tsconfig.json`.

## Quick start

```bash
npm install
npm run dev        # start the Vite dev server (prints a Local: URL)
npm run build      # type-check (tsc -b, strict) + production build (vite build)
npm run preview    # preview the production build
```

`npm run build` runs `tsc -b && vite build` and must stay green.

## Project structure

```
src/
  App.tsx              # all view state, routing between views, two Sheets, Toaster
  main.tsx             # React root
  index.css            # Tailwind + glass utilities + SOTA pulse animation
  types.ts             # Model, Benchmark, BenchmarkCategory, CATEGORIES, CATEGORY_LABELS
  data/
    models.ts          # model catalog
    benchmarks.ts      # 17 benchmarks (id, name, category, scaleMax, higherIsBetter, ...)
    scores.ts          # getValue(modelId, benchmarkId) — the single score accessor
  lib/
    aggregate.ts       # ranking + averages
    color.ts           # heatmap color scale
    categories.ts      # category colors / tints
    palette.ts         # shared per-model color palette
    utils.ts           # cn()
  components/
    ScoreTable.tsx     # leaderboard table
    ScoreHeatmap.tsx   # compare heatmap matrix
    BenchmarkBars.tsx  # per-benchmark grouped bars
    RadarChart.tsx     # SVG radar chart
    ModelComparison.tsx# compare layout
    ModelDetail.tsx    # model Sheet content
    BenchmarkCard.tsx  # benchmark Sheet content
    CategoryLeaders.tsx# strip of per-category leaders
    Filters.tsx, Header.tsx, GlossaryDialog.tsx
    ui/                # Radix-based UI primitives
```

## Notes for developers

- `getValue(modelId, benchmarkId)` (in `src/data/scores.ts`) is the **only** way to read a score.
  It returns `number | null`; a `null` means the model has no score for that benchmark (e.g. a
  non-vision model on a vision benchmark). All views render null as "no data".
- See [`handoff.md`](./handoff.md) for full orientation, conventions, and the pending
  Radix → Base UI migration task.

## License

[MIT](./LICENSE)
