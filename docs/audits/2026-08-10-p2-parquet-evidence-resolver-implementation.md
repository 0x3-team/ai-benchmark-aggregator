# P2 Parquet Evidence-Resolution Performance Slice — Implementation

**Date:** 2026-08-10
**Task:** task_0d41a55079b6 (Orca worker; correction of the resolver-lifecycle slice — the
run-scoped resolver must close on every `_run_one_source` exit, and row-group
denominations must be metadata-only).
**Goal (audit `2026-08-10-p2-performance-operations-handoff.md` §3.1):** cache one
immutable Parquet evidence resolver per snapshot so a snapshot is opened/decoded
once and reused by extraction, admission, and re-resolution.

## Scope of ownership
This document is itself part of the delivered work (see Changes) and is listed
in the worker receipt.  Ledger Parquet evidence resolver / admission /
BigCodeBench adapter / focused tests / this report only. **Not touched:**
DB migration, backup/security, registry/tooling, frontend, workflow config,
and all P1-security-worker-owned files (`db/migrate.py`, `db/repositories.py`,
`backup/sqlite_driver.py`, `test_migrations.py`,
`test_ingestion_runner_transactions.py`, PG/recovery/storage tests). No commit,
stash, clean, network, provider, Official, or deployment was run.

## Changes

- `parquet_cells.py` — reworked `ParquetEvidenceResolver`:
  - **open once**: construction opens and decodes the snapshot a single time;
    a snapshot is opened/decoded once per ingestion run and reused.
  - **binding (fail-closed)**: every read path that accepts both `raw_bytes`
    and a resolver verifies the resolver is bound to those exact bytes.
    `verify()` uses an O(1) identity fast path when the *same* bytes object is
    passed (no re-hash), and a full sha256 digest comparison for equal-but-
    distinct objects. Object identity alone is never authoritative. A resolver
    bound to different bytes raises `ParquetCellError`
    (`EVIDENCE_SNAPSHOT_MISMATCH` on the read path).
  - **immutable records**: decoded cells are exposed as `MappingProxyType`
    immutable mappings, so caller mutation cannot corrupt later reads. Adapter
    code reads them via `Mapping` compatibility (`.get`, `[]`, equality).
  - **O(1) lookup**: `read` stores an immutable nested tuple
    `groups[row_group][row_index]` and performs direct indexing — no linear
    scan over the snapshot. An optional `_lookup_counter` records one direct
    record access per `read`/`iter_records`, powering the deterministic
    bounded-operation assertion.
  - **honest lifecycle**: `close()` / context manager drops the resolver's
    reference to the decoded snapshot so it can be reclaimed; it never frees
    the caller's own `raw_bytes`. No process-global cache. `close()` is
    idempotent; after it, every consume path (`read`, `iter_records`) raises
    `ParquetCellError`. The previous `release_parquet_records` no-op is removed.
    Closed-state behavior is asserted (reads/iter/verify after `close()` raise;
    `close()` itself never raises).
- `parquet_cells.py` — `parquet_row_group_rows` is now **metadata-only**: it
  opens the footer and reads each row group's `num_rows` from
  `ParquetFile.metadata` and never calls `read_row_group`/`to_pylist`. The
  returned denominations are bounded by the number of row groups, not by the
  size of the snapshot's rows. A full row-grid decode is left to the shared
  `ParquetEvidenceResolver`, which a caller reuses across extraction,
  admission, and validation. A focused test wires `read_row_group` to fail
  loudly and proves a correct metadata-only path still succeeds.
- `admission.py` — `resolve_claim_admission(..., parquet_resolver=None)` and
  `_evidence_record(...)` thread a shared resolver into the typed
  `parquet_cell_v1` re-resolution, which now verifies the resolver against
  `raw_bytes` and fails closed with `EVIDENCE_SNAPSHOT_MISMATCH` on mismatch.
  Exact raw-lexeme policy and `EVIDENCE_VALUE_NOT_VERBATIM` unchanged.
- `adapters/base.py` — opt-in trait renamed to `uses_parquet_evidence_resolver`
  (default `False`); no default fallback.
- `adapters/bigcodebench_parquet.py` — `uses_parquet_evidence_resolver = True`;
  `extract_claims` verifies a supplied resolver before iterating and fails
  closed (PARQUET_UNREADABLE) on mismatch instead of silently falling back;
  `validate_claim` re-resolves through the verifier. Exact locator semantics,
  duplicate prevention, fail-closed accounting unchanged.
- `runner.py` — `_run_one_source` builds one resolver per source when the
  adapter opts in and creates it inside a `try/finally` whose `finally`
  **always** `close()`s it on every exit path: success, extraction exception,
  missing-decision guard, admission-rejected `continue`, validation failure,
  or persistence exception. The resolver is never process-global.  Two distinct
  lifetimes are involved: `ParquetEvidenceResolver` construction force-closes the
  PyArrow `ParquetFile` reader (via `parquet_file.close(force=True)`) after
  decode, while the runner's `finally` calls `ParquetEvidenceResolver.close()`
  on every exit to drop the retained decoded grid — that method does **not**
  accept a `force` argument. On an opt-in
  adapter, malformed Parquet now raises (fail-closed) rather than silently
  degrading — no performance fallback is presented as normal operation.
- `tests/test_parquet_evidence_resolver.py` (new), plus additions to
  `tests/test_parquet_cells.py`, plus a new
  `tests/test_runner_parquet_resolver_lifecycle.py` (a **new** file — the
  P1-owned `test_ingestion_runner_transactions.py` was not edited):
  same-snapshot reuse with counted opens, equal-but-distinct bytes via digest,
  mismatched-resolver fail-closed for extraction/admission/validation,
  immutable record maps (caller mutation cannot persist), O(1) last-row lookup
  on a 10,000-row fixture via a bounded operation counter, context-manager
  close, closed-state fail-closed behavior (reads/iter/verify after close
  raise), and runner-level open/close symmetry on the success, extraction-
  exception, missing-decision-exception, and rejected-admission paths (each
  asserts exactly one resolver is created and exactly one is closed).

## Results / measurements
Deterministic counts (acceptance criterion — not timing):
- **Opens**: one `ParquetEvidenceResolver` build = exactly **1 open**; re-reads
  and batch `iter_records` reuse it (no further opens). Verified by
  monkeypatching the module opener.
- **Decodes**: the snapshot is decoded exactly once at construction for a given
  resolver (asserted by the same open counter plus the O(1) direct-index check).
- **Direct lookup bound**: on the 10,000-row fixture, reading the LAST row
  three times performs exactly **3** record accesses (asserted via the
  `lookup` counter) — i.e. each last-row read is one direct index, not a
  linear scan of 10k rows.
- **Mismatch**: a resolver bound to different bytes rejects `PARQUET_UNREADABLE`
  (extraction), `EVIDENCE_SNAPSHOT_MISMATCH` (admission and validation); the
  same-object fast path skips the digest re-hash (asserted).
- **Lifetime (deterministic, runner-level)**:
  - success: exactly **1** open and **1** close of the shared resolver, and
    the closed instance is the one that was opened (no leak);
  - injected extraction exception: the resolver created before the failure is
    still closed **1** time;
  - missing-decision guard raise: resolver closed **1** time;
  - rejected admission: resolver closed **1** time.
  These are asserted via a recording resolver subclass wired into the runner's
  resolver construction — no wall-clock involved.
- **Closed-state**: after `close()`, `read`, `iter_records`, and `verify`
  raise `ParquetCellError`; `close()` itself is idempotent and never raises.
- **Metadata-only denominations**: `parquet_row_group_rows` reads row counts
  from the footer metadata and never decodes rows; a loud-failure wiring of
  `read_row_group` proves the metadata path needs no row decode.

## Tests (focused)
All green:
```
cd ledger && source .venv/bin/activate
python -m pytest tests/test_parquet_cells.py \
  tests/test_parquet_evidence_resolver.py \
  tests/test_runner_parquet_resolver_lifecycle.py \
  tests/test_bigcodebench_parquet_adapter.py \
  tests/test_ingestion_runner_transactions.py -q
# 41 (owned parquet/resolver/lifecycle) + 11 adapter + 11 runner transactions = 63 passed
```
`git diff --check` passes.

## Residual / risks
- Broad resolver sharing is limited to the BigCodeBench parquet adapter (the
  only production adapter using `parquet_cell_v1`). CSV/JSON adapters keep
  their existing per-call decode paths; extending the shared seam (audit §3.2)
  is a separate slice — no default fallback added.
- The runner passes a resolver only when the adapter opts in via
  `uses_parquet_evidence_resolver`, so all other adapters are unaffected.
- Microsecond wall-clock and the previous ~500x claim are deliberately removed
  because they are machine-dependent and not reproducible; the acceptance
  bound is the deterministic open/decode/lookup counts above.

## Coordinator Rework (task_c1ddcbcc35e7, dispatch ctx_7c63e1c91735)

The first `worker_done` for this slice was returned `REWORK` after source review
despite green tests.  The ten corrections below were applied; none touched the
P1-security-owned files (`db/migrate.py`, `db/repositories.py`), and the prior
resolver lifecycle/evidence-resolution behavior above is retained.

### 1. Metadata limits gate before row-group access
`_enforce_metadata_limits` now validates the scalar row-group and column counts
via `_require_nonnegative_int` *before* any `range(row_groups)` work. A hostile
`num_row_groups` is rejected by the scalar cap gate before iteration, so a bad
footer can never drive an unbounded `range` loop. A load-bearing
`test_range_bounded_scalar_cap_gate_before_row_access` forges a footer whose row
group accessor raises if touched, proving the scalar gates reject first.

### 2. Strict metadata validation (fail closed, no coercion)
Every denominator is validated as a strict non-negative `int`:
- top-level `num_row_groups` and `num_columns`;
- **scalar caps first** — rejecting a bad row-group/column claim before any
  row group is read;
- each row group's `num_rows` and `num_columns`, with `num_columns` required to
  equal the shared schema column count (a mismatch fails closed);
- each column chunk's `total_uncompressed_size` as a non-negative int.

Negatives are never allowed to *reduce* running totals, and invalid metadata is
never silently coerced (no `or 0`). Every rejection raises the stable
`ParquetMetadataLimitError`, caught as `EVIDENCE_METADATA_LIMIT_*` on the
locator path. Focused tests assert zero, negative, non-int, and column-count
mismatch all fail closed.

### 3. Bounded `iter_batches` decode (no whole-group `read_row_group`)
`_decode_group` decodes exactly one row group through `iter_batches(batch_size=
MAX_PARQUET_BATCH_SIZE, use_threads=False)` and calls `to_pylist` only on each
bounded `RecordBatch`, never a whole row group. `use_threads=False`
disables concurrent column decoding at this boundary for resource
predictability — it is a
**resource/concurrency control**, not a guarantee of output determinism. `row_index`
is tracked across batch boundaries so the global index stays exact, and a batch
whose decoded `num_rows` exceeds the cap fails closed. A faithful spy wraps every
`ParquetFile.iter_batches` call and asserts `batch_size` is positive and at most
the fixed cap, exactly one row group is requested per call, and `use_threads`
is `False` — this test is load-bearing and **mutation-proven by two real isolated
temporary mutations during task `044592efe856`**:
1. **use_threads removed** → spy test failed: `assert use_threads is False`.
2. **batch_size raised to `999_999_999`** → spy test failed:
   `assert 999999999 <= 8192`.
Both mutations were restored with inverse `apply_patch` and the spy test returned
green. Honest note: the batch cap bounds how many records a single
`to_pylist` conversion materializes at once. The retained rendered grid still
accumulates across the whole row group and is separately bounded by
`MAX_PARQUET_CELLS` — total peak allocation is not one batch. Codec internals
may still expand a column chunk transiently; the `total_uncompressed_size`-derived
cap is an estimate, not a hard heap bound.

### 4. Force-close on every decoder exit
`ParquetEvidenceResolver.__init__` wraps construction in `try/finally` and calls
`parquet_file.close(force=True)` on success, metadata-limit rejection, and
decode failure alike. `parquet_row_group_rows` applies the same metadata limits
and force-close without decoding rows. Exact close-count tests cover the
success, metadata-limit-failure, and decode-failure paths.

### 5. Adapter streams the resolver iterator
`BigCodeBenchParquetAdapter.extract_claims` consumes the shared resolver's
one-shot `iter_records()` directly, counting `record_count` as the sole source
of truth; the redundant full `records` list is removed. `PARQUET_EMPTY` and the
all-or-nothing `INCOMPLETE_ACCOUNTING` fail-closed return are preserved. A test
hands the adapter a resolver whose `iter_records` returns a one-shot iterator
whose `__length_hint__` raises: direct `for`-loop iteration (what the adapter
uses) succeeds, but `list(...)` raises — the test is load-bearing and
mutation-proven to fail if a future re-implementation ever regressed to
materialising the records into a list. During task `044592efe856` a **real
isolated mutation** wrapped both the resolver and the `iter_parquet_records`
path in `list(...)`; applying it made `test_extract_streams_resolver_iterator_not_list`
fail with `RuntimeError: length_hint forbidden: consumer must stream, not materialise`.
The mutation was restored with inverse `apply_patch` and the test returned green.

### 6. Runner lifecycle coverage for validation and insert failures
Two new runner-lifecycle tests assert exactly **1 created / 1 closed** each when
(a) the adapter's `validate_claim` raises, and (b) a non-dry-run persistence
`insert_claim_if_new` raises. The non-dry-run insert test is wired to reach the
claim-persistence path by stubbing the DB current-revision snapshot insert (an
unrelated reconciliation constraint) while letting the injected insert failure
escape through the runner's `finally`-guarded resolver lifecycle.

### 7. Reassessed, conservative resource caps
Caps were re-derived against the Python per-record amplification — a decoded
row becomes a rendered-cell dict, plus (in the adapter path) a
`ResultClaimInput` and a duplicate-tracking set entry per dimension — not
against a claim that the encoded Parquet bytes bound the Python heap.  The
final conservative fixed caps are below the previous figures, still far above
the current fixtures (a 10k-row × 3-column snapshot = 30,000 cells) yet below
the heap hostile amplification could demand:
`MAX_PARQUET_ROWS` 100,000 · `MAX_PARQUET_COLUMNS` 32 ·
`MAX_PARQUET_CELLS` 500,000 · `MAX_PARQUET_ROW_GROUPS` 128 ·
`MAX_PARQUET_DECOMPRESSED_BYTES` 128 MiB (codec-expansion *estimate* only;
metadata size is **not** a heap guarantee).
`MAX_PARQUET_BATCH_SIZE` 8,192 is a fixed, documented decode batch bound and is
not tunable per source.  Relative to the 10k-row × 3-column fixture (30,000
cells) these caps hold **10× row and ≥16× cell headroom**; they are safety
ceilings for the bounded decode grid, not guarantees about peak PyArrow heap
during column-chunk expansion.  The decode path passes `use_threads=False` as a
single-threaded resource/concurrency control (not a determinism guarantee).

### 8. Verification
Ran from `ledger/` via `uv run pytest` (pyarrow pinned 18.x).  Exact durable
counts recorded in task `044592efe856` after all three real isolated mutation
tests were restored and re-verified green:

```
ledger$ uv run pytest -q tests/test_parquet_cells.py \
  tests/test_parquet_evidence_resolver.py \
  tests/test_bigcodebench_parquet_adapter.py \
  tests/test_runner_parquet_resolver_lifecycle.py     # 75 passed
ledger$ uv run pytest -q tests/test_ingestion_runner_transactions.py \
  tests/test_operational_persistence_postgresql.py    # 11 passed, 3 skipped
ledger$ uv run pytest -q tests/test_claim_admission.py # 31 passed
ledger$ uv run pytest -q tests/test_registry_preservation.py  # 12 passed
git diff --check   # clean
```
The 75 owned passes cover parquet cells + evidence-resolver (incl. the force
-close decode-failure seam and the two load-bearing mutation-proven batch/stream
spy tests) + the BigCodeBench adapter (incl. the length-hint streaming test) +
7 runner-lifecycle tests.  No reset/stash/clean/checkout/commit/network/
provider was run.
