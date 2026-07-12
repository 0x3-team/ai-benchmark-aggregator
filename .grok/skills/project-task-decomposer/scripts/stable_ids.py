#!/usr/bin/env python3
"""Deterministic stable ID helpers for requirements and tasks."""
from __future__ import annotations

import hashlib
import re


def _slug(text: str, max_len: int = 48) -> str:
    text = re.sub(r"[^A-Za-z0-9]+", "-", text.strip().upper()).strip("-")
    return text[:max_len] or "X"


def digest(parts: list[str], length: int = 10) -> str:
    h = hashlib.sha256("||".join(parts).encode("utf-8")).hexdigest().upper()
    return h[:length]


def task_id(*, project_id: str, objective: str, requirement_ids: list[str], expected_outputs: list[str]) -> str:
    """Semantic identity: project + objective + sorted reqs + sorted outputs."""
    parts = [
        project_id.strip(),
        re.sub(r"\s+", " ", objective.strip().lower()),
        ",".join(sorted(r.strip() for r in requirement_ids)),
        ",".join(sorted(o.strip().lower() for o in expected_outputs)),
    ]
    return f"TSK-{digest(parts, 10)}"


def requirement_id(*, project_id: str, statement: str, source_refs: list[str]) -> str:
    d = digest([project_id, statement.strip().lower(), ",".join(sorted(source_refs))], 8)
    return f"REQ-{d}"


def display_key(workstream: str, feature: str, seq: int) -> str:
    return f"{_slug(workstream, 12)}-{_slug(feature, 16)}-{seq:03d}"


def component_id(name: str) -> str:
    return f"CMP-{_slug(name, 24)}"
