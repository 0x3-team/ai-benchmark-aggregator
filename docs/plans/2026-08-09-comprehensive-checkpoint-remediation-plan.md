# AI Benchmark Platform Comprehensive Checkpoint Remediation Plan

## Checkpoint metadata

- Repository: `0x3-team/ai-benchmark-aggregator`
- Branch/baseline: `main`, `5eb3b35e35867e6b56837d7fc9b67e120c423b45`; `origin/main` is `f0115929898dc4ec7c65882db7db96b0172c0143`; local is ahead 3.
- Date: 2026-08-09
- Planning used the highest review tier because the checkpoint crossed frontend, ledger, security, release, immutable-data, and production-risk surfaces.
- Existing in-progress adapter and scale-test work must be preserved in place. Never reset, stash, clean, or overwrite unrelated work.
- Planning only: this file is the sole planning-phase edit. Implementation has not started under this plan.

## Outcome and guardrails

Target outcome: a locally validated Demo release candidate whose synthetic nature is unmistakable, whose frontend calculations and no-data behavior are truthful, whose ledger CLI starts cleanly and remains contained, and whose static Cloudflare artifact has safe baseline routing/metadata. This does **not** authorize an Official release or a production deployment.

Guardrails:

- Keep the governed Official artifact unavailable and data-free. Do not ingest sources, capture claims, publish/export Official data, certify revisions, or relax REL-05.
- Do not mutate Cloudflare, GitHub, DNS, databases, paid services, branches, commits, remotes, or provider settings.
- Do not run destructive filesystem or database operations. New tests use temporary directories/databases only.
- Preserve raw source lexemes and append-only ledger semantics. No coercion, fallback data, synthetic-to-Official promotion, or historical-row rewrite.
- Keep implementation, debugging, integration, validation, independent acceptance, and browser evidence as separate owned phases.
- A worker owns only its files below. Cross-lane changes return to the coordinator for reassignment; workers never opportunistically refactor.

## Source-of-truth contract

- Intent: show synthetic Demo comparisons honestly while Official remains unavailable; store only immutable source-reported claims in the CLI ledger.
- Current behavior: frontend tests report 66 passing but one suite collects 3 instead of 5; typecheck/build fail; clean ledger CLI import fails; Demo metadata and calculations violate their contracts; provider/browser checks are partly blocked.
- Expected outcome: all local gates pass without weakening tests, Demo is persistently labeled synthetic, missing data stays missing, full-cohort claims stay global, and no dormant Official/provider path is activated.
- Truth owners: `AGENTS.md`; immutable `DatasetProvider`/`getValue`; the tracked unavailable Official artifact and release runbooks; ledger schema/admission/Alembic contracts; later Cloudflare/GitHub receipts for provider state.
- Contract boundary: local source, tests, static assets, and documentation only.
- Displaced paths: eager ingestion barrel import; unchecked Demo casts; subset-derived SOTA; missing-as-zero; unstable virtual rows; abstract registered adapter; SPA soft-404 fallback; unsafe contributor instructions.
- Cutover: merge local workstreams only after their targeted gates and the integrated suite pass. Live cutover is `none` in this checkpoint.
- Acceptance evidence: exact command exits, test counts, clean-archive build, static artifact inspection, later in-app browser evidence, and later authenticated provider receipts kept as separate lanes.
- Kill criteria: any Official data appears, a provider/database is mutated, user work is lost, raw values are coerced, a failing assertion is weakened, or a worker cannot prove its contract from fixtures.
- Forbidden moves: deleting the BigCodeBench work to make tests green; silently defaulting invalid metrics to zero; clamping source values; substituting an outside browser; claiming deployed/live/visual verification from local tests.

## Orchestration decision

- Mode: full implementation handoff using staged, disjoint Luna High workers.
- Independent surfaces: ledger CLI, Parquet adapter, frontend build fixtures, Demo schema, calculation/state semantics, accessibility, static Cloudflare/repository hygiene, dependency integrity.
- Worker count: eight bounded lanes plus one Sol Max acceptance review. Parallelize only Phase 1; dependency order below is mandatory.
- Browser lane: required after UI changes, but currently blocked because the Codex in-app browser reports `Browser is not available: iab`. Do not substitute Chrome/Comet/Safari.
- Reconsider trigger: unexpected file overlap, a new migration, a source-governance decision, provider access, or a test exposing a different truth contract.

## Frozen baseline

- Ledger: full local suite passed `1096` with `11` skips. Clean CLI startup still fails from a circular import masked by `tests/conftest.py`.
- Frontend: `npm test` passed 13 files / 66 tests; targeted scale suite collected only 3 intended tests. `npm run typecheck` and `npm run build` fail at `src/lib/scaleFixtures.ts:68-69`.
- Official containment verifier passed 5/5. Production npm graph has zero known advisories; the full dev graph has 7 advisories (1 critical, 4 high, 2 moderate). Python audit found a setuptools issue and a pyarrow advisory explicitly marked not applicable to Python bindings.
- Live Demo hosts return 200 and matching HTML, but unknown paths/assets are soft 200s, robots/canonical policy is incomplete, and security headers are incomplete. Cloudflare project/account access is wrong or unavailable, so deploy identity/config/rollback remain unverified.
- Latest remote Verify run failed before steps because of an account payment/spending block. `main` is unprotected on the current plan; all current CODEOWNERS entries are invalid live.
- Managed Codex Security Deep Scan could not proceed because the required managed filesystem profile is unavailable. The independent static audit found no critical/high security issue.

## Dependency order

1. Phase 1A runs W1, W2, W3, W4, and W7 in parallel because ownership is disjoint.
2. W2 registers BigCodeBench only after its own fixture/adversarial gate; otherwise it preserves the file and removes only the premature import/map entry.
3. Phase 1B runs W5 after W3 and W4; W6 runs after W5 so UI semantics are tested against final calculation/state behavior.
4. Run the integrated local gate. Only then run W8 dependency/lock work in isolation.
5. Rerun the full integrated and clean-archive gates, then request independent Sol Max acceptance.

## Immediate Luna High workstreams

### W1 — Ledger CLI and containment boundary

- Owns: `ledger/app/ingestion/__init__.py`, `ledger/app/cli.py`, `ledger/app/db/migrate.py`, new `ledger/tests/test_cli_import_boundary.py`, and narrowly relevant CLI/migration tests only.
- Remove the eager import cycle without moving domain authority into a new barrel. Add a fresh-process `benchmark-ledger --help`/isolated-import regression.
- Refuse non-dry `ingest` before `init_db`; map expected `SafeFetchError` to a stable redacted exit. Prove a missing DB stays absent on refusal.
- Make documented fresh SQLite initialization create only its explicitly selected missing parent, after scheme/path validation; never create parents for PostgreSQL or an existing/nonempty target.

### W2 — BigCodeBench Parquet adapter, fixture-first

- Owns: protected `ledger/app/ingestion/adapters/bigcodebench_parquet.py`, protected `ledger/app/ingestion/adapters/__init__.py`, and new `ledger/tests/test_bigcodebench_parquet_adapter.py`.
- Default decision: finish `extract_claims` with deterministic in-memory Parquet fixtures; preserve model/metric/raw score fields and typed `parquet_cell_v1` evidence. Fail the whole batch on malformed/zero-row data, missing declared columns, duplicate model+dimension identity, non-finite/nonnumeric values, or incomplete accounting.
- Required tests: exact row-group/index re-resolution, every declared dimension once, raw string lexemes, duplicate/zero/malformed cases, replay identity, and registry-wide “no abstract adapter” construction.
- Registration is the last step. If exact raw/evidence behavior cannot be proved without source invention, keep the implementation file intact but unregister it; do not delete it, fetch the live source, certify it, or alter `official_sources.yaml`.

### W3 — Frontend build and false-green scale suite

- Owns only the four protected scale files under `src/lib/` and `src/components/ScoreTable.scale.test.tsx`.
- Build modalities through a mutable local `Modality[]` or immutable construction, preserving the readonly public type.
- Close the sort test before the nested suite; retain ascending assertions in the sort test. Require exactly 5 collected scale cases and keep all focus/virtualization assertions meaningful.

### W4 — Demo catalog and metric-domain contract

- Owns: `src/types.ts`, `src/data/benchmarks.json`, `src/data/benchmarks.ts`, new `src/data/demoCatalog.test.ts`, and any new data-boundary parser module under `src/data/`.
- Replace unchecked casts with a fail-closed tracked-Demo parser. Repair all required metadata and the BenchLM legacy shape so 26 headers equal 26 body columns; never invent an Official claim.
- Add explicit normalization metadata: bounded domain with min/max or `raw_only`. Signed/rating metrics and any uncertain domain remain raw-only; preserve all raw table scores. A contract test must enumerate every shipped benchmark and reject an out-of-domain value presented as normalized.

### W5 — Frontend calculation, state, and virtualization truth

- Depends on W3/W4. Owns: `src/App.tsx`, `src/components/ScoreTable.tsx`, `src/components/ModelDetail.tsx`, `src/components/BenchmarkCard.tsx`, `src/lib/chartData.ts`, `src/lib/aggregate.ts`, `src/data/dataset.tsx`, owned chart adapters, and their focused tests.
- Pass separate visible and full-cohort model sets. Compute SOTA, “Best,” leaders, field averages, and detail comparisons from the immutable full cohort; add filter-out-the-leader regressions.
- Make empty aggregates nullable and render no-data, never `0%`. Centralize direction/domain-aware normalization; raw-only/invalid normalized points are omitted while raw table values remain visible.
- Clone/freeze every score snapshot so retained caller references cannot change `getValue`.
- On filter/sort/source/list identity change, reset DOM and state scroll and clamp indices. Enforce the declared fixed row height/truncation, preserve an accessible full name, expose total/index and `aria-sort`, and test deep-scroll then filter/sort/source switch.
- Audit source switching against every data-dependent state: selection, comparison, sheet, sort, filters, hover/highlight, and focus. Add a regression for each cleared state.

### W6 — Truth labeling and high-value accessibility

- Depends on W5. Owns: `src/data/dataMode.ts`, `src/components/Header.tsx`, `Filters.tsx`, `ScoreHeatmap.tsx`, `ModelComparison.tsx`, `src/components/ui/badge.tsx`, `toast.tsx`, adapter-level chart legends, `src/index.css`, and focused tests.
- Persistently show `Demo (synthetic)` anywhere populated Demo data is visible; Official unavailability must explicitly say Demo remains visible. Remove the contradictory “no synthetic data” note.
- Add durable search labels, semantic toggle groups/`aria-pressed`, polite result status, comparison-limit disabled semantics, accessible toast close, and presentational badges by default.
- Replace pointer-only chart legend controls at the adapter layer. Reduce the heatmap tab sequence to row/detail and real evidence actions unless a tested arrow-key grid is implemented.
- Make the header wrap/stack at 390px and 200% zoom; replace low-contrast opacity-on-muted text with verified solid tokens. Do not edit vendored EvilCharts.

### W7 — Static Pages and repository truth

- Owns: `public/`, `index.html`, `CONTRIBUTING.md`, `.github/ISSUE_TEMPLATE/*`, PR-template files, new `scripts/verify-pages-static-node-tests.mjs`, and `docs/audits/2026-08-09-comprehensive-checkpoint-audit.md`.
- Add a real `404.html`, non-HTML `robots.txt`, and custom-domain canonical URL. Add conservative `_headers`: nosniff, strict referrer, clickjacking denial, minimal Permissions-Policy, and report-only CSP. Do not add HSTS or enforcing CSP without domain/browser proof; do not add a Worker.
- Add static tests for copied assets, valid robots, canonical, 404, and header directives.
- Rewrite contributor instructions around containment/read-only validation; remove ingest/export/Official-switch instructions and unverified branch-protection claims.
- Fix issue-form `description` keys; replace the invalid YAML PR form with Markdown. Do not guess CODEOWNERS identities—record the live owner/setup blocker in the audit.
- The audit report must list findings by severity, fixed/deferred/blocked state, positive controls, exact evidence, and “good next features.”

### W8 — Dependency and lock integrity, serialized

- Runs only after the integrated gate. Owns: `package.json`, `package-lock.json`, `.pre-commit-config.yaml`, `ledger/pyproject.toml`, `ledger/uv.lock`, `ledger/requirements-ci.lock`, `ledger/README.md`, `ledger/.env.example`, `.github/workflows/verify.yml`, and dependency-specific tests/docs.
- Use current official Vite/Vitest/PostCSS release notes because Context7 is unavailable. Upgrade in the smallest compatible steps; major Vite/Vitest changes get separate commits/receipts and may be deferred if behavior changes cannot be bounded.
- Select one hash-bearing Python lock authority, use it frozen in CI/local docs, add drift/tampered-hash tests, remove unauthorized credential placeholders, and make PostgreSQL proof fail rather than silently skip in CI.
- Pin pre-commit hooks to reviewed commit SHAs. Do not “fix” the Python-only-not-affected pyarrow advisory by forcing an incompatible upgrade.

## Exact verification

Run from repo root unless noted; retain exits and test counts:

```sh
git status --short --branch
git diff --check
cd ledger && PYTHONPATH=. .venv/bin/benchmark-ledger --help
cd ledger && .venv/bin/pytest -q tests/test_cli_import_boundary.py tests/test_cli_containment.py tests/test_bigcodebench_parquet_adapter.py
cd ledger && .venv/bin/pytest -q
npm test -- src/components/ScoreTable.scale.test.tsx
npm run verify:official-artifact
npm run typecheck
npm test
npm run build
node --test scripts/verify-pages-static-node-tests.mjs
npm audit --omit=dev --json
npm audit --json
uvx pip-audit -r ledger/requirements-ci.lock --no-deps --disable-pip
git diff --check
```

- Scale test must collect 5 cases. Ledger must not fall below 1096 tests or exceed 11 skips without a reviewed explanation. Official verifier stays 5/5 and unavailable/data-free.
- Clean archive gate: extract `git archive HEAD` into `mktemp -d`, run `npm ci`, Official verification, typecheck, tests, build, and the static Pages test; remove only that explicit temp directory on exit.
- Once the in-app browser is available, check the local build at 390/768/1440px and 200% zoom: source truth, filter/SOTA semantics, deep-scroll resets, compare limit, keyboard-only flow, sheets, no overlap/overflow, console errors, and responsive header. Until then visual acceptance is blocked, not passed.
- No live curl result can prove the new artifact until an authorized deployment exists. After provider access, separately verify root/asset 200, unknown route/asset 404, robots plain text, canonical, headers, pages.dev noindex/redirect, deploy-to-SHA identity, and rollback.

## Acceptance criteria

- Clean CLI help works in a fresh process; contained ingest creates no DB and emits no sensitive error detail.
- BigCodeBench is either fully fixture-proven and concrete or safely unregistered with all user work preserved.
- Typecheck/build pass; the scale suite collects all intended cases; no assertion was weakened.
- Demo is always called synthetic; catalog parsing is fail-closed; header/body parity is exact; raw-only/out-of-domain and missing values never become normalized zero.
- Global labels use the full cohort; score snapshots resist retained-reference mutation; source switching clears all dependent state; virtual rows reset and maintain their declared geometry/semantics.
- Static Pages files and repository templates validate locally. No deployment, Official publication, source ingestion, or provider mutation occurred.
- Independent engineering acceptance reviews the actual diff and command receipts. Do not claim full UI acceptance until browser evidence exists, or production readiness until Cloudflare/GitHub gates are closed.

## Deferred/manual backlog

1. **Governed Official launch:** assign release/source/legal/telemetry/signer owners; certify a permitted source/revision/dimensions; rehearse export, withdrawal, and REL-05. This is a product/governance decision, not this checkpoint.
2. **Cloudflare:** obtain the correct account/project; prove Git mode/branch, deployment history, DNS, preview access, WAF/cache/analytics, host-specific pages.dev redirect/noindex, HSTS readiness, monitoring, and real rollback. Never deploy from the currently wrong account.
3. **GitHub:** clear the billing/spending block; rerun all Verify jobs; supply valid write-access users/teams; clear CODEOWNERS errors; enable required checks/reviews on a plan that supports protection.
4. **Security tooling:** provision the managed filesystem profile and rerun/seal Codex Security Deep Scan. Re-run dependency/digest advisory checks with network access.
5. **Ledger security migrations:** in separate forward-only slices, constrain ingestion-role updates to one-time finalization; bind worker timestamps to trusted commit time; harden migration backup, discovery fixtures, and restore paths with descriptor-relative no-follow operations. Require SQLite and PostgreSQL adversarial tests and disposable-copy migration receipts.
6. **Ledger scale:** cache one immutable evidence resolver per snapshot; preload identity maps/fingerprints; page/bulk-load reports and review queues; bulk registry seeding; make local orphan inventory linear. Add statement/decode/read counters, 10k-claim budgets, and RSS measurements before optimization acceptance.
7. **Registry/utility governance:** reject conflicting duplicate model IDs; retire or redesign direct-network helpers and the HF registry rewriter as offline review-only candidate tools.
8. **Official activation prerequisites:** make lower-is-better behavior consistent everywhere; reject forgeable published results outside the governed parser; reject credential-bearing evidence URL queries/fragments; require streaming/decompression/peer/TLS proof before enabling transport.
9. **Accessibility/performance:** evaluate accessible pagination or a proven virtual grid with assistive technology; profile 500x42 scrolling and the 1.4 MB raw bundle; set bundle/runtime budgets before lazy splitting.

Good next features after correctness: coverage/confidence indicators for sparse comparisons; provenance-first claim detail and downloadable evidence receipts for governed releases; saved/shareable comparison presets only after explicit routing/404 design; benchmark-domain diagnostics; privacy-minimized release status/incident page; operator-facing release/rollback receipt generation. Keep the ledger CLI-only.

## Recovery and handoff

- Before each lane, capture status and a scoped diff. Roll back only that lane’s owned patch with `apply_patch`; never use reset/checkout/clean.
- If a dependency upgrade or header policy regresses behavior, retain the prior lock/static files and defer the slice; do not weaken tests or deploy to learn in production.
- The implementation owner should dispatch in the dependency order above, collect scoped diffs and test receipts, and loop until criteria pass or a named blocker remains.
- “Verified” requires target-perspective evidence from the real CLI process, immutable record/artifact, rendered UI, or provider deployment—not a worker statement or diff alone.

## Historical execution note

Planning completed and its findings were reconciled against the frozen
baseline. Browser evidence was unavailable, so no visual acceptance was
claimed. Local provider, model, permission, task, terminal, and launcher-failure
evidence is intentionally not tracked in this public repository.
