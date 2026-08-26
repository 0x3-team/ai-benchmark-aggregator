from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from app.db.models import SourceSnapshot
from app.ingestion.adapters import ADAPTERS, get_adapter
from app.ingestion.adapters.evalplus_results import (
    EvalPlusResultsAdapter,
    EvalPlusResultsBatchError,
)
from app.schemas.boundary import OfficialSource


SNAPSHOT = SourceSnapshot(
    id="33333333-3333-3333-3333-333333333333",
    official_source_id="evalplus-fixture",
    raw_content_uri="memory://evalplus-evalperf-summary.brief.json",
    content_hash="b" * 64,
)
FIXTURE = Path(__file__).parent / "fixtures" / "evalplus_evalperf_summary.brief.json"


def _source(*, status: str = "inactive", **config: object) -> OfficialSource:
    return OfficialSource(
        id="evalplus-fixture",
        benchmark_id="evalperf",
        source_name="EvalPlus EvalPerf fixture",
        source_url="https://example.invalid/results/evalperf/example_evalperf_results.brief.json",
        source_type="evalplus_results",
        officialness_level="O1",
        status=status,
        parser_config={
            "mode": "test_fixture_only",
            "model_field": "model",
            "score_fields": {"pass@1": "pass@1", "DPS": "DPS"},
            "configuration_fields": {
                "setting_raw": "evaluation_config",
                "evaluation_version_raw": "evaluation_version",
            },
            "benchmark_raw": "EvalPerf",
            **config,
        },
    )


def test_extracts_only_configured_top_level_summary_scores_with_exact_lexemes() -> None:
    raw = FIXTURE.read_bytes()

    claims = EvalPlusResultsAdapter().extract_claims(_source(), SNAPSHOT, raw)

    assert [(claim.metric_raw, claim.score_raw) for claim in claims] == [
        ("pass@1", "71.2500"),
        ("DPS", "80.0"),
    ]
    assert [claim.score_numeric for claim in claims] == [71.25, 80.0]
    assert all(claim.model_raw == "Example/EvalPerf-Model" for claim in claims)
    assert all(claim.model_entity_id is None for claim in claims)
    assert all(claim.capture_status == "needs_review" for claim in claims)
    assert all(claim.capture_confidence == 0.0 for claim in claims)
    assert claims[0].benchmark_raw == "EvalPerf"
    assert claims[0].setting_raw == "temperature=0.0,n=1"
    assert claims[0].evaluation_version_raw == "20240328"
    assert claims[0].evidence_location == {
        "type": "json_path_v1",
        "record_path": "$",
        "fields": {
            "model_raw": "model",
            "setting_raw": "evaluation_config",
            "evaluation_version_raw": "evaluation_version",
            "score_raw": "pass@1",
        },
    }
    assert all(EvalPlusResultsAdapter().validate_claim(claim, raw)[0].outcome == "pass" for claim in claims)


def test_fixture_intentionally_has_no_model_output_code() -> None:
    """Brief-result fixtures are summary/configuration only, unlike possible source files."""

    fixture_text = FIXTURE.read_text(encoding="utf-8")

    assert "solution" not in fixture_text.lower()
    assert "model_output" not in fixture_text.lower()
    assert "profile" not in fixture_text.lower()


def test_unresolved_model_identity_stays_raw_and_needs_review() -> None:
    claim = EvalPlusResultsAdapter().extract_claims(_source(), SNAPSHOT, FIXTURE.read_bytes())[0]

    assert claim.model_raw == "Example/EvalPerf-Model"
    assert claim.model_entity_id is None
    assert claim.capture_status == "needs_review"


def test_adapter_is_registered_but_requires_explicit_fixture_mode_and_never_fetches() -> None:
    adapter = EvalPlusResultsAdapter()

    assert ADAPTERS["evalplus_results"] is EvalPlusResultsAdapter
    assert type(get_adapter("evalplus_results")) is EvalPlusResultsAdapter
    assert adapter.requires_central_fetch is False
    assert adapter.extract_claims(_source(mode="inactive"), SNAPSHOT, FIXTURE.read_bytes()) == []
    with pytest.raises(EvalPlusResultsBatchError, match="CONFIG_INVALID"):
        adapter.extract_claims(_source(status="active"), SNAPSHOT, FIXTURE.read_bytes())
    with pytest.raises(RuntimeError, match="fixture-only"):
        adapter.fetch(_source())


@pytest.mark.parametrize(
    ("raw", "source", "reason_code"),
    [
        (b"{", _source(), "JSON_INVALID"),
        (b"[]", _source(), "SUMMARY_ROOT_INVALID"),
        (
            b'{"model":"Model","pass@1":null,"DPS":80.0,"evaluation_config":"n=1","evaluation_version":"v1"}',
            _source(),
            "SCORE_VALUE_MISSING",
        ),
        (
            b'{"model":"Model","pass@1":"NaN","DPS":80.0,"evaluation_config":"n=1","evaluation_version":"v1"}',
            _source(),
            "SCORE_NOT_FINITE",
        ),
        (
            b'{"model":"Model","pass@1":"not-a-score","DPS":80.0,"evaluation_config":"n=1","evaluation_version":"v1"}',
            _source(),
            "SCORE_NOT_NUMERIC",
        ),
        (
            b'{"model":"Model","pass@1":71.0,"pass@1":72.0,"DPS":80.0,"evaluation_config":"n=1","evaluation_version":"v1"}',
            _source(),
            "JSON_INVALID",
        ),
        (
            b'{"model":"Model","pass@1":71.0,"DPS":80.0,"evaluation_config":null,"evaluation_version":"v1"}',
            _source(),
            "CONFIGURATION_VALUE_MISSING",
        ),
        (
            FIXTURE.read_bytes(),
            _source(score_fields={"pass@1": "pass@1", "duplicate": "pass@1"}),
            "CONFIG_INVALID",
        ),
        (
            FIXTURE.read_bytes(),
            _source(score_fields={"pass@1": "DPS", "DPS": "DPS"}),
            "CONFIG_INVALID",
        ),
    ],
)
def test_malformed_null_nonfinite_and_duplicate_inputs_quarantine_single_file(
    raw: bytes, source: OfficialSource, reason_code: str
) -> None:
    adapter = EvalPlusResultsAdapter()

    with pytest.raises(EvalPlusResultsBatchError) as raised:
        adapter.extract_claims(source, SNAPSHOT, raw)

    assert raised.value.reason_code == reason_code


def test_fixture_byte_bound_quarantines_before_json_decoding() -> None:
    raw = b"x" * (EvalPlusResultsAdapter.MAX_FIXTURE_BYTES + 1)

    with pytest.raises(EvalPlusResultsBatchError) as raised:
        EvalPlusResultsAdapter().extract_claims(_source(), SNAPSHOT, raw)

    assert raised.value.reason_code == "RESULT_FILE_TOO_LARGE"


def test_single_file_replay_reresolves_summary_without_aggregating_profiles() -> None:
    raw = FIXTURE.read_bytes()
    adapter = EvalPlusResultsAdapter()

    first = adapter.extract_claims(_source(), SNAPSHOT, raw)
    replay = adapter.extract_claims(_source(), SNAPSHOT, raw)

    assert first == replay
    altered = first[0].model_copy(update={"score_raw": "99.0"})
    assert adapter.validate_claim(altered, raw)[0].outcome == "uncertain"
    altered_metric = first[0].model_copy(update={"metric_raw": "DPS"})
    assert adapter.validate_claim(altered_metric, raw)[0].outcome == "uncertain"
    assert adapter.validate_claim(first[0], b'{"model":"Example/EvalPerf-Model"}')[0].outcome == "uncertain"


def test_registry_contains_no_abstract_adapter_classes() -> None:
    for source_type, adapter_class in ADAPTERS.items():
        assert not inspect.isabstract(adapter_class), source_type
        assert type(get_adapter(source_type)) is adapter_class
