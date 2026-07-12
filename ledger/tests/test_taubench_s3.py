from __future__ import annotations

from app.db.models import SourceSnapshot
from app.ingestion.adapters.taubench_s3 import TauBenchS3Adapter
from app.schemas.boundary import OfficialSource

SNAP = SourceSnapshot(
    id="33333333-3333-3333-3333-333333333333",
    official_source_id="taubench_test",
    raw_content_uri="mem",
    content_hash="z",
)


def test_taubench_s3_extract_single_model():
    """A single submission.json with pass_* metrics across multiple domains should
    yield one claim with the mean pass rate."""
    raw = b"""{"model": "test-model-1", "results": {"domain_a": {"pass_1": 80, "pass_2": 90}, "domain_b": {"pass_1": 70, "pass_2": 85}}}"""

    source = OfficialSource(
        id="taubench_test",
        source_name="tau-bench Live S3",
        source_url="https://sierra-tau-bench-public.s3.amazonaws.com/",
        source_type="taubench_s3",
        officialness_level="O1",
        benchmark_id="tau_bench",
        parser_config={"max_keys": 50},
    )

    adapter = TauBenchS3Adapter()
    claims = adapter.extract_claims(source, SNAP, raw)

    assert len(claims) == 1
    c = claims[0]
    assert c.model_raw == "test-model-1"
    assert c.score_raw == "81.2500"
    assert c.score_numeric == 81.25
    assert c.metric_raw == "mean_pass_rate"
    assert c.capture_method == "taubench_s3_parser"
    assert c.capture_confidence == 0.9
    assert c.capture_status == "parser_verified"
    assert c.benchmark_id == "tau_bench"
    assert c.evidence_location == {"type": "s3_submission", "model": "test-model-1"}

    # Validation should pass
    validations = adapter.validate_claim(c, raw)
    assert len(validations) == 1
    assert validations[0].validation_type == "taubench_agg"
    assert validations[0].outcome == "pass"
    assert validations[0].validator == "TauBenchS3Adapter"


def test_taubench_s3_multiple_models_ndjson():
    """Two submission lines (NDJSON) should produce two claims."""
    raw = b"""{"model": "model-a", "results": {"d1": {"pass_1": 50, "pass_2": 60}}}
{"model": "model-b", "results": {"d1": {"pass_1": 70}}}"""

    source = OfficialSource(
        id="taubench_test",
        source_name="tau-bench Live S3",
        source_url="https://sierra-tau-bench-public.s3.amazonaws.com/",
        source_type="taubench_s3",
        officialness_level="O1",
        benchmark_id="tau_bench",
        parser_config={},
    )

    claims = TauBenchS3Adapter().extract_claims(source, SNAP, raw)

    assert len(claims) == 2
    # model-a: (50+60)/2 = 55.0
    assert claims[0].model_raw == "model-a"
    assert claims[0].score_numeric == 55.0
    assert claims[0].score_raw == "55.0000"
    # model-b: 70/1 = 70.0
    assert claims[1].model_raw == "model-b"
    assert claims[1].score_numeric == 70.0
    assert claims[1].score_raw == "70.0000"


def test_taubench_s3_alternate_model_fields():
    """Should resolve model_name and model_id fallbacks."""
    raw = b"""{"model_name": "fallback-model", "results": {"d1": {"pass_1": 100}}}"""

    source = OfficialSource(
        id="taubench_test",
        source_name="tau-bench Live S3",
        source_url="https://sierra-tau-bench-public.s3.amazonaws.com/",
        source_type="taubench_s3",
        officialness_level="O1",
        benchmark_id="tau_bench",
        parser_config={},
    )

    claims = TauBenchS3Adapter().extract_claims(source, SNAP, raw)

    assert len(claims) == 1
    assert claims[0].model_raw == "fallback-model"
    assert claims[0].score_numeric == 100.0


def test_taubench_s3_no_pass_metrics():
    """Results without any pass_* keys should produce no claims."""
    raw = b"""{"model": "no-pass-model", "results": {"d1": {"accuracy": 95}}}"""

    source = OfficialSource(
        id="taubench_test",
        source_name="tau-bench Live S3",
        source_url="https://sierra-tau-bench-public.s3.amazonaws.com/",
        source_type="taubench_s3",
        officialness_level="O1",
        benchmark_id="tau_bench",
        parser_config={},
    )

    claims = TauBenchS3Adapter().extract_claims(source, SNAP, raw)
    assert len(claims) == 0


def test_taubench_s3_empty_lines():
    """NDJSON with blank lines should be handled gracefully."""
    raw = b"""
{"model": "model-c", "results": {"d1": {"pass_1": 42}}}

"""

    source = OfficialSource(
        id="taubench_test",
        source_name="tau-bench Live S3",
        source_url="https://sierra-tau-bench-public.s3.amazonaws.com/",
        source_type="taubench_s3",
        officialness_level="O1",
        benchmark_id="tau_bench",
        parser_config={},
    )

    claims = TauBenchS3Adapter().extract_claims(source, SNAP, raw)
    assert len(claims) == 1
    assert claims[0].model_raw == "model-c"
    assert claims[0].score_numeric == 42.0
