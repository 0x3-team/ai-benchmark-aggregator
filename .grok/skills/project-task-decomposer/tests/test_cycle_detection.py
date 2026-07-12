from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "examples" / "example-corpus"
SCRIPTS = ROOT / "scripts"


def test_example_corpus_no_cycles():
    p = subprocess.run(
        [sys.executable, str(SCRIPTS / "detect_cycles.py"), str(CORPUS)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert p.returncode == 0, p.stdout + p.stderr
