# Frontend scale and browser-evidence protocol

**Status:** Blocked pending P0-08 browser/support-matrix decision  
**Local receipt:** 2026-07-14 — unit/JSDOM checks available; isolated browser runner could not reach the local Vite server and therefore produced no rendered-page evidence.

## Scope

This protocol applies to the Demo/unavailable frontend first. It does not
authorize Official mode, a v2 artifact, or an external source. Large test data
must be generated in test-only helpers and must never be imported from
`src/data/official` or packaged as a release input.

## Decisions required before a budget is set

| Item | Required value |
| --- | --- |
| Supported browsers/versions and viewport classes | UNDECIDED |
| Assistive-technology combinations and manual test owner | UNDECIDED |
| Representative device/CPU/network baseline | UNDECIDED |
| Dataset size and score sparsity profile | UNDECIDED |
| Performance thresholds and regression action | UNDECIDED |
| Browser-test runner/network topology and CI retention | UNDECIDED |

Do not invent millisecond budgets from a developer laptop or JSDOM timing. A
budget must record device, browser, dataset generator seed, visible row/column
counts, score density, commit, and repeat-run distribution.

## Required automated browser checks

- keyboard navigation through source status, filters, score table, comparison,
  model/benchmark sheets, and provenance/source-manifest disclosures;
- Escape/focus restoration and independent Sheet roots;
- missing-value, coverage/rank, unavailable-source, and root-error-boundary
  states with accessible names/messages;
- narrow viewport, 200% zoom, reduced motion, and sticky-column behavior;
- source selection clearing data-dependent state and restoring source-control
  focus;
- console/network error receipt and a screenshot/trace policy that excludes
  protected values and credentials.

## Required manual accessibility protocol

Record browser/OS/AT versions and a dated tester receipt for keyboard-only,
screen-reader, high-zoom, contrast, and reduced-motion passes. JSDOM and a
single automated Chromium run are useful regressions but do not replace this
manual evidence.

## Current stop condition

No rendered browser matrix is recorded. The local tool attempt was unable to
connect to `127.0.0.1` because its browser environment denies private/internal
addresses. Do not describe UI-08 as complete until P0-08 selects a CI/browser
environment that can reach a controlled preview or an approved local bridge.
