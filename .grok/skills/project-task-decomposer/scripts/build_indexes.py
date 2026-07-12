#!/usr/bin/env python3
"""Build deterministic lookup indexes from task JSONL shards."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("corpus_root", type=Path)
    args = parser.parse_args()
    root = args.corpus_root.resolve()

    tasks: list[dict[str, Any]] = []
    for shard in sorted((root / "tasks").glob("tasks-*.jsonl")):
        with shard.open("r", encoding="utf-8") as handle:
            for raw in handle:
                if raw.strip():
                    tasks.append(json.loads(raw))

    index_specs = {
        "by-requirement.json": lambda task: task.get("requirement_ids", []),
        "by-component.json": lambda task: task.get("component_ids", []),
        "by-capability.json": lambda task: task.get("capability_tags", []),
        "by-agent-role.json": lambda task: [task.get("suggested_agent_role")],
        "by-status.json": lambda task: [task.get("status")],
        "by-workstream.json": lambda task: [task.get("workstream_id")],
    }

    index_dir = root / "indexes"
    index_dir.mkdir(parents=True, exist_ok=True)
    for filename, key_fn in index_specs.items():
        index: dict[str, list[str]] = defaultdict(list)
        for task in tasks:
            for key in key_fn(task):
                if key:
                    index[str(key)].append(task["task_id"])
        normalized = {key: sorted(set(ids)) for key, ids in sorted(index.items())}
        (index_dir / filename).write_text(json.dumps(normalized, indent=2) + "\n", encoding="utf-8")

    print(f"Built {len(index_specs)} indexes for {len(tasks)} tasks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
