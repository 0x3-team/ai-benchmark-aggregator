#!/usr/bin/env python3
"""Dependency-free structural validator for a generated task corpus.

Core invariants without requiring jsonschema.
Use a Draft 2020-12 JSON Schema validator in CI for full schema enforcement when available.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict, deque
from pathlib import Path
from typing import Any, Iterable

REQUIRED_TASK_FIELDS = {
    "schema_version",
    "task_id",
    "display_key",
    "project_id",
    "plan_version",
    "title",
    "objective",
    "rationale",
    "level",
    "dispatchable",
    "category",
    "hierarchy_path",
    "requirement_ids",
    "source_refs",
    "status",
    "priority",
    "risk",
    "size",
    "inputs",
    "expected_outputs",
    "in_scope",
    "out_of_scope",
    "hard_dependencies",
    "soft_dependencies",
    "acceptance_criteria",
    "verification_plan",
    "definition_of_ready",
    "definition_of_done",
    "capability_tags",
    "suggested_agent_role",
    "tools_required",
    "parallelization",
}

TASK_ID_RE = re.compile(r"^TSK-[A-Z0-9]{8,12}$")


def read_jsonl(path: Path) -> Iterable[tuple[int, dict[str, Any]]]:
    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw in enumerate(handle, start=1):
            if not raw.strip():
                continue
            try:
                value = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number}: invalid JSON: {exc}") from exc
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_number}: expected an object")
            yield line_number, value


def load_tasks(root: Path) -> tuple[dict[str, dict[str, Any]], list[str]]:
    errors: list[str] = []
    tasks: dict[str, dict[str, Any]] = {}
    task_dir = root / "tasks"
    shards = sorted(task_dir.glob("tasks-*.jsonl"))
    if not shards:
        return {}, [f"No task shards found under {task_dir}"]

    for shard in shards:
        try:
            records = list(read_jsonl(shard))
        except ValueError as exc:
            errors.append(str(exc))
            continue
        for line_number, task in records:
            missing = REQUIRED_TASK_FIELDS - task.keys()
            if missing:
                errors.append(f"{shard}:{line_number}: missing fields {sorted(missing)}")
            task_id = task.get("task_id")
            if not isinstance(task_id, str) or not task_id:
                errors.append(f"{shard}:{line_number}: invalid task_id")
                continue
            if not TASK_ID_RE.match(task_id):
                errors.append(f"{task_id}: task_id format invalid")
            if task_id in tasks:
                errors.append(f"Duplicate task_id {task_id}")
            tasks[task_id] = task
            if task.get("dispatchable"):
                if task.get("level") != "LEAF":
                    errors.append(f"{task_id}: dispatchable task must have level LEAF")
                if task.get("size") not in {"XS", "S", "M"}:
                    errors.append(f"{task_id}: dispatchable leaf has invalid size {task.get('size')}")
                criteria = task.get("acceptance_criteria") or []
                if not criteria:
                    errors.append(f"{task_id}: dispatchable leaf has no acceptance criteria")
                if not task.get("verification_plan"):
                    errors.append(f"{task_id}: dispatchable leaf has no verification plan")
                if not task.get("definition_of_ready"):
                    errors.append(f"{task_id}: missing definition_of_ready")
                if not task.get("definition_of_done"):
                    errors.append(f"{task_id}: missing definition_of_done")
                if not task.get("capability_tags"):
                    errors.append(f"{task_id}: missing capability_tags")
                if not task.get("suggested_agent_role"):
                    errors.append(f"{task_id}: missing suggested_agent_role")
                para = task.get("parallelization") or {}
                for key in ("parallelizable", "execution_wave", "conflict_keys", "integration_surface"):
                    if key not in para:
                        errors.append(f"{task_id}: parallelization missing {key}")
            else:
                if task.get("level") == "LEAF" and task.get("size") in {"L", "XL"}:
                    errors.append(f"{task_id}: non-dispatchable oversize leaf should be split")
    return tasks, errors


def validate_dependencies(tasks: dict[str, dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    adjacency: dict[str, list[str]] = defaultdict(list)
    indegree = {task_id: 0 for task_id in tasks}

    for task_id, task in tasks.items():
        for dependency in task.get("hard_dependencies", []):
            if dependency == task_id:
                errors.append(f"{task_id}: self-dependency")
                continue
            if dependency not in tasks:
                errors.append(f"{task_id}: missing dependency {dependency}")
                continue
            adjacency[dependency].append(task_id)
            indegree[task_id] += 1

    queue = deque(task_id for task_id, degree in indegree.items() if degree == 0)
    visited = 0
    while queue:
        current = queue.popleft()
        visited += 1
        for downstream in adjacency[current]:
            indegree[downstream] -= 1
            if indegree[downstream] == 0:
                queue.append(downstream)

    if visited != len(tasks):
        cyclic = sorted(task_id for task_id, degree in indegree.items() if degree > 0)
        errors.append(f"Hard dependency graph contains a cycle involving: {cyclic[:50]}")
    return errors


def validate_traceability(tasks: dict[str, dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    for task_id, task in tasks.items():
        if not task.get("requirement_ids"):
            errors.append(f"{task_id}: no requirement_ids")
        if not task.get("source_refs"):
            errors.append(f"{task_id}: no source_refs")
        if task.get("dispatchable") and not task.get("expected_outputs"):
            errors.append(f"{task_id}: no expected_outputs")
    return errors


def validate_manifest(root: Path, tasks: dict[str, dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    man_path = root / "manifest.json"
    if not man_path.exists():
        errors.append("manifest.json missing")
        return errors
    try:
        man = json.loads(man_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"manifest.json invalid JSON: {exc}"]
    for key in ("schema_version", "project_id", "project_slug", "plan_version", "mode", "task_shards", "counts", "readiness", "audits"):
        if key not in man:
            errors.append(f"manifest missing {key}")
    if man.get("mode") not in {"PRD_ONLY", "PRD_PLUS_REPO", "CORPUS_UPDATE", None}:
        errors.append(f"manifest mode invalid: {man.get('mode')}")
    if man.get("readiness") not in {"READY", "CONDITIONALLY_READY", "NOT_READY", None}:
        errors.append(f"manifest readiness invalid: {man.get('readiness')}")
    count = (man.get("counts") or {}).get("tasks_total")
    if isinstance(count, int) and count != len(tasks):
        errors.append(f"manifest counts.tasks_total={count} != loaded {len(tasks)}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("corpus_root", type=Path)
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--write-report", action="store_true")
    args = parser.parse_args()

    root = args.corpus_root.resolve()
    tasks, errors = load_tasks(root)
    errors.extend(validate_dependencies(tasks))
    errors.extend(validate_traceability(tasks))
    errors.extend(validate_manifest(root, tasks))

    result = {
        "audit_type": "SCHEMA",
        "status": "PASS" if not errors else "FAIL",
        "task_count": len(tasks),
        "error_count": len(errors),
        "errors": errors,
        "findings": [{"severity": "ERROR", "code": "STRUCT", "message": e, "task_ids": []} for e in errors],
        "metrics": {"tasks": len(tasks)},
    }
    if args.write_report:
        out = root / "audits" / "schema-report.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    if args.as_json:
        print(json.dumps(result, indent=2))
    else:
        print(f"Status: {result['status']}")
        print(f"Tasks: {len(tasks)}")
        for error in errors:
            print(f"ERROR: {error}")
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
