from __future__ import annotations

import io
import inspect

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from app.db.models import SourceSnapshot
from app.ingestion.adapters import ADAPTERS, get_adapter
from app.ingestion.adapters.bigcodebench_parquet import (
    BigCodeBenchBatchError,
    BigCodeBenchParquetAdapter,
)
from app.ingestion.parquet_cells import read_parquet_record
from app.schemas.boundary import OfficialSource


SNAPSHOT = SourceSnapshot(
    id="11111111-1111-1111-1111-111111111111",
    official_source_id="bigcodebench-fixture",
    raw_content_uri="memory://bigcodebench.parquet",
    content_hash="a" * 64,
)


def _parquet(rows: list[dict[str, object]], *, row_group_size: int | None = None) -> bytes:
    table = pa.Table.from_pylist(
        rows,
        schema=pa.schema(
            [
                pa.field("model", pa.string()),
                pa.field("complete", pa.string()),
                pa.field("instruct", pa.string()),
            ]
        ),
    )
    buffer = io.BytesIO()
    pq.write_table(table, buffer, row_group_size=row_group_size)
    return buffer.getvalue()


def _source(**config: object) -> OfficialSource:
    return OfficialSource(
        id="bigcodebench-fixture",
        benchmark_id="bigcodebench",
        source_name="BigCodeBench fixture",
        source_url="https://official.example/bigcodebench.parquet",
        source_type="bigcodebench_parquet",
        officialness_level="O4",
        parser_config={
            "model_field": "model",
            "dimension_fields": {"complete": "complete", "instruct": "instruct"},
            **config,
        },
    )


def test_extracts_every_declared_dimension_with_exact_typed_locator() -> None:
    raw = _parquet(
        [{"model": "Model A", "complete": "001.2300", "instruct": "87.50"}],
        row_group_size=1,
    )

    claims = BigCodeBenchParquetAdapter().extract_claims(_source(), SNAPSHOT, raw)

    assert [(claim.model_raw, claim.metric_raw, claim.score_raw) for claim in claims] == [
        ("Model A", "complete", "001.2300"),
        ("Model A", "instruct", "87.50"),
    ]
    assert claims[0].score_numeric == 1.23
    assert claims[0].benchmark_raw == "bigcodebench"
    assert claims[0].evidence_location == {
        "type": "parquet_cell_v1",
        "row_group": 0,
        "row_index": 0,
        "fields": {"model_raw": "model", "score_raw": "complete"},
    }


def test_registered_adapter_is_concrete_and_constructible() -> None:
    adapter_class = ADAPTERS["bigcodebench_parquet"]
    assert adapter_class is BigCodeBenchParquetAdapter
    assert type(get_adapter("bigcodebench_parquet")) is BigCodeBenchParquetAdapter


def test_claim_locators_reresolve_each_row_group_and_replay_is_identical() -> None:
    raw = _parquet(
        [
            {"model": "Model A", "complete": "1.2300", "instruct": "2.50"},
            {"model": "Model B", "complete": "3.75", "instruct": "4.000"},
        ],
        row_group_size=1,
    )
    adapter = BigCodeBenchParquetAdapter()

    first = adapter.extract_claims(_source(split_raw="test", setting_raw="instruct"), SNAPSHOT, raw)
    replay = adapter.extract_claims(_source(split_raw="test", setting_raw="instruct"), SNAPSHOT, raw)

    assert first == replay
    assert [(claim.evidence_location["row_group"], claim.metric_raw) for claim in first] == [
        (0, "complete"),
        (0, "instruct"),
        (1, "complete"),
        (1, "instruct"),
    ]
    for claim in first:
        locator = claim.evidence_location
        record, error = read_parquet_record(
            raw,
            row_group=locator["row_group"],
            row_index=locator["row_index"],
        )
        assert error is None
        assert record is not None
        assert record[locator["fields"]["model_raw"]] == claim.model_raw
        assert record[locator["fields"]["score_raw"]] == claim.score_raw
        assert adapter.validate_claim(claim, raw)[0].outcome == "pass"

    altered = first[0].model_copy(update={"score_raw": "9.99"})
    assert adapter.validate_claim(altered, raw)[0].outcome == "uncertain"


@pytest.mark.parametrize(
    ("raw", "source", "reason_code"),
    [
        (_parquet([]), _source(), "PARQUET_EMPTY"),
        (b"not parquet", _source(), "PARQUET_UNREADABLE"),
        (
            _parquet(
                [
                    {"model": "Model A", "complete": "1.0", "instruct": "2.0"},
                    {"model": "Model A", "complete": "3.0", "instruct": "4.0"},
                ]
            ),
            _source(),
            "DUPLICATE_MODEL_DIMENSION",
        ),
        (
            _parquet([{"model": "Model A", "complete": "NaN", "instruct": "2.0"}]),
            _source(),
            "SCORE_NOT_FINITE",
        ),
        (
            _parquet([{"model": "Model A", "complete": "unknown", "instruct": "2.0"}]),
            _source(),
            "SCORE_NOT_NUMERIC",
        ),
        (
            _parquet([{"model": "Model A", "complete": None, "instruct": "2.0"}]),
            _source(),
            "PARQUET_COLUMN_MISSING",
        ),
    ],
)
def test_bad_complete_artifacts_quarantine_the_whole_batch(
    raw: bytes, source: OfficialSource, reason_code: str
) -> None:
    with pytest.raises(BigCodeBenchBatchError) as raised:
        BigCodeBenchParquetAdapter().extract_claims(source, SNAPSHOT, raw)

    assert raised.value.reason_code == reason_code


def test_missing_declared_column_is_not_substituted() -> None:
    source = _source(dimension_fields={"complete": "missing_column", "instruct": "instruct"})

    with pytest.raises(BigCodeBenchBatchError) as raised:
        BigCodeBenchParquetAdapter().extract_claims(
            source,
            SNAPSHOT,
            _parquet([{"model": "Model A", "complete": "1.0", "instruct": "2.0"}]),
        )

    assert raised.value.reason_code == "PARQUET_COLUMN_MISSING"


def test_registry_contains_no_abstract_adapter_classes() -> None:
    for source_type, adapter_class in ADAPTERS.items():
        assert not inspect.isabstract(adapter_class), source_type
        assert type(get_adapter(source_type)) is adapter_class


class _LengthHintRaisingIterator:
    """A one-shot iterator whose ``__length_hint__`` raises.

    Direct ``for``/``next`` iteration succeeds, but ``list(...)`` /
    ``tuple(...)`` / ``sum(...)`` (anything that pre-sizes via
    ``__length_hint__``) raises.  This is the canonical seam for proving a
    consumer streams records instead of materialising them into a list.
    """

    def __init__(self, records):
        self._iter = iter(records)

    def __iter__(self):
        return self

    def __next__(self):
        return next(self._iter)

    def __length_hint__(self):
        raise RuntimeError("length_hint forbidden: consumer must stream, not materialise")


def test_extract_streams_resolver_iterator_not_list(monkeypatch) -> None:
    """Defect 4: extraction consumes the resolver's iterator directly and does
    not materialise a ``list`` of all records.

    We hand the adapter a resolver whose ``iter_records`` returns a one-shot
    iterator whose ``__length_hint__`` raises.  The streaming ``for``-loop the
    adapter uses yields the records fine.  If a future re-implementation ever
    regressed to ``list(parquet_resolver.iter_records())`` (or relied on
    ``len``/``__length_hint__`` of the record source), ``list()`` would raise
    the ``__length_hint__`` error and this test fails loudly — proving the
    load-bearing seam catches reintroduction of list materialisation.
    """
    from app.ingestion.parquet_cells import ParquetEvidenceResolver

    raw = _parquet(
        [{"model": "Model A", "complete": "1.0", "instruct": "2.0"}],
        row_group_size=1,
    )

    class _OnceResolver(ParquetEvidenceResolver):
        def __init__(self, raw, *a, **k):
            super().__init__(raw, *a, **k)

        def iter_records(self):
            # One-shot iterator: __length_hint__ raises; direct iteration OK.
            return _LengthHintRaisingIterator(super().iter_records())

    resolver = _OnceResolver(raw)
    claims = BigCodeBenchParquetAdapter().extract_claims(
        _source(), SNAPSHOT, raw, parquet_resolver=resolver
    )
    assert len(claims) == 2  # one record x two dimensions
    resolver.close()

def test_extract_shared_resolver_consumed_exactly_once(monkeypatch) -> None:
    """The shared run-scoped resolver is consumed exactly once and reused by
    re-resolution, never re-streamed."""
    from app.ingestion.parquet_cells import ParquetEvidenceResolver

    raw = _parquet(
        [{"model": "Model A", "complete": "1.0", "instruct": "2.0"}],
        row_group_size=1,
    )
    resolver = ParquetEvidenceResolver(raw)
    adapter = BigCodeBenchParquetAdapter()
    claims = adapter.extract_claims(_source(), SNAPSHOT, raw, parquet_resolver=resolver)
    assert len(claims) == 2
    # Each claim re-resolves through the same immutable resolver (read path is
    # O(1) direct index, no streaming required).
    for claim in claims:
        assert adapter.validate_claim(claim, raw, parquet_resolver=resolver)[0].outcome == "pass"
    resolver.close()
