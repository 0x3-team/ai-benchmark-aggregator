#!/usr/bin/env python3
"""Diff two plan versions and emit changes/corpus-diff.json structure."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def load_tasks(root: Path) -> dict[str, dict[str, Any]]:
    tasks: dict[str, dict[str, Any]] = {}
    for shard in sorted((root / "tasks").glob("tasks-*.jsonl")):
        for raw in shard.read_text(encoding="utf-8").splitlines():
            if not raw.strip():
                continue
            t = json.loads(raw)
            tasks[t["task_id"]] = t
    return tasks


SEMANTIC_FIELDS = (
    "objective",
    "expected_outputs",
    "requirement_ids",
    "in_scope",
    "out_of_scope",
    "acceptance_criteria",
    "hard_dependencies",
    "status",
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("old_corpus", type=Path)
    ap.add_argument("new_corpus", type=Path)
    ap.add_argument("--write", type=Path, default=None)
    args = ap.parse_args()
    old = load_tasks(args.old_corpus.resolve())
    new = load_tasks(args.new_corpus.resolve())
    old_ids, new_ids = set(old), set(new)
    added = sorted(new_ids - old_ids)
    retired = sorted(old_ids - new_ids)
    unchanged = []
    changed = []
    for tid in sorted(old_ids & new_ids):
        fields = []
        for f in SEMANTIC_FIELDS:
            if json.dumps(old[tid].get(f), sort_keys=True) != json.dumps(new[tid].get(f), sort_keys=True):
                fields.append(f)
        if fields:
            changed.append({"task_id": tid, "fields_changed": fields})
        else:
            unchanged.append(tid)
    # split/merge heuristics via supersedes/replaced_by
    split, merged = [], []
    for tid, t in new.items():
        if t.get("supersedes") and len(t.get("supersedes") or []) > 1:
            merged.append({"from_task_ids": t["supersedes"], "to_task_id": tid})
        elif t.get("supersedes") and len(t.get("supersedes") or []) == 1:
            # may be rename/change; ignore as split
            pass
    for tid, t in old.items():
        rb = t.get("replaced_by") or t.get("superseded_by") or []
        if len(rb) > 1:
            split.append({"from_task_id": tid, "to_task_ids": rb})

    old_manifest = {}
    new_manifest = {}
    om = args.old_corpus / "manifest.json"
    nm = args.new_corpus / "manifest.json"
    if om.exists():
        old_manifest = json.loads(om.read_text())
    if nm.exists():
        new_manifest = json.loads(nm.read_text())

    payload = {
        "schema_version": "1.0.0",
        "from_plan_version": old_manifest.get("plan_version", "unknown"),
        "to_plan_version": new_manifest.get("plan_version", "unknown"),
        "added": added,
        "changed": changed,
        "unchanged": unchanged,
        "split": split,
        "merged": merged,
        "retired": [{"task_id": t, "replaced_by": (old[t].get("replaced_by") or [])} for t in retired],
        "invalidated_waves": [],
        "notes": [],
    }
    text = json.dumps(payload, indent=2) + "\n"
    if args.write:
        args.write.parent.mkdir(parents=True, exist_ok=True)
        args.write.write_text(text, encoding="utf-8")
        print(f"wrote {args.write}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
