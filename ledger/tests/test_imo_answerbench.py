from app.db.models import SourceSnapshot
from app.ingestion.adapters.imo_answerbench import ImoAnswerBenchAdapter
from app.schemas.boundary import OfficialSource

SNAP = SourceSnapshot(
    id="33333333-3333-3333-3333-333333333333",
    official_source_id="imo_answerbench_test",
    raw_content_uri="mem",
    content_hash="z",
)


def test_imo_answerbench_csv_aggregation() -> None:
    """CSV with model/problem_id/correct — verify per-model accuracy claims."""
    raw = (
        b"model,problem_id,correct\n"
        b"Model-A,p001,1\n"
        b"Model-A,p002,0\n"
        b"Model-A,p003,1\n"
        b"Model-A,p004,1\n"
        b"Model-B,p001,1\n"
        b"Model-B,p002,1\n"
        b"Model-B,p003,0\n"
        b"Model-B,p004,0\n"
    )

    source = OfficialSource(
        id="imo_answerbench_test",
        source_name="IMO-AnswerBench v2",
        source_url="https://datasets-server.huggingface.co/first-rows?dataset=google-deepmind%2Fsuperhuman&config=answerbench_v2&split=train",
        source_type="imo_answerbench",
        officialness_level="O4",
        benchmark_id="imo_answerbench",
        parser_config={
            "model_field": "model",
            "score_field": "correct",
        },
    )

    claims = ImoAnswerBenchAdapter().extract_claims(source, SNAP, raw)

    assert len(claims) == 2, f"Expected 2 claims, got {len(claims)}"

    # Model-A: 3/4 = 0.7500
    claim_a = [c for c in claims if c.model_raw == "Model-A"][0]
    assert claim_a.score_raw == "0.7500", f"Expected 0.7500, got {claim_a.score_raw}"
    assert claim_a.score_numeric == 0.75
    assert claim_a.metric_raw == "accuracy_over_problems"
    assert claim_a.capture_method == "imo_answerbench_parser"
    assert claim_a.capture_confidence == 0.9
    assert claim_a.capture_status == "parser_verified"
    assert claim_a.officialness_level == "O4"
    assert claim_a.benchmark_raw == "imo_answerbench"
    assert claim_a.evidence_location["num_problems"] == 4

    # Model-B: 2/4 = 0.5000
    claim_b = [c for c in claims if c.model_raw == "Model-B"][0]
    assert claim_b.score_raw == "0.5000", f"Expected 0.5000, got {claim_b.score_raw}"
    assert claim_b.score_numeric == 0.5
    assert claim_b.evidence_location["num_problems"] == 4

    # Validate
    val = ImoAnswerBenchAdapter().validate_claim(claim_a, raw)
    assert len(val) == 1
    assert val[0].validation_type == "imo_csv_match"
    assert val[0].outcome == "uncertain"  # aggregated score not in raw CSV bytes
    assert val[0].validator == "ImoAnswerBenchAdapter"


def test_imo_answerbench_json_rows_format() -> None:
    """Handle HF datasets-server JSON row format."""
    import json

    payload = {
        "rows": [
            {"row": {"model": "Gemini-2.5-Pro", "problem_id": "p001", "correct": "1"}},
            {"row": {"model": "Gemini-2.5-Pro", "problem_id": "p002", "correct": "0"}},
            {"row": {"model": "Gemini-2.5-Pro", "problem_id": "p003", "correct": "1"}},
        ]
    }
    raw = json.dumps(payload).encode("utf-8")

    source = OfficialSource(
        id="imo_answerbench_json_test",
        source_name="IMO-AnswerBench v2 (JSON)",
        source_url="https://example.com",
        source_type="imo_answerbench",
        officialness_level="O4",
        benchmark_id="imo_answerbench",
        parser_config={
            "model_field": "model",
            "score_field": "correct",
        },
    )

    claims = ImoAnswerBenchAdapter().extract_claims(source, SNAP, raw)
    assert len(claims) == 1
    assert claims[0].model_raw == "Gemini-2.5-Pro"
    assert claims[0].score_raw == "0.6667"  # 2/3


def test_imo_answerbench_custom_fields() -> None:
    """parser_config overrides model_field and score_field."""
    raw = (
        b"llm,problem,is_correct\n"
        b"GPT-5,q1,1\n"
        b"GPT-5,q2,1\n"
        b"GPT-5,q3,0\n"
    )

    source = OfficialSource(
        id="imo_custom_test",
        source_name="Custom CSV",
        source_url="https://example.com",
        source_type="imo_answerbench",
        officialness_level="O3",
        benchmark_id="imo_answerbench",
        parser_config={
            "model_field": "llm",
            "score_field": "is_correct",
        },
    )

    claims = ImoAnswerBenchAdapter().extract_claims(source, SNAP, raw)
    assert len(claims) == 1
    assert claims[0].model_raw == "GPT-5"
    assert claims[0].score_raw == "0.6667"  # 2/3


def test_imo_answerbench_empty() -> None:
    """Empty CSV returns no claims."""
    source = OfficialSource(
        id="imo_empty_test",
        source_name="Empty CSV",
        source_url="https://example.com",
        source_type="imo_answerbench",
        officialness_level="O4",
        benchmark_id="imo_answerbench",
        parser_config={},
    )
    claims = ImoAnswerBenchAdapter().extract_claims(source, SNAP, b"model,problem_id,correct\n")
    assert claims == []


def test_imo_answerbench_single_model() -> None:
    """Single model with all-correct scores."""
    raw = (
        b"model,problem_id,correct\n"
        b"Perfect-Model,p001,1\n"
        b"Perfect-Model,p002,1\n"
    )

    source = OfficialSource(
        id="imo_single_test",
        source_name="Single Model",
        source_url="https://example.com",
        source_type="imo_answerbench",
        officialness_level="O4",
        benchmark_id="imo_answerbench",
        parser_config={},
    )

    claims = ImoAnswerBenchAdapter().extract_claims(source, SNAP, raw)
    assert len(claims) == 1
    assert claims[0].model_raw == "Perfect-Model"
    assert claims[0].score_raw == "1.0000"
    assert claims[0].score_numeric == 1.0
