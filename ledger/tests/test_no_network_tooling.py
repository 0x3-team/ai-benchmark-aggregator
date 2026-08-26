"""Static policy: no runnable app/script Python performs a raw outbound GET.

Direct-network helper scripts are retired: their tracked entrypoints are
restored as no-network stubs and no runnable raw-network copy is retained
anywhere on disk. The production ``SafeFetch`` seam in ``app/ingestion/`` is
the only sanctioned transport and defaults to a disabled network transport.

Unlike a purely tracked-tree scan, this test walks the **on-disk** runnable
``app/``, ``scripts/``, and ``tools/`` trees, so it also catches untracked task outputs
that might smuggle a raw HTTP client back into a runnable path. Test files are
excluded because they legitimately quote these strings, and the single
governed seam is allowed explicitly — every other runnable file must be free
of raw outbound client calls.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

LEDGER = Path(__file__).resolve().parents[1]

# Client entrypoints that perform an unbound outbound GET outside SafeFetch.
# These are the raw-network signatures the tooling backlog requires to be gone.
BANNED_CALLS = (
    "httpx.get(",
    "httpx.Client(",
    "requests.get(",
    "requests.post(",
    "requests.request(",
    "urllib.request.urlopen(",
    "request.urlopen(",
    "urlopen(",
)

# The governed transport seam that is *allowed* to open a network object. Under
# this seam the default transport refuses all outbound traffic; a private
# runner must explicitly grant authority.
SAFE_FETCH_SEAM = "app/ingestion/safe_fetch.py"

# Runnable roots we gate. ``scripts/`` includes any untracked task outputs the
# prior worker left there; a directory that could hold a runnable raw-network
# copy is NOT exempted.
_RUNNABLE_DIRS = ("app", "scripts", "tools")


def _runnable_py_files() -> list[str]:
    """Every ``.py`` file on disk under the runnable app/ and scripts/ trees.

    Uses the filesystem, not ``git ls-files``, so untracked files contributed
    by other workers (task outputs, new tools) are also inspected. Test
    directories are not runnable tooling paths and are out of policy scope.
    """
    out: list[str] = []
    for root in _RUNNABLE_DIRS:
        base = LEDGER / root
        if not base.is_dir():
            continue
        for dirpath, _dirnames, filenames in os.walk(base):
            # Keep __pycache__ out of the policy scan; it is not runnable source.
            if "__pycache__" in dirpath:
                continue
            for name in filenames:
                if name.endswith(".py"):
                    rel = Path(dirpath).relative_to(LEDGER).as_posix() + "/" + name
                    out.append(rel)
    return sorted(out)


_ALL = _runnable_py_files()


@pytest.mark.parametrize("path", _ALL, ids=lambda p: p)
def test_runnable_python_has_no_direct_network_call(path: str):
    full = LEDGER / path
    if not full.exists():
        raise AssertionError(f"expected on-disk runnable python file but it is missing: {path}")
    text = full.read_text(encoding="utf-8")
    if path == SAFE_FETCH_SEAM:
        # The governed seam may legitimately contain socket/url helpers; it is
        # covered by its own suite and defaults to a disabled transport.
        return
    for banned in BANNED_CALLS:
        if banned in text:
            raise AssertionError(
                f"{path} contains a raw outbound call {banned!r}; use the SafeFetch seam."
            )


def test_safe_fetch_seam_is_still_the_single_network_boundary():
    seam = LEDGER / SAFE_FETCH_SEAM
    assert seam.exists(), "governed SafeFetch seam must remain present"
    text = seam.read_text(encoding="utf-8")
    assert (
        "DisabledNetworkTransport" in text
    ), "SafeFetch seam must keep a fail-closed disabled transport"


@pytest.mark.parametrize(
    "rel",
    [
        "tools/retired/check_aider_yaml.py",
        "tools/retired/check_bfcl_humaneval.py",
        "tools/retired/check_frontiercode.py",
        "tools/retired/check_gaia.py",
        "tools/retired/check_paperbench.py",
        "tools/retired/check_tool_mt.py",
        "tools/retired/check_urls.py",
        "tools/retired/dump_tables.py",
        "tools/retired/test_hf_urls.py",
    ],
)
def test_legacy_network_helper_is_a_no_network_stub(rel: str):
    """The tracked legacy entrypoint must run, exit non-zero, and touch no network.

    Invoking the module is the proof: if the stub still smuggled a raw client it
    would import/execute live-fetch code. A retired helper must fail closed at
    run time with a clear message and no socket.
    """
    full = LEDGER / rel
    assert full.exists(), f"legacy entrypoint {rel} must remain tracked on disk"
    text = full.read_text(encoding="utf-8")
    for banned in BANNED_CALLS:
        assert banned not in text, f"{rel} is a stub and must not contain {banned}"

    proc = subprocess.run(
        [sys.executable, str(full)],
        cwd=str(LEDGER),
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert proc.returncode != 0, f"{rel} must exit non-zero (retired, no work done)"
    assert (
        "retired" in (proc.stderr + proc.stdout).lower()
    ), f"{rel} must print an explicit retired/governed message"


def test_no_runnable_raw_network_archive_is_retained_on_disk():
    """No ``scripts/retired/`` archive may hold a runnable raw copy.

    Retirement must preserve history through git, not by leaving an executable
    raw-network copy on disk where it can run again. A retired archive directory
    that would contain runnable raw code is a policy violation.
    """
    retired = LEDGER / "scripts" / "retired"
    if retired.is_dir():
        files = sorted(p for p in retired.rglob("*.py") if p.is_file())
        assert not files, (
            f"an on-disk archive holds runnable raw-network copies: {[f.name for f in files]}. "
            "Retirement preserves history through git; retain only tracked no-network stubs."
        )


_RETIRED_TOOL_NAMES = (
    "check_aider_yaml.py",
    "check_bfcl_humaneval.py",
    "check_frontiercode.py",
    "check_gaia.py",
    "check_paperbench.py",
    "check_tool_mt.py",
    "check_urls.py",
    "dump_tables.py",
    "test_hf_urls.py",
    "verify_adapter.py",
    "list_benchmark_ids.py",
)
_RETIRED_ENTRYPOINTS = tuple(f"ledger/tools/retired/{name}" for name in _RETIRED_TOOL_NAMES)


def test_retired_tools_are_relocated_out_of_ledger_root():
    for name in _RETIRED_TOOL_NAMES:
        assert not (LEDGER / name).exists(), f"retired helper must leave ledger root: {name}"
        assert (
            LEDGER / "tools" / "retired" / name
        ).is_file(), f"retired helper must be under ledger/tools/retired: {name}"


def test_no_owned_path_is_staged():
    """None of the worker-owned tooling paths may appear in the git index.

    The retired tools are intentionally left unstaged while this worker is active.
    """
    staged = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=str(LEDGER.parent),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    for path in _RETIRED_ENTRYPOINTS:
        assert path not in staged, f"owned path must not be staged: {path}"
    assert "ledger/scripts/retired" not in "\n".join(staged), "retired archive must not be staged"


def test_retired_moved_names_also_clean_from_index():
    """The old ``scripts/retired/`` destination names must not linger staged."""
    staged = subprocess.run(
        ["git", "diff", "--cached", "--name-status"],
        cwd=str(LEDGER),
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert "scripts/retired" not in staged, "no retired-dir path may be present in the index"


def test_rewritten_hf_seed_tooling_is_offline():
    seed = LEDGER / "scripts" / "seed_models_from_hf.py"
    assert seed.exists()
    text = seed.read_text(encoding="utf-8")
    for banned in BANNED_CALLS:
        assert banned not in text, f"rewritten seed tool must not contain {banned}"
    # Must accept an explicit input and an explicit new output path; never a
    # live registry path. The rewrite must refuse to overwrite existing work.
    assert "--input" in text
    assert "--output" in text
    assert ".open(" in text, "seed tool must use an explicit open() for its output"
    # The tool may only ever open the active registry files, and the only writer
    # path that resolves to a real file is the --output flag. Guard against a
    # future regression that writes straight into a registry filename.
    assert "--registry-dir" in text, "seed tool must scan an explicit registry directory"
    assert "NONE (review only)" in text, "review output must never claim a registry write"
