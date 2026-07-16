import builtins
from pathlib import Path

import pytest

from app.db.models import SourceSnapshot
from app.ingestion.adapters import lmsys_arena_api as lmsys_arena_module
from app.ingestion.adapters.hf_datasets_server import HFDatasetsServerAdapter
from app.ingestion.adapters.lmsys_arena_api import LMSYSArenaAPIAdapter
from app.ingestion.adapters.artificial_analysis_api import ArtificialAnalysisAPIAdapter
from app.ingestion.adapters.swe_bench_adapter import SWEBenchAdapter
from app.ingestion.adapters.livecodebench_adapter import LiveCodeBenchAdapter
from app.schemas.boundary import OfficialSource

SNAP = SourceSnapshot(
    id="22222222-2222-2222-2222-222222222222",
    official_source_id="s",
    raw_content_uri="mem",
    content_hash="y",
)


def test_hf_datasets_server_adapter():
    raw = (Path(__file__).parent / "fixtures/hf_datasets_server_sample.json").read_bytes()
    source = OfficialSource(
        id="mteb_test",
        source_name="mteb_test",
        source_url="https://example.com",
        source_type="api",
        officialness_level="O4",
        benchmark_id="mteb",
        parser_config={
            "dataset_id": "mteb/results",
            "config": "default",
            "split": "train",
            "records_path": "rows",
            "row_field": "row",
            "model_field": "model_name",
            "score_field": "score",
            "metric_field": "task_name",
            "split_field": "split",
        },
    )
    claims = HFDatasetsServerAdapter().extract_claims(source, SNAP, raw)
    assert len(claims) == 2
    assert claims[0].model_raw == "model-a"
    assert claims[0].score_raw == "85.5"
    assert claims[0].metric_raw == "task-1"
    assert claims[0].score_numeric is None
    assert claims[0].evidence_location == {
        "type": "json_path_v1",
        "record_path": "$.rows[0].row",
        "fields": {
            "model_raw": "model_name",
            "score_raw": "score",
            "metric_raw": "task_name",
            "split_raw": "split",
        },
    }
    assert HFDatasetsServerAdapter().validate_claim(claims[0], raw)[0].outcome == "pass"


def test_lmsys_arena_fixture_parser_is_non_certifying_and_fetch_is_retired(monkeypatch):
    raw = (Path(__file__).parent / "fixtures/lmsys_arena_sample.json").read_bytes()
    source = OfficialSource(
        id="lmsys_test",
        source_name="lmsys_test",
        source_url="https://example.com",
        source_type="api",
        officialness_level="O5",
        benchmark_id="chatbot_arena",
        requires_auth=True,
        parser_config={"api_key_env": "LMSYS_API_KEY"},
    )
    adapter = LMSYSArenaAPIAdapter()
    claims = adapter.extract_claims(source, SNAP, raw)
    assert len(claims) == 2
    assert claims[0].model_raw == "model-a"
    assert claims[0].score_raw == "1200"
    assert claims[0].metric_raw == "Elo"
    assert claims[0].capture_status == "unreviewed"
    assert claims[0].capture_confidence == 0.0
    assert adapter.validate_claim(claims[0], raw)[0].outcome == "fail"

    # Authentication configuration must not revive the old primary/fallback
    # network path.
    monkeypatch.setenv("LMSYS_API_KEY", "fixture-only-key")
    assert "api.wulong.dev" not in Path(lmsys_arena_module.__file__).read_text(encoding="utf-8")
    original_import = builtins.__import__

    def deny_network_dependencies(name, *args, **kwargs):  # type: ignore[no-untyped-def]
        if name in {"httpx", "app.config"}:
            pytest.fail(f"retired LMSYS fetch imported {name}")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", deny_network_dependencies)
    with pytest.raises(RuntimeError, match="adapter is retired"):
        adapter.fetch(source)


def test_lmsys_arena_retired_registry_mode_emits_no_fixture_candidates():
    raw = (Path(__file__).parent / "fixtures/lmsys_arena_sample.json").read_bytes()
    source = OfficialSource(
        id="lmsys-retired-test",
        source_name="lmsys-retired-test",
        source_url="https://example.com",
        source_type="api",
        officialness_level="O5",
        benchmark_id="chatbot_arena",
        parser_config={"mode": "retired"},
    )

    assert LMSYSArenaAPIAdapter().extract_claims(source, SNAP, raw) == []


def test_artificial_analysis_fixture_parser_is_non_certifying_and_fetch_is_retired(monkeypatch):
    raw = (Path(__file__).parent / "fixtures/artificial_analysis_sample.json").read_bytes()
    source = OfficialSource(
        id="aa_test",
        source_name="aa_test",
        source_url="https://example.com",
        source_type="api",
        officialness_level="O5",
        benchmark_id="artificial_analysis",
        parser_config={},
    )
    adapter = ArtificialAnalysisAPIAdapter()
    claims = adapter.extract_claims(source, SNAP, raw)
    assert len(claims) == 2
    assert claims[0].model_raw == "model-a"
    assert claims[0].score_raw == "85.5"
    assert claims[0].metric_raw == "Intelligence Index"
    assert claims[0].capture_status == "unreviewed"
    assert claims[0].capture_confidence == 0.0
    assert adapter.validate_claim(claims[0], raw)[0].outcome == "fail"

    # A configured key must not revive a network or mock-data path.
    monkeypatch.setenv("ARTIFICIAL_ANALYSIS_API_KEY", "fixture-only-key")
    with pytest.raises(RuntimeError, match="adapter is retired"):
        adapter.fetch(source)


def test_artificial_analysis_retired_registry_mode_emits_no_fixture_candidates():
    raw = (Path(__file__).parent / "fixtures/artificial_analysis_sample.json").read_bytes()
    source = OfficialSource(
        id="aa-retired-test",
        source_name="aa-retired-test",
        source_url="https://example.com",
        source_type="api",
        officialness_level="O5",
        benchmark_id="artificial_analysis",
        parser_config={"mode": "retired"},
    )

    assert ArtificialAnalysisAPIAdapter().extract_claims(source, SNAP, raw) == []


def test_swe_bench_adapter():
    # Reuse html_table_sample but parse via swe_bench_adapter with suitable JSON data mock
    raw = b"""<html><body><script id="leaderboard-data">[{"name": "Verified", "results": [{"name": "Model-A", "resolved": 55.5}]}]</script></body></html>"""
    source = OfficialSource(
        id="swe_test",
        source_name="swe_test",
        source_url="https://example.com",
        source_type="api",
        officialness_level="O4",
        benchmark_id="swe_bench_verified",
        parser_config={"category": "Verified"},
    )
    claims = SWEBenchAdapter().extract_claims(source, SNAP, raw)
    assert len(claims) == 1
    assert claims[0].model_raw == "Model-A"
    assert claims[0].score_raw == "55.5"
    assert claims[0].metric_raw == "% Resolved"
    assert claims[0].score_numeric is None
    assert claims[0].evidence_location == {
        "type": "json_script_path_v1",
        "script_id": "leaderboard-data",
        "script_type": None,
        "record_path": "$[0].results[0]",
        "fields": {"model_raw": "name", "score_raw": "resolved"},
        "assertions": [{"path": "$[0].name", "equals": "Verified"}],
    }
    assert SWEBenchAdapter().validate_claim(claims[0], raw)[0].outcome == "pass"


def test_swe_bench_adapter_prepares_the_direct_json_artifact_shape():
    raw = b"""[
        {
            "name": "Verified",
            "results": [{"name": "Model-A", "resolved": 55.5000}]
        }
    ]"""
    source = OfficialSource(
        id="swe-direct-json-test",
        source_name="swe-direct-json-test",
        source_url="https://example.com/leaderboards.json",
        source_type="static_json",
        officialness_level="O4",
        benchmark_id="swe_bench_verified",
        parser_config={
            "artifact_format": "direct_json",
            "category": "Verified",
            "leaderboards_path": "$",
            "category_name_field": "name",
            "results_field": "results",
            "model_field": "name",
            "score_field": "resolved",
            "metric_raw": "% Resolved",
        },
    )

    claims = SWEBenchAdapter().extract_claims(source, SNAP, raw)

    assert len(claims) == 1
    assert claims[0].score_raw == "55.5000"
    assert claims[0].score_numeric is None
    assert claims[0].evidence_location == {
        "type": "json_path_v1",
        "record_path": "$[0].results[0]",
        "fields": {"model_raw": "name", "score_raw": "resolved"},
    }
    assert SWEBenchAdapter().validate_claim(claims[0], raw)[0].outcome == "pass"


def test_livecodebench_adapter():
    raw = b"""{
        "models": [{"model_repr": "Model-X"}],
        "performances": [
            {"model": "Model-X", "pass@1": 60.0, "date": 100},
            {"model": "Model-X", "pass@1": 90.0, "date": 200}
        ],
        "date_marks": [100, 200]
    }"""
    source = OfficialSource(
        id="lcb_test",
        source_name="lcb_test",
        source_url="https://example.com",
        source_type="api",
        officialness_level="O4",
        benchmark_id="livecodebench",
        parser_config={},
    )
    claims = LiveCodeBenchAdapter().extract_claims(source, SNAP, raw)
    assert len(claims) == 1
    assert claims[0].model_raw == "Model-X"
    assert claims[0].score_raw == "75.0"
    assert claims[0].metric_raw == "Pass@1"
    assert claims[0].evidence_location["type"] == "derived_analytics"
    assert claims[0].capture_status == "unreviewed"
    assert claims[0].capture_confidence == 0.0
    assert LiveCodeBenchAdapter().validate_claim(claims[0], raw)[0].outcome == "fail"


def test_github_yaml_adapter():
    from app.ingestion.adapters.github_yaml import GitHubYAMLAdapter
    raw = b"""- model: model-a
  pass_rate_2: 35.6
- model: model-b
  pass_rate_2: 45.2
"""
    source = OfficialSource(
        id="aider_test",
        source_name="aider_test",
        source_url="https://example.com",
        source_type="github_yaml",
        officialness_level="O1",
        benchmark_id="aider_polyglot",
        parser_config={"model_field": "model", "score_field": "pass_rate_2"},
    )
    claims = GitHubYAMLAdapter().extract_claims(source, SNAP, raw)
    assert len(claims) == 2
    assert claims[0].model_raw == "model-a"
    assert claims[0].score_raw == "35.6"
    assert claims[0].score_numeric == 35.6
    assert GitHubYAMLAdapter().validate_claim(claims[0], raw)[0].outcome == "pass"
