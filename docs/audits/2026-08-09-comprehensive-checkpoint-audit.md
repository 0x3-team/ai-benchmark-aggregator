# Comprehensive checkpoint audit

**Date:** 2026-08-09
**Final continuation:** 2026-08-12 local
**Repository:** `/Users/stevmq/Documents/ai-benchmark-aggregator`
**Local HEAD:** `5eb3b35e35867e6b56837d7fc9b67e120c423b45`
**Branch:** `main` (local `main...origin/main [ahead 3]`)
**Plan:** [2026-08-09 comprehensive checkpoint remediation plan](../plans/2026-08-09-comprehensive-checkpoint-remediation-plan.md)
**Release state:** local remediation worktree only; not pushed, deployed, or accepted live

This report is the final evidence-led checkpoint artifact. It records the
current worktree and the frozen planning evidence without treating a worker
screen, a local build, or a live page as proof of another state. No Official
release, source ingestion, provider mutation, paid operation, Worker, or
deployment was authorized or performed by this checkpoint.

## Executive verdict

The worktree contains broad local remediation across the ledger, frontend,
dependency, documentation, repository, and static Pages lanes. The known local
defects from the frozen baseline have been addressed in source and focused
fixtures, including CLI import/containment, BigCodeBench extraction, Demo
catalog contracts, immutable dataset and calculation semantics, virtualization
and accessibility controls, dependency/lock hygiene, PostgreSQL role/run
hardening, and static Pages metadata.

The final local frontend gates are green. After a test-only correction to two
stale assertions, the unfiltered ledger suite is also green: 1,524 passed and
14 skipped. **Local engineering verdict: ACCEPT WITH RISKS.** No known material
local code or CI defect remains, but the worktree is dirty, the candidate
archive is not final, and browser/live/provider proof is absent.
**Production-readiness verdict: NOT READY.** The governed Official artifact,
GitHub billing and repository controls, Cloudflare ownership and deployment
identity, native-browser evidence, and managed security-scan access remain open
blockers.

### Exact local and live anchors

- Local source anchor: HEAD `5eb3b35`, branch `main`, dirty shared worktree.
  The current status includes concurrent lane edits; they are preserved and
  have not been reset, cleaned, stashed, or overwritten.
- Intended live custom host: [`https://benchmark.0x3.dev/`](https://benchmark.0x3.dev/).
  At `2026-08-09T13:39Z`, the two recorded live hosts returned identical old
  421-byte HTML. Neither response contained the new canonical or noindex
  controls; unknown and missing-asset probes remained soft 200s. The second
  host is retained in the parent live receipt rather than guessed here.
- The live responses are therefore unshipped state, not a source-to-SHA
  deployment receipt for this worktree. No verified deployment of the new
  canonical, Pages `_headers`, or `404.html` was established.
- No deployment, push, rollback, DNS change, Cloudflare configuration change,
  GitHub setting change, or paid operation was performed by this checkpoint.

## Scope, methodology, and limits

### Scope

The audit covers the frozen baseline, the current shared worktree, the
remediation plan, focused source/tests, repository and release controls, and a
bounded read-only probe of the known live host. It covers these trust surfaces:

- ledger CLI startup, admission, evidence, adapters, migrations, storage, and
  dependency controls;
- Demo/Official data boundaries, score calculations, chart semantics, state
  resets, virtualization, and accessibility disclosures;
- static Pages fallback, robots/canonical/security metadata;
- GitHub templates, CODEOWNERS, CI, documentation, lockfiles, and release
  truthfulness.

### Method

1. Anchored to the actual checkout, branch, HEAD, dirty status, plan, and
   changed paths.
2. Reconciled the plan's frozen baseline and worker receipts against local
   source, fixtures, migration files, package/lock files, and documentation.
3. Used read-only `curl` requests for the recorded live hosts and deliberately
   tested unknown and missing assets.
4. Reconciled the final frontend, unfiltered ledger, clean-copy, CLI/Alembic,
   lock/hash, provenance, and provider receipts. No final receipt was inferred
   from a worker screen alone.
5. Kept local, pushed, deployed, live-verified, and accepted states separate.

### Limits

- The worktree is dirty and the remediation is not pushed or deployed. The
  fresh local receipts support ACCEPT WITH RISKS; production-readiness remains
  NOT READY because external blockers persist.
- The local HEAD does not contain these uncommitted changes; therefore a
  `git archive HEAD` result cannot include or validate this remediation.
- The live host is serving an older/different artifact; it is not proof of this
  worktree or of the new Pages controls.
- The in-app browser reported `Browser is not available: iab`; no outside
  browser was substituted.
- Managed Codex Security Deep Scan could not start because its managed
  filesystem profile was unavailable.
- Worker-reported outcomes are useful routing/evidence context, but final
  acceptance still requires the command, artifact, target-perspective, or
  provider receipt named in the matrix below.

## State vocabulary

- **Fixed locally:** source/tests/docs in this worktree address the finding;
  integrated rerun or target-perspective proof may still require completion.
- **Deferred:** deliberately not implemented because required authority or
  evidence is missing.
- **Blocked:** the next proof requires an unavailable account, tool, owner, or
  external state.
- **Intentional gate:** the absence is the required containment behavior.
- **Pushed/deployed/live/accepted:** not claimed unless an exact receipt proves
  that state.

## Findings ordered by severity

| Severity | Domain | Risk / original evidence | State | Exact remediation or next proof |
| --- | --- | --- | --- | --- |
| P0 | Governance / Official | The frozen baseline and release runbooks require REL-05 authorization, source certification, immutable evidence, review, and publication decisions. No governed Official artifact is available. | **Intentional gate** | Keep the tracked unavailable artifact and Demo-only runtime. Acceptance requires a governed release manifest, source/revision decisions, digest, evidence receipts, withdrawal path, and independent release sign-off. |
| P0 | Production claims | A local source change, test, or GitHub commit must not be presented as deployed or live. | **Intentional gate** | No deploy/push was made by this checkpoint. Production acceptance requires provider deployment-to-SHA, live headers/routes, rollback, and release receipts. |
| P1 | Cloudflare / Pages | Frozen evidence showed live soft 200 routes/assets and incomplete robots/canonical/security policy; the `2026-08-09T13:39Z` live receipt still showed identical old 421-byte HTML, no canonical/noindex, and soft 200 unknown/missing assets on both recorded hosts. | **Fixed locally / live blocked** | `public/404.html`, `public/robots.txt`, `public/_headers`, and `index.html` now provide source controls. Deploy the exact source only after correct account/project authority, then prove 404, robots, canonical, headers, preview policy, and rollback. |
| P1 | Cloudflare identity | Project/account access, deployment identity, Git mode/branch, DNS/TLS, and rollback remain unverified. | **Blocked** | No Wrangler config or binary, token, account ID, or assigned operator exists locally. The operator must identify the correct project/account and supply deployment ID, commit SHA, host/DNS/TLS, preview, and rollback receipts. |
| P1 | GitHub governance | Latest remote Verify run `30247550042` failed before steps due to account payment/spend limit; `main` remains unprotected on the current plan. | **Blocked** | GitHub owner must clear billing/plan limits, rerun Verify, and enable supported required checks/reviews. Acceptance is a live settings and successful-run receipt. |
| P1 | GitHub ownership | Frozen evidence reported invalid live CODEOWNERS entries. The local file now uses the supplied valid owner identity. | **Fixed locally / live blocked** | `.github/CODEOWNERS` uses `@Masih-0x3` for declared paths. GitHub must verify account/team existence, write access, and review routing; W7 did not guess additional identities. |
| P1 | Ledger CLI | Clean fresh-process CLI import was blocked by an eager circular ingestion import; tests had masked the issue. | **Fixed locally / integrated receipt passed** | `ledger/app/ingestion/__init__.py` and `ledger/app/cli.py` isolate imports; `ledger/tests/test_cli_import_boundary.py` covers fresh CLI/help and the import boundary. CLI/compile/Alembic checks and the final unfiltered ledger suite passed. |
| P1 | Ledger containment | Fresh initialization could auto-create unsafe parents and non-dry ingestion could reach a missing database; SafeFetch error handling needed redaction on the real path. | **Fixed locally** | `ledger/app/db/migrate.py`, `ledger/app/cli.py`, and `ledger/app/ingestion/runner.py` add validated fresh-parent behavior, no-auto-init/refusal, and SafeFetch redaction. Acceptance requires the targeted containment tests plus no-new-DB proof. |
| P1 | Ledger evidence | BigCodeBench work was protected but required fixture-first extraction, exact raw lexemes, typed evidence, duplicate/zero/malformed rejection, and replay identity. | **Fixed locally / integrated receipt passed** | `ledger/app/ingestion/adapters/bigcodebench_parquet.py`, registry boundary, and `ledger/tests/test_bigcodebench_parquet_adapter.py` implement and test the contract. The final unfiltered ledger suite passed. |
| P1 | Frontend data trust | Demo metadata, legacy shape, normalization domains, and unchecked casts could present invalid or invented score semantics. | **Fixed locally / frontend receipt passed** | `src/data/demoCatalog.ts`, `src/data/demoCatalog.test.ts`, `src/data/benchmarks.{json,ts}`, and `src/types.ts` add fail-closed parsing, methodology/domain metadata, raw-only handling, and header/body parity. Frozen `npm ci`, typecheck, test, verifier, and build receipts passed. |
| P1 | Frontend calculations | Missing values, out-of-domain values, lower-is-better metrics, subset-derived SOTA, and partial-cohort comparison could mislead users. | **Fixed locally / frontend receipt passed** | `src/lib/aggregate.ts`, `src/lib/chartData.ts`, `App.tsx`, chart adapters, and focused tests preserve nulls, omit invalid normalized points, handle direction, and use full-cohort statistics including comparison. The final frontend receipt covered 19 files and 96 tests. |
| P1 | Frontend state/scale | Retained score references could mutate; filters/sorts/source changes could retain stale virtual scroll or dependent state; the scale suite collected only three cases. | **Fixed locally / frontend receipt passed; visual blocked** | `src/data/dataset.tsx`, `App.tsx`, `ScoreTable.tsx`, `ModelDetail.tsx`, scale fixtures/tests, and component tests add immutable snapshots, reset/clamping, row semantics, totals/indices, and five intended scale cases. `npm ci`, typecheck, tests, verifiers, and build passed; native browser evidence remains blocked. |
| P1 | Frontend accessibility | Header, filters, comparison limits, heatmap, chart legends, evidence disclosures, toast controls, and 200%/390px behavior lacked durable semantics or evidence. | **Fixed locally / visual blocked** | W6 component/CSS changes and `src/components/W6B.a11y.test.tsx` add labels, pressed/disabled/polite semantics, evidence disclosures, and keyboard controls. Computer Use visual/AT acceptance is blocked by `iab`. |
| P1 | Dependency/reproducibility | Frozen baseline had dev advisories and unbounded Python/dependency drift. | **Fixed locally / residual package audit caveat** | Frontend `npm audit` reported 0 after Vite `6.4.3`, Vitest `3.2.7`, PostCSS `8.5.26`, undici `7.29.0`, and nanoid `3.3.18`. `uv.lock` is authoritative; `requirements-ci.lock` must be its exact byte-identical deterministic export. `ledger/scripts/verify_ci_lock.py` performs that export comparison and rejects graph/version/hash/marker tampering; the official `astral-sh/setup-uv@c771a70e6277c0a99b617c7a806ffedaca235ff9` v9.0.0 action pins uv 0.11.18 and runs before `pip install --require-hashes`. Package-level audit still flags `pyarrow` `PYSEC-2026-113`, documented as non-applicable to Python bindings/Parquet path; final policy disposition remains required. |
| P1 | Database security | PostgreSQL and SQLite run finalization needed forward-only hardening; migration recovery must not use downgrade. | **Fixed locally / integrated gate passed** | Migrations 0011 and 0012 enforce one terminal finalization for PostgreSQL and SQLite. CLI/compile/Alembic, role, migration, and final ledger gates passed. |
| P1 | Build provenance | A built Pages artifact was not bound to its exact source tree and artifact bytes. | **Partially fixed locally / external authorization blocked** | Deterministic source and `dist` digests, canonical manifest validation, tamper tests, build integration, and CI gates are present. Release still needs an assigned signer, authorized signed artifact, provider deployment, and published-digest proof. |
| P1 | Recovery and discovery bounds | SQLite recovery and discovery fixtures could materialize attacker-controlled content without complete resource limits. | **Fixed locally / integrated gate passed** | F19 and F20 add descriptor/stream bounds, fail-closed errors, and focused regressions. The final unfiltered ledger suite passed. |
| P2 | Static Pages / repository truth | Missing templates and unsafe contributor instructions could cause invalid GitHub forms, false status claims, or unsafe operational actions. | **Fixed locally / CI wired fail-closed** | `CONTRIBUTING.md`, issue-form `description` keys, Markdown PR template, Pages files, and `scripts/verify-pages-static.mjs` provide containment-safe guidance. The public CLI requires `--require-dist`; its no-dist regression passes, and `npm run verify:pages-static` now runs after build in both frontend and clean-archive CI with 10/10 verifier tests. |
| P2 | Documentation/environment | README, ledger README, and `.env.example` needed truthful unavailable/CLI-only/credential boundaries and dependency/install guidance. | **Fixed locally** | Documentation and `ledger/.env.example` now state Demo synthetic status, Official unavailability, no source credentials, read-only/remediation boundaries, and provider-state limits. Markdown links validate locally. |
| P2 | Ledger performance | Local orphan inventory, ingestion/reporting paths, and evidence parsing had avoidable repeated scans/reparsing and N+1 behavior at scale. | **Fixed locally in bounded slice / follow-up required** | Local orphan accounting is O(n) and the current path avoids the known repeated work. Acceptance still needs counters, 10k-claim budgets, RSS/timing receipts, and broader N+1 remediation. |
| P2 | Release operations | No complete release pipeline, withdrawal/rollback rehearsal, monitoring, incident path, or accountable owner set is live. | **Blocked / deferred** | Assign release/source/legal/telemetry/monitoring/rollback owners and rehearse capture → review → artifact → deploy → withdraw → rollback with exact receipts. |
| P3 | Performance/AT | Enforced bundle and large-table budgets pass, but Vite still warns about the 696,014-byte entry chunk; visual and assistive-technology acceptance is unavailable. | **Backlog / visual blocked** | Keep the current fail-closed budgets, reduce the entry chunk when the change is measured and safe, and complete native-browser and AT evidence before production readiness. |
| P3 | Frontend test hygiene | The passing frontend run emits React `act(...)` warnings for suspended resources and SVG/JSDOM tag or casing warnings. These warnings can hide later test regressions. | **Backlog** | Make async test completion explicit and correct the SVG test-environment mocks/context, then require a warning-clean frontend test run. |

## Resolved locally in the current worktree

These are source-level remediations visible in the dirty worktree. They are not
claims that the changes are pushed, deployed, or fully accepted.

### Ledger and data boundary

- Removed the eager CLI import cycle and added a fresh-process CLI/help
  regression (`ledger/app/ingestion/__init__.py`, `ledger/app/cli.py`,
  `ledger/tests/test_cli_import_boundary.py`).
- Added safe no-auto-init/refusal behavior and validated creation of only the
  explicitly selected fresh parent (`ledger/app/db/migrate.py`, CLI tests).
- Routed SafeFetch redaction through the real ingestion path rather than only a
  test helper (`ledger/app/ingestion/runner.py`).
- Completed the protected BigCodeBench Parquet adapter with deterministic
  fixture/adversarial tests and typed `parquet_cell_v1` evidence.
- Added the forward-only PostgreSQL ingestion-run hardening migration `0011`
  and retained downgrade refusal; role and migration tests are present.
- Made `uv.lock` the authoritative Python lock and retained
  `requirements-ci.lock` as its exact byte-identical deterministic export.
  `ledger/scripts/verify_ci_lock.py` compares the regenerated export byte for
  byte and rejects graph/version/hash/marker tampering. The official
  `astral-sh/setup-uv@c771a70e6277c0a99b617c7a806ffedaca235ff9` v9.0.0 action pins
  uv 0.11.18 and CI runs the verifier before `pip install --require-hashes`.
  The setuptools finding is corrected and pre-commit hooks are pinned to
  reviewed commit SHAs.
- Kept local orphan accounting O(n) in the bounded storage path and preserved
  append-only evidence/claim behavior.

### Frontend truth and interaction

- Added a fail-closed Demo catalog/parser with methodology and
  bounded-domain/raw-only normalization metadata and repaired legacy table
  parity.
- Made dataset score snapshots immutable against retained caller references.
- Preserved null/no-data display, omitted invalid/out-of-domain normalized
  points, and applied lower-is-better direction consistently in aggregates and
  charts while retaining raw table values.
- Moved SOTA, leaders, field averages, and comparison statistics to the full
  cohort rather than the visible subset.
- Added filter/sort/source identity reset and clamping for virtualization;
  retained fixed row geometry, accessible full names, totals/indices, and sort
  semantics. The scale suite now has the intended five cases in source.
- Added Demo/Official truth labels, evidence disclosures, durable search labels,
  toggle/pressed/disabled/polite status semantics, chart legend controls, toast
  close semantics, and high-value heatmap keyboard/accessibility fixes.
- Hardened Official URL parsing/validation and kept the unavailable artifact
  data-free.

### Static Pages, repository, and dependency truth

- Added Pages `404.html`, plain-text `robots.txt`, conservative `_headers`, and
  canonical `https://benchmark.0x3.dev/` metadata. CSP remains report-only; no
  HSTS, enforcing CSP, report endpoint, Worker, or Function was added.
- Added `scripts/verify-pages-static.mjs`, whose public CLI requires
  `--require-dist` and validates matching built `dist` copies. Its no-dist
  regression fails closed, while source-only unit validation remains available.
  CI runs `npm run verify:pages-static` after build in both frontend and
  clean-archive; the suite covers source behavior plus missing/stale `dist`
  regressions and passes 10/10.
- Rewrote contributor guidance to be containment-safe and status-truthful;
  fixed issue-form metadata; replaced the YAML PR form with Markdown.
- Updated README/ledger README/environment truth for Demo-only runtime,
  unavailable Official mode, CLI-only ledger, no credentials, and provider
  limits.
- Upgraded Vite/Vitest/PostCSS and remediated `undici`/`nanoid`; the dependency
  lane reports `npm audit` 0 after those changes. The package-level Python
  audit still records the documented non-applicable pyarrow advisory.
- Replaced invalid CODEOWNERS identities locally with the supplied owner entry;
  live GitHub validity and routing remain blocked by provider access/plan state.

## Unresolved prioritized backlog

| Priority | Owner needed | Action | Acceptance evidence |
| --- | --- | --- | --- |
| P0 | Release/governance owner | Certify a permitted source/revision, dimensions, evidence, review, publication decision, and immutable Official artifact; retain withdrawal. | REL-05 decision, canonical digest, source/evidence receipts, unavailable-to-Official cutover review, and withdrawal rehearsal. |
| P1 | Cloudflare operator | Resolve wrong account/project; verify custom host, Git mode/branch, deployment-to-SHA, DNS/TLS, preview policy, headers, 404, cache, and rollback. | Authenticated provider receipt plus `curl`/native-browser route/header matrix against the exact deployed SHA. |
| P1 | GitHub owner | Clear billing/spending block, verify `@Masih-0x3` access, rerun Verify, and establish supported branch protection/review checks. | Successful remote Verify run, live settings screenshot/API receipt, valid CODEOWNERS review assignment. |
| P1 | Frontend QA/AT owner | Obtain native in-app browser and perform 390/768/1440px, 200% zoom, keyboard, console, overflow, comparison, source-switch, and deep-scroll checks. | Computer Use receipt with screenshots/DOM evidence and no unreviewed visual/AT failures. |
| P1 | Security owner | Provision the managed filesystem profile and rerun/seal the Codex Security Deep Scan. | Managed scan receipt with findings disposition and no critical/high unresolved result. |
| P1 | Ledger security owner | Bind future operational timestamps to trusted commit/receipt time; harden SQLite descriptor-relative no-follow operations. | Forward-only migration/design review plus SQLite/PostgreSQL adversarial tests for symlink/race and timestamp authority. |
| P1 | Discovery owner | Close discovery fixture symlink handling and prove fixture-only transport boundaries. | Symlink adversarial fixture receipt; no live fetch or source certification. |
| P1 | Tooling owner | Retire or redesign direct-network scripts and the HF registry rewriter as offline review-only tools. | Static/network policy tests showing no unapproved direct-network path. |
| P1 | Registry owner | Reject duplicate model IDs and define deterministic filename-precedence behavior without silently choosing a row. | Collision fixtures, explicit rejection/review queue, and registry census receipt. |
| P2 | Ledger performance owner | Remove ingestion/reporting N+1/reparse behavior and scale evidence resolution. | Statement/decode/read counters, 10k-claim timing/RSS budgets, and regression tests. |
| P2 | Release/operations owner | Build the release/withdrawal/rollback pipeline and assign monitoring, incident, source, legal, telemetry, and signer owners. | Copy-only rehearsal dossier linking decisions, artifact, deployment, alert, withdrawal, restore, and rollback. |
| P2 | Frontend performance owner | Measure bundle and 500×42 scrolling; set budgets and split only where measurement supports it. | Clean build size/runtime report, budget thresholds, and regression gate. |
| P3 | Product owner | Add practical post-correctness features: governed release status, change history, comparison permalinks/exports, confidence/evidence UX, saved cohorts, and freshness/status. | Product decision plus URL/404/privacy/provenance contracts and focused tests before implementation. |
| P3 | Coordinator | Complete final CI/full-suite rerun, then decide whether push/deploy is authorized. | Full command receipt, clean archive from the exact candidate commit, explicit push/deploy approval, and post-deploy live evidence. |

## Positive controls

- The Official containment verifier was 5/5 in the frozen baseline and the
  shipped Official artifact remains unavailable/data-free.
- Raw source lexemes, immutable snapshots, append-only claims, typed evidence,
  uncertain identity review, and no recalculation-as-claim remain explicit.
- `DatasetProvider`/`getValue` remains the frontend score boundary; nulls stay
  no-data and presentation rankings are not persisted as Official claims.
- The ledger remains CLI-only. No public ingestion API, Worker, source token,
  provider credential, or paid service was introduced.
- Static Pages controls are source-only and conservative: nosniff, strict
  referrer, clickjacking denial, minimal Permissions-Policy, report-only CSP,
  pages.dev noindex patterns, and no HSTS/enforcing CSP without proof.
- Contributor/PR templates require exact evidence and prohibit fabricated live,
  browser, Official, destructive-recovery, or credential claims.
- Existing dirty work and protected adapter/fixture files were preserved.

## Cloudflare and GitHub live evidence/blockers

### Cloudflare

At `2026-08-09T13:39Z`, both recorded live hosts returned identical old
421-byte HTML. Neither contained the new canonical or noindex controls, and
unknown/missing assets remained soft 200s. The custom host
`https://benchmark.0x3.dev/` is therefore still unshipped relative to this
worktree. Cloudflare authentication is blocked by 401/403 and Wrangler is
unavailable. Deployment identity, account/project, DNS/TLS ownership, preview
behavior, headers, and rollback remain unverified; no provider mutation was
attempted.

The source follows current [Cloudflare Pages Serving Pages semantics](https://developers.cloudflare.com/pages/configuration/serving-pages/): a
top-level `404.html` disables the implicit SPA fallback for unknown paths. It
also follows the current [`_headers` semantics](https://developers.cloudflare.com/pages/configuration/headers/),
including static-asset rules and documented pages.dev noindex patterns. These
official docs support source shape only; they do not prove this project's live
deployment.

### GitHub

The latest remote Verify run `30247550042` failed before steps because of the
account payment/spend limit. `main` remains unprotected on the current plan,
and the pushed CODEOWNERS entries were invalid live.
The local CODEOWNERS file now names `@Masih-0x3`, but live account/team
validity, write access, review routing, required checks, and branch protection
remain unverified. No GitHub setting, branch protection, CODEOWNERS ownership,
push, or PR action was performed by this checkpoint.

## 2026-08-12 final continuation

This section supersedes the older test counts and route status below where they
conflict. The older entries remain as historical checkpoint evidence.

- **Local engineering verdict: ACCEPT WITH RISKS.** No known material local
  code or CI defect remains after the fresh integrated gates. The worktree is
  still dirty and uncommitted, the exact candidate archive is not final, and
  browser, provider, and live release evidence remain absent.
- **Production-readiness verdict: NOT READY.** Nothing from this continuation
  was pushed, deployed, or verified live.
- F19 SQLite recovery resource bounds, F20 discovery fixture bounds, and F16
  SQLite ingestion-run terminal history are fixed locally.
- F13 source-to-`dist` provenance is implemented and CI-wired, but remains
  **PARTIALLY FIXED LOCALLY / EXTERNAL AUTHORIZATION BLOCKED**. No signer or
  approval authority, authorized signed artifact, push, Cloudflare deployment,
  or published-digest proof exists.
- The first fresh full ledger gate found two stale assertions: 2 failed, 1,522
  passed, and 14 skipped. A test-only repair updated the explicit registry row
  baseline after the intentional three-row deduplication and made the
  PostgreSQL portability check reject real SQLite-only SQL instead of a valid
  revision name. The coordinator then reran the two tests and the unfiltered
  suite: 2/2 passed, followed by 1,524 passed and 14 skipped with exit 0.
- `ledger/tests/_tmp_probe_reg.py` is an untracked P3 ownership/cleanup review
  item. This continuation did not delete it or claim ownership.

## Verification matrix

| Gate | Evidence/command | Current state | Truthful interpretation |
| --- | --- | --- | --- |
| Local anchor/status | `git rev-parse HEAD`, `git branch --show-current`, `git status --short --branch` | **Observed** | HEAD/branch are exact above; worktree is dirty and uncommitted. |
| Diff hygiene | `git diff --check` | **Passed for W7 closeout** | Whitespace is clean for the current worktree check; not a full acceptance gate. |
| Static Pages | `npm run build` then `npm run verify:pages-static` | **Passed 10/10** | The public `scripts/verify-pages-static.mjs --require-dist` contract fails closed when `dist` is absent, rejects missing or stale built controls, and retains source-only unit coverage; both frontend and clean-archive CI paths invoke it after build. This remains local/unpushed. |
| Issue YAML | Ruby YAML parse of both issue forms | **Passed locally** | Syntax parses; live GitHub rendering/permissions remain unverified. |
| Official containment | `npm run verify:official-artifact` | **Passed 5/5** | Official remains unavailable/data-free; this is containment evidence, not publication authorization. |
| Frontend install/tests | Frontend typecheck, `typecheck:test`, verifiers, and `npm test` | **Passed** | 19 files and 96 tests passed; Official 5/5, provenance 25/25, Pages 10/10, and bundle 52/52 passed. |
| Frontend build | `npm run build` | **Passed** | TypeScript, Vite, and provenance creation passed. This is local build evidence only. |
| Frontend clean copy | Clean-copy install/build receipt | **Passed** | Clean-copy build passed; this remains local and unpushed. |
| Ledger monolithic run | `cd ledger && uv run pytest -q` | **Passed after test-only repair** | Initial gate: 2 failed, 1,522 passed, 14 skipped. Coordinator final rerun: 1,524 passed, 14 skipped in 111.06 seconds, exit 0. |
| Ledger file-sharded run | Historical low-disk fallback across 56 files | **Passed historically** | The earlier 1,131/1,131 sharded receipt remains for history; final acceptance uses the later unfiltered monolithic run. |
| Ledger CLI/compile/migrations | Fresh CLI/help, compile, Alembic head, migrations 0011/0012, role gate | **Passed** | CLI/compile/Alembic single-head, both forward-only run-history guards, and PostgreSQL role gates passed. |
| Containment smoke | `bash -n scripts/mvp_acceptance.sh`; disposable `bash scripts/mvp_acceptance.sh` | **Passed** | Script syntax and the local disposable SQLite containment smoke passed without provider credentials or network access. |
| Dependency/lock audit | Fresh npm audit plus Python lock integrity | **Passed with residual** | `npm audit --audit-level=low` found 0 vulnerabilities. `verify_ci_lock` and its tamper guards passed. `pip-audit` was unavailable, so no fresh Python vulnerability scan is claimed; the older PyArrow advisory qualification remains residual history. |
| Clean archive | `git archive HEAD` + full clean archive matrix | **Not final-accepted** | Clean-copy build passed, but current local HEAD excludes dirty changes; exact candidate-commit archive receipt remains required. |
| Live host | Read-only `curl` at `2026-08-09T13:39Z` to both recorded hosts | **Observed failure/blocker** | Both returned identical old 421-byte HTML with no canonical/noindex; unknown/missing assets remained soft 200. |
| Native browser | Computer Use against `http://127.0.0.1:4173/` | **Blocked; preview stopped** | GPT-5.6 Sol Low Fast received `Browser is not available: iab`. Only Chrome extension surfaces were visible and were not substituted. No tab, screenshot, viewport, interaction, console, network, auth, or focus-interruption evidence exists. |
| Security scan | Managed Codex Security Deep Scan | **Blocked** | Required managed filesystem profile unavailable; independent static audit found no critical/high issue in frozen evidence. |
| GitHub | Verify workflow, protection/rulesets, CODEOWNERS, templates | **Blocked** | The latest run remains `30247550042` at `f0115929898dc4ec7c65882db7db96b0172c0143`; jobs had no steps and the annotation cites failed payments or spending limit. Pushed CODEOWNERS has 10 unknown-owner errors. Local CODEOWNERS/template fixes are unpushed; the live profile still has no issue template and points to the old YAML PR template. Protection and rulesets return 403 on the private-repo plan. Actions permits all actions and does not require SHA pinning. |
| Cloudflare | Local configuration, credentials, provider identity, deployment | **Blocked / not verified** | Pages is selected, but operator/account/project/DNS/deploy authority is unassigned. No Wrangler config or binary is present; token and account-ID environment variables are absent. No provider API read or mutation, deployment identity, published digest, or rollback proof occurred. |

## Good-next product and engineering features

After the correctness and acceptance gates close, the practical next features
are:

- a governed Official release pipeline with source certification, immutable
  artifacts, explicit publication, withdrawal, and rollback receipts;
- model/benchmark change history tied to source revisions and methodology;
- comparison permalinks and safe exports designed around explicit routing and
  provenance;
- confidence, coverage, raw-evidence, and methodology UX that never turns
  presentation estimates into claims;
- saved cohorts/comparison presets after privacy, URL, and 404 contracts are
  accepted;
- freshness and release/status indicators with clear Demo versus Official
  state;
- further measured entry-chunk splitting, warning-clean async/SVG tests, and
  accessible pagination or a proven assistive-technology-compatible virtual
  grid.

## Agent usage and strict-route record

This section records routing context from the remediation plan and current
checkpoint. It is not a substitute for command or provider evidence.

- **Planning:** native Sol Max/planner route selected for the cross-surface
  checkpoint; the planning route passed and produced the linked remediation
  plan.
- **First independent acceptance:** native Sol Max returned **CHANGES REQUIRED**
  for the Python lock-integrity and built-`dist` Pages-verifier gaps. Both gaps
  were remediated and independently reverified by the receipts above. The final
  independent receipt is **Local engineering verdict: APPROVE**;
  **Production-readiness verdict: NOT READY**; no material code/CI findings
  remain.
- **Second acceptance marker:** native Sol Max again returned **CHANGES REQUIRED**
  for the missing exact uv-export/setup-uv/tamper guards and the public Pages
  dist requirement. The exact byte comparison, official setup-uv pin and uv
  version, marker/hash/version tamper rejection, public `--require-dist` CLI,
  no-dist regression, and 10/10 verifier suite are now remediated and
  independently reverified. The final independent receipt is **Local
  engineering verdict: APPROVE**; **Production-readiness verdict: NOT READY**;
  no material code/CI findings remain.
- **Independent audit:** native Sol Max audit workers covered
  architecture, frontend logic, ledger integrity, security, performance,
  QA/docs, UI/UX, and Cloudflare/release. Their findings were reconciled with
  the frozen evidence; they did not prove deployment or final integrated gates.
- **Implementation:** the older Luna High lanes remain historical context. The
  final F19, F20, F16, and F13 continuation used the exact user-selected
  `zro launch claude --model deepseek-v4-flash-0731 '--dangerously-skip-permissions'`
  route. Process and managed-model evidence
  showed `deepseek-v4-flash-0731`; reasoning and Fast status were not surfaced.
  Stalled or inaccurate worker output was rejected and its task-owned terminal
  was closed. Accepted code and tests followed coordinator review, rework, and
  fresh command evidence. The main coordinator's runtime identity, model,
  reasoning level, and Fast status were not exposed and are not inferred.
- **Orca/Claude/deepseek route:** the earlier launch failure is a superseded
  historical receipt. Later workers launched successfully through Orca/ZRO.
  The final read-only gate found two stale test assertions; the focused repair
  worker corrected them, and the coordinator independently confirmed the
  unfiltered 1,524-pass ledger result.
- **Computer Use:** GPT-5.6 Sol Low Fast route was required, but the native
  in-app browser returned `Browser is not available: iab`; no outside browser
  evidence was accepted.
- **Managed security scan:** blocked because the required managed filesystem
  profile was unavailable; no scan result was fabricated.
- **Strict-route result:** the selected Claude implementation route passed for
  accepted source and test work. The Computer Use route used GPT-5.6 Sol Low
  Fast as required, but its `iab` surface was unavailable, so browser QA is
  blocked. **Local engineering verdict: ACCEPT WITH RISKS.**
  **Production-readiness verdict: NOT READY.** Native-browser acceptance,
  candidate-archive proof, and provider verification remain blocked. No push
  or deploy occurred.

## Final handoff

The final local receipts establish a remediation candidate, not a release.
**Local engineering verdict: ACCEPT WITH RISKS.** The fresh frontend gates and
the final unfiltered ledger suite pass, and no known material local code or CI
defect remains. The worktree is still dirty, a clean candidate-commit archive
is not proved, and the untracked P3 probe needs an ownership decision.

**Production-readiness verdict: NOT READY.** Production remains blocked by
Official governance and signing, GitHub billing/plan and live repository
controls, Cloudflare ownership/configuration/deployment identity, exact
published-digest and rollback evidence, and native-browser/assistive-technology
acceptance. Pushed: no. Deployed: no. Verified live: no. The preview server is
stopped.

## Ordered next five tasks

1. Assign governance, release, source-certification, and signing owners; then
   authorize one immutable Official artifact and digest.
2. Resolve GitHub billing and plan limits. Create a reviewed candidate commit
   and PR, validate CODEOWNERS and templates live, and enable required checks
   and protection or record the plan limitation.
3. Assign the Cloudflare operator, account, and Pages project. Create a
   least-privilege static Pages setup and deploy the exact authorized digest to
   preview only.
4. On that exact preview, run native-browser desktop/mobile/keyboard and
   assistive-technology checks plus headers, 404, robots, canonical, and
   noindex checks.
5. Run the signed publish, withdrawal, rollback, backup/restore, and monitoring
   rehearsal. Decide production promotion only after that evidence is accepted.

## Model inventory continuation — 2026-08-25

The next workstream starts at a safe, review-only checkpoint. A fresh bounded
discovery captured 417 OpenRouter entries and 100 Hugging Face top-download
entries. Combined with the 486 frontend models and 1,186 unique ledger registry
models, the inventory contains 2,027 normalized candidate keys. Only one exact
frontend/registry ID match exists, so identity reconciliation is required before
catalog enrichment or synthetic-data removal.

Evidence is recorded in
[`docs/handover/2026-08-25-model-inventory-checkpoint.md`](../handover/2026-08-25-model-inventory-checkpoint.md)
and [`docs/data/model-inventory-2026-08-25.json`](../data/model-inventory-2026-08-25.json).
The inventory is candidate-only, does not certify sources, and does not mutate
the frontend, claims ledger, or Official artifact. The 976 synthetic Demo
scores remain in place until canonical identities and scope are reviewed.
