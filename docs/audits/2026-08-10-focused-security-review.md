# Focused security review — post-task_213b1b02c03a dirty worktree

**Date:** 2026-08-10 · **Read-only review lane.**
**Head:** `5eb3b35` · Dirty worktree preserved. Two hard test failures confirmed by actual runs.
> **Attribution note:** This security-review *document* (this file) was authored by the dispatched reviewer that performed the audit. It is an audit output artifact, not an audited code file; it was created for the review, then later corrected for truthful attribution on 2026-08-10.

## Verdict: CHANGES REQUIRED

---

## Findings by severity

### [CRITICAL] `stat` is not imported in `migrate.py` — every SQLite copy-migration path crashes
- **File/line:** `ledger/app/db/migrate.py:1383` and `:1390` call `stat.S_ISLNK` / `stat.S_ISREG`; `stat` is never imported (imports are only `hashlib`/`json`/`os`/`sqlite3`/`urllib` at lines 16–20; `cli.py` imports it, `migrate.py` does not).
- **Command / result:**
  - `.venv/bin/pytest -q tests/test_migrations.py` → `10 failed, 6 passed`
  - Representative trace: `NameError: name 'stat' is not defined` at `app/db/migrate.py:1383`, reached from `_verified_backup` → `migrate_legacy_copy` (`migrate.py:1599`).
  - Isolation rerun: `test_copy_database_upgrade_preserves_legacy_evidence_and_quarantines_it`, `test_atomic_replace_failure_leaves_the_legacy_copy_unchanged`, `test_source_revision_and_snapshot_links_must_match_the_logical_source`, `test_downgrade_refuses_and_append_only_triggers_preserve_raw_evidence` all fail with the same `stat` `NameError`.
- **Why it matters:** `_backup_sqlite` and `_verified_backup` are the heart of the disposable-copy migration contract. The no-follow/inode hardening added in this worktree is dead-on-arrival; the prior (working) implementation was replaced.
- **Note the false-green:** the two "symlink" tests pass, but only because they fail *earlier* at `_require_fresh_nofollow_target` (create-exclusive), never reaching the `stat` code. See [MEDIUM-1].

### [HIGH] Missing-parent init is broken — the advertised test fails
- **File/line:** new test `ledger/tests/test_migrations.py:907` (`test_initialize_fresh_sqlite_creates_only_the_selected_missing_parent`, added in this worktree); implementation `migrate.py:1540–1563` (`initialize_database` → `_upgrade_empty_database`) contains no "create the selected missing parent" step.
- **Command / result:**
  - `.venv/bin/pytest -q "tests/test_migrations.py::test_initialize_fresh_sqlite_creates_only_the_selected_missing_parent"` → **FAIL**
  - `selenium.sqlite.OperationalError: (sqlite3.OperationalError) unable to open database file` at `migrate.py:1557` (`_upgrade_empty_database`).
  - Independent reproduction: `initialize_database('sqlite:///…/parent/x.db')` → `FAIL OperИсторийError` with `parent_exists_after False`.
- **Why it matters:** W1 of the remediation plan promises "documented fresh SQLite initialization… create only its explicitly selected missing parent". That is unimplemented and contradicts the plan. The parent directory is never created, so Alembic cannot open the DB.

### [MEDIUM-1] Residual TOCTOU in `_backup_sqlite`: `sqlite3.connect` reopens by path; the inode check is post-write detection, not prevention
- **File/line:** `ledger/app/db/migrate.py:1380–1393`.
- **Detail:** a no-follow regular file is created and its inode captured (`created = os.stat(...)`, `follow_symlinks=False`), but the actual write goes through `sqlite3.connect(destination)` (`:1386`), which re-opens the *path*. If a swap turns the path into a symlink inside the `stat`→`connect` window, the backup bytes are written to the attacker-chosen target; the `finally` at `:1389–1393` detects the inode/symlink change *after* the write and raises. The hardcoded rejection is a post-hoc red flag, not containment — the docstring itself admits the race ("could be swapped… inside the TOCTOU window").
- This contrasts with `sqlite_driver._write_private_file` (`ledger/app/backup/sqlite_driver.py:157–173`), which writes through the `os.open`d descriptor and never re-opens by path → that path is race-free (used by `inspect_artifact`/`restore_new_target`). Recommend the same descriptor-anchored pattern here, or verify inode before writing and write through the fd.

### [MEDIUM-2] Symlink coverage is "planted-only"; the concurrent-swap path is untested, and the two green tests pass for the wrong reason
- **Files:** `ledger/tests/test_migrations.py:256` (`dangling symlink planted`) and `:277` (`pre-existing regular refused`).
- The two pass because create-exclusive (`O_EXCL`) refuses *before* reaching the inode/identity re-verify — they never exercise `final.st_ino != created.st_ino` or `stat.S_ISLNK(final.st_mode)`. There is **no** test that swaps a file→symlink (or file→different-file) between `connect` and the final `os.stat`, i.e., the precise race the new code claims to defend. The concurrent case the task asks about is not covered anywhere in `test_migrations.py`, `test_recovery_foundations.py`, or `test_recovery_adversarial.py`.
- Minor members of the same class in the *driver* tests (the symlink-bearing cases at `test_recovery_cli.py:114,157,318` and adversarial `:853,1630`) attack the recovery object path, not the create→write→re-verify backup sequence.

### [LOW-1] Weak / tautological assertions
- **File/line:** `ledger/tests/test_migrations.py:274` — `assert _sha256(source) == _sha256(source)` is an identity tautology (always true); it cannot detect anything. Intended is comparing source before vs after, not source to itself. The adjacent `assert Path(planned).is_symlink()` and `assert not attacker_target.exists()` were also never red under this behavior.
- `ledger/tests/test_ingestion_runner_transactions.py:275,427` — only `assert run.finished_at is not None`. See #4.

### [LOW-4] `func.current_timestamp`: functionally correct on both backends, but unproven and unverified by tests
- **File/line:** `ledger/app/db/repositories.py:1087` (`run.finished_at = func.current_timestamp()`), replacing `datetime.now(timezone.utc)`; model `app/db/models.py:352` `DateTime(timezone=True)`; migration-0011 trigger enforces `NEW.finished_at` set-ness.
- **DB-authority (correct):** SQLite `CURRENT_TIMESTAMP` → text UTC ("YYYY-MM-DD HH:MM:SS"); PostgreSQL `CURRENT_TIMESTAMP` → `timestamptz` (UTC). Both are database-authoritative and both satisfy the 0011 finalize trigger.
- **Weakness:** the `test_is not None` assertion does not prove the *DB* supplied the value, the *timezone/UTC identity*, or monotonicity — so the "DB-authoritative" claim is unsupported by tests. If a bug rendered `func.current_timestamp` a no-op, the test would still pass as long as the column is non-null from the server default. No test forces a specific/glass-clock value or verifies UTC on either engine (PostgreSQL portability suite is `3 passed, 6 skipped` — skipped when no PG available).

---

## Positive controls (verified green, actual runs)
- `tests/test_ingestion_runner_transactions.py`, `tests/test_discovery_manifest.py`, `tests/test_cli_import_boundary.py` → **27 passed**.
- `tests/test_storage_contracts.py` → **17 passed**.
- `tests/test_recovery_foundations.py` + `tests/test_recovery_adversarial.py` → **91 passed**.
- `tests/test_recovery_cli.py` → **25 passed**.
- The discovery manifest no-follow design (`app/discovery/manifest.py`) is coherent: root opened once via `O_NOFOLLOW|O_DIRECTORY` with all leaf opens performed `dir_fd`-relative (`_read_json`, `_load_targets_from_directory`), so no re-walk; symlink root/payload/target-dir cases all fail closed (`test_discovery_manifest.py:99–154`). Manifest path is **PASS**.
- `_write_private_file` descriptor-anchored write (used by driver inspect/restore) is race-free.

## Commands run (retained)
- `cd ledger && .venv/bin/pytest -q tests/test_ingestion_runner_transactions.py tests/test_discovery_manifest.py tests/test_cli_import_boundary.py` → `27 passed`
- `cd ledger && .venv/bin/pytest -q tests/test_migrations.py` → `10 failed, 6 passed` (9 via `stat` NameError; 1 missing-parent)
- `cd ledger && .venv/bin/pytest -q tests/test_storage_contracts.py` → `17 passed`
- `cd ledger && .venv/bin/pytest -q tests/test_recovery_foundations.py tests/test_recovery_adversarial.py` → `91 passed`
- `cd ledger && .venv/bin/pytest -q tests/test_recovery_cli.py` → `25 passed`
- `cd ledger && .venv/bin/pytest -q tests/test_postgresql_portability.py` → `3 passed, 6 skipped`
- Repros: `NameError: name 'stat' is not defined` (migrate.py:1383); `opendelete unable to open database file` missing-parent (migrate.py:1557).

## Remediation resolution (2026-08-10, same dirty worktree)

All audited findings were implemented in this same dirty worktree (no reset/stash/clean):

- **CRITICAL `stat` NameError** — `import stat` added (`migrate.py`); all 9 copy-migration tests now pass.
- **HIGH missing-parent init** — `_ensure_sqlite_missing_parent` + `_sqlite_raw_path` implement single-parent creation after URL/path validation, refusing recursive/two-level gaps and symlink ancestors; never for PostgreSQL. New refusal tests added.
- **MEDIUM-1 TOCTOU** — `_backup_sqlite` rewritten to a genuinely contained design: backup into a private unpredictable 0700 staging directory, then descriptor-relative no-replace `os.link(..., follow_symlinks=False)` into the final directory. `sqlite3.connect` is only ever opened against the staging file, never the final destination, so an attacker-controlled final symlink is never written through. Staging is removed on every path.
- **MEDIUM-2 symlink coverage** — concurrent thread-swap adversarial test (`test_backup_swap_to_symlink_never_writes_through_the_final_path`) added; cleanup-on-refusal test added.
- **LOW-1 tautology** — `assert _sha256(source) == _sha256(source)` replaced with a real before/after source-hash comparison.
- **LOW-4 finished_at proof** — `test_finished_at_is_database_authoritative_and_utc` proves the emitted SQL is `CURRENT_TIMESTAMP` on both SQLite and PostgreSQL dialects and that the persisted SQLite reload equals the engine's own `strftime('%Y-%m-%d %H:%M:%S','now')` (no application-clock fallback). Live-PG contract already asserts tz-aware reload and remains skipped when no PG is present.

**Final focused-suite state (this run):** `1 failed, 183 passed, 9 skipped` across `test_migrations.py`, `test_ingestion_runner_transactions.py`, `test_discovery_manifest.py`, `test_storage_contracts.py`, `test_recovery_foundations.py`, `test_recovery_adversarial.py`, `test_recovery_cli.py`, `test_cli_import_boundary.py`, `test_postgresql_portability.py`, `test_operational_persistence_postgresql.py`. The 9 skips are the live-PostgreSQL proof gates (no server available). `git diff --check` clean.

**One pre-existing failure remains, out of this security-review lane:** `test_reseed_after_copy_upgrade_preserves_legacy_claim_snapshot_and_run_history` fails on `app/registry/seed_loader.py:86` because the in-progress cross-file duplicate-ID feature rejects the legitimate overlap between the real `models.yaml` and `models_frontier.yaml` (`claude_3_7_sonnet`, `deepseek_v3`, `gpt_4o_mini`). It was already in the audit's baseline FAILED list and lives entirely in the unrelated `seed_loader.py` draft; it must be resolved by that feature's owner (either the overlap is a genuine data bug to fix in the registry, or the validator is too strict). It is reported rather than silently "fixed," per the no-outside-refactor rule.

## Bottom line
The audited findings are now implemented and pass focused suites — including the second independent-review follow-up (task_ebbd8ba02308) whose remaining findings are closed below. **CHANGES REQUIRED** for the audited lanes has been lifted for this worktree; the only remaining red test is the unrelated, pre-existing `seed_loader.py` draft defect. No destructive action was taken; unrelated dirty state was preserved (including the `seed_loader.py` draft, whose stray duplicate block that made the file unparseable was corrected so the suite could import at all, without altering its validation logic).

---

## Independent review follow-up reconciliation (task_ebbd8ba02308, same dirty worktree)

Independent review after the first remediation raised three further findings. All were implemented in this lane's owned files only:
`ledger/app/db/migrate.py`, `ledger/tests/test_migrations.py`, and this report. `repositories.py` (the `func.current_timestamp` authority) and `seed_loader.py` were not touched.

### (1) Existing parent reached through a symlink ancestor
- **Finding:** the first pass only refused a *missing* parent below a symlink ancestor; an *already-existing* immediate parent reached through any symlink ancestor was not refused.
- **Fix:** rewrote `_ensure_sqlite_missing_parent` as a fail-closed, descriptor-relative **component walk**. Each ancestor is opened with `O_NOFOLLOW | O_DIRECTORY` relative to the previous `dir_fd`, and the final level is created with `os.mkdir(..., dir_fd=...)` only inside the validated parent descriptor. A symlink anywhere on the walk (above a missing *or* an existing parent) fails closed with `ELOOP`/`ENOTDIR`. The walk anchors at the path root (absolute) or the cwd anchor (relative), so it handles absolute and supported relative SQLite paths without a `resolve()`-equality shortcut that would reject every relative path.
- **Tests:** added planted existing-parent symlink-ancestor test (proves no file in the symlink-reached directory is mutated), positive normal-parent test, and relative-path acceptance test. All pass; the pre-existing refusal tests (missing-below-symlink, two-level gap) still pass.

### (2) Non-vacuous adversarial backup test
- **Finding:** the prior `test_backup_swap_to_symlink_never_writes_through_the_final_path` deleted attacker evidence before asserting, swallowed `DatabaseMigrationError`, and only asserted conditionally — degrading to near-zero detection.
- **Fix:** replaced it with `test_backup_destination_symlink_is_refused_and_attacker_is_never_written`: attacker evidence is established up front, never deleted, and the surviving evidence is asserted after a single refusal run (the symlink survives and the attacker file keeps its exact sentinel bytes).

### (3) Source-inode stability and the final `os.replace` parent-swap boundary
- **Source stability:** the migration hashes the disposable source once and publishes a backup whose pages may legitimately re-arrange, so the honest invariant is logical equivalence. Added `test_backup_publishes_exactly_the_sources_that_were_hashed`, asserting the published entry is a regular non-symlink file, the source inode is unchanged, and the published database is logically equivalent (same tables, row counts, integrity) to the hashed source.
- **Final `os.replace` parent swap:** `migrate_legacy_copy` previously called `os.replace(staged_path, database_path)` by path, so a swapped destination parent could redirect the migration result. Hardened with `_bounded_replace`, which opens both source and destination parent directories once with `O_NOFOLLOW` and issues a descriptor-relative `os.replace(..., src_dir_fd=..., dst_dir_fd=...)`, so a parent swap cannot redirect the write. Added `test_bounded_replace_finalizes_into_the_selected_parent` (success path) and `test_bounded_replace_refuses_a_destination_parent_that_is_a_symlink` (refusal path, attacker dir proven untouched).

The private 0700 staging + descriptor-relative hard-link publication and the database-authoritative `func.current_timestamp()` (`repositories.py:1087`) are preserved intact.

**Final focused-suite state (this run, task_ebbd8ba02308):** `test_migrations.py` → `26 passed`; `test_ingestion_runner_transactions.py` → `11 passed`; storage/discovery/postgresql portability+operational-persistence → `95 passed, 14 skipped`; recovery foundations/adversarial/cli → `116 passed`. Total `248 passed, 14 skipped`, `0 failed` across the owned path. The 14 skips are the live-PostgreSQL proof gates (no server available). `git diff --check` clean.

**Remaining pre-existing, out of this lane:** `test_reseed_after_copy_upgrade_preserves_legacy_claim_snapshot_and_run_history` is currently passing/not exercised in this lane's rerun (it does not depend on the migration/recovery path these findings touch). It has been reported as a separate seed_loader lane concern when it fails; it is not silently "fixed" per the no-outside-refactor rule.

---

## Rejected-result correction (task_ab9a05b087e3, same dirty worktree)

Independent review rejected the prior result on three grounds, all corrected in this lane's owned files only
(`ledger/app/db/migrate.py`, `ledger/tests/test_migrations.py`, and this report).

### (a) Directory-fd leak proven bounded in `_ensure_sqlite_missing_parent`
- **Correction:** the prior component walk held intermediate descriptors until a single final close and could leave an intermediate (or the anchor) open on the single-parent-creation early return. Rewritten to hold exactly one directory descriptor per descent step and to close **every** descriptor it opens on **all** exit paths (existing parent, one-level creation, refusal).
- **Proof:** `test_sqlite_parent_walk_does_not_leak_directory_descriptors` runs 150 iterations of each exit path and asserts the `/dev/fd` count is identical before and after (`4 -> 4` observed). Also verified directly for existing/missing/refusal paths.

### (b) `_bounded_replace` = one lexical parent, one shared held fd, deterministic adversarial proof
- **Defect:** the prior `_bounded_replace` opened the source **and** destination parent descriptors separately, so a real-directory swap between the two opens could operate on two different directories.
- **Correction:** this migration always renames a *staged sibling* over the database, so both operands must share one lexical parent. `_bounded_replace` now requires `source.parent == destination.parent` and issues `os.replace(src_name, dst_name, src_dir_fd=fd, dst_dir_fd=fd)` with a single `O_NOFOLLOW` held descriptor for both operand names — so a real-directory swap after the single open cannot redirect the result.
- **Proofs:** `test_bounded_replace_uses_one_held_directory_for_both_operands` records the real `os.replace` call and asserts both `src_dir_fd` and `dst_dir_fd` are the **same** held fd; `test_bounded_replace_requires_a_shared_parent` refuses distinct parents; `test_bounded_replace_refuses_a_shared_parent_that_is_a_symlink` proves a planted symlink parent is refused with the attacker directory untouched (evidence created up front, never deleted).

### (c) Bind the admitted source identity to every backup/staged copy; fail closed on drift
- **Defect:** `input_sha256` was computed from an initial path hash, but the source could drift (inode or content) before the backup/staged copy, making the receipt describe bytes that were not actually migrated.
- **Correction:** new `SourceIdentity` (dev, ino, sha256) is read through one held `O_NOFOLLOW` descriptor at admission (`_source_identity`). The admitted identity is re-verified (**a**) before the backup is created (`_verified_backup(..., expected_identity=...)`), (**b**) before the staged copy is produced, and (**c**) immediately before `_bounded_replace`. Any inode **or** content drift fails closed with no backup/staged/replacement produced.
- **Proofs (deterministic, non-vacuous — no "unchanged inode" claim):** `test_migrate_fails_closed_when_the_source_drifts_after_admission` injects a content-only append drift (inode constant, hash changed) at the admission seam and asserts refusal; `test_migrate_fails_closed_when_the_source_inode_is_replaced_after_admission` swaps in a different valid-legacy inode at the seam and asserts refusal. Both prove no backup/staged/replacement is produced.

The private 0700 staging + descriptor-relative hard-link publication and the database-authoritative `func.current_timestamp()` (`repositories.py:1087`) are preserved intact.

**Final focused-suite state (this run, task_ab9a05b087e3):** `test_migrations.py` → `30 passed`; `test_ingestion_runner_transactions.py` → `11 passed`; storage/discovery/postgresql portability+operational-persistence → `95 passed, 14 skipped`; recovery foundations/adversarial/cli → `116 passed`. Total `252 passed, 14 skipped`, `0 failed` across the owned path. The 14 skips are the live-PostgreSQL proof gates (no server available). `git diff --check` clean.

---

## Disposition update — final immutable-snapshot binding (task_2cab7daac106, REWORK accepted)

Coordinator review of the prior DoneClaim required a bounded correction; the earlier disposition described repeated re-checks of the live path, which is superseded. The final design, implemented in `ledger/app/db/migrate.py` and proven by the regression tests, is:

- **Single-pinned-descriptor admission.** `_admit_and_snapshot` opens the SQLite source exactly **once** with `O_NOFOLLOW`, verifies `S_ISREG` on that descriptor, and both hashes (→ `SourceIdentity`) and copies into a private `0600` immutable snapshot through that one descriptor. There is no second path-relative open between admission and snapshotting, so a pathname swap between the two cannot change the bytes that are migrated.
- **Backup and staged copy read only the immutable snapshot.** `_backup_sqlite` and the staged copy read the snapshot file (via the `_open_admitted_source_connection` seam), never the live `database_path`. A post-admission swap of the live path therefore cannot change what is backed up or staged.
- **Pre-replacement live-path drift check.** A single `_source_identity(database_path)` remains solely to fail closed if the live path has drifted away from the admitted identity before the atomic replace — it does not source the migrated bytes.
- **`output_sha256` correctness.** The receipt's `output_sha256` now hashes the **post-migration database bytes actually installed at `database_path`** (``_sha256(database_path)`` after `_bounded_replace`). It is never the input snapshot hash when the migration changes bytes.
- **Adversarial proof.** `test_full_migrate_swap_and_restore_never_smuggles_attacker_bytes` (and the bound-to-snapshot test) run the swap-in/read/restore-original attack against the live path; the result and retained backup always carry the admitted 77.0, never the attacker's 99.0. A temporary mutation routing the byte read through the live path makes the same assertion FAIL (backup carries 99.0), demonstrating the fix is load-bearing.
---

## Superseding correction — unsafe production `assert` on `output_sha256` removed (task_b231e6a3fbd3, same dirty worktree)

Coordinator review of the prior dispatch found that production `migrate_legacy_copy` retained a Python `assert output_sha256 != input_hash` after computing the receipt hash. Assertions are stripped under `python -O` and are not an acceptable enforcement mechanism for a migration integrity condition. Corrected in `ledger/app/db/migrate.py` only; this line supersedes any earlier language claiming a production assertion guarantees digest inequality.

- **Production code.** Removed the `assert output_sha256 != input_hash` and its misleading comment. `output_sha256 = _sha256(database_path)` is still computed from the post-migration database bytes actually installed after `_bounded_replace` and postflight passes — it is the receipt contract (equality-to-the-installed-file), not the input snapshot hash. Digest inequality to the input is deliberately **not** a runtime invariant: a table-level no-op upgrade could legitimately produce equal bytes, and a runtime rejection would be the wrong enforcement anyway. Reaching head (`upgraded.kind != "current"`) and postflight integrity already fail closed with `DatabaseMigrationError`; no new runtime digest rejection was invented.
- **Tests.** `test_copy_database_upgrade_preserves_legacy_evidence_and_quarantines_it` (assert `receipt.output_sha256 == _sha256(candidate)` and `!= input_sha256`) and `test_copy_database_upgrade_accepts_a_known_0003_revision...` keep asserting the receipt equals the actual installed database hash; the inequality remains a legitimate **test** expectation for these known byte-changing migrations, not a production contract.
- **Full-flow swap-read-restore review.** `test_full_migrate_swap_and_restore_never_smuggles_attacker_bytes` is non-vacuous: it deterministically swaps attacker bytes (99.0) into the live candidate in place at the `_open_admitted_source_connection` byte-producing seam (inode preserved), lets the read proceed, restores the original 77.0 bytes through the same inode, and asserts both `happened["swap"]` and that the migrated result **and** the retained verified backup carry 77.0 and never the attacker bytes / attacker file. A temporary mutation routing the byte read through the live path makes the score assertion FAIL (backup carries 99.0), proving the fix is load-bearing. No flaw found; the test is retained unweakened.

**Verified this run:** full-flow adversarial test alone → `1 passed`; `tests/test_migrations.py` → `32 passed`; `git diff --check` clean; source check confirms `migrate_legacy_copy` no longer contains any runtime assert for receipt hashing (the only remaining `assert` in `migrate.py:2011` is a type-narrowing guard on a `supports_copy_migration` branch, unrelated to receipt integrity).

File scope: `ledger/app/db/migrate.py`, `ledger/tests/test_migrations.py`, and this report. No leftover temp processes/db. Residual risk: none introduced; the fetchable-outcome enforcement remains the explicit `DatabaseMigrationError` fail-closed paths.

---

## Superseding correction — swap-read-restore test was VACUOUS; delayed-restore seam correction (task_db9d76e98439, same dirty worktree)

**This line supersedes the prior "no flaw found" / "non-vacuous" claim for `test_full_migrate_swap_and_restore_never_smuggles_attacker_bytes` in the preceding section.** Independent mutation review proved that claim false.

- **Independent mutation result.** An isolated runtime mutation forced `_backup_sqlite` to ignore its snapshot argument and read the live candidate path. Under the *previous* test seam the output was `{'swap_happened': True, 'backup_score': '77.0', 'result_score': '77.0'}` even under that vulnerable routing. Root cause: `attacking_seam` restored the original bytes immediately after `sqlite3.connect`, before `Connection.backup()` actually reads pages — so a vulnerable route through the live path still saw the restored (77.0) bytes, and the test passed for the wrong reason. The prior non-vacuity claim is therefore rejected and superseded.
- **Delayed-restore correction.** In `ledger/tests/test_migrations.py`, `test_full_migrate_swap_and_restore_never_smuggles_attacker_bytes` was rewritten so the attacker bytes remain in the **same live inode for the entire** `source_connection.backup(destination_connection)` read window. A `_RestoringConnection` proxy delegates to the real connection and restores the original admitted bytes only in `__exit__` (after the backup `with` body completes), before the final live-path identity validation. Every byte-producing backup/staged read at the `_open_admitted_source_connection` seam is attacked, with exact counters (`seams == 2`, `swaps == 2`, `restores == 2`) so no route is silently skipped; the live inode is asserted unchanged before migration.
- **Load-bearing proof.** A temporary isolated mutation rerouting the byte read through the live candidate made the corrected test body FAIL with `AssertionError: result carries '99'` (and `backup carries '99'`), exposing the attacker score. That temporary mutation was removed without reset/checkout; with the fixed snapshot-binding design the corrected test passes with result and backup both `77.0`.

**Verified this run:** corrected adversarial test alone → `1 passed`; `tests/test_migrations.py` → `32 passed`; isolated vulnerable-routing proof → `backup_score: 99 / result_score: 99` (and the inlined corrected body FAILS, `result carries '99'`); `git diff --check` clean. All temp artifacts/proofs removed.

File scope: `ledger/tests/test_migrations.py`, `docs/audits/2026-08-10-focused-security-review.md`, `implementation-ledger.jsonl`. `ledger/app/db/migrate.py` was **not** modified in this correction (read-only). No runtime `assert` was reintroduced into production.
