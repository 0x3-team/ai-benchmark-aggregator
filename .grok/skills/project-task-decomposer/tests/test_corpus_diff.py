from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "examples" / "example-corpus"
SCRIPTS = ROOT / "scripts"


def test_diff_self_all_unchanged_or_added_empty_change():
    p = subprocess.run(
        [sys.executable, str(SCRIPTS / "diff_corpora.py"), str(CORPUS), str(CORPUS)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert p.returncode == 0, p.stdout + p.stderr
    data = json.loads(p.stdout)
    assert data["added"] == []
    assert data["retired"] == []
    assert isinstance(data["unchanged"], list)
    assert len(data["unchanged"]) >= 3
