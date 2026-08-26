# Implementation handoff: Tooling / Registry / Scale governance (deferred 6–9)

**Date:** 2026-08-10
**Author:** mapper (this artifact was authored by the mapper, not a dispatched read-only evidence worker)
**Repo / branch:** `/Users/stevmq/Documents/ai-benchmark-aggregator`, `main` (dirty, shared worktree — **no files were modified by this worker**).
**References:** AGENTS.md; `docs/audits/2026-08-09-comprehensive-checkpoint-audit.md` (rows 218–220); `docs/plans/2026-08-09-comprehensive-checkpoint-remediation-plan.md` items 6–9.

Read-only evidence task. No edits and no live network calls were made. This is a
concise implementation handoff: exact files, current unsafe behavior, smallest
safe code changes, focused tests, and what needs product/governance authority.

---

## 1. Direct-network helper scripts (deferred 7 — "retire or redesign direct-network helpers")

These are top-level purpose-built scripts that perform **unmediated outbound
HTTP GETs** with no allowlist, no limit, no peer-pinning, and no SafeFetch
containment. They are not on the normal CLI path (`benchmark-ledger`) but are
committed and runnable. None is invoked by the test suite and none is an adapter.

| File | Network capability | Notes |
| --- | --- | --- |
| `ledger/scripts/seed_models_from_hf.py` | `urllib.request.urlopen` to HF API + per-model fetch | **The "HF registry rewriter"**: fetches top-1000+ model downloads, then **writes** `app/registry/models_hf_seed.yaml` and **mutates `models_frontier.yaml` in place** to add aliases. Direct edits to tracked registry YAML. |
| `ledger/check_urls.py` | `httpx.get` to 12 live leaderboard URLs | |
| `ledger/check_bfcl_humaneval.py` | `httpx.get` (2 URLs) | |
| `ledger/check_frontiercode.py` | `httpx.get` (1) | |
| `ledger/check_gaia.py` | `httpx.get` (1 datasets-server) | |
| `ledger/check_paperbench.py` | `httpx.get` (1 github) | |
| `ledger/check_tool_mt.py` | `httpx.get` (2) | |
| `ledger/check_aider_yaml.py` | `httpx.get` (1 raw github) | |
| `ledger/test_hf_urls.py` | `httpx.get` (2 datasets-server) | |
| `ledger/dump_tables.py` | `httpx.get` to 2 live leaderboard URLs despite its name | **Mislabelled in the original characterization as "local DB dump"**; it actually fetches bfcl + humaneval leaderboards. Retired to `scripts/retired/`. |
| `ledger/list_benchmark_ids.py` | none (local DB) | Static |
| `ledger/verify_adapter.py` | empty file (0 bytes) | Dead |

Also `tests/*` contain live-fetch access patterns **in comments/helpers only** —
e.g. `tests/test_httpx...`-style is not a real pytest file but the retirement name
`test_httpx_vs_urllib` does not exist; the closest are `test_artificial_analysis_retirement.py`
and `test_livecodebench_retirement.py` which assert the adapters are **retired/down**, not live.

### Current unsafe behavior
- Direct `httpx.get` / `urllib.urlopen` against arbitrary upstream hosts with no
  transport authority, no rate limiting, no credential redaction, no timeout
  guarantees object-reference of a raw string.
- `seed_models_from_hf.py` **writes** two registry YAML files at runtime.
- No committed test asserts these scripts cannot run live.

### Smallest safe code changes (ownership: Tooling owner)
1. **Retire**: delete (or move under `ledger/scripts/retired/`) the live-fetch
   `.py` scripts: `seed_models_from_hf.py`, `test_hf_urls.py`, `check_*.py`,
   `check_urls.py`. Deleting files mutates git so **requires coordinator
   confirmation** — it is outside "read-only" but is the safe end-state.
2. **Add a static policy test** (e.g. `ledger/tests/test_no_direct_network_scripts.py`)
   that scans the tree for pytest-visible live fetch objects and asserts **no
   committed plan asset performs unbound outbound GET** (mirroring how
   `verify_ci_lock` enforces offline lock policy):
   - assert `app/` adapters use the `SafeFetchClient` seam, never `httpx.get`/`urllib.request`.
   - assert the ready-live fetchers enumerated above are absent from `ledger/`.
3. **Do not** touch `app/ingestion/safe_fetch.py`; it is already the intended
   offline-first transport.

---

## 2. HF registry rewriter → offline candidate review-only tool (deferred 7)

- **File:** `ledger/scripts/seed_models_from_hf.py`
- **Current unsafe behavior:** requires live HF access and **writes over
  `app/registry/models_hf_seed.yaml`** and **adds aliases into
  `app/registry/models_frontier.yaml`** (mutates a curated/governed file).
- **Smallest safe change:** convert to an **offline, review-only** tool:
  1. Remove the `main()` network fetch path.
  2. Read an **already-exported, committed JSON/YAML** input (a reviewed snapshot)
     instead of calling the HF API.
  3. Write only to a **new** output path (e.g. `models_hf_seed.candidates.yaml`)
     with `O_EXCL`/no-overwrite and a `.reject` for readers — never mutate
     `models_frontier.yaml`.
  4. Emit a review queue (collision list) rather than auto-appending aliases.
- **Focused test:** `tests/test_models_hf_seed_offline.py` — feed a tiny committed
  fixture, assert it **never opens `models_frontier.yaml` for write** and produces
  a parseable candidate file.

---

## 3. Registry duplicate-ID collision (deferred 7 — "reject conflicting duplicate model IDs")

- **File:** `ledger/app/registry/seed_loader.py`
- **Current unsafe behavior:** `_registry_files()` (`seed_loader.py:45-47`) globs
  `benchmarks*.yaml` → includes **both `benchmarks.yaml` and `benchmarks_curated.yaml`**,
  and `models*.yaml` → includes **`models.yaml`, `models_frontier.yaml`,
  `models_hf_seed.yaml`**. `_seed_registry_changes()` then **silently skips** a
  duplicate ID after `seen_benchmark_ids`/`seen_model_ids` (`seed_loader.py:77-79`,
  `124-126`) — so when two files both define the same model/benchmark `id`, the
  **first glob entry wins silently and the differing second row is never surfaced.**
  This is the exact "silently choosing a row" defect the audit flags. The
  **source** (`_validated_source_entries`, `seed_loader.py:17-42`) already rejects
  duplicate source `id`s — the pattern to mirror.)
- **Smallest safe code change:**
  1. Make the benchmark/model loops mirror `_validated_source_entries`: detect a
     duplicate `id`, and **raise** `ValueError` naming both IDs **before any
     registry write** (keep it outside the transaction opened by `seed_registry`).
  2. Optionally, tighten `_registry_files` to a single deterministic file
     (preached priority) OR require callers to pass one explicit file. Do:

     ```python
     # before: sorted(glob(pattern))
     ```

     keeping deterministic order but raising on an ID seen in a later file.
  3. Do **not** change `upsert_model_entity`/`upsert_benchmark` semantics for an
     actual entity — only the loader.
- **Focused tests** (`tests/test_registry_preservation.py` — extend, or new file):
   fixture with two registry files containing the same `id` with different bodies;
   assert `seed_registry` raises and **DB count of that entity is unchanged**
   (reuse the `_count` + `after == before` pattern already in the file).

---

## 5. Everything else (deferred 6, 8, 9) — out of contractual scope for a worker

For completeness, these remain open and are **affected**:

- deferred **6 (scale)**: operators the performance N+1 / census / 10k budgets —
  see `ledger/tests/test_coverage_census.py`, `test_operational_persistence*`.
- deferred **8 (Official activation prerequisites)**: lower-is-better consistency,
  credential-bearing URL rejection, streaming/decompression/peer/TLS proof. Touches
  `app/ingestion/admission.py`, `safe_fetch.py`, adapter evidence.
- deferred **9 (a11y/perf)**: frontend bundle + virtualization (`src/`), requires
  `npm` and browser evidence — out of ledger scope.

These should be their own, separately authorized workstreams; they are not part of
this tooling/registry slice.

---

## Coordination inventory
**Files to change (pending governance on the delete):**
- `ledger/scripts/seed_models_from_hf.py`
- `ledger/check_urls.py`, `ledger/check_bfcl_humaneval.py`, `check_frontiercode.py`,
  `check_gaia.py`, `check_paperbench.py`, `check_tool_mt.py`, `check_aider_yaml.py`
- `ledger/scripts/verify_ci_lock.py` (leave as-is; already offline)
- `ledger/app/registry/seed_loader.py`
- New: `ledger/tests/test_no_network_scripts.py`, `ledger/tests/test_models_hf_seed_offline.py`
  (`subprocess`/`pytest` node tests), and a `docs/runbooks` note.

**Needs product/governance authority:**
- Deleting committed files / removing `models_hf_seed.yaml` from the registry glob.
- Deciding the canonical behavior for a model that exists in both `models.yaml`
  and `models_hf_seed.yaml` (raise-vs-review).
- Whether the rewriter may ever touch `models_frontier.yaml` (governed).
- Whether `retire_missing` remains operator-only.

**Verification sequence (when authorized):**
1. `cd ledger && .venv/bin/pytest -q`
2. focused: `.venv/bin/pytest tests/test_registry_preservation_no_network_hf_seed.py -q`
3. `git diff --check` and `git status --short --branch`.

No files were edited for this task; the toolchain, plan, and suite were left in
the pre-existing dirty state.

---

## 5.1 Addendum — implementation status (2026-08-10, follow-up worker)

This addendum records what was subsequently implemented against this handoff.
Read-only origins no longer apply; a follow-up worker executed the tooling and
registry slice.

- **Retired live-fetch helpers** to `ledger/scripts/retired/` (checked in via
  `git mv`, preserving history): `check_aider_yaml.py`, `check_bfcl_humaneval.py`,
  `check_frontiercode.py`, `check_gaia.py`, `check_paperbench.py`,
  `check_tool_mt.py`, `check_urls.py`, `test_hf_urls.py`, and `dump_tables.py`
  (the last was mislabelled above as a local dump; it performs live GETs).
- **Rewrote** `ledger/scripts/seed_models_from_hf.py` as an offline, review-only
  candidate generator: reads an exported snapshot, writes only to an explicit
  new path (no-overwrite), reports collisions against the read-only registry,
  and never writes `models_frontier.yaml` / `models_hf_seed.yaml`.
- **Hardened** `ledger/app/registry/seed_loader.py`: `seed_registry` now rejects
  cross-file duplicate benchmark/model IDs *before* any durable write, with exact
  filenames + IDs, instead of silently first-file-wins. The real registry tree
  carries three genuine non-identical model-ID collisions to be resolved by
  governance: `claude_3_7_sonnet`, `deepseek_v3` (`api` vs `open_weights`),
  `gpt_4o_mini`.
- **New tests**: `tests/test_no_network_tooling.py` (static scan over tracked
  non-test Python files for raw `httpx.get`/`urllib.request.urlopen`, allowing
  the SafeFetch seam), `tests/test_models_hf_seed_offline.py` (offline behavior,
  no-overwrite, collision reporting, no registry write), and collision tests in
  `tests/test_registry_preservation.py`.
- `tests/conftest.py` `seeded_db` now seeds a collision-free copy of the base
  model manifest so the (intentionally failing-closed) live model tree does not
  block the persistence suite.

---

## 5.2 Correction — stub-based retirement (2026-08-10, correction worker)

The retirement in §5.1 was revised: moving the raw live-fetch helpers into
`ledger/scripts/retired/` and exempting that directory from the no-network
policy is **not** fail-closed, because the raw copies remained on disk and
directly executable.

The revised, fully fail-closed end-state:

- **Restored the nine tracked legacy entrypoints** (`check_*.py`, `dump_tables.py`,
  `test_hf_urls.py`) **in place** as minimal no-network stubs that immediately
  exit with a clear governed-SafeFetch message and perform no socket I/O.
- **Removed the runnable raw-network `scripts/retired/` directory** entirely.
  History is preserved through git only; no executable raw-network copy is
  retained on disk or in the index.
- **The static policy** (`tests/test_no_network_tooling.py`) now inspects
  **on-disk** runnable `app/` and `scripts/` Python (including untracked task
  outputs), uses the filesystem rather than `git ls-files`, **does not exempt**
  any directory that could hold raw network code, and allows only the governed
  `app/ingestion/safe_fetch.py` seam.
- Focused tests assert: each legacy entrypoint **cannot network even when
  invoked** (runs, exits non-zero, prints a retired message), **no runnable raw
  network copy** is retained, the HF seed tool stays offline with exclusive
  no-overwrite output and collision reporting, registry-ID collisions leave the
  database **unchanged**, and **no worker-owned path is staged** in the shared
  index.
- `ledger/app/registry/seed_loader.py` still rejects *all* cross-file duplicate
  model/benchmark IDs (byte-identical or not) before any durable write, and its
  docstring matches that all-duplicates-rejected behavior. The three genuine
  collisions (`claude_3_7_sonnet`, `deepseek_v3`, `gpt_4o_mini`) remain
  **unresolved** for governance; no row was chosen.