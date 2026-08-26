from __future__ import annotations

import inspect

import pytest

from app.db.models import SourceSnapshot
from app.ingestion.adapters import ADAPTERS, get_adapter
from app.ingestion.adapters.agc_bench import AGCBenchAdapter, AGCBenchBatchError
from app.schemas.boundary import OfficialSource


SNAPSHOT = SourceSnapshot(
    id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
    official_source_id="agc-bench-fixture",
    raw_content_uri="memory://agc-bench/model_dataset_scores.csv",
    content_hash="b" * 64,
)


def _source(
    *, record_kind: str = "model_dataset_scores", status: str = "inactive", **config: object
) -> OfficialSource:
    return OfficialSource(
        id="agc-bench-fixture",
        benchmark_id="agc_bench",
        source_name="AGC-Bench generated fixture",
        source_url="https://huggingface.co/datasets/agcbench-2026/AGC-Bench",
        source_type="agc_bench",
        officialness_level="O0",
        status=status,
        parser_name="agc_bench",
        parser_config={
            "mode": "fixture_only",
            "record_kind": record_kind,
            "model_field": "model",
            "benchmark_field": "dataset",
            "metric_field": "metric",
            "score_field": "score",
            "max_bytes": 4096,
            "max_rows": 10,
            **config,
        },
    )


def _csv(*rows: str, header: str = "model,dataset,metric,score") -> bytes:
    return (header + "\n" + "\n".join(rows) + "\n").encode("utf-8")


def test_model_dataset_cells_preserve_exact_lexemes_dimensions_and_unresolved_identity() -> None:
    raw = _csv(
        "Model A,ARC-Challenge,accuracy,001.2300",
        "Model B,GPQA,accuracy,47.60",
    )

    claims = AGCBenchAdapter().extract_claims(_source(), SNAPSHOT, raw)

    assert [
        (claim.model_raw, claim.benchmark_raw, claim.metric_raw, claim.score_raw)
        for claim in claims
    ] == [
        ("Model A", "ARC-Challenge", "accuracy", "001.2300"),
        ("Model B", "GPQA", "accuracy", "47.60"),
    ]
    assert claims[0].score_numeric == 1.23
    assert claims[0].model_entity_id is None
    assert claims[0].capture_status == "unreviewed"
    assert claims[0].capture_confidence == 0.0
    assert claims[0].evidence_location == {
        "type": "csv_cell_v1",
        "row_index": 0,
        "fields": {
            "model_raw": "model",
            "benchmark_raw": "dataset",
            "metric_raw": "metric",
            "score_raw": "score",
        },
    }


def test_source_reported_headline_field_is_distinct_and_never_recalculated() -> None:
    raw = _csv(
        "Model A,AGC-Bench,source_reported_composite,88.125",
        header="model,benchmark,reported_field,headline_score",
    )
    source = _source(
        record_kind="headline_leaderboard",
        benchmark_field="benchmark",
        metric_field="reported_field",
        score_field="headline_score",
    )

    [claim] = AGCBenchAdapter().extract_claims(source, SNAPSHOT, raw)

    assert (claim.benchmark_raw, claim.metric_raw, claim.score_raw) == (
        "AGC-Bench",
        "source_reported_composite",
        "88.125",
    )
    assert claim.capture_method == "agc_bench_headline_leaderboard_fixture_parser"


def test_claim_evidence_replays_exactly_and_rejects_altered_cell_values() -> None:
    raw = _csv("Model A,ARC-Challenge,accuracy,001.2300")
    adapter = AGCBenchAdapter()
    [claim] = adapter.extract_claims(_source(), SNAPSHOT, raw)

    assert adapter.extract_claims(_source(), SNAPSHOT, raw) == [claim]
    assert adapter.validate_claim(claim, raw)[0].outcome == "pass"
    assert adapter.validate_claim(
        claim.model_copy(update={"score_raw": "1.23"}), raw
    )[0].outcome == "uncertain"
    assert adapter.validate_claim(
        claim.model_copy(update={"benchmark_raw": "substituted"}), raw
    )[0].outcome == "uncertain"


@pytest.mark.parametrize(
    ("raw", "source", "reason_code"),
    [
        (_csv("Model A,ARC,accuracy,"), _source(), "SCORE_VALUE_MISSING"),
        (_csv("Model A,ARC,accuracy,NaN"), _source(), "SCORE_NOT_FINITE"),
        (_csv("Model A,ARC,accuracy,-Infinity"), _source(), "SCORE_NOT_FINITE"),
        (_csv("Model A,ARC,accuracy,not-a-score"), _source(), "SCORE_NOT_NUMERIC"),
        (
            _csv("Model A,ARC,accuracy,1.0", header="model,dataset,score"),
            _source(),
            "CSV_SCHEMA_INVALID",
        ),
        (
            _csv("Model A,ARC,accuracy,1.0", "Model A,ARC,accuracy,2.0"),
            _source(),
            "DUPLICATE_MODEL_DIMENSION",
        ),
        (_csv("Model A,ARC,accuracy,1.0", "Model B,GPQA,accuracy,2.0"), _source(max_rows=1), "CSV_MAX_ROWS_EXCEEDED"),
    ],
)
def test_invalid_or_incomplete_fixture_batches_fail_closed(
    raw: bytes, source: OfficialSource, reason_code: str
) -> None:
    with pytest.raises(AGCBenchBatchError) as raised:
        AGCBenchAdapter().extract_claims(source, SNAPSHOT, raw)

    assert raised.value.reason_code == reason_code


def test_byte_bound_and_complete_accounting_are_enforced() -> None:
    raw = _csv("Model A,ARC,accuracy,1.0", "Model B,GPQA,accuracy,2.0")
    adapter = AGCBenchAdapter()

    claims = adapter.extract_claims(_source(max_bytes=len(raw), max_rows=2), SNAPSHOT, raw)
    assert len(claims) == 2
    with pytest.raises(AGCBenchBatchError) as raised:
        adapter.extract_claims(_source(max_bytes=len(raw) - 1), SNAPSHOT, raw)
    assert raised.value.reason_code == "CSV_MAX_BYTES_EXCEEDED"


def test_unscoped_or_active_sources_cannot_parse_and_adapter_cannot_fetch() -> None:
    raw = _csv("Model A,ARC,accuracy,1.0")
    adapter = AGCBenchAdapter()

    assert adapter.extract_claims(_source(mode="retired"), SNAPSHOT, raw) == []
    assert adapter.extract_claims(_source(status="active"), SNAPSHOT, raw) == []
    with pytest.raises(RuntimeError, match="fixture-only"):
        adapter.fetch(_source())


def test_adapter_is_registered_but_fixture_only_and_has_no_transport_or_database_path() -> None:
    assert ADAPTERS["agc_bench"] is AGCBenchAdapter
    assert type(get_adapter("agc_bench")) is AGCBenchAdapter
    assert AGCBenchAdapter.requires_central_fetch is False
    implementation = inspect.getsource(AGCBenchAdapter)
    assert "httpx" not in implementation
    assert "sqlalchemy" not in implementation
