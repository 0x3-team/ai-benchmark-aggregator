from pathlib import Path

import pytest
import yaml

from app.ingestion.policy import can_ingest_source, source_admission_reason
from app.schemas.boundary import OfficialSource


def _governance() -> dict[str, object]:
    return {
        "production_eligible": True,
        "result_kind": "reported_result",
        "direct_source_only": True,
    }


def test_policy_rejects_o0_even_with_governance():
    s = OfficialSource(
        id="x",
        source_name="blog",
        source_url="https://example.com",
        source_type="api",
        officialness_level="O0",
        status="active",
        machine_readable=True,
        parser_config={"governance": _governance()},
    )
    assert can_ingest_source(s) is False


def test_policy_accepts_only_explicit_direct_result_governance():
    s = OfficialSource(
        id="x",
        source_name="api",
        source_url="https://example.com",
        source_type="api",
        officialness_level="O5",
        status="active",
        machine_readable=True,
        parser_config={"governance": _governance()},
    )
    assert can_ingest_source(s) is True


def test_policy_fails_closed_for_missing_or_unsafe_governance():
    base = {
        "id": "x",
        "source_name": "api",
        "source_url": "https://example.com/results.json",
        "source_type": "api",
        "officialness_level": "O5",
        "status": "active",
        "machine_readable": True,
    }
    cases = [
        {},
        {"governance": {"production_eligible": True}},
        {"governance": {**_governance(), "result_kind": "derived_result"}},
        {"governance": {**_governance(), "direct_source_only": False}},
        {"governance": _governance(), "mode": "discovery"},
    ]
    for parser_config in cases:
        assert can_ingest_source(OfficialSource(**base, parser_config=parser_config)) is False


def test_policy_blocks_known_unsafe_source_forms():
    base = {
        "id": "x",
        "source_name": "source",
        "officialness_level": "O5",
        "status": "active",
        "machine_readable": True,
        "parser_config": {"governance": _governance()},
    }
    cases = [
        {"source_url": "file://fixture", "source_type": "fake", "parser_name": "fake"},
        {"source_url": "https://example.com/mock", "source_type": "mock", "parser_name": "api"},
        {"source_url": "https://example.com/blog/results", "source_type": "api", "parser_name": "api"},
        {"source_url": "https://example.com/news/results", "source_type": "api", "parser_name": "api"},
        {"source_url": "https://example.com/results", "source_type": "html_table", "parser_name": "generic_html_table"},
        {"source_url": "https://example.com/results", "source_type": "api", "parser_name": "livebench_adapter"},
        {
            "source_url": "https://example.com/results",
            "source_type": "api",
            "parser_name": "api",
            "parser_config": {"governance": _governance(), "fallback_used": True},
        },
        {
            "source_url": "https://example.com/results",
            "source_type": "api",
            "parser_name": "api",
            "parser_config": {"governance": _governance(), "derived_score": True},
        },
    ]
    for case in cases:
        source_data = {**base, **case}
        assert can_ingest_source(OfficialSource(**source_data)) is False


@pytest.mark.parametrize(
    "source_url",
    [
        "https://datasets-server.huggingface.co/first-rows?dataset=owner/results",
        "https://datasets-server.huggingface.co/%66irst-rows/?dataset=owner/results",
    ],
)
def test_policy_blocks_preview_first_rows_before_an_adapter_can_treat_it_as_complete(source_url: str):
    source = OfficialSource(
        id="preview-fixture",
        source_name="Preview fixture",
        source_url=source_url,
        source_type="api",
        officialness_level="O5",
        status="active",
        machine_readable=True,
        parser_config={"governance": _governance()},
    )

    assert can_ingest_source(source) is False
    assert source_admission_reason(source) == "preview first-rows endpoint is not a complete source artifact"


def test_policy_blocks_explicit_source_terms_automation_gate():
    source = OfficialSource(
        id="terms-gated-fixture",
        source_name="Terms-gated fixture",
        source_url="https://official.example/results.json",
        source_type="static_json",
        officialness_level="O5",
        status="active",
        machine_readable=True,
        parser_config={
            "governance": _governance(),
            "automation_collection_prohibited": True,
        },
    )

    assert can_ingest_source(source) is False
    assert source_admission_reason(source) == (
        "source terms prohibit automated collection pending an owner-approved exception"
    )


@pytest.mark.parametrize(
    "source_url",
    [
        "https://arcprize.org/media/data/leaderboard/v2.json",
        "https://ARCPrize.org/media/data/leaderboard/v2%2Ejson/",
    ],
)
def test_policy_blocks_configured_arc_endpoint_even_with_governance(source_url: str):
    source = OfficialSource(
        id="arc-terms-fixture",
        source_name="ARC terms fixture",
        source_url=source_url,
        source_type="static_json",
        officialness_level="O5",
        status="active",
        machine_readable=True,
        parser_config={"governance": _governance()},
    )

    assert can_ingest_source(source) is False
    assert source_admission_reason(source) == (
        "source terms prohibit automated collection for this endpoint pending written permission"
    )


def test_current_registry_has_no_production_eligible_source():
    path = Path(__file__).resolve().parents[1] / "app" / "registry" / "official_sources.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    sources = [OfficialSource(**source) for source in raw["sources"]]
    assert sources
    assert not any(can_ingest_source(source) for source in sources)


def test_hf_discovery_registry_route_is_explicitly_retired():
    path = Path(__file__).resolve().parents[1] / "app" / "registry" / "official_sources.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    discovery = next(source for source in raw["sources"] if source["id"] == "hf_official_benchmark_discovery")
    source = OfficialSource(**discovery)

    assert source.status == "inactive"
    assert source.parser_config["mode"] == "discovery"
    assert "retirement_reason" in source.parser_config
    assert can_ingest_source(source) is False
    assert source_admission_reason(source) == "source is not active"


def test_hf_benchmark_api_has_no_active_registry_binding():
    path = Path(__file__).resolve().parents[1] / "app" / "registry" / "official_sources.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))

    active_bindings = [
        source
        for source in raw["sources"]
        if source.get("status") == "active"
        and (source.get("parser_name") == "hf_benchmark_api" or source.get("source_type") == "hf_benchmark_api")
    ]

    assert active_bindings == []


def test_hf_benchmark_adapter_remains_quarantined_outside_the_retired_source():
    source = OfficialSource(
        id="unregistered-hf-leaderboard",
        source_name="Unregistered HF leaderboard adapter route",
        source_url="https://example.invalid/leaderboard",
        source_type="hf_benchmark_api",
        officialness_level="O5",
        machine_readable=True,
        parser_name="hf_benchmark_api",
        status="active",
        parser_config={"governance": _governance(), "mode": "leaderboard"},
    )

    assert can_ingest_source(source) is False
    assert source_admission_reason(source) == "parser 'hf_benchmark_api' is quarantined"


def test_artificial_analysis_registry_route_is_explicitly_retired():
    path = Path(__file__).resolve().parents[1] / "app" / "registry" / "official_sources.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    source_data = next(source for source in raw["sources"] if source["id"] == "artificial_analysis_leaderboard")
    source = OfficialSource(**source_data)

    assert source.status == "inactive"
    assert source.parser_config["mode"] == "retired"
    assert "retirement_reason" in source.parser_config
    assert can_ingest_source(source) is False
    assert source_admission_reason(source) == "source is not active"


def test_artificial_analysis_adapter_has_no_active_registry_binding():
    path = Path(__file__).resolve().parents[1] / "app" / "registry" / "official_sources.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))

    active_bindings = [
        source
        for source in raw["sources"]
        if source.get("status") == "active" and source.get("parser_name") == "artificial_analysis_api"
    ]

    assert active_bindings == []


def test_artificial_analysis_adapter_remains_quarantined_outside_the_retired_source():
    source = OfficialSource(
        id="unregistered-artificial-analysis-route",
        source_name="Unregistered Artificial Analysis route",
        source_url="https://example.invalid/api/v2/language/models",
        source_type="api",
        officialness_level="O5",
        machine_readable=True,
        parser_name="artificial_analysis_api",
        status="active",
        parser_config={"governance": _governance()},
    )

    assert can_ingest_source(source) is False
    assert source_admission_reason(source) == "parser 'artificial_analysis_api' is quarantined"


def test_lmsys_arena_registry_route_is_explicitly_retired():
    path = Path(__file__).resolve().parents[1] / "app" / "registry" / "official_sources.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    source_data = next(source for source in raw["sources"] if source["id"] == "lmsys_arena_leaderboard")
    source = OfficialSource(**source_data)

    assert source.status == "inactive"
    assert source.parser_config["mode"] == "retired"
    assert "retirement_reason" in source.parser_config
    assert can_ingest_source(source) is False
    assert source_admission_reason(source) == "source is not active"


def test_lmsys_arena_adapter_has_no_active_registry_binding():
    path = Path(__file__).resolve().parents[1] / "app" / "registry" / "official_sources.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))

    active_bindings = [
        source
        for source in raw["sources"]
        if source.get("status") == "active" and source.get("parser_name") == "lmsys_arena_api"
    ]

    assert active_bindings == []


def test_lmsys_arena_adapter_remains_quarantined_outside_the_retired_source():
    source = OfficialSource(
        id="unregistered-lmsys-arena-route",
        source_name="Unregistered LMSYS Arena route",
        source_url="https://example.invalid/leaderboard",
        source_type="api",
        officialness_level="O5",
        machine_readable=True,
        parser_name="lmsys_arena_api",
        status="active",
        parser_config={"governance": _governance()},
    )

    assert can_ingest_source(source) is False
    assert source_admission_reason(source) == "parser 'lmsys_arena_api' is quarantined"


def test_fake_fixture_registry_route_is_explicitly_retired():
    path = Path(__file__).resolve().parents[1] / "app" / "registry" / "official_sources.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    source_data = next(source for source in raw["sources"] if source["id"] == "fake_local_fixture")
    source = OfficialSource(**source_data)

    assert source.status == "inactive"
    assert source.parser_config["mode"] == "retired"
    assert "retirement_reason" in source.parser_config
    assert can_ingest_source(source) is False
    assert source_admission_reason(source) == "source is not active"


def test_fake_adapter_has_no_active_registry_binding():
    path = Path(__file__).resolve().parents[1] / "app" / "registry" / "official_sources.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))

    active_bindings = [
        source
        for source in raw["sources"]
        if source.get("status") == "active"
        and (source.get("parser_name") == "fake" or source.get("source_type") == "fake")
    ]

    assert active_bindings == []


def test_fake_adapter_remains_quarantined_outside_the_retired_source():
    source = OfficialSource(
        id="unregistered-fake-route",
        source_name="Unregistered fake route",
        source_url="file://fixture",
        source_type="fake",
        officialness_level="O5",
        machine_readable=True,
        parser_name="fake",
        status="active",
        parser_config={"mode": "test_fixture_only", "governance": _governance()},
    )

    assert can_ingest_source(source) is False
    assert source_admission_reason(source) == "source type 'fake' is quarantined"


def test_livebench_registry_route_is_explicitly_retired():
    path = Path(__file__).resolve().parents[1] / "app" / "registry" / "official_sources.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    source_data = next(source for source in raw["sources"] if source["id"] == "livebench_leaderboard")
    source = OfficialSource(**source_data)

    assert source.status == "inactive"
    assert source.parser_config["mode"] == "retired"
    assert "retirement_reason" in source.parser_config
    assert can_ingest_source(source) is False
    assert source_admission_reason(source) == "source is not active"


def test_livebench_adapter_has_no_active_registry_binding():
    path = Path(__file__).resolve().parents[1] / "app" / "registry" / "official_sources.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))

    active_bindings = [
        source
        for source in raw["sources"]
        if source.get("status") == "active" and source.get("parser_name") == "livebench_adapter"
    ]

    assert active_bindings == []


def test_livebench_adapter_remains_quarantined_outside_the_retired_source():
    source = OfficialSource(
        id="unregistered-livebench-route",
        source_name="Unregistered LiveBench route",
        source_url="https://example.invalid/",
        source_type="api",
        officialness_level="O4",
        machine_readable=True,
        parser_name="livebench_adapter",
        status="active",
        parser_config={"governance": _governance()},
    )

    assert can_ingest_source(source) is False
    assert source_admission_reason(source) == "parser 'livebench_adapter' is quarantined"


def test_livecodebench_registry_route_is_explicitly_retired():
    path = Path(__file__).resolve().parents[1] / "app" / "registry" / "official_sources.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    source_data = next(source for source in raw["sources"] if source["id"] == "livecodebench_official_leaderboard")
    source = OfficialSource(**source_data)

    assert source.status == "inactive"
    assert source.parser_config["mode"] == "retired"
    assert "retirement_reason" in source.parser_config
    assert can_ingest_source(source) is False
    assert source_admission_reason(source) == "source is not active"


def test_livecodebench_adapter_has_no_active_registry_binding():
    path = Path(__file__).resolve().parents[1] / "app" / "registry" / "official_sources.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))

    active_bindings = [
        source
        for source in raw["sources"]
        if source.get("status") == "active" and source.get("parser_name") == "livecodebench_adapter"
    ]

    assert active_bindings == []


def test_livecodebench_adapter_remains_quarantined_outside_the_retired_source():
    source = OfficialSource(
        id="unregistered-livecodebench-route",
        source_name="Unregistered LiveCodeBench route",
        source_url="https://example.invalid/",
        source_type="api",
        officialness_level="O4",
        machine_readable=True,
        parser_name="livecodebench_adapter",
        status="active",
        parser_config={"governance": _governance()},
    )

    assert can_ingest_source(source) is False
    assert source_admission_reason(source) == "parser 'livecodebench_adapter' is quarantined"


def test_taubench_registry_route_is_explicitly_retired():
    path = Path(__file__).resolve().parents[1] / "app" / "registry" / "official_sources.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    source_data = next(source for source in raw["sources"] if source["id"] == "tau_bench_s3")
    source = OfficialSource(**source_data)

    assert source.status == "inactive"
    assert source.parser_config["mode"] == "retired"
    assert "retirement_reason" in source.parser_config
    assert can_ingest_source(source) is False
    assert source_admission_reason(source) == "source is not active"


def test_taubench_adapter_has_no_active_registry_binding():
    path = Path(__file__).resolve().parents[1] / "app" / "registry" / "official_sources.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))

    active_bindings = [
        source
        for source in raw["sources"]
        if source.get("status") == "active"
        and (source.get("parser_name") == "taubench_s3" or source.get("source_type") == "taubench_s3")
    ]

    assert active_bindings == []


def test_taubench_adapter_remains_quarantined_outside_the_retired_source():
    source = OfficialSource(
        id="unregistered-taubench-route",
        source_name="Unregistered TauBench route",
        source_url="https://example.invalid/",
        source_type="taubench_s3",
        officialness_level="O1",
        machine_readable=True,
        parser_name="taubench_s3",
        status="active",
        parser_config={"governance": _governance()},
    )

    assert can_ingest_source(source) is False
    assert source_admission_reason(source) == "parser 'taubench_s3' is quarantined"
