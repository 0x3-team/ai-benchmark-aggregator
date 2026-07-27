# EvilCharts vendored source

These 14 files are vendored verbatim from [github.com/legions-developer/evilcharts](https://github.com/legions-developer/evilcharts).

- Upstream commit SHA: `d4c753c6940bb70fef1c6f08ed3fd1fbdbd6ddbd`
- Vendored on: 2026-07-24
- Upstream docs: [https://evilcharts.com/docs/](https://evilcharts.com/docs/)

These files are READ-ONLY. Do not edit their logic. All app-specific behavior
lives in adapters (`src/components/charts/`) and builders (`src/lib/chartData.ts`).

The only modification applied: `"use client";` directives were removed (this is
a Vite SPA, not Next.js). The upstream `@/registry/*` import paths resolve via a
tsconfig/vite path alias pointing to this directory.
