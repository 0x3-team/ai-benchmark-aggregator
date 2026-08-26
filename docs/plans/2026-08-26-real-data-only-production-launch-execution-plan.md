# Agent execution plan v2 — real-data-only production launch

> **Checkpoint note (2026-08-26):** This file preserves the approved execution
> baseline and its original forecasts. Work was subsequently executed and then
> stopped for local continuation. Current PR heads, accepted evidence, review
> findings, changed source conclusions, and remaining blockers are recorded in
> [`docs/handover/2026-08-26-real-data-only-launch-local-continuation.md`](../handover/2026-08-26-real-data-only-launch-local-continuation.md).

**Date:** 2026-08-26 · **Base:** `main @ 3bffe66` · **Supersedes:** v1 (2026-08-26)
**User directives applied:** no demo or synthetic data anywhere · launch = production with real, source-backed, current data · pipelines must be exercised and proven live · plan only (no tasks launched yet) · **the user reviews and merges every PR**.

---

## 1. What the directives change

1. **Launch = the first governed Official release.** There is no interim beta. The public site goes live only when real claims flow: certified sources → snapshots → claims → review → export → digest-pinned artifact → deploy. Everything else (UX, headers, deploy pipeline) is built in parallel but is not the launch gate.
2. **The synthetic dataset is deleted, not relabeled.** `src/data/scores.json` + `models.json` (486 fictional-or-scraped models, 976 scores) leave the runtime. The immutable `DatasetProvider`/`getValue` boundary stays (it is load-bearing in tests and architecture); the UI becomes single-source Official with the existing "awaiting publication" empty state until the artifact exists. Tests keep their own fixtures (`testFixtures.ts`, scale fixtures) — those never render to users.
3. **The data machine is the critical path**, so it gets the strongest models and the most parallel lanes: live transport, runner, certifications for *every structured source that passes terms review* (not just 3), REL-05, identity resolution, and an explicit pipeline-validation stage with receipts.
4. **"Most current info" is engineered, not assumed:** every certified source gets a freshness check at capture using a publisher-provided timestamp or a timestamped immutable revision. An opaque ETag or untimestamped revision cannot prove age and yields `freshness=unknown`. Every claim carries its capture date in the UI, and a scheduled re-ingest keeps data moving after launch. Historically frozen sources are labeled with their publisher-provided last-update date rather than silently presented as current.

### Honest coverage forecast (set expectations before approving)

"Everything real" launches with what certifiable sources actually publish. From the 23 active registry routes, the realistically certifiable-in-two-weeks portfolio is structured-data sources:

| Source | Category | What it yields |
| --- | --- | --- |
| SWE-bench Verified (commit-pinned JSON) | coding/agentic | frontier + open models, well maintained |
| BigCodeBench (Parquet) | coding | broad open-model coverage |
| MTEB (HF datasets-server) | embeddings | large but a *different model class* — needs its own UI category |
| GAIA (HF datasets-server) | agentic | agent systems |
| Aider Polyglot (GitHub YAML) | coding | frontier + open models, frequently updated |
| Terminal-Bench (HTML table — only if its structure proves stable) | agentic | frontier models |
| HF Open LLM Leaderboard v2 family (~8 routes, datasets-server) | knowledge/math/reasoning | huge open-model coverage, **but the leaderboard is frozen — include only with a visible "last updated" label** (decision ND2) |
| Vendor-reported slice (system/model cards, new adapter) | knowledge/math/coding | the frontier numbers users actually search for (decision ND3) |

Expected launch shape: **≈40–150 models with ≥1 real score across 8–14 benchmarks**, strong in coding/agentic, thin in chat/vision. Every number source-backed with evidence disclosures — a smaller but honest product. Coverage then compounds weekly via the runner + new certifications. If that shape is unacceptable for launch, the lever is ND3 (vendor-reported slice) and launch-gate ND1, not synthetic filler.

---

## 2. New decisions (defaults pre-set so agents never stall; change any in one reply)

| # | Decision | Default |
| --- | --- | --- |
| ND1 | Launch gate | ≥4 certified sources across ≥3 categories, ≥40 models with ≥1 real score, all freshness receipts ≤7 days old at deploy. Launch as soon as the gate is met, not when the backlog is empty. |
| ND2 | Frozen-source policy (OLL v2 family) | Include only when a publisher-provided timestamp or timestamped immutable revision supports a per-source "source last updated YYYY-MM-DD" label in the benchmark sheet and manifest; always exclude it from any "current" claim. If that timestamp evidence is absent, mark freshness unknown and exclude the source from freshness-qualified launch coverage. |
| ND3 | Vendor-reported slice at launch | **Yes.** New `vendor_reported` officialness class (ADR-011): snapshot the vendor's own system/model card (PDF/HTML), extract exact reported values with typed evidence, distinct UI badge. Launch slice: top ~10 frontier models × their reported GPQA/SWE-bench/AIME-class numbers. This is real, source-backed, and current — it is a policy widening, not a trust-boundary breach. |
| ND4 | Pre-launch deploy | No public deploy until the artifact merges. (The stale 421-byte page at `benchmark.0x3.dev` gets replaced at launch; if you want it blanked sooner, say so — 5-minute human action.) |
| ND5 | Demo removal semantics | Delete `scores.json`/`models.json` and the Demo toggle from the UI; keep the dual-mode dataset boundary internally (Official-or-awaiting), keep test fixtures for CI. `export.sample.json` remains test-only. |
| ND6 | Review cadence (you merge every PR) | Two daily merge windows (start/end of your day). Lanes are batched into **~13 PRs total** with a one-paragraph review guide each; the timeline below assumes windows actually happen — each skipped day slips the tail 1:1. |

Carried over from v1 with governance clarification: ranking threshold ≥60% coverage with visible caption, hide zero-score models by default, Cloudflare Pages + wrangler deploy, GitHub-Actions runner with private `benchmark-ledger-data` repo for snapshots/checkpoints, CSP/HSTS sequencing, and registry retirement of aggregator routes. Before the release PR can merge, an independently supplied append-only REL-05 authorization must pin the exact artifact ID, digest, policy, signer, timestamp, and frontend build. Withdrawal requires an append-only revocation decision naming the artifact and reason, an explicit withdrawn frontend state, and then cache invalidation or redeployment; a Git revert alone is not a withdrawal record.

---

## 3. Human checklist (unchanged ≈45 min, plus your merge windows)

| # | Action | Gates |
| --- | --- | --- |
| H1 | Approve this plan (with any ND overrides) | everything |
| H2 | Cloudflare token + account ID as Actions secrets; confirm DNS | launch deploy only |
| H3 | Branch protection (require `Verify` + review); read the 3 Dependabot alerts and paste them (agents draft dispositions) | merge train |
| H4 | Create private repo `0x3-team/benchmark-ledger-data`; add `LEDGER_DATA_TOKEN` secret | runner (Wave 2) |
| H5 | Security sign-off: pinned-transport PR | first live byte |
| H6 | Create and verify the append-only REL-05 authorization for the exact first artifact before approving its release PR | launch |
| H7 | Daily merge windows per ND6 | overall pace |

---

## 4. Lanes and PR batches (≈24 tasks → 13 PRs; you review each once)

Model tiers: **CHEAP** = gpt-5.6-luna / grok-4.5 · **STD** = gpt-5.6-terra / grok-4.6 · **STRONG** = gpt-5.6-sol (high reasoning). All subscription-billed. Every task: isolated machine, fresh checkout, lane-scoped file list, repo gates green locally, no secrets, screenshots for UI, "pick the decision-sheet default and continue" rule. I inspect every diff and rerun decisive checks before it ever reaches your merge queue.

### Track 1 — Data machine (critical path)

| PR | Lane / tasks | Tier | Contents | Review focus for you |
| --- | --- | --- | --- | --- |
| **P1** | Transport (T-J1) | STRONG | `live_transport.py`: single-resolve → public-IP assert → pinned-IP TLS connect verified against hostname → no redirects → streamed byte cap. Adversarial tests (rebind, smuggle, oversize, non-global IP, TLS mismatch). Default runtime still refuses network. | **Sign-off H5.** Check: no default-path change; tests cover the 5 adversarial cases. |
| **P2** | REL-05 + ADR-011 (T-K1..K3) | STRONG→STD stacked | Release-authorization record (digest pinned outside artifact), artifact builder from eligible feed, offline verifier extension, dormant v2 parser activation behind the record, tamper tests. ADR-011 vendor-reported class. | Digest pinning location; tamper test flips UI to unavailable. |
| **P3** | Runner (T-R1) | STD | Scheduled workflow: restore data repo → migrate check → `ingest` → DATA-10 checkpoint → push snapshots/checkpoints → failure opens issue. | Secrets only from repo config; no ingest on PRs. |
| **P4** | Certifications A (T-S1..S3) | STRONG | BigCodeBench, SWE-bench Verified, MTEB: terms citation, source-revision certification decision docs, URL allowlists + byte bounds, fixture rehearsals, admission dry-run receipts. | Terms quotes are verbatim + dated; bounds match file sizes. |
| **P5** | Certifications B (T-S4..S8) | STD | GAIA, Aider Polyglot, OLL family (per ND2, with last-updated labels), Terminal-Bench only if fixture proves table stability. | Same shape as P4. |
| **P6** | Vendor-reported slice (T-S9, per ND3) | STRONG | Model-card adapter (PDF/HTML snapshot → exact lexeme extraction → typed evidence), certification docs for ~10 frontier vendors' cards, `vendor_reported` class wiring. | This is the policy widening — check the badge/labeling contract. |
| **P7** | Identity (T-N1..N2) | STD | Exact HF/OpenRouter ID auto-accept into aliases via existing `review map-model` path; review-queue CSV for the rest; enrichment for models the launch cohort covers. | No silent merges; needs_review preserved. |
| **P8** | Pipeline validation receipts (T-P1..P3) | STD | On disposable DBs: live capture rehearsal per certified source (via granted transport), **idempotency proof** (second run inserts 0), coverage census receipt, freshness receipts (source update time vs capture time), evidence re-resolution spot checks. Committed under `docs/receipts/`. | This is your "pipelines actually work" evidence — read it. |

### Track 2 — Frontend truth + launch shell (parallel, never the gate)

| PR | Lane / tasks | Tier | Contents |
| --- | --- | --- | --- |
| **P9** | Real-only refactor (T-D2) | STRONG | Delete synthetic jsons + Demo toggle per ND5; single Official-or-awaiting mode; awaiting state copy; tests migrated to fixtures; docstring/README truth pass. |
| **P10** | Ranking + defaults (T-E1) stacked on P9 | STD | ≥60%-coverage ranking with caption, hide zero-score default + toggle, sane default sort; embeddings (MTEB) as separate model-class category so apples stay with apples. |
| **P11** | Permalinks (T-F1) stacked on P10 | STD | URL-encoded view state, fail-closed parsing, browser-proof screenshots. |
| **P12** | Shell + headers + hygiene (T-A1, T-B1, T-C1) | CHEAP/STD | Cruft removal (`commit.sh`/`commit.py`), pre-commit fix (`debug-logger`→`debug-statements`), ledger root stubs relocated; meta/OG/favicon; enforcing CSP + staged HSTS; pages-static verifier updated. |
| **P13** | Deploy + monitoring (T-G1, T-B2) | STD | Wrangler deploy workflow gated on `Verify`, smoke matrix, rollback note, smoke-cron issue-on-failure, Web Analytics snippet (post-H2). Registry retirements (D8) ride along here or in P5. |

Research (no PR): licensing memo (T-I1, CHEAP) feeding P4–P6 terms citations; delivered as a doc for your read.

---

## 5. Pipeline validation — how "our system has the most current up-to-date info" gets proven, not claimed

1. **Fixture truth (exists):** every adapter already has offline fixture tests; CI enforces them.
2. **Live rehearsal per source (new, P8):** one governed capture on a disposable DB per certified source; receipt records URL, revision, bytes, content hash, HTTP metadata, and the extracted claim count.
3. **Idempotency proof (new):** immediate second ingest of the same snapshot must insert zero claims — receipt committed.
4. **Freshness receipt (new):** compare capture time only with a publisher-provided timestamp such as `Last-Modified` or a timestamped immutable commit or dataset revision. Treat opaque ETags and untimestamped revisions as `freshness=unknown`. Frozen sources use the exact publisher date and never satisfy the current-source launch gate.
5. **Evidence re-resolution (exists, spot-checked in P8):** sampled claims re-resolved from immutable snapshot bytes must reproduce the exact raw lexemes.
6. **Continuous:** the runner re-ingests on schedule (daily default), the coverage census runs weekly in CI, and a source that fails N=3 consecutive captures opens an issue automatically. Post-launch, the discovery engine's live connector leg (currently fixture-only) is the first expansion item so new sources/models surface as quarantined candidates instead of hand-edits.

---

## 6. Timeline (assumes daily merge windows; slips 1:1 with skipped windows)

| Day | Milestone |
| --- | --- |
| 0 | Plan approved; Wave 1 launches: P1, P2, P4, P9, P12 lanes start in parallel (+ licensing memo) |
| 1–2 | P1 (transport) + P2 (REL-05) + P9 (real-only) PRs up; **your merge window 1–2**; H5 transport sign-off |
| 2–4 | P3 runner, P5/P6 certifications, P10/P11 UX, P13 deploy pipeline up; merge windows 3–4 |
| 4–6 | P7 identity + P8 live rehearsals run against certified sources; receipts committed |
| 6–8 | Real captures → review queue (agents draft dispositions; you approve batches) → export → **first artifact PR** |
| 8–12 | **H6 authorization verified, then release PR approval**: deploy, smoke matrix on `benchmark.0x3.dev`, HSTS second deploy, announce |
| 12+ | Weekly: +1–2 new certified sources, discovery live connectors, review-queue burn-down, coverage census in CI |

Critical path: P1 → (P3, P4) → P8 → captures → P2's builder → H6. Frontend track has ~4 days of slack; it can never delay launch.

---

## 7. Standing rules for every task (embedded in each prompt)

Same as v1 §5, plus: **no synthetic, mock, fallback, or derived data may be introduced anywhere in runtime paths** — test fixtures live under `tests`/`testFixtures` only; any agent that cannot complete with real inputs stops and reports rather than fabricating. The repository owner or an operator explicitly authorized by the owner may merge ordinary code PRs after required review and CI. The first release remains blocked until the independent REL-05 authorization is recorded and verified against the exact artifact and frontend build.
