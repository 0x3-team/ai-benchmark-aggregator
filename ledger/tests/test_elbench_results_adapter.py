from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.db.models import SourceSnapshot
from app.ingestion.adapters import ADAPTERS, get_adapter
from app.ingestion.adapters.elbench_results import (
    ElBenchResultsAdapter,
    ElBenchResultsBatchError,
)
from app.ingestion.safe_fetch import SafeFetchError
from app.schemas.boundary import OfficialSource


SNAPSHOT = SourceSnapshot(
    id="44444444-4444-4444-4444-444444444444",
    official_source_id="elbench-fixture",
    raw_content_uri="memory://elbench-results.json",
    content_hash="b" * 64,
)
FIXTURE = Path(__file__).parent / "fixtures" / "elbench_results_aggregate_fixture.json"


def _source(*, expected_row_count: int = 1, status: str = "inactive", **config: object) -> OfficialSource:
    return OfficialSource(
        id="elbench-fixture",
        benchmark_id="elbench",
        source_name="ELBench aggregate fixture candidate",
        source_url=(
            "https://huggingface.co/datasets/ZeroLoss-Lab/ELBench-results/resolve/"
            "86ca44d147899fdb7ef40448c0cae50334aa10b4/"
            "audit-judge-integrity/leaderboard_FINAL.json"
        ),
        source_type="elbench_results",
        officialness_level="O4",
        status=status,
        parser_config={
            "mode": "fixture_candidate_only",
            "expected_row_count": expected_row_count,
            **config,
        },
    )


def _fixture() -> bytes:
    return FIXTURE.read_bytes()


def _payload() -> dict[str, object]:
    return json.loads(_fixture())


def _raw(payload: object) -> bytes:
    return json.dumps(payload, separators=(",", ":")).encode("utf-8")


def test_extracts_exact_aggregate_fields_with_typed_replayable_evidence() -> None:
    claims = ElBenchResultsAdapter().extract_claims(_source(), SNAPSHOT, _fixture())

    assert [(claim.metric_raw, claim.score_raw) for claim in claims] == [
        ("General Capability", "91.86"),
        ("Safety & Trustworthiness", "75.75"),
        ("Basic Education", "92.7"),
        ("High-Level Educational Cultivation", "69.5"),
        ("Historical Overall (source-reported)", "77.38"),
        ("Corrected Overall", "82.45"),
    ]
    assert [claim.score_numeric for claim in claims] == [91.86, 75.75, 92.7, 69.5, 77.38, 82.45]
    assert all(claim.model_raw == "claude-opus-4-8" for claim in claims)
    assert all(claim.model_entity_id is None for claim in claims)
    assert all(claim.capture_status == "unreviewed" for claim in claims)
    assert all(claim.capture_confidence == 0.0 for claim in claims)
    assert claims[0].evidence_location == {
        "type": "json_path_v1",
        "record_path": "$.rows[0]",
        "fields": {"model_raw": "model", "score_raw": "gen"},
    }
    assert claims[-1].evidence_location["fields"]["score_raw"] == "ovr_new"


def test_historical_overall_is_explicit_and_rank_maps_never_emit_scores() -> None:
    claims = ElBenchResultsAdapter().extract_claims(_source(), SNAPSHOT, _fixture())

    assert {claim.metric_raw for claim in claims} == {
        "General Capability",
        "Safety & Trustworthiness",
        "Basic Education",
        "High-Level Educational Cultivation",
        "Historical Overall (source-reported)",
        "Corrected Overall",
    }
    assert all(claim.score_raw not in {"1", "2"} for claim in claims)


def test_replay_is_identical_and_re_resolves_each_exact_lexeme() -> None:
    adapter = ElBenchResultsAdapter()
    first = adapter.extract_claims(_source(), SNAPSHOT, _fixture())
    replay = adapter.extract_claims(_source(), SNAPSHOT, _fixture())

    assert first == replay
    assert all(adapter.validate_claim(claim, _fixture())[0].outcome == "pass" for claim in first)
    assert adapter.validate_claim(first[0].model_copy(update={"score_raw": "91.860"}), _fixture())[0].outcome == "uncertain"
    assert adapter.validate_claim(
        first[-1].model_copy(update={"metric_raw": "Corrected Overall (invented)"}), _fixture()
    )[0].outcome == "uncertain"


def test_adapter_is_registered_but_refuses_non_fixture_or_active_sources() -> None:
    adapter = ElBenchResultsAdapter()

    assert ADAPTERS["elbench_results"] is ElBenchResultsAdapter
    assert type(get_adapter("elbench_results")) is ElBenchResultsAdapter
    assert adapter.extract_claims(
        _source(mode="not_fixture_candidate_only"), SNAPSHOT, _fixture()
    ) == []
    assert adapter.extract_claims(_source(status="active"), SNAPSHOT, _fixture()) == []
    with pytest.raises(SafeFetchError, match="FETCH_PLAN_REQUIRED"):
        adapter.fetch(_source())


@pytest.mark.parametrize(
    ("raw", "source", "reason_code"),
    [
        (b"not json", _source(), "JSON_MALFORMED"),
        (_raw({"rows": []}), _source(), "ROOT_SHAPE_INVALID"),
        (_raw({**_payload(), "samples": []}), _source(), "ROOT_SHAPE_INVALID"),
        (
            _raw({**_payload(), "rows": [{**_payload()["rows"][0], "gen": None}]}),
            _source(),
            "SCORE_NOT_NUMERIC",
        ),
        (
            _raw({**_payload(), "rows": [{**_payload()["rows"][0], "gen": "NaN"}]}),
            _source(),
            "SCORE_NOT_FINITE",
        ),
        (
            _raw({**_payload(), "rows": [{**_payload()["rows"][0], "gen": "91.86%"}]}),
            _source(),
            "SCORE_NOT_NUMERIC",
        ),
        (
            _raw({**_payload(), "rows": [_payload()["rows"][0], _payload()["rows"][0]]}),
            _source(expected_row_count=2),
            "DUPLICATE_MODEL",
        ),
    ],
)
def test_malformed_or_unsafe_aggregate_data_quarantines_the_entire_batch(
    raw: bytes, source: OfficialSource, reason_code: str
) -> None:
    with pytest.raises(ElBenchResultsBatchError) as raised:
        ElBenchResultsAdapter().extract_claims(source, SNAPSHOT, raw)

    assert raised.value.reason_code == reason_code


def test_complete_accounting_requires_each_row_and_context_rank_map() -> None:
    payload = _payload()
    row = payload["rows"][0]
    payload["rows"] = [row, {**row, "model": "unresolved-elbench-system"}]
    payload["old_rank"] = {"claude-opus-4-8": 1, "unresolved-elbench-system": 2}
    payload["new_rank"] = {"claude-opus-4-8": 1, "unresolved-elbench-system": 2}
    claims = ElBenchResultsAdapter().extract_claims(_source(expected_row_count=2), SNAPSHOT, _raw(payload))

    assert len(claims) == 12
    assert {claim.model_raw for claim in claims} == {"claude-opus-4-8", "unresolved-elbench-system"}
    assert all(claim.model_entity_id is None for claim in claims)

    payload["new_rank"] = {"claude-opus-4-8": 1}
    with pytest.raises(ElBenchResultsBatchError) as raised:
        ElBenchResultsAdapter().extract_claims(_source(expected_row_count=2), SNAPSHOT, _raw(payload))
    assert raised.value.reason_code == "RANK_CONTEXT_INVALID"


@pytest.mark.parametrize(
    "rank_map",
    [
        {"claude-opus-4-8": 1, "unresolved-elbench-system": 1},
        {"claude-opus-4-8": 1, "unresolved-elbench-system": 3},
    ],
)
def test_rank_context_requires_each_rank_map_to_be_a_complete_permutation(
    rank_map: dict[str, int]
) -> None:
    payload = _payload()
    row = payload["rows"][0]
    payload["rows"] = [row, {**row, "model": "unresolved-elbench-system"}]
    payload["old_rank"] = rank_map
    payload["new_rank"] = {"claude-opus-4-8": 1, "unresolved-elbench-system": 2}

    with pytest.raises(ElBenchResultsBatchError) as raised:
        ElBenchResultsAdapter().extract_claims(_source(expected_row_count=2), SNAPSHOT, _raw(payload))

    assert raised.value.reason_code == "RANK_CONTEXT_INVALID"


def test_bounds_reject_oversized_artifacts_and_more_than_nine_rows() -> None:
    adapter = ElBenchResultsAdapter()
    with pytest.raises(ElBenchResultsBatchError) as raised:
        adapter.extract_claims(_source(), SNAPSHOT, b" " * 4_097)
    assert raised.value.reason_code == "ARTIFACT_BYTES_EXCEEDED"

    payload = _payload()
    row = payload["rows"][0]
    models = [
        {**row, "model": f"fixture-model-{index}"}
        for index in range(10)
    ]
    payload["rows"] = models
    payload["old_rank"] = {row["model"]: index + 1 for index, row in enumerate(models)}
    payload["new_rank"] = {row["model"]: index + 1 for index, row in enumerate(models)}
    with pytest.raises(ElBenchResultsBatchError) as raised:
        adapter.extract_claims(_source(expected_row_count=9), SNAPSHOT, _raw(payload))
    assert raised.value.reason_code == "ROW_LIMIT_EXCEEDED"
