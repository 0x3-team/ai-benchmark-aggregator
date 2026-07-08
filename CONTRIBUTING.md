# Contributing

Thanks for your interest in improving the AI Benchmark Aggregator. This is a small, client-only
SPA — no backend, no CI yet. Keep changes lean and the build green.

## Running locally

```bash
npm install
npm run dev      # dev server
npm run build    # tsc -b (strict) + vite build — MUST stay green
npm run typecheck# tsc --noEmit, fastest correctness check
```

## Before opening a PR

- `npm run build` must pass. The project uses TypeScript **strict** mode with
  `noUnusedLocals` / `noUnusedParameters`, so remove unused imports when you delete usages.
- For orientation on architecture and conventions, read [`handoff.md`](./handoff.md) first.

## Conventions

- Merge conditional classes with `cn(...)` (from `src/lib/utils.ts`) — never raw conditional
  template strings.
- Use the glass utility classes (`glass-strong`, `glass-inset` in `src/index.css`) and the `Card`
  primitive for surfaces.
- Tables with sticky columns use plain `overflow-x-auto` + `position: sticky; left: 0`. Do **not**
  use the Radix `ScrollArea` wrapper for these — it breaks `position: sticky`.
- Handle null scores consistently (dashed in heatmap, placeholder bar, "—" in the table).
- Use the shared `modelColor(i)` palette so radar, category bars, and benchmark bars stay
  color-consistent across the compare view.

## Scope

This repo is prepared for open-sourcing but is **not yet published**. Please do not add a public
remote or push without explicit confirmation.
