"""F4 regression: the acceptance smoke script must pin the repository venv
executable by absolute path, require a regular (non-symlink) executable, and
never resolve ``benchmark-ledger`` from PATH.

The former script preferred the first ``benchmark-ledger`` found on PATH and
only used ``PROJECT/.venv/bin/benchmark-ledger`` when PATH lookup failed, so a
PATH-preceding executable could impersonate the intended CLI (CWE-427/CWE-426).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import textwrap
from pathlib import Path

LEDGER = Path(__file__).resolve().parents[1]
ACCEPTANCE = LEDGER / "scripts" / "mvp_acceptance.sh"


def _capable_cli(marker: str, log_env: str) -> str:
    """Return a ``#!/bin/bash`` capable fake CLI script.

    Uses only bash builtins ``printf``/``case``/``exit`` plus shell
    redirection (no ``mkdir``/``cat``/``tee``/``env``/``dirname``/``touch``
    and no ``if``/``[``), so it cannot be subverted through PATH-resolved
    helpers.  The log directory must already exist.  After appending the exact
    ``"$*"`` once to the selected env log, it prints the unique marker
    unconditionally, then dispatches on the exact full ``"$*"`` string:

    - ``init-db`` succeeds.
    - ``seed-registry`` prints nonzero benchmarks/models/sources and succeeds.
    - ``db preflight`` prints current/integrity true and succeeds.
    - ``ingest --source fake_local_fixture --dry-run`` prints ``Ingestion
      blocked`` and exits 1.
    - anything else exits 1.
    """
    return textwrap.dedent(
        f"""\
        #!/bin/bash
        printf '%s\\n' "$*" >> "${log_env}"
        printf '{marker}\\n'
        case "$*" in
            "init-db")
                printf 'initialized\\n'
                exit 0
                ;;
            "seed-registry")
                printf 'benchmarks: 3\\nmodels: 5\\nsources: 2\\n'
                exit 0
                ;;
            "db preflight")
                printf '%s\\n' '{{"kind": "current", "integrity_ok": true}}'
                exit 0
                ;;
            "ingest --source fake_local_fixture --dry-run")
                printf 'Ingestion blocked: quarantined fixture\\n'
                exit 1
                ;;
            *)
                exit 1
                ;;
        esac
        """
    )


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def _fake_ledger_tree(tmp_path: Path) -> Path:
    """Materialize a physical fake project tree (no symlinks anywhere).

    The script derives ``PROJECT`` from its own location, so copying it into
    ``<fake>/ledger/scripts/`` makes ``PROJECT=<fake>/ledger`` without touching
    the real tree.  The tree is fully physical: every directory is a real
    directory and the venv binary is a regular executable file, so the only
    symlink under test is the one the tests create deliberately.
    """
    scripts = tmp_path / "ledger" / "scripts"
    scripts.mkdir(parents=True)
    shutil.copy2(ACCEPTANCE, scripts / "mvp_acceptance.sh")
    venv_bin = tmp_path / "ledger" / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    _write_executable(
        venv_bin / "benchmark-ledger",
        _capable_cli("REPO-VENV-CLI", "REPO_CALL_LOG"),
    )
    return tmp_path / "ledger"


def _impostor_bin(tmp_path: Path) -> None:
    """A PATH-preceding impostor that must never run.  Equally capable."""
    impostor_dir = tmp_path / "impostor"
    impostor_dir.mkdir()
    _write_executable(
        impostor_dir / "benchmark-ledger",
        _capable_cli("PATH-IMPOSTOR", "PATH_CALL_LOG"),
    )


def _external_target(tmp_path: Path) -> Path:
    """A real capable executable under tmp_path, outside .venv, that must never
    run.  Equally capable; its marker and log env are EXTERNAL-TARGET /
    EXTERNAL_CALL_LOG."""
    target = tmp_path / "external" / "benchmark-ledger"
    target.parent.mkdir(parents=True)
    _write_executable(
        target,
        _capable_cli("EXTERNAL-TARGET", "EXTERNAL_CALL_LOG"),
    )
    return target


def _run_smoke(
    script: Path,
    project: Path,
    tmp_path: Path,
    *,
    symlink_alias: bool = False,
    remove_repo_binary: bool = False,
    symlink_repo_binary: bool = False,
    env_extra: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    venv_bin = project / ".venv" / "bin"
    if remove_repo_binary:
        (venv_bin / "benchmark-ledger").unlink()
    if symlink_repo_binary:
        (venv_bin / "benchmark-ledger").unlink()
        (venv_bin / "benchmark-ledger").symlink_to(_external_target(tmp_path))

    impostor_dir = tmp_path / "impostor"
    env = os.environ.copy()
    # Capable PATH: standard tools still resolve, impostor directory first.
    env["PATH"] = f"{impostor_dir}:{env['PATH']}"
    if env_extra:
        env.update(env_extra)

    invoke_script = script
    if symlink_alias:
        alias_root = tmp_path / "alias"
        alias_root.mkdir()
        alias = alias_root / "ledger"
        alias.symlink_to(project, target_is_directory=True)
        invoke_script = alias / "scripts" / "mvp_acceptance.sh"

    return subprocess.run(
        ["/bin/bash", str(invoke_script)],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )


def test_acceptance_script_runs_full_smoke_via_pinned_venv_with_exact_ordered_repo_log(
    tmp_path: Path,
) -> None:
    """The full four-call smoke genuinely succeeds through the pinned venv CLI
    (invoked via a directory symlink alias to the physical project) with a
    capable PATH; the exact ordered repo argv log is recorded and the PATH
    impostor log is absent."""
    project = _fake_ledger_tree(tmp_path)
    script = project / "scripts" / "mvp_acceptance.sh"
    fake_logs = tmp_path / "fake-logs"
    fake_logs.mkdir()
    repo_log = fake_logs / "repo-calls.log"
    path_log = fake_logs / "path-calls.log"
    _impostor_bin(tmp_path)

    result = _run_smoke(
        script,
        project,
        tmp_path,
        symlink_alias=True,
        env_extra={
            "REPO_CALL_LOG": str(repo_log),
            "PATH_CALL_LOG": str(path_log),
        },
    )

    assert result.returncode == 0, result.stderr + result.stdout
    assert "CONTAINMENT SMOKE PASSED" in result.stdout
    assert "REPO-VENV-CLI" in result.stdout
    assert "PATH-IMPOSTOR" not in result.stdout
    assert "PATH-IMPOSTOR" not in result.stderr
    # Physical project path pinned, alias pinned path absent.
    pinned = f"{project.resolve()}/.venv/bin/benchmark-ledger"
    assert pinned in result.stdout
    assert f"{tmp_path / 'alias'}/ledger/.venv/bin/benchmark-ledger" not in result.stdout
    # Exact ordered repo log; PATH impostor log absent.
    assert repo_log.read_text(encoding="utf-8").splitlines() == [
        "init-db",
        "seed-registry",
        "db preflight",
        "ingest --source fake_local_fixture --dry-run",
    ]
    assert not path_log.exists() or path_log.read_text(encoding="utf-8") == ""


def test_acceptance_script_fails_closed_when_venv_binary_is_missing(
    tmp_path: Path,
) -> None:
    """Without the repo venv binary, the script must exit 1 and never fall back
    to a PATH executable."""
    project = _fake_ledger_tree(tmp_path)
    script = project / "scripts" / "mvp_acceptance.sh"
    fake_logs = tmp_path / "fake-logs"
    fake_logs.mkdir()
    path_log = fake_logs / "path-calls.log"
    _impostor_bin(tmp_path)

    result = _run_smoke(
        script,
        project,
        tmp_path,
        remove_repo_binary=True,
        env_extra={"PATH_CALL_LOG": str(path_log)},
    )
    assert result.returncode == 1
    assert "FATAL" in result.stderr
    assert "PATH-IMPOSTOR" not in result.stdout
    assert "PATH-IMPOSTOR" not in result.stderr
    assert not path_log.exists() or path_log.read_text(encoding="utf-8") == ""


def test_acceptance_script_fails_closed_when_venv_binary_is_a_symlink(
    tmp_path: Path,
) -> None:
    """A symlinked venv binary must be rejected: a link could redirect to a real
    external executable, so the script must exit 1 without running it and
    without running the PATH impostor or the external target."""
    project = _fake_ledger_tree(tmp_path)
    script = project / "scripts" / "mvp_acceptance.sh"
    fake_logs = tmp_path / "fake-logs"
    fake_logs.mkdir()
    path_log = fake_logs / "path-calls.log"
    external_log = fake_logs / "external-calls.log"
    _impostor_bin(tmp_path)

    result = _run_smoke(
        script,
        project,
        tmp_path,
        symlink_repo_binary=True,
        env_extra={
            "PATH_CALL_LOG": str(path_log),
            "EXTERNAL_CALL_LOG": str(external_log),
        },
    )
    assert result.returncode == 1
    assert "symbolic link" in result.stderr
    assert "PATH-IMPOSTOR" not in result.stdout
    assert "PATH-IMPOSTOR" not in result.stderr
    assert "EXTERNAL-TARGET" not in result.stdout
    assert "EXTERNAL-TARGET" not in result.stderr
    assert "CONTAINMENT SMOKE PASSED" not in result.stdout
    assert not path_log.exists() or path_log.read_text(encoding="utf-8") == ""
    assert not external_log.exists() or external_log.read_text(encoding="utf-8") == ""
