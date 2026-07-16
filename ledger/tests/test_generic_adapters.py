from pathlib import Path

import pytest

from app.db.models import SourceSnapshot
from app.ingestion.adapters.generic_csv import GenericCSVAdapter
from app.ingestion.adapters.generic_html_table import GenericHTMLTableAdapter
from app.ingestion.adapters.generic_json import GenericJSONAdapter
from app.ingestion.adapters.hf_benchmark_api import HFBenchmarkAPIAdapter
from app.schemas.boundary import OfficialSource, ResultClaimInput

SNAP = SourceSnapshot(
    id="11111111-1111-1111-1111-111111111111",
    official_source_id="s",
    raw_content_uri="mem",
    content_hash="x",
)


def test_json_adapter_fixture():
    raw = (Path(__file__).parent / "fixtures/generic_json_sample.json").read_bytes()
    source = OfficialSource(
        id="j",
        source_name="j",
        source_url="file://j",
        source_type="static_json",
        officialness_level="O5",
        benchmark_id="livecodebench",
        parser_config={"records_path": "results", "model_field": "model", "score_field": "score"},
    )
    claims = GenericJSONAdapter().extract_claims(source, SNAP, raw)
    assert claims[0].score_raw == "90.1"
    assert claims[0].score_numeric is None
    assert claims[0].evidence_location == {
        "type": "json_path_v1",
        "record_path": "$.results[0]",
        "fields": {"model_raw": "model", "score_raw": "score"},
    }
    assert GenericJSONAdapter().validate_claim(claims[0], raw)[0].outcome == "pass"


def test_json_adapter_preserves_numeric_score_lexemes_without_coercing_other_json_types():
    raw = (
        b'{"results":['
        b'{"model":"Model-A","score":1.2300},'
        b'{"model":7,"score":2.50},'
        b'{"model":"Model-C","score":true},'
        b'{"model":"Model-D","score":null}'
        b']}'
    )
    source = OfficialSource(
        id="json-lexeme",
        source_name="json-lexeme",
        source_url="https://example.com/lexemes.json",
        source_type="static_json",
        officialness_level="O5",
        benchmark_id="livecodebench",
        parser_config={
            "records_path": "results",
            "model_field": "model",
            "score_field": "score",
        },
    )

    claims = GenericJSONAdapter().extract_claims(source, SNAP, raw)

    assert [(claim.model_raw, claim.score_raw, claim.score_numeric) for claim in claims] == [
        ("Model-A", "1.2300", None)
    ]
    assert claims[0].evidence_location["record_path"] == "$.results[0]"


def test_json_adapter_requires_an_explicit_configured_record_path():
    source = OfficialSource(
        id="json-no-fallback",
        source_name="json-no-fallback",
        source_url="https://example.com/no-fallback.json",
        source_type="static_json",
        officialness_level="O5",
        benchmark_id="livecodebench",
        parser_config={"model_field": "model", "score_field": "score"},
    )

    assert GenericJSONAdapter().extract_claims(
        source,
        SNAP,
        b'{"results":[{"model":"Model-A","score":1.0}]}',
    ) == []


def test_csv_adapter_fixture():
    raw = (Path(__file__).parent / "fixtures/generic_csv_sample.csv").read_bytes()
    source = OfficialSource(
        id="c",
        source_name="c",
        source_url="file://c",
        source_type="static_csv",
        officialness_level="O5",
        benchmark_id="livecodebench",
        parser_config={"model_field": "model", "score_field": "score"},
    )
    claims = GenericCSVAdapter().extract_claims(source, SNAP, raw)
    assert claims[0].score_raw == "91.5"


def test_html_adapter_fixture():
    raw = (Path(__file__).parent / "fixtures/html_table_sample.html").read_bytes()
    source = OfficialSource(
        id="h",
        source_name="h",
        source_url="file://h",
        source_type="html_table",
        officialness_level="O4",
        benchmark_id="swe_bench_verified",
        parser_config={"model_column": "Model", "score_column": "% Resolved", "table_index": 0},
    )
    claims = GenericHTMLTableAdapter().extract_claims(source, SNAP, raw)
    assert len(claims) == 2
    assert claims[0].score_raw == "50.80"
    assert claims[0].model_raw == "Agent-X"
    # Validate: score_raw must appear verbatim in raw bytes.
    assert GenericHTMLTableAdapter().validate_claim(claims[0], raw)[0].outcome == "pass"
    assert GenericHTMLTableAdapter().validate_claim(claims[1], raw)[0].outcome == "pass"


def test_html_adapter_validate_uncertain():
    """validate_claim must return uncertain when score_raw is not in raw bytes."""
    raw = (Path(__file__).parent / "fixtures/html_table_sample.html").read_bytes()
    source = OfficialSource(
        id="h",
        source_name="h",
        source_url="file://h",
        source_type="html_table",
        officialness_level="O4",
        benchmark_id="swe_bench_verified",
        parser_config={"model_column": "Model", "score_column": "% Resolved", "table_index": 0},
    )
    claims = GenericHTMLTableAdapter().extract_claims(source, SNAP, raw)
    # Mutate the claim to a value that does not exist in the raw bytes.
    claims[0].score_raw = "999.99"
    assert GenericHTMLTableAdapter().validate_claim(claims[0], raw)[0].outcome == "uncertain"


def test_html_adapter_messy_headers():
    raw = (Path(__file__).parent / "fixtures/html_table_messy_header.html").read_bytes()
    source = OfficialSource(
        id="hm",
        source_name="hm",
        source_url="file://hm",
        source_type="html_table",
        officialness_level="O4",
        benchmark_id="swe_bench_verified",
        parser_config={"model_column": "Model", "score_column": "% Resolved", "table_index": 0},
    )
    claims = GenericHTMLTableAdapter().extract_claims(source, SNAP, raw)
    # Whitespace/newline/nbsp inside headers must be normalized for matching.
    assert len(claims) == 2
    assert claims[0].model_raw == "Agent-X"
    assert claims[0].score_raw == "50.80"
    assert claims[1].model_raw == "Agent-Y"
    assert claims[1].score_raw == "40.00"
    # Validation passes: the raw score values appear in the snapshot bytes.
    for c in claims:
        assert GenericHTMLTableAdapter().validate_claim(c, raw)[0].outcome == "pass"


def test_html_adapter_case_insensitive_headers():
    """Column matching must be case-insensitive after normalization."""
    raw = (Path(__file__).parent / "fixtures/html_table_case_headers.html").read_bytes()
    source = OfficialSource(
        id="hci",
        source_name="hci",
        source_url="file://hci",
        source_type="html_table",
        officialness_level="O4",
        benchmark_id="case_test",
        parser_config={"model_column": "Model", "score_column": "% Resolved", "table_index": 0},
    )
    claims = GenericHTMLTableAdapter().extract_claims(source, SNAP, raw)
    assert len(claims) == 1
    assert claims[0].model_raw == "CaseModel1"
    assert claims[0].score_raw == "99.99"
    assert GenericHTMLTableAdapter().validate_claim(claims[0], raw)[0].outcome == "pass"


def test_html_adapter_optional_columns():
    """Optional metric/split/rank/date columns should be extracted when configured."""
    raw = (Path(__file__).parent / "fixtures/html_table_optional_columns.html").read_bytes()
    source = OfficialSource(
        id="ho",
        source_name="ho",
        source_url="file://ho",
        source_type="html_table",
        officialness_level="O4",
        benchmark_id="optional_test",
        parser_config={
            "model_column": "Model",
            "score_column": "Score",
            "metric_column": "Metric",
            "split_column": "Split",
            "rank_column": "Rank",
            "date_column": "Date",
            "table_index": 0,
        },
    )
    claims = GenericHTMLTableAdapter().extract_claims(source, SNAP, raw)
    assert len(claims) == 2
    assert claims[0].model_raw == "Model-A"
    assert claims[0].score_raw == "88.2"
    assert claims[0].metric_raw == "Pass@1"
    assert claims[0].split_raw == "test"
    assert claims[0].rank_raw == "1"
    assert claims[0].date_raw == "2024-06-01"
    assert claims[1].model_raw == "Model-B"
    assert claims[1].score_raw == "77.1"
    assert claims[1].metric_raw == "Pass@5"
    assert claims[1].split_raw == "val"
    assert claims[1].rank_raw == "2"
    assert claims[1].date_raw == "2024-06-02"
    # Validate.
    for c in claims:
        assert GenericHTMLTableAdapter().validate_claim(c, raw)[0].outcome == "pass"


def test_html_adapter_table_index_failure_falls_back_to_hint():
    raw = (Path(__file__).parent / "fixtures/html_table_multitable.html").read_bytes()
    source = OfficialSource(
        id="ht",
        source_name="ht",
        source_url="file://ht",
        source_type="html_table",
        officialness_level="O4",
        benchmark_id="livecodebench",
        # table_index 0 is the wrong table; table_hint must find the correct one.
        parser_config={
            "model_column": "Model",
            "score_column": "Pass@1",
            "table_index": 0,
            "table_hint": "Pass@1",
        },
    )
    claims = GenericHTMLTableAdapter().extract_claims(source, SNAP, raw)
    assert len(claims) == 2
    assert {c.model_raw for c in claims} == {"Model-A", "Model-B"}
    assert claims[0].evidence_location["table_index"] == 1
    # Validate: score_raw values must appear in the raw bytes.
    for c in claims:
        assert GenericHTMLTableAdapter().validate_claim(c, raw)[0].outcome == "pass"


def test_hf_leaderboard_fixture_offline():
    raw = (Path(__file__).parent / "fixtures/hf_leaderboard_sample.json").read_bytes()
    source = OfficialSource(
        id="hf",
        source_name="hf",
        source_url="https://example.invalid",
        source_type="hf_benchmark_api",
        officialness_level="O5",
        benchmark_id="hf_official_benchmarks",
        parser_config={"mode": "leaderboard", "dataset_id": "example"},
    )
    claims = HFBenchmarkAPIAdapter().extract_claims(source, SNAP, raw)
    assert claims[0].score_raw == "55.5"
    assert claims[0].model_raw == "org/model-a"
    assert HFBenchmarkAPIAdapter().validate_claim(claims[0], raw)[0].outcome == "pass"


def test_hf_discovery_mode_is_retired_and_never_emits_pseudo_claims():
    source = OfficialSource(
        id="hf-discovery",
        source_name="hf discovery",
        source_url="https://example.invalid/discovery",
        source_type="hf_benchmark_api",
        officialness_level="O5",
        benchmark_id="hf_official_benchmarks",
        parser_config={"mode": "discovery"},
    )
    adapter = HFBenchmarkAPIAdapter()

    assert adapter.extract_claims(source, SNAP, b'[{"id":"dataset/example"}]') == []
    with pytest.raises(RuntimeError, match="discovery mode is retired"):
        adapter.fetch(source)
    validation = adapter.validate_claim(
        ResultClaimInput(
            official_source_id=source.id,
            source_snapshot_id=SNAP.id,
            benchmark_id=source.benchmark_id,
            model_raw="dataset/example",
            benchmark_raw="hf_official_benchmarks",
            score_raw="n/a",
            evidence_location={"type": "json_path_v1"},
            capture_method="legacy_discovery",
        ),
        b'[{"id":"dataset/example"}]',
    )
    assert validation[0].outcome == "fail"
