from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "examples" / "example-corpus"
SCRIPTS = ROOT / "scripts"


def test_example_task_jsonschema():
    import jsonschema
    from jsonschema import Draft202012Validator

    schema = json.loads((ROOT / "schemas" / "task.schema.json").read_text())
    task = json.loads((ROOT / "examples" / "example-task.json").read_text())
    Draft202012Validator(schema).validate(task)


def test_example_requirement_jsonschema():
    import jsonschema
    from jsonschema import Draft202012Validator

    schema = json.loads((ROOT / "schemas" / "requirement.schema.json").read_text())
    req = json.loads((ROOT / "examples" / "example-requirement.json").read_text())
    Draft202012Validator(schema).validate(req)


def test_validate_task_corpus_pass():
    p = subprocess.run(
        [sys.executable, str(SCRIPTS / "validate_task_corpus.py"), str(CORPUS), "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    data = json.loads(p.stdout)
    assert data["status"] == "PASS", data
    assert data["task_count"] >= 3
