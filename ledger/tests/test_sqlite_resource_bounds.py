"""F19 Checkpoint B: bounded SQLite recovery reads and row-budget accounting
(CWE-400) — focused GREEN contract.

The SQLite recovery driver must never unboundedly materialize file bytes or
cursor rows.  ``sqlite_driver.py`` previously used unbounded ``Path.read_bytes()``
in ``_inspect_sqlite_path`` / ``create_backup`` / ``restore_new_target`` and
``cursor.fetchall()`` in ``_rows``.  The controls under test are:

* ``_read_bounded_bytes(path, cap, label)`` — a bounded, fixed-positive
  ``os.read`` streamer that clamps its request total to at most ``cap+1``,
  rejects in-place growth beyond the fstat size and unsafe symlink posture,
  maps read errors to a typed redacted ``RecoveryPartialFailure``, and closes
  its descriptor on both success and failure.
* ``_require_artifact`` (an instance method) — rejects an artifact whose
  ``raw_bytes`` exceeds the module ``_DATABASE_BYTES_CAP`` BEFORE
  ``_write_private_file`` is reached; ``inspect_artifact`` verifies its staged
  file and the restored target by STREAMING with no second full-bytes copy.
* ``_RowBudget`` with FOUR independent limits — per-table rows, cumulative
  rows, per-table payload bytes, cumulative payload bytes — plus ``_rows``
  driven only by fixed-positive ``fetchmany(_ROW_FETCH_BATCH)`` (never
  ``fetchall``), charging payload bytes from the rows actually returned.

``_ROW_FETCH_BATCH`` is the documented positive bounded batch size: every
``fetchmany`` request must equal it exactly, never an arbitrarily huge size.

Documented deterministic payload byte rule: a row's payload bytes equal
``sum(len(str(cell).encode("utf-8")) for cell in row)``.
"""

from __future__ import annotations

import ast
import hashlib
import os
from pathlib import Path

import pytest

from app.backup.errors import RecoveryIntegrityError, RecoveryPartialFailure
from app.backup.protocols import RelationalBackupArtifact

import app.backup.sqlite_driver as sqlite_driver

# Tiny fixture cap: never allocate real-cap (unbounded) data.
_CAP = 64
_SQLITE_HEADER_LEN = len(sqlite_driver._SQLITE_HEADER)  # 16


def _artifact(total_bytes: int) -> RelationalBackupArtifact:
    """A VALID current SQLite artifact whose raw bytes start with the header.

    Metadata is taken from the driver class attributes (not nonexistent module
    constants); ``total_bytes`` must be >= header length so the exact-cap
    artifact passes the existing format/version/header validation.
    """
    driver = sqlite_driver.SQLiteBackupRestoreDriver
    return RelationalBackupArtifact(
        driver_id=driver.driver_id,
        driver_version=driver.driver_version,
        engine_name=driver.engine_name,
        engine_version=driver.engine_version,
        tool_name=driver.tool_name,
        tool_version=driver.tool_version,
        artifact_type=driver.artifact_type,
        format=driver.format,
        format_version=driver.format_version,
        source_database_identity_sha256="a" * 64,
        raw_bytes=sqlite_driver._SQLITE_HEADER
        + b"z" * (total_bytes - _SQLITE_HEADER_LEN),
    )


def _driver() -> sqlite_driver.SQLiteBackupRestoreDriver:
    return object.__new__(sqlite_driver.SQLiteBackupRestoreDriver)


def _write_private(path: Path, data: bytes) -> None:
    """0600, O_EXCL fixture writer (bounded-read fixtures must be private)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)


def _count_open_fds() -> int:
    if not Path("/dev/fd").exists():
        return 0
    return len(list(Path("/dev/fd").iterdir()))


class _FakeCursor:
    """Serves a deterministic row stream; records fetch calls; fetchall RAISES."""

    def __init__(self, rows: list[tuple]) -> None:
        self._rows = rows
        self._pos = 0
        self.calls: list[int] = []
        self.fetchall_called = False

    @property
    def description(self) -> list[tuple]:
        return [("row_id",), ("payload",)]

    def fetchmany(self, size: int) -> list[tuple]:
        self.calls.append(size)
        if self._pos >= len(self._rows):
            return []
        chunk = self._rows[self._pos : self._pos + size]
        self._pos += len(chunk)
        return chunk

    def fetchall(self) -> list[tuple]:
        self.fetchall_called = True
        raise AssertionError("fetchall must never be called by _rows")


class _FakeConnection:
    """Planned ``_rows(connection, table, budget)`` takes a connection."""

    def __init__(self, cursor: _FakeCursor) -> None:
        self._cursor = cursor

    def execute(self, _sql: str) -> _FakeCursor:
        return self._cursor


# ---------------------------------------------------------------------------
# planned _read_bounded_bytes
# ---------------------------------------------------------------------------

def test_read_bounded_bytes_exact_cap_mode_0600_no_fd_leak(tmp_path: Path) -> None:
    """Exact-cap 0600 file is read fully and the descriptor is closed."""
    path = tmp_path / "exact.bin"
    payload = b"x" * _CAP
    _write_private(path, payload)
    before = _count_open_fds()
    data = sqlite_driver._read_bounded_bytes(path, cap=_CAP, label="sqlite")
    assert data == payload
    assert _count_open_fds() == before


def test_read_bounded_bytes_cap_plus_one_fails_closed(tmp_path: Path) -> None:
    """cap+1 must be rejected before full materialization."""
    path = tmp_path / "overflow.bin"
    _write_private(path, b"y" * (_CAP + 1))
    with pytest.raises(RecoveryIntegrityError, match="cap"):
        sqlite_driver._read_bounded_bytes(path, cap=_CAP, label="sqlite")


def test_read_bounded_bytes_inplace_growth_after_fstat_requests_cap_plus_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A file that grows past its fstat size in place must be rejected after
    being offered at most cap+1 bytes (never a full chunk over the cap)."""
    path = tmp_path / "grow.bin"
    _write_private(path, b"g" * 16)  # small on disk -> passes the fstat precheck

    requests: list[int] = []

    def growing_read(fd: int, size: int) -> bytes:
        requests.append(size)
        return b"G" * size  # serve unbounded bytes past the fstat claim

    monkeypatch.setattr(os, "read", growing_read)
    with pytest.raises(RecoveryIntegrityError, match="cap"):
        sqlite_driver._read_bounded_bytes(path, cap=_CAP, label="sqlite")
    assert requests
    assert all(0 < size <= _CAP + 1 for size in requests)
    assert sum(requests) == _CAP + 1  # cap + 1, never cap + chunk


def test_read_bounded_bytes_read_error_is_typed_redacted_fd_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A read OSError is a typed redacted recovery failure (never a raw
    OSError) and the descriptor is closed."""
    path = tmp_path / "readfail.bin"
    _write_private(path, b"z" * 16)

    def exploding_read(fd: int, size: int) -> bytes:
        raise OSError("secret read detail")

    monkeypatch.setattr(os, "read", exploding_read)
    before = _count_open_fds()
    with pytest.raises(RecoveryPartialFailure) as exc:
        sqlite_driver._read_bounded_bytes(path, cap=_CAP, label="sqlite")
    assert exc.value.reason_code == "SQLITE_ARCHIVE_READ_FAILED"
    assert "secret" not in str(exc.value)
    assert str(exc.value.__cause__) == "None"
    assert _count_open_fds() == before


def test_read_bounded_bytes_rejects_symlink_posture(tmp_path: Path) -> None:
    """O_NOFOLLOW open of a symlink is a posture rejection, never a follow."""
    target = tmp_path / "target.bin"
    _write_private(target, b"payload")
    link = tmp_path / "link.bin"
    link.symlink_to(target)
    with pytest.raises(RecoveryIntegrityError, match="posture"):
        sqlite_driver._read_bounded_bytes(link, cap=_CAP, label="sqlite")


# ---------------------------------------------------------------------------
# planned _require_artifact database-byte cap gate
# ---------------------------------------------------------------------------

def test_require_artifact_rejects_cap_plus_one_before_private_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An over-cap VALID artifact must be rejected by _require_artifact before
    inspect_artifact can reach _write_private_file (bomb write never fires)."""
    monkeypatch.setattr(sqlite_driver, "_DATABASE_BYTES_CAP", _CAP)

    def bomb_write(_path: Path, _raw: bytes) -> None:
        raise AssertionError("_write_private_file must never be reached")

    monkeypatch.setattr(sqlite_driver, "_write_private_file", bomb_write)
    with pytest.raises(RecoveryIntegrityError, match="cap"):
        _driver().inspect_artifact(_artifact(_CAP + 1))


def test_require_artifact_exact_cap_valid_artifact_passes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An exact-cap valid artifact passes the cap gate without raising."""
    monkeypatch.setattr(sqlite_driver, "_DATABASE_BYTES_CAP", _CAP)
    _driver()._require_artifact(_artifact(_CAP))


# ---------------------------------------------------------------------------
# planned _RowBudget: four independent limits
# ---------------------------------------------------------------------------

def _budget(
    *,
    rows_per_table: int,
    rows_cumulative: int,
    payload_per_table: int,
    payload_cumulative: int,
) -> "sqlite_driver._RowBudget":
    return sqlite_driver._RowBudget(
        max_rows_per_table=rows_per_table,
        max_rows_cumulative=rows_cumulative,
        max_payload_bytes_per_table=payload_per_table,
        max_payload_bytes_cumulative=payload_cumulative,
    )


def test_row_budget_rows_per_table_and_cumulative_exact_and_cap_plus_one() -> None:
    """Per-table and cumulative row limits are distinct counters: each exact
    and cap+1 case uses a FRESH budget, and the untested counter is set far
    higher so only the intended limit can trip."""
    # Per-table exact and +1 (cumulative limit far above).
    assert _budget(
        rows_per_table=5, rows_cumulative=1000,
        payload_per_table=1000, payload_cumulative=1000,
    ).admit_rows("t", 5) is True
    with pytest.raises(RecoveryIntegrityError, match="row"):
        _budget(
            rows_per_table=5, rows_cumulative=1000,
            payload_per_table=1000, payload_cumulative=1000,
        ).admit_rows("t", 6)
    # Cumulative exact and +1 across tables (per-table limit far above).
    assert _budget(
        rows_per_table=1000, rows_cumulative=8,
        payload_per_table=1000, payload_cumulative=1000,
    ).admit_rows("a", 5) is True
    cumulative_exact = _budget(
        rows_per_table=1000, rows_cumulative=8,
        payload_per_table=1000, payload_cumulative=1000,
    )
    assert cumulative_exact.admit_rows("a", 5) is True
    assert cumulative_exact.admit_rows("b", 3) is True
    cumulative_over = _budget(
        rows_per_table=1000, rows_cumulative=8,
        payload_per_table=1000, payload_cumulative=1000,
    )
    assert cumulative_over.admit_rows("a", 5) is True
    with pytest.raises(RecoveryIntegrityError, match="row"):
        cumulative_over.admit_rows("b", 4)


def test_row_budget_payload_per_table_exact_and_cap_plus_one() -> None:
    """Per-table payload limit: exact bound passes, cap+1 fails, with the
    cumulative counter set far above so only per-table can trip."""
    assert _budget(
        rows_per_table=1000, rows_cumulative=1000,
        payload_per_table=16, payload_cumulative=1000,
    ).admit_payload("t", 16) is True
    with pytest.raises(RecoveryIntegrityError, match="payload"):
        _budget(
            rows_per_table=1000, rows_cumulative=1000,
            payload_per_table=16, payload_cumulative=1000,
        ).admit_payload("t", 17)


def test_row_budget_payload_cumulative_cross_table_and_large_cell() -> None:
    """Cumulative payload limit: cross-table accumulation and a single large
    cell both fail closed, with per-table limits far above so only the
    cumulative counter can trip."""
    cumulative_exact = _budget(
        rows_per_table=1000, rows_cumulative=1000,
        payload_per_table=1000, payload_cumulative=20,
    )
    assert cumulative_exact.admit_payload("a", 10) is True
    assert cumulative_exact.admit_payload("b", 10) is True
    # Cross-table cap+1: a 10, then b 11 -> 21 > 20.
    cross_table_over = _budget(
        rows_per_table=1000, rows_cumulative=1000,
        payload_per_table=1000, payload_cumulative=20,
    )
    assert cross_table_over.admit_payload("a", 10) is True
    with pytest.raises(RecoveryIntegrityError, match="payload"):
        cross_table_over.admit_payload("b", 11)
    # One large cell over the remaining cumulative budget (same table).
    large_cell_over = _budget(
        rows_per_table=1000, rows_cumulative=1000,
        payload_per_table=1000, payload_cumulative=8,
    )
    assert large_cell_over.admit_payload("a", 5) is True
    with pytest.raises(RecoveryIntegrityError, match="payload"):
        large_cell_over.admit_payload("a", 4)


# ---------------------------------------------------------------------------
# planned _rows(connection, table, budget) integration
# ---------------------------------------------------------------------------

def test_rows_uses_fixed_positive_fetchmany_never_fetchall() -> None:
    """_rows(connection, table, budget) must drive the cursor with exactly
    ``fetchmany(_ROW_FETCH_BATCH)`` (a positive bounded batch constant — a
    larger request would prove an unbounded fetch); the cursor's fetchall
    raises, so completing the call proves fetchall was never invoked."""
    cursor = _FakeCursor([(1, "a"), (2, "bb"), (3, "ccc")])
    connection = _FakeConnection(cursor)
    budget = _budget(
        rows_per_table=100, rows_cumulative=100,
        payload_per_table=1000, payload_cumulative=1000,
    )
    rows = sqlite_driver._rows(connection, "fixture_table", budget)
    assert rows == [
        {"row_id": 1, "payload": "a"},
        {"row_id": 2, "payload": "bb"},
        {"row_id": 3, "payload": "ccc"},
    ]
    assert cursor.calls
    assert all(size == sqlite_driver._ROW_FETCH_BATCH for size in cursor.calls)
    assert cursor.fetchall_called is False


def test_rows_payload_accounting_debited_by_returned_rows() -> None:
    """Payload accounting is debited from the rows actually returned, using
    the documented deterministic byte rule (sum of utf-8 bytes per cell):
    row (1, 'a') = 2 bytes, row (2, 'bb') = 3 bytes, total 5."""
    rows = [(1, "a"), (2, "bb")]
    cursor = _FakeCursor(rows)
    connection = _FakeConnection(cursor)
    exact = _budget(
        rows_per_table=10, rows_cumulative=10,
        payload_per_table=5, payload_cumulative=5,
    )
    result = sqlite_driver._rows(connection, "fixture_table", exact)
    assert result == [{"row_id": 1, "payload": "a"}, {"row_id": 2, "payload": "bb"}]
    assert exact.payload_bytes_per_table["fixture_table"] == 5
    # Fresh budget with the per-table payload cap at 4: 2 + 3 > 4 fails closed.
    overflow_cursor = _FakeCursor(rows)
    with pytest.raises(RecoveryIntegrityError, match="payload"):
        sqlite_driver._rows(
            _FakeConnection(overflow_cursor),
            "fixture_table",
            _budget(
                rows_per_table=10, rows_cumulative=10,
                payload_per_table=4, payload_cumulative=1000,
            ),
        )


# ---------------------------------------------------------------------------
# F19 integration RED layer (A6.1): create_backup source preflight + staged
# bounded-read routing — controls missing from current production, so these
# fail only on the missing gate, never on the fake/bomb.
# ---------------------------------------------------------------------------

def test_create_backup_source_preflight_rejects_cap_plus_one_before_connection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A private regular SQLite source whose stat size is cap+1 must be
    rejected by create_backup BEFORE any SQLite connection is opened.

    The connection is a bomb that raises AssertionError, so reaching it would
    fail the test; only the missing size gate can produce the expected cap
    RecoveryIntegrityError.
    """
    source = tmp_path / "oversize.db"
    _write_private(source, b"z" * (_CAP + 1))

    def bomb_connection(_path: Path) -> None:
        raise AssertionError("_read_only_connection must never be reached")

    monkeypatch.setattr(sqlite_driver, "_DATABASE_BYTES_CAP", _CAP)
    monkeypatch.setattr(sqlite_driver, "_read_only_connection", bomb_connection)
    with pytest.raises(RecoveryIntegrityError, match="cap"):
        sqlite_driver.SQLiteBackupRestoreDriver().create_backup(source)


def test_create_backup_routes_staged_file_through_bounded_reader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """create_backup must route the staged file through
    _read_bounded_bytes(..., cap=_DATABASE_BYTES_CAP) before artifact
    construction.

    The spy records the staged path and the cap, then raises the cap
    RecoveryIntegrityError; a create_backup that still reads the staged bytes
    directly (current production) bypasses the spy and returns an artifact,
    which fails this test.
    """
    source = tmp_path / "source.db"
    _write_private(source, b"z" * _CAP)

    class _Destination:
        def __init__(self, path: Path) -> None:
            self.path = path

        def close(self) -> None:
            return None

    class _SourceContext:
        def __enter__(self) -> "_SourceContext":
            return self

        def __exit__(self, *_exc: object) -> None:
            return None

        def backup(self, destination: _Destination, pages: int, progress: object) -> None:
            _write_private(destination.path, sqlite_driver._SQLITE_HEADER + b"y" * (_CAP - _SQLITE_HEADER_LEN))
            if callable(progress):
                progress(0, 0, _CAP)

    calls: list[tuple[Path, int, str]] = []

    def fake_read_only_connection(_path: Path) -> _SourceContext:
        return _SourceContext()

    def fake_connect(_path: Path) -> _Destination:
        return _Destination(_path)

    def spy_bounded_read(path: Path, *, cap: int, label: str) -> bytes:
        calls.append((path, cap, label))
        raise RecoveryIntegrityError("cap")

    monkeypatch.setattr(sqlite_driver, "_read_only_connection", fake_read_only_connection)
    monkeypatch.setattr(sqlite_driver, "sqlite3", type("_FakeSqlite3", (), {"connect": staticmethod(fake_connect)}))
    monkeypatch.setattr(sqlite_driver, "_read_bounded_bytes", spy_bounded_read)

    with pytest.raises(RecoveryIntegrityError, match="cap"):
        sqlite_driver.SQLiteBackupRestoreDriver().create_backup(source)
    assert len(calls) == 1
    assert calls[0][0].name == "backup.sqlite3"
    assert calls[0][1] == sqlite_driver._DATABASE_BYTES_CAP
    assert isinstance(calls[0][2], str) and calls[0][2]


# ---------------------------------------------------------------------------
# F19 integration RED layer (A6.2): planned _stream_path_identity helper and
# restore_new_target streaming verification — controls missing from current
# production, so these fail on the missing control, never on the fake.
# ---------------------------------------------------------------------------

def test_stream_path_identity_returns_length_and_sha256_no_bytes(
    tmp_path: Path
) -> None:
    """The planned _stream_path_identity(path, *, cap, label) must return only
    (byte length, SHA256 hexdigest) with descriptor-pinned fixed-positive reads
    — never a full bytes object — and must reject cap+1 files."""
    path = tmp_path / "payload.bin"
    payload = b"ab" * 3
    _write_private(path, payload)
    identity = sqlite_driver._stream_path_identity(path, cap=_CAP, label="sqlite")
    assert identity == (len(payload), hashlib.sha256(payload).hexdigest())
    assert not isinstance(identity, bytes)
    assert not any(isinstance(item, bytes) for item in identity)
    overflow = tmp_path / "overflow.bin"
    _write_private(overflow, b"z" * (_CAP + 1))
    with pytest.raises(RecoveryIntegrityError, match="cap"):
        sqlite_driver._stream_path_identity(overflow, cap=_CAP, label="sqlite")


def test_restore_new_target_streams_verification_and_reuses_artifact_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """restore_new_target must verify the restored target through the real
    streaming identity helper (length + digest, no full re-read into a second
    bytes object) and pass artifact.raw_bytes by identity into the inspection
    artifact.

    The spy records target/cap/label and returns the real helper's result;
    _inspect_sqlite_path captures the inspection artifact and returns a unique
    sentinel. Missing _stream_path_identity fails at monkeypatch time — the
    intended RED.
    """
    artifact = _artifact(_CAP)
    target = tmp_path / "restored.db"
    calls: list[tuple[Path, int, str]] = []
    real_stream = sqlite_driver._stream_path_identity
    captured: dict[str, object] = {}
    sentinel = object()

    def spy_stream(path: Path, *, cap: int, label: str) -> tuple[int, str]:
        calls.append((path, cap, label))
        return real_stream(path, cap=cap, label=label)

    def fake_inspect(path: Path, inspection_artifact: object) -> object:
        captured["path"] = path
        captured["artifact"] = inspection_artifact
        return sentinel

    monkeypatch.setattr(sqlite_driver, "_DATABASE_BYTES_CAP", _CAP)
    monkeypatch.setattr(sqlite_driver, "_stream_path_identity", spy_stream)
    monkeypatch.setattr(sqlite_driver, "_inspect_sqlite_path", fake_inspect)
    result = sqlite_driver.SQLiteBackupRestoreDriver().restore_new_target(
        artifact, target, target_id="restore-a6-2"
    )
    assert result is sentinel
    assert len(calls) == 1
    assert calls[0][0] == target
    assert calls[0][1] == _CAP
    assert isinstance(calls[0][2], str) and calls[0][2]
    assert captured["artifact"].raw_bytes is artifact.raw_bytes
    assert sqlite_driver._read_bounded_bytes(target, cap=_CAP, label="sqlite") == artifact.raw_bytes


# ---------------------------------------------------------------------------
# F19 integration RED layer (A6.3): planned _collect_semantic_rows shared
# cumulative budget + AST read_bytes ban — controls missing from current
# production, so these fail on the missing control, never on the fake.
# ---------------------------------------------------------------------------

def test_collect_semantic_rows_uses_one_shared_cumulative_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The planned _collect_semantic_rows(connection, expected) must extract
    every table through ONE shared _RowBudget, so a cumulative cross-table
    payload cap fails even when each per-table payload stays under its own
    limit. Per-table budgets would both pass (3 <= 5), proving the shared
    cumulative budget is the only trip."""
    monkeypatch.setattr(sqlite_driver, "_MAX_ROWS_PER_TABLE", 100, raising=False)
    monkeypatch.setattr(sqlite_driver, "_MAX_ROWS_CUMULATIVE", 100, raising=False)
    monkeypatch.setattr(sqlite_driver, "_MAX_PAYLOAD_BYTES_PER_TABLE", 100, raising=False)
    monkeypatch.setattr(sqlite_driver, "_MAX_PAYLOAD_BYTES_CUMULATIVE", 5, raising=False)

    executed: list[str] = []

    class _MultiConnection:
        def execute(self, sql: str) -> _FakeCursor:
            if sql == 'SELECT * FROM "a"':
                executed.append("a")
                return _FakeCursor([(1, "aa")])
            if sql == 'SELECT * FROM "b"':
                executed.append("b")
                return _FakeCursor([(2, "bb")])
            raise AssertionError(f"unexpected SQL: {sql}")

    with pytest.raises(RecoveryIntegrityError, match="payload"):
        sqlite_driver._collect_semantic_rows(
            _MultiConnection(), {"b": (), "a": ()}
        )
    assert executed == ["a", "b"]


def test_sqlite_driver_has_no_read_bytes_call() -> None:
    """AST proof: sqlite_driver.py must contain zero
    ``.read_bytes()`` ast.Call nodes — no unbounded full-file materialization.
    Current production has exactly three (inspect, create_backup, restore) and
    must fail this assertion."""
    tree = ast.parse(
        Path(sqlite_driver.__file__).read_text(encoding="utf-8")
    )
    read_bytes_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "read_bytes"
    ]
    assert read_bytes_calls == []
