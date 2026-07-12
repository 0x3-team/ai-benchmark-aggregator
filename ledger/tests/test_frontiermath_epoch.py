from __future__ import annotations

from app.db.models import SourceSnapshot
from app.ingestion.adapters.frontiermath_epoch import FrontierMathEpochAdapter
from app.schemas.boundary import OfficialSource

SNAP = SourceSnapshot(
    id="33333333-3333-3333-3333-333333333333",
    official_source_id="fm",
    raw_content_uri="mem",
    content_hash="z",
)


def test_frontiermath_epoch_extract_claims():
    csv_raw = b"model,score\nModel-A,0.25\nModel-B,0.45\nModel-C,0.78\n"
    source = OfficialSource(
        id="frontiermath_test",
        source_name="frontiermath_test",
        source_url="https://example.com/leaderboard.csv",
        source_type="frontiermath_epoch",
        officialness_level="O4",
        benchmark_id="frontiermath",
        parser_config={},
    )
    claims = FrontierMathEpochAdapter().extract_claims(source, SNAP, csv_raw)
    assert len(claims) == 3

    assert claims[0].model_raw == "Model-A"
    assert claims[0].score_raw == "0.25"
    assert claims[0].score_numeric == 0.25
    assert claims[0].capture_method == "frontiermath_epoch_parser"
    assert claims[0].capture_confidence == 0.9
    assert claims[0].capture_status == "parser_verified"

    assert claims[1].model_raw == "Model-B"
    assert claims[1].score_raw == "0.45"
    assert claims[1].score_numeric == 0.45

    assert claims[2].model_raw == "Model-C"
    assert claims[2].score_raw == "0.78"
    assert claims[2].score_numeric == 0.78


def test_frontiermath_epoch_validate_claim():
    csv_raw = b"model,score\nModel-A,0.25\n"
    source = OfficialSource(
        id="frontiermath_test",
        source_name="frontiermath_test",
        source_url="https://example.com/leaderboard.csv",
        source_type="frontiermath_epoch",
        officialness_level="O4",
        benchmark_id="frontiermath",
        parser_config={},
    )
    claims = FrontierMathEpochAdapter().extract_claims(source, SNAP, csv_raw)
    assert len(claims) == 1

    validation = FrontierMathEpochAdapter().validate_claim(claims[0], csv_raw)
    assert len(validation) == 1
    assert validation[0].validation_type == "fm_csv_match"
    assert validation[0].outcome == "pass"
    assert validation[0].validator == "FrontierMathEpochAdapter"


def test_frontiermath_epoch_custom_fields():
    csv_raw = b"model_name,pass_rate\nAlpha,0.92\nBeta,0.67\n"
    source = OfficialSource(
        id="frontiermath_custom_test",
        source_name="frontiermath_custom_test",
        source_url="https://example.com/leaderboard.csv",
        source_type="frontiermath_epoch",
        officialness_level="O4",
        benchmark_id="frontiermath",
        parser_config={
            "model_field": "model_name",
            "score_field": "pass_rate",
            "metric_field": "pass_rate",
        },
    )
    claims = FrontierMathEpochAdapter().extract_claims(source, SNAP, csv_raw)
    assert len(claims) == 2
    assert claims[0].model_raw == "Alpha"
    assert claims[0].score_raw == "0.92"
    assert claims[0].score_numeric == 0.92
    assert claims[0].metric_raw == "pass_rate"
    assert claims[1].model_raw == "Beta"
    assert claims[1].score_raw == "0.67"
    assert claims[1].score_numeric == 0.67


def test_frontiermath_epoch_empty_rows_skipped():
    csv_raw = b"model,score\nModel-A,0.50\n,,\nModel-B,0.80\n"
    source = OfficialSource(
        id="frontiermath_test",
        source_name="frontiermath_test",
        source_url="https://example.com/leaderboard.csv",
        source_type="frontiermath_epoch",
        officialness_level="O4",
        benchmark_id="frontiermath",
        parser_config={},
    )
    claims = FrontierMathEpochAdapter().extract_claims(source, SNAP, csv_raw)
    assert len(claims) == 2
    assert claims[0].model_raw == "Model-A"
    assert claims[1].model_raw == "Model-B"
