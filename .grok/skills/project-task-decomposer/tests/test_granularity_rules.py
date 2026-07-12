from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "examples" / "example-corpus"
SCRIPTS = ROOT / "scripts"


def test_granularity_pass():
    p = subprocess.run(
        [sys.executable, str(SCRIPTS / "audit_granularity.py"), str(CORPUS)],
        capture_output=True,
        text=True,
        check=False,
    )
    data = json.loads(p.stdout)
    assert data["status"] in {"PASS", "WARN"}, data
    assert p.returncode == 0
