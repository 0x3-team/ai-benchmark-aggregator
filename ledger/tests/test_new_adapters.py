from pathlib import Path

from app.db.models import SourceSnapshot
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
    assert HFDatasetsServerAdapter().validate_claim(claims[0], raw)[0].outcome == "pass"


def test_lmsys_arena_api_adapter():
    raw = (Path(__file__).parent / "fixtures/lmsys_arena_sample.json").read_bytes()
    source = OfficialSource(
        id="lmsys_test",
        source_name="lmsys_test",
        source_url="https://example.com",
        source_type="api",
        officialness_level="O5",
        benchmark_id="chatbot_arena",
        parser_config={},
    )
    claims = LMSYSArenaAPIAdapter().extract_claims(source, SNAP, raw)
    assert len(claims) == 2
    assert claims[0].model_raw == "model-a"
    assert claims[0].score_raw == "1200"
    assert claims[0].metric_raw == "Elo"
    assert LMSYSArenaAPIAdapter().validate_claim(claims[0], raw)[0].outcome == "pass"


def test_artificial_analysis_api_adapter():
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
    claims = ArtificialAnalysisAPIAdapter().extract_claims(source, SNAP, raw)
    assert len(claims) == 2
    assert claims[0].model_raw == "model-a"
    assert claims[0].score_raw == "85.5"
    assert claims[0].metric_raw == "Intelligence Index"
    assert ArtificialAnalysisAPIAdapter().validate_claim(claims[0], raw)[0].outcome == "pass"


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
    assert SWEBenchAdapter().validate_claim(claims[0], raw)[0].outcome == "pass"


def test_livecodebench_adapter():
    raw = b"""{
        "models": [{"model_repr": "Model-X"}],
        "performances": [{"model": "Model-X", "pass@1": 75.0, "date": 100}],
        "date_marks": [100]
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
    assert LiveCodeBenchAdapter().validate_claim(claims[0], raw)[0].outcome == "pass"


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

