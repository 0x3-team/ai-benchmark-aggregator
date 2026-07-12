from __future__ import annotations

import json

from app.db.models import SourceSnapshot
from app.ingestion.adapters.helm_json import HelmJSONAdapter
from app.schemas.boundary import OfficialSource

SNAP = SourceSnapshot(
    id="33333333-3333-3333-3333-333333333333",
    official_source_id="s",
    raw_content_uri="mem",
    content_hash="z",
)


def _make_source(parser_config: dict | None = None) -> OfficialSource:
    return OfficialSource(
        id="helm_test",
        source_name="helm_test",
        source_url="https://example.com/runs.json",
        source_type="helm_json",
        officialness_level="O4",
        benchmark_id="helm",
        parser_config=parser_config or {},
    )


def _raw(data) -> bytes:
    return json.dumps(data).encode("utf-8")


# ---------------------------------------------------------------------------
# Shape 2: real HELM runs.json format (flat list of runs with stats)
# ---------------------------------------------------------------------------


def test_helm_json_shape2_flat_runs():
    """Single run with two accuracy-like stats; one metadata stat skipped."""
    data = [
        {
            "run_path": "benchmark_output/runs/v1/some-run",
            "run_spec": {"adapter_spec": {"model": "test-model-1"}},
            "stats": [
                {"name": {"name": "exact_match", "split": "test"}, "mean": 0.92},
                {"name": {"name": "f1_score", "split": "test"}, "mean": 0.88},
                {"name": {"name": "num_prompt_tokens", "split": "test"}, "mean": 260.0},
            ],
        }
    ]
    source = _make_source()
    claims = HelmJSONAdapter().extract_claims(source, SNAP, _raw(data))
    assert len(claims) == 2
    assert claims[0].model_raw == "test-model-1"
    assert claims[0].score_raw == "0.92"
    assert claims[0].metric_raw == "exact_match"
    assert claims[0].split_raw == "test"
    assert claims[0].score_numeric == 0.92
    assert claims[0].capture_method == "helm_json_parser"
    assert claims[0].capture_confidence == 0.85
    assert claims[0].capture_status == "parser_verified"
    assert claims[0].officialness_level == "O4"
    assert claims[0].evidence_location == {"type": "helm_json", "model_path": "model"}
    assert claims[1].model_raw == "test-model-1"
    assert claims[1].score_raw == "0.88"
    assert claims[1].metric_raw == "f1_score"
    assert HelmJSONAdapter().validate_claim(claims[0], _raw(data))[0].outcome == "pass"


def test_helm_json_shape2_multiple_runs():
    """Two runs — verify model separation + non-accuracy skip."""
    data = [
        {"run_spec": {"adapter_spec": {"model": "model-a"}}, "stats": [
            {"name": {"name": "exact_match", "split": "test"}, "mean": 0.75}]},
        {"run_spec": {"adapter_spec": {"model": "model-b"}}, "stats": [
            {"name": {"name": "exact_match", "split": "test"}, "mean": 0.80},
            {"name": {"name": "num_instances", "split": "test"}, "mean": 500.0}]},
    ]
    source = _make_source()
    claims = HelmJSONAdapter().extract_claims(source, SNAP, _raw(data))
    assert len(claims) == 2
    assert claims[0].model_raw == "model-a"
    assert claims[0].score_raw == "0.75"
    assert claims[1].model_raw == "model-b"
    assert claims[1].score_raw == "0.8"


def test_helm_json_shape2_bleu_rouge():
    """bleu_1, bleu_4, rouge_l should all be accuracy-like."""
    data = [
        {"run_spec": {"adapter_spec": {"model": "translator"}}, "stats": [
            {"name": {"name": "bleu_1", "split": "test"}, "mean": 0.65},
            {"name": {"name": "bleu_4", "split": "test"}, "mean": 0.42},
            {"name": {"name": "rouge_l", "split": "test"}, "mean": 0.55}]}
    ]
    source = _make_source()
    claims = HelmJSONAdapter().extract_claims(source, SNAP, _raw(data))
    assert len(claims) == 3
    assert {c.metric_raw for c in claims} == {"bleu_1", "bleu_4", "rouge_l"}


def test_helm_json_shape2_parser_config_overrides():
    """Custom model_field / score_field / metric_field from parser_config."""
    data = [
        {"run_spec": {"adapter_spec": {"name": "gpt-4"}}, "stats": [
            {"name": {"key": "accuracy", "split": "dev"}, "avg": 0.99}]}
    ]
    source = _make_source(parser_config={
        "model_field": "name", "score_field": "avg", "metric_field": "key",
    })
    claims = HelmJSONAdapter().extract_claims(source, SNAP, _raw(data))
    assert len(claims) == 1
    assert claims[0].model_raw == "gpt-4"
    assert claims[0].score_raw == "0.99"
    assert claims[0].metric_raw == "accuracy"
    assert claims[0].split_raw == "dev"


def test_helm_json_shape2_skip_non_numeric():
    """Stats with null or non-numeric mean should be skipped."""
    data = [
        {"run_spec": {"adapter_spec": {"model": "m"}}, "stats": [
            {"name": {"name": "exact_match", "split": "test"}, "mean": None},
            {"name": {"name": "f1_score", "split": "test"}, "mean": "n/a"}]}
    ]
    source = _make_source()
    claims = HelmJSONAdapter().extract_claims(source, SNAP, _raw(data))
    assert len(claims) == 0



# ---------------------------------------------------------------------------
# Shape 1: described groups/runs/metrics format
# ---------------------------------------------------------------------------


def test_helm_json_shape1_groups():
    """Top-level 'groups' key, runs with metrics list."""
    data = {
        "groups": [
            {"runs": [{"run_name": "shape1-model", "metrics": [
                {"name": "accuracy", "value": 88.5},
                {"name": "precision", "value": 90.0}]}]}
        ]
    }
    source = _make_source()
    claims = HelmJSONAdapter().extract_claims(source, SNAP, _raw(data))
    assert len(claims) == 2
    assert claims[0].model_raw == "shape1-model"
    assert claims[0].score_raw == "88.5"
    assert claims[0].metric_raw == "accuracy"
    assert claims[1].score_raw == "90.0"
    assert claims[1].metric_raw == "precision"


def test_helm_json_shape1_custom_model_field():
    """Shape 1 with custom model_field in parser_config."""
    data = {
        "groups": [
            {"runs": [{"model_id": "custom-model", "metrics": [
                {"name": "accuracy", "value": 77.7}]}]}
        ]
    }
    source = _make_source(parser_config={"model_field": "model_id"})
    claims = HelmJSONAdapter().extract_claims(source, SNAP, _raw(data))
    assert len(claims) == 1
    assert claims[0].model_raw == "custom-model"
    assert claims[0].score_raw == "77.7"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_helm_json_validate_claim_pass():
    raw = _raw({"groups": [{"runs": [
        {"run_name": "m", "metrics": [{"name": "acc", "value": 99}]}]}]})
    claim = HelmJSONAdapter().extract_claims(_make_source(), SNAP, raw)[0]
    validations = HelmJSONAdapter().validate_claim(claim, raw)
    assert len(validations) == 1
    assert validations[0].validation_type == "helm_json_match"
    assert validations[0].outcome == "pass"
    assert validations[0].validator == "HelmJSONAdapter"


def test_helm_json_validate_claim_uncertain():
    raw = _raw({"groups": [{"runs": [
        {"run_name": "m", "metrics": [{"name": "acc", "value": 99}]}]}]})
    claim = HelmJSONAdapter().extract_claims(_make_source(), SNAP, raw)[0]
    validations = HelmJSONAdapter().validate_claim(claim, b"different")
    assert len(validations) == 1
    assert validations[0].validation_type == "helm_json_match"
    assert validations[0].outcome == "uncertain"

