#!/usr/bin/env python3
"""Compute execution waves from hard dependencies and write graph/execution-waves.json."""
from __future__ import annotations

import argparse
import json
from collections import defaultdict, deque
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


def waves(tasks: dict[str, dict[str, Any]]) -> tuple[dict[str, int], list[str]]:
    errors: list[str] = []
    indeg = {tid: 0 for tid in tasks}
    adj: dict[str, list[str]] = defaultdict(list)
    for tid, t in tasks.items():
        for dep in t.get("hard_dependencies") or []:
            if dep not in tasks:
                errors.append(f"{tid}: missing dep {dep}")
                continue
            if dep == tid:
                errors.append(f"{tid}: self-dep")
                continue
            adj[dep].append(tid)
            indeg[tid] += 1
    q = deque([tid for tid, d in indeg.items() if d == 0])
    wave: dict[str, int] = {tid: 0 for tid in q}
    seen = 0
    while q:
        cur = q.popleft()
        seen += 1
        for nxt in adj[cur]:
            wave[nxt] = max(wave.get(nxt, 0), wave[cur] + 1)
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                q.append(nxt)
    if seen != len(tasks):
        errors.append("cycle detected; waves incomplete")
    return wave, errors


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("corpus_root", type=Path)
    ap.add_argument("--write", action="store_true", help="write graph/execution-waves.json")
    args = ap.parse_args()
    root = args.corpus_root.resolve()
    tasks = load_tasks(root)
    w, errors = waves(tasks)
    by_wave: dict[str, list[str]] = defaultdict(list)
    for tid, n in sorted(w.items(), key=lambda x: (x[1], x[0])):
        by_wave[str(n)].append(tid)
    payload = {
        "task_count": len(tasks),
        "wave_count": (max(w.values()) + 1) if w else 0,
        "waves": {k: v for k, v in sorted(by_wave.items(), key=lambda x: int(x[0]))},
        "errors": errors,
    }
    if args.write:
        out = root / "graph" / "execution-waves.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {out}")
    else:
        print(json.dumps(payload, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
