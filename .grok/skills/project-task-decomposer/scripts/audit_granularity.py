#!/usr/bin/env python3
"""Granularity audit for dispatchable leaves."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def load_tasks(root: Path) -> list[dict[str, Any]]:
    tasks = []
    for shard in sorted((root / "tasks").glob("tasks-*.jsonl")):
        for raw in shard.read_text(encoding="utf-8").splitlines():
            if raw.strip():
                tasks.append(json.loads(raw))
    return tasks


VAGUE = ("handle", "support", "complete", "implement all", "build the", "add all", "do the")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("corpus_root", type=Path)
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    root = args.corpus_root.resolve()
    tasks = load_tasks(root)
    findings = []
    for t in tasks:
        tid = t.get("task_id", "?")
        if t.get("dispatchable"):
            if t.get("level") != "LEAF":
                findings.append({"severity": "ERROR", "code": "NON_LEAF_DISPATCH", "message": f"{tid} dispatchable but not LEAF", "task_ids": [tid]})
            if t.get("size") in {"L", "XL"}:
                findings.append({"severity": "ERROR", "code": "OVERSIZE_LEAF", "message": f"{tid} size {t.get('size')}", "task_ids": [tid]})
            ac = t.get("acceptance_criteria") or []
            if len(ac) > 7:
                findings.append({"severity": "WARN", "code": "MANY_AC", "message": f"{tid} has {len(ac)} acceptance criteria", "task_ids": [tid]})
            if not ac:
                findings.append({"severity": "ERROR", "code": "NO_AC", "message": f"{tid} missing acceptance criteria", "task_ids": [tid]})
            if not t.get("verification_plan"):
                findings.append({"severity": "ERROR", "code": "NO_VERIFY_PLAN", "message": f"{tid} missing verification_plan", "task_ids": [tid]})
            title = (t.get("title") or "").lower()
            obj = (t.get("objective") or "").lower()
            if any(v in title or v in obj for v in VAGUE) and t.get("size") in {"L", "XL", "M"} and len(ac) < 2:
                findings.append({"severity": "WARN", "code": "VAGUE", "message": f"{tid} may be underspecified", "task_ids": [tid]})
        else:
            if t.get("level") == "LEAF" and t.get("size") in {"L", "XL"}:
                findings.append({"severity": "WARN", "code": "NONDISPATCH_OVERSIZE", "message": f"{tid} leaf still oversized", "task_ids": [tid]})

    status = "PASS"
    if any(f["severity"] == "ERROR" for f in findings):
        status = "FAIL"
    elif findings:
        status = "WARN"
    report = {
        "audit_type": "GRANULARITY",
        "status": status,
        "generated_at": "",
        "findings": findings,
        "metrics": {"tasks": len(tasks), "dispatchable": sum(1 for t in tasks if t.get("dispatchable"))},
    }
    text = json.dumps(report, indent=2) + "\n"
    if args.write:
        out = root / "audits" / "granularity-report.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        print(f"wrote {out} status={status}")
    else:
        print(text)
    return 0 if status != "FAIL" else 1


if __name__ == "__main__":
    raise SystemExit(main())
