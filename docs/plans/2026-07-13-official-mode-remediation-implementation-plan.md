# Official-Mode Trust Remediation — Implementation Plan

## Planner metadata

| Field | Value |
| --- | --- |
| Repository | `/srv/hermes/development/ai-benchmark-aggregator` |
| Branch | `main` |
| Date | 2026-07-13 |
| Planning mode | Full worker run; read-only planning only |
| Primary input | [Comprehensive project audit](../audits/2026-07-13-comprehensive-project-audit.md) |
| Routing input | (internal, not tracked) |
| Product surfaces | Python claim ledger and immutable snapshots; deterministic Official feed; React Official-mode UX; CI/release/operator workflow |
| Planning workers | Ledger/data-contract lens, frontend trust-UX lens, release/QA lens |
| External research | None requested or needed. The audit and repository are the evidence source. |
| Implementation status | **Not started.** This artifact authorizes no code, data, source ingestion, deployment, package update, or commit by itself. |

## Executive goal

Make Official mode safe to re-enable by turning the ledger into a fail-closed store of verbatim, source-backed claims; producing one deterministic, provenance-complete value per display identity; and rendering that feed in a React UI that cannot imply more certainty, coverage, or metadata than the feed provides.

The target release is not “a dashboard with scores.” It is a reproducible, operator-auditable path from an approved source revision to a clearly qualified Official display. Demo mode remains available and visibly synthetic throughout the program.

## Source-of-truth contract

| Contract field | Decision / requirement |
| --- | --- |
| Intent | Publish only source-backed benchmark claims, never locally calculated benchmark results. |
| Current behavior | The audit found fake/mock/fallback/blog/discovery/derived paths, destructive source seeding, non-deterministic cell selection, a stale mode switch, and an ignored build artifact. |
| Expected outcome | Each Official display cell is a deterministic projection of one immutable raw claim whose approved source revision, snapshot bytes, evidence location, identity dimensions, and publication decision are all present and valid. |
| Truth owner | The ledger database plus immutable snapshot storage; the export is a versioned read model. React is a consumer only. |
| Contract boundary | `OfficialSource revision → source snapshot → raw claim + validation/review decision → versioned export + manifest → frontend parser → rendered Official UI`. UI ranking is presentation-only and is never written back to the ledger. |
| Displaced path | Active fake/mock/fallback/blog/discovery/derived adapters; destructive `seed-registry`; `review auto-verify-matched` promotion; unordered all-claims export; module-global data switching; ignored static export dependency. |
| Cutover | Keep Official unavailable until the strict feed gate passes. Then ship a versioned, content-hashed approved artifact and enable UI consumption behind its availability state. |
| Acceptance evidence | Offline fixture/adversarial tests, migration/reseed survival proof, schema/provenance/unique-cell export report, fresh-archive build, browser-mode switch evidence, and release rehearsal receipt. |
| Evidence lane | Codex parent reviews source/DB/export/UI evidence; model outputs are advisory until independently checked. |
| Kill criteria | Any publishable claim that is derived, lacks a verbatim evidence match, uses an unapproved source/revision, has ambiguous identity, has unresolved conflict, or lacks provenance immediately keeps Official unavailable. |
| Forbidden moves | Do not run benchmarks; do not recalculate/store a score as an official claim; do not rewrite/delete historical claims/snapshots; do not make CI ingest live sources; do not present Demo or a fallback as Official; do not deploy paid infrastructure. |

### Required policy decisions before product changes

These decisions block implementation tasks that depend on them; they must be recorded in an ADR/runbook with executable examples.

1. **Publication status:** recommended initial default is an explicit human-approved publication decision, not merely `parser_verified`, until certified adapters are proven. The owner may choose another policy only if it is encoded and visibly communicated.
2. **Source eligibility:** define approved source classes and the exact source/revision approval workflow. O0 articles, vendor blogs, newsletters, social posts, mock/fallback data, and discovery metadata are never official result sources.
3. **Display identity:** define one display metric, split, setting/configuration, and evaluation version per benchmark for the MVP. Do not make the UI silently choose among dimensions.
4. **Conflict behavior:** recommended default is strict export failure plus a machine-readable conflict report, never “last row wins.”
5. **Artifact ownership:** choose a tracked schema-valid unavailable fixture for builds plus an immutable release artifact for real publication. Decide who approves and retains each release artifact.
6. **Legacy retention:** existing claims/snapshots remain queryable but are quarantined/unpublished by a new append-only assessment; they are not overwritten or deleted.

## Native planning superiority

| Field | Plan commitment |
| --- | --- |
| Codex Native baseline risk | A generic roadmap would list audit fixes without enforcing their data-contract dependency, executable exit gates, or safe model routing. |
| What this plan adds | A source-of-truth contract, policy blockers, task-level model/subagent assignments, telemetry receipts, strict cutover/rollback rules, and target-perspective evidence. |
| User-specific context used | Repository-specific AGENTS rules, the audit’s P0–P3 evidence, known harness access/telemetry behavior, and the user’s requirement to route every task to a relevant model and subagent. |
| Superiority score target | 5/5: durable handoff, evidence-backed task routing, explicit decision gates, and release criteria. |
| Proof artifacts | This plan; ADR/runbook decisions; migration/reseed evidence; export contract report; CI clean-archive artifact; browser/a11y/performance evidence; Local Model Guideline Ledger entries. |

## Orchestration decision and closeout

| Field | Decision |
| --- | --- |
| Mode | Full worker run |
| Worker count | 3 distinct planning workers |
| Decision reason | Ledger truth/migration, frontend trust UX, and delivery/QA each require different evidence and are independently planable. |
| Worker scopes | Ledger data contract and migration; React feed/UX/ranking/provenance; CI/release/security/reproducibility. |
| Results accepted | All three were accepted after parent reconciliation; no worker changed files. Their model self-reported token data was `NOT_EMITTED`, so no synthetic cost/token total is asserted. |
| Workers skipped | Muse was not needed for a core planning gap; Antigravity is not locally callable. Both remain conditional execution routes below. |
| Visible thread | Not used: this is a single parent-owned implementation handoff, not a user-managed long-lived lane. |
| Background browser lane | Not needed during planning: no deployed/staging target or external reference was supplied. It becomes required for release validation once a valid artifact and preview target exist. |
| Reconsider trigger | Add a focused follow-up planner if the policy owner cannot resolve publication/artifact/migration decisions, if a source adapter lacks evidence semantics, or if a migration discovery changes the data model materially. |

## Model, subagent, and telemetry operating contract

The named models below are **future task assignments**, not claims that those providers ran this planning pass. Each implementation task has one execution lead and at least one review/validation subagent role. The parent owns integration, accepts/rejects output, and runs the listed evidence checks.

| Route | Best use in this program | Invocation and safety | Native telemetry to retain |
| --- | --- | --- | --- |
| CommandCode / DeepSeek V4 Pro | Data model, migration, claim-admission, export projection, conflict policy, difficult code review | Controlled interactive PTY; confirm `/effort max`; fixed file/finding budget; no autonomous fan-out or writes without a task-specific authorization | Session/harness receipt if emitted; otherwise record `NOT_EMITTED` and retain the prompt-level receipt. |
| Cline / GLM-5.2 | React state architecture, trust/provenance UI, accessibility and visual refinement | `--thinking xhigh`; interactive approval in the checkout. Headless `--auto-approve true` only in a credential-free, OS-level sandbox/read-only snapshot | `--json` `run_result.model`, `usage`, and `aggregateUsage`. |
| Kilo / Tencent HY3 Free | Bounded fixtures, repetitive adapter edits, test scaffolding, CI/docs mechanical work | `--variant high --thinking`; interactive approval preferred. `--dangerously-skip-permissions` only in a disposable credential-free sandbox; never use broad `--auto` in the checkout | `--format json` final session/step token objects and cost; preserve cache counts without double-counting steps. |
| OpenCode / Muse Spark 1.1 | A single bounded alternative for public ranking/provenance wording or conflict UX, if needed | `xhigh`; cap context/cost. Use only if its alternative is materially distinct; technical review remains separate | Native OpenCode usage/cost when emitted plus prompt receipt. |
| Antigravity / Gemini 3.5 Flash High | Browser, visual, accessibility, and difficult edge-case validation | **Conditional:** only after bridge/model/High-setting smoke passes. Until then Codex parent performs validation. | Connected IDE/agent telemetry and browser receipt; otherwise `NOT_EMITTED`. |
| Codex parent | Policy, data integrity adjudication, integration, security and release sign-off | Owns all merge decisions and target evidence | Goal/task receipt plus retained native child telemetry. |

### Mandatory footer for every delegated task

Every task prompt must end with the following request, as required by the guideline ledger:

```text
Before your final answer, provide a USAGE_REPORT with the actual provider/model,
requested and observed reasoning effort, input/output/reasoning/cache token counts,
total tokens, tool-call count, elapsed time, and cost. If your interface cannot see a
field, write NOT_EMITTED; never estimate or invent it.
```

The parent reconciles the report against native harness telemetry. A task is not closed until the reconciled usage (or explicit `NOT_EMITTED` reason), changed files, evidence, validation results, parent decision, and lesson are recorded in the internal routing ledger (not tracked in repo).

## Current-state diagnosis

The audit establishes the following order of risk:

1. The current ledger can publish claims that are not verbatim official source reports, including fake/mock/fallback/discovery/blog/derived paths.
2. `seed-registry` destroys claim/snapshot/run history, while snapshot storage and runner semantics have integrity/reliability defects.
3. Export emits all statuses with no unique-cell selection policy; the frontend chooses final array order through a map overwrite.
4. Official mode can render stale registry data and cannot build reliably from a clean checkout because its static artifact is ignored.
5. The UI ranks sparse or provisional data as global results and cannot expose complete provenance or honest unknown metadata.
6. CI, dependency controls, accessibility/performance evidence, CLI docs, and release safeguards are insufficient to make the repaired pipeline durable.

## Future state

After completion:

- `ingest` only creates a candidate claim from a governed source revision and verbatim raw evidence; publication is fail-closed.
- Registry updates create/retire versioned source records and never delete evidence history.
- A versioned export contains one explicit selection per display identity, a provenance/source manifest, a declared availability/publication policy, and no unsafe/null pseudo-score rows.
- A fresh checkout always builds against a tracked unavailable contract fixture or a verified immutable artifact.
- The UI switches datasets atomically, presents provenance and policy clearly, treats unknown/no-data as unknown/no-data, and qualifies ranking by coverage.
- CI is offline, reproducible, adversarially tested, and gates release on actual artifacts rather than row counts.

## Non-goals

- Building a ledger web UI, running benchmarks, or adding a paid cloud deployment.
- Repairing historical source values in place or deleting legacy evidence.
- Automatically trusting all existing active adapters after a code refactor.
- Adding a broad new component library solely to solve table rendering or tests.
- Making a public “best model” claim without an approved cohort and visible coverage policy.

## Phased task backlog

### Phase 0 — contain risk and lock policy

| ID | Depends on | Work and likely files | Execution lead and required subagents | Acceptance evidence / stop condition |
| --- | --- | --- | --- | --- |
| GOV-01 | — | Write publication, source-tier, identity-dimension, conflict, artifact, and legacy-retention ADR/runbook. Likely `docs/adr/`, `README.md`, `ledger/README.md`, `AGENTS.md` only after approval. | **Lead:** DeepSeek V4 Pro `/effort max` planning/design. **Subagents:** `policy-adversary` (Codex security review), `operator-representative` (Kilo turns examples into fixture cases). | Owner signs a decision table with accepted/rejected claim examples. **Stop:** no schema/export/UI implementation while any of the six policy decisions is unresolved. |
| GOV-02 | GOV-01 | Quarantine unsafe production routes and block Official promotion: fake, mock, fallback, blog, discovery metadata, and derived-score adapters; safe Demo/unavailable behavior. Likely `ledger/app/registry/official_sources.yaml`, adapter registration/policy, frontend availability wiring. | **Lead:** DeepSeek designs boundary; **implementation subagent:** Kilo HY3 High for bounded registry/test edits; **review:** Codex parent. | Offline matrix proves no default `ingest --all` can create a publishable unsafe claim. Official is unavailable/Demo-only until a valid artifact exists. **Rollback:** retain data; revert only the gating change, never re-enable unsafe sources. |
| GOV-03 | GOV-01 | Choose and implement the build baseline: tracked schema-valid unavailable fixture plus explicit immutable release-artifact path; remove dependence on ignored static export. Likely `.gitignore`, `src/data/official.ts`, `src/data/official/`, scripts, workflow. | **Lead:** Cline GLM-5.2 `xhigh` for consumer/build boundary. **Subagents:** Kilo CI fixture scaffolding; DeepSeek contract reviewer. | Fresh `git archive HEAD` path resolves module import and shows unavailable Official state, not sample data. **Stop:** do not add a live-source CI fetch. |
| GOV-04 | GOV-01 | Inventory and preserve existing local evidence before migration: DB/snapshot counts, hashes, source IDs, and restoration plan. New operator runbook/scripts only after design approval. | **Lead:** Codex parent. **Subagents:** DeepSeek migration reviewer; Kilo bounded inventory-script/test helper. | Immutable backup/recovery receipt exists; no task deletes/reseeds a claim-bearing database. **Rollback:** restore verified backup rather than destructive reseed. |

### Phase 1 — repair ledger truth and durability

| ID | Depends on | Work and likely files | Execution lead and required subagents | Acceptance evidence / stop condition |
| --- | --- | --- | --- | --- |
| LDR-01 | GOV-01, GOV-04 | Introduce an explicit migration baseline and append-only domain seams: logical source versus source revision, immutable raw claim, publication/review decision. Likely `ledger/pyproject.toml`, `ledger/app/db/models.py`, `db/engine.py`, new migrations, repositories, tests. | **Lead:** DeepSeek V4 Pro `/effort max`. **Subagents:** `migration-keeper` (Codex parent), Kilo fixture helper. | Copy-DB upgrade, reseed, and `PRAGMA integrity_check` preserve prior runs/snapshots/claims. Legacy records are quarantined by new assessment, not rewritten. |
| LDR-02 | LDR-01 | Replace destructive `seed-registry` with idempotent source-revision upsert/retirement. Likely `registry/seed_loader.py`, `db/repositories.py`, registry tests. | **Lead:** DeepSeek. **Subagent:** Kilo regression-fixture worker. | Same manifest is idempotent; changed source creates a revision; removed source retires; no FK disable/delete path remains. |
| LDR-03 | LDR-01 | Fix snapshot identity and storage: full-digest path/equality, full verification on reuse, atomic write, and safe collision behavior. Likely `storage/local.py`, runner, snapshot tests. | **Lead:** Kilo High for bounded storage/test change. **Review:** DeepSeek plus Codex security reviewer. | Forced same-prefix/different-full-digest fixture cannot share URI; stored bytes hash to persisted hash. |
| LDR-04 | LDR-01, LDR-03 | Make ingestion transaction and dry-run semantics honest: no writes in dry-run, per-source transactions, explicit partial/failure run status, accurate error records. Likely `ingestion/runner.py`, repositories, CLI, tests. | **Lead:** DeepSeek. **Subagent:** Kilo failure-path fixture worker. | Mock partial failure and dry-run tests prove no snapshot/claim/run writes where prohibited and no partial completion is labeled complete. |
| LDR-05 | GOV-01, LDR-01, LDR-02 | Build one central fail-closed admission/evidence resolver. Likely `ingestion/policy.py`, `adapters/base.py`, schemas, runner, tests. | **Lead:** DeepSeek. **Subagents:** `evidence-adversary` (Codex), Kilo rejection-matrix fixtures. | Rejects fake/mock/fallback/blog/discovery/derived data, missing or mismatched evidence, ambiguous mapping, unapproved source/revision/dimensions, and nonnumeric publishable values. Raw source fields stay verbatim. |
| LDR-06 | LDR-05 | Certify or retire adapters one at a time. Start by retiring unsafe active routes; reactivate only with typed evidence extraction and fixture coverage. Includes `fake.py`, `artificial_analysis_api.py`, `lmsys_arena_api.py`, `hf_benchmark_api.py`, `livebench_adapter.py`, `livecodebench_adapter.py`, `taubench_s3.py`, and affected source registry entries. | **Lead:** Kilo High for one bounded adapter/fixture ticket at a time. **Adjudicator:** DeepSeek for source/evidence semantics; **review:** Codex. | Each reactivated adapter copies a source-reported raw score exactly and resolves evidence. TauBench/LiveBench/LiveCodeBench aggregates remain non-claim analytics unless the upstream artifact exposes that exact aggregate. **Stop:** unknown adapter stays inactive. |
| LDR-07 | LDR-01, LDR-05 | Make matching/review ambiguity-safe and append-only. Separate identity mapping from validation/status promotion; restore manual map-model command; retire unsafe bulk auto-verification. Likely `matching/aliases.py`, `db/repositories.py`, `cli.py`, review tests. | **Lead:** DeepSeek. **Subagent:** Kilo CLI/test worker; **review:** Codex security. | Alias collision returns unresolved/null entity; a failed validation cannot become published without a new recorded review decision; manual correction is available and tested. |
| LDR-08 | LDR-05, LDR-07 | Define deterministic feed projection and versioned schema/manifest. Likely `export/official_json.py`, export contracts, tests, frontend shared types. | **Lead:** DeepSeek. **Subagents:** Cline TS contract reviewer; `conflict-fixture` Kilo worker. | Sorted output has one selected numeric eligible cell per `(model, benchmark, metric, split, setting, evaluation version)`; source manifest and provenance are complete; unresolved conflicts produce an explicit export failure/report, not Map-last-wins. |
| LDR-09 | LDR-02–LDR-08 | Reconcile legacy data without mutation: generate inventory/conflict/quarantine report; publish only eligible new projections; document recovery. Likely new CLI/report modules, docs, tests. | **Lead:** DeepSeek rollout design. **Subagents:** Kilo report fixtures; Codex parent approves operator steps. | Existing claims/snapshots remain queryable; old invalid/derived/provisional records are omitted from the published view with an explainable report. |

### Phase 2 — make the feed consumable and the UI honest

| ID | Depends on | Work and likely files | Execution lead and required subagents | Acceptance evidence / stop condition |
| --- | --- | --- | --- | --- |
| FEED-01 | GOV-03, LDR-08 | Implement immutable, versioned artifact preparation and offline CI contract validation. Likely export script/manifest, `.github/workflows/verify.yml`, fixture files, `src/data/official.ts`. | **Lead:** Kilo High for CI/script/fixture mechanics. **Subagents:** DeepSeek export reviewer; Cline frontend consumer reviewer. | Clean archive runs `npm ci`, typecheck, test, and build; artifact digest/schema/provenance report passes offline. CI never ingests live sources. |
| UI-01 | FEED-01 | Replace module-global active data with an immutable React dataset provider/context while retaining `getValue` as the only score accessor. Likely `src/App.tsx`, `src/data/registry.ts`, dependent aggregates/components. | **Lead:** Cline GLM-5.2 `xhigh`. **Subagents:** `react-state-reviewer` (DeepSeek bounded review), Kilo test helper. | Demo→Official and Official→Demo first committed render has matching models, benchmarks, values, and provenance; no component reads raw score arrays. |
| UI-02 | FEED-01 | Add strict frontend feed parser/availability boundary; remove unsafe `as OfficialExport`, false defaults, and silent sample fallback. Likely `src/data/official.ts`, `src/types.ts`, data mode/types/tests. | **Lead:** Cline. **Subagents:** DeepSeek contract review; Kilo malformed-fixture tests. | Invalid schema, duplicate cell, null published value, missing provenance, or unavailable artifact becomes an accessible unavailable state, never fake Official data. |
| UI-03 | UI-01, UI-02 | Build clear data-mode/trust UX: availability, timestamp/policy, atomic resets, focus restoration, truthful status language. Likely `App.tsx`, `Header.tsx`, mode controls. | **Lead:** Cline. **Subagents:** Muse Spark 1.1 supplies one capped alternative for trust wording only; Codex chooses/reviews. | UI does not use a green/pulsing cue to imply every claim is verified; keyboard users receive coherent state on mode changes. |
| UI-04 | UI-01, UI-02 | Add reusable claim provenance/evidence surface and source manifest consumption. Likely new `ClaimEvidence` component plus `ScoreTable.tsx`, `ScoreHeatmap.tsx`, `ModelDetail.tsx`, `BenchmarkCard.tsx`, `Header.tsx`. | **Lead:** Cline. **Subagents:** Kilo fixture/test worker; Antigravity/Gemini High only if bridge is later proven for visual validation. | Every displayed Official score exposes raw value, source/URL, claim ID, snapshot ID, evidence location, retrieval date, and policy via keyboard-accessible UI. No empty anchors or nested sheets. |
| UI-05 | UI-01, GOV-01 | Implement coverage-aware global/category ranking and invalid-sort repair. Likely `src/lib/aggregate.ts`, `App.tsx`, `ScoreTable.tsx`, `CategoryLeaders.tsx`, `ScoreHeatmap.tsx`, detail/comparison components. | **Lead:** Cline implementation. **Subagents:** DeepSeek cohort-logic review; Muse optional alternative disclosure design; Codex decides policy. | A sparse model cannot receive an undisclosed global/category rank; `n/total`, eligibility, and an unranked reason are visible. Category changes clear/repair a hidden sort. |
| UI-06 | UI-02, UI-05 | Make unknown model metadata and no-data semantics end-to-end honest. Likely types, filters, details/comparison, chart components including `RadarChart.tsx`. | **Lead:** Cline. **Subagent:** Kilo adversarial null/unknown fixture worker. | No null becomes zero/rank/SOTA; unknown specifications never display as `0k`, false, or text-only facts and cannot drive unsupported filters. |
| UI-07 | UI-01, UI-05, UI-06 | Profile and make the large table accessible at realistic feed scale; choose pagination or accessible virtualization without violating sticky-column constraints. Likely `ScoreTable.tsx`, `App.tsx`, lazy loading/build config. | **Lead:** Cline. **Subagents:** `performance-fixture` Kilo worker; Antigravity browser trace conditional, Codex fallback. | Agreed render/filter/sort and bundle budgets are measured against approved data; no unapproved Vite size warning; sticky left columns use plain `overflow-x-auto`, never Radix ScrollArea. |
| UI-08 | UI-01–UI-07 | Add unit/component/browser coverage for mode switching, parser rejection, provenance, ranks, nulls, focus, keyboard/screen reader, responsive scale. Likely test config, `src/**/*.test.tsx`, browser setup after approval. | **Lead:** Kilo High for scaffolding/fixtures. **Subagents:** Cline interaction-test author; Codex/Antigravity target validation. | Tests cover actual App/component behavior, not utilities alone; browser smoke includes valid/invalid Official artifact, desktop/mobile, console health, and evidence links. |

### Phase 3 — resilience, reproducibility, and release operation

| ID | Depends on | Work and likely files | Execution lead and required subagents | Acceptance evidence / stop condition |
| --- | --- | --- | --- | --- |
| REL-01 | LDR-04, LDR-05 | Centralize outbound-fetch limits and parser/resource controls: HTTPS/host/IP redirect policy, timeouts, byte ceilings, content-type/max-key limits. Likely shared HTTP helper, adapters, settings, mock tests. | **Lead:** DeepSeek design. **Subagents:** Kilo mock/adversarial fixtures; Codex security reviewer. | Redirect to private/link-local, oversized/malformed body, unexpected content type, and oversized config are rejected in offline tests. No live source access in CI. |
| REL-02 | FEED-01, UI-08 | Make CI and dependency resolution reproducible: Python lock/constraints policy, semantic export gate, clean-archive job, action pinning/least privilege, offline supply-chain checks. Likely `.github/workflows/verify.yml`, `ledger/pyproject.toml`, lock/constraint assets, package policy. | **Lead:** Kilo High for bounded YAML/docs mechanics. **Subagents:** DeepSeek CI design reviewer; Codex security release owner. | Locked/reviewed Python install, `npm ci`, explicit workflow permissions, reviewed action refs, and semantic artifact checks all pass. Do not weaken a gate to ship. |
| REL-03 | LDR-01–LDR-09, UI-01–UI-08 | Update operator workflow, CLI/docs/ADRs, migrations and secret-safe output. Likely `README.md`, `ledger/README.md`, `AGENTS.md`, ADRs, `cli.py`, test/docs. | **Lead:** Kilo High for synchronized docs and CLI tests. **Subagents:** DeepSeek migration/runbook reviewer; Cline trust-copy review. | Docs match `--help`; no unsafe quick-start order; `init-db` redacts credential-bearing URLs; future schema changes use the approved migration path. |
| REL-04 | REL-01–REL-03 | Run an offline release rehearsal against copied fixtures/artifacts: backup, migrate, reseed, ingest dry-run, strict export, clean build, frontend/browser evidence, restoration drill. | **Lead:** Codex parent. **Subagents:** `release-scribe` Kilo; DeepSeek go/no-go reviewer; Antigravity/Gemini High browser validation only if bridge is proven. | Signed release receipt contains artifact hash, source/revision policy, test outputs, browser/a11y/performance evidence, rollback result, and all delegated telemetry. **Stop:** no Official release with an unresolved critical/P0 item. |
| REL-05 | REL-04 | Re-enable Official publication only through a documented approval gate; otherwise retain Demo/unavailable mode. | **Lead:** Codex parent and policy owner. **Subagents:** DeepSeek final integrity review; Cline final UI trust review. | All release gates below pass simultaneously and the policy owner approves the artifact. **Rollback:** select last known-good immutable artifact or set Official unavailable; never mutate claims to fix display. |

## Adapter certification task template

`LDR-06` must be broken into one small ticket per source/adaptor; a batch “fix all adapters” task is forbidden. Every ticket carries:

1. Source ID/revision and an approved canonical source URL.
2. Source classification and explicit proof it is not a fallback, vendor blog, discovery record, or derived metric.
3. Raw fixture bytes saved before extraction.
4. Verbatim `model_raw`, `benchmark_raw`, `score_raw`, identity dimensions, and an evidence locator that re-resolves in the raw snapshot.
5. An uncertainty path that yields `model_entity_id = null` and `needs_review` rather than a best guess.
6. Adapter fixture, invalid-input fixture, idempotency fixture, and publishability fixture.
7. Parent acceptance plus reconciled model telemetry.

## Cross-phase acceptance gates

### Ledger and artifact gate

- Every published score has approved source/revision, immutable snapshot, raw fields, exact evidence match, valid identity dimensions, a publishable decision, and required provenance.
- No fake, mock, fallback, blog, discovery, derived, ambiguous, failed-validation, unresolved-conflict, or null pseudo-score enters a published export.
- Reseeding preserves source/snapshot/claim/run history; migrations are reversible only through recovery, never destructive deletion.
- Snapshot hash, storage URI, and bytes agree; dry-run causes no durable side effect; partial source failure is visible.
- Export is schema-valid, sorted, unique by display identity, deterministic across repeated runs, and accompanied by a manifest/conflict report.

### Frontend gate

- Demo is visibly synthetic; unavailable Official data is visibly unavailable, never silently substituted.
- Switching modes is atomic on the first render under strict/component testing.
- `getValue(modelId, benchmarkId)` remains the sole score accessor; no UI calculation is stored as an official claim.
- All Official scores expose evidence; no empty source links, invented metadata, or hidden status ambiguity remain.
- No-data remains no-data in tables, charts, details, comparisons, ranks, SOTA detection, and filters.
- Global/category rankings show their eligible cohort/coverage and do not promote sparse results as global leaders.

### Release gate

- A clean archive/fresh checkout resolves the frontend artifact and passes install, typecheck, test, and build.
- CI performs only offline fixtures/artifact checks; it never live-ingests benchmark sources.
- Python and Node dependency paths are reproducible and reviewed; workflow permissions/action refs meet project policy.
- Browser, keyboard, screen-reader, responsive, and realistic-data performance evidence exists for the exact approved artifact.
- Operator runbook, CLI help, migration/backup/recovery evidence, artifact hash, approval decision, and every delegated `USAGE_REPORT` are retained.

## Validation plan

| Layer | Required checks |
| --- | --- |
| Ledger unit/fixture | `cd ledger && pytest -q`; source-class/rejection matrix; exact-evidence resolution; no derived score; adapter certification fixtures; alias collision; failed-validation promotion; snapshot collision; dry-run/no-write; partial failure; reseed survival. |
| Migration/integration | Copy SQLite fixture; backup/hash; migrate; reseed; query legacy claims/snapshots/runs; `PRAGMA integrity_check`; restoration drill. |
| Export | Schema and semantic validator; repeat export comparison; unique-cell/conflict report; required provenance manifest; only eligible finite numeric published values. |
| Frontend unit/component | `npm run typecheck`, `npm run test`, feed parser, App first-render mode switch, unavailable state, provenance, coverage rank, unknown/null semantics, sort repair, focus/keyboard behavior. |
| Fresh build | Archive/fresh directory: `npm ci && npm run typecheck && npm run test && npm run build`; confirm no ignored local export is required. |
| Browser/a11y/performance | Valid and invalid artifact smoke; desktop/mobile screenshots; keyboard and screen-reader pass; console health; realistic artifact rendering/filter/sort trace; agreed bundle/render budget. |
| Security/release | Mock redirect/private-address/oversized-body tests; redacted CLI URL test; CI permission/action/dependency checks; offline release rehearsal. |

## Risks, dependencies, and stop conditions

| Risk / open question | Handling |
| --- | --- |
| Policy owner does not choose publication eligibility or artifact owner | Block GOV-01 descendants; retain Demo/unavailable mode. Do not substitute an implicit policy. |
| Existing source data cannot provide a verbatim official score | Keep that adapter inactive or model it as non-claim analytics; do not aggregate locally. |
| Migration discovers unmodelled legacy state | Pause migration, preserve backup, add a focused schema/recovery plan; never use `seed-registry` deletion as a shortcut. |
| Cline/Kilo headless permission flags are requested for a project write | Decline unless the work runs in an approved sandbox. Use interactive approval in the checkout. |
| Antigravity bridge is still unavailable | Do not claim browser/visual validation by that lane; use Codex-owned test evidence and mark the limitation. |
| Performance budget is unknown | Profile a valid realistic artifact first, then record the agreed threshold before enforcing it in CI. |
| A task’s model reports token usage incompletely | Record prompt-level `NOT_EMITTED`, retain native telemetry when available, and do not estimate. This is a telemetry gap, not permission to omit the task receipt. |

## Implementation orchestrator handoff

### Recommended first slice

Create a new implementation goal for **GOV-01 through GOV-04 only**. It is the smallest safe starting slice because it fixes no source values and establishes the policy, safe default, clean-build baseline, and backup evidence that every later code change depends on.

### Required phase order

`GOV → LDR truth/migration → deterministic feed/artifact → React trust UI → resilience/CI/docs → offline release rehearsal → explicit publication approval`.

Do not reorder this to start with visual leaderboard work. The UI must consume a valid feed contract before it can truthfully render official rankings or provenance.

### Likely change areas

- Ledger: `ledger/app/ingestion/`, `registry/`, `matching/`, `db/`, `storage/`, `export/`, `cli.py`, tests, migration assets, source registry.
- Frontend: `src/data/`, `src/App.tsx`, `src/lib/aggregate.ts`, table/chart/detail/header components, test configuration and tests.
- Delivery: `.github/workflows/verify.yml`, dependency constraints/lock policy, artifact scripts/fixtures, README/ledger README/ADRs/runbooks.

### Allowed and disallowed changes

- **Allowed after slice-specific approval:** small, tested source-code/config/test/docs changes that implement the named task and preserve immutable evidence.
- **Disallowed:** live ingestion, paid deployment, benchmark execution, destructive reseeding, rewrites/deletes of claims/snapshots, silent source fallback, automatic dependency updates, or committing generated production data without the selected artifact policy.

### Required implementation skills and tools

- DeepSeek-route tasks: architecture/migration design plus parent code review.
- Cline-route tasks: UI implementation with interactive approval and `xhigh` reasoning.
- Kilo-route tasks: bounded fixtures/docs/CI with interactive approval and High reasoning.
- Security tasks: mock-only validation; no live endpoints.
- Browser/a11y tasks: a callable browser bridge or approved local browser runner; otherwise report the missing target evidence.

### Questions that block implementation

- The six GOV-01 policy decisions.
- Database migration and backup/restore ownership.
- Real artifact release/approval location and retention.
- Required source certification owner and public status policy.

### Questions that can be resolved during implementation

- Exact migration library/mechanism, provided it supports append-only preservation and a copied-DB rehearsal.
- Pagination versus accessible virtualization, after profiling a valid feed.
- Precise browser performance budget, after initial realistic-data trace.
- Exact component/file extraction for evidence UI, provided independent Sheet roots and `getValue` invariants remain intact.

### Do-not-claim-complete rule

The implementation orchestrator must make the chosen slice its own goal, run its implementation/validation loop, retain telemetry and parent review evidence, and continue until the slice’s acceptance criteria are met or it is explicitly blocked. It must not report a task as verified solely because code compiles or tests pass; it needs target-perspective evidence from the relevant snapshot, DB record, export artifact, rendered UI, CLI output, browser trace, or operator-visible recovery rehearsal.

## Planning closeout

This plan is ready for implementation orchestration once GOV-01 policy decisions are assigned to an owner. It intentionally leaves Official mode unavailable until the stated ledger, artifact, UI, and release gates all pass. No implementation has started.
