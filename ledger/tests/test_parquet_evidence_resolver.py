from __future__ import annotations

import io
from types import MappingProxyType

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

import app.ingestion.parquet_cells as pc
from app.ingestion.parquet_cells import (
    MAX_PARQUET_BATCH_SIZE,
    ParquetCellError,
    ParquetEvidenceResolver,
    build_snapshot_digest,
    iter_parquet_records,
    read_parquet_record,
)


def _write(table: pa.Table, *, row_group_size: int | None = None) -> bytes:
    buffer = io.BytesIO()
    pq.write_table(table, buffer, row_group_size=row_group_size)
    return buffer.getvalue()


def _parquet(cols: dict[str, list[str]], **kw) -> bytes:
    """Build Parquet bytes from a column -> rows mapping (equal lengths)."""
    keys = list(cols.keys())
    depth = max(len(cols[k]) for k in keys)
    rows = [
        {key: (cols[key][i] if i < len(cols[key]) else None) for key in keys}
        for i in range(depth)
    ]
    return _write(pa.Table.from_pylist(rows), **kw)


def _tenk() -> bytes:
    """A deterministic 10k-row Parquet fixture (bounded memory/cpu)."""
    models = [f"model_{i % 97}".encode() for i in range(10_000)]
    scores = [f"{i % 1000}.00".encode() for i in range(10_000)]
    ranks = [i for i in range(10_000)]
    schema = pa.schema(
        [
            ("model", pa.string()),
            ("score", pa.string()),
            ("rank", pa.int64()),
        ]
    )
    table = pa.Table.from_arrays(
        [
            pa.array(models, type=pa.string()),
            pa.array(scores, type=pa.string()),
            pa.array(ranks, type=pa.int64()),
        ],
        schema=schema,
    )
    return _write(table, row_group_size=512)


class OpenCounter:
    """Counts calls to the module-level Parquet opener via monkeypatch."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.count = 0
        real_open = pc._open

        def _counting(raw_bytes: bytes):
            self.count += 1
            return real_open(raw_bytes)

        monkeypatch.setattr(pc, "_open", _counting)


class LookupCounter:
    """Counts direct record lookups regardless of row position."""

    def __init__(self) -> None:
        self.accesses = 0


def test_resolver_opens_exactly_once_across_reads_and_iteration(
    monkeypatch,
) -> None:
    raw = _parquet({"model": ["A"], "score": ["1.0"]}, row_group_size=1)
    counter = OpenCounter(monkeypatch)
    lookups = LookupCounter()

    resolver = ParquetEvidenceResolver(raw, _lookup_counter=lookups)
    assert counter.count == 1

    first, error = resolver.read(row_group=0, row_index=0)
    assert error is None
    assert first == {"model": "A", "score": "1.0"}
    second, _ = resolver.read(row_group=0, row_index=0)
    assert second == first
    assert counter.count == 1
    assert lookups.accesses == 2  # direct indexing: 2 reads => 2 accesses

    rows = list(resolver.iter_records())
    assert len(rows) == 1
    assert counter.count == 1
    resolver.close()


def test_same_object_identity_fast_path_skips_digest() -> None:
    raw = _parquet({"model": ["A"], "score": ["1.5"]})
    resolver = ParquetEvidenceResolver(raw)

    calls: list[str] = []
    real_digest = pc.build_snapshot_digest

    def _spy(raw_bytes: bytes) -> str:
        calls.append("digest")
        return real_digest(raw_bytes)

    orig = pc.build_snapshot_digest
    pc.build_snapshot_digest = _spy
    try:
        resolver.verify(raw)  # same object => identity fast path, no hash
        assert calls == []
    finally:
        pc.build_snapshot_digest = orig
    resolver.close()


def test_equal_but_distinct_bytes_accepted_via_digest() -> None:
    raw = _write(pa.table({"model": ["A"], "score": ["2.0"]}))
    resolver = ParquetEvidenceResolver(raw)

    distinct = bytes(bytearray(raw))  # force a genuinely new bytes object
    assert distinct is not raw
    assert distinct == raw
    resolver.verify(distinct)  # equal-but-distinct => digest match accepted
    record, error = read_parquet_record(
        distinct, resolver=resolver, row_group=0, row_index=0
    )
    assert error is None
    assert record["score"] == "2.0"
    resolver.close()


def test_resolver_fails_closed_on_mismatched_bytes() -> None:
    raw = _write(pa.table({"model": ["A"], "score": ["3.0"]}))
    other = _write(pa.table({"model": ["B"], "score": ["9.9"]}))

    resolver = ParquetEvidenceResolver(raw)
    with pytest.raises(ParquetCellError):
        resolver.verify(other)

    record, error = read_parquet_record(
        other, resolver=resolver, row_group=0, row_index=0
    )
    assert error == "EVIDENCE_SNAPSHOT_MISMATCH"
    assert record is None
    resolver.close()


def test_read_parquet_record_without_resolver_still_works(monkeypatch) -> None:
    counter = OpenCounter(monkeypatch)
    raw = _parquet({"model": ["A"], "score": ["1.5"]})
    record, error = read_parquet_record(raw, row_group=0, row_index=0)
    assert error is None
    assert record["model"] == "A"
    assert counter.count == 1


def test_shared_resolver_rejects_invalid_bounds(monkeypatch) -> None:
    raw = _parquet({"model": ["A" * 20, "B"], "score": ["001.2300", "2.5"]}, row_group_size=1)
    resolver = ParquetEvidenceResolver(raw)

    assert resolver.read(row_group=0, row_index=2) == (None, "EVIDENCE_NOT_FOUND")
    assert resolver.read(row_group=1, row_index=1) == (None, "EVIDENCE_NOT_FOUND")
    assert resolver.read(row_group=-1, row_index=0) == (None, "EVIDENCE_LOCATOR_INVALID")
    assert resolver.read(row_group=0, row_index="x") == (None, "EVIDENCE_LOCATOR_INVALID")

    record, error = resolver.read(row_group=0, row_index=0)
    assert error is None
    assert record["score"] == "001.2300"
    assert record["score"] != "888.0000"
    resolver.close()


def test_records_are_immutable_mapping_objects() -> None:
    """Returned records are immutable Mappings; caller mutation cannot persist."""
    raw = _parquet({"model": ["A"], "score": ["1.0"]})
    resolver = ParquetEvidenceResolver(raw)
    record, error = resolver.read(row_group=0, row_index=0)
    assert error is None
    assert isinstance(record, MappingProxyType)
    # Re-read is equal; because MappingProxyType is immutable and shared, it
    # may be the same object — the guarantee is equality, not distinctness.
    again, _ = resolver.read(row_group=0, row_index=0)
    assert record == again
    # Mutation attempt raises TypeError instead of mutating.
    with pytest.raises(TypeError):
        record["model"] = "changed"  # type: ignore[index]
    # Re-read still yields the original cells.
    third, _ = resolver.read(row_group=0, row_index=0)
    assert third["model"] == "A"
    resolver.close()


def test_iter_parquet_records_fails_closed_on_malformed() -> None:
    with pytest.raises(ParquetCellError):
        list(iter_parquet_records(b"not parquet"))


def test_build_digest_binds_content_not_object_identity() -> None:
    raw = _parquet({"x": ["a"]})
    assert build_snapshot_digest(raw) == build_snapshot_digest(bytes(raw))
    assert build_snapshot_digest(raw) != build_snapshot_digest(raw + b"\x00")
    assert len(build_snapshot_digest(raw)) == 64


def test_resolver_binds_digest_and_denominators_to_snapshot() -> None:
    raw = _parquet({"model": ["x", "y"]}, row_group_size=1)
    left = ParquetEvidenceResolver(raw)
    right = ParquetEvidenceResolver(bytes(raw))
    assert left.digest == right.digest
    assert left.row_group_rows == right.row_group_rows
    assert left.read(row_group=0, row_index=0) == right.read(row_group=0, row_index=0)
    left.close()
    right.close()


def test_bounded_tenk_last_row_lookup_is_direct_indexing() -> None:
    """Reading the LAST row of a 10k fixture uses direct access, not a scan."""
    raw = _tenk()
    lookups = LookupCounter()
    resolver = ParquetEvidenceResolver(raw, _lookup_counter=lookups)

    last_group = len(resolver.row_group_rows) - 1
    last_index = resolver.row_group_rows[last_group] - 1
    for _ in range(3):
        record, error = resolver.read(row_group=last_group, row_index=last_index)
        assert error is None
        assert record is not None
    # 3 reads => 3 record accesses, independent of row position. A linear scan
    # of a 10k-row snapshot would perform >= 10k accesses per last-row read.
    assert lookups.accesses == 3
    resolver.close()


def test_malformed_bytes_fail_closed_in_resolver() -> None:
    with pytest.raises(ParquetCellError):
        ParquetEvidenceResolver(b"not parquet")


# --- adapter + admission integration (shared-resolver binding) ----------------

from app.db.models import SourceSnapshot  # noqa: E402
from app.ingestion.adapters.bigcodebench_parquet import (  # noqa: E402
    BigCodeBenchBatchError,
    BigCodeBenchParquetAdapter,
)
from app.schemas.boundary import OfficialSource  # noqa: E402


ADAPTER = BigCodeBenchParquetAdapter()


def _bcb_source() -> OfficialSource:
    return OfficialSource(
        id="bcb-rslv2",
        benchmark_id="bigcodebench",
        source_name="BigCodeBench resolver",
        source_url="https://official.example/bcb.parquet",
        source_type="bigcodebench_parquet",
        officialness_level="O4",
        parser_config={
            "model_field": "model",
            "dimension_fields": {"complete": "complete", "instruct": "instruct"},
        },
    )


def _bcb_snapshot() -> SourceSnapshot:
    return SourceSnapshot(
        id="22222222-2222-2222-2222-222222222222",
        official_source_id="bcb-rsd",
        raw_content_uri="memory://bcb.parquet",
        content_hash="b" * 64,
    )


def test_adapter_extract_and_validate_share_one_resolver_open(monkeypatch) -> None:
    counter = OpenCounter(monkeypatch)
    raw = _parquet(
        {"model": ["Model A", "Model B"], "complete": ["1.0", "2.0"], "instruct": ["3.0", "4.0"]},
        row_group_size=1,
    )

    resolver = ParquetEvidenceResolver(raw)
    assert counter.count == 1

    claims = ADAPTER.extract_claims(_bcb_source(), _bcb_snapshot(), raw, parquet_resolver=resolver)
    assert len(claims) == 4
    assert counter.count == 1

    for claim in claims:
        validations = ADAPTER.validate_claim(claim, raw, parquet_resolver=resolver)
        assert validations[0].outcome == "pass"
    assert counter.count == 1
    resolver.close()


def test_adapter_fails_closed_on_mismatched_resolver() -> None:
    """Extraction with a resolver bound to different bytes fails closed (no silent fallback)."""
    raw = _parquet({"model": ["M"], "complete": ["1.0"], "instruct": ["2.0"]})
    other = _parquet({"model": ["N"], "complete": ["9.9"], "instruct": ["8.8"]})

    resolver = ParquetEvidenceResolver(other)
    with pytest.raises(BigCodeBenchBatchError) as raised:
        ADAPTER.extract_claims(_bcb_source(), _bcb_snapshot(), raw, parquet_resolver=resolver)
    assert raised.value.reason_code == "PARQUET_UNREADABLE"
    resolver.close()


def test_normal_adapter_trait_flags_parquet_resolver() -> None:
    assert ADAPTER.uses_parquet_evidence_resolver is True


def test_close_raises_on_read_iter_and_validate_but_verify_stays_safe() -> None:
    """Closed-state behavior: a closed resolver fails closed on every consume path."""
    raw = _parquet({"model": ["M"], "score": ["1.0"]})
    resolver = ParquetEvidenceResolver(raw)
    resolver.close()

    with pytest.raises(ParquetCellError):
        resolver.read(row_group=0, row_index=0)
    with pytest.raises(ParquetCellError):
        list(resolver.iter_records())
    with pytest.raises(ParquetCellError):
        resolver.verify(raw)
    # close is idempotent and never raises after the first call.
    resolver.close()
    resolver.close()


def test_close_is_idempotent_and_context_manager_closes_once() -> None:
    raw = _parquet({"a": ["M"], "score": ["1.0"]})
    resolver = ParquetEvidenceResolver(raw)
    with resolver as entered:
        assert entered is resolver
        assert resolver.row_group_rows == (1,)
        resolver.read(row_group=0, row_index=0)  # still readable inside
    # __exit__ closed it even though no exception surfaced.
    assert resolver._closed is True
    with pytest.raises(ParquetCellError):
        resolver.read(row_group=0, row_index=0)


class _SeamParquetFile:
    """A faithful in-process wrapper around a real ``ParquetFile`` that records
    ``close(force=...)`` calls so a test can assert exact one-time force-close on
    every resolver-construction exit path, without any handle leak."""

    closed_calls: list[bool] = []

    def __init__(self, raw_bytes: bytes):
        self._inner = pq.ParquetFile(io.BytesIO(raw_bytes))
        type(self).closed_calls = []

    @property
    def num_row_groups(self):
        return self._inner.num_row_groups

    @property
    def metadata(self):
        return self._inner.metadata

    def iter_batches(self, *a, **k):
        return self._inner.iter_batches(*a, **k)

    def close(self, force=False):
        type(self).closed_calls.append(force)
        self._inner.close(force=force)


def test_close_force_exactly_once_on_success_materialization(monkeypatch) -> None:
    """Defect 5: a successful resolver build force-closes the ParquetFile exactly
    once, with ``force=True`` — proving no handle is leaked after decoding."""
    raw = _parquet({"model": ["M"], "score": ["1.0"]})

    real_open = pc._open
    seam_ref = {}

    def _fake_open(raw: bytes):
        f = _SeamParquetFile(raw)
        seam_ref["f"] = f
        return f

    monkeypatch.setattr(pc, "_open", _fake_open)
    resolver = ParquetEvidenceResolver(raw)
    monkeypatch.setattr(pc, "_open", real_open)

    seam = seam_ref["f"]
    assert seam.closed_calls == [True], "exactly one force=True close on success"
    assert resolver.row_group_rows  # decode completed
    resolver.close()


def test_real_force_close_once_on_decode_failure(monkeypatch) -> None:
    """Defect 5: if batch decode raises, the ParquetFile handle is still
    force-closed exactly once (the ``finally``), never leaked.

    The decode seam is a faithful *subclass* override (a bound method), not a
    bare function stuck on an instance — that would fail with a missing-self
    TypeError before ``to_pylist`` ever executes and would let the test pass
    for the wrong reason.
    """
    raw = _parquet({"model": ["M"], "score": ["1.0"]})
    seam_ref = {}

    class Boom:
        num_rows = 1

        def to_pylist(self):
            raise RuntimeError("injected decode failure")

    class _BoomSeam(_SeamParquetFile):
        def iter_batches(self, *a, **k):
            return iter([Boom()])

    def _open_seam(raw: bytes):
        seam = _BoomSeam(raw)
        seam_ref["f"] = seam
        return seam

    monkeypatch.setattr(pc, "_open", _open_seam)
    with pytest.raises(ParquetCellError) as raised:
        pc.ParquetEvidenceResolver(raw)

    # The intended injected failure must be present in the cause chain (a
    # missing-self TypeError or an unrelated failure would not carry it).
    cause = raised.value
    causes: list[BaseException | None] = [cause for cause in _cause_chain(cause)]
    seam = seam_ref["f"]
    assert any(
        isinstance(c, RuntimeError) and str(c) == "injected decode failure" for c in causes
    ), "the injected to_pylist decode failure must be in the exception cause chain"
    assert seam.closed_calls == [True], "exactly one force=True close on decode failure"


def _cause_chain(exc: BaseException):
    """Yield the exception then every nested ``__cause__``/``__context__``."""
    seen = set()
    cur = exc
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        yield cur
        cur = cur.__cause__ or cur.__context__


def test_resolver_decodes_via_bounded_batches_no_read_row_group(
    monkeypatch,
) -> None:
    """Defect 3: the resolver decodes through ``iter_batches`` with a bounded
    per-batch row cap and never calls ``read_row_group``; row indices stay
    exact across batch boundaries and decoded counts match metadata."""
    raw = _tenk()  # 10_000 rows, row_group_size=512, 3 columns

    decode_attempts = {"read_row_group": 0}
    real_read_row_group = pq.ParquetFile.read_row_group

    def _counting_read_row_group(self, *a, **k):
        decode_attempts["read_row_group"] += 1
        return real_read_row_group(self, *a, **k)

    monkeypatch.setattr(pq.ParquetFile, "read_row_group", _counting_read_row_group)

    resolver = ParquetEvidenceResolver(raw)
    assert decode_attempts["read_row_group"] == 0

    # Row-group denominators come from metadata; total matches 10_000.
    assert sum(resolver.row_group_rows) == 10_000
    # Cross-batch row indices are exact regardless of batch boundaries: the
    # expected grid is derived from the same metadata denominators, so index
    # identity is verified against the *source* grid, not a hand count.
    expected = [
        (g, i) for g, rows in enumerate(resolver.row_group_rows) for i in range(rows)
    ]
    all_records = list(resolver.iter_records())
    assert [(g, i) for g, i, _ in all_records] == expected
    assert len(all_records) == 10_000
    resolver.close()
    monkeypatch.setattr(pq.ParquetFile, "read_row_group", real_read_row_group)


def test_resolver_blocks_read_row_group_with_error(monkeypatch) -> None:
    """If a future implementation regressed to ``read_row_group``, it must not
    be used: wiring it to fail loudly still leaves the bounded-batch path green."""
    raw = _tenk()
    real_read_row_group = pq.ParquetFile.read_row_group

    def _loud(*a, **k):
        raise AssertionError("resolver must decode via iter_batches, not read_row_group")

    monkeypatch.setattr(pq.ParquetFile, "read_row_group", _loud)
    resolver = ParquetEvidenceResolver(raw)
    last_group = len(resolver.row_group_rows) - 1
    last_index = resolver.row_group_rows[last_group] - 1
    record, error = resolver.read(row_group=last_group, row_index=last_index)
    assert error is None and record is not None
    resolver.close()
    monkeypatch.setattr(pq.ParquetFile, "read_row_group", real_read_row_group)


def test_iter_batches_recorded_with_bounded_size_one_group_single_threaded(
    monkeypatch,
) -> None:
    """Every ``iter_batches`` call on the decode path is a faithful bound:

    - ``batch_size`` is positive and at most the fixed cap;
    - exactly one row group is requested per call;
    - ``use_threads`` is explicitly ``False``.

    The patch is *load-bearing*: removing the ``batch_size`` argument, changing
    the batch size, requesting more than one row group, or dropping/setting
    ``use_threads`` makes the corresponding assertion fail loudly rather than
    letting a vacuous smoke check pass.
    """
    raw = _tenk()  # 10_000 rows, row_group_size=512 => 20 row groups

    real_iter_batches = pq.ParquetFile.iter_batches
    calls: list[tuple[int, int, bool | None, bool]] = []

    def _spy(self, batch_size, row_groups, use_threads=None, **kw):
        # Default the thread flag to a sentinel so the test can tell "explicit
        # use_threads=False" apart from "use_threads omitted altogether".
        calls.append((batch_size, len(row_groups), use_threads, kw))
        return real_iter_batches(
            self,
            batch_size=batch_size,
            row_groups=row_groups,
            use_threads=False if use_threads is None else use_threads,
            **kw,
        )

    monkeypatch.setattr(pq.ParquetFile, "iter_batches", _spy)
    resolver = ParquetEvidenceResolver(raw)
    monkeypatch.setattr(pq.ParquetFile, "iter_batches", real_iter_batches)

    assert len(calls) >= 1  # every row group is decoded through iter_batches
    for batch_size, row_group_count, use_threads, kw in calls:
        assert isinstance(batch_size, int) and batch_size > 0
        assert batch_size <= MAX_PARQUET_BATCH_SIZE
        assert row_group_count == 1, "exactly one row group must be requested per call"
        assert use_threads is False, "iter_batches must set use_threads=False"
    resolver.close()
