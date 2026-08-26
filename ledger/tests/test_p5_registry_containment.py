"""P5a Certification-B registry containment.

Fail-closes ten Certification-B source routes while preserving their stable
identities and coverage-universe membership.  The test performs no network
requests: it loads the two registry YAML files and uses a disposable SQLite
database for the seeding and idempotency checks.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import socket
from typing import Any

import pytest
import yaml
from sqlalchemy import func, select

from app.db import models, repositories as repo
from app.db.engine import get_session
from app.ingestion.policy import can_ingest_source, source_admission_reason
from app.registry.seed_loader import seed_registry
from app.schemas.boundary import OfficialSource
from app.schemas.coverage_contracts import validate_coverage_universe


P5_INACTIVE_IDS = frozenset(
    {
        "aider_polyglot_yaml",
        "gaia_results_public",
        "terminal_bench_tbench_leaderboard",
        "open_llm_leaderboard_v2",
        "open_llm_leaderboard_v2_gpqa",
        "open_llm_leaderboard_v2_mmlu_pro",
        "open_llm_leaderboard_v2_math",
        "open_llm_leaderboard_v2_bbh",
        "mmlu_openllm_v2",
        "truthfulqa_openllm_v2",
    }
)

# Frozen against base 220ce272467ee99b1cb02a319a3c8277951c2f3c.  The
# fingerprints below normalize only the fields explicitly allowed by P5a:
# target source status/notes, target coverage route status/reason, and the two
# deterministic digest slots.
BASE_COMMIT = "220ce272467ee99b1cb02a319a3c8277951c2f3c"
OFFICIAL_SOURCES_BASE_FINGERPRINT = "6e866deb1736a55df244c6bae6235d96138a02a5be1f48d3f0d61140ec4c2b3f"
COVERAGE_UNIVERSE_BASE_FINGERPRINT = "37c2e686b2a7c3bc4f6109de4299044e328b02b1925f99df0904d7757ad91aaa"

CANDIDATE_WARNING = "Candidate only; not certified; capture ineligible; publication ineligible."

LOCAL_BLOCKERS: dict[str, str] = {
    "aider_polyglot_yaml": "mutable YAML route, unsupported `yaml_path`, no exact-lexeme evidence contract, governance absent",
    "gaia_results_public": "preview-only `first-rows` endpoint, not a complete artifact",
    "terminal_bench_tbench_leaderboard": "quarantined `html_table` route and no approved structured artifact",
    "open_llm_leaderboard_v2": "article/blog URLs are not result artifacts",
    "open_llm_leaderboard_v2_gpqa": "article/blog URLs are not result artifacts",
    "open_llm_leaderboard_v2_mmlu_pro": "article/blog URLs are not result artifacts",
    "open_llm_leaderboard_v2_math": "article/blog URLs are not result artifacts",
    "open_llm_leaderboard_v2_bbh": "article/blog URLs are not result artifacts",
    "mmlu_openllm_v2": "incomplete previews; nested-field and complete-manifest contracts are absent",
    "truthfulqa_openllm_v2": "incomplete previews; nested-field and complete-manifest contracts are absent",
}

REGISTRY_DIR = Path(__file__).resolve().parents[1] / "app" / "registry"
OFFICIAL_SOURCES = REGISTRY_DIR / "official_sources.yaml"
COVERAGE_UNIVERSE = REGISTRY_DIR / "coverage_universe.yaml"


def _registry_sources() -> dict[str, OfficialSource]:
    manifest = yaml.safe_load(OFFICIAL_SOURCES.read_text(encoding="utf-8"))
    return {row["id"]: OfficialSource(**row) for row in manifest["sources"]}


def _coverage_universe() -> dict[str, Any]:
    return yaml.safe_load(COVERAGE_UNIVERSE.read_text(encoding="utf-8"))


def _canonical_sha256(value: object) -> str:
    canonical = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _normalized_official_sources(document: dict[str, Any]) -> dict[str, Any]:
    normalized = deepcopy(document)
    for row in normalized["sources"]:
        if row["id"] in P5_INACTIVE_IDS:
            row["status"] = "__p5_status__"
            row["notes"] = "__p5_notes__"
    return normalized


def _normalized_coverage_universe(document: dict[str, Any]) -> dict[str, Any]:
    normalized = deepcopy(document)
    normalized["manifest"]["contentSha256"] = "__coverage_content_sha256__"
    source_pin = next(
        pin
        for pin in normalized["scope"]["registryInputs"]
        if pin["recordType"] == "configured_source_route"
    )
    source_pin["semanticSha256"] = "__source_semantic_sha256__"
    for route in normalized["configuredSourceRoutes"]:
        if route["sourceRouteId"] in P5_INACTIVE_IDS:
            route["registryStatus"] = "__p5_status__"
            route["reasonCode"] = "__p5_reason__"
    return normalized


def test_p5_official_sources_match_frozen_base_outside_allowed_fields() -> None:
    current_manifest = yaml.safe_load(OFFICIAL_SOURCES.read_text(encoding="utf-8"))
    assert _canonical_sha256(_normalized_official_sources(current_manifest)) == (
        OFFICIAL_SOURCES_BASE_FINGERPRINT
    ), f"official source registry diverged from frozen base {BASE_COMMIT}"


def test_p5_ten_ids_remain_inactive_with_candidate_warning_and_local_blocker() -> None:
    sources = _registry_sources()

    for source_id in P5_INACTIVE_IDS:
        source = sources[source_id]
        assert source.status == "inactive", f"{source_id} must be inactive"
        assert source.notes is not None, f"{source_id} must carry a notes field"
        assert CANDIDATE_WARNING in source.notes, f"{source_id} must carry the candidate-only warning"
        assert LOCAL_BLOCKERS[source_id] in source.notes, f"{source_id} must preserve its local blocker"


def test_p5_can_ingest_source_is_false_for_every_route() -> None:
    sources = _registry_sources()

    for source_id in P5_INACTIVE_IDS:
        source = sources[source_id]
        assert can_ingest_source(source) is False, f"{source_id} must not be ingestible"
        reason = source_admission_reason(source)
        assert reason is not None, f"{source_id} must have a stable rejection reason"
        assert reason == "source is not active", f"{source_id} rejection must be status-driven fail-closed"


def test_p5_coverage_universe_mirrors_inactive_routes_and_preserves_membership() -> None:
    universe = _coverage_universe()
    validate_coverage_universe(universe)

    routes = universe["configuredSourceRoutes"]
    route_by_id = {route["sourceRouteId"]: route for route in routes}

    assert universe["manifest"]["configuredSourceRouteCount"] == 53
    assert sum(route["registryStatus"] == "active" for route in routes) == 13
    for source_id in P5_INACTIVE_IDS:
        assert source_id in route_by_id, f"{source_id} must remain in coverage universe"
        route = route_by_id[source_id]
        assert route["registryStatus"] == "inactive"
        assert route["coverageStatus"] == "configured"
        assert route["reasonCode"] == "BASELINE_CONFIGURED_INACTIVE_ROUTE"

    authority = universe["authority"]
    assert authority["certifiesSources"] is False
    assert authority["authorizesCapture"] is False
    assert authority["authorizesPublication"] is False
    assert authority["frontendLoadable"] is False


def test_p5_coverage_diff_preserves_membership_and_changes_only_allowed_fields() -> None:
    current = deepcopy(_coverage_universe())
    assert _canonical_sha256(_normalized_coverage_universe(current)) == (
        COVERAGE_UNIVERSE_BASE_FINGERPRINT
    ), f"coverage universe diverged from frozen base {BASE_COMMIT}"


def test_p5_registry_active_count_is_thirteen_and_excludes_ten() -> None:
    sources = _registry_sources()
    active_ids = {source_id for source_id, source in sources.items() if source.status == "active"}
    assert active_ids.isdisjoint(P5_INACTIVE_IDS)
    assert len(active_ids) == 13


def test_p5_disposable_seeding_excludes_ten_from_active_sources_and_is_idempotent(
    tmp_db: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Seed a disposable database and prove the ten routes are absent from active
    source enumeration.  Reseeding with identical registry state must not create
    new revisions, snapshots, claims, or ingestion runs.
    """
    real_registry = REGISTRY_DIR
    monkeypatch.setattr(
        socket,
        "socket",
        lambda *_args, **_kwargs: pytest.fail("P5a containment must not open a network socket"),
    )
    monkeypatch.setattr(
        socket,
        "create_connection",
        lambda *_args, **_kwargs: pytest.fail("P5a containment must not create a network connection"),
    )
    models_path = tmp_path / "models.yaml"
    models_path.write_text(
        (real_registry / "models.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    def _counts(session) -> dict[str, int]:
        return {
            "revisions": session.scalar(select(func.count()).select_from(models.OfficialSourceRevision)) or 0,
            "snapshots": session.scalar(select(func.count()).select_from(models.SourceSnapshot)) or 0,
            "claims": session.scalar(select(func.count()).select_from(models.ResultClaim)) or 0,
            "runs": session.scalar(select(func.count()).select_from(models.IngestionRun)) or 0,
            "certified_decisions": session.scalar(
                select(func.count())
                .select_from(models.SourceRevisionDecision)
                .where(models.SourceRevisionDecision.outcome == "certified")
            )
            or 0,
        }

    with get_session() as session:
        first = seed_registry(
            session,
            benchmarks_path=real_registry / "benchmarks.yaml",
            models_path=models_path,
            sources_path=real_registry / "official_sources.yaml",
            retire_missing=False,
        )
        assert first["sources"] == 54
        assert first["source_revisions"] == 54

        active_sources = repo.list_active_sources(session)
        active_ids = {source.id for source in active_sources}
        assert active_ids.isdisjoint(P5_INACTIVE_IDS)
        assert len(active_ids) == 13

        for source_id in P5_INACTIVE_IDS:
            row = session.get(models.OfficialSourceRow, source_id)
            assert row is not None, f"{source_id} must survive seeding"
            assert row.status == "inactive", f"{source_id} must project as inactive"

        before = _counts(session)
        assert before["certified_decisions"] == 0
        assert before["claims"] == 0

        second = seed_registry(
            session,
            benchmarks_path=real_registry / "benchmarks.yaml",
            models_path=models_path,
            sources_path=real_registry / "official_sources.yaml",
            retire_missing=False,
        )
        assert second["sources"] == 54
        assert second["source_revisions"] == 0

        after = _counts(session)
        assert after == before
