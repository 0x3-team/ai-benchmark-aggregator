"""Offline, review-only behavior of the HF model candidate generator.

The rewritten ``scripts/seed_models_from_hf.py`` must never open a network
socket, never overwrite an existing output, and never write any active registry
file (notably ``models_frontier.yaml`` or ``models_hf_seed.yaml``). It emits a
brand-new review queue only.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

LEDGER = Path(__file__).resolve().parents[1]
TOOL = LEDGER / "scripts" / "seed_models_from_hf.py"
FIXTURE = Path(__file__).parent / "fixtures" / "hf_seed_candidates.yaml"


def _run_tool(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(TOOL), *args],
        cwd=str(LEDGER),
        capture_output=True,
        text=True,
    )


def test_offline_seed_writes_review_file_and_never_touches_registry(tmp_path: Path):
    out = tmp_path / "candidates.out.yaml"
    proc = _run_tool("--input", str(FIXTURE), "--output", str(out), "--registry-dir", str(tmp_path))

    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert out.exists()
    lines = out.read_text(encoding="utf-8")
    assert "NONE (review only)" in lines
    assert "novel-bench-7b" in lines or "acme/novel-bench-7b" in lines


def test_offline_seed_reports_collision_and_writes_nothing(tmp_path: Path):
    # Seed a real-looking registry file that already contains one of the
    # candidate IDs, so the tool must fail closed and write nothing.
    registry = tmp_path / "models_frontier.yaml"
    registry.write_text(
        "models:\n  - id: acme/novel-bench-7b\n    canonical_name: NovelBench-7B\n",
        encoding="utf-8",
    )
    out = tmp_path / "out.yaml"
    proc = _run_tool("--input", str(FIXTURE), "--output", str(out), "--registry-dir", str(tmp_path))

    assert proc.returncode == 1
    assert "COLLISIONS" in proc.stdout
    assert "acme/novel-bench-7b" in proc.stdout
    # Retained the governing file path in the report, and never wrote the
    # candidate output or the (already-present) frontier file.
    assert not out.exists(), "no output file should be written on a detected collision"
    assert registry.read_text(encoding="utf-8").startswith("models:"), "registry file untouched"


def test_offline_seed_no_overwrite(tmp_path: Path):
    out = tmp_path / "out.yaml"
    out.write_text("existing work\n", encoding="utf-8")

    proc = _run_tool("--input", str(FIXTURE), "--output", str(out), "--registry-dir", str(tmp_path))

    assert proc.returncode == 1
    assert "refusing to overwrite" in proc.stdout
    assert out.read_text(encoding="utf-8") == "existing work\n", "existing output must be untouched"


def test_offline_seed_never_invokes_network_client(tmp_path: Path):
    """The tool must never import or call a raw HTTP client."""
    text = TOOL.read_text(encoding="utf-8")
    for banned in ("import urllib.request", "import httpx", "import requests", "httpx.get(", "urlopen("):
        assert banned not in text, f"offline tool must not call {banned}"


def test_offline_seed_parse_error_fails_closed(tmp_path: Path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("models: [ { no, valid ]\n", encoding="utf-8")
    out = tmp_path / "out.yaml"
    proc = _run_tool("--input", str(bad), "--output", str(out), "--registry-dir", str(tmp_path))
    assert proc.returncode == 1


def test_offline_seed_does_not_define_any_network_symbol_in_its_imports():
    """The tool module exposes a main()/argparse CLI and no httpx/urllib import."""
    text = TOOL.read_text(encoding="utf-8")
    for banned_import in ("import httpx", "import urllib", "import requests"):
        assert banned_import not in text, f"tool must not import {banned_import}"