# P2 Performance & Operations Handoff — Evidence and Implementation Plan

**Date:** 2026-08-10
**Repository:** `/Users/stevmq/Documents/ai-benchmark-aggregator`
**Branch:** `main` (local worktree, dirtied by prior protected lanes — do not reset/stash/clean)
**Predecessors:** [comprehensive checkpoint audit `2026-08-09`](../audits/2026-08-09-comprehensive-checkpoint-audit.md) and its [remediation plan](../plans/2026-08-09-comprehensive-checkpoint-remediation-plan.md)
**Scope:** Deferred backlog items **6** (ledger scale) and **9** (accessibility/performance), plus the local-only release/withdrawal/rollback rehearsal/runbook gap.

This is an **evidence and implementation-handoff** artifact only. It names exact
symbols/files, provides locally obtainable baseline measurements, and proposes
the smallest safe code/test changes, counters, budgets, dependencies, and
external/product blockers. **No source/config was edited, and no live network,
browser, provider, database, deploy, commit, or push action was run while
producing it.**

---

## 1. Scope of this lane

The four P2 threads that must be measured before optimization acceptance (per
plan deferred items 6, 7 and the audit's "P2 Ledger performance", "P2 Release
operations", "P3 Performance/AT" rows):

1. **Ledger ingestion/reporting N+1** and **repeated evidence
   decoding/resolution** (item 6).
2. **Registry bulk seeding**, **orphan inventory**, **report/review-queue
   paging** (item 6).
3. **Frontend bundle composition** and **ScoreTable 500×42 behavior** (item 9).
4. **Local-only release/withdrawal/rollback rehearsal/runbook gaps** (not
   currently measurable as code; requires governed responsibility).

Everything below names exact files and symbols. Baselines labeled **[measured]**
were obtained by the bounded read-only commands in §7.1 (CPU-only, in-memory,
no DB/network/deploy); predicates labeled **[static]** come from reading
source.

---

## 2. Ledger — N+1 queries

### 2.1 The dominant N+1: eligible-candidate analysis

`ledger/app/export/official_json.py` → `analyze_official_feed_candidates`
(lines 524–561) loops every claim and calls `_eligible_claim(session, claim)`
(lines 360–436). Per claim that function performs **10 DB round-trips**
(counted from the access sites in §2.2 below) before a single verdict. At 10k
claims this is ~100k round-trips. Both the official-feed projection and the
legacy inventory (`legacy_inventory.py:362`) call this per-claim analysis, so
**two separate report paths share the same N+1**.

**Exact DB access sites inside the per-claim path:**
- `official_json.py:299` `session.get(SourceRevisionDecision, ...)`
- `official_json.py:311–316` `_source_provenance`: `session.get(SourceSnapshot)`,
  `session.get(SourceRevisionDecision)` (2nd), `session.get(OfficialSourceRevision)`,
  `session.get(OfficialSourceRow)` (4 gets)
- `:176–177` `_effective_source_revision_decision` → **1** `scalars(select ...)` per revision
- `:367–370` validations → **1** `scalars(select ClaimValidation)` per claim
- `_claim_review_chain` (`repositories.py:725`, via `get_claim_review_projection`
  `:784`) → **1** `scalars(select ClaimReviewDecision)` per claim
- `_claim_publication_chain` (`repositories.py:834`, via
  `get_claim_publication_projection` `:896`) → **1** `scalars(select ClaimPublicationDecision)` per claim
- `:381` `_effective_review` `get(ClaimReviewDecision)`; `:411–412`
  `get(ModelEntity)`, `get(Benchmark)` (3 gets)
- `:299` again inside `_claim_locator_matches_capture_policy` (`:296–302`)

Estimated **~5 SQL `SELECT`s + ~5 identity-map `get`s per claim ≈ 10
round-trips × 10k claims ≈ 100k round-trips**. SQLAlchemy's identity map
deduplicates some `get()` calls when the objects are already loaded, but the
`scalars(select ...)` per-claim queries are **not** deduplicated, so the SQL
statement count is the true N+1.

**Smallest safe change:** factor the candidate analysis to bulk-load the
per-claim fan-out once per run, keyed by claim id, then resolve per claim from
in-memory maps instead of issuing per-claim statements:
- One `select(ClaimReviewDecision)` / `select(ClaimPublicationDecision)` /
  `select(ClaimValidation)` / `select(SourceRevisionDecision)` fanned by the
  full claim-id set (`WHERE result_claim_id IN (...)` chunked), sorted, and
  rebuilt into `{claim_id: chain}` maps.
- Rewrite the chain walkers `_claim_review_chain` / `_claim_publication_chain`
  (`repositories.py`) to accept an optional preloaded `Sequence` instead of
  issuing their own `scalars`; keep the public single-claim function unchanged
  (its current semantics are correct and tested).
- `legacy_inventory.build_legacy_inventory_report` should compute the analysis
  **once** and reuse the preloaded decision/validation maps for its `_claim_record`
  pass (currently `:362` resolves chains, then `:406–414` re-resolves them —
  a second resolution of the same data).

**Rationale for not caching at session level:** SQLAlchemy identity-map caching
already helps `get()`; the win is almost entirely from removing the N
`scalars(select ...)` statements.

### 2.2 Review chain fails closed — preserve it

Both `_claim_review_chain` and `_claim_publication_chain` raise
`ClaimReviewChainError` when the chain is branching/cyclic/invalid
(`repositories.py:725–773`, `:834–885`). Any fanned-out refactor must reproduce
this fail-closed behavior — a batched walker still must detect multiple
leaves / foreign parent / cycle and set the same error string so
`chain_error` display is unchanged.

### 2.3 Reporting inventory report

`ledger/app/reporting/legacy_inventory.py`:
- `build_legacy_inventory_report` (`:341`) loads all claims/snapshots/sources/
  revisions in 4 ordered scans, then per-claim calls `_claim_record` (`:227`),
  which itself calls `get_claim_review_projection` + `get_claim_publication_projection`
  (`:237–238`) — a **second** per-claim chain resolution on top of the analysis
  scan (fixed in 2.1 by reusing the preloaded maps).
- The orphan/omission counting is already O(n) in-memory via `Counter`s — no
  orphan N+1 to fix. **[labeled]** The audit's "orphan accounting is O(n)" is accurate;
  the remaining cost is the repeated projection calls, not a true orphan query loop.

---

## 3. Ledger — repeated evidence decoding/resolution

### 3.1 Evidence resolver seam

`ledger/app/ingestion/admission.py:533–549` `_evidence_record` dispatches on
locator `type` to:
- `_json_record` / `_json_script_record` (`:484`, `:495`) — `decode_json_bytes` each call
- `_csv_record` (`:520`) — re-parses the whole CSV with `csv.DictReader` each call
- `parquet_cell_v1` → `read_parquet_record` (`parquet_cells.py:79`)

`read_parquet_record` **re-opens and re-reads the whole Parquet file on every
call** (`_open(raw_bytes)` at `parquet_cells.py:88`, then `read_row_group`).
Called once per claim during admission (`_evidence_record`) and again per claim
during adapter `validate_claim` (`bigcodebench_parquet.py:188–200`
`read_parquet_record`). For a Parquet snapshot with every claim pointing at the
same bytes, that is the same file decoded **twice per claim**.

**Measurement [measured]** — in-memory 10k-row × 8-col Parquet, pyarrow 18.1.0:
```
single read_parquet_record:   155.8 us   (reopens file + row group)
full-batch iter (all 10k rows): 55.7 ms  →  5.57 us/row  (decode once)
```
Ratio ≈ **28×**. Per-claim re-open is ~156 µs/claim → **~1.56 s of pure decode
for 10k claims** that a single decode pass would do in ~56 ms.

**Smallest safe change — cache one immutable resolver per snapshot:**
Add (in `parquet_cells.py`) a small `ParquetEvidenceResolver` that opens
`pq.ParquetFile` **once** and serves `read(row_group, row_index)` and
`iter()` from the held handle; `_ClaimAdmission` accepts an optional prebuilt
resolver so `resolve_claim_admission` and adapter `validate_claim` reuse the
same open handle/key for the same `raw_bytes.id()` digest. Key the cache by
`(id(raw_bytes), content_sha256)` and scope it to one `run_ingestion` so a
long-lived process never pins snapshot bytes — the deferred plan's wording is
"cache one immutable evidence resolver per snapshot."

Budgets (proposed, seen baseline above):
- `EVIDENCE_DECODE_US_PER_CLAIM`: admit ≤ **60 us/claim** at 10k (current
  ~156 us single-read; ~5.6 us batch). Budget target ≤ **100 us/claim** mean
  including resolver overhead.
- A regression asserting `read_parquet_record` is **not** called more than once
  per distinct snapshot bytes in a fixture run (via an injected-count resolver),
  so the cache is proven, not assumed.

### 3.2 CSV the same shape
`_csv_record` re-decode on every call. If a source uses `csv_cell_v1`, the same
single-parse-per-snapshot resolver applies (`list(csv.DictReader(...))` once,
indexed by `row_index`). Same invariant as Parquet.

---

## 4. Ledger — registry bulk seeding + review-queue paging

### 4.1 Bulk seeding N+1

`ledger/app/registry/seed_loader.py` `_seed_registry_changes` (lines 50–150):
- `repo.upsert_benchmark` / `upsert_model_entity` (`repositories.py:119,:132`)
  do `session.get(Model, id)` then `flush()` — **1 identity get + flush per row**.
- `repo.add_alias` (`repositories.py:145`) does a `scalars(select Alias)` on
  every alias — **1 SELECT per alias**.
- `repo.reconcile_official_source` (`:312`) per source does several selects
  (current-revision lookup, identity checks).

For a large registry (thousands of rows × aliases) this is a true bulk-seeding
N+1. All-or-nothing it is already preserved via
`seed_registry` → `session.begin_nested()` (lines 167–177) — keep that.

**Smallest safe change (scale improvement, not semantic):**
- Preload the existing benchmark/model/alias keys the seed depends on into
  `{id: row}` maps (one SELECT for each of `Benchmark`, `ModelEntity`, and
  `Alias` where `entity_type` in the two columns), then `upsert_*` reads from
  the map instead of `session.get`; fall back to a `get` only for an id absent
  from the map.
- Batch `add_alias` existence: load the target alias strings for the seeded
  entities once, then insert only missing aliases in bulk; keep the same
  dedupe + unique semantics. Do **not** change the duplicate-id rejection in
  `_validated_source_entries` (`:17–42`) or the retirement guard
  (`retire_registry_sources_not_in`, `:448,`, `retire_missing` default False).

### 4.2 Review-queue paging is Python-side and has no offset/cursor

`repositories.py:1153` `list_review_queue(session, limit=100)`:
- Loads **all** `ResultClaim` (`select ... order by created_at desc`, no
  `limit` in SQL), then walks projection per row until the queue fills. On a
  large ledger this reads the entire claims table for a 100-item queue. CLI
  `review_queue` (`cli.py:780`) and its `limit` cannot page past the last page
  and has no cursor.

**Smallest safe change:** add an explicit `offset`/`after` (cursor by
`created_at,id`) parameter that slices the ordered SQL `limit` window in the
SQL, and reject sampling for SQL that must inspect many rows; document that the
Python projection loop is bounded by the supplied window. The deferred plan's
"page/bulk-load reports and review queues" is this. The review SQL must remain
the same `order_by created_at desc` so results are deterministic; add an
`id` tie-break for stable cursors.

**Proposed counters for the review queue:** `REVIEW_QUEUE_TABLE_SCANNED` (rows
actually read by SQL, should equal the window after the fix) and
`REVIEW_QUEUE_PROJECTED` (number of claims worth projection walked
`=` the SQL window). Before the fix the SQL scan = all claims; after the SQL
window = scanned rows; a regression test asserts scanned ≤ window.

---

## 5. Frontend — bundle composition & 500,42

### 5.1 Bundle is a single ~1.43 MB IIFE, no lazy splitting

**[measured]** `dist/assets/` (current static build):
```
index-BQhvxvR0.js    1,433,793 bytes   (≈ 1.37 MiB raw, > 1.43 MB transient)
index-BL6wlD-L.css      41,679 bytes
```
`vite.config.ts` has **no `build.rollupOptions.output.manualChunks`** and the
app has **no `React.lazy`/dynamic `import()`** — everything is in one chunk at
page load. This matches the audit's "1.4 MB raw bundle" and the build's own
"1433.79 kB chunk" warning.

**Primary budget (uncompressed raw):** ≤ **1,100,000 bytes** of **initial
eager JS** — the single synchronous chunk loaded at page start — not **total**
JS across all deferred/lazy chunks. This targets the single eager chunk below
the 1,433,648 baseline (see §5.1) without constraining bytes later fetched
after a lazy split. Do **not** pick a compression-adjusted number; gzip/brotli
budgets vary until a real CDN (`brotli`) is measured. No concrete split target
is chosen here; the candidate is whatever moves
`recharts` + `motion` + the vendored `evilcharts/` chart layer onto a deferred
chunk.

**Smallest safe change (measure-first, split-only-where-supported, per
deferred item 9):**
1. **Add a build-size budget gate** (`scripts/verify-bundle-budget.mjs`,
   public CLI `--budget-total B` / `--budget-eager B`, run in CI after
   `npm run build`) that sums `dist/assets/*.js` and fails if the eager/total
   exceeds the budget above. The script already exists; this item is wiring
   the freshly decided 1,100,000-byte initial-eager budget as the CI
   assertion threshold.
2. **Instrument a runtime budget** via `performance.`/`web-vitals`-free hooks
   flagged off by default (they are presentation-only, not claims) to record:
   `BUNDLE_TOTAL_JS`, `SCROLL_TABLE_TOTAL_ROWS`, `SCROLL_TABLE_FIRST_PAINT_MS`,
   `SCROLL_TABLE_TICK_MS` on deep scroll. These become the runtime baselines
   before any micro-splicing.
3. **Then, and only then, lazy-load** the comparison-view/sheet/heatmap and any
   chart-rich secondary route with `import()`/`manualChunks` so the axis-line
   deps (`recharts`+`motion` → vendored `evilcharts/`) move to a deferred chunk.
   Lazy splitting must be **justified by the measured debit**, not speculative,
   per item 9's "split only where measurement supports it".

**External blocker:** real numbers need the Chrome/WebKit framing for
`PerformanceNavigationTiming` on a built artifact; native in-app browser was
`iab`-blocked in the prior checkpoint, so runtime budgets are **proposed
thresholds awaiting an authorized build + browser receipt**. Do not claim a live
runtime number locally.

### 5.2 ScoreTable 500×42 — geometrically correct, still sequentially slow

`src/components/ScoreTable.tsx` (634 lines) and `src/lib/table.ts`:
```
ROW_H=40, BODY_MAX_H=560, ROW_BUFFER=10  → ~24 rows captured (14 visible + 2×10)
```
So a 500-×-42 cohort renders only **~24 rows live** —
the virtualization (lines 91–143) is already correct and bounded; the
scrollbar is top/bottom padded. **The 42 columns are NOT virtualized** — all
42 columns per visible row are mounted, and headers + `tfoot` render all 42.
That is the 500×42 hot spot: ~24 visible rows × (2 sticky + 42 data) ≈
**~1,056 live cells, no column virtualization**. On top of the cells, the
first render pass computes `statsByBench` via `cohortModels.map(getValue)` for
each of 42 benchmarks (lines 59–66), i.e. **42 × 500 = 21,000 `getValue` calls**
on every recompute (every filter/sort), plus the analogous `bestByBench`
(`:68–79`).

**[labeled]** Geometry is correct; the cost is:
- `columnStats` + `bestModelId` are O(modelCount × benchCount) and recomputed
  on any dependency change (cohort/sorts) — 21k+ `getValue` calls per pass, plus
  per-render work for every visible row/cell.

**Smallest safe changes:**
1. **Memoize columnStats/bestByBench keyed on the immutable snapshot fingerprint**
   (the `DatasetProvider` snapshot object identity), so a filter/sort of
   `models` (visible) that never changes `cohortModels` does **not** recompute
   the 21,000 calls. The two are already `useMemo`d but their deps can be too
   broad (a new `models` array identity from sort triggers them though the
   full cohort is unchanged). Tighten deps to `cohortModels` + `getValue`
   identity (**already the deps** — verify that `cohortModels` is actually
   referentially stable; if App recreates it on each render, that is the leak).
2. **Add row-h = 42 budget & a deep-scroll regression that asserts the live cell
   count** stays ≤ `(2|sticky) × (visible+2×buffer) × benchCount′` and that the
   render tick (`SCROLL_TABLE_TICK_MS`) stays at/under a threshold on a synthetic
   500×42 (the existing `ScoreTable.scale.test.tsx` already seeds 500×42).
3. **Accessibility eval / pagination** (item 9) — the audit lists "accessible
   pagination or a proven virtual grid with AT"; the row-virtualization is
   already ARIA-correct (`aria-rowindex`, `aria-sort`). A **column** virtual
   window is more invasive and lower-value (42 cols is not that wide). The
   available accessible option is adding a first-page/last-page skip or a
   proven column-group virtualization; either must be backed by AT testing,
   which is blocked (#iab) — so **defer the accessible column window** and gate
   on the frontend browser/AT receipt (external blocker).

**Runtime budget:** `RENDER_TICK_MS` for 500×42, target scroll-tick frame
≤ **16 ms** under a normal load. **JSDOM wall-clock timing is informational
only** (jsdom is not a rendering engine and its numbers are not a real-browser
baseline); acceptance for the `ScoreTable` scale regression is the
**deterministic cell/row counts** (`SCROLL_CAPTURED_CELLS` ≤ the fixed
virtualization window, `aria-rowindex`/`aria-sort` correctness) rather than
jsdom ms. A native-browser frame-time budget is only established by an
authorized `iab`-capable browser receipt, which is currently blocked.

---

## 6. Release / withdrawal / rollback rehearsal & runbook gaps

**Runbooks present (read-only):**
- `docs/runbooks/release-artifact-and-withdrawal.md` (65 lines) — REL-05
  preconditions, prohibited shortcuts, and a **future** release + withdrawal
  protocol.
- `docs/runbooks/official-publication-and-evidence-preservation.md` (129 lines)
  — the publication protocol, also future/enhanced.
- `docs/runbooks/release-withdrawal-rollback-rehearsal.md` — the operator
  rehearsal runbook created for this lane (state separation, exact IDs,
  preflight, smoke, stop/withdrawal/rollback, ownership, RTO/RPO, retention).
- `docs/runbooks/release-rehearsal-evidence-receipt.md` — the blank
  fill-in evidence/receipt template created for this lane.

**Gaps addressed by the new runbook/template:**
- The rehearsal runbook turns the pointer runbooks into a **documented,
  non-executed template** that links capture → review → release → deploy →
  withdraw → rollback, and names the exact symbols/stores; it is copy-only.
- It separates states strictly (validated locally / CI verified / pushed /
  deployed / verified live), records exact IDs, and marks every provider /
  authenticated step **BLOCKED / NOT EXECUTED**.
- Ownership, RTO/RPO and retention placeholders are repeated from the launch
  charter; residual missing checks (R1–R4) are listed as residuals, not
  invented.

**Exact blocking blockers (unchanged from audit):**
- Official artifact is unavailable by design (governance gate). No claim,
  snapshot, digest, or signer to rehearse against.
- Cloudflare auth 401/403, Wrangler unavailable → no deploy/rollback/history
  to rehearse against a real provider.
- `iab`-browser blocked → no browser reproduction of the rollback UI state.

---

## 7. Proposed counters & budgets (summary)

| Counter (name) | Where measured | Baseline [measured/labeled] | Budget |
| --- | --- | --- | --- |
| `EVIDENCE_DECODE_US_PER_CLAIM` | `parquet_cells.read_parquet_record` | ~156 µs single | ≤ 60 µs (resolver) |
| `EVIDENCE_DECODE_BATCH_US/ROW` | `iter_parquet_records` | ~5.6 µs/row | reference only |
| `CANDIDATE_PER_CLAIM_ROUNDTRIPS` | `official_json._eligible_claim` | ~10 (labeled) | ≤ 3 (1 SQL + preloaded) |
| `REVIEW_QUEUE_TABLE_SCAN` | `list_review_queue` | = all claims (labeled) | ≤ window |
| `REVIEW_QUEUE_PROJECTED` | `list_review_queue` | = all claims | ≤ window |
| `SEED_ALIAS_PER_SELECT` | `add_alias` | 1 SELECT/alias | 0 (bulk) |
| `BUNDLE_TOTAL_JS` | `dist/assets/*.js` | 1,433,648 B [measured] | ≤ 1,100,000 B |
| `SCROLL_TICK_MS` at 500×42 | `ScoreTable` | unmeasured (jsdom) | ≤ 16 ms target |
| `SCROLL_CAPTURED_CELLS` | `ScoreTable` virtualization | ~1,056 (labeled) | ≤ 1,200 (no column virtualization) |

`K`-claim acceptance is: 10k-claim ledger fixture runs the analysis + evidence
consume path, asserts each counter and total-time/RSS under the budget, with a
regression asserting no-counts. RSS is measured externally (e.g. `resource` in
a probe script), per the audit's "RSS measurements before optimization acceptance".

### 7.1 Exact read-only measurements run for this handoff

These are the bounded, CPU-only, in-memory probes behind the `[measured]` labels
above. None touched a database, network, browser, provider, or deployed artifact.

Parquet decode-cost probe (`ledger/`, uses the pinned pyarrow 18.1.0 and the
in-memory-only `parquet_cells` module):
```sh
cd ledger && PYTHONPATH=app .venv/bin/python - <<'PY'
import io, time
import pyarrow as pa, pyarrow.parquet as pq
from app.ingestion.parquet_cells import _open, read_parquet_record, iter_parquet_records
N = 10_000
tbl = pa.table({
  "model":[f"model-{i%500}" for i in range(N)],
  "score":[float(i%1000) for i in range(N)],
  "metric":[f"m{i%7}" for i in range(N)],
  "split":["test"]*N, "setting":[f"s{i%3}" for i in range(N)],
  "pass@1":[float(i%97) for i in range(N)],
  "extra7":[f"x{i%50}" for i in range(N)], "extra8":[i%1000 for i in range(N)],
})
buf = io.BytesIO(); pq.write_table(tbl, buf, row_group_size=512); raw = buf.getvalue()
pf = _open(raw)
print(f"bytes={len(raw):,} rows={N} row_groups={pf.num_row_groups}")
t0=time.perf_counter()
for i in range(1000): read_parquet_record(raw, row_group=i%512, row_index=i%37)
dt=(time.perf_counter()-t0)/1000
print(f"single read_parquet_record {dt*1e6:.1f} us -> 10k = {dt*1e6*1e4/1e6:.2f} s")
t0=time.perf_counter(); rows=list(iter_parquet_records(raw)); dt=(time.perf_counter()-t0)
print(f"batch decode {len(rows)} rows {dt*1e3:.1f} ms ({dt/len(rows)*1e6:.2f} us/row)")
PY
```
Result: `single = 155.8 us` → **10k = 1.56 s**; `batch all 10k = 55.7 ms
(5.57 us/row)`; ratio ≈ **28×**.

Bundle-size probe (repo root, static `dist`, no rebuild):
```sh
wc -c dist/assets/*.js dist/assets/*.css
```
Result: `index-BQhvxvR0.js = 1,433,793 B`; `index-BL6wlD-L.css = 41,679 B`;
total JS is the single-chunk 1,433,793 B baseline.

All other baselines in §7 are `[labeled]` (read from source) or listed with no
measurement because a native browser is unavailable.

---

## 8. Smallest safe code/test changes (ordered, lowest-risk first)

1. `repositories.py` — make `_claim_review_chain`/`_claim_publication_chain`
   accept a preloaded `Sequence` of decisions (public-minus private signature
   unchanged; **same fail-closed chain walker**).
2. `export/official_json.py` — fan-out the per-claim validations/review/pub/
   source-decision selects once per `analyze_official_feed_candidates` run; pass
   preloaded maps.
   Regression: correctness identical; `chain_error` strings byte-identical.
3. `legacy_inventory.py` — reuse the preloaded decision maps in `_claim_record`
   instead of second re-resolution.
4. `admission.py` + `parquet_cells.py` — a per-snapshot `ParquetEvidenceResolver`
   (open once) injected into `resolve_claim_admission` and the
   **`bigcodebench_parquet` validate_claim** seam; prove via a decode-count
   test (a resolver that counts how many times the slice is read).
5. `operational_repositories.py`/`repositories.py` — `offset`/`after` cursor to
   `list_review_queue`; SQL-window bounded. Keep order-by `created_at`.
6. `seed_loader.py` — preload id/alias maps; bulk alias insert; keep
   `begin_nested` atomicity and duplicate rejection.
7. `vite.config.ts` + `scripts/verify-bundle-budget.mjs` + a
   `ScoreTable` perf test asserting `SCROLL_CAPTURED_CELLS`/tick. **Build the
   budget gate first; lazy-split only after the §5.1 measurements.**
8. `docs/runbooks/release-withdrawal-rollback-rehearsal.md` — copy-only
   rehearsal; record the exact providers/symbols and mark every step blocked
   on absent governance/browser/provider authority.

**Never, in any of these:** coerce raw lexemes, rewrite a claim/record, weaken
a prior audit assertion, mutate a provider/database/remote, or claim a live
runtime or live browser/rollback number without a real receipt.

---

## 9. Dependencies

- **No new run-control product deps needed to build the counters & budgets.**
- Ledger: `pyarrow` already pinned (18.1.0) and used; the evidence resolver
  needs no new lib. Any change stays on already-pinned PyPI graph (uv.lock
  authoritative).
- Frontend: `recharts`+`motion`+Base UI already vendored/installed; lazy
  splitting is rollup/dynamic-import only (no new dep). If anything is added
  only for perf probes, keep it in `devDependencies` and out of `dependencies`,
  so it never ships in the production bundle.

## 10. External / product blockers (final)

1. **Native browser (`iab`)** — gates runtime bundle budgets, Tick/AT
   accessible-pagination acceptance, and rollback reproduction. **Product/QA
   owner** must supply a browser receipt; otherwise all frontend runtime
   numbers stay "probe baseline, not shipped."
2. **_Governed Official source + REL-05 decision** — no artifact to rehearse
   withdrawal/rollback against; rehearsal remains a document, not an executed
   chain.
3. **Cloudflare account/project/rollback token & a long-lived Wrangler** — the
   only way to prove withdrawal/rollback receipt. Provider owner.
4. **GitHub billing/plan** — pushes must be authorized before any CI bundle
   gate/ledger perf test can run on a real runner (all gates above run in the
   `verify.yml` after a successful build).
5. **Lead-back** — budget numbers are placeholders until the gate owner
   confirms them; the product/release owner must confirm the **initial eager**
   bundle budget (1.1 MB) and the `RENDER_TICK_MS`/`SCROLL_TICK_MS` targets
   before any gate is made authoritative.

---
## 11. Task 1D closeout — review-queue pagination + registry seeding (implemented)

This section records the implemented state from `task_87266f60ddf4` (dispatch
`ctx_264d8b02b10e`), reconciled against the proposed "smallest safe changes" in
§4.1 / §4.2 above. Where the proposal described a direction, the implementation
is the locally validated form; it has not been committed, pushed, deployed, or
verified against a live PostgreSQL service.

### 11.1 Review-queue pagination (§4.2) — implemented
- **Bounded SQL `(created_at, id)` keyset window** in `repositories.list_review_queue_page`.
  The SQL window equals `limit` (no hidden probe): `scanned == len(rows) <= limit`.
  `limit` is strictly validated positive and capped at `REVIEW_QUEUE_MAX_SCAN =
  10_000` (defect: reject `limit > max`).
- **Ordered** `created_at DESC, id DESC` with an `id` tie-break for stable,
  duplicate-free cursors across equal timestamps (§4.2 asked for this exactly).
- **Grouped decision load** — one `IN` query loads review decisions for the whole
  window via `_load_review_decisions`, resolving each projection in-memory through
  the pure, fail-closed `_resolve_review_chain`. No per-row `SELECT`.
- **Canonical cursor** — `_serialize_cursor`/`_parse_review_cursor` emit and
  validate a strict `v1.<b64>` token preserving **full timestamp precision** (never
  truncating microseconds); parse rejects truncated/extra-key/non-canonical tokens
  fail-closed.  `id` is validated as a strict `UUID` with `str(uuid_obj)==id` (no
  loose 36-char regex); `created_at` is validated through the same UTC-normalized
  renderer (`_cursor_datetime_str(parsed) == raw`) and aware values are converted
  to UTC via `astimezone(timezone.utc).replace(tzinfo=None)` before persistence;
  the PostgreSQL branch binds a UTC-aware `tzinfo=timezone.utc` literal.
- **Microsecond round-trip** — regression test inserts 20 claims with distinct
  microsecond `created_at` and proves no duplicate/omission across a full drain,
  that each stored `created_at` equals the exact supplied value, and that the
  first page's cursor decodes to the exact 6th-descending microsecond boundary.
- **Exact-full window** documents one extra empty page at the true end
  (`exhausted=True`); a sparse-but-not-empty page keeps a usable `next_cursor`
  without unbounded scanning. CLI `review_queue` renders items + continuation.
- **Public `list_review_queue(limit=...)`** retained as a first-page compatibility
  wrapper (identical first-page semantics).

### 11.2 Registry bulk seeding (§4.1) — implemented
- **Preloaded `{id: row}` maps** for `Benchmark`/`ModelEntity` (one constant
  `SELECT` each) drive batched `_upsert_benchmark_from_map`/
  `_upsert_model_entity_from_map` in-memory upserts (no per-row `get`/`flush`);
  constant SELECT count as the seed grows. Public `upsert_benchmark`/
  `upsert_model_entity` and `add_alias` are unchanged for single-row callers.
- **Chunked alias existence lookup** (`add_aliases_bulk`, `_ALIAS_LOOKUP_BATCH =
  250`) — O(len/batch) SELECTs, bounding SQLite/PostgreSQL IN parameter limits
  (verified with a 3,000-alias fixture).
- **Cross-file duplicate identity rejection** (`_validate_entity_ids`) runs before
  any durable write; `begin_nested()` all-or-nothing preserved; `retire_missing`
  default/guard unchanged; `counts["aliases"]` retains its prior "manifest entries
  processed" meaning.

### 11.3 Not in this scope (kept for follow-up, not silently dropped)
- §3.1/§3.2 evidence-resolver reuse (Parquet/CSV decode-once) — owned by the
  parquet evidence-resolver lane, not this task.
- Frontend bundle/500×42 work (§5) — frontend lane.

### 11.4 Verification (raw, unpiped)
```
cd ledger
uv run pytest -q tests/test_review_queue_perf.py tests/test_review_queue.py tests/test_registry_seed_perf.py tests/test_registry_preservation.py   # 36 passed
uv run pytest -q tests/test_claim_admission.py tests/test_registry_preservation.py tests/test_review_queue.py   # 47 passed
uv run pytest -q tests/test_postgresql_portability.py tests/test_operational_persistence_postgresql.py   # 3 passed, 9 skipped (no live PG)
git diff --check   # clean
```
Worker-reported mutation probes (each regression **failed for the intended
reason**, was restored, then the final load-bearing tests passed): remove SQL
`limit` (scanned leaked to row count); per-row decision load (11 SELECTs ≠
constant 2); per-row benchmark upsert (198 SELECTs ≠ sub-linear `== 3`).
Implementer truthfully reports no code was committed/deployed; this is a handoff of
implemented, test-green state for coordinator acceptance.

---

## Report created

This **handoff report file itself** was originally created as the artifact of
record. Subsequent local implementation tasks updated §11 and the corresponding
source/tests; the original statement that no source/config was edited no longer
describes the current document. No live network, browser, provider, deploy,
commit, or push action is claimed by this report.

The downstream rehearsal/runbook work is owned by the
[release, withdrawal, and rollback rehearsal runbook](../runbooks/release-withdrawal-rollback-rehearsal.md)
and its fill-in
[evidence-receipt template](../runbooks/release-rehearsal-evidence-receipt.md).
