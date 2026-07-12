#!/usr/bin/env python3
"""Requirement coverage audit."""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        if raw.strip():
            out.append(json.loads(raw))
    return out


def load_tasks(root: Path) -> list[dict[str, Any]]:
    tasks = []
    for shard in sorted((root / "tasks").glob("tasks-*.jsonl")):
        tasks.extend(load_jsonl(shard))
    return tasks


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("corpus_root", type=Path)
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    root = args.corpus_root.resolve()
    reqs = load_jsonl(root / "requirements" / "requirements.jsonl")
    tasks = load_tasks(root)
    by_req: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for t in tasks:
        for rid in t.get("requirement_ids") or []:
            by_req[rid].append(t)

    findings = []
    covered = partial = uncovered = 0
    for r in reqs:
        rid = r["requirement_id"]
        related = by_req.get(rid, [])
        delivery = [t for t in related if t.get("category") in {"IMPLEMENTATION", "CONTRACT", "MIGRATION", "SECURITY", "RELEASE", "CLEANUP", "DOCUMENTATION", "OBSERVABILITY"} or t.get("dispatchable")]
        verify = [t for t in related if t.get("category") == "VERIFICATION" or any(
            (ac.get("verification_type") if isinstance(ac, dict) else None) for ac in (t.get("acceptance_criteria") or [])
        )]
        # simpler: verification category OR any LEAF with verification_plan
        verify = [t for t in related if t.get("category") == "VERIFICATION"] or [
            t for t in related if t.get("dispatchable") and t.get("verification_plan")
        ]
        delivery = [t for t in related if t.get("dispatchable") or t.get("category") in {"IMPLEMENTATION", "CONTRACT", "MIGRATION", "SECURITY"}]
        if not related:
            uncovered += 1
            findings.append({"severity": "ERROR", "code": "NO_TASKS", "message": f"{rid} has no tasks", "task_ids": []})
        elif not delivery:
            partial += 1
            findings.append({"severity": "ERROR", "code": "NO_DELIVERY", "message": f"{rid} missing delivery task", "task_ids": [t["task_id"] for t in related]})
        elif not verify:
            partial += 1
            findings.append({"severity": "WARN", "code": "NO_VERIFY", "message": f"{rid} missing dedicated verification task", "task_ids": [t["task_id"] for t in related]})
        else:
            covered += 1

    # tasks without requirements
    for t in tasks:
        if not t.get("requirement_ids"):
            findings.append({"severity": "ERROR", "code": "TASK_NO_REQ", "message": f"{t.get('task_id')} has no requirement_ids", "task_ids": [t.get("task_id")]})

    status = "PASS"
    if any(f["severity"] == "ERROR" for f in findings):
        status = "FAIL"
    elif any(f["severity"] == "WARN" for f in findings):
        status = "WARN"

    report = {
        "audit_type": "COVERAGE",
        "status": status,
        "generated_at": "",
        "findings": findings,
        "metrics": {
            "requirements": len(reqs),
            "covered": covered,
            "partial": partial,
            "uncovered": uncovered,
            "tasks": len(tasks),
        },
    }
    text = json.dumps(report, indent=2) + "\n"
    if args.write:
        out = root / "audits" / "coverage-report.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        print(f"wrote {out} status={status}")
    else:
        print(text)
    return 0 if status != "FAIL" else 1


if __name__ == "__main__":
    raise SystemExit(main())
