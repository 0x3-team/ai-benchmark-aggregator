#!/usr/bin/env python3
"""Duplicate / near-duplicate task detection."""
from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def load_tasks(root: Path) -> list[dict[str, Any]]:
    tasks = []
    for shard in sorted((root / "tasks").glob("tasks-*.jsonl")):
        for raw in shard.read_text(encoding="utf-8").splitlines():
            if raw.strip():
                tasks.append(json.loads(raw))
    return tasks


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("corpus_root", type=Path)
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    root = args.corpus_root.resolve()
    tasks = load_tasks(root)
    by_obj: dict[str, list[str]] = defaultdict(list)
    by_title: dict[str, list[str]] = defaultdict(list)
    for t in tasks:
        by_obj[norm(t.get("objective", ""))].append(t["task_id"])
        by_title[norm(t.get("title", ""))].append(t["task_id"])
    findings = []
    for key, ids in by_obj.items():
        if key and len(ids) > 1:
            findings.append({"severity": "WARN", "code": "DUP_OBJECTIVE", "message": f"duplicate objective: {key[:80]}", "task_ids": ids})
    for key, ids in by_title.items():
        if key and len(ids) > 1:
            findings.append({"severity": "WARN", "code": "DUP_TITLE", "message": f"duplicate title: {key[:80]}", "task_ids": ids})
    status = "PASS" if not findings else "WARN"
    report = {
        "audit_type": "DUPLICATION",
        "status": status,
        "generated_at": "",
        "findings": findings,
        "metrics": {"tasks": len(tasks), "dup_groups": len(findings)},
    }
    text = json.dumps(report, indent=2) + "\n"
    if args.write:
        out = root / "audits" / "duplication-report.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        print(f"wrote {out} status={status}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
