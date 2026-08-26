"""Resource-bound tests for app.discovery.fixture_io.

Pins the bounded descriptor-relative JSON object reader: per-file and shared
bytes/depth/node caps are enforced at the exact boundary, the descriptor is
opened exactly once with no-follow/O_CLOEXEC flags, closed exactly once, reads
are small positive fixed-size bounded requests, and depth is counted with a
string-aware scanner before json.loads.

Also pins the fixture-root limits surfaced through
:mod:`app.discovery.manifest.load_manifest` with tiny monkeypatched caps: the
mandatory exported constant values, per-file byte exact/+1, aggregate bytes
and nodes exact/+1 across every manifest JSON payload, the bounded
``targets/`` name scan (total-entry and JSON-file exact/+1, with a malformed
overflow JSON never decoded), deterministic target order, and an AST/source
guard that the loader never falls back to unbounded file reads.
"""

from __future__ import annotations

import ast
import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import func, select

import app.discovery.connectors.base as base_mod
import app.discovery.controller as controller_mod
import app.discovery.fixture_io as fixture_io_mod
import app.discovery.manifest as manifest_mod
from app.db import models
from app.db.engine import get_session
from app.discovery.candidates import assemble_candidate
from app.discovery.connectors.base import ConnectorObservation
from app.discovery.connectors.base import StaticFixtureConnector
from app.discovery.connectors.base import (
    MAX_STATIC_CANDIDATES_PER_TARGET,
    MAX_STATIC_CANDIDATE_SPECS,
    MAX_STATIC_FIXTURE_BYTES,
    MAX_STATIC_JSON_DEPTH,
    MAX_STATIC_JSON_NODES,
    MAX_STATIC_TARGET_ENTRIES,
)
from app.discovery.connectors.base import ConnectorError
from app.discovery.controller import DiscoveryControllerError, run_discovery_cycle
from app.discovery.fixture_io import FixtureBudget, FixtureInputError, read_json_object_at
from app.discovery.manifest import (
    load_manifest,
    MAX_FIXTURE_JSON_BYTES,
    MAX_FIXTURE_JSON_DEPTH,
    MAX_FIXTURE_JSON_NODES,
    MAX_FIXTURE_MANIFEST_BYTES,
    MAX_FIXTURE_MANIFEST_NODES,
    MAX_TARGET_DIRECTORY_ENTRIES,
    MAX_TARGET_JSON_FILES,
)
from discovery_fixtures import build_candidate_spec, build_target, write_manifest_root
from app.scheduling.slots import slot_for_ordinal


@pytest.fixture
def parent_fd(tmp_path):
    fd = os.open(tmp_path, os.O_RDONLY)
    try:
        yield fd
    finally:
        os.close(fd)


def _write(tmp_path, leaf, payload):
    """Write a JSON object payload as UTF-8 text; return the raw bytes."""
    if isinstance(payload, str):
        raw = payload.encode("utf-8")
    else:
        raw = json.dumps(payload).encode("utf-8")
    (tmp_path / leaf).write_bytes(raw)
    return raw


# ---------------------------------------------------------------------------
# 1) Stable error + budget contract
# ---------------------------------------------------------------------------
def test_fixture_input_error_exposes_stable_reason_code():
    err = FixtureInputError("FIXTURE_DEPTH_EXCEEDED")
    assert isinstance(err, ValueError)
    assert err.reason_code == "FIXTURE_DEPTH_EXCEEDED"


def test_fixture_budget_zeroed_and_positive_validation():
    budget = FixtureBudget(max_bytes=100, max_nodes=10)
    assert budget.max_bytes == 100
    assert budget.max_nodes == 10
    assert budget.used_bytes == 0
    assert budget.used_nodes == 0

    with pytest.raises(FixtureInputError) as exc:
        FixtureBudget(max_bytes=0, max_nodes=10)
    assert exc.value.reason_code == "FIXTURE_BUDGET_BYTES_EXCEEDED"

    with pytest.raises(FixtureInputError) as exc:
        FixtureBudget(max_bytes=100, max_nodes=0)
    assert exc.value.reason_code == "FIXTURE_BUDGET_NODES_EXCEEDED"


# ---------------------------------------------------------------------------
# 2) per-file bytes: exact boundary and +1
# ---------------------------------------------------------------------------
def test_bytes_exact_boundary_reads_ok(tmp_path, parent_fd):
    raw = _write(tmp_path, "leaf.json", {"a": 1})
    result = read_json_object_at(
        parent_fd, "leaf.json", max_bytes=len(raw), max_depth=3, max_nodes=10
    )
    assert result == {"a": 1}


def test_bytes_plus_one_exceeds(tmp_path, parent_fd):
    raw = _write(tmp_path, "leaf.json", {"a": 1})
    with pytest.raises(FixtureInputError) as exc:
        read_json_object_at(
            parent_fd, "leaf.json", max_bytes=len(raw) - 1,
            max_depth=3, max_nodes=10,
        )
    assert exc.value.reason_code == "FIXTURE_BYTES_EXCEEDED"


def test_fstat_oversize_pre_rejects_before_read(tmp_path, parent_fd, monkeypatch):
    """A file whose fstat size already exceeds the cap is rejected with zero reads."""
    _write(tmp_path, "leaf.json", {"a": 1})
    import app.discovery.fixture_io as fixture_io

    real_read = os.read
    calls = {"n": 0}

    def fake_read(fd, size):
        calls["n"] += 1
        return real_read(fd, size)

    monkeypatch.setattr(fixture_io.os, "read", fake_read)
    with pytest.raises(FixtureInputError) as exc:
        read_json_object_at(
            parent_fd, "leaf.json", max_bytes=2,  # well under the file size
            max_depth=3, max_nodes=10,
        )
    assert exc.value.reason_code == "FIXTURE_BYTES_EXCEEDED"
    assert calls["n"] == 0  # rejected at fstat, before any read


# ---------------------------------------------------------------------------
# 3) descriptor-relative open, flags, close-once
# ---------------------------------------------------------------------------
def test_open_is_descriptor_relative_no_follow_cloexec(tmp_path, parent_fd, monkeypatch):
    _write(tmp_path, "leaf.json", {"a": 1})
    captured = {}
    close_calls = []
    real_open = os.open
    real_close = os.close

    def fake_open(path, flags, **kwargs):
        fd = real_open(path, flags, **kwargs)
        captured.update(path=path, flag=flags, fd=fd, kwargs=kwargs)
        return fd

    def fake_close(fd):
        close_calls.append(fd)
        return real_close(fd)

    monkeypatch.setattr(os, "open", fake_open)
    monkeypatch.setattr(os, "close", fake_close)

    result = read_json_object_at(
        parent_fd, "leaf.json", max_bytes=100, max_depth=3, max_nodes=10
    )

    assert result == {"a": 1}
    assert captured["path"] == "leaf.json"
    assert captured["kwargs"] == {"dir_fd": parent_fd}
    assert captured["flag"] & os.O_ACCMODE == os.O_RDONLY
    assert captured["flag"] & os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        assert captured["flag"] & os.O_CLOEXEC
    assert close_calls == [captured["fd"]]  # closed exactly once


def test_close_once_on_failure(tmp_path, parent_fd, monkeypatch):
    _write(tmp_path, "leaf.json", {"a": 1})
    close_calls = []
    real_close = os.close

    def fake_close(fd):
        close_calls.append(fd)
        return real_close(fd)

    monkeypatch.setattr(os, "close", fake_close)
    with pytest.raises(FixtureInputError) as exc:
        read_json_object_at(
            parent_fd, "leaf.json", max_bytes=1, max_depth=3, max_nodes=10
        )
    assert exc.value.reason_code == "FIXTURE_BYTES_EXCEEDED"
    assert len(close_calls) == 1


def test_non_regular_rejected(tmp_path, parent_fd):
    (tmp_path / "subdir").mkdir()
    with pytest.raises(FixtureInputError) as exc:
        read_json_object_at(
            parent_fd, "subdir", max_bytes=8192, max_depth=3, max_nodes=10
        )
    assert exc.value.reason_code == "FIXTURE_NOT_REGULAR"


def test_leaf_bad_names(tmp_path, parent_fd):
    for bad in ("../escape.json", "a/b.json", "..", ".", ""):
        with pytest.raises(FixtureInputError) as exc:
            read_json_object_at(
                parent_fd, bad, max_bytes=8192, max_depth=3, max_nodes=10
            )
        assert exc.value.reason_code == "FIXTURE_OPEN_FAILED"


def test_invalid_caps(tmp_path, parent_fd):
    base = dict(max_bytes=100, max_depth=3, max_nodes=10)
    cases = (
        ({**base, "max_bytes": 0}, "FIXTURE_BYTES_EXCEEDED"),
        ({**base, "max_depth": 0}, "FIXTURE_DEPTH_EXCEEDED"),
        ({**base, "max_nodes": 0}, "FIXTURE_NODES_EXCEEDED"),
    )
    for kwargs, code in cases:
        with pytest.raises(FixtureInputError) as exc:
            read_json_object_at(parent_fd, "leaf.json", **kwargs)
        assert exc.value.reason_code == code


# ---------------------------------------------------------------------------
# 4) reads are positive, fixed, and bounded
# ---------------------------------------------------------------------------
def test_read_requests_positive_and_bounded(tmp_path, parent_fd, monkeypatch):
    _write(tmp_path, "leaf.json", {"a": 1})
    requests = []
    real_read = os.read

    def fake_read(fd, size):
        requests.append(size)
        return real_read(fd, size)

    monkeypatch.setattr(os, "read", fake_read)
    result = read_json_object_at(
        parent_fd, "leaf.json", max_bytes=128, max_depth=3, max_nodes=10
    )

    assert result == {"a": 1}
    assert requests
    assert all(req > 0 for req in requests)
    assert sum(requests) <= 128 + 1


def test_growth_after_fstat_rejected(tmp_path, parent_fd, monkeypatch):
    """File fstats small but grows past cap during read -> rejected, close once."""
    _write(tmp_path, "leaf.json", {"a": 1})
    real_fstat = os.fstat
    real_close = os.close
    close_calls = []
    stat_calls = {"n": 0}

    def fake_fstat(fd):
        meta = real_fstat(fd)
        if stat_calls["n"] == 0:  # pretend tiny at first fstat
            stat_calls["n"] += 1
            return SimpleNamespace(st_mode=meta.st_mode, st_size=1)
        return meta

    def fake_close(fd):
        close_calls.append(fd)
        return real_close(fd)

    monkeypatch.setattr(os, "fstat", fake_fstat)
    monkeypatch.setattr(os, "close", fake_close)

    with pytest.raises(FixtureInputError) as exc:
        read_json_object_at(
            parent_fd, "leaf.json", max_bytes=2, max_depth=3, max_nodes=10
        )
    assert exc.value.reason_code == "FIXTURE_BYTES_EXCEEDED"
    assert len(close_calls) == 1


# ---------------------------------------------------------------------------
# 5) decode / depth / nodes
# ---------------------------------------------------------------------------
def test_invalid_utf8(tmp_path, parent_fd):
    (tmp_path / "leaf.json").write_bytes(b'{"a":"\xff\xfe"}')
    with pytest.raises(FixtureInputError) as exc:
        read_json_object_at(
            parent_fd, "leaf.json", max_bytes=1000, max_depth=3, max_nodes=10
        )
    assert exc.value.reason_code == "FIXTURE_UTF8_INVALID"


def test_invalid_json(tmp_path, parent_fd):
    _write(tmp_path, "leaf.json", '{"a": ')
    with pytest.raises(FixtureInputError) as exc:
        read_json_object_at(
            parent_fd, "leaf.json", max_bytes=1000, max_depth=3, max_nodes=10
        )
    assert exc.value.reason_code == "FIXTURE_JSON_INVALID"


def test_non_object_root(tmp_path, parent_fd):
    _write(tmp_path, "leaf.json", "[1,2,3]")
    with pytest.raises(FixtureInputError) as exc:
        read_json_object_at(
            parent_fd, "leaf.json", max_bytes=1000, max_depth=3, max_nodes=10
        )
    assert exc.value.reason_code == "FIXTURE_ROOT_NOT_OBJECT"


def test_depth_exact_and_plus_one(tmp_path, parent_fd):
    # exact boundary: max_depth == actual depth parses OK
    _write(tmp_path, "ok.json", '{"a":{"b":[1]}}')  # depth 3
    result = read_json_object_at(
        parent_fd, "ok.json", max_bytes=1000, max_depth=3, max_nodes=10
    )
    assert result == {"a": {"b": [1]}}

    # +1 rejected
    _write(tmp_path, "deep.json", '{"a":{"b":[1]}}')
    with pytest.raises(FixtureInputError) as exc:
        read_json_object_at(
            parent_fd, "deep.json", max_bytes=1000, max_depth=2, max_nodes=10
        )
    assert exc.value.reason_code == "FIXTURE_DEPTH_EXCEEDED"


def test_depth_scanner_string_aware(tmp_path, parent_fd):
    """Braces/brackets/escapes inside string literals never count toward depth.

    The payload has real nesting depth 1, but the string values contain naked
    braces, brackets, an escaped quote, and a backslash. A naive scanner that
    counts in-string brackets would report depth > 1; ours must not, so
    ``max_depth=1`` accepts it and it parses fine.
    """
    payload = {"a": "{[({}])}", "b": "esc\\aped \"quote\""}
    _write(tmp_path, "leaf.json", payload)
    result = read_json_object_at(
        parent_fd, "leaf.json", max_bytes=10000, max_depth=1, max_nodes=10
    )
    assert result == payload


def test_depth_reject_happens_before_json_loads(tmp_path, parent_fd, monkeypatch):
    """Depth +1 is rejected by the scanner before fixture_io invokes json.loads."""
    _write(tmp_path, "leaf.json", '{"a":{"b":[1]}}')  # depth 3
    real_loads = json.loads
    calls = {"n": 0}

    def fake_loads(*args, **kwargs):
        calls["n"] += 1
        return real_loads(*args, **kwargs)

    monkeypatch.setattr("app.discovery.fixture_io.json.loads", fake_loads)
    with pytest.raises(FixtureInputError) as exc:
        read_json_object_at(
            parent_fd, "leaf.json", max_bytes=10000, max_depth=2, max_nodes=10
        )
    assert exc.value.reason_code == "FIXTURE_DEPTH_EXCEEDED"
    assert calls["n"] == 0


def test_nodes_exact_and_plus_one(tmp_path, parent_fd):
    payload = {"a": [1, 2, {"b": "x"}]}
    _write(tmp_path, "leaf.json", payload)
    # root dict 1 + list 1 + scalars 1 and 2 + inner dict 1 + scalar x 1 = 6
    actual_nodes = 6

    result = read_json_object_at(
        parent_fd, "leaf.json", max_bytes=10000, max_depth=5,
        max_nodes=actual_nodes,
    )
    assert result == payload

    with pytest.raises(FixtureInputError) as exc:
        read_json_object_at(
            parent_fd, "leaf.json", max_bytes=10000, max_depth=5,
            max_nodes=actual_nodes - 1,
        )
    assert exc.value.reason_code == "FIXTURE_NODES_EXCEEDED"


# ---------------------------------------------------------------------------
# 6) shared budget: bytes and nodes exact and +1, atomic on rejection
# ---------------------------------------------------------------------------
def test_shared_byte_budget_exact_and_plus_one(tmp_path, parent_fd):
    raw = _write(tmp_path, "leaf.json", {"a": 1})
    size = len(raw)

    # exact: budget bytes == file size
    budget = FixtureBudget(max_bytes=size, max_nodes=100)
    result = read_json_object_at(
        parent_fd, "leaf.json", max_bytes=10000, max_depth=3,
        max_nodes=100, budget=budget,
    )
    assert result == {"a": 1}
    assert budget.used_bytes == size
    assert budget.used_nodes == 2  # object root + scalar; key is not a node

    # +1 -> rejected and budget must not be consumed
    budget2 = FixtureBudget(max_bytes=size - 1, max_nodes=100)
    with pytest.raises(FixtureInputError) as exc:
        read_json_object_at(
            parent_fd, "leaf.json", max_bytes=10000, max_depth=3,
            max_nodes=100, budget=budget2,
        )
    assert exc.value.reason_code == "FIXTURE_BUDGET_BYTES_EXCEEDED"
    assert budget2.used_bytes == 0
    assert budget2.used_nodes == 0


def test_shared_node_budget_exact_and_plus_one(tmp_path, parent_fd):
    _write(tmp_path, "leaf.json", {"a": 1})

    budget = FixtureBudget(max_bytes=10000, max_nodes=2)
    result = read_json_object_at(
        parent_fd, "leaf.json", max_bytes=10000, max_depth=3,
        max_nodes=100, budget=budget,
    )
    assert result == {"a": 1}
    assert budget.used_nodes == 2

    budget2 = FixtureBudget(max_bytes=10000, max_nodes=1)
    with pytest.raises(FixtureInputError) as exc:
        read_json_object_at(
            parent_fd, "leaf.json", max_bytes=10000, max_depth=3,
            max_nodes=100, budget=budget2,
        )
    assert exc.value.reason_code == "FIXTURE_BUDGET_NODES_EXCEEDED"
    assert budget2.used_bytes == 0
    assert budget2.used_nodes == 0


def test_shared_budget_accumulates_across_reads(tmp_path, parent_fd):
    """Two exact-boundary reads share one budget; the second keeps accumulating."""
    raw_a = _write(tmp_path, "a.json", {"x": 1})
    raw_b = _write(tmp_path, "b.json", {"y": 2})
    size = len(raw_a) + len(raw_b)

    budget = FixtureBudget(max_bytes=size, max_nodes=100)
    read_json_object_at(
        parent_fd, "a.json", max_bytes=10000, max_depth=3, max_nodes=100,
        budget=budget,
    )
    read_json_object_at(
        parent_fd, "b.json", max_bytes=10000, max_depth=3, max_nodes=100,
        budget=budget,
    )
    assert budget.used_bytes == size
    assert budget.used_nodes == 4  # two objects, each 2 nodes


# ===========================================================================
# Public load_manifest fixture-resource bounds
# ===========================================================================


def test_mandatory_manifest_constant_values() -> None:
    assert MAX_FIXTURE_JSON_BYTES == 8 * 1024 * 1024
    assert MAX_FIXTURE_MANIFEST_BYTES == 32 * 1024 * 1024
    assert MAX_TARGET_DIRECTORY_ENTRIES == 512
    assert MAX_TARGET_JSON_FILES == 512
    assert MAX_FIXTURE_JSON_DEPTH == 64
    assert MAX_FIXTURE_JSON_NODES == 100_000
    assert MAX_FIXTURE_MANIFEST_NODES == 500_000


def _tiny_manifest_budget(monkeypatch) -> None:
    """Patch manifest caps so tests can drive exact/+1 boundaries with tiny data."""
    monkeypatch.setattr(manifest_mod, "MAX_FIXTURE_JSON_BYTES", 1_000_000)
    monkeypatch.setattr(manifest_mod, "MAX_FIXTURE_JSON_DEPTH", 64)
    monkeypatch.setattr(manifest_mod, "MAX_FIXTURE_JSON_NODES", 1_000_000)
    monkeypatch.setattr(manifest_mod, "MAX_FIXTURE_MANIFEST_BYTES", 100_000)
    monkeypatch.setattr(manifest_mod, "MAX_FIXTURE_MANIFEST_NODES", 100_000)
    monkeypatch.setattr(manifest_mod, "MAX_TARGET_DIRECTORY_ENTRIES", 512)
    monkeypatch.setattr(manifest_mod, "MAX_TARGET_JSON_FILES", 512)


def _agg_bytes(tmp_path: Path, root: str) -> int:
    total = 0
    for leaf in ("manifest.json", "coverage-universe.json"):
        total += (tmp_path / root / leaf).stat().st_size
    targets_dir = tmp_path / root / "targets"
    for leaf in targets_dir.iterdir():
        total += leaf.stat().st_size
    return total


def _iter_json_nodes(path: Path) -> int:
    """Iterative JSON node counter over one file; never recurses."""
    total = 0
    stack = [iter([json.loads(path.read_text(encoding="utf-8"))])]
    while stack:
        try:
            node = next(stack[-1])
        except StopIteration:
            stack.pop()
            continue
        total += 1
        if isinstance(node, dict):
            stack.append(iter(node.values()))
        elif isinstance(node, list):
            stack.append(iter(node))
    return total


def _manifest_node_total(root: Path) -> int:
    total = 0
    for leaf in ("manifest.json", "coverage-universe.json"):
        total += _iter_json_nodes(root / leaf)
    for target in (root / "targets").iterdir():
        total += _iter_json_nodes(target)
    return total


def test_per_file_byte_cap_exact_and_plus_one(tmp_path, monkeypatch) -> None:
    """MAX_FIXTURE_JSON_BYTES enforced against the largest payload file."""
    _tiny_manifest_budget(monkeypatch)
    root = write_manifest_root(tmp_path / "fx-perfile")

    paths = [
        root / "manifest.json",
        root / "coverage-universe.json",
    ]
    paths.extend((root / "targets").iterdir())
    largest = max(path.stat().st_size for path in paths)

    monkeypatch.setattr(manifest_mod, "MAX_FIXTURE_JSON_BYTES", largest)
    assert load_manifest(root).lane == "discovery"  # exact largest passes

    monkeypatch.setattr(manifest_mod, "MAX_FIXTURE_JSON_BYTES", largest - 1)
    with pytest.raises(manifest_mod.DiscoveryManifestError) as exc:
        load_manifest(root)
    # The largest payload now exceeds the per-file cap.
    assert "FIXTURE_BYTES_EXCEEDED" in str(exc.value)


def test_aggregate_bytes_exact_and_plus_one(tmp_path, monkeypatch) -> None:
    """Shared FixtureBudget bytes span manifest + universe + every target."""
    root = write_manifest_root(tmp_path / "fx-agg")
    total = _agg_bytes(tmp_path, "fx-agg")

    monkeypatch.setattr(manifest_mod, "MAX_FIXTURE_MANIFEST_BYTES", total)
    load_manifest(root)  # exact total passes

    monkeypatch.setattr(manifest_mod, "MAX_FIXTURE_MANIFEST_BYTES", total - 1)
    with pytest.raises(manifest_mod.DiscoveryManifestError) as exc:
        load_manifest(root)
    assert "FIXTURE_BUDGET_BYTES_EXCEEDED" in str(exc.value)


def test_aggregate_nodes_exact_and_plus_one(tmp_path, monkeypatch) -> None:
    """Shared FixtureBudget nodes span every manifest JSON payload."""
    _tiny_manifest_budget(monkeypatch)
    root = write_manifest_root(tmp_path / "fx-nodes")
    total_nodes = _manifest_node_total(root)

    monkeypatch.setattr(manifest_mod, "MAX_FIXTURE_MANIFEST_NODES", total_nodes)
    load_manifest(root)

    monkeypatch.setattr(manifest_mod, "MAX_FIXTURE_MANIFEST_NODES", total_nodes - 1)
    with pytest.raises(manifest_mod.DiscoveryManifestError) as exc:
        load_manifest(root)
    assert "FIXTURE_BUDGET_NODES_EXCEEDED" in str(exc.value)


def test_target_total_entries_exact_and_plus_one(tmp_path, monkeypatch) -> None:
    """Total targets/ entries (ignored non-JSON counts) bounded by cap."""
    _tiny_manifest_budget(monkeypatch)
    root = write_manifest_root(tmp_path / "fx-entries")
    # one valid JSON target plus one ignored non-JSON entry => 2 total entries
    (root / "targets" / "ignore.txt").write_text("ignored", encoding="utf-8")

    monkeypatch.setattr(manifest_mod, "MAX_TARGET_DIRECTORY_ENTRIES", 2)
    load_manifest(root)

    monkeypatch.setattr(manifest_mod, "MAX_TARGET_DIRECTORY_ENTRIES", 1)
    with pytest.raises(manifest_mod.DiscoveryManifestError, match="entries"):
        load_manifest(root)


def test_target_json_files_exact_and_plus_one_before_decode(tmp_path, monkeypatch) -> None:
    """JSON-file cap is enforced by the bounded name scan, before any decode.

    cap=1 with exactly one valid JSON target loads (exact). Adding a malformed
    overflow JSON as a second file keeps cap=1; rejection comes from the scan
    (``JSON payload files``), never from decoding the broken file.
    """
    _tiny_manifest_budget(monkeypatch)

    root = write_manifest_root(tmp_path / "fx-json", targets={
        "t-a": build_target("t-a"),
    })
    monkeypatch.setattr(manifest_mod, "MAX_TARGET_JSON_FILES", 1)
    assert len(load_manifest(root).targets) == 1  # exactly one JSON at cap=1

    # A second JSON file (malformed, overflow) now exceeds cap=1; the bounded
    # scan rejects it before any payload — including the broken overflow — is
    # decoded.
    (root / "targets" / "malformed-overflow.json").write_text(
        '{"broken', encoding="utf-8"
    )
    with pytest.raises(manifest_mod.DiscoveryManifestError) as exc:
        load_manifest(root)
    assert "JSON payload files" in str(exc.value)


def test_target_deterministic_order(tmp_path, monkeypatch) -> None:
    _tiny_manifest_budget(monkeypatch)
    root = write_manifest_root(
        tmp_path / "fx-ord",
        targets={
            "zz-target-v1": build_target("zz-target-v1"),
            "aa-target-v1": build_target("aa-target-v1"),
        },
    )
    manifest = load_manifest(root)
    assert [t["targetRevisionId"] for t in manifest.targets] == [
        "aa-target-v1",
        "zz-target-v1",
    ]


def test_target_scan_oserror_maps_to_stable_error(tmp_path, monkeypatch) -> None:
    """An OSError during the targets/ name scan maps to a redacted error."""
    _tiny_manifest_budget(monkeypatch)
    root = write_manifest_root(tmp_path / "fx-scan-error")

    made = {}

    class _Failing:
        def __init__(self):
            self.closed = False

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self.closed = True
            return False

        def __iter__(self):
            return self

        def __next__(self):
            raise OSError("raw detail must be redacted")

    def failing_scandir(fd):
        instance = _Failing()
        made["instance"] = instance
        return instance

    monkeypatch.setattr(manifest_mod.os, "scandir", failing_scandir)
    with pytest.raises(manifest_mod.DiscoveryManifestError) as exc:
        load_manifest(root)
    message = str(exc.value)
    assert message == "targets/: directory scan failed"
    assert "raw detail must be redacted" not in message  # raw OS detail never leaks
    assert made["instance"].closed is True  # context manager closed even on failure


def test_no_unbounded_file_reads_in_discovery_source() -> None:
    """AST guard: discovery loading must rely on bounded descriptor reads.

    Iterates fixture_io.py, manifest.py, and connectors/base.py. For each
    module it rejects ``Path.read_text``/``read_bytes``, a zero-arg
    ``.read()`` (no positional args and no keywords), and ``os.listdir``.
    It must NOT flag ``os.read(fd, size)`` (the bounded helper) by treating
    any ``os.read`` attribute as a forbidden ``.read()``.
    """
    modules = (fixture_io_mod, manifest_mod, base_mod)
    for mod in modules:
        source = Path(mod.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        label = Path(mod.__file__).name
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                assert node.attr != "listdir", f"forbidden os.listdir in {label}"
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Attribute):
                    if func.attr == "read_text" or func.attr == "read_bytes":
                        assert False, f"forbidden unbounded read {func.attr} in {label}"
                    if func.attr == "read":
                        # Zero-arg `.read()` only: `os.read(fd, size)` has args.
                        if not node.args and not node.keywords:
                            assert False, f"forbidden zero-arg .read() in {label}"
                elif isinstance(func, ast.Name) and func.id == "read":
                    if not node.args and not node.keywords:
                        assert False, f"forbidden zero-arg read in {label}"


# ===========================================================================
# StaticFixtureConnector: bounded descriptor loading + whole-file caps
# ===========================================================================


def test_connector_mandatory_constant_values() -> None:
    assert MAX_STATIC_FIXTURE_BYTES == 8 * 1024 * 1024
    assert MAX_STATIC_JSON_DEPTH == 64
    assert MAX_STATIC_JSON_NODES == 100_000
    assert MAX_STATIC_TARGET_ENTRIES == 512
    assert MAX_STATIC_CANDIDATES_PER_TARGET == 1_000
    assert MAX_STATIC_CANDIDATE_SPECS == 10_000


def test_connector_fixture_root_symlink_rejects_with_zero_reads(
    tmp_path, monkeypatch
) -> None:
    """A symlink fixture root must fail before any outside byte is read."""
    real_read = os.read
    reads = {"n": 0}

    def fake_read(fd, size):
        reads["n"] += 1
        return real_read(fd, size)

    monkeypatch.setattr("app.discovery.connectors.base.os.read", fake_read)

    real_root = tmp_path / "real-root"
    write_manifest_root(real_root, observations={"example-target-v1": {"candidates": [], "reviewRequired": False}})
    link = tmp_path / "root-link"
    link.symlink_to(real_root)

    connector = StaticFixtureConnector()
    target = {"targetRevisionId": "example-target-v1"}
    from app.scheduling.slots import slot_for_ordinal

    slot = slot_for_ordinal("2026-01-01T00:00:00Z", 43_200, 0)
    with pytest.raises(ConnectorError) as exc:
        connector.observe(target=target, fixture_root=link, slot=slot)
    assert exc.value.reason_code == "STATIC_FIXTURE_UNREADABLE"
    assert reads["n"] == 0


def test_connector_connectors_dir_symlink_rejects_with_zero_reads(
    tmp_path, monkeypatch
) -> None:
    """A symlink ``connectors/`` directory must fail before any outside read."""
    import app.discovery.connectors.base as base_mod

    real_read = os.read
    reads = {"n": 0}

    def fake_read(fd, size):
        reads["n"] += 1
        return real_read(fd, size)

    monkeypatch.setattr(base_mod.os, "read", fake_read)

    root = tmp_path / "fx-root"
    write_manifest_root(
        root,
        observations={"example-target-v1": {"candidates": [], "reviewRequired": False}},
    )
    real_conn = root / "real-conn"
    (root / "connectors").rename(real_conn)
    (root / "connectors").symlink_to(real_conn)

    connector = StaticFixtureConnector()
    from app.scheduling.slots import slot_for_ordinal

    slot = slot_for_ordinal("2026-01-01T00:00:00Z", 43_200, 0)
    with pytest.raises(ConnectorError) as exc:
        connector.observe(
            target={"targetRevisionId": "example-target-v1"},
            fixture_root=root,
            slot=slot,
        )
    assert exc.value.reason_code == "STATIC_FIXTURE_UNREADABLE"
    assert reads["n"] == 0


def test_connector_static_json_symlink_rejects_with_zero_reads(
    tmp_path, monkeypatch
) -> None:
    """A symlink ``static.json`` leaf must fail before any outside bytes read."""
    import app.discovery.connectors.base as base_mod

    real_read = os.read
    reads = {"n": 0}

    def fake_read(fd, size):
        reads["n"] += 1
        return real_read(fd, size)

    monkeypatch.setattr(base_mod.os, "read", fake_read)

    root = tmp_path / "fx-root"
    write_manifest_root(
        root,
        observations={"example-target-v1": {"candidates": [], "reviewRequired": False}},
    )
    real_leaf = root / "connectors" / "real-static.json"
    (root / "connectors" / "static.json").rename(real_leaf)
    (root / "connectors" / "static.json").symlink_to(real_leaf)

    connector = StaticFixtureConnector()
    from app.scheduling.slots import slot_for_ordinal

    slot = slot_for_ordinal("2026-01-01T00:00:00Z", 43_200, 0)
    with pytest.raises(ConnectorError) as exc:
        connector.observe(
            target={"targetRevisionId": "example-target-v1"},
            fixture_root=root,
            slot=slot,
        )
    assert exc.value.reason_code == "STATIC_FIXTURE_UNREADABLE"
    assert reads["n"] == 0


def test_connector_target_entries_exact_and_plus_one(tmp_path, monkeypatch) -> None:
    """MAX_STATIC_TARGET_ENTRIES boundaries with assembly-call accounting."""
    root = write_manifest_root(
        tmp_path / "fx-target-entries",
        observations={
            "selected-target-v1": {
                "candidates": [build_candidate_spec("selected-source")],
                "reviewRequired": False,
            },
            "empty-target-v1": {
                "candidates": [],
                "reviewRequired": False,
            },
        },
    )
    connector = StaticFixtureConnector()
    slot = slot_for_ordinal("2026-01-01T00:00:00Z", 43_200, 0)

    calls = []
    monkeypatch.setattr(
        base_mod,
        "assemble_candidate",
        lambda rev, spec: calls.append(rev) or {"ok": True},
    )

    # exact: two entries at cap=2 passes and assembles only the selected target.
    monkeypatch.setattr(base_mod, "MAX_STATIC_TARGET_ENTRIES", 2)
    obs = connector.observe(
        target={"targetRevisionId": "selected-target-v1"},
        fixture_root=root,
        slot=slot,
    )
    assert obs.candidates == ({"ok": True},)
    assert calls == ["selected-target-v1"]

    # +1: three... two entries exceed cap=1, rejected before any assembly.
    calls.clear()
    monkeypatch.setattr(base_mod, "MAX_STATIC_TARGET_ENTRIES", 1)
    with pytest.raises(ConnectorError) as exc:
        connector.observe(
            target={"targetRevisionId": "selected-target-v1"},
            fixture_root=root,
            slot=slot,
        )
    assert exc.value.reason_code == "STATIC_FIXTURE_TOO_MANY_TARGETS"
    assert calls == []


def test_connector_selected_target_candidates_exact_and_plus_one(
    tmp_path, monkeypatch
) -> None:
    """MAX_STATIC_CANDIDATES_PER_TARGET boundaries for one selected target."""
    root = write_manifest_root(
        tmp_path / "fx-selected-candidates",
        observations={
            "selected-target-v1": {
                "candidates": [
                    build_candidate_spec("selected-source-a"),
                    build_candidate_spec("selected-source-b"),
                ],
                "reviewRequired": False,
            },
        },
    )
    connector = StaticFixtureConnector()
    slot = slot_for_ordinal("2026-01-01T00:00:00Z", 43_200, 0)

    calls = []
    monkeypatch.setattr(
        base_mod,
        "assemble_candidate",
        lambda rev, spec: calls.append(rev) or {"ok": True},
    )
    # Keep target-entry and aggregate caps high; only the per-target cap moves.
    monkeypatch.setattr(base_mod, "MAX_STATIC_TARGET_ENTRIES", 100)
    monkeypatch.setattr(base_mod, "MAX_STATIC_CANDIDATES_PER_TARGET", 2)
    monkeypatch.setattr(base_mod, "MAX_STATIC_CANDIDATE_SPECS", 100)

    # exact: two candidate specs at cap=2 assembles both.
    obs = connector.observe(
        target={"targetRevisionId": "selected-target-v1"},
        fixture_root=root,
        slot=slot,
    )
    assert obs.candidates == ({"ok": True}, {"ok": True})
    assert calls == ["selected-target-v1", "selected-target-v1"]

    # +1: two specs exceed cap=1, rejected before any assembly.
    calls.clear()
    monkeypatch.setattr(base_mod, "MAX_STATIC_CANDIDATES_PER_TARGET", 1)
    with pytest.raises(ConnectorError) as exc:
        connector.observe(
            target={"targetRevisionId": "selected-target-v1"},
            fixture_root=root,
            slot=slot,
        )
    assert exc.value.reason_code == "STATIC_FIXTURE_TOO_MANY_CANDIDATES"
    assert calls == []


def test_connector_aggregate_candidates_exact_and_plus_one(
    tmp_path, monkeypatch
) -> None:
    """MAX_STATIC_CANDIDATE_SPECS whole-file aggregate across target entries."""
    root = write_manifest_root(
        tmp_path / "fx-aggregate-candidates",
        observations={
            "selected-target-v1": {
                "candidates": [
                    build_candidate_spec("selected-source-a"),
                    build_candidate_spec("selected-source-b"),
                ],
                "reviewRequired": False,
            },
            "other-target-v1": {
                "candidates": [build_candidate_spec("other-source")],
                "reviewRequired": False,
            },
        },
    )
    connector = StaticFixtureConnector()
    slot = slot_for_ordinal("2026-01-01T00:00:00Z", 43_200, 0)

    calls = []
    monkeypatch.setattr(
        base_mod,
        "assemble_candidate",
        lambda rev, spec: calls.append(rev) or {"ok": True},
    )
    # Keep per-target and target caps high; only the aggregate cap moves.
    monkeypatch.setattr(base_mod, "MAX_STATIC_TARGET_ENTRIES", 100)
    monkeypatch.setattr(base_mod, "MAX_STATIC_CANDIDATES_PER_TARGET", 100)
    monkeypatch.setattr(base_mod, "MAX_STATIC_CANDIDATE_SPECS", 3)

    # exact: total 3 specs across two entries at aggregate cap=3 passes, and
    # assembles only the selected target's 2 specs.
    obs = connector.observe(
        target={"targetRevisionId": "selected-target-v1"},
        fixture_root=root,
        slot=slot,
    )
    assert obs.candidates == ({"ok": True}, {"ok": True})
    assert calls == ["selected-target-v1", "selected-target-v1"]

    # +1: total 3 specs exceed aggregate cap=2, rejected before any assembly.
    calls.clear()
    monkeypatch.setattr(base_mod, "MAX_STATIC_CANDIDATE_SPECS", 2)
    with pytest.raises(ConnectorError) as exc:
        connector.observe(
            target={"targetRevisionId": "selected-target-v1"},
            fixture_root=root,
            slot=slot,
        )
    assert exc.value.reason_code == "STATIC_FIXTURE_TOO_MANY_CANDIDATES"
    assert calls == []


class _MemoryConnector:
    """Return preassembled candidates without reading a connector fixture."""

    connector_id = "memory"

    def __init__(self, candidates_by_revision):
        self._candidates_by_revision = candidates_by_revision

    def observe(self, *, target, fixture_root, slot):
        del fixture_root, slot
        return ConnectorObservation(
            candidates=self._candidates_by_revision[target["targetRevisionId"]],
            review_required=False,
        )


def _two_target_controller_fixture(tmp_path):
    root = write_manifest_root(
        tmp_path / "controller-fixture",
        targets={
            "a-target-v1": build_target("a-target-v1", connector_id="memory"),
            "b-target-v1": build_target("b-target-v1", connector_id="memory"),
        },
    )
    manifest = load_manifest(root)
    slot = slot_for_ordinal(manifest.anchor_utc, manifest.cadence_seconds, 0)
    return root, manifest, slot


def _operational_counts(session):
    return {
        model.__tablename__: session.scalar(select(func.count()).select_from(model))
        for model in (
            models.ScheduledCycleIntent,
            models.ScheduledCycleIntentCompletion,
            models.ScheduledJobIntent,
            models.DiscoveryCandidate,
        )
    }


def test_controller_candidate_cycle_cap_is_documented() -> None:
    assert controller_mod.MAX_CANDIDATES_PER_CYCLE == 10_000


def test_controller_candidate_cycle_exact_cap_commits(tmp_db, tmp_path, monkeypatch) -> None:
    root, manifest, slot = _two_target_controller_fixture(tmp_path)
    connector = _MemoryConnector(
        {
            "a-target-v1": (
                assemble_candidate("a-target-v1", build_candidate_spec("a-source")),
            ),
            "b-target-v1": (
                assemble_candidate("b-target-v1", build_candidate_spec("b-source")),
            ),
        }
    )
    monkeypatch.setattr(controller_mod, "MAX_CANDIDATES_PER_CYCLE", 2)

    with get_session() as session:
        report = run_discovery_cycle(
            session,
            manifest=manifest,
            slot=slot,
            connectors={"memory": connector},
            fixture_root=root,
        )
        assert report.counts["newCandidateCount"] == 2

    with get_session() as session:
        assert _operational_counts(session) == {
            "scheduled_cycle_intents": 1,
            "scheduled_cycle_intent_completions": 1,
            "scheduled_job_intents": 2,
            "discovery_candidates": 2,
        }


def test_controller_candidate_cycle_plus_one_rolls_back(
    tmp_db, tmp_path, monkeypatch
) -> None:
    root, manifest, slot = _two_target_controller_fixture(tmp_path)
    connector = _MemoryConnector(
        {
            "a-target-v1": (
                assemble_candidate("a-target-v1", build_candidate_spec("a-source")),
            ),
            "b-target-v1": (
                assemble_candidate("b-target-v1", build_candidate_spec("b-source-1")),
                assemble_candidate("b-target-v1", build_candidate_spec("b-source-2")),
            ),
        }
    )
    monkeypatch.setattr(controller_mod, "MAX_CANDIDATES_PER_CYCLE", 2)

    real_append = controller_mod.append_discovery_candidate
    appended_candidate_ids = []

    def recording_append(session, payload):
        row = real_append(session, payload)
        appended_candidate_ids.append(row.candidate_id)
        return row

    monkeypatch.setattr(controller_mod, "append_discovery_candidate", recording_append)
    report = None
    with pytest.raises(DiscoveryControllerError, match="exceeds per-cycle cap"):
        with get_session() as session:
            report = run_discovery_cycle(
                session,
                manifest=manifest,
                slot=slot,
                connectors={"memory": connector},
                fixture_root=root,
            )

    assert report is None
    assert len(appended_candidate_ids) == 1
    with get_session() as session:
        assert _operational_counts(session) == {
            "scheduled_cycle_intents": 0,
            "scheduled_cycle_intent_completions": 0,
            "scheduled_job_intents": 0,
            "discovery_candidates": 0,
        }
