"""Static containment checks for the inert P3 private-runner candidate."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys

import pytest

from app.runtime.dependencies import NoOpRateLimiter, RuntimeDependencyError
from scripts import private_runner_p3

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/private-ledger-recheck.yml"
RUNNER = ROOT / "ledger/scripts/private_runner_p3.py"


def test_private_runner_workflow_is_manual_only_and_schedule_is_inert() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "pull_request:" not in text
    assert "push:" not in text
    assert "workflow_dispatch:" in text
    assert "activate_private_runner:" in text
    assert "default: false" in text
    assert "# schedule:" in text
    assert '#   - cron: "0 4,16 * * *"' in text
    assert "github.event_name == 'workflow_dispatch' && inputs.activate_private_runner == true && github.ref == 'refs/heads/main'" in text
    assert "|| github.event_name == 'schedule'" in text
    assert "always() && (inputs.activate_private_runner == true || github.event_name == 'schedule')" not in text
    assert "always() && ((github.event_name == 'workflow_dispatch' && inputs.activate_private_runner == true && github.ref == 'refs/heads/main') || github.event_name == 'schedule')" in text


def test_private_runner_workflow_has_explicit_auth_and_data_plane_fences() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "token: ${{ github.token }}" in text
    assert "GH_TOKEN: ${{ github.token }}" in text
    assert "permissions:\n  contents: read" in text
    assert "LEDGER_DATA_REPOSITORY_TOKEN" in text
    assert "LEDGER_RUNNER_REPOSITORY_TOKEN" not in text
    assert "LEDGER_FAILURE_ISSUE_TOKEN" not in text
    assert "LEDGER_RUNNER_DATABASE_URL" not in text
    assert "persist-credentials: false" in text
    assert "persist-credentials: true" not in text
    assert "concurrency:\n  group: private-ledger-data-plane\n  cancel-in-progress: false" in text
    assert 'flock --nonblock "$RUNNER_TEMP/private-ledger-data-plane.lock"' in text
    assert "runs-on: ubuntu-latest" in text
    assert "environment: private-ledger-production" in text
    assert "actions: read" in text
    assert "issues: write" in text
    assert text.count("LEDGER_DATA_REPOSITORY_TOKEN: ${{ secrets.LEDGER_DATA_REPOSITORY_TOKEN }}") == 2
    assert text.count("${{ secrets.LEDGER_DATA_REPOSITORY_TOKEN }}") == 3
    assert "GIT_ASKPASS" in text
    assert 'destination="https://github.com/${LEDGER_DATA_REPOSITORY}.git"' in text
    assert 'git clone --bare --no-local "$LEDGER_DATA_DIR" "$push_repository"' in text
    assert 'config --local --remove-section remote.origin' in text
    assert 'git --git-dir="$push_repository" fsck --no-dangling' in text
    assert 'push "$LEDGER_PUSH_DESTINATION" HEAD:refs/heads/main' in text
    assert "push origin" not in text
    assert "GIT_CONFIG_NOSYSTEM=1" in text
    assert "GIT_CONFIG_KEY_1=credential.helper" in text
    assert "GIT_CONFIG_KEY_2=http.https://github.com/.extraheader" in text
    assert "-c core.hooksPath=/dev/null" in text

    prepare = text.split("      - name: Prepare immutable checkpoint and snapshot artifacts only", 1)[1].split(
        "      - name: Push prepared immutable artifacts", 1
    )[0]
    prepare_push = text.split("      - name: Prepare sanitized push repository", 1)[1].split(
        "      - name: Push prepared immutable artifacts", 1
    )[0]
    push = text.split("      - name: Push prepared immutable artifacts", 1)[1].split(
        "  repeated-failure-issue:", 1
    )[0]
    assert "LEDGER_DATA_REPOSITORY_TOKEN" not in prepare
    assert "private_runner_p3.py" in prepare
    assert "git -C \"$LEDGER_DATA_DIR\" commit" in prepare
    assert "LEDGER_DATA_REPOSITORY_TOKEN" not in prepare_push
    assert "LEDGER_DATA_REPOSITORY_TOKEN" in push
    assert "GIT_CONFIG_NOSYSTEM=1" in prepare_push
    assert "GIT_CONFIG_GLOBAL=/dev/null" in prepare_push
    assert "private_runner_p3.py" not in push
    assert "git -C \"$LEDGER_DATA_DIR\" commit" not in push


def test_private_runner_persists_only_additive_checkpoint_and_snapshot_artifacts() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    runner = RUNNER.read_text(encoding="utf-8")
    assert "git -C \"$LEDGER_DATA_DIR\" add -- snapshots recovery/checkpoints" in text
    assert "assert-data-repo pre-add" in text
    assert "assert-data-repo staged-adds" in text
    assert '"snapshots/", "recovery/checkpoints/"' in runner
    assert "lstat()" in runner
    assert "nested repository" in runner
    assert 'state == b"??"' in runner
    assert 'state == b"A "' in runner
    assert "--ignored=matching" in runner
    assert "artifact tree and staged index differ" in runner
    assert '"hash-object", "--no-filters"' in runner


def test_live_dependency_candidate_is_explicit_but_h4_blocks_execution() -> None:
    text = RUNNER.read_text(encoding="utf-8")
    assert "PinnedHTTPSFetchTransport()" in text
    assert "RuntimeCapability.NETWORK_FETCH" in text
    assert "rate_limiter: RateLimiter, data_dir: Path" in text
    assert "storage_factory=LocalSnapshotStorageFactory(root / \"snapshots\")" in text
    assert "DenyAllP3RateLimiter" in text
    assert "P3SerialRateLimiter" not in text
    assert "def verify_fresh_or_current_database" in text
    assert 'status.kind == "empty"' in text
    assert "initialize_database(database_url)" in text
    assert "migrate_legacy_copy" not in text
    assert "upgrade_postgresql_database" not in text
    assert "run_ingestion(" in text
    assert "H4_BLOCKED" in text
    assert "Refusing unbound ingestion" in text


def test_importable_live_helpers_require_a_real_caller_supplied_limiter(tmp_path: Path) -> None:
    data_dir = _data_repo(tmp_path)
    with pytest.raises(TypeError):
        private_runner_p3.pinned_network_dependencies()  # type: ignore[call-arg]
    with pytest.raises(RuntimeDependencyError):
        private_runner_p3.pinned_network_dependencies(
            rate_limiter=NoOpRateLimiter(), data_dir=data_dir
        )
    dependencies = private_runner_p3.pinned_network_dependencies(
        rate_limiter=private_runner_p3.DenyAllP3RateLimiter(), data_dir=data_dir
    )
    assert dependencies.storage_factory is not None
    assert dependencies.storage_factory.root == data_dir / "snapshots"
    with pytest.raises(private_runner_p3.PrivateRunnerBlockedError, match="refuses every fetch"):
        private_runner_p3.DenyAllP3RateLimiter().acquire(
            source_id="source",
            url="https://example.invalid",
            observed_at=object(),
        )


def test_repeated_failure_issue_requires_two_prior_consecutive_failures() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "name: private-ledger-run" in text
    assert "--limit 20 --json databaseId" in text
    assert 'select(.name == "private-ledger-run")' in text
    assert 'skipped|absent)' in text
    assert "select(.databaseId != $GITHUB_RUN_ID)" in text
    assert 'if [ "$prior_failures" -lt 2 ]' in text


def _candidate(data_dir: Path, mode: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(RUNNER), "assert-data-repo", mode, str(data_dir)],
        cwd=ROOT / "ledger",
        check=False,
        capture_output=True,
        text=True,
    )


def _git(data_dir: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(data_dir), *args], check=True, capture_output=True)


def _data_repo(tmp_path: Path) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.name", "test")
    _git(tmp_path, "config", "user.email", "test@example.invalid")
    return tmp_path


def test_data_repository_containment_rejects_modified_or_non_artifact_files(tmp_path: Path) -> None:
    _data_repo(tmp_path)
    (tmp_path / "snapshots").mkdir()
    (tmp_path / "snapshots" / "new-object").write_text("new", encoding="utf-8")
    allowed = _candidate(tmp_path, "pre-add")
    assert allowed.returncode == 0, allowed.stderr

    _git(tmp_path, "add", "snapshots")
    staged = _candidate(tmp_path, "staged-adds")
    assert staged.returncode == 0, staged.stderr

    (tmp_path / "README.md").write_text("blocked", encoding="utf-8")
    blocked = _candidate(tmp_path, "staged-adds")
    assert blocked.returncode == 2
    assert "DATA_REPOSITORY_CONTAINMENT" in blocked.stderr


def test_data_repository_containment_rejects_symlink_and_nested_repo(tmp_path: Path) -> None:
    data_dir = _data_repo(tmp_path)
    snapshots = data_dir / "snapshots"
    snapshots.mkdir()
    (snapshots / "escape").symlink_to(tmp_path.parent / "outside")
    symlink = _candidate(data_dir, "pre-add")
    assert symlink.returncode == 2
    assert "DATA_REPOSITORY_CONTAINMENT" in symlink.stderr

    (snapshots / "escape").unlink()
    nested = snapshots / "nested"
    nested.mkdir()
    _git(nested, "init")
    nested_repo = _candidate(data_dir, "pre-add")
    assert nested_repo.returncode == 2
    assert "DATA_REPOSITORY_CONTAINMENT" in nested_repo.stderr


def test_data_repository_containment_rejects_a_symlinked_supplied_root(tmp_path: Path) -> None:
    data_dir = _data_repo(tmp_path / "data")
    alias = tmp_path / "alias"
    alias.symlink_to(data_dir, target_is_directory=True)
    blocked = _candidate(alias, "pre-add")
    assert blocked.returncode == 2
    assert "DATA_REPOSITORY_CONTAINMENT" in blocked.stderr


def test_data_repository_containment_rejects_ignored_artifact(tmp_path: Path) -> None:
    data_dir = _data_repo(tmp_path)
    (data_dir / ".gitignore").write_text("snapshots/ignored\n", encoding="utf-8")
    _git(data_dir, "add", ".gitignore")
    _git(data_dir, "commit", "-m", "ignore artifact")
    ignored = data_dir / "snapshots" / "ignored"
    ignored.parent.mkdir()
    ignored.write_text("ignored", encoding="utf-8")
    blocked = _candidate(data_dir, "pre-add")
    assert blocked.returncode == 2
    assert "ignored artifact" in blocked.stderr


@pytest.mark.parametrize("relative", ["snapshots/.git/object", "recovery/checkpoints/.gitmodules/object"])
def test_data_repository_containment_rejects_git_metadata_path_components(
    tmp_path: Path, relative: str
) -> None:
    data_dir = _data_repo(tmp_path)
    candidate = data_dir / relative
    candidate.parent.mkdir(parents=True)
    candidate.write_text("blocked", encoding="utf-8")
    blocked = _candidate(data_dir, "pre-add")
    assert blocked.returncode == 2
    assert "DATA_REPOSITORY_CONTAINMENT" in blocked.stderr


def test_data_repository_containment_rejects_tracked_modification_and_staged_symlink(tmp_path: Path) -> None:
    data_dir = _data_repo(tmp_path)
    tracked = data_dir / "snapshots" / "old-object"
    tracked.parent.mkdir()
    tracked.write_text("old", encoding="utf-8")
    _git(data_dir, "add", "snapshots")
    _git(data_dir, "commit", "-m", "baseline")
    tracked.write_text("changed", encoding="utf-8")
    modified = _candidate(data_dir, "pre-add")
    assert modified.returncode == 2
    assert "DATA_REPOSITORY_CONTAINMENT" in modified.stderr

    _git(data_dir, "restore", "snapshots/old-object")
    (data_dir / "snapshots" / "linked-object").symlink_to(tracked)
    _git(data_dir, "add", "snapshots/linked-object")
    staged_link = _candidate(data_dir, "staged-adds")
    assert staged_link.returncode == 2
    assert "DATA_REPOSITORY_CONTAINMENT" in staged_link.stderr


def test_staged_artifacts_require_exact_index_coverage_and_raw_bytes(tmp_path: Path) -> None:
    data_dir = _data_repo(tmp_path)
    artifact = data_dir / "snapshots" / "object"
    artifact.parent.mkdir()
    artifact.write_bytes(b"worktree bytes")
    _git(data_dir, "add", "snapshots")
    assert _candidate(data_dir, "staged-adds").returncode == 0

    _git(data_dir, "rm", "--cached", "snapshots/object")
    blocked = _candidate(data_dir, "staged-adds")
    assert blocked.returncode == 2
    assert "DATA_REPOSITORY_CONTAINMENT" in blocked.stderr
