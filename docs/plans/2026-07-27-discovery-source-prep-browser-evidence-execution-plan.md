# Discovery Engine, Source-Certification Prep, and Browser Evidence — Execution Plan

- **Date:** 2026-07-27
- **Status:** In progress
- **Origin:** Authored in a Qoder session on 2026-07-27 (session `task-56f44830662d4bb197da`). The session hit its usage limit mid-execution with the plan held only in memory; it is persisted here verbatim (see *Original plan* below) plus a status tracker so execution resumes deterministically.
- **Parent documents:** [Continuous-discovery implementation plan](./2026-07-15-continuous-benchmark-discovery-recheck-and-alerting-implementation-plan.md) (DSC-01–03), [Production-launch plan](./2026-07-14-production-launch-architecture-and-release-plan.md) (UI-07/UI-08), [Initial source certification preparation runbook](../runbooks/initial-source-certification-preparation.md) (BigCodeBench / SWE-bench Verified).
- **Scope guard:** This plan deliberately excludes the GitHub Actions billing blocker (external account action) and all Phase-0 ownership decisions (charter stop-states). Nothing here requires provider accounts, live fetches, source certification, or ownership sign-off.

## Resumption state (as of 2026-07-27)

The originating session ended mid-A1. Concrete state at handoff:

- [x] Plan authored (this document) — was in-memory only in the Qoder session; now persisted.
- [x] A1 code study complete: `ledger/app/db/models.py`, `ledger/app/db/operational_repositories.py`, `ledger/app/schemas/operations_contracts.py`, `ledger/app/schemas/coverage_contracts.py`, `ledger/app/runtime/dependencies.py`, `ledger/app/cli.py`, `ledger/tests/conftest.py`.
- [x] `ledger/app/scheduling/__init__.py` written.
- [x] `ledger/app/scheduling/slots.py` written — deterministic UTC slot calculus (`ScheduleSlot`, `slot_for_ordinal`, `slot_at`, `TWICE_DAILY_CADENCE_SECONDS`), cycle IDs via `derive_cycle_id` from `app.schemas.operations_contracts`.
- [ ] A1 remainder: scheduling unit tests, `ledger/app/discovery/` package (target-manifest loader + discovery controller), `discovery` CLI sub-app, discovery fixture tests.
- [ ] A2, A3, B1–B4, C1–C3, final gates — not started.

## Status tracker

| #  | Task | Status | Notes |
|----|------|--------|-------|
| A1 | DSC-01: scheduling + discovery packages, CLI, tests | 🔶 In progress | `scheduling/` package done; `discovery/` package, CLI sub-app, and tests remain |
| A2 | DSC-02: fixture-only discovery connectors | ⬜ Pending | |
| A3 | DSC-03: candidate lifecycle + batch review + reports | ⬜ Pending | |
| B1 | `parquet_cell_v1` evidence resolver + pinned `pyarrow` | ⬜ Pending | |
| B2 | BigCodeBench Parquet adapter + fixtures | ⬜ Pending | |
| B3 | SWE-bench Verified full-artifact hardening | ⬜ Pending | |
| B4 | Draft `source-contract-v2` examples + runbook update | ⬜ Pending | |
| C1 | UI-07 scale fixtures + regression tests | ⬜ Pending | |
| C2 | Playwright UI-08 harness + specs | ⬜ Pending | |
| C3 | Manual AT protocol template in runbook | ⬜ Pending | |
| —  | Full ledger + frontend gates | ⬜ Pending | |

## Execution log (append-only)

- 2026-07-27 — Plan persisted to the repository from the Qoder session transcript; A1 resumed.

---

## Original plan (verbatim)

# Discovery Engine, Source-Certification Prep, and Browser Evidence

## Summary

Three parallel, authority-free workstreams that advance the launch plan without CI/CD work, provider accounts, live fetches, source certification, or ownership decisions:

- **A — Fixture-only discovery engine** (`DSC-01` → `DSC-02` → `DSC-03` from the continuous-discovery plan)
- **B — First-source certification engineering prep** (Parquet evidence locator + BigCodeBench adapter, SWE-bench Verified full-artifact hardening, draft `source-contract-v2` fixtures)
- **C — UI-07 scale budget + UI-08 real-browser harness** (Playwright automation + manual AT protocol template)

All prerequisites are verified present: `coverage_contracts.py` (COV-02), discovery/candidate tables in `models.py` + `operational_repositories.py` (DATA-09), and the live-disabled composition root in `ledger/app/runtime/dependencies.py` (CFG-01). The workstreams touch disjoint file surfaces and can run in parallel.

## Workstream A — Fixture-only discovery engine

### A1. DSC-01: due planner and discovery controller
- New `ledger/app/scheduling/` package: deterministic twice-daily UTC slot calculus (slot IDs consistent with `scheduled-cycle-v1` semantics in `continuous_contracts.py`), DST-independent, reusable later by RCK-01.
- New `ledger/app/discovery/` package:
  - Target-manifest loader validating `discovery-target-v1` / `coverage-universe-v1` payloads through existing `coverage_contracts.py` validators (reject unknown IDs, duplicate targets, missing denominators).
  - Discovery controller: for each cycle, every target gets exactly one terminal disposition (`due`, `not_due`, `blocked` + stable reason code); complete denominator accounting (expected/due/checked/not-due/blocked/failed/unchanged/changed/review-required counts must balance).
  - Persistence through the existing DATA-09 operational repositories only; forward-only, append-only; **zero** `SourceSnapshot`/`ResultClaim`/source-decision/certification writes.
- CLI (`ledger/app/cli.py`): new `discovery` sub-app — `discovery plan`, `discovery run --fixture-root …`, `discovery report --format json|markdown`. Constructed only via the inert composition root; transport stays disabled; dry-run is side-effect free.
- Tests: two deterministic cycles over fixtures produce exactly one run each; re-running same connector/revision/slot creates no duplicate observation/candidate; blocked/uncovered targets are explicit, never silently omitted.

### A2. DSC-02: bounded fixture-only connectors
- Connector family under `ledger/app/discovery/connectors/`: Git repository release/tree/commit metadata, Hugging Face dataset metadata/revisions, official JSON/file manifests, sitemap/feed/embedded structured-data locators, manually governed roots.
- Each connector: consumes fixture bytes through the safe-fetch plan interface (no adapter-owned HTTP; live transport remains fail-closed), enforces host/size/request budgets, emits stable content fingerprints and revision-change detection, outputs **candidates only** (`discovery-candidate-v1`).
- Fixture tests per connector in `ledger/tests/` with new fixture files under `ledger/tests/fixtures/discovery/`.

### A3. DSC-03: candidate lifecycle and batch review
- Candidate deduplication (stable fingerprint + revision), lifecycle decisions, contract-draft generation (emits a draft `source-contract-v2` skeleton for an operator, never a certified contract), terms/correction evidence references.
- Batch review import: one reviewed manifest, itemized append-only decisions per candidate — no bulk implicit certification path exists.
- Coverage reporting: integrate candidate/disposition counts into `ledger/app/reporting/` alongside the existing coverage census; stable JSON/Markdown output.

## Workstream B — First-source certification engineering prep (fixture-first)

Scope is strictly parser/locator/contract engineering: no network fetch, no source revision certification, no claim against the protected ledger. Every test runs against checked-in fixtures on disposable databases.

### B1. Typed Parquet evidence locator (`parquet_cell_v1`)
- Add `pyarrow` (pinned) to `ledger/pyproject.toml`; regenerate `uv.lock`.
- Implement a Parquet evidence resolver honoring the existing `parquet_cell_v1` shape already declared in `source_contracts.py` (row-group/row/column binding). Re-resolution must return the identical raw lexeme from the immutable snapshot bytes.
- Raw-lexeme policy for typed Parquet values: define deterministic lexical rendering (via existing `json_lexemes.py` rules) so float/decimal/string cells preserve source values exactly; non-finite and nonnumeric score lexemes are rejected at admission, never coerced.
- Flip `parquetLocatorSupport` binding status in the contract implementation-binding path once the resolver passes its fixtures.

### B2. BigCodeBench Parquet adapter
- New `ledger/app/ingestion/adapters/bigcodebench_parquet.py` + small checked-in Parquet fixture (generated deterministically by a test helper, a few KB).
- Rules from the certification-prep runbook: `complete` and `instruct` are **distinct source-reported metric dimensions** (never averaged or row-order-selected); model identity preserved raw with `model_entity_id` null + `needs_review` when uncertain; complete-artifact accounting (every row accounted, zero-row collapse and duplicate locators quarantine the batch).
- Fixture tests: lexical raw preservation, duplicate-key rejection, evidence re-resolution, drift/malformed-file failure, idempotent re-ingestion.

### B3. SWE-bench Verified full-artifact hardening
- Extend the existing `swe_bench_adapter.py` for the commit-pinned full `data/leaderboards.json` shape: enforce the 8 MiB max-byte bound, select **exactly** the Verified category (Community/preview mixing fails closed), preserve `resolved` as raw lexical value.
- Evidence: `json_path_v1` for direct JSON and `json_script_path_v1` (exact script id/type/category assertion/record path/field map) for the historical embedded shape; substitution of any locator component fails.
- Model entries are evaluated systems: keep raw system strings, no forced base-model mapping; ambiguous identities go to the review queue.
- Synthetic schema-complete fixture (small) + tests mirroring B2's acceptance list.

### B4. Draft source contracts and runbook update
- Add draft (explicitly `uncertified`) `source-contract-v2` example fixtures for both candidates under `docs/contracts/examples/`, validating through `source_contracts.py` — revision-pinned URLs, byte bounds, dimensions, locator families from the prep runbook.
- Update `docs/runbooks/initial-source-certification-preparation.md`: record that the Parquet locator/adapter gap is closed, terms/owner decisions remain the sole outstanding blockers, and fixtures prove parser behavior only (per the runbook's own boundary wording).

## Workstream C — UI-07 scale budget and UI-08 browser evidence

### C1. UI-07: documented scale budget + regression fixtures
- Test-only large dataset builders (e.g., 500 models × 42 benchmarks) in a `src/lib` test helper; never importable by runtime code paths (enforce via a test asserting `scores.ts` provenance).
- Document the baseline budget (dataset size, target interaction timings) in a short doc section; add automated regression tests: virtualized `ScoreTable` renders bounded DOM rows, sort/filter over the large fixture stays under budget, keyboard focus and row/column context survive filtering and virtualization scroll, sticky-column behavior intact.

### C2. UI-08: Playwright harness (automated browser evidence)
- Add `@playwright/test` as devDependency, `playwright.config.ts` targeting Chromium/Firefox/WebKit against `vite preview` of a production build; new `npm run test:e2e`. Local execution only (no CI wiring per current scope); Demo data only, Official stays unavailable.
- Spec coverage mapped to the UI-08 matrix: keyboard-only navigation; Escape/focus restoration; Model and Benchmark sheets as independent roots; provenance/data-source status control (switching clears data-dependent filters/sort/comparison/sheet state and returns focus to the source control); no-data rendering; error-boundary recovery without hidden Demo fallback; reduced-motion; 200%/400% zoom; narrow viewport; baseline visual regression screenshots.
- Record artifact identity (unavailable-artifact digest) in the test run output so receipts are reusable for future Official pre-release checks.

### C3. UI-08: manual assistive-technology protocol template
- Add `docs/runbooks/frontend-scale-and-browser-evidence.md` updates: a dated manual NVDA/VoiceOver/TalkBack protocol checklist with receipt table (browser/OS/AT versions, artifact digest, pass/fail per scenario). Execution of manual receipts remains explicitly gated on the P0-08 owner decision — the template and automated harness land now.

## Suggested sequence

1. **A1**, **B1**, **C1** in parallel (disjoint surfaces: new ledger packages / ingestion+schemas / frontend tests).
2. **A2** + **B2/B3** in parallel; **C2** after C1 fixtures exist.
3. **A3**, **B4**, **C3** as closing slices; then full gates and an append-only receipt per slice.

## Test plan

- Ledger: `cd ledger && pytest -q` green, including new discovery/scheduling/Parquet/SWE suites; re-run idempotency checks; protected SQLite fingerprint unchanged (read-only).
- Frontend: `npm run typecheck && npm test && npm run build && npm run verify:official-artifact` green; `npm run test:e2e` green locally across three engines.
- Static: one Alembic head unchanged unless a forward-only migration is genuinely required by DSC persistence gaps (expected: none — DATA-09 tables suffice); JSON/JSONL/contract examples validate.

## Containment guardrails (apply to every slice)

- No live network fetch; transport stays fail-closed; connectors/adapters consume fixtures only.
- No source certification, claim write to a claim-bearing ledger, publication, release artifact, or Official-mode change; discovery output is candidates/receipts only.
- Append-only everywhere; no downgrade/delete recovery; no edits to historical plan receipts — new work gets new append-only ledger entries.
- Raw source values preserved exactly; nothing coerced to become admissible.

## Assumptions

- `pyarrow` is an acceptable pinned ledger dependency for Parquet reading (standard, offline-capable).
- `@playwright/test` with locally installed browsers is acceptable for the frontend harness; CI wiring is explicitly out of scope for now.
- DATA-09's existing discovery/candidate tables cover DSC persistence; if a real gap appears, it is closed with a forward-only Alembic revision, never a table rewrite.
- Manual AT receipts and any terms/owner approvals stay blocked per the charter; this plan does not simulate them.