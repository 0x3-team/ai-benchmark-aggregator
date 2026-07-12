#!/usr/bin/env python3
"""Detect hard-dependency cycles in a task corpus."""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path


def load_tasks(root: Path) -> dict[str, list[str]]:
    edges: dict[str, list[str]] = defaultdict(list)
    for shard in sorted((root / "tasks").glob("tasks-*.jsonl")):
        for raw in shard.read_text(encoding="utf-8").splitlines():
            if not raw.strip():
                continue
            t = json.loads(raw)
            tid = t["task_id"]
            edges.setdefault(tid, [])
            for dep in t.get("hard_dependencies") or []:
                # edge dep -> tid means dep must complete first
                edges[dep].append(tid)
                edges.setdefault(dep, edges.get(dep, []))
    return edges


def find_cycles(adj: dict[str, list[str]]) -> list[list[str]]:
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {n: WHITE for n in adj}
    stack: list[str] = []
    cycles: list[list[str]] = []

    def dfs(u: str) -> None:
        color[u] = GRAY
        stack.append(u)
        for v in adj.get(u, []):
            if v not in color:
                color[v] = WHITE
            if color[v] == WHITE:
                dfs(v)
            elif color[v] == GRAY:
                if v in stack:
                    i = stack.index(v)
                    cycles.append(stack[i:] + [v])
        stack.pop()
        color[u] = BLACK

    for n in list(adj):
        if color[n] == WHITE:
            dfs(n)
    return cycles


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("corpus_root", type=Path)
    args = ap.parse_args()
    adj = load_tasks(args.corpus_root.resolve())
    cycles = find_cycles(adj)
    if not cycles:
        print("No cycles")
        return 0
    print(f"Found {len(cycles)} cycle(s)")
    for c in cycles[:20]:
        print(" -> ".join(c))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
