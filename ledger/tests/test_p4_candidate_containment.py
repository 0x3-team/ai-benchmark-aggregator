from pathlib import Path

import yaml

from app.ingestion.policy import source_admission_reason
from app.schemas.boundary import OfficialSource

REGISTRY = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "registry"
    / "official_sources.yaml"
)


def _registry_sources() -> dict[str, OfficialSource]:
    manifest = yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))
    return {row["id"]: OfficialSource(**row) for row in manifest["sources"]}


def test_p4_candidate_documents_do_not_admit_current_registry_routes() -> None:
    sources = _registry_sources()

    assert source_admission_reason(sources["bigcodebench_leaderboard"]) == (
        "preview first-rows endpoint is not a complete source artifact"
    )
    assert source_admission_reason(sources["mteb_leaderboard"]) == (
        "preview first-rows endpoint is not a complete source artifact"
    )
    assert source_admission_reason(sources["swe_bench_verified_official_leaderboard"]) == (
        "missing governance declaration"
    )


def test_lmarena_replacement_candidate_does_not_revive_retired_route() -> None:
    source = _registry_sources()["lmsys_arena_leaderboard"]

    assert source.status == "inactive"
    assert source.parser_name == "lmsys_arena_api"
    assert source.parser_config["mode"] == "retired"
    assert source_admission_reason(source) == "source is not active"
