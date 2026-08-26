"""Bounded descriptor-relative JSON object reader (discovery fixtures).

Reads a small JSON object file relative to an already-opened parent directory
descriptor with hard resource caps enforced *before* and *during* read, so an
untrusted fixture can never cause unbounded memory or depth consumption in the
discovery lane.

Safety properties:

* The leaf is opened exactly once with ``os.open(..., O_RDONLY | O_NOFOLLOW |
  O_CLOEXEC, dir_fd=parent_fd)`` — no symlink follow, no path re-walk, and the
  descriptor is closed exactly once in a ``finally``.
* ``fstat`` size is checked above ``max_bytes`` *before* any read, and reads
  are made only via ``os.read`` with small positive fixed-size buffers so we
  never request or materialize more than ``max_bytes + 1`` bytes total even if
  the file grows after ``fstat``.
* JSON nesting depth is rejected by a string-aware scanner before ``json.loads``
  to avoid unbounded recursion in the decoder.
* Decoded nodes are counted iteratively and bounded against both the per-file
  cap and the shared :class:`FixtureBudget` aggregate caps.
"""

from __future__ import annotations

import json
import os
import stat
from typing import Optional

__all__ = [
    "FixtureBudget",
    "FixtureInputError",
    "read_json_object_at",
]


class FixtureInputError(ValueError):
    """Stable fail-closed error for bounded fixture reads.

    ``reason_code`` is a stable machine-readable string (e.g.
    ``FIXTURE_BYTES_EXCEEDED``); it never exposes raw OS/decoder/JSON details.
    """

    def __init__(self, reason_code: str, message: str = "") -> None:
        super().__init__(message or reason_code)
        self.reason_code = reason_code


def _fail(reason_code: str, message: str) -> FixtureInputError:
    return FixtureInputError(reason_code, message)


class FixtureBudget:
    """Mutable shared aggregate budget across multiple fixture reads.

    ``used_bytes`` / ``used_nodes`` start at zero and are consumed (never reset)
    across reads so callers can enforce a global budget for a discovery cycle.
    """

    __slots__ = ("max_bytes", "max_nodes", "used_bytes", "used_nodes")

    def __init__(self, max_bytes: int, max_nodes: int) -> None:
        if max_bytes <= 0:
            raise _fail(
                "FIXTURE_BUDGET_BYTES_EXCEEDED",
                "FixtureBudget max_bytes must be positive",
            )
        if max_nodes <= 0:
            raise _fail(
                "FIXTURE_BUDGET_NODES_EXCEEDED",
                "FixtureBudget max_nodes must be positive",
            )
        self.max_bytes = max_bytes
        self.max_nodes = max_nodes
        self.used_bytes = 0
        self.used_nodes = 0

    def _charge(self, nodes: int, size: int) -> None:
        # Atomic: validate proposed totals first, mutate only on success.
        proposed_nodes = self.used_nodes + nodes
        proposed_bytes = self.used_bytes + size
        if proposed_nodes > self.max_nodes:
            raise _fail(
                "FIXTURE_BUDGET_NODES_EXCEEDED",
                "shared node budget exhausted",
            )
        if proposed_bytes > self.max_bytes:
            raise _fail(
                "FIXTURE_BUDGET_BYTES_EXCEEDED",
                "shared byte budget exhausted",
            )
        self.used_nodes = proposed_nodes
        self.used_bytes = proposed_bytes


def _open_flags() -> int:
    """O_RDONLY | O_NOFOLLOW plus O_CLOEXEC when available."""
    flags = os.O_RDONLY | os.O_NOFOLLOW
    flags |= getattr(os, "O_CLOEXEC", 0)
    return flags


def _validate_leaf_name(leaf: str) -> None:
    """A fixture leaf must be a single safe path component, not dot/dotdot."""
    if not isinstance(leaf, str) or not leaf:
        raise _fail("FIXTURE_OPEN_FAILED", "leaf name must be a non-empty string")
    if "/" in leaf or "\\" in leaf or leaf in (".", ".."):
        raise _fail("FIXTURE_OPEN_FAILED", "leaf name must be a single component")


def _deepest_scan(raw: bytes) -> int:
    """Return the maximum JSON nesting depth with a string-aware scan.

    Counts both object braces ``{}`` and array brackets ``[]`` outside string
    literals, skipping over escaped quotes and backslashes so embedded
    ``{ } [ ]`` inside strings never count toward nesting.
    """
    depth = 0
    max_depth = 0
    in_string = False
    escaped = False
    for byte in raw:
        ch = chr(byte)
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch in "[{":
            depth += 1
            if depth > max_depth:
                max_depth = depth
        elif ch in "]}":
            if depth > 0:
                depth -= 1
    return max_depth


def _count_nodes(root: object, max_nodes: int) -> int:
    """Count decoded JSON nodes iteratively with an iterator stack.

    Every dict, list, and scalar counts as exactly one node; object keys are
    not nodes.  The stack holds *iterators* (dict value views / list iterators)
    rather than expanded child lists, so its memory stays proportional to the
    JSON depth, not the total node count.  Raises ``FIXTURE_NODES_EXCEEDED`` as
    soon as the count exceeds ``max_nodes``.
    """
    total = 0
    stack = [iter([root])]
    while stack:
        try:
            node = next(stack[-1])
        except StopIteration:
            stack.pop()
            continue
        total += 1
        if total > max_nodes:
            raise _fail(
                "FIXTURE_NODES_EXCEEDED",
                "fixture has too many nodes",
            )
        if isinstance(node, dict):
            stack.append(iter(node.values()))
        elif isinstance(node, list):
            stack.append(iter(node))
    return total


def read_json_object_at(
    parent_fd: int,
    leaf: str,
    *,
    max_bytes: int,
    max_depth: int,
    max_nodes: int,
    budget: Optional[FixtureBudget] = None,
) -> dict:
    """Read and parse one JSON object from ``leaf`` relative to ``parent_fd``.

    Raises :class:`FixtureInputError` with a stable ``reason_code`` on any
    input failure; the descriptor is always closed exactly once, even on failure.
    """
    if max_bytes <= 0:
        raise _fail("FIXTURE_BYTES_EXCEEDED", "max_bytes must be positive")
    if max_depth <= 0:
        raise _fail("FIXTURE_DEPTH_EXCEEDED", "max_depth must be positive")
    if max_nodes <= 0:
        raise _fail("FIXTURE_NODES_EXCEEDED", "max_nodes must be positive")
    _validate_leaf_name(leaf)

    shared = budget if budget is not None else FixtureBudget(max_bytes, max_nodes)

    descriptor = None
    try:
        try:
            descriptor = os.open(
                leaf, _open_flags(), dir_fd=parent_fd
            )
        except OSError:
            raise _fail("FIXTURE_OPEN_FAILED", "cannot open fixture leaf") from None

        try:
            metadata = os.fstat(descriptor)
        except OSError:
            raise _fail("FIXTURE_READ_FAILED", "cannot fstat fixture leaf") from None
        if not stat.S_ISREG(metadata.st_mode):
            raise _fail("FIXTURE_NOT_REGULAR", "fixture leaf is not a regular file")
        if metadata.st_size > max_bytes:
            raise _fail(
                "FIXTURE_BYTES_EXCEEDED",
                "fixture file is larger than the byte cap",
            )

        raw_parts = []
        total_read = 0
        # Read in small positive fixed-size chunks, bounded to max_bytes + 1 total.
        chunk_size = 4096
        while True:
            remaining = (max_bytes + 1) - total_read
            if remaining <= 0:
                break
            request = min(chunk_size, remaining)  # always in [1, chunk_size]
            try:
                chunk = os.read(descriptor, request)
            except OSError:
                raise _fail("FIXTURE_READ_FAILED", "failed reading fixture leaf") from None
            if not chunk:
                break
            total_read += len(chunk)
            raw_parts.append(chunk)
            if total_read > max_bytes:
                raise _fail(
                    "FIXTURE_BYTES_EXCEEDED",
                    "fixture file grew past the byte cap during read",
                )
            if len(chunk) < request:
                break
        raw = b"".join(raw_parts)

        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            raise _fail("FIXTURE_UTF8_INVALID", "fixture is not valid UTF-8") from None

        if _deepest_scan(raw) > max_depth:
            raise _fail("FIXTURE_DEPTH_EXCEEDED", "fixture nesting exceeds the depth cap")

        try:
            payload = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            raise _fail("FIXTURE_JSON_INVALID", "fixture is not valid JSON") from None

        if type(payload) is not dict:
            raise _fail("FIXTURE_ROOT_NOT_OBJECT", "fixture root must be a JSON object")

        node_count = _count_nodes(payload, max_nodes)
        shared._charge(node_count, total_read)
        return payload
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
