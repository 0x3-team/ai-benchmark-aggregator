from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from stable_ids import task_id, requirement_id  # type: ignore


def test_task_id_stable():
    a = task_id(
        project_id="p",
        objective="Implement X",
        requirement_ids=["REQ-2", "REQ-1"],
        expected_outputs=["out B", "out A"],
    )
    b = task_id(
        project_id="p",
        objective="Implement X",
        requirement_ids=["REQ-1", "REQ-2"],
        expected_outputs=["out A", "out B"],
    )
    assert a == b
    assert a.startswith("TSK-")
    assert 12 <= len(a) <= 16


def test_task_id_changes_on_objective():
    a = task_id(project_id="p", objective="A", requirement_ids=["R1"], expected_outputs=["o"])
    b = task_id(project_id="p", objective="B", requirement_ids=["R1"], expected_outputs=["o"])
    assert a != b


def test_requirement_id_format():
    rid = requirement_id(project_id="p", statement="Users can login", source_refs=["SRC-1"])
    assert rid.startswith("REQ-")
