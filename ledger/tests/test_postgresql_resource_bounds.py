"""F9 regression: bounded PostgreSQL recovery backup materialization (CWE-400).

The PostgreSQL 16 custom-archive recovery path must never unboundedly
materialize archive bytes, pg-tool stdout, or TOC entries, and must enforce a
documented database-size budget before pg_dump / restore / inspection.  Every
guard is fail-closed with a stable redacted typed failure; exact caps pass and
cap+1 fails before full materialization.  Tests are adversarial and use fakes
only -- no live PostgreSQL is exercised (real coverage is opt-in and owned by
the recovery/portability suites, which skip when unset).
"""

from __future__ import annotations

import errno
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.backup.errors import (
    RecoveryIntegrityError,
    RecoveryPartialFailure,
    RecoveryTargetError,
    UnsupportedRecoveryArtifact,
)
from app.backup.postgresql_driver import (
    PG_DUMP_PATH,
    PG_RESTORE_PATH,
    PostgreSQLBackupRestoreDriver,
    _ARCHIVE_BYTES_CAP,
    _ARCHIVE_TOC_OUTPUT_BUDGET,
    _MAX_DATABASE_SIZE_BYTES,
    _OUTPUT_READ_CHUNK,
    _SCHEMA_ONLY_OUTPUT_BUDGET,
    _TOC_ENTRY_BOUND,
    _TOOL_VERSION_OUTPUT_BUDGET,
    _ZERO_OUTPUT_BUDGET,
    _assert_database_size_budget,
    _filter_public_schema_toc,
    _parse_tool_version,
    _read_bounded_bytes,
    _run_pg_tool,
    _schema_sha256,
    _write_archive_bytes,
    _write_archive_toc,
)
from app.backup.protocols import RelationalBackupArtifact

import app.backup.postgresql_driver as postgresql_driver


# F9 fixtures: monkeypatch the module archive cap to a tiny 64 bytes (never
# allocate over-1-GiB fixtures) and bypass the real toolchain so a driver can
# be built with object.__new__ (no live pg_dump/pg_restore dependency).


@pytest.fixture
def small_cap(monkeypatch: pytest.MonkeyPatch) -> int:
    monkeypatch.setattr(postgresql_driver, "_ARCHIVE_BYTES_CAP", 64)
    return 64


@pytest.fixture
def driver(
    monkeypatch: pytest.MonkeyPatch,
) -> PostgreSQLBackupRestoreDriver:
    """A driver instance that skips the binary-dependent __init__ and enforces
    a tiny archive cap.  All F9 tests stay fake-only and low-resource."""
    monkeypatch.setattr(postgresql_driver, "_ARCHIVE_BYTES_CAP", 64)
    monkeypatch.setattr(
        postgresql_driver, "_toolchain_version", lambda **_: "16.10"
    )
    d = object.__new__(PostgreSQLBackupRestoreDriver)
    d._command_timeout_seconds = 30.0
    d.tool_version = "16.10"
    d.driver_id = postgresql_driver._DRIVER_ID
    d.driver_version = postgresql_driver._DRIVER_VERSION
    d.engine_name = postgresql_driver._ENGINE_NAME
    d.tool_name = postgresql_driver._TOOL_NAME
    d.artifact_type = postgresql_driver._ARTIFACT_TYPE
    d.format = postgresql_driver._FORMAT
    d.format_version = postgresql_driver._FORMAT_VERSION
    return d


def _artifact(raw_payload: bytes = b"", *, header: bytes = b"PGDMP") -> RelationalBackupArtifact:
    return RelationalBackupArtifact(
        driver_id="postgresql-pg-tools",
        driver_version="1.0.0",
        engine_name="postgresql",
        engine_version="16.10",
        tool_name="pg_dump-pg_restore",
        tool_version="16.10",
        artifact_type="postgresql_database",
        format="postgresql_custom_archive",
        format_version="pg_dump-custom-v1",
        source_database_identity_sha256="b" * 64,
        raw_bytes=header + raw_payload,
    )


def _write_private(path: Path, data: bytes) -> None:
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


# ---------------------------------------------------------------------------
# Archive bounded reads (_read_bounded_bytes)
# ---------------------------------------------------------------------------

def test_bounded_read_fixed_positive_requests_and_no_leak(tmp_path: Path) -> None:
    path = tmp_path / "fixed.dump"
    _write_private(path, b"z" * 5000)
    before = _count_open_fds()
    data = _read_bounded_bytes(path, cap=5000, label="archive")
    assert data == b"z" * 5000
    assert _count_open_fds() == before


def test_bounded_read_cap_plus_one_fails_closed(
    tmp_path: Path, small_cap: int
) -> None:
    path = tmp_path / "too-big.dump"
    _write_private(path, b"y" * (small_cap + 1))
    with pytest.raises(RecoveryIntegrityError, match="posture or size"):
        _read_bounded_bytes(path, cap=small_cap, label="archive")


def test_bounded_read_growth_after_fstat_requests_at_most_cap_plus_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A file that grows past its fstat size in place must be rejected after
    being offered at most cap+1 bytes (never a full chunk over the cap)."""
    path = tmp_path / "grow.dump"
    _write_private(path, b"g" * 16)  # small on disk -> passes fstat precheck

    calls: list[int] = []

    def growing_read(fd: int, size: int) -> bytes:
        calls.append(size)
        return b"G" * size  # serve unbounded bytes past the fstat claim

    monkeypatch.setattr(os, "read", growing_read)
    with pytest.raises(RecoveryIntegrityError, match="cap"):
        _read_bounded_bytes(path, cap=1000, label="archive")
    assert calls
    assert all(0 < size <= 1001 for size in calls)
    assert sum(calls) == 1001  # cap + 1, never cap + CHUNK


def test_bounded_read_rejects_symlink_and_non_regular(
    tmp_path: Path, small_cap: int
) -> None:
    target = tmp_path / "target.dump"
    _write_private(target, b"payload")
    link = tmp_path / "link.dump"
    link.symlink_to(target)
    # O_NOFOLLOW open fails with ELOOP -> unsafe symlink posture, a strong
    # RecoveryIntegrityError (never a silent follow, never an opaque OSError).
    with pytest.raises(RecoveryIntegrityError, match="posture"):
        _read_bounded_bytes(link, cap=small_cap, label="archive")


def test_bounded_read_rejects_world_readable_private_posture(
    tmp_path: Path, small_cap: int
) -> None:
    path = tmp_path / "world.dump"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
    os.write(fd, b"data")
    os.close(fd)
    with pytest.raises(RecoveryIntegrityError, match="posture"):
        _read_bounded_bytes(path, cap=small_cap, label="archive")


def test_bounded_read_open_eloop_is_symlink_posture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An ELOOP open failure is a symlink-posture rejection (RecoveryIntegrity
    Error), preserving the prior strong posture semantics."""
    def explode_eloop_open(*_a, **_k):
        exc = OSError(errno.ELOOP, "too many levels of symbolic links")
        raise exc

    monkeypatch.setattr(os, "open", explode_eloop_open)
    with pytest.raises(RecoveryIntegrityError, match="posture"):
        _read_bounded_bytes(tmp_path / "link.dump", cap=64, label="archive")


def test_bounded_read_open_non_eloop_is_partial_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A non-ELOOP open failure is a typed RecoveryPartialFailure, not a raw
    OSError and not a posture claim."""
    def explode_open(*_a, **_k):
        raise OSError(errno.ENOENT, "No such file or directory")

    monkeypatch.setattr(os, "open", explode_open)
    with pytest.raises(RecoveryPartialFailure) as exc:
        _read_bounded_bytes(tmp_path / "missing.dump", cap=64, label="archive")
    assert exc.value.reason_code == "POSTGRESQL_ARCHIVE_OPEN_FAILED"
    assert "No such file" not in str(exc.value)


def test_bounded_read_open_failure_is_typed_redacted_fd_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def explode_open(*_a, **_k):
        raise OSError("secret open detail")

    monkeypatch.setattr(os, "open", explode_open)
    before = _count_open_fds()
    with pytest.raises(RecoveryPartialFailure) as exc:
        _read_bounded_bytes(tmp_path / "nope.dump", cap=64, label="archive")
    assert exc.value.reason_code == "POSTGRESQL_ARCHIVE_OPEN_FAILED"
    assert "secret" not in str(exc.value)
    assert str(exc.value.__cause__) == "None"
    assert _count_open_fds() == before


def test_bounded_read_fstat_failure_is_typed_redacted_fd_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An fstat failure closes the descriptor and raises a typed failure."""
    path = tmp_path / "statfail.dump"
    _write_private(path, b"data")

    def failing_fstat(_fd):
        raise OSError("secret fstat detail")

    monkeypatch.setattr(os, "fstat", failing_fstat)
    before = _count_open_fds()
    with pytest.raises(RecoveryPartialFailure) as exc:
        _read_bounded_bytes(path, cap=100, label="archive")
    assert exc.value.reason_code == "POSTGRESQL_ARCHIVE_STAT_FAILED"
    assert "secret" not in str(exc.value)
    assert _count_open_fds() == before


def test_bounded_read_error_is_typed_redacted_fd_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A read error after open closes the descriptor and raises a typed failure,
    never a raw OSError (source-text-avoidant: assert on the reason code)."""
    path = tmp_path / "readfail.dump"
    _write_private(path, b"data")

    def explode_read(_fd, _size):
        raise OSError("secret read detail")

    monkeypatch.setattr(os, "read", explode_read)
    before = _count_open_fds()
    with pytest.raises(RecoveryPartialFailure) as exc:
        _read_bounded_bytes(path, cap=100, label="archive")
    assert exc.value.reason_code == "POSTGRESQL_ARCHIVE_READ_FAILED"
    assert "secret" not in str(exc.value)
    assert _count_open_fds() == before


# ---------------------------------------------------------------------------
# _run_pg_tool output budgets
# ---------------------------------------------------------------------------

class _FakeProcess:
    def __init__(self, *, returncode: int | None) -> None:
        self.pid = 424242
        self.returncode = returncode
        self.killed = False
        self.wait_calls: list[float] = []
        self.closed = False
        self.read_sizes: list[int] = []
        read_fd, self._write_fd = os.pipe()
        self.stdout = os.fdopen(read_fd, "rb")
        # Record every read1 request size (never <= 0, never unbounded).
        real_read1 = self.stdout.read1

        def record_read1(size: int = -1) -> bytes:
            self.read_sizes.append(size)
            return real_read1(size)

        self.stdout.read1 = record_read1  # type: ignore[method-assign]
        # Record when the stream is closed.
        real_close = self.stdout.close

        def record_close() -> None:
            self.closed = True
            real_close()

        self.stdout.close = record_close  # type: ignore[method-assign]

    def feed(self, payload: bytes) -> None:
        os.write(self._write_fd, payload)
        os.close(self._write_fd)

    def poll(self) -> int | None:
        return self.returncode

    def wait(self, *, timeout: float) -> int:
        self.wait_calls.append(timeout)
        self.returncode = self.returncode if self.returncode is not None else -15
        return self.returncode


def _killpg_recording(monkeypatch: pytest.MonkeyPatch, process: _FakeProcess) -> None:
    """Patch os.killpg to record that the child-group was signaled without
    actually signaling a (nonexistent) PID, so the drain's kill path is proven."""
    def spy_killpg(_pid, _sig) -> None:
        process.killed = True

    monkeypatch.setattr(os, "killpg", spy_killpg)


def test_pg_tool_output_exact_budget_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Exact len(payload)==budget, drained even after the child already exited,
    with every read1 request bounded (0 < size <= budget+1)."""
    payload = b"v" * 100
    process = _FakeProcess(returncode=0)  # child already exited
    os.write(process._write_fd, payload)
    os.close(process._write_fd)
    monkeypatch.setattr(
        "app.backup.postgresql_driver.subprocess.Popen",
        lambda *_args, **_kwargs: process,
    )
    out = _run_pg_tool(
        (str(PG_DUMP_PATH), "--version"),
        environment={"LANG": "C", "LC_ALL": "C", "TZ": "UTC"},
        phase="unit-version",
        timeout_seconds=1,
        output_budget=100,
    )
    assert out == payload
    assert len(out) == 100
    # Every read1 request is fixed, positive, and never unbounded: bounded by
    # min(_OUTPUT_READ_CHUNK, budget + 1 - already_read) so it never overruns.
    assert process.read_sizes
    assert all(0 < size <= min(_OUTPUT_READ_CHUNK, 100 + 1) for size in process.read_sizes)
    # The child already exited, so it is not killed; stdout is closed exactly once.
    assert not process.killed
    assert process.closed


def test_pg_tool_output_budget_overflow_fails_redacted(monkeypatch: pytest.MonkeyPatch) -> None:
    """cap+1 provokes a child-process-group kill (killpg) and wait, then a stable
    redacted typed failure with killpg/wait proof."""
    process = _FakeProcess(returncode=0)
    _killpg_recording(monkeypatch, process)
    os.write(process._write_fd, b"x" * 101)
    os.close(process._write_fd)
    monkeypatch.setattr(
        "app.backup.postgresql_driver.subprocess.Popen",
        lambda *_args, **_kwargs: process,
    )
    with pytest.raises(RecoveryPartialFailure) as exc:
        _run_pg_tool(
            (str(PG_RESTORE_PATH), "--version"),
            environment={"LANG": "C", "LC_ALL": "C", "TZ": "UTC"},
            phase="zone-overflow",
            timeout_seconds=1,
            output_budget=100,
        )
    assert exc.value.reason_code == "POSTGRESQL_TOOL_OUTPUT_BUDGET_EXCEEDED"
    assert "very-secret" not in str(exc.value)
    assert "postgresql://" not in str(exc.value)
    assert exc.value.__cause__ is None
    # killpg targeted the isolated child group and wait was invoked.
    assert process.killed
    assert process.wait_calls
    assert process.closed


def test_pg_tool_zero_output_budget_rejects_one_byte(monkeypatch: pytest.MonkeyPatch) -> None:
    """A true zero budget rejects the very first stdout byte."""
    process = _FakeProcess(returncode=0)
    _killpg_recording(monkeypatch, process)
    os.write(process._write_fd, b"a")
    os.close(process._write_fd)
    monkeypatch.setattr(
        "app.backup.postgresql_driver.subprocess.Popen",
        lambda *_args, **_kwargs: process,
    )
    with pytest.raises(RecoveryPartialFailure, match="OUTPUT_BUDGET"):
        _run_pg_tool(
            (str(PG_DUMP_PATH), "--version"),
            environment={"LANG": "C", "LC_ALL": "C", "TZ": "UTC"},
            phase="zone-zero",
            timeout_seconds=1,
            output_budget=_ZERO_OUTPUT_BUDGET,
        )
    # The first byte triggers an immediate fail-closed kill and wait.
    assert process.killed
    assert process.wait_calls
    assert process.closed


def test_pg_tool_never_calls_communicate(monkeypatch: pytest.MonkeyPatch) -> None:
    process = _FakeProcess(returncode=0)
    process.feed(b"small")

    def explode_communicate(*_a, **_k):
        raise AssertionError("communicate must never be called")

    process.communicate = explode_communicate  # type: ignore[method-assign]
    monkeypatch.setattr(
        "app.backup.postgresql_driver.subprocess.Popen",
        lambda *_args, **_kwargs: process,
    )
    out = _run_pg_tool(
        (str(PG_DUMP_PATH), "--version"),
        environment={"LANG": "C", "LC_ALL": "C", "TZ": "UTC"},
        phase="zone-no-buffer",
        timeout_seconds=1,
        output_budget=100,
    )
    assert out == b"small"
    assert process.closed


def test_pg_tool_negative_budget_rejected() -> None:
    with pytest.raises(RecoveryTargetError, match="budget"):
        _run_pg_tool(
            (str(PG_DUMP_PATH), "--version"),
            environment={"LANG": "C", "LC_ALL": "C", "TZ": "UTC"},
            phase="zone-bad-budget",
            timeout_seconds=1,
            output_budget=-1,
        )


def test_pg_tool_positive_budget_exact_passes_overflow_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """Exact-cap output passes (fully drained after child exit), cap+1 fails
    closed with every read1 request bounded."""
    process = _FakeProcess(returncode=0)
    os.write(process._write_fd, b"y" * 100)
    os.close(process._write_fd)
    monkeypatch.setattr(
        "app.backup.postgresql_driver.subprocess.Popen",
        lambda *_args, **_kwargs: process,
    )
    out = _run_pg_tool(
        (str(PG_DUMP_PATH), "--version"),
        environment={"LANG": "C", "LC_ALL": "C", "TZ": "UTC"},
        phase="zone-positive",
        timeout_seconds=1,
        output_budget=100,
    )
    assert out == b"y" * 100
    assert not process.killed

    # cap+1 fails closed before returning anything, with kill + wait + FD closure.
    process = _FakeProcess(returncode=0)
    _killpg_recording(monkeypatch, process)
    os.write(process._write_fd, b"z" * 101)
    os.close(process._write_fd)
    monkeypatch.setattr(
        "app.backup.postgresql_driver.subprocess.Popen",
        lambda *_args, **_kwargs: process,
    )
    with pytest.raises(RecoveryPartialFailure, match="OUTPUT_BUDGET"):
        _run_pg_tool(
            (str(PG_RESTORE_PATH), "--version"),
            environment={"LANG": "C", "LC_ALL": "C", "TZ": "UTC"},
            phase="zone-cap-plus-one",
            timeout_seconds=1,
            output_budget=100,
        )
    assert process.killed
    assert process.wait_calls
    assert process.closed


def test_pg_tool_drains_stdout_after_child_exits(monkeypatch: pytest.MonkeyPatch) -> None:
    """The child already exited before the final bytes were read; the bounded
    drain must still consume every buffered byte within the budget (neither
    losing trailing output nor bypassing the cap)."""
    payload = b"tail-after-exit"
    process = _FakeProcess(returncode=0)  # child already exited
    os.write(process._write_fd, payload)
    os.close(process._write_fd)
    monkeypatch.setattr(
        "app.backup.postgresql_driver.subprocess.Popen",
        lambda *_args, **_kwargs: process,
    )
    out = _run_pg_tool(
        (str(PG_RESTORE_PATH), "--version"),
        environment={"LANG": "C", "LC_ALL": "C", "TZ": "UTC"},
        phase="zone-drain-exit",
        timeout_seconds=1,
        output_budget=len(payload),
    )
    assert out == payload
    # len==budget exactly; every read1 request is bounded and the stream closed.
    assert len(out) == len(payload)
    assert process.read_sizes
    assert all(0 < size <= _OUTPUT_READ_CHUNK for size in process.read_sizes)
    assert process.closed


def test_pg_tool_partial_output_read_error_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """A stdout read error after partial output must fail closed, never return
    the truncated output as success."""
    process = _FakeProcess(returncode=0)
    os.write(process._write_fd, b"partial")
    os.close(process._write_fd)

    served = [b"data"]  # one partial chunk, then a read error

    def flaky_read1(size: int = -1) -> bytes:
        if served:
            return served.pop(0)  # serve exactly "data" then fail next time
        raise OSError("simulated stdout read failure after partial output")

    process.stdout.read1 = flaky_read1  # type: ignore[method-assign]
    monkeypatch.setattr(
        "app.backup.postgresql_driver.subprocess.Popen",
        lambda *_args, **_kwargs: process,
    )
    with pytest.raises(RecoveryPartialFailure, match="RUNTIME_FAILED"):
        _run_pg_tool(
            (str(PG_DUMP_PATH), "--version"),
            environment={"LANG": "C", "LC_ALL": "C", "TZ": "UTC"},
            phase="zone-partial-read-error",
            timeout_seconds=1,
            output_budget=100,
        )


def test_pg_tool_select_failure_fails_closed_with_kill_wait_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A select.select OSError/ValueError must terminate the child group, wait,
    close stdout, and raise a stable redacted POSTGRESQL_TOOL_RUNTIME_FAILED
    with no raw cause retained."""
    process = _FakeProcess(returncode=0)
    _killpg_recording(monkeypatch, process)
    os.write(process._write_fd, b"data")  # some stdout exists but select fails
    os.close(process._write_fd)

    def explode_select(_a, _b, _c, _timeout):
        raise OSError("simulated select failure")

    monkeypatch.setattr(postgresql_driver.select, "select", explode_select)
    monkeypatch.setattr(
        "app.backup.postgresql_driver.subprocess.Popen",
        lambda *_args, **_kwargs: process,
    )
    with pytest.raises(RecoveryPartialFailure) as exc:
        _run_pg_tool(
            (str(PG_DUMP_PATH), "--version"),
            environment={"LANG": "C", "LC_ALL": "C", "TZ": "UTC"},
            phase="zone-select-error",
            timeout_seconds=1,
            output_budget=100,
        )
    assert exc.value.reason_code == "POSTGRESQL_TOOL_RUNTIME_FAILED"
    assert exc.value.__cause__ is None
    assert "simulated select failure" not in str(exc.value)
    assert "very-secret" not in str(exc.value)
    # The polling failure fails closed exactly like a read failure: kill the
    # isolated child group, wait for it, and close stdout.
    assert process.killed
    assert process.wait_calls
    assert process.closed


# ---------------------------------------------------------------------------
# Per-call output budget wiring
# ---------------------------------------------------------------------------

def test_production_calls_bytes_use_per_invocation_budgets() -> None:
    assert _TOOL_VERSION_OUTPUT_BUDGET > 0
    assert _ARCHIVE_TOC_OUTPUT_BUDGET > 0
    assert _SCHEMA_ONLY_OUTPUT_BUDGET > 0
    assert _ZERO_OUTPUT_BUDGET == 0  # true zero: any byte is an overflow
    assert _OUTPUT_READ_CHUNK > 0
    assert _ZERO_OUTPUT_BUDGET < _TOOL_VERSION_OUTPUT_BUDGET
    assert _TOOL_VERSION_OUTPUT_BUDGET < _ARCHIVE_TOC_OUTPUT_BUDGET


# ---------------------------------------------------------------------------
# TOC entry bound
# ---------------------------------------------------------------------------

def _toc_lines(*lines: str) -> bytes:
    return "\n".join(("; header", *lines, "")).encode()


def _toc_denominator() -> tuple[str, ...]:
    return (
        "6; 2615 2200 SCHEMA - public pg_database_owner",
        "215; 1259 18001 TABLE public alembic_version source_owner",
        "4210; 0 18001 TABLE DATA public alembic_version source_owner",
    )


def test_toc_exact_entry_bound_passes() -> None:
    """Exactly _TOC_ENTRY_BOUND total splitlines (with the required schema /
    table / table-data denominator) passes the entry bound and still filters."""
    denominator = _toc_denominator()
    # 3 valid denominator lines + (bound - 4) comment-only filler lines =>
    # (bound-4)+1 header + 3 denominator = bound splitlines total.
    filler = ["; comment line"] * (_TOC_ENTRY_BOUND - 4)
    lines = [*denominator, *filler]
    raw = _toc_lines(*lines)
    assert len(raw.decode("utf-8").splitlines()) == _TOC_ENTRY_BOUND
    filtered = _filter_public_schema_toc(raw)
    # The public SCHEMA create entry was omitted; the table denominator remains.
    assert b"SCHEMA public" not in filtered
    assert b"TABLE public alembic_version" in filtered


def test_toc_entry_bound_plus_one_fails_closed() -> None:
    # One extra splitline over the bound must fail closed.
    filler = ["; comment line"] * (_TOC_ENTRY_BOUND - 3)  # 4097 total splitlines
    lines = list(_toc_denominator()) + filler
    raw = _toc_lines(*lines)
    assert len(raw.decode("utf-8").splitlines()) == _TOC_ENTRY_BOUND + 1
    with pytest.raises(UnsupportedRecoveryArtifact, match="entry bound"):
        _filter_public_schema_toc(raw)


# ---------------------------------------------------------------------------
# Database-size budget
# ---------------------------------------------------------------------------

class _FakeConnection:
    def __init__(self, value: int) -> None:
        self._value = value

    def execute(self, _sql: str):
        class _Result:
            def __init__(self, value):
                self._v = value

            def fetchone(self):
                return (self._v,)

        return _Result(self._value)

    def close(self) -> None:
        return None


def test_database_size_budget_exact_cap_passes() -> None:
    _assert_database_size_budget(
        _FakeConnection(_MAX_DATABASE_SIZE_BYTES), label="source"
    )


def test_database_size_budget_cap_plus_one_fails_closed() -> None:
    with pytest.raises(RecoveryPartialFailure, match="DATABASE_SIZE_BUDGET"):
        _assert_database_size_budget(
            _FakeConnection(_MAX_DATABASE_SIZE_BYTES + 1), label="source"
        )


def test_database_size_budget_negative_fails_closed() -> None:
    with pytest.raises(RecoveryIntegrityError, match="malformed"):
        _assert_database_size_budget(_FakeConnection(-1), label="source")


def test_database_size_budget_non_int_fails_closed() -> None:
    with pytest.raises(RecoveryIntegrityError, match="malformed"):
        _assert_database_size_budget(_FakeConnection("big"), label="source")

# ---------------------------------------------------------------------------
# Archive cap ordering: rejected before any write or tool call
# (monkeypatched 64-byte cap -- no over-1-GiB allocation in fixtures)
# ---------------------------------------------------------------------------

def _exact_cap_artifact(small_cap: int) -> RelationalBackupArtifact:
    """An archive whose total raw length (5-byte PGDMP header + payload) is
    EXACTLY the documented cap.  len(raw_bytes) == cap passes; cap+1 fails."""
    header_len = len(b"PGDMP")
    return _artifact(b"e" * (small_cap - header_len))


def test_archive_toc_enforces_cap_before_write(
    tmp_path: Path,
    driver: PostgreSQLBackupRestoreDriver,
    small_cap: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An over-cap archive must fail closed inside _archive_toc BEFORE the
    private archive byte write lands and BEFORE any pg_tool invocation."""
    mod = postgresql_driver
    written: list[Path] = []
    tool_run: list[tuple] = []
    real_private_write = mod._private_write
    original_run_pg_tool = mod._run_pg_tool

    def guard_write(path: Path, raw: bytes) -> None:
        written.append(path)
        real_private_write(path, raw)

    def guard_run_pg_tool(*a, **k):
        tool_run.append(a)
        return original_run_pg_tool(*a, **k)

    monkeypatch.setattr(mod, "_private_write", guard_write)
    monkeypatch.setattr(mod, "_run_pg_tool", guard_run_pg_tool)
    # cap+1 total length: header (5) + (cap+1-5) payload bytes == cap+1 total.
    payload = b"x" * (small_cap + 1 - len(b"PGDMP"))
    over_cap = _artifact(payload)
    assert len(over_cap.raw_bytes) == small_cap + 1
    with pytest.raises(RecoveryIntegrityError, match="archive byte cap"):
        driver._archive_toc(
            over_cap,
            temporary_root=tmp_path,
            cancel_requested=None,
            target_created=False,
        )
    # cap+1 reaches neither the private write nor the pg_tool call.
    assert written == []
    assert tool_run == []


def test_write_archive_bytes_exact_cap_passes_overflow_rejected(
    tmp_path: Path, small_cap: int
) -> None:
    """The executable _write_archive_bytes path accepts an exact-cap archive and
    persists it privately, and rejects cap+1 BEFORE the write."""
    exact = _exact_cap_artifact(small_cap)
    path = _write_archive_bytes(tmp_path / "relational-backup.dump", exact)
    assert path.read_bytes() == exact.raw_bytes

    over = _artifact(b"y" * (small_cap + 1 - len(b"PGDMP")))
    target = tmp_path / "relational-backup-over.dump"
    with pytest.raises(RecoveryIntegrityError, match="archive byte cap"):
        _write_archive_bytes(target, over)
    assert not target.exists()


def test_require_artifact_rejects_over_cap_before_mutation(
    driver: PostgreSQLBackupRestoreDriver, small_cap: int
) -> None:
    over_cap = _artifact(b"y" * (small_cap + 1 - len(b"PGDMP")))
    with pytest.raises(RecoveryIntegrityError, match="archive byte cap"):
        driver._require_artifact(over_cap)


def test_require_artifact_exact_cap_passes_before_write(
    driver: PostgreSQLBackupRestoreDriver, small_cap: int
) -> None:
    """The exact-cap archive passes _require_artifact; only the metadata/header
    guards fire.  (Load-bearing: a too-small cap would reject the exact file.)"""
    driver._require_artifact(_exact_cap_artifact(small_cap))


# BaseException-driven mutation: removing any single guard must fail a test.
def test_archive_cap_mutation_fails_closed(
    tmp_path: Path,
    driver: PostgreSQLBackupRestoreDriver,
    small_cap: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod = postgresql_driver
    calls: list[str] = []
    real_require = driver._require_artifact

    def spy_require(*a, **k):
        calls.append("require")
        return real_require(*a, **k)

    monkeypatch.setattr(driver, "_require_artifact", spy_require)
    # If the cap check were removed, an over-cap archive would reach the
    # private write; guard the write to prove it never happens.
    wrote: list[Path] = []

    real_private_write = mod._private_write

    def guard_write(path: Path, raw: bytes) -> None:
        wrote.append(path)
        real_private_write(path, raw)

    monkeypatch.setattr(mod, "_private_write", guard_write)
    over_cap = _artifact(b"y" * (small_cap + 1 - len(b"PGDMP")))
    with pytest.raises(RecoveryIntegrityError):
        driver._require_artifact(over_cap)
    # The cap check must fire before any write is reached.
    assert wrote == []
    assert calls == ["require"]


def test_archive_cap_is_checked_in_require_before_write(
    driver: PostgreSQLBackupRestoreDriver, small_cap: int
) -> None:
    """A removed cap guard in _require_artifact must cause this test to fail
    (mutation proof): the over-cap archive is rejected there."""
    over_cap = _artifact(b"\x00" * (small_cap + 1 - len(b"PGDMP")))
    with pytest.raises(RecoveryIntegrityError, match="archive byte cap"):
        driver._require_artifact(over_cap)


# ---------------------------------------------------------------------------
# Database-size budget ordering (source / target / inspection) -- F9 C
# Sentinel-based: stop before the complex dependency graph.
# ---------------------------------------------------------------------------

class _ReachedSentinel(Exception):
    """Raised by a patched downstream function to prove the guarded step was
    reached (and only reached on the exact-cap path)."""


class _FakeSpec:
    database = "ledger"
    user = "ledger"
    host = "/tmp"
    port = 5432

    def libpq_environment(self, *, application_name: str) -> dict[str, str]:
        return {"PGAPPNAME": application_name, "LANG": "C", "TZ": "UTC"}


def _fake_connection(value: int) -> _FakeConnection:
    return _FakeConnection(value)


def _patch_ambient(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(postgresql_driver, "_assert_no_ambient_libpq_environment", lambda: None)


def test_create_backup_source_size_budget_before_pg_dump(
    driver: PostgreSQLBackupRestoreDriver, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Source cap+1 fails BEFORE _private_write and pg_dump; exact cap reaches
    the pg_dump sentinel, proving the budget check precedes materialization."""
    spec = _FakeSpec()
    monkeypatch.setattr(postgresql_driver, "_coerce_connection_spec", lambda _v, *, role: spec)
    _patch_ambient(monkeypatch)
    monkeypatch.setattr(driver, "_current_tool_version", lambda: "16.10")
    facts = SimpleNamespace(engine_version="16.10", identity_sha256="b" * 64)
    monkeypatch.setattr(
        postgresql_driver, "_read_database_facts", lambda _s, **_: facts
    )
    monkeypatch.setattr(postgresql_driver, "_assert_safe_backup_source_scope", lambda _f: None)
    monkeypatch.setattr(postgresql_driver, "_strict_current_head", lambda _s: None)
    monkeypatch.setattr(postgresql_driver, "_strict_public_object_denominator", lambda _a, **_: None)
    # Cancel the durable body: _run_pg_tool (pg_dump) becomes a sentinel.
    dump_calls: list[int] = []

    def reached_pg_dump(*_a, **_k):
        dump_calls.append(1)
        raise _ReachedSentinel()

    monkeypatch.setattr(postgresql_driver, "_run_pg_tool", reached_pg_dump)
    private_writes: list[Path] = []
    real_private_write = postgresql_driver._private_write

    def guard_write(path: Path, raw: bytes) -> None:
        private_writes.append(path)
        real_private_write(path, raw)

    monkeypatch.setattr(postgresql_driver, "_private_write", guard_write)

    # cap+1 at the source: the budget fails before any write or pg_dump launch.
    monkeypatch.setattr(
        postgresql_driver, "_open_connection",
        lambda _s, **_: _fake_connection(_MAX_DATABASE_SIZE_BYTES + 1),
    )
    with pytest.raises(RecoveryPartialFailure) as exc:
        driver.create_backup(spec)
    assert exc.value.reason_code == "POSTGRESQL_DATABASE_SIZE_BUDGET_EXCEEDED"
    assert exc.value.phase == "postgresql_database_size_budget"
    assert exc.value.relational_target_created is False
    assert private_writes == []
    assert dump_calls == []

    # exact cap reaches the pg_dump sentinel (and thus a private write happens
    # first), proving the check is ordered before materialization.
    monkeypatch.setattr(
        postgresql_driver, "_open_connection",
        lambda _s, **_: _fake_connection(_MAX_DATABASE_SIZE_BYTES),
    )
    private_writes.clear()
    dump_calls.clear()
    with pytest.raises(_ReachedSentinel):
        driver.create_backup(spec)
    assert private_writes  # pg_dump's private archive file was created
    assert dump_calls


def test_restore_and_inspect_target_size_budget_before_archive_toc(
    driver: PostgreSQLBackupRestoreDriver, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Restore-target cap+1 stops BEFORE _archive_toc / pg_restore and reports
    target_created=True with the target-specific phase; exact cap reaches the
    _archive_toc sentinel."""
    spec = _FakeSpec()
    artifact = _artifact()
    monkeypatch.setattr(postgresql_driver, "_coerce_connection_spec", lambda _v, *, role: spec)
    _patch_ambient(monkeypatch)
    monkeypatch.setattr(driver, "_require_artifact", lambda _a: None)
    monkeypatch.setattr(
        postgresql_driver,
        "_consume_fresh_target",
        lambda _s, **_: (
            SimpleNamespace(identity_sha256="b" * 64, database_scope_sha256="c" * 64),
            "marker",
        ),
    )
    archive_toc_calls: list[int] = []

    def reached_archive_toc(*_a, **_k):
        archive_toc_calls.append(1)
        raise _ReachedSentinel()

    monkeypatch.setattr(driver, "_archive_toc", reached_archive_toc)

    # cap+1 at the restore target: fails closed, target_created=True, right phase.
    monkeypatch.setattr(
        postgresql_driver, "_open_connection",
        lambda _s, **_: _fake_connection(_MAX_DATABASE_SIZE_BYTES + 1),
    )
    with pytest.raises(RecoveryPartialFailure) as exc:
        driver._restore_and_inspect(
            artifact, spec, target_id="target-0001", cancel_requested=None
        )
    assert exc.value.reason_code == "POSTGRESQL_DATABASE_SIZE_BUDGET_EXCEEDED"
    assert exc.value.relational_target_created is True
    assert exc.value.phase == "postgresql_restore_size_budget"
    assert archive_toc_calls == []

    # exact cap reaches the _archive_toc sentinel.
    monkeypatch.setattr(
        postgresql_driver, "_open_connection",
        lambda _s, **_: _fake_connection(_MAX_DATABASE_SIZE_BYTES),
    )
    archive_toc_calls.clear()
    with pytest.raises(_ReachedSentinel):
        driver._restore_and_inspect(
            artifact, spec, target_id="target-0001", cancel_requested=None
        )
    assert archive_toc_calls


def test_inspect_restored_target_size_budget_before_strict_head(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Post-restore inspection cap+1 stops BEFORE _strict_current_head (and so
    before _rows_by_table / _schema_sha256) and reports target_created=True with
    the inspection phase; exact cap reaches the _strict_current_head sentinel."""
    spec = _FakeSpec()
    artifact = _artifact()
    monkeypatch.setattr(postgresql_driver, "_assert_target_marker", lambda *_a, **_k: None)
    strict_head_calls: list[int] = []

    def reached_strict_head(_s):
        strict_head_calls.append(1)
        raise _ReachedSentinel()

    monkeypatch.setattr(postgresql_driver, "_strict_current_head", reached_strict_head)
    # rows_by_table and schema_sha256 must not run before the budget check;
    # spy them so a removed guard is caught (they would be reached first).
    rows_calls: list[int] = []
    schema_calls: list[int] = []

    def spy_rows(_s):
        rows_calls.append(1)
        raise _ReachedSentinel()

    def spy_schema(*_a, **_k):
        schema_calls.append(1)
        raise _ReachedSentinel()

    monkeypatch.setattr(postgresql_driver, "_rows_by_table", spy_rows)
    monkeypatch.setattr(postgresql_driver, "_schema_sha256", spy_schema)

    kw = dict(
        artifact=artifact,
        target_identity_sha256="b" * 64,
        target_marker="marker",
        target_database_scope_sha256="c" * 64,
        tool_version="16.10",
        timeout_seconds=30.0,
        cancel_requested=None,
    )

    # cap+1 at inspection: fails before strict-current-head, rows, schema.
    monkeypatch.setattr(
        postgresql_driver, "_open_connection",
        lambda _s, **_: _fake_connection(_MAX_DATABASE_SIZE_BYTES + 1),
    )
    with pytest.raises(RecoveryPartialFailure) as exc:
        postgresql_driver._inspect_restored_target(spec, **kw)
    assert exc.value.reason_code == "POSTGRESQL_DATABASE_SIZE_BUDGET_EXCEEDED"
    assert exc.value.relational_target_created is True
    assert exc.value.phase == "postgresql_inspection_size_budget"
    assert strict_head_calls == []
    assert rows_calls == []
    assert schema_calls == []

    # exact cap reaches the strict-head sentinel first (rows/schema never run).
    monkeypatch.setattr(
        postgresql_driver, "_open_connection",
        lambda _s, **_: _fake_connection(_MAX_DATABASE_SIZE_BYTES),
    )
    strict_head_calls.clear()
    rows_calls.clear()
    schema_calls.clear()
    with pytest.raises(_ReachedSentinel):
        postgresql_driver._inspect_restored_target(spec, **kw)
    assert strict_head_calls


# ---------------------------------------------------------------------------
# Caller-budget wiring (F9 D): each production call site passes the intended
# documented output budget.  Fake-only, no source-text assertions.
# ---------------------------------------------------------------------------

_VALID_TOC = (
    "; header\n"
    "6; 2615 2200 SCHEMA - public pg_database_owner\n"
    "215; 1259 18001 TABLE public alembic_version source_owner\n"
    "4210; 0 18001 TABLE DATA public alembic_version source_owner\n"
).encode()


def _recording_tool(monkeypatch: pytest.MonkeyPatch, *, output: bytes) -> dict:
    """Patch _run_pg_tool to record every call's kwargs (incl output_budget and
    argv phase) and return ``output``; returns the recorded-call dict."""
    calls: dict[str, list] = {"argv": [], "phase": [], "budget": []}

    def rec(command, **kwargs):
        calls["argv"].append(tuple(command))
        calls["phase"].append(kwargs.get("phase"))
        calls["budget"].append(kwargs.get("output_budget"))
        return output

    monkeypatch.setattr(postgresql_driver, "_run_pg_tool", rec)
    return calls


def test_parse_tool_version_captures_version_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_parse_tool_version runs --version through _run_pg_tool with the
    documented tool-version output budget."""
    monkeypatch.setattr(postgresql_driver, "_require_tool_binary", lambda _p: None)
    calls = _recording_tool(
        monkeypatch, output=b"pg_dump (PostgreSQL) 16.10\n"
    )
    version = _parse_tool_version(Path("/usr/lib/postgresql/16/bin/pg_dump"), timeout_seconds=30.0)
    assert version == "16.10"
    assert calls["budget"] == [_TOOL_VERSION_OUTPUT_BUDGET]
    assert calls["phase"] == ["postgresql_tool_version"]
    assert all(str(PG_DUMP_PATH) in argv or str(PG_RESTORE_PATH) in argv for argv in calls["argv"])


def test_archive_toc_captures_toc_budget_with_fake_toc(
    driver: PostgreSQLBackupRestoreDriver, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """driver._archive_toc passes _ARCHIVE_TOC_OUTPUT_BUDGET to the --list tool
    and (with a fake valid TOC returned) produces a bounded archive + TOC."""
    monkeypatch.setattr(driver, "_require_artifact", lambda _a: None)
    calls = _recording_tool(monkeypatch, output=_VALID_TOC)
    toc_writes: list[bytes] = []
    monkeypatch.setattr(
        postgresql_driver, "_write_archive_toc",
        lambda path, payload: toc_writes.append(payload),
    )
    driver._archive_toc(
        _artifact(),
        temporary_root=tmp_path,
        cancel_requested=None,
        target_created=False,
    )
    assert calls["budget"] == [_ARCHIVE_TOC_OUTPUT_BUDGET]
    assert calls["phase"] == ["postgresql_archive_list"]
    assert "--list" in calls["argv"][0]
    # a fake valid TOC was filtered (public-SCHEMA entry omitted) and written
    # bounded to the archive TOC path.
    expected_filtered = (
        "; header\n"
        "215; 1259 18001 TABLE public alembic_version source_owner\n"
        "4210; 0 18001 TABLE DATA public alembic_version source_owner\n"
    ).encode()
    assert toc_writes == [expected_filtered]


def test_schema_sha256_captures_schema_only_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_schema_sha256 captures _SCHEMA_ONLY_OUTPUT_BUDGET with fake valid
    restrict/unrestrict output (never touching a live schema dump)."""
    spec = _FakeSpec()
    monkeypatch.setattr(
        postgresql_driver, "_toolchain_version", lambda **_: "16.10"
    )
    schema_out = b"\\restrict same-nonce-1\nCREATE TABLE x ();\n\\unrestrict same-nonce-1\n"
    calls = _recording_tool(monkeypatch, output=schema_out)
    result = _schema_sha256(
        spec,
        tool_version="16.10",
        timeout_seconds=30.0,
        cancel_requested=None,
    )
    assert calls["budget"] == [_SCHEMA_ONLY_OUTPUT_BUDGET]
    assert calls["phase"] == ["postgresql_schema_digest"]
    assert calls["argv"][0][0] == str(PG_DUMP_PATH)
    assert result  # a real sha256 hash was produced from the fake output




def test_create_backup_pg_dump_uses_zero_output_budget(
    driver: PostgreSQLBackupRestoreDriver, monkeypatch: pytest.MonkeyPatch
) -> None:
    """create_backup runs pg_dump through _run_pg_tool with _ZERO_OUTPUT_BUDGET
    (true zero: any pg_dump stdout is an overflow) after the source budget."""
    spec = _FakeSpec()
    monkeypatch.setattr(postgresql_driver, "_coerce_connection_spec", lambda _v, *, role: spec)
    _patch_ambient(monkeypatch)
    monkeypatch.setattr(driver, "_current_tool_version", lambda: "16.10")
    facts = SimpleNamespace(engine_version="16.10", identity_sha256="b" * 64)
    monkeypatch.setattr(
        postgresql_driver, "_read_database_facts", lambda _s, **_: facts
    )
    monkeypatch.setattr(postgresql_driver, "_assert_safe_backup_source_scope", lambda _f: None)
    monkeypatch.setattr(postgresql_driver, "_strict_current_head", lambda _s: None)
    monkeypatch.setattr(postgresql_driver, "_strict_public_object_denominator", lambda _a, **_: None)
    monkeypatch.setattr(
        postgresql_driver, "_open_connection",
        lambda _s, **_: _fake_connection(_MAX_DATABASE_SIZE_BYTES),
    )
    pg_dump_args: list[tuple] = []
    pg_dump_budgets: list = []
    pg_dump_phases: list = []

    def capture_pg_dump(command, **kwargs):
        pg_dump_args.append(tuple(command))
        pg_dump_budgets.append(kwargs.get("output_budget"))
        pg_dump_phases.append(kwargs.get("phase"))
        raise _ReachedSentinel()

    monkeypatch.setattr(postgresql_driver, "_run_pg_tool", capture_pg_dump)
    # The very first _run_pg_tool call in create_backup IS pg_dump, reached only
    # after the source size-budget passes: capture its documented zero budget.
    with pytest.raises(_ReachedSentinel):
        driver.create_backup(spec)
    assert pg_dump_args
    assert str(pg_dump_args[0][0]).endswith("pg_dump")
    assert pg_dump_budgets == [_ZERO_OUTPUT_BUDGET]
    assert pg_dump_phases == ["postgresql_relational_backup"]


def test_restore_and_inspect_pg_restore_uses_zero_output_budget(
    driver: PostgreSQLBackupRestoreDriver, monkeypatch: pytest.MonkeyPatch
) -> None:
    """_restore_and_inspect runs pg_restore (--use-list) through _run_pg_tool
    with _ZERO_OUTPUT_BUDGET after a fake _archive_toc return."""
    spec = _FakeSpec()
    artifact = _artifact()
    monkeypatch.setattr(postgresql_driver, "_coerce_connection_spec", lambda _v, *, role: spec)
    _patch_ambient(monkeypatch)
    monkeypatch.setattr(driver, "_require_artifact", lambda _a: None)
    monkeypatch.setattr(
        postgresql_driver, "_consume_fresh_target",
        lambda _s, **_: (
            SimpleNamespace(identity_sha256="b" * 64, database_scope_sha256="c" * 64),
            "marker",
        ),
    )
    monkeypatch.setattr(
        postgresql_driver, "_open_connection",
        lambda _s, **_: _fake_connection(_MAX_DATABASE_SIZE_BYTES),
    )
    # fake _archive_toc returns Paths; pg_restore runs next with zero budget.
    monkeypatch.setattr(
        driver, "_archive_toc",
        lambda self, **_: (Path("/tmp/a.dump"), Path("/tmp/a.list")),
    )
    monkeypatch.setattr(postgresql_driver, "_assert_target_marker", lambda *_a, **_k: None)
    monkeypatch.setattr(postgresql_driver, "_apply_restore_safety_floor", lambda *_a, **_k: None)
    pg_restore_args: list[tuple] = []
    pg_restore_budgets: list = []
    pg_restore_phases: list = []

    def capture_pg_restore(command, **kwargs):
        pg_restore_args.append(tuple(command))
        pg_restore_budgets.append(kwargs.get("output_budget"))
        pg_restore_phases.append(kwargs.get("phase"))
        raise _ReachedSentinel()

    monkeypatch.setattr(postgresql_driver, "_run_pg_tool", capture_pg_restore)
    # The first _run_pg_tool call after the size budget + archive_toc IS
    # pg_restore; capturing it proves the restored archive uses a zero budget.
    with pytest.raises(_ReachedSentinel):
        driver._restore_and_inspect(
            artifact, spec, target_id="target-0001", cancel_requested=None
        )
    assert pg_restore_args
    assert str(pg_restore_args[0][0]).endswith("pg_restore")
    assert pg_restore_budgets == [_ZERO_OUTPUT_BUDGET]
    assert pg_restore_phases == ["postgresql_relational_restore"]
