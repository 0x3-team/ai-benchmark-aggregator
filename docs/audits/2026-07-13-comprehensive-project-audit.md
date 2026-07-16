# Comprehensive Project Audit — 2026-07-13

**Audit ID:** AUD-2026-07-13  
**Status:** completed, read-only  
**Release conclusion:** the demo UI can continue to be developed, but the current ledger ingestion and Official-mode publication path are **not ready to represent official benchmark results**. Do not publish or promote the current Official mode until the P0 containment and claim-integrity work below is complete.

## Audit anchor and method

| Field | Value |
| --- | --- |
| Repository / revision | `ai-benchmark-aggregator` / `b0e33e64683652b14377fd6440960acf52ce4d76` (`b0e33e6`) |
| Scope | React SPA, ledger ingestion/storage/review/export/CLI, source registry, tests, CI, documentation, and bounded security review |
| Mode | Read-only inspection and offline validation; no production code, ledger data, remote source, deployment, credential, migration, or dependency update was changed or invoked |
| Governing invariants | `AGENTS.md`: raw source preservation, immutable claims/snapshots, official-source-only admission, no derived official scores, uncertainty preserved as `needs_review`, idempotency, and a CLI-only ledger |
| Worktree note | Existing modified/untracked work was preserved. This report and the local model-routing ledger are audit documentation, not product data. |

The audit decomposed independent lanes for ledger trust, frontend behavior, storage/CLI integrity, and security validation. Every accepted finding below was independently checked against the repository or a bounded offline reproduction; external harness output was advisory unless independently verified.

## Verification completed

| Check | Result | Interpretation |
| --- | --- | --- |
| `npm run typecheck` | Passed | TypeScript passes in the current local workspace. |
| `npm run test` | Passed: 3 files, 6 tests | Basic frontend unit coverage exists, but it does not exercise application mode switching or components. |
| `npm run build` | Passed with a bundle warning | Main JavaScript output was 1,688.95 kB (300.76 kB gzip), above Vite's 500 kB warning threshold. The success relies on a locally present ignored export file. |
| `cd ledger && .venv/bin/python -m pytest -q` | Passed: 49 tests | Ledger fixture tests pass, but several tests encode or miss the trust-boundary failures below. |
| `npm audit --omit=dev --json` | 0 production vulnerabilities | A useful dependency signal, not a substitute for source-level security review. |
| Bounded security validation | Existing TauBench tests plus temporary mock/in-memory checks passed | Confirmed derived-score, hash-collision, bulk-verification, and CLI-secret-output findings without live source access. |

Passing local gates does **not** establish a release-ready clean checkout. The generated Official export used by the build is ignored by Git and is absent from an archive of `HEAD`.

## Immediate operating guardrails

Until the P0 acceptance criteria are met:

1. Do not run `seed-registry` against a database containing claims or snapshots.
2. Do not run a default `ingest --all`, `review auto-verify`, or Official export/publish workflow as a production-trust operation.
3. Do not present the current Official mode as verified official benchmark data. Keep demo data visibly distinct, or temporarily disable the Official switch.
4. Do not rely on the local ignored `src/data/official/export.from-ledger.json` as a reproducible release artifact.
5. Preserve existing local claims and snapshots for investigation; repair through new, source-backed claims and explicit migration/reconciliation, never by silently rewriting history.

## Prioritized remediation backlog

### P0 — release blockers and trust-boundary violations

| ID | Finding and evidence | Impact | Required outcome |
| --- | --- | --- |
| AUD-01 | **The claim-admission boundary accepts non-official, mock, fallback, metadata, and derived data as official results.** `ledger/app/ingestion/policy.py` checks source classification rather than validating a concrete source/payload/field. Active `fake_local_fixture` emits synthetic parser-verified claims (`official_sources.yaml`, `adapters/fake.py`). Artificial Analysis can emit hard-coded fallback data under an official identity (`artificial_analysis_api.py`); LMSYS falls back to a third-party endpoint (`lmsys_arena_api.py`); an active MT-Bench entry points to a blog; Hugging Face discovery metadata becomes parser-verified claims with `score_raw="n/a"` (`hf_benchmark_api.py`). LiveBench, LiveCodeBench, and TauBench calculate or transform scores; TauBench averages `pass_*` inputs into `81.2500` in the existing fixture and marks it verified (`taubench_s3.py:89-91,139-186`). | The ledger can state “official source X reported Z” when X did not report Z. This directly violates the repository's core product promise. | Introduce a centralized, fail-closed admission rule: a publishable claim must have an approved official source, an immutable snapshot, a verbatim raw reported value, an evidence location resolving to that value, and a permitted source/metric/split/configuration. Deactivate or quarantine fake, mock, fallback, blog, discovery-metadata, and derived-score adapters from the production path. Keep calculations only as clearly labeled presentation analytics outside official claims. Add fixture tests that reject each disallowed category. |
| AUD-02 | **`seed-registry` deletes historical ledger data.** `ledger/app/registry/seed_loader.py:103-115` disables foreign keys and deletes ingestion runs, claims, snapshots, and source rows before reseeding. | Reseeding can destroy the immutable historical evidence the ledger is intended to preserve; raw files are not reconciled atomically. | Replace destructive reseeding with versioned/upserted source-registry records. Never delete claims or snapshots as a seed side effect. Define a migration/reconciliation plan for existing data and add a regression test proving an existing claim/snapshot survives a seed refresh. |
| AUD-03 | **Official export has no deterministic selection policy.** `ledger/app/export/official_json.py:29-90` exports all statuses and does not order or choose a claim per model/benchmark identity. `src/data/registry.ts:28-31` then overwrites duplicate cells in a `Map`. In the inspected local export, 243 cells had duplicate rows (958 rows total); `claude_3_opus/tau_bench` had materially different values, and the UI selects whichever JSON row is last. | Rankings and displayed values can depend on query/order history rather than a stated provenance policy. | Define the result identity dimensions (model, benchmark, metric, split, setting, version) and a deterministic projection policy (eligible status, source priority, snapshot/version/date, conflict behavior). Order the query explicitly, reject or surface unresolved conflicts, and make the frontend consume a unique validated cell. Add export and UI tests for conflicting historical claims. |
| AUD-04 | **The Demo ↔ Official switch is non-reactive and can render stale values.** `src/App.tsx:74-89` changes module-global registry state in an effect after rendering; `src/data/registry.ts:40-46` does not notify React. A bounded rendering check showed the first post-switch lookup can use the prior index until an unrelated rerender. | A user may see mismatched models/benchmarks/scores immediately after changing data mode, undermining trust even after data integrity is fixed. | Keep active data and its index in React state/context (or a correctly subscribed external store) and switch them atomically. Add an application integration test that changes both directions and asserts the first committed render has matching models, benchmarks, values, and provenance. |
| AUD-05 | **A clean checkout cannot reliably build the frontend.** `src/data/official.ts` statically imports `export.from-ledger.json`, but `.gitignore` excludes it and it is not tracked. `.github/workflows/verify.yml` builds before its later export sanity check; README describes the artifact inconsistently. | A local build can pass while CI, a release checkout, or a new contributor fails at module resolution. | Choose and document one reproducible strategy: commit a governed fixture/export, generate it deterministically before build from an available fixture/artifact, or make Official mode a genuinely optional runtime capability. Test a clean `git archive HEAD`/fresh clone path in CI. |

### P1 — correctness, review, and trustworthy presentation

| ID | Finding and evidence | Impact | Required outcome |
| --- | --- | --- |
| AUD-06 | **Alias matching and bulk review can falsely verify uncertain or failed claims.** The model alias catalog contains 85 exact alias collisions across model IDs; `ledger/app/registry/aliases.py:16-49` returns a first match instead of marking ambiguity. `cli.py:157-174` bulk auto-verifies mapped claims, while `repositories.py:255-306` can change a failed-validation claim to `parser_verified` without a `ClaimValidation` record. An in-memory validation confirmed that a stored failed validation can be promoted and exported. The `review_map_model` helper lacks the command decorator, so the intended manual path is unavailable. | The explicit “uncertain model → null entity + needs_review” rule is bypassed, and failed data can reach Official output. | Make ambiguous aliases unmatchable by default; keep `model_raw`, entity null, and `needs_review`. Separate entity mapping from evidence validation/status transition. Require an explicit human review trail for any promotion, restore/expose a tested `map-model` CLI command, and prevent failed validations from becoming verified without a new recorded validation. |
| AUD-07 | **Export publishes provisional and structurally invalid score rows.** The inspected export contained 2,526 rows: 1,495 `needs_review` (59.2%) and 1,157 `value: null`. The TypeScript type says `value: number`, then masks mismatch with `as OfficialExport` (`official.ts:16-26,124-126`). The exporter includes all statuses; CI only counts rows rather than publishable numeric claims. | “Official” includes unresolved data and non-results. Consumers cannot distinguish reliable benchmark values from discovery/review backlog. | Make a product decision and encode it: either Official mode includes only a defined publishable status, or it visibly partitions/filters provisional claims with explicit policy. Validate JSON schema and semantic content at export time; count numeric, eligible, uniquely selected values in CI. Do not represent metadata/discovery rows as benchmark scores. |
| AUD-08 | **Global and category leaderboards reward sparse coverage.** `src/lib/aggregate.ts:34-72,141-188` averages only available ranks. `App.tsx` displays the resulting rank; coverage is calculated but not enforced or displayed. In the inspected export, the top ten global models each had one of 25 benchmarks (4% coverage) and rank 1. | The headline ordering can imply broad superiority from a single observation. | Establish disclosed cohort and coverage rules before ranking: minimum benchmark count/percentage, a common benchmark set, confidence/coverage display, and no global rank when the cohort is insufficient. Apply the same rule to category leaders and test sparse cases. |
| AUD-09 | **Official provenance cannot be followed in the UI.** `official.ts:83-96` supplies empty benchmark source URLs; `ScoreTable` and benchmark cards render links from them. `App.tsx:96-126` hardcodes six source IDs while the inspected export contained 27, leaving 21 unmapped. Claim/snapshot/evidence identifiers are retained but not shown. | Users cannot verify the source behind a score, contradicting the source-backed trust proposition. | Export a governed source/provenance manifest (canonical name/URL, source snapshot, evidence location, claim ID, retrieved date) and display it for every Official score. Do not render empty anchors. Add a link-completeness test. |
| AUD-10 | **Official model specifications are invented rather than unknown.** `official.ts:65-80` gives exported models values such as `contextWindowK: 0`, `openWeights: false`, and `modalities: ["text"]`; detail/comparison surfaces present them as facts. | Unsupported metadata makes the trust UI less credible. | Model unknown facts as unknown and hide them until sourced. If specs become part of the product, ingest them through a separate sourced metadata pipeline with provenance. |

### P2 — resilience, security hardening, performance, and test depth

| ID | Finding and evidence | Impact | Required outcome |
| --- | --- | --- |
| AUD-11 | **Snapshot storage deduplicates on only the first 16 hex characters of SHA-256.** `ledger/app/storage/local.py:25-35` reuses a path keyed by the truncated prefix while the database stores the full hash. A bounded temporary-directory reproduction forced distinct full digests with the same prefix and made the second snapshot point to the first bytes. | A chosen-prefix collision can detach persisted evidence bytes from the stored full digest and extracted claim. Accidental collision is very unlikely, but the integrity boundary should not use mismatched equivalence rules. | Use the full digest in the path, or verify the full digest before reuse; write atomically; add a collision-path regression test. |
| AUD-12 | **Remote fetchers lack consistent redirect destination and response-size controls.** Generic HTML/YAML and source fetch paths follow redirects without final host/IP/scheme validation and read full bodies; a mock redirect reached a link-local target. No lower-privileged source-configuration endpoint was established, so this is follow-up hardening rather than a proven externally exploitable SSRF path. | A compromised/operator-misconfigured source can broaden outbound requests or consume excessive memory/disk before snapshotting. | Centralize outbound HTTP policy: HTTPS/allowlist checks on every hop, reject private/link-local destinations where applicable, connect/read/total timeouts, streaming byte ceilings, content-type expectations, and bounded parser/config limits. Test redirect and oversized-body rejection. |
| AUD-13 | **Runner error and dry-run semantics are unsafe for operations.** `runner.py:97-122` writes snapshots before the dry-run branch; partial adapter failure can leave flushed data with incomplete run error reporting. Some generic JSON/CSV fetchers do not raise on HTTP error; a configured dotted Hugging Face field is read as a literal key and can silently yield no claims. | Operators cannot trust dry-run as non-mutating or distinguish a complete ingestion from a partial one. | Make dry-run entirely side-effect-free, use per-source transactions/explicit partial-run status, record every adapter error, call `raise_for_status`, validate adapter configuration at startup, and add failure-path fixtures. |
| AUD-14 | **Frontend test and performance coverage do not exercise the risky paths.** There are only three frontend unit-test files, no App/component/a11y/browser test, and the 2,280-model × 25-benchmark table can construct roughly 57,000 cells without virtualization or pagination. The build warning confirms a large initial bundle. A category change can retain a hidden benchmark sort (`App.tsx:275`, `aggregate.ts:122`). | Correctness regressions, accessibility issues, and slow rendering are likely to escape CI as data grows. | Add mode-switch, table/ranking, provenance, no-data, keyboard/screen-reader, and responsive/browser coverage. Profile realistic Official-sized data; add pagination/virtualization or a deliberate rendering strategy; split/lazy-load noncritical code; reset or visibly disclose invalid sort state. Set an agreed performance budget. |
| AUD-15 | **CI and dependency reproducibility need hardening.** Ledger dependencies use lower bounds without a lock/constraints file and CI installs them unbounded, while npm is locked. Workflow actions use mutable tags and the workflow lacks explicit minimum `permissions`. | Rebuilds can drift and CI supply-chain posture is weaker than necessary. | Pin/constraint Python dependencies with a reviewed update process, use reproducible installs, pin GitHub Actions to reviewed commit SHAs where policy permits, set least-privilege workflow permissions, and test the clean build path described in AUD-05. |

### P3 — operational polish and documentation consistency

| ID | Finding and evidence | Impact | Required outcome |
| --- | --- | --- |
| AUD-16 | **CLI/docs/architecture drift.** README says the ignored export is committed, ledger documentation describes an HF adapter as still needed although it exists, and the unusable `map-model` workflow is not documented as unavailable. The schema uses `Base.metadata.create_all()` with no migration system. | Operators receive unsafe or inaccurate guidance; schema evolution will become harder to audit. | Update README, AGENTS/ADR guidance, and CLI help after behavior is repaired. Add an explicit database migration strategy before schema changes become routine. |
| AUD-17 | **`init-db` can print credential-bearing database URLs.** `ledger/app/cli.py:30-34` prints `Settings.database_url`; a bounded fake-URL check retained the password in stdout. | Low-severity credential exposure through logs/terminal capture. | Redact userinfo/query secrets before display and add a CLI-output test. |

## Recommended delivery sequence

The work has real dependencies; fixing the UI alone would make an untrustworthy claim store easier to display. The smallest safe sequence is:

| Phase | Dependencies | Deliverables and exit criteria |
| --- | --- | --- |
| 0. Contain and decide | None | Quarantine unsafe sources/adapters; block Official publication; preserve all current evidence; select the clean-build artifact strategy and the definition of a publishable claim. Exit: no routine command can label fake/fallback/blog/derived/discovery data as publishable. |
| 1. Repair ledger truth | Phase 0 decisions | Non-destructive source seeding; source/field/evidence admission gate; ambiguity-safe mapping and validation review; full-hash snapshots; transactional runner semantics. Exit: fixtures prove raw `score_raw` appears at evidence location, uncertain matches remain unresolved, history survives refresh, and derived claims are rejected. |
| 2. Build a deterministic official feed | Phase 1 | Versioned schema; explicit projection/selection/conflict policy; provenance manifest; semantic export validation; clean checkout generator/fixture. Exit: each exported cell is unique, eligible, numeric where required, reproducible, traceable, and buildable from a fresh checkout. |
| 3. Repair product semantics | Phase 2 | Reactive mode state, truth-status treatment, provenance UI, unknown metadata handling, coverage-aware rankings, and responsive table strategy. Exit: first render after switching modes is coherent; no sparse model receives an undisclosed global rank; every displayed Official score links to evidence. |
| 4. Make the path durable | Phases 1–3 | CI reproducibility/security hardening, test expansion, a11y/browser tests, performance budgets, docs/CLI updates, migrations, and operator runbook. Exit: CI validates clean checkout, adversarial fixtures, accessibility, and data-scale behavior. |

## Acceptance gates before re-enabling Official publication

The following should be green simultaneously, not treated as independent optional improvements:

1. A source-admission test matrix rejects fake, fallback, third-party, blog, discovery metadata, derived calculation, missing evidence, and ambiguous model cases.
2. Every candidate Official score is verbatim in its immutable snapshot at the recorded evidence location; its status and source classification meet the selected publication policy.
3. Registry refresh has a non-destructive regression test, and source/snapshot/claim history remains queryable.
4. Export has a versioned schema and deterministic unique-cell projection with explicit conflict handling and provenance completeness checks.
5. A fresh clone or `git archive HEAD` completes install, typecheck, test, and build without relying on ignored local data.
6. Browser/component tests verify initial and switched Demo/Official renders, null handling, provenance links, ranking coverage, keyboard navigation, and screen-reader labels.
7. Ingestion failure, redirect, oversized response, configuration error, and dry-run tests prove bounded and accurately reported behavior.

## Confirmed strengths to retain

- The codebase has the right architectural intent: snapshots, raw source fields, source IDs, evidence locations, claim fingerprints, and fixture/idempotency tests already exist.
- `getValue(modelId, benchmarkId)` is used as the frontend score accessor, and null scores are generally rendered as no-data rather than coerced to zero.
- The frontend follows several stated UI rules: sticky left columns avoid Radix ScrollArea; model/benchmark sheets are independent; basic skip-link, focus, and reduced-motion affordances are present.
- There is no observed browser-to-ledger write path, and the ledger remains CLI-oriented.
- Local typecheck, existing frontend/ledger tests, and production npm audit are presently green. These should become stronger gates rather than be discarded.

## Audit limitations and confidence

- No live official source, deployed environment, cloud account, browser session, credential, or CI run was accessed. Findings therefore distinguish confirmed local data-flow/integrity defects from follow-up network hardening.
- The security review was repository-scoped and partial: it deeply traced the trust boundary and ran bounded offline reproductions, not an exhaustive dynamic test of every adapter or dependency.
- The ignored local export/database were inspected only read-only. Counts in this report describe that local artifact and should not be treated as official benchmark facts.
- No remediation was implemented in this audit. All priorities are evidence-backed recommendations, not claims that the associated fixes are already complete.

## Orchestration closeout

| Lane | Scope | Result used in this report |
| --- | --- | --- |
| Codex parent | Scope control, evidence reconciliation, test/build verification, final priority/risk assessment | Accepted only findings independently verified against source or bounded validation. |
| Ledger-trust reviewer | Ingestion policy, adapters, immutability, alias/review/export correctness | Accepted after parent source review; supplied the majority of P0/P1 data-integrity evidence. |
| Frontend reviewer | Data-mode behavior, ranking semantics, provenance, accessibility, performance | Accepted after parent source/behavior review. |
| Security reviewers | Storage/CLI and network/trust-boundary validation | Four formal confirmed findings: derived TauBench claim (high), snapshot prefix collision (medium), bulk auto-verification (medium), and URL secret output (low). Redirect/body-size items retained as non-overstated hardening follow-up. |
| Cline / GLM-5.2 | UI audit attempt at requested `xhigh` effort | Rejected as evidence: headless approval prevented source access and no valid result was returned. |
| Kilo / Tencent Hy3 | CI/release audit attempt at requested High reasoning | Rejected as evidence: noninteractive permission controls prevented source access. |
| CommandCode / DeepSeek V4 Pro | Architecture/integration review at observed `/effort max` | Used only as an advisory checklist. It launched broad internal exploration and wrote a plan outside the repository; all adopted statements were independently rechecked. |
| Antigravity / Muse | Premium validation / creative alternative routes | Not assigned: Antigravity was not locally callable; Muse had no unique coverage sufficient to justify its observed high overhead. |

The next engineering task should be Phase 0 containment plus a narrowly scoped design decision for publishability and reproducible Official artifacts. It should not begin with visual refinement or leaderboard tuning.
