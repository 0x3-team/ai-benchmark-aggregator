# Fix Report: csf_99f038f70e2f1fab37c3eb7a — Silent partial registry reconciliation

- Finding: **F12 — Silent partial registry reconciliation** (`occ_9aea26568c5ca71863bf2f20` in `report.md`)
- Worker: supervised Orca worker `term_c9388fe3-fea5-4e92-9022-702db34193b4`
- Task: `task_0a9b75e334ba`; Dispatch: `ctx_17090d3f8df6`
- Route receipt: Command Code v1.15.0; active config `deepseek/deepseek-v4-flash`; banner `deepseek-v4-flash-(latest)`, max effort; canary passed on `main` at `5eb3b35e35867e6b56837d7fc9b67e120c423b45` with an empty index. Route, branch, worktree, model, and effort were not changed.
- Outcome: **FIXED**

## Invariant

Every authoritative benchmark/model file is loaded and strictly validated exactly once before any durable write; the same validated entry snapshot feeds both the cross-file duplicate-ID scan and the durable upserts. Missing/null/wrong-type collection, non-mapping row, blank/missing `id`, or malformed aliases raise a deterministic `ValueError` naming the file, kind, and 0-based row index where applicable — before any durable write.

## Path

`ledger/app/registry/seed_loader.py`

## Patch (narrow, no production weakening)

1. `_validate_entity_ids(files, kind)` now **returns** `dict[Path, list[dict[str, Any]]]` — one validated `_strict_entries` snapshot per authoritative file — instead of `None`. It delegates row/collection/alias validation to the existing `_strict_entries` (the same fail-closed checks, unchanged error messages) and still rejects cross-file duplicate IDs before any durable write.
2. `_seed_registry_changes` gains `benchmark_entries_by_file` / `model_entries_by_file` parameters and consumes those snapshots in the write loops instead of re-calling `_strict_entries(_load_yaml(...))` per file. Every file is now loaded and validated **exactly once** (in the preflight); the write loops no longer re-read or re-parse the files, so a file mutated between preflight and write cannot silently reconcile differently from what was validated.
3. `seed_registry` captures the returned snapshots and threads them into `_seed_registry_changes`.

Preserved unchanged: explicit canonical allowlist + sibling exclusion (`_registry_files` with `benchmarks_curated.yaml` / `models_frontier.yaml`), cross-file duplicate rejection, partial-manifest no-retirement default, retirement guard, `session.begin_nested()` all-or-nothing behavior, alias batching (`add_aliases_bulk`), count semantics, idempotency, and bounded SELECT/query behavior.

## Fixture correction

The two failing tests in `ledger/tests/test_security_remediation_regressions.py` used valid authoritative model fixtures that omitted required NOT NULL `ModelEntity` columns (`display_name`, `entity_type`), so the seed hit `NOT NULL constraint failed: model_entities.display_name` and the test failed at the write, not at the assert. The task-specified "valid authoritative model fixtures" were corrected by adding the required `display_name` (and `entity_type`, also required NOT NULL) to the canonical/frontier fixtures and to the review-only/arbitrary fixtures that must remain **excluded**. Production code was not weakened: `display_name`/`entity_type` remain required NOT NULL columns; a fixture omitting them still fails closed at the database.

## Load-once regression (rework)

Added `test_each_authoritative_registry_file_loaded_exactly_once` in `ledger/tests/test_security_remediation_regressions.py`. It monkeypatches `app.registry.seed_loader._load_yaml` to count each exact `Path`, seeds valid canonical benchmark/model files plus the explicit `benchmarks_curated.yaml` and `models_frontier.yaml` overlays, then asserts:

- Each selected authoritative benchmark path (`benchmarks.yaml`, `benchmarks_curated.yaml`) and model path (`models.yaml`, `models_frontier.yaml`) has load count exactly 1.
- Unselected siblings (`models_demo.yaml`, `models_hf_seed.yaml`) have load count 0 — no promotion.
- Legitimate control: the seeded `Benchmark` IDs are `{"b1", "b2"}` and the seeded `ModelEntity` IDs are `{"m1", "m2"}`, proving the single validated load fed the durable writes.

The count assertion is load-bearing: in the former implementation the write loops called `_strict_entries(_load_yaml(...))` a second time per file, so every authoritative path was necessarily loaded twice (count 2); the current implementation loads each authoritative file exactly once in `_validate_entity_ids` and reuses that validated snapshot in `_seed_registry_changes`. The test passes on the current code and fails on the former reload behavior by construction.

Truthful note on `seed_loader.py` during rework: to demonstrate the regression, the worker began a temporary mutation of `seed_loader.py` back toward the former reload behavior — outside the rework ownership. The coordinator interrupted before the demonstration completed. The worker then reversed only those two temporary write-loop edits, removed its exact task-created scratch backup (inside the Command Code scratchpad), and verified the final production file hashes to `6c5216c22da8f560d9bed1cc5b4f0fef6a78aa4f` before running the final tests. There is **no persistent production delta from the rework**; `seed_loader.py` is byte-identical to the accepted F12 fixed state.

## Exact commands and counts

Baseline (before edits):

```
cd ledger && uv run pytest -q tests/test_security_remediation_regressions.py
FF...............  [100%]
2 failed, 15 passed in 4.14s
```

Failures were both `sqlite3.IntegrityError: NOT NULL constraint failed: model_entities.display_name` on the valid fixture writes.

After edits (raw and unpiped):

```
cd ledger && uv run pytest -q tests/test_security_remediation_regressions.py
..................  [100%]
18 passed in 4.19s

cd ledger && uv run pytest -q tests/test_security_remediation_regressions.py::test_each_authoritative_registry_file_loaded_exactly_once
.  [100%]
1 passed in 0.33s

cd ledger && uv run pytest -q tests/test_registry_preservation.py
..............  [100%]
14 passed in 4.90s

cd ledger && uv run pytest -q tests/test_registry_seed_perf.py
...  [100%]
3 passed in 1.56s

git diff --check
(no output — clean)
```

Note: the rework added one load-once test, so the security-regression suite is now **18 passed** (17 prior tests + the new load-bearing `test_each_authoritative_registry_file_loaded_exactly_once`). The `1 passed` single-test run is the exact command/count for the new regression.

Adjacent-suite verification (not part of the four required checks): `tests/test_migrations.py` → 34 passed (run in the prior F12 task, before the bounded task was cut off). The full ledger suite was not completed in either bounded task and was not rerun.

## Legitimate control proof

The owned regression file already covers the fail-closed classes. Re-verified passing after the patch:

- Wrong-type `models`/`benchmarks` collection → `ValueError`, zero writes.
- Non-mapping entry (bare string) → `ValueError`, zero writes.
- Id-less registry entry (model and benchmark) → `ValueError`, zero writes.
- Malformed overlay (`models_frontier.yaml` id-less entry, `benchmarks_curated.yaml` wrong-shaped aliases) → `ValueError`, zero writes to either entity table, including when the caller flushes after catching.
- Valid canonical + frontier models seed exactly 2 rows; review-only `models_hf_seed.yaml` unique id and arbitrary `models_demo.yaml` sibling are excluded (no promotion).

Additionally verified in the sibling-exclusion tests after the fixture fix: the review-only model `only-in-review` is **not** present as a `ModelEntity`, and the arbitrary sibling `sneaky` is **not** present — the allowlist is still effective (the fixtures being valid did not weaken exclusion).

## Original issue non-reproduction

The pre-fix behavior of re-loading/parsing in the write loop is gone; a mutated-in-place file can no longer reconcile differently from the preflight snapshot. `_validate_entity_ids` is the single validation pass, and `seed_registry` passes its return value directly to `_seed_registry_changes`, so the preflight-validated entries are exactly the durable-written entries. No path silently skips a malformed row: `_strict_entries` raises before any write for every malformed class above.

## Bypass review

- `_registry_files` still returns the explicit canonical file plus the explicit overlay only (`benchmarks_curated.yaml`, `models_frontier.yaml`); arbitrary `models*.yaml` siblings (including `models_hf_seed.yaml`, `models_demo.yaml`, `models_review.yaml`) are excluded by construction and verified by tests.
- Duplicate IDs across files are still rejected before any write; no "first file wins".
- Retirement only occurs with `retire_missing=True`; programmatic/library callers default to no retirement.
- Alias batching and bounded SELECT counts unchanged (`test_registry_seed_perf` exact-3-SELECT assertion passes).
- No network, provider, browser, Cloudflare, GitHub, live database, staging, commit, push, deploy, or deletion was performed.

## Remaining uncertainty

- The full ledger suite was not completed in either bounded task (the first was aborted at ~74% by the task bound; the rework did not rerun it). A full-suite run by the coordinator is the remaining confirmation that no other caller regressed. No claim is made here about any mid-suite failure because its exact test node and output were not captured.
- `seed_loader.py` is outside the rework ownership. During the rework the worker did begin a temporary former-behavior mutation of the file (interrupted by the coordinator); it then reversed only those edits and verified the final production file hashes to `6c5216c22da8f560d9bed1cc5b4f0fef6a78aa4f` before the final tests. There is no persistent production delta from the rework.

## Files modified (task-owned)

- `ledger/tests/test_security_remediation_regressions.py`
- `docs/audits/2026-08-10-codex-security-deep-scan/fix_report.md`

`ledger/app/registry/seed_loader.py` remains at the accepted F12 fixed state from the prior task (verified by blob hash) and is listed here only as the referenced production file, not as a rework modification. No persistent task-caused delta remains outside the owned paths; git index is empty (no staged changes).

---

# Fix Report: csf_ecf43ce83d91cefb330998d6 — Raw discovery exception disclosure to CLI output

- Finding: **F3 — Raw discovery exception disclosure to CLI output** (`occ_2eb9113574659e19e25f6741` in `report.md`)
- Worker: supervised Orca worker `term_c9388fe3-fea5-4e92-9022-702db34193b4`
- Task: `task_3b7283da5759`; Dispatch: `ctx_95294afb77e4`
- Route receipt: Command Code v1.15.0; active config `deepseek/deepseek-v4-flash`; banner `deepseek-v4-flash-(latest)`, max effort. Route, branch, worktree, model, and effort were not changed.
- Outcome: **FIXED**

## Invariant

The discovery failure path emits exactly one bounded JSON object on stderr with the stable keys `availability: candidate_only`, `status: failed_closed`, `reasonCode: DISCOVERY_INPUT_REJECTED`, and `detail: "Discovery input was rejected."`. Raw exception text, class names, file paths, filenames, parser/provider/OS/DB detail, secrets, and terminal control bytes must never appear. Exit 2 is preserved, no traceback, success behavior unchanged, and the failed-target path keeps exit 1.

## Path

`ledger/app/cli.py` — `_fail_discovery`

## Patch (narrow, no production weakening)

Replaced `"detail": str(exc)` with the stable generic `"detail": "Discovery input was rejected."` in `_fail_discovery`. The `exc` parameter remains accepted (unused) so all four call sites and the exit-2 contract are unchanged. JSON keys, `sort_keys=True`, stderr output, and `typer.Exit(code=2)` are preserved.

## Adversarial test-first (RED)

Added `test_discovery_failure_never_discloses_raw_exception_detail` in `ledger/tests/test_discovery_cli.py`. It monkeypatches the CLI module-level `load_manifest` to raise `DiscoveryManifestError` carrying one sentinel string containing a private path (`/private/tmp/secret-ops/credentials.json`), a filename (`provider-auth-secret.json`), provider detail (`smtp-relay-internal-vendor`), a DB URL with embedded secret (`postgres://user:secret@10.0.0.8/prod`), and an ESC/OSC terminal-control sequence (`\x1b]0;evil-title\x07\x1b[31m`), then invokes the real `discovery plan` command with any fixture root.

RED captured before the fix: the payload's `detail` was the full sentinel string, exposing every component including the control bytes.

## Exact commands and counts (raw and unpiped)

```
cd ledger && uv run pytest -q tests/test_discovery_cli.py
.....  [100%]
5 passed in 0.74s

cd ledger && uv run pytest -q tests/test_discovery_manifest.py
..............  [100%]
14 passed in 0.08s

cd ledger && uv run pytest -q tests/test_discovery_controller.py
........  [100%]
8 passed in 2.07s

cd ledger && uv run pytest -q tests/test_discovery_planner.py
........................  [100%]
24 passed in 0.05s

git diff --check
(no output — clean)
```

Focused RED check (before the production fix): `uv run pytest -q tests/test_discovery_cli.py::test_discovery_failure_never_discloses_raw_exception_detail` → 1 failed, with the sentinel leaked in `detail`.

## Legitimate control proof

The pre-existing `test_invalid_manifest_exits_two_with_bounded_error` still passes: a real invalid manifest exits 2 with `reasonCode DISCOVERY_INPUT_REJECTED`, `availability candidate_only`, and now also asserts `status failed_closed`. The new adversarial test asserts the exact four-key JSON payload, exit 2, and the absence of every sentinel component plus the bare `\x1b` ESC byte in both stderr and stdout.

## Bypass review

- All four `_fail_discovery` call sites (`_load_discovery_inputs`, `discovery_plan` planner errors, `discovery_run` connector/controller/planner/persistence errors) route through the same bounded emitter, so no call path can re-introduce raw detail.
- The `detail` value is a constant string; `sort_keys=True` and the single `typer.echo(..., err=True)` guarantee one parseable JSON object with no traceback.
- The failed-target path (`run_outcome == "failed"`) still emits the receipt on stdout and exits 1 — unchanged.
- No network, provider, browser, Cloudflare, GitHub, live database, staging, commit, push, deploy, or deletion was performed.

## Remaining uncertainty

- Only the four required discovery suites plus `git diff --check` were run in this bounded task; a full ledger-suite run by the coordinator is the remaining confirmation that no other caller regressed.

## Files modified (task-owned)

- `ledger/app/cli.py` (only the `_fail_discovery` hunk; other hunks shown by `git diff` are pre-existing shared-worktree changes from other owners)
- `ledger/tests/test_discovery_cli.py`
- `docs/audits/2026-08-10-codex-security-deep-scan/fix_report.md` (this appended F3 entry)

Git index is empty (no staged changes).

---

# Fix Report: csf_ec97e56661bcb001ac5fb4c5 — PATH-hijacked acceptance smoke executable

- Finding: **F4 — PATH-hijacked acceptance smoke executable** (`occ_3498067ccad1626d6f469101` in `report.md`; `csf_ec97e56661bcb001ac5fb4c5` in `findings.json`)
- Worker: supervised Orca worker `term_c9388fe3-fea5-4e92-9022-702db34193b4`
- Task: `task_fc2aca40cd61` (original), `task_6762dc18a2d1` (rework), `task_a3d279b141a5` (final rework), `task_47233562e620` (R4); Dispatches: `ctx_d1c22836d524`, `ctx_1cbe32afb73c`, `ctx_c6ded9e99107`, `ctx_71b67b22aee3`
- Route receipt: Command Code v1.15.0; active config `deepseek/deepseek-v4-flash`; banner `deepseek-v4-flash-(latest)`, max effort. Route, branch, worktree, model, and effort were not changed.
- Outcome: **FIXED**

## Invariant

The acceptance smoke script must invoke the repository virtualenv executable by absolute path (`PROJECT/.venv/bin/benchmark-ledger`), require it to be a regular (non-symlink) executable file, and must never resolve `benchmark-ledger` from `PATH`. If the pinned binary is missing, not a regular file, or a symbolic link, the script fails closed with exit 1 — a PATH-preceding impostor or a symlink-redirected executable can never impersonate the intended CLI.

## Path

`ledger/scripts/mvp_acceptance.sh`

## Patch (narrow, no production weakening)

Replaced the PATH-preferring resolution block with a pinned absolute-path, regular-file gate:

- `HERE="$(cd "$(dirname "$0")" && pwd -P)"` and `PROJECT="$(cd "$HERE/.." && pwd -P)"` — the physical (symlink-free) project root, so a directory-symlink alias of the script location still pins the real repo path.
- `LEDGER_CLI="$PROJECT/.venv/bin/benchmark-ledger"` (absolute path, computed from the script's own location).
- `if [ -L "$LEDGER_CLI" ]` → `FATAL` (symbolic link rejected) to stderr and `exit 1`.
- `if [ ! -f "$LEDGER_CLI" ] || [ ! -x "$LEDGER_CLI" ]` → `FATAL` (missing or non-executable) to stderr and `exit 1`.
- Removed `command -v` PATH lookup and the `PATH="$PROJECT/.venv/bin:$PATH"` fallback entirely.
- `work_dir="$(mktemp -d)"` followed immediately by `trap 'rm -rf "$work_dir"' EXIT`, then `work_dir="$(cd "$work_dir" && pwd -P)"` canonicalizes the temp dir to its fully physical path. On macOS, `/var` is a symlink to `/private/var`, and `init-db`'s descriptor-relative `O_NOFOLLOW` parent walk fails closed when any ancestor is a symlink; resolving to the physical path keeps the SQLite URL symlink-free. Placing the trap before canonicalization ensures a `cd`/`pwd -P` failure cannot leak the temp dir.

All invocations (`init-db`, `seed-registry`, `db preflight`, `ingest --dry-run`) use the pinned absolute path. `set -euo pipefail`, the temporary-database containment, the trap cleanup, and the pass/fail assertions are unchanged.

## Tests (GREEN)

`ledger/tests/test_mvp_acceptance_script.py` contains three tests using a `_capable_cli(marker, log_env)` helper that generates a `#!/bin/bash` fake CLI using only bash builtins `printf`/`case`/`exit` plus shell redirection (no `mkdir`/`cat`/`tee`/`env`/`dirname`/`touch` and no `if`/`[`). After appending the exact `"$*"` once to its env log, it prints its unique marker unconditionally, then dispatches on the exact full `"$*"` string for the four accepted calls. The repo CLI uses marker `REPO-VENV-CLI`/`REPO_CALL_LOG`; the PATH impostor uses `PATH-IMPOSTOR`/`PATH_CALL_LOG`; the external target uses `EXTERNAL-TARGET`/`EXTERNAL_CALL_LOG`. All subprocess invocations begin `["/bin/bash", str(script)]`.

1. `test_acceptance_script_runs_full_smoke_via_pinned_venv_with_exact_ordered_repo_log` — the script is invoked through a directory symlink alias to the physical project with a capable PATH (impostor dir first, standard tools still resolvable). Asserts exit 0, `CONTAINMENT SMOKE PASSED`, `REPO-VENV-CLI` present, `PATH-IMPOSTOR` absent, the physical `project.resolve()/.venv/bin/benchmark-ledger` pinned path printed, the alias pinned path absent, and the exact ordered repo log `["init-db", "seed-registry", "db preflight", "ingest --source fake_local_fixture --dry-run"]` with the PATH log absent.
2. `test_acceptance_script_fails_closed_when_venv_binary_is_missing` — with the venv binary removed and only the PATH impostor present, the script must exit 1, print `FATAL`, never print `PATH-IMPOSTOR`, and leave the PATH log absent.
3. `test_acceptance_script_fails_closed_when_venv_binary_is_a_symlink` — with the venv binary replaced by a symlink to a real capable external executable under `tmp_path` (outside `.venv`), the script must exit 1 with a `symbolic link` FATAL message, never print `PATH-IMPOSTOR` or `EXTERNAL-TARGET`, and leave both the PATH and EXTERNAL logs absent.

## Exact commands and counts (raw and unpiped)

```
cd ledger && uv run pytest -q tests/test_mvp_acceptance_script.py
...  [100%]
3 passed in 0.45s

cd ledger && uv run pytest -q tests/test_mvp_acceptance_script.py tests/test_cli_import_boundary.py tests/test_security_remediation_regressions.py
........................  [100%]
24 passed in 7.06s

cd /Users/stevmq/Documents/ai-benchmark-aggregator && git diff --check
(no output — clean)

cd /Users/stevmq/Documents/ai-benchmark-aggregator/ledger && bash -n scripts/mvp_acceptance.sh
(no output — syntax OK)
```

## Raw real smoke receipt

`cd /Users/stevmq/Documents/ai-benchmark-aggregator/ledger && bash scripts/mvp_acceptance.sh` — exit 0, `CONTAINMENT SMOKE PASSED`. Selected exact output lines:

```
> /Users/stevmq/Documents/ai-benchmark-aggregator/ledger/.venv/bin/benchmark-ledger init-db
Initialized database: sqlite:////private/var/folders/ck/xs13v7617m71z8k4mtxh2bz80000gn/T/tmp.A07Qh2vtXm/benchmark_ledger.db
> /Users/stevmq/Documents/ai-benchmark-aggregator/ledger/.venv/bin/benchmark-ledger seed-registry
Seeded: {'benchmarks': 42, 'models': 105, 'aliases': 607, 'sources': 53, 'source_revisions': 53, 'sources_retired': 0}
> /Users/stevmq/Documents/ai-benchmark-aggregator/ledger/.venv/bin/benchmark-ledger db preflight
> /Users/stevmq/Documents/ai-benchmark-aggregator/ledger/.venv/bin/benchmark-ledger ingest --source fake_local_fixture --dry-run (expected block)
Ingestion blocked: No production-eligible source for fake_local_fixture: no matching active source
CONTAINMENT SMOKE PASSED
```

The temporary database URL is under the fully physical `/private/var/...` path, so `init-db`'s `O_NOFOLLOW` parent walk succeeds and the whole smoke passes.

## Legitimate control proof

- The repo venv binary exists (`ledger/.venv/bin/benchmark-ledger`, regular executable), and the script is invoked as `bash scripts/mvp_acceptance.sh`, so `HERE`/`PROJECT` resolve to the real repo and the pinned absolute path is correct.
- `test_cli_import_boundary.py` still passes (`benchmark-ledger --help` via the same absolute venv path), exercising the real venv binary.
- The fake-tree tests prove: the full four-call smoke genuinely succeeds through the pinned venv CLI with exact ordered repo logs; the PATH impostor never runs; missing and symlinked binaries both fail closed with exit 1, leaving the PATH and EXTERNAL logs absent.

## Bypass review

- No `command -v`, `which`, `PATH` prepend, or bare-name invocation remains; every CLI call uses the absolute `LEDGER_CLI` path.
- A symlinked venv binary is rejected up front (`-L` gate), closing the link-redirection vector.
- An actor who can write the repository virtualenv can still replace the regular executable; this fix closes PATH and symlink substitution, not repository-write compromise.
- `set -euo pipefail` and the exit-1 fail-closed contract are preserved; success behavior is unchanged.
- No network, provider, browser, Cloudflare, GitHub, live database, staging, commit, push, deploy, or deletion was performed.

## Remaining uncertainty

- Only the acceptance-script tests plus the related CLI-import and security-remediation suites were run in this bounded task; a full ledger-suite run is the remaining confirmation that no other caller regressed.
- The real smoke passes on this macOS host (verified exit 0 with the physical temp-path canonicalization); a CI run on Linux is optional further confirmation.

## Files modified (task-owned)

- `ledger/scripts/mvp_acceptance.sh`
- `ledger/tests/test_mvp_acceptance_script.py`
- `docs/audits/2026-08-10-codex-security-deep-scan/fix_report.md` (this appended F4 entry)

Git index is empty (no staged changes).

---

# Fix Report: csf_f5754c0ddec0ba3a9dba769e — Terminal control injection in raw claim and review output

- Finding: **F14 — Terminal control injection in raw claim and review output** (`occ_bf5fc2403e720e1aa29e0f91` in `report.md`; `csf_f5754c0ddec0ba3a9dba769e` in `findings.json`)
- Worker: supervised Orca worker `term_c9388fe3-fea5-4e92-9022-702db34193b4`
- Routes: `task_ba8bb15ff605`/`ctx_231345ef725c` (initial — stopped on a false hash-method collision, no edits); `task_24ade381f1c3`/`ctx_2dda4cab8ff7` (implementation, baselines confirmed via plain `shasum`); `task_102865bc44eb`/`ctx_b83c24568bd7` (acceptance rework); `task_5955ac317cae`/`ctx_daf67fb372f6` (final mechanical correction — three exact test corrections and truthful RED/task report corrections; `cli.py` not edited)
- Route receipt: Command Code v1.15.0; active config `deepseek/deepseek-v4-flash`; banner `deepseek-v4-flash-(latest)`, max effort. Route, branch, worktree, model, and effort were not changed.
- Outcome: **FIXED** (final correction: dry-run `capture_status` exact `needs\x9breview` visible-escape assertion; backslash test exact-line assertions via `out.splitlines()`; queue test exact reason-line single-pass assertions via `out.splitlines()`; truthful task-route and RED receipt)

## Invariant

CLI terminal output must never carry raw control bytes or control/format code points from durable values (claims, review, ingestion). A central renderer accepts any value via `str(value)`, preserves ordinary printable Unicode, renders a literal backslash visibly as `\\`, renders LF/CR/TAB/BS/FF as visible short escapes (`\n`/`\r`/`\t`/`\b`/`\f`), and renders every other Unicode Cc/Cf code point (ESC, BEL, DEL, C1 CSI/OSC, bidi controls, …) as lowercase visible escapes (`\xNN` ≤ 0xff, `\uNNNN` ≤ 0xffff, `\UNNNNNNNN` otherwise). Durable values are never rewritten — only the terminal projection changes. Source-embedded newlines render as text; Typer layout newlines are unchanged.

## Path

`ledger/app/cli.py`

## Patch (narrow, no production weakening)

Added `_terminal_render(value)` and `_is_control_or_format(code)` as one central helper (module-private), then applied `_terminal_render` at every F14 sink:

- **Ingestion summary errors** (`IngestionBlockedError`, `DatabaseMigrationError`, `SafeFetchError.code`, `summary.errors`, `summary.status`) and **every dry-run sample field** (`model_raw`, `score_raw`, `capture_status`).
- **Claims list** — every field: `id`, `benchmark_id or benchmark_raw`, `model_raw`, `score_raw`, `capture_status`.
- **Claims show and review show (delegation)** — every value including `id`, `model_raw`, `captured_model_entity_id`, `effective_model_entity_id`, `chain_error`, `benchmark_raw`, `benchmark_id`, `score_raw`, `capture_status`, `evidence_location`, `source_snapshot_id`, `official_source_id`.
- **Review queue** — `Claim ID`, `Benchmark`, `Model raw`, `Score raw`, `Reason` (chain-error reason), `Evidence`, and the `Next cursor` continuation token; the invalid-cursor error is sanitized too.
- **Review map-model** — error message, `claim_id`, `model_entity_id`, `decision_id`.

Identifiers and status strings are sanitized at the same sinks. No durable column/row is modified.

## Test-first (RED), GREEN, and acceptance rework

Added `ledger/tests/test_cli_terminal_safety.py` using the real Typer app (`CliRunner`) with monkeypatched repo/session/ingestion seams. Adversarial values span `model_raw`, `benchmark_raw`, `score_raw`, `evidence`, `chain_error`, identifiers, and status strings and include ANSI CSI (`\x1b[31m`), OSC+BEL (`\x1b]0;…\x07`), CR, embedded newline, backspace, literal backslash, C1 CSI (`\x9b`), bidi (`\u202e`), LRM (`\u200e`), and astral Cf (U+E0001). The eight tests cover:

- `test_terminal_render_helper_full_edge_cases` — exact, deterministic renderer behavior for every documented class (short escapes, backslash, `\xNN`/`\uNNNN`/`\UNNNNNNNN`, printable Unicode incl. emoji/CJK preserved, non-string values via `str()`).
- `test_claims_terminal_output_never_leaks_control_bytes[list|show]` — claims list/show with control bytes in identifiers and status too.
- `test_review_show_delegation_sanitizes_values` — review show (delegates to claims show).
- `test_review_queue_single_pass_reason_rendering` — asserts the chain-error reason renders exactly once (output contains `chain\ninjected`, not `chain\\ninjected`), so an escaped value is never re-escaped.
- `test_ingest_dry_run_sample_and_summary_error_are_sanitized` — dry-run samples and summary errors.
- `test_literal_backslash_renders_exactly_in_claims_show` — exact: `C:\temp\file` renders as `C:\\temp\\file` (each `\` → `\\` once).
- `test_identifier_and_status_controls_are_sanitized` — control bytes in `claim_id`, `model_entity_id`, `benchmark_id`, `capture_status` are escaped.

RED captured before the fix (initial raw, unpiped run):

```
cd ledger && uv run pytest -q tests/test_cli_terminal_safety.py
FFFFF.  [100%]
5 failed, 1 passed in 1.89s
```

Truthful breakdown of that initial RED: **four** failures were genuine security leaks (raw control bytes/sequences verbatim in `result.output`, e.g. `c1 | b\x1b]0;evil-title\x07y | m\x1b[31mx | s\x9bz`) and **one** failure was a test-fixture defect (`ReviewQueuePage.__init__() missing 'scanned'`), which was fixed in the test before the production change. A later "5-security/1-pass" observation was captured through a piped `2>&1 | tail` command and is **not** a reliable exit receipt; the authoritative RED is the raw run above. The corrected test suite (8 tests) passes after the fix.

## Exact commands and counts (raw and unpiped, final correction)

```
cd ledger && uv run pytest -q tests/test_cli_terminal_safety.py
........  [100%]
8 passed in 1.91s

cd ledger && uv run pytest -q tests/test_cli_containment.py tests/test_review_queue.py tests/test_ingestion_runner_transactions.py tests/test_cli_import_boundary.py
.........................  [100%]
25 passed in 10.71s

cd ledger && uv run pytest -q tests/test_security_remediation_regressions.py
..................  [100%]
18 passed in 4.58s

cd /Users/stevmq/Documents/ai-benchmark-aggregator && git diff --check
(no output — clean)
```

The full helper edge-case coverage is an in-file test (`test_terminal_render_helper_full_edge_cases`) asserting exact strings: C1 CSI → `\x9b`, bidi → `\u202e`, LRM → `\u200e`, ESC/BEL/DEL → `\x1b`/`\x07`/`\x7f`, astral Cf → `\U000e0001`, backslash → `\\`, `\r\t\b\f` → visible short escapes, embedded `\n` → visible `\n`, printable Unicode (incl. emoji and CJK) preserved exactly. The final correction's three exact assertions: dry-run `capture_status` renders as `needs\x9breview`; backslash `model_raw: mC:\temp\file` renders as the exact line `model_raw: mC:\\temp\\file` with the raw-single-backslash line absent; the queue reason line is exactly `Reason: review chain invalid: chain\ninjected` (single backslash) with the double-escaped line absent.

## Controls and bypass attempts

- No raw control byte survives stdout/stderr for any tested sink; the adversarial values render as visible escapes.
- No injected output line appears: an embedded newline renders as the two-character visible `\n` escape, so adversarial text never starts a new terminal line (asserted as no `\n`+token sequence).
- Printable Unicode stays readable; literal backslashes are unambiguous (`\\`).
- The helper is applied at the same sinks for identifiers/status, so a control byte smuggled in an id or status is escaped too.
- Durable values are untouched: the renderer is projection-only and no repository/DB write path is involved.
- Not in scope (kept narrow per task): `snapshots list` `raw_content_uri`, discovery/reporting markdown output, and JSON export paths were not modified.

## Residual risk

- The renderer covers the listed F14 sinks; any future CLI command that echoes a durable value must use `_terminal_render` to stay safe. The helper is module-private in `cli.py`.
- Review-reason rendering is single-pass: `_render_review_queue_item_reason` returns raw strings and `_render_review_queue_item` renders the joined reason exactly once, so an escaped value is never re-escaped (verified by the `chain\ninjected` assertion).
- Type/import hygiene: `unicodedata` is a top-level import; the test module has no unused imports.
- The full ledger test suite was not run in this bounded task; the focused and related suites above are green, and a full-suite run by the coordinator remains the final confirmation.

## Files modified (task-owned)

- `ledger/app/cli.py` (only the `_terminal_render`/`_is_control_or_format` helper and the F14 sink applications, including the single-pass review-reason fix; other hunks shown by `git diff` are pre-existing shared-worktree changes from other owners)
- `ledger/tests/test_cli_terminal_safety.py` (new)
- `docs/audits/2026-08-10-codex-security-deep-scan/fix_report.md` (this appended F14 entry)

Git index is empty (no staged changes).

---

# Fix Report: csf_dbd47cf5cbba4a7e414da683 — Caller-controlled review actor attribution

- Finding: **F17 — Caller-controlled review actor attribution** (`occ_d059a59adf0f369a1f16ab92` in `report.md`; `csf_dbd47cf5cbba4a7e414da683` in `findings.json`)
- Worker: supervised Orca worker `term_c9388fe3-fea5-4e92-9022-702db34193b4`
- Routes: `task_1d8aa4305447`/`ctx_6004431dde32` (R1 — initial implementation); `task_306a1d352386`/`ctx_026fc0297f59` (R2 — acceptance rework, this entry)
- Route receipt: Command Code v1.15.0; active config `deepseek/deepseek-v4-flash`; banner `deepseek-v4-flash-(latest)`, max effort. Route, branch, worktree, model, and effort were not changed.
- Outcome: **FIXED** (accepted after coordinator rework and independent local verification)

## R1 rejection reason

R1 bound the actor to a bare passwd name via a top-level `import pwd` and `os.getuid()`. It was rejected because: the top-level `pwd` import makes the whole CLI unimportable on a platform without the module; the bare-name actor was not canonical (no UID binding, so a later name/UID change is ambiguous); `os.getuid()` is the real UID rather than the effective UID; no strict validation existed (blank/control names, UID mismatch, overlong values); and the report did not reconcile the rejection. R2 addresses all of these in place.

## Invariant

The review map-model CLI must never persist caller-supplied provenance. The stored `ClaimReviewDecision.actor` is a canonical value `posix:euid=<decimal>;name=<name>` resolved from the effective UID (`os.geteuid()`) and the passwd database record for that exact UID (never `USER`/`LOGNAME`/`getpass`). The passwd lookup is lazy (inside the helper), so the CLI stays importable without `pwd` and only map-model fails closed. The record's `pw_uid` must exactly equal the requested euid, the name must be nonempty and free of control/format characters, and the canonical value must fit the persisted `String(128)` field. Any failure raises one stable `LookupError` and the command exits 2 before a DB session or write. Append-only review semantics, raw claims, capture status, validation status, publication state, and terminal escaping are preserved.

## Path

`ledger/app/cli.py` (narrow F17 hunks only)

## Patch (narrow, no production weakening)

- Removed the top-level `import pwd`; `pwd` is imported lazily inside `_os_principal()` so the full CLI remains importable on platforms without it.
- Added `_os_principal()` returning the canonical `posix:euid=<decimal>;name=<name>`:
  - requires `os.geteuid` (else one stable `LookupError`);
  - lazily imports `pwd` (ImportError → same stable `LookupError`);
  - `pwd.getpwuid(euid)` (KeyError → `LookupError`);
  - verifies `record.pw_uid == euid` exactly (mismatch → `LookupError`);
  - requires a nonempty `str` name (else `LookupError`);
  - rejects control/format characters in the name via the existing F14 `_is_control_or_format` (else `LookupError`);
  - rejects any canonical value over the `String(128)` bound (128 UTF-8 bytes, no truncation; else `LookupError`).
- Removed the `actor: str = typer.Option("cli", "--actor", ...)` CLI option from `review_map_model`; the command resolves the actor via `_os_principal()` and fails closed (exit 2, `Review mapping blocked: …`) before opening a DB session or calling `append_manual_model_mapping`.
- `ledger/app/db/repositories.py` and `ledger/app/db/models.py` were **not** modified (verified unchanged at baseline shasums).

## Test-first (RED) and GREEN

`ledger/tests/test_f17_actor_boundary.py` was extended to **10 tests** — 7 direct production-helper tests plus 3 CLI tests:

Direct helper tests (each fails closed):
- `test_helper_missing_geteuid_fails_closed` — no `os.geteuid`.
- `test_helper_missing_pwd_module_fails_closed` — `pwd` import raises `ImportError`.
- `test_helper_passwd_lookup_failure_fails_closed` — `pwd.getpwuid` raises `KeyError`.
- `test_helper_uid_mismatch_fails_closed` — `pw_uid != euid`.
- `test_helper_blank_or_control_name_fails_closed` — empty name and `\x1b`-containing name.
- `test_helper_overlong_value_fails_closed` — name that makes the canonical value exceed 128 bytes.
- `test_helper_success_returns_canonical_euid_and_name` — exact `posix:euid=<euid>;name=<name>`.

CLI tests:
- `test_cli_rejects_caller_supplied_actor_before_any_row` — `--actor` is no longer an option; the invocation fails with the exact Typer `No such option` output and writes zero rows (separate exact zero-row check).
- `test_cli_writes_os_bound_actor_even_with_forged_identity_env` — a legitimate command writes the canonical OS actor even when `USER`/`LOGNAME` are forged.
- `test_cli_fails_closed_when_trusted_principal_unresolvable_writes_zero_rows` — a real helper failure (monkeypatched `_os_principal`) exits 2 and writes zero rows.

The existing `test_manual_model_mapping_cli_is_registered_and_preserves_claim_fields` in `ledger/tests/test_review_queue.py` was updated: the forged `--actor` invocation asserts the exact `No such option` output (no `or` fallback), and the persisted actor is asserted to be the canonical `posix:euid=<euid>;name=<name>` value, not the forged env value.

RED captured (R1, raw, unpiped):

```
cd ledger && uv run pytest -q tests/test_f17_actor_boundary.py tests/test_review_queue.py::test_manual_model_mapping_cli_is_registered_and_preserves_claim_fields
FFFF  [100%]
4 failed in 3.67s
```

The failures demonstrated the defect: `--actor operator` was accepted (exit 0), the stored actor was the `"cli"` default instead of the OS principal under forged env, and `_os_principal` did not exist.

## Exact commands and counts (raw and unpiped, R2 final)

```
cd ledger && uv run pytest -q tests/test_f17_actor_boundary.py
..........  [100%]
10 passed in 1.72s

cd ledger && uv run pytest -q tests/test_review_queue.py
....  [100%]
4 passed in 1.91s

cd ledger && uv run pytest -q tests/test_cli_import_boundary.py
...  [100%]
3 passed in 1.39s

cd ledger && uv run pytest -q tests/test_cli_terminal_safety.py
........  [100%]
8 passed in 1.81s

cd ledger && uv run pytest -q tests/test_security_remediation_regressions.py
..................  [100%]
18 passed in 3.60s

cd /Users/stevmq/Documents/ai-benchmark-aggregator && git diff --check
(no output — clean)
```

## Plain shasums (R2 final)

- `ledger/app/cli.py` → `3a884c479fe3a3580aed8c1e0b3649fe3ee72b2d` (R2 canonical-actor fix applied)
- `ledger/tests/test_review_queue.py` → `f0b3eb653d0e1590b0105fd3a69fd2caf99671c4` (CLI test updated to canonical actor + exact `No such option` assertion)
- `ledger/tests/test_f17_actor_boundary.py` → `60e6f9dd5857ba94610ff7fb548cd1801b6774f5` (extended to 10 tests)
- `ledger/app/db/repositories.py` → `23fe1ad38427857c85e74292cfbf78eb326d7598` (unchanged, read-only)
- `ledger/app/db/models.py` → `64fba1cc6b17f902495af1d9b05ff966543ebae9` (unchanged, read-only)
- `docs/audits/2026-08-10-codex-security-deep-scan/fix_report.md` → F17 section reconciled in place

Git index is empty (no staged changes).

## Controls and bypass attempts

- Caller-supplied `--actor` is rejected before any row is written (Typer no longer accepts the option; exact `No such option` output asserted).
- Forged `USER`/`LOGNAME` environment values do not influence the stored actor; the passwd DB keyed by the effective UID is authoritative.
- Every helper failure mode (missing `pwd`/`geteuid`, passwd lookup failure, UID mismatch, blank/control name, overlong value) fails closed with one stable `LookupError`; a real helper failure through the CLI writes zero rows.
- The CLI remains importable on platforms without `pwd` (lazy import inside the helper).
- Existing controlled internal `repo.append_manual_model_mapping(..., actor="pytest")` calls in tests remain explicit; they are not exposed through the CLI boundary.
- Append-only decision chaining, raw claim fields, capture/validation/publication state, and the F14 terminal escaping are preserved.
- `repositories.py`/`models.py` were not modified; no schema change, no authentication invented.

## Residual risk

- `_os_principal` trusts the local passwd database; a compromised host with a poisoned passwd DB could still attribute a decision to a chosen name, but that is outside the CLI trust boundary this fix addresses.
- The full ledger suite was not run in this bounded task; the focused and related suites above are green, and a full-suite run by the coordinator remains the final confirmation.

## Files modified (task-owned)

- `ledger/app/cli.py` (narrow F17 hunks: lazy `pwd` import, `_os_principal()` canonical actor, `review_map_model` actor binding)
- `ledger/tests/test_review_queue.py` (updated the existing CLI map-model test)
- `ledger/tests/test_f17_actor_boundary.py` (extended focused F17 regression file)
- `docs/audits/2026-08-10-codex-security-deep-scan/fix_report.md` (this F17 entry reconciled in place)

Git index is empty (no staged changes).

---

# Fix Report: csf_1637ae892cde183ecaba427b — Unbounded official candidate report database amplification

- Finding: **F7 — Unbounded official candidate report database amplification** (`occ_6ca7ddd69179ebb14ce2db0b` in `report.md`; `csf_1637ae892cde183ecaba427b` in `findings.json`)
- Worker: supervised Orca worker `term_c9388fe3-fea5-4e92-9022-702db34193b4`
- Routes: `task_3e9fbc5b81df`/`ctx_5ea99af5b042` (R1 — rejected); `task_cd3e9a1136bf`/`ctx_765855eb8f9f` (R2); `task_373466daa8c3`/`ctx_5d8890e91a11` (R3); `task_4c95320c0442`/`ctx_d217c27c5960` (R4 — this entry)
- Route receipt: Command Code v1.15.0; active config `deepseek/deepseek-v4-flash`; banner `deepseek-v4-flash-(latest)`, max effort. Route, branch, worktree, model, and effort were not changed.
- Outcome: **FIXED** (accepted after coordinator rework and independent local verification)

## R3 cleanup

R3 reviewed the R2 source and report and made these narrow corrections without weakening bounds:

- **`FeedBatch` docstring** now truthfully describes the two load shapes: unique-ID loads (sources/revisions/models/benchmarks) are bounded by IN-chunk size and carry no SQL `LIMIT`; budgeted loads (snapshots and decision/validation rows) carry `LIMIT remaining + 1` per chunk with a persistent cross-chunk budget. The previous docstring falsely claimed every load applied an SQL `LIMIT`.
- **`_project_publication`** no longer takes the unused `claim` parameter (removed from the definition and the single call site in `_claim_record_batched`).
- **Snapshot loading** is documented as a deliberate bounded duplicate: the legacy report loads the full (SQL `LIMIT cap + 1`) snapshot set to surface orphan snapshots, while `FeedBatch` loads the claim-referenced subset under the same shared `MAX_SNAPSHOTS` cap for the candidate analysis. The two loads serve different row sets; `FeedBatch` remains a self-contained reusable context with its own cap guard, so no complexity was added to share the map.
- **Imports** were confirmed non-cyclic: `legacy_inventory` imports the shared caps and `FeedBatch` from `official_json`, which imports only `app.db` and `app.ingestion.admission`.

## R1 rejection reason

R1 was rejected after source review because: the aggregate cap counted grouped-dictionary keys rather than actual ORM rows; the budget was reset per chunk (a single fixed `LIMIT` on every chunk) so a chunk could materialize far over the cap; the source-revision-decision chain query had no `LIMIT` and was outside the budget; snapshot limits reset per chunk; the legacy path still loaded all `OfficialSourceRow`/`OfficialSourceRevision` rows unbounded; unreachable dead code remained after `_project_publication_from_chain`'s return; duplicated chain/projection implementations drifted from `repositories.py`; and the cap sizes (250k/2M) could still consume several GB once serialized. R2 corrects all of these in place.

## Invariant

The official candidate projection and legacy inventory are bounded read models: hard cardinality caps bound output and heap, related rows are batch-loaded with no per-claim SELECT, overflow fails closed before any per-claim processing (never a partial report), exact under-cap semantics and deterministic ordering/digests are preserved, and the CLI emits one fixed terminal-safe refusal on overflow.

## Caps (documented, conservative, not test-sized)

- `MAX_CLAIMS = 50_000` — loaded via SQL `LIMIT MAX_CLAIMS + 1`.
- `MAX_SNAPSHOTS = 20_000` — aggregate cross-chunk SQL `LIMIT remaining + 1` with a stable "snapshot count" label.
- `MAX_RELATED_ROWS = 200_000` — aggregate decision/validation rows, one persistent cross-chunk budget with a stable label.
- `_BATCH_CHUNK = 500` — IN-chunk size far below SQLite (999) / PostgreSQL (32767) parameter ceilings.

Headroom rationale: a nested JSON report at 250k claims / 2M related rows can consume several GB once serialized, so R2 chose materially conservative production caps (50k claims / 20k snapshots / 200k related rows) that bound heap and output while retaining headroom well above realistic local capture ledgers (tens of thousands of claims).

## Patch (narrow, R2)

- **`ledger/app/export/official_json.py`**
  - Caps, `FeedResourceLimitError`, `_batch_ids`, `_load_budgeted_by_ids` (persistent cross-chunk budget: each chunk carries `LIMIT remaining + 1`, deterministic PK ordering, sorted/deduped IDs, fail-closed on the first chunk past the budget), `_load_plain_by_ids` (bounded IN-chunk loads that do not consume the related budget), and a public `FeedBatch` context.
  - Snapshots use a labeled aggregate budget. Sources/revisions/models/benchmarks are plain bounded IN-chunk loads (one row per referenced id — they do not consume the related budget).
  - Source-revision decisions are loaded by referenced revision id FIRST (one chunked IN, same persistent related budget), then only exact decision ids missing from that map are queried — a durable row is never materialized or charged twice, so an under-cap ledger is never falsely rejected.
  - Validations/review/publication decisions share the ONE persistent related budget (actual ORM row counts, not grouped keys).
  - `FeedBatch` defensively rejects `len(claims) > MAX_CLAIMS` before any related load, so an oversized prebuilt batch cannot bypass the shared cap.
  - Non-unique related queries order by `(id_attr, model.id)` for deterministic tie-breaking.
  - `analyze_official_feed_candidates(session, *, batch=None)` loads claims with `LIMIT MAX_CLAIMS + 1`, builds the batch once, and evaluates purely from the batch (`_eligible_claim_batched`).
  - Removed the duplicated `_resolve_review_chain_batch`/`_resolve_publication_chain_batch`; the batch reuses `repo._resolve_review_chain` / `repo._resolve_publication_chain` (pure, fail-closed). Removed dead session-based evaluators, `_load_chunked_by_ids`, `claim_limit`, `_claims_by_id`, and `effective_source_decision`.
- **`ledger/app/reporting/legacy_inventory.py`**
  - Reuses the shared `MAX_CLAIMS`/`MAX_SNAPSHOTS` imported from official_json (no local duplicates); `build_legacy_inventory_report` loads claims/snapshots with `LIMIT cap + 1`, builds ONE `FeedBatch`, reuses `batch.sources`/`batch.revisions` (no unbounded all-table scans), passes the batch to `analyze_official_feed_candidates(batch=...)` and `_claim_record_batched`, and converts `FeedResourceLimitError` to `LegacyInventoryError`.
  - `_claim_record_batched` reuses `repo._resolve_review_chain` + `repo._project_review` directly (no duplicated review projection); a minimal `_project_publication` mirrors the repository's publication-projection semantics. Removed the unreachable former per-claim body.
- **`ledger/app/cli.py`**
  - `reports_legacy_inventory` catches `LegacyInventoryError` and emits one fixed terminal-safe refusal (`Legacy inventory refused: report exceeds the bounded resource limits.`) with exit 2; the exception is never interpolated.
- `ledger/app/db/repositories.py` and `ledger/app/db/models.py` were **not** modified (read-only, hashes unchanged).

## Tests (test-first, R2 = 17 tests)

`ledger/tests/test_official_feed_resource_bounds.py`:

1. `test_cap_plus_one_claims_fails_closed_before_partial_artifact` — cap+1 fails before candidate evaluation.
2. `test_over_cap_related_rows_fails_closed` — over-cap related rows fail.
3. `test_legacy_snapshot_cap_fails_closed` — legacy snapshot cap fails.
4. `test_statement_count_is_flat_across_small_and_larger_same_batch_datasets` — 1-claim vs 4-claim windows issue the same SELECT count (no per-claim query).
5. `test_large_under_cap_fixture_returns_all_rows_deterministically` — 5-claim fixture returns all, deterministically, each accounted once.
6. `test_invalid_decision_chain_remains_fail_closed` — forced invalid chain → `REVIEW_CHAIN_INVALID`, claim excluded.
7. `test_claims_load_uses_sql_limit_mutation_removal_fails` — claims SELECT carries `LIMIT` (mutation: removal changes the query and the cap check still fails closed).
8. `test_reintroducing_a_per_claim_query_breaks_flat_statement_count` — mutation adding one per-claim SELECT grows the count.
9. `test_cli_legacy_inventory_emits_generic_refusal_on_cap_overflow` — hostile detail-rich exception text absent from the fixed refusal, exit 2.
10. `test_related_cap_counts_actual_orm_rows_not_grouped_keys` — many validations on ONE claim trip a small cap (R1's group-count bug).
11. `test_cross_chunk_remaining_budget_is_persistent` — tiny `_BATCH_CHUNK` cannot reset the budget.
12. `test_source_decision_chain_row_overflow_fails_closed` — over-cap source decisions on a revision fail.
13. `test_snapshot_cross_chunk_overflow_fails_closed` — snapshot budget is aggregate across chunks.
14. `test_referenced_source_decision_counted_once_not_twice` — a certified decision is loaded/charged once, so an under-cap ledger is not falsely rejected.
15. `test_legacy_inventory_statement_count_is_flat` — legacy path issues no per-claim SELECT.
16. `test_shared_cap_cannot_be_bypassed_by_prebuilt_batch` — an oversized prebuilt `FeedBatch` fails closed at the shared claim cap.
17. `test_legacy_route_uses_shared_caps_not_local_duplicates` — legacy imports the shared caps; monkeypatching the shared `MAX_CLAIMS` is honored.

RED captured (R1, raw, unpiped):

```
cd ledger && uv run pytest -q tests/test_official_feed_resource_bounds.py
FFFFFF  [100%]
6 failed in 4.83s
```

All 6 initial tests failed (no caps, no batch loader, per-claim SELECTs present).

## Exact commands and counts (raw and unpiped, R2 final)

```
cd ledger && uv run pytest -q tests/test_official_feed_resource_bounds.py
.................  [100%]
17 passed in 8.93s

cd ledger && uv run pytest -q tests/test_official_feed_projection.py
..................  [100%]
18 passed in 8.35s

cd ledger && uv run pytest -q tests/test_cli_containment.py tests/test_cli_terminal_safety.py tests/test_security_remediation_regressions.py tests/test_cli_import_boundary.py
................................  [100%]
33 passed in 8.44s

cd ledger && uv run pytest -q tests/test_postgresql_portability.py
...ssssss  [100%]
3 passed, 6 skipped in 0.13s

cd /Users/stevmq/Documents/ai-benchmark-aggregator && git diff --check
(no output — clean)
```

## Query-count evidence

The statement-count tests prove the batch loader is flat for both the candidate and legacy paths: small and larger same-chunk windows issue the same number of SELECTs. The mutation test proves reintroducing one per-claim SELECT breaks that flatness.

## Mutations

- Removing the SQL `LIMIT` from the claims load (mutation): the query text loses `LIMIT` and a cap+1 dataset would be fully materialized before the post-load check — the `LIMIT` presence assertion rejects this.
- Reintroducing one per-claim `SELECT` (mutation): the flat statement-count assertion rejects it.
- Removing the source-revision-decision chain `LIMIT` (mutation): over-cap source decisions would not fail closed — the source-decision overflow test rejects this.

## Plain shasums (R4 final)

- `ledger/app/export/official_json.py` → `ecafba6fa4fcba348d020882c07719f375d5c8cd`
- `ledger/app/reporting/legacy_inventory.py` → `1e48fd9d7b9abed1f5dbcfaea0816027c9df2d19`
- `ledger/tests/test_official_feed_resource_bounds.py` → `da1b3e4d7fdede8e64cd575fbd149fe990c273a3`
- `ledger/app/cli.py` → `f1bfdaa0dd0fd1ed1d7be8670cf4cfb3d4d0d9b8`
- `ledger/tests/test_official_feed_projection.py` → `cacb471b0a9aae6213dba02286a3f900957a10fd` (unchanged — no assertion edits were necessary; exact under-cap semantics preserved)
- `ledger/app/db/repositories.py` → `23fe1ad38427857c85e74292cfbf78eb326d7598` (unchanged, read-only)
- `ledger/app/db/models.py` → `64fba1cc6b17f902495af1d9b05ff966543ebae9` (unchanged, read-only)

The F7 section was reconciled in place for R4; its own hash is intentionally omitted because embedding it would be self-referential.

Git index is empty (no staged changes).

## Controls and bypass attempts

- Every budgeted load carries a deterministic SQL `LIMIT` (`cap + 1` for claims; `remaining + 1` per chunk, persistent across all chunks and related types, for snapshots and decision/validation rows), so a single oversized chunk cannot materialize an unbounded result.
- The aggregate cap counts actual ORM rows (not grouped keys); a budget persists across chunks and all related types, including the source-revision-decision chain query.
- Source-revision decisions are loaded by revision first, then only missing exact ids — each durable row is counted once.
- Sources/revisions/models/benchmarks are bounded IN-chunk loads (bounded by referenced ids) and do not consume the related budget.
- No per-claim query remains; chains and projections reuse the repository's pure fail-closed resolvers.
- Exact under-cap semantics preserved: all 18 projection tests pass unchanged, deterministic ordering and digests intact.
- Invalid chains remain fail-closed (`REVIEW_CHAIN_INVALID` / `chain_error`).
- CLI overflow emits one fixed terminal-safe refusal, exit 2, with no raw exception/cap/DB detail (hostile-detail test).
- `repositories.py`/`models.py` unchanged; no schema, claim, registry, publication-authority, F17/F14, or unrelated hunks modified.

## Residual risk

- The caps and batching were validated on SQLite only; `test_postgresql_portability.py` passes (3 passed, 6 skipped — the skips are the existing non-Postgres environment skips), but a live PostgreSQL run by the coordinator remains the final confirmation of the `LIMIT`/IN-chunk SQL compile behavior on that dialect.
- The full ledger suite was not run in this bounded task.

## Files modified (task-owned)

- `ledger/app/export/official_json.py`
- `ledger/app/reporting/legacy_inventory.py`
- `ledger/tests/test_official_feed_resource_bounds.py` (new)
- `ledger/app/cli.py` (fixed generic-refusal branch in `reports_legacy_inventory`)
- `docs/audits/2026-08-10-codex-security-deep-scan/fix_report.md` (this F7 entry reconciled in place)

Git index is empty (no staged changes).

---

# Fix Report: csf_763d72930ef8ff3289f350b6 — Unbounded local snapshot materialization before integrity verification

- Finding: **F8 — Unbounded local snapshot materialization before integrity verification** (`occ_7957646c4a3a09911211528b`)
- Worker: supervised Orca worker `term_047e2d9a-af25-402a-9eb3-ae8b3f5a3875`
- Task: `task_579d0dac96fb`; Dispatch: `ctx_5b7f50a486da` (this reconciliation)
- Reconciles failed **R1** (`task_5540633de716`, `ctx_b9704512e481`) and the reworked implementation candidate **R2** (`task_f8ef6d694ceb`, `ctx_46da0ace6ae3`)
- Root control consumer: `ledger/app/ingestion/runner.py:268` relies on `storage.verify_snapshot(...)` to preserve the size-bound invariant; the bound is implemented in `ledger/app/storage/local.py` and enforced end-to-end in `ledger/app/backup/service.py`.
- Outcome: **FIXED**

## Route reconciliation

- **R1 (failed)** — abandoned partway from the Command Code **five-hour usage limit**, before the acceptance tests were run or the report section written. R1 left only untrusted, partial edits in the working tree (a descriptor helper with a potential fd-leak and an unclamped `read(_CHUNK_SIZE)` call in `_stream_object`), which were **not** accepted.
- **R2 (accepted after coordinator rework and independent local verification)** — completed under the exact Claude Code DeepSeek V4 Flash 0731 route, model `deepseek-v4-flash-0731` (session model `deepseek-v4-flash-0731-high-throughput`, effort high, service tier standard; Fast not surfaced), with no route/branch/model change. The coordinator reviewed the initial R2 output and issued corrections across three review blocks (SOURCE, SECOND, FINAL TEST): threads the descriptor through a single ownership-transfer reader, clamps every capped read to `min(_CHUNK_SIZE, cap+1-total)`, replaces the O(n²) `sum(charged.values())` with an O(1) running total, and corrects the false "no-partial-object-set" prose in service comments, module docstring, and checkpoint/restore test docstrings.

## Invariant

Every immutable SNAPSHOT object is streamed through a descriptor-pinned no-follow regular file with fixed **positive** read sizes only (never an unbounded `read()`/`read(-1)`). A single snapshot object is bounded from above at 64 MiB and the cumulative unique snapshot byte budget for one checkpoint/restore unit is 512 MiB; a snapshot over its per-object cap — including inherently in-place file growth past the `fstat` size, and an aggregate over the cumulative budget (counting duplicate references once) — fails closed with a redacted partial failure and **no success receipt**. `verify_snapshot` computes the digest without materializing bytes. The per-object cap applies **only** to `StorageObjectKind.SNAPSHOT`; `ARTIFACT` relational blobs (owned by the F9/F19 drivers) are intentionally uncapped here.

## Path

- `ledger/app/storage/local.py`
- `ledger/app/backup/service.py`
- `ledger/tests/test_snapshot_resource_bounds.py` (this task owned; helper edited to use verification)

## Patch (narrow, no production weakening)

1. `ledger/app/storage/local.py`
   - `MAX_SNAPSHOT_BYTES = 64 * 1024 * 1024` (per-snapshot, SNAPSHOT-only) and `_CHUNK_SIZE = 64 * 1024`.
   - `_sha256_stream(handle, *, cap)` reads `min(_CHUNK_SIZE, cap + 1 - byte_count)` (positive-only remaining clamp); when `cap is None` (artifact) still `_CHUNK_SIZE` chunks but no total bound.
   - `_stream_object` is the only descriptor reader: `_open_regular_file` opens the exact no-follow regular inode (ownership transferred to caller; intermediate fds closed on every exception path), then an `fstat` precheck `st.st_size > cap` → `_raise_over_cap`, then streamed reads clamped to `cap+1`, then `os.close(fd)` exactly once. The R1 duplicate `if cap is not None and st.st_size > cap:` was collapsed into a single raise.
   - `read_snapshot`/`read`/`verify_snapshot` use the same bounded reader; `verify_snapshot` streams a digest without materializing; `store_snapshot` enforces the cap before hashing/writing.
   - `_verify_target_from_parent` (reuse-race) transfers the opened fd into a context-managed handle so the inner close runs exactly once (R1 leak removed).
   - `_cap_for_path`/`_cap_for_kind` return `None` for `ARTIFACT`, preserving the F9/F19 relational backups uncapped.

2. `ledger/app/backup/service.py`
   - `MAX_UNIQUE_SNAPSHOT_BYTES = 512 * 1024 * 1024`. Rationale (truthful, no heap claims): the storage layer bounds **every** SNAPSHOT object **from above** at 64 MiB; 512 MiB is exactly 8× that per-object cap, bounding the durable disk cost of one unit's unique raw evidence to half a gigabyte regardless of historical snapshot rows cited or dedup multiplicities. 1 GiB was rejected as too permissive with no added safety.
   - `_charge_snapshot_bytes(*, key, verified_byte_length, charged, charging_bytes) -> new_total` uses the caller's **explicit O(1) running total** (never `sum(charged.values())`, so no O(n²)). A duplicate key returns the running total unchanged (counted once); overflow raises the redacted `RECOVERY_OBJECT_BYTE_BUDGET_OVERFLOW` partial failure.
   - Real checkpoint/restore loops charge the unique verified byte length **before** the durable write; an over-budget abort leaves no success receipt, no current over-budget copy, and earlier fully-written unique copies remain as **bounded immutable partial state** (documented, not denied). Relational artifact bytes excluded.

3. `ledger/tests/test_snapshot_resource_bounds.py`
   - `_raw_bytes_for` now uses `LocalSnapshotStorage.read_snapshot(uri=snapshot.raw_content_uri, content_sha256=snapshot.content_hash)` and returns `result.verification.byte_length` — the length is integrity-verified, not just the bytes-at-URI (the prior helper used the unverifying `read`). The fixture-bounds tests are unchanged.
   - Load-bearing tests: `_stream_object` growth-after-`fstat` requests exactly ≤ `cap+1` (never `cap+CHUNK`); `_sha256_stream` request-size clamp + exact-cap; no-leak on reuse-verify success and over-cap; real checkpoint+restore cumulative budget fail-closed (first sorted object by UUID id remains, second explicitly absent); real checkpoint+restore dedup of two identical-bytes rows → 2 references / 1 unique object, single physical object; artifact namespace exclusion; verify-no-materialization; public-read bounded.

## Exact commands and counts (raw, unpiped)

Focused file (ran twice, deterministic):

```
cd ledger && uv run pytest -q tests/test_snapshot_resource_bounds.py
......................  [100%]
22 passed in 0.82s
```

Related storage/recovery suites:

```
cd ledger && uv run pytest -q tests/test_snapshot_storage.py tests/test_snapshot_resource_bounds.py tests/test_storage_contracts.py tests/test_r2_storage.py tests/test_recovery_adversarial.py tests/test_recovery_cli.py tests/test_recovery_foundations.py tests/test_recovery_postgresql.py tests/test_operational_persistence_postgresql.py
================================== 255 passed, 8 skipped in 9.94s
```

Full-ledger observation (recorded as given by the acceptance environment, not re-derived here): **1389 passed** plus one unrelated `tests/test_coverage_cli.py` registry-count failure, recorded as residual and **not** an F8 regression.

Static checks:

```
cd ledger && uv run python -m py_compile app/storage/local.py app/backup/service.py tests/test_snapshot_resource_bounds.py
(no output — clean)

git diff --check
(no output — clean)

git diff --cached --name-only
(no output — empty index)
```

## Plain shasums (F8 report-repair final)

MacOS `shasum` SHA-1:

- `ledger/app/storage/local.py` → `810ae6b22bb6616c4c62de6896d2214c32fa8ab8`
- `ledger/app/backup/service.py` → `24fb38952305115aa63f56f8e9c0f4eaf6da6d09`
- `ledger/tests/test_snapshot_resource_bounds.py` → `d8524cf9b46f61248f78bcd8f1ccd8f7e7b13135`

This report's own hash is intentionally omitted (self-referential). Git index is empty (no staged changes).

## Residual risk

The unrelated full-ledger `test_coverage_cli.py` registry-count failure is recorded as an independent, pre-existing failure and is **not** a regression of this change: F8 touches only the storage/backup stack and its resource-bounds test; the CLI coverage path is outside these files. The storage-level caps were validated on the local/SQLite storage layer; a production PostgreSQL run is owned by the F9/F19 drivers and is out of scope for this finding.

## Files modified (task-owned)

- `ledger/tests/test_snapshot_resource_bounds.py` (helper correctness fix)
- `docs/audits/2026-08-10-codex-security-deep-scan/fix_report.md` (this F8 section)

`ledger/app/storage/local.py` and `ledger/app/backup/service.py` are referenced production files from the reconciled R2 state; no production source was edited in this report repair. Git index is empty (no staged changes).

# Fix Report: csf_be13837ec4b4fb3ea324d114 — Unbounded PostgreSQL recovery backup materialization

- Finding: **F9 — Unbounded PostgreSQL recovery backup materialization** (`occ_848209a33f7f4be66b908614` in `report.md`)

## Route reconciliation

Completed under the exact Claude Code DeepSeek V4 Flash 0731 route (session model `deepseek-v4-flash-0731-high-throughput`, effort high, service tier standard; Fast unknown). No task-owned branch change. The coordinator issued corrections across checkpoints A–D and a cleanup review (select fail-closed, archive-copy removal, `locators`/import order); each was applied and independently re-verified raw.

## Invariant

Every unbounded PostgreSQL archive load, captured tool stdout, TOC, schema-only digest feed, and database-size admission is bounded at the descriptor/byte boundary with fixed **positive** reads only (never an unbounded full-file `read_bytes`/`communicate`). An over-budget archive, over-budget tool stdout, over-budget TOC entry, or a target database over the documented size budget fails closed with a **stable typed fail-closed error** and **no success receipt**: archive cap/posture violations raise `RecoveryIntegrityError`, the TOC entry bound raises `UnsupportedRecoveryArtifact`, and tool-output overflow plus database-size overflow raise `RecoveryPartialFailure`. libpq diagnostics are discarded at the descriptor boundary. The raw claim/ledger trust boundaries are unchanged. The regression tests are fake-only; production code was not exercised against a live PostgreSQL database.

## Path

- `ledger/app/backup/postgresql_driver.py` (this task owned)
- `ledger/tests/test_postgresql_resource_bounds.py` (this task owned, NEW)
- `ledger/tests/test_recovery_postgresql.py` (this task owned; dirty before F9, received only narrow fake compatibility adaptations)

## Controls

1. **Descriptor-pinned bounded archive reading** — the pg_dump-produced archive path is read through `_read_bounded_bytes(..., cap=_ARCHIVE_BYTES_CAP)` (cap+1 guard, `O_NOFOLLOW`/non-regular/private-posture rejection, single descriptor close; a cap or posture violation raises `RecoveryIntegrityError`). `_archive_toc`/`_require_artifact` enforce type, `PGDMP` header, and the cap before any write.
2. **Bounded tool stdout** — `_run_pg_tool` uses `select.select` + fixed positive `read1` (never `communicate`); per-call `output_budget` (tool-version / TOC / schema-only / zero for pg_dump and pg_restore); overflow terminates only the isolated child group and raises a `RecoveryPartialFailure` with `POSTGRESQL_TOOL_OUTPUT_BUDGET_EXCEEDED`; `select.select` OSError/ValueError and read errors after partial output fail closed as a `RecoveryPartialFailure` with `POSTGRESQL_TOOL_RUNTIME_FAILED`, terminating the child group and closing stdout with no raw cause.
3. **Database-size budget** — `_assert_database_size_budget` derives `pg_database_size(current_database())`, validates exact non-negative int, and cap+1 fails as `RecoveryPartialFailure`; enforced at backup source (`phase="postgresql_database_size_budget"`, `target_created=False`), restore target, and inspection target (`postgresql_restore_size_budget`/`postgresql_inspection_size_budget`, `target_created=True`) before pg_dump / `_archive_toc` / inspection materialization.
4. **TOC budget** — `--list` output is capped (`_ARCHIVE_TOC_OUTPUT_BUDGET`); an entry count over `_TOC_ENTRY_BOUND` raises `UnsupportedRecoveryArtifact`; the filtered TOC is written privately fail-closed.

## Tests and counts

Focused suite:

```
cd ledger && uv run pytest -q tests/test_postgresql_resource_bounds.py
40 passed
```

Compatibility suite — independently rerun **raw and unpiped** by the coordinator:

```
cd ledger && uv run pytest -q tests/test_recovery_postgresql.py tests/test_postgresql_portability.py tests/test_operational_persistence_postgresql.py
64 passed, 14 skipped
```

Static: `uv run python -m py_compile app/backup/postgresql_driver.py tests/test_postgresql_resource_bounds.py` (clean); `git diff --check` (clean); `git diff --cached --name-status` (empty).

## Plain shasums (F9 final)

macOS `shasum` SHA-1:

- `ledger/app/backup/postgresql_driver.py` → `01b71fa2cebc420e041ae63128d4c6996146959b`
- `ledger/tests/test_postgresql_resource_bounds.py` → `13e1beb3293f91317c9e0801527ebf62ab2fd928`
- `ledger/tests/test_recovery_postgresql.py` → `2b858e0a6b62c21b809e1b19467361e8c864df86`

The report's own hash is omitted (self-referential). Git index is empty (no staged changes).

## Residual risk

`RelationalBackupArtifact` still carries bytes in memory but is capped at 1 GiB. Source/target database-size admission is sampled, not a continuous `pg_restore` quota. The trusted checkpoint chain and the 2 GiB source cap indirectly bound legitimate restore expansion. No live PostgreSQL run occurred; the caps may need operational tuning for real deployments.

## Files modified (task-owned)

- `ledger/app/backup/postgresql_driver.py`
- `ledger/tests/test_postgresql_resource_bounds.py`
- `ledger/tests/test_recovery_postgresql.py` (dirty before F9; narrow fake compatibility adaptations only)
- `docs/audits/2026-08-10-codex-security-deep-scan/fix_report.md` (this F9 section)

Accepted after coordinator review and independent local verification.

---

# Fix Report: csf_d5cd490f3017455ec4b2b552 — Unbounded SQLite recovery backup materialization

- Finding: **F19 — Unbounded SQLite recovery backup materialization** (`occ_f0c26100c8808ff91d568e3b` in `report.md`; `csf_d5cd490f3017455ec4b2b552` in `findings.json`)
- Worker: supervised Orca worker `term_cd1e605b-ccab-44da-8a2d-58f21e872c31`
- Task: `task_75bab3269f1c`; Dispatch: `ctx_3b559baa4b20`
- Route receipt: Command Code v1.20.0; route DeepSeek V4 Flash Latest at Max effort; route, branch, worktree, model, and effort were not changed.
- Outcome: **FIXED**

This entry is appended by a separate report-only worker (task `task_1138f50ce5d9`, dispatch `ctx_3ff779faaa22`, terminal `term_1ff276e5-03a1-4a8b-8d11-f4ed942fe506`) that owned only this report; the production implementation, tests, and commands below are the prior F19 task's records, re-verified statically where noted.

## Invariant

Every SQLite recovery backup artifact and inspection result is bounded at the byte boundary with fixed **positive** reads only. A SQLite source or backup over the documented 1 GiB database byte cap, in-place file growth past the `fstat` size, or an inventory extraction over the shared row/payload budget fails closed with a stable typed fail-closed error and **no success receipt**. The archive's byte identity is streamed (`_stream_path_identity`) without materializing bytes, and application-table rows are read through fixed-positive `fetchmany` under one shared `_RowBudget`. The raw claim/ledger trust boundaries are unchanged.

## Path

`ledger/app/backup/sqlite_driver.py` — the accepted production path from the prior F19 implementation task (not changed by this report-only task)

## Controls

1. **Source cap** — `_require_regular_source` rejects a non-regular/symlink source and a source over `_DATABASE_BYTES_CAP` (1 GiB) before any backup is attempted.
2. **Staged chmod 0600** — `create_backup` chmods the staged `backup.sqlite3` to `0o600` immediately after the stdlib backup API creates it (the API writes under the process umask), so the private-posture check reads a private file (CWE-400 private-posture rule).
3. **Descriptor-pinned bounded chunk reader and streamed identity** — `_private_regular_file` opens the exact no-follow regular inode with `O_NOFOLLOW` where available, validates regular-file/no-symlink/private-posture and the byte cap before the first read, and closes the descriptor exactly once after a successful open, including all later rejection and read paths (a failed open never yields a descriptor); `_iter_bounded_reads` performs only fixed **positive** `os.read` requests clamped to `cap+1` (in-place growth past the `fstat` size fails closed after at most `cap+1` offered bytes, never a full chunk over the cap); `_read_bounded_bytes` reads the backup through that reader and `_stream_path_identity` computes byte length and SHA-256 **without materializing** the bytes.
4. **Artifact cap** — `_require_artifact` rejects any `RelationalBackupArtifact` whose `raw_bytes` exceed `_DATABASE_BYTES_CAP`, plus driver/engine/format/version and SQLite-header checks, before inspection or restore.
5. **One shared row/payload budget** — `_collect_semantic_rows` builds **one** `_RowBudget` enforcing all four documented limits (`_MAX_ROWS_PER_TABLE` 250k, `_MAX_ROWS_CUMULATIVE` 1M, `_MAX_PAYLOAD_BYTES_PER_TABLE` 128 MiB, `_MAX_PAYLOAD_BYTES_CUMULATIVE` 512 MiB) across the full sorted table set, so a cross-table overflow fails closed no matter the per-table counts.
6. **Fixed-positive fetchmany** — `_rows` drives the cursor only with `fetchmany(_ROW_FETCH_BATCH)` (256 rows) and debits the budget from the rows actually returned. Fixed `fetchall` calls remain for schema metadata, PRAGMA integrity and foreign-key results, table-column metadata, and the single Alembic revision; application-table rows alone use fixed-positive `fetchmany`.
7. **artifact.raw_bytes reuse** — `inspect_artifact` stages `artifact.raw_bytes` and `restore_new_target` writes `artifact.raw_bytes`, each reusing the already-capped in-memory artifact bytes; no byte is re-read unbounded from a source or staged file, and each write path (`_write_private_file`, mode 0600, O_EXCL, `O_NOFOLLOW` where available, fsync) is private and fail-closed.

## Exact commands and counts (raw and unpiped)

Focused suite (worker, 18 tests):

```
cd ledger && uv run pytest -q tests/test_sqlite_resource_bounds.py
18 passed in 0.05s
```

Compatibility suite (worker, 116 tests):

```
cd ledger && uv run pytest -q tests/test_recovery_foundations.py tests/test_recovery_adversarial.py tests/test_recovery_cli.py
116 passed
```

Coordinator independent combined verification:

```
cd ledger && uv run pytest -q tests/test_sqlite_resource_bounds.py tests/test_recovery_foundations.py tests/test_recovery_adversarial.py tests/test_recovery_cli.py
134 passed in 5.08s
```

Static checks:

```
cd ledger && uv run python -m py_compile app/backup/sqlite_driver.py
(no output — exit 0)

git diff --check -- ledger/app/backup/sqlite_driver.py
(no output — exit 0)

rg -n "read_bytes" ledger/app/backup/sqlite_driver.py
(no matches — exit 1)
```

Worker checks: 18 focused and 116 compatibility tests. Coordinator independent combined: 134 passed in 5.08s, plus `py_compile`, `git diff --check`, and no-`read_bytes`.

## Plain shasums (F19 final)

macOS `shasum` SHA-1:

- `ledger/app/backup/sqlite_driver.py` → `488a94708ec165666bcdf065c7ae40e392aaa956` (accepted production path)
- `ledger/tests/test_sqlite_resource_bounds.py` → `3411bf71a382e9c81c47a9f4bf63cf522ae057c5` (unchanged test)

This report's own hash is omitted (self-referential). Git index is empty (no staged changes).

## Bypass review

- No `read_bytes` remains in the SQLite recovery path; every archive byte is read through the descriptor-pinned bounded reader, and application-table rows through fixed-positive `fetchmany`. Fixed `fetchall` calls remain only for bounded schema-metadata, PRAGMA-integrity/foreign-key, table-column-metadata, and Alembic-revision results.
- The one shared `_RowBudget` cannot be bypassed by per-table counts: cumulative limits span every table.
- `_require_artifact` bounds inspection/restore even if a caller constructs an oversized artifact in memory.
- No browser, cloud, live database, commit, push, or deploy was performed.

## Files modified (ownership)

- Prior F19 implementation/test workers changed `ledger/app/backup/sqlite_driver.py` and `ledger/tests/test_sqlite_resource_bounds.py` (accepted at the shasums above).
- This report-only task changes only `docs/audits/2026-08-10-codex-security-deep-scan/fix_report.md` (this appended F19 entry).

## Residual risk

Bounded local verification only: the 18 focused and 116 compatibility tests (coordinator independent combined 134 passed in 5.08s, plus `py_compile`, `git diff --check`, and no-`read_bytes`) ran against fake/local SQLite fixtures, not a live production database. Production readiness still pending later gates.

---

# Fix Report: csf_f8cd23ed6809346c3b0bed87 — Unbounded discovery fixture materialization

- Finding: **F20 — Unbounded discovery fixture materialization** (`occ_f90d7b2e7833150ed43bd91a`)
- Outcome: **FIXED LOCALLY**

## Invariant and controls

Discovery fixtures now fail closed before unbounded file, JSON, candidate, or persistence materialization:

1. `fixture_io.py` uses descriptor-relative, no-follow, regular-file reads with fixed positive `os.read` requests. Each JSON file is limited to 8 MiB, nesting depth 64, and 100,000 decoded nodes. Shared budgets are charged atomically.
2. `manifest.py` applies one 32 MiB and 500,000-node shared budget across the manifest, universe, and target files. The target directory is scanned before decode with caps of 512 total entries and 512 JSON files.
3. `connectors/base.py` pins the fixture root and `connectors/` directory to no-follow descriptors. `static.json` is bounded to 8 MiB, depth 64, and 100,000 nodes. The complete file is validated before assembly, with caps of 512 target entries, 1,000 candidates per target, and 10,000 aggregate candidate specifications.
4. `controller.py` caps one discovery cycle at 10,000 observed candidates. It checks the cumulative proposed total before persisting an observation. An overflow raises `DiscoveryControllerError`; the caller transaction rolls back prior cycle intents, job intents, completions, and candidates.
5. The source guard rejects `os.listdir`, `read_text`, `read_bytes`, and zero-argument `read()` in the three fixture-loading production modules while permitting bounded `os.read(fd, size)`.

## Verification

- Shared reader checkpoint: 22 focused tests passed.
- Manifest checkpoint: 84 combined resource, manifest, controller, planner, CLI, and adjacent retirement tests passed.
- Connector checkpoint: 91 combined tests passed.
- Final controller checkpoint: 41 resource-bound tests and 53 adjacent discovery tests passed, 94 total. The exact-cap test commits two candidates. The cap-plus-one test records one append before the later observation proposes three candidates, then proves the transaction rollback leaves zero `ScheduledCycleIntent`, `ScheduledCycleIntentCompletion`, `ScheduledJobIntent`, and `DiscoveryCandidate` rows.
- `py_compile`, `git diff --check`, empty staged-index, and LF-ending checks passed.

## SHA-256

- `ledger/app/discovery/fixture_io.py` — `ae279293d2d41a40dc802480210317437a19fe7fbc432937eaf86ddca8163cb6`
- `ledger/app/discovery/manifest.py` — `6ceb61e1ad99aeb69c4f0d00e13f1e3703f42a2a142b7b704600a8021cf69f7a`
- `ledger/app/discovery/connectors/base.py` — `3f315cf0e4738c2cc199a70da91fe749d116c2a784fb6f80495532e6e2a2daf3`
- `ledger/app/discovery/controller.py` — `af76d0589659335e00cf8ea88dc56b8e61af60eb0997a30e0b47443eaaf48ceb`
- `ledger/tests/test_discovery_resource_bounds.py` — `2542f9ab75212b2b80674d654b4a894db7013497cfdce7c7d9517092f1039673`

## Route and ownership

Claude Code on the exact registered `deepseek-v4-flash-0731` route produced the shared reader, manifest, connector, and controller production changes. The controller test workers stalled; one supplied only the required imports before its terminal was stopped. The coordinator completed the three controller acceptance tests and independently ran the final gates. The report-only Claude worker also missed its write deadline with zero report changes, so the coordinator appended this evidence from the accepted receipts. Every task-owned worker terminal was closed after acceptance or rejection.

## Residual risk and status

This is local fixture and SQLite test evidence only. No browser, live database, Cloudflare, paid cloud operation, commit, push, or deploy was performed. Full-ledger and final release gates remain pending, so this finding is fixed locally but does not make the product production-ready.

# Fix Report: csf_58191babfc1077827d0187ce — Mutable SQLite ingestion-run terminal history

- Finding: **F16 — Mutable SQLite ingestion-run terminal history** (`occ_ce5c3179ebcaa0a346f30b29`)
- Outcome: **FIXED LOCALLY**

## Invariant

- Forward-only 0012 SQLite trigger permits exactly one running/null -> completed|partial|failed/non-null finalization while `id`, `started_at`, `run_type`, `official_source_id` remain unchanged.
- Every other SQLite UPDATE on `ingestion_runs` fails with the stable immutable-history error; the DELETE guard remains.
- `repositories.finish_ingestion_run` only admits completed/partial/failed, only a running unfinished row, and exactly seven allowlisted non-negative int counters (bool rejected); no `hasattr` writes.
- SQLite recovery binds head 0012, requires `trg_ingestion_runs_finalize_once`, and accepts exactly two reviewed full-schema hashes caused solely by Alembic 1.18.5 batch reflection swapping two semantically identical unnamed FK clauses on `official_source_revisions`:
  - `db670c153790c9805f6af46c7f462b2ddd13a49f5a4d7e3294637c646aa068e4`
  - `4602bd3a302274e46180d93839f6cafeaa7863e7b2523c2a76fd4ac7b195e7c9`
- No other `sqlite_schema` object differs.

## Path/patch

- `ledger/migrations/versions/0012_sqlite_ingestion_run_hardening.py`
- `ledger/app/db/repositories.py`
- `ledger/app/backup/sqlite_driver.py`

## Test-first/root cause

Root cause: SQLite ingestion-run terminal rows were mutable after finalization, allowing a non-forward-only UPDATE to rewrite immutable terminal history (a DELETE guard already existed; the missing control was the finalize-once/terminal UPDATE guard). The 0012 forward-only trigger plus repository-side allowlisted finalization and exactly-seven counters closes the mutation surface; SQLite recovery identity is pinned to the trigger while tolerating only the two innocuous batch-reflection FK clause ordering variants from Alembic 1.18.5.

## Exact commands and counts

- `tests/test_ingestion_run_history.py` + `tests/test_ingestion_runner_transactions.py`: **37 passed in 8.34s**.
- Integrated history, runner, SQLite bounds, recovery foundations, recovery PostgreSQL, migrations: **176 passed, 5 skipped in 15.99s**.
- 12 real sequential fresh-head `create_backup` + `inspect_artifact` calls: **12 accepted**; hash counts `4602bd3a302274e46180d93839f6cafeaa7863e7b2523c2a76fd4ac7b195e7c9` = 11 and `db670c153790c9805f6af46c7f462b2ddd13a49f5a4d7e3294637c646aa068e4` = 1.
- `py_compile` passed; `git diff --check` passed; staged index empty.

## SHA-256 (accepted files)

- `ledger/migrations/versions/0012_sqlite_ingestion_run_hardening.py` — `ba255396b8eeda2033affda4ac028400a343305fbc1dafca5452509a3a44d452`
- `ledger/app/db/repositories.py` — `308ac5d0710c22a01d09c34c209bcbaf4cea682bc5e340f6d96a2a60f81d4863`
- `ledger/tests/test_ingestion_run_history.py` — `339aa0bb3dc75832673cc60257b7859ae358ccd57e0a2444884232c6ba55e266`
- `ledger/app/backup/sqlite_driver.py` — `f9e2cdac7e38a740fa3e30db3fa6431f162afff389feaf30ab2ebf4fa8fd50e5`
- `ledger/tests/test_recovery_postgresql.py` — `32ebe72716fc88f8c377653f5f66c841445e67bc0fd378e6e8845004846e9a40`

## Bypass review

- Immutable-history UPDATE/DELETE guards hold on every other transition; only the single forward-only finalization is permitted.
- Recovery binds head 0012 and requires the finalize-once trigger, so downgraded or trigger-less schemas are rejected.
- The two accepted schema-hash variants differ only in FK clause ordering from the Alembic batch reflection; no other object differs.

## Route/ownership

Exact Claude Code banner DeepSeek V4 Flash 0731, model `deepseek-v4-flash-0731` for implementation workers; reasoning/Fast not exposed. Migration and repository slices accepted after review/rework. Several broad/test/recovery attempts were stopped or rejected for zero edits, incomplete receipts, tautological tests, or the single-hash assumption. Coordinator root-cause analysis and direct verification corrected those outputs; F16C3 task `task_c68daa5693d7` was accepted after independent verification.

## Residual risk/status

No browser, live DB, provider, Cloudflare, paid operation, commit, push, or deploy. This is fixed locally; production readiness remains pending later gates.

# Fix Report: csf_26bde360141a34726824c06d — Published build artifact is not bound to source provenance

## Outcome

**PARTIALLY FIXED LOCALLY / EXTERNAL AUTHORIZATION BLOCKED** — Finding F13, occurrence occ_b1a4ecb0ed03cca1530f2f95. Local source-to-dist integrity binding is implemented and wired into CI, but this is NOT an authorized signed release manifest, so F13 remains open at the governed publication boundary.

## Invariant/local controls

- `npm run build` is ordered TypeScript -> Vite -> provenance create.
- `dist/build-provenance.json` fixed schema `ai-benchmark-build-provenance-v1`, algorithm `sha256-length-framed-tree-v1`.
- Source binding covers recursive regular `src/` and `public/`, required root build inputs, optional tsconfig.app/node only if present, sorted root-relative POSIX paths, u32BE path length + path bytes + u64BE file length + file bytes, SHA-256.
- Artifact binding covers every recursive regular dist file except the manifest itself, including `.vite/manifest.json`; at least one artifact required.
- Creation writes canonical fixed-order JSON atomically. Verification rejects missing/malformed/noncanonical/unknown/wrong-type/tampered digest/count, source or artifact add/delete/change, symlinks/non-regular entries, and directory-root symlinks. File reads use O_NOFOLLOW where available plus fstat; no whole-directory concurrent-rename immunity is claimed.
- `verify:build-provenance` verifies real dist then runs tests; `verify:pages-static` begins with provenance verify and retains --require-dist; both frontend and clean-archive CI explicitly verify after build before Pages/bundle.

## SHA-256

- scripts/build-provenance.mjs `69c5eebf208f81c13e0896b545a229c2b8a2c801c7a6cb661294d7c840d4b2c8`
- scripts/build-provenance-node-tests.mjs `d94f2addab1fb25fd1c696ba2af535cd0c3801895cbcbdf6ef11ec93f585904d`
- package.json `728fa1a5ad2312464181937a62777ebdfc122ce1fa6f57f51e3b672f77a36844`
- .github/workflows/verify.yml `5b9231d54865c7001aca8c017c1c0329261484887be6ef0158baf73980a60a33`

## Verification

- provenance: 25 passed, 0 failed, 0 skipped.
- real npm build passed; real manifest source digest `45a7daff8f1163112dd0c85eb1809228432f6b9ac1194ddedf9487a92a4544f4` / 106 files; artifact digest `6246765f6fb741256d763ab1f5bfc90e9242cfbc109fc8bdec6272f7fc92ad08` / 15 files.
- Pages verifier: 10 passed; bundle verifier: 52 passed, eager 696,014 bytes, total 1,440,883 bytes.
- npm typecheck, test typecheck, compatible Ruby YAML parse passed; actionlint unavailable; git diff --check passed; staged index empty.

## Route/ownership

Initial broad task `task_d5f9addd0dc7` stalled with zero owned edits and was rejected/closed. Core task `task_01ed10c64cf1` returned 16/16 but the coordinator rejected three fail-open defects; rework task `task_d425c75a21af` accepted after 25/25. Integration task `task_0c03193b9ee2` accepted after coordinator reruns. Independent read-only review task `task_a2f01f4cbcd7` stalled and was rejected; do not claim independent Claude acceptance. Workers run Claude banner DeepSeek V4 Flash 0731, model `deepseek-v4-flash-0731`; reasoning/Fast unknown.

## Final integrated closeout — 2026-08-12 local

Read-only gate task `task_dc8256028f32` passed the frontend, lock, and
containment gates, then found two stale ledger test assertions. Test-only task
`task_8b789e78325f` changed the explicit model-row baseline from 1,189 to
1,186 after the intentional three-row registry deduplication (the unique count
remains 1,186). It also replaced the false broad `sqlite` text check with
semantic proof that revision `0012_sqlite_ingestion_run_hardening` is present
while SQLite-only `RAISE(ABORT)` SQL is absent from PostgreSQL offline DDL.

- `ledger/tests/test_coverage_cli.py` SHA-256: `0c6ea312307843fe07f469aa088cf841e0582e1663ba78730e2c1acc3e0e79d0`
- `ledger/tests/test_postgresql_portability.py` SHA-256: `d6714df9748f95f717aa1a66689c869958b968d88bab971b3fdaf8f907c28c69`
- Coordinator direct repair check: 2 passed in 1.02 seconds.
- Coordinator direct unfiltered ledger check: 1,524 passed, 14 skipped in 111.06 seconds; exit 0.
- Frontend gate: typecheck and test typecheck passed; 19 test files and 96 tests passed; Official verifier 5/5; build passed; provenance 25/25; Pages 10/10; bundle 52/52.
- Python lock verification and the disposable containment smoke passed. A fresh `npm audit --audit-level=low` reported 0 vulnerabilities; `pip-audit` was unavailable, so no fresh Python vulnerability scan is claimed.

These are local results. They are not browser, live, pushed, deployed, or
authorized-publication proof. F13 remains open at the governed publication
boundary.

## Residual publication blocker

This is NOT an authorized signed release manifest. The private repo has unsigned commits, release signer/approval authority is UNASSIGNED/UNDECIDED, and no GitHub attestation/signing permission was added. No Cloudflare Pages upload/deploy happened, and no exact published artifact/digest was verified. No browser/live provider/commit/push/deploy/paid operation. Production remains NOT READY.
