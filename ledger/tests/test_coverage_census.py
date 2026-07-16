from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any, Callable
from urllib.parse import quote

import pytest
import yaml
from alembic import command

from app.db.migrate import _alembic_config, initialize_database, inspect_database
from app.reporting.coverage_census import (
    CoverageCensusError,
    _registry_semantic_digest,
    build_coverage_census,
    canonical_coverage_json,
    coverage_census_digest,
    render_coverage_markdown,
    validate_coverage_census,
)


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def _sha256_json(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode()).hexdigest()


def _semantic_rows_digest(rows: list[object]) -> str:
    semantic_rows: list[object] = []
    for value in rows:
        row = deepcopy(value)
        if isinstance(row, dict) and isinstance(row.get("aliases"), list):
            row["aliases"] = sorted(row["aliases"], key=_canonical_json)
        semantic_rows.append(row)
    semantic_rows.sort(
        key=lambda row: (
            row.get("id", "") if isinstance(row, dict) else "",
            _canonical_json(row),
        )
    )
    return _sha256_json(semantic_rows)


def _self_digest(document: dict[str, Any]) -> str:
    candidate = deepcopy(document)
    candidate["manifest"]["contentSha256"] = None
    return _sha256_json(candidate)


def _write_yaml(path: Path, value: object) -> None:
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")


def _default_benchmarks() -> list[dict[str, Any]]:
    return [
        {
            "id": "benchmark_one",
            "canonical_name": "Benchmark One",
            "status": "active",
            "aliases": ["Benchmark One"],
        }
    ]


def _default_sources() -> list[dict[str, Any]]:
    return [
        {
            "id": "source_one",
            "benchmark_id": "benchmark_one",
            "source_name": "Source One",
            "source_url": "https://example.invalid/results.json",
            "source_type": "json",
            "status": "active",
            "parser_config": {"fallback_priority": ["primary", "secondary"]},
        }
    ]


def _default_models() -> list[dict[str, Any]]:
    return [
        {
            "id": "Provider/Model-X",
            "canonical_name": "Model X",
            "status": "active",
            "aliases": ["Model X"],
        }
    ]


def _universe_document(
    *,
    benchmark_rows: list[object],
    source_rows: list[object],
    universe_benchmark_ids: list[str] | None = None,
    universe_sources: list[dict[str, str]] | None = None,
    approval_status: str = "owner_approved",
) -> dict[str, Any]:
    if universe_benchmark_ids is None:
        universe_benchmark_ids = sorted(
            {
                row["id"]
                for row in benchmark_rows
                if isinstance(row, dict) and isinstance(row.get("id"), str)
            }
        )
    if universe_sources is None:
        universe_sources = [
            {
                "sourceRouteId": row["id"],
                "benchmarkId": row["benchmark_id"],
                "registryStatus": row["status"],
            }
            for row in source_rows
            if isinstance(row, dict)
            and all(isinstance(row.get(key), str) for key in ("id", "benchmark_id", "status"))
            and row["benchmark_id"] in universe_benchmark_ids
        ]
    document: dict[str, Any] = {
        "schemaVersion": "1.0.0",
        "policyVersion": "coverage-universe-v1",
        "availability": "coverage_definition_only",
        "universeRevisionId": "test-universe-v1",
        "supersedesUniverseRevisionId": None,
        "effectiveOn": "2026-07-15" if approval_status == "owner_approved" else None,
        "decisionReference": "coverage-owner-decision-1"
        if approval_status == "owner_approved"
        else None,
        "authority": {
            "classification": "coverage_definition_only",
            "approvalStatus": approval_status,
            "certifiesSources": False,
            "authorizesCapture": False,
            "authorizesPublication": False,
            "frontendLoadable": False,
        },
        "manifest": {
            "algorithm": "sha256-canonical-json-v1",
            "contentSha256": None,
            "benchmarkCount": len(universe_benchmark_ids),
            "configuredSourceRouteCount": len(universe_sources),
            "sourceClassCount": 1,
            "exclusionCount": 0,
        },
        "scope": {
            "name": "Test bounded coverage",
            "boundedStatement": "Fixture-only bounded registry coverage.",
            "internetComplete": False,
            "registryInputs": [
                {
                    "inputPath": "ledger/app/registry/benchmarks*.yaml",
                    "recordType": "benchmark",
                    "selectionRule": "all_unique_stable_ids",
                    "expectedUniqueCount": len(
                        {
                            row["id"]
                            for row in benchmark_rows
                            if isinstance(row, dict) and isinstance(row.get("id"), str)
                        }
                    ),
                    "semanticSha256": _semantic_rows_digest(benchmark_rows),
                },
                {
                    "inputPath": "ledger/app/registry/official_sources.yaml",
                    "recordType": "configured_source_route",
                    "selectionRule": "all_unique_stable_ids",
                    "expectedUniqueCount": len(
                        {
                            row["id"]
                            for row in source_rows
                            if isinstance(row, dict) and isinstance(row.get("id"), str)
                        }
                    ),
                    "semanticSha256": _semantic_rows_digest(source_rows),
                },
            ],
        },
        "cohorts": [
            {
                "cohortId": "test-cohort",
                "name": "Test cohort",
                "purpose": "Fixture coverage",
                "memberBenchmarkIds": list(universe_benchmark_ids),
            }
        ],
        "benchmarks": [
            {
                "benchmarkId": benchmark_id,
                "coverageStatus": "configured",
                "reasonCode": "TEST_BOUNDED_BENCHMARK",
                "cohortIds": ["test-cohort"],
            }
            for benchmark_id in universe_benchmark_ids
        ],
        "configuredSourceRoutes": [
            {
                **source,
                "coverageStatus": "configured",
                "reasonCode": "TEST_BOUNDED_SOURCE",
            }
            for source in universe_sources
        ],
        "sourceClasses": [
            {
                "sourceClassId": "official-structured-file",
                "priority": 1,
                "methodFamily": "Official structured file",
                "candidateUse": "Fixture-only candidate location",
                "discoveryOnly": False,
                "captureRequiresSeparateCertification": True,
                "publicationRequiresSeparateDecision": True,
            }
        ],
        "refreshPolicy": {
            "discoveryPlanningCadence": "PT12H",
            "registryReconciliationCadence": "P1D",
            "coverageOwnerReviewCadence": "P30D",
            "stalenessThreshold": "P30D",
            "termsReviewPolicy": "Separate terms review.",
            "sourceRecheckAuthority": "separate_certified_source_contract_only",
        },
        "exclusions": [],
        "publicWording": {
            "coverageLabel": "Bounded test coverage",
            "scopeStatement": "One fixture benchmark and route.",
            "requiredDisclaimer": "Configured is not certified or published.",
            "forbiddenClaims": ["all internet benchmarks"],
        },
    }
    document["manifest"]["contentSha256"] = _self_digest(document)
    return document


def _make_fixture(
    tmp_path: Path,
    *,
    benchmarks: list[object] | None = None,
    sources: list[object] | None = None,
    models: list[object] | None = None,
    universe_benchmark_ids: list[str] | None = None,
    universe_sources: list[dict[str, str]] | None = None,
    approval_status: str = "owner_approved",
) -> tuple[Path, Path]:
    benchmark_rows = deepcopy(benchmarks if benchmarks is not None else _default_benchmarks())
    source_rows = deepcopy(sources if sources is not None else _default_sources())
    model_rows = deepcopy(models if models is not None else _default_models())
    registry_dir = tmp_path / "registry"
    registry_dir.mkdir()
    _write_yaml(registry_dir / "benchmarks.yaml", {"benchmarks": benchmark_rows})
    _write_yaml(registry_dir / "models.yaml", {"models": model_rows})
    _write_yaml(registry_dir / "official_sources.yaml", {"sources": source_rows})
    universe = _universe_document(
        benchmark_rows=benchmark_rows,
        source_rows=source_rows,
        universe_benchmark_ids=universe_benchmark_ids,
        universe_sources=universe_sources,
        approval_status=approval_status,
    )
    universe_path = registry_dir / "coverage_universe.yaml"
    _write_yaml(universe_path, universe)
    return registry_dir, universe_path


def _redigest(report: dict[str, Any]) -> None:
    report["manifest"]["contentSha256"] = coverage_census_digest(report)


def _remove_issue(report: dict[str, Any], reason_code: str) -> None:
    report["issues"] = [
        issue for issue in report["issues"] if issue["reasonCode"] != reason_code
    ]
    report["manifest"]["denominators"]["issueCount"] = len(report["issues"])
    counts: dict[str, int] = {}
    for issue in report["issues"]:
        counts[issue["reasonCode"]] = counts.get(issue["reasonCode"], 0) + 1
    report["summary"]["reasonCounts"] = dict(sorted(counts.items()))
    report["readiness"] = "blocked" if any(issue["blocking"] for issue in report["issues"]) else "ready"
    _redigest(report)


def _fingerprint(path: Path) -> tuple[str, int, int]:
    return hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns, path.stat().st_size


def _sidecars(path: Path) -> list[Path]:
    return [Path(f"{path}{suffix}") for suffix in ("-wal", "-shm", "-journal")]


def _database_shape(path: Path) -> tuple[list[tuple[Any, ...]], dict[str, int]]:
    connection = sqlite3.connect(f"file:{quote(str(path.resolve()))}?mode=ro", uri=True)
    try:
        schema = connection.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY type, name"
        ).fetchall()
        tables = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        counts = {
            table: connection.execute(
                'SELECT COUNT(*) FROM "' + table.replace('"', '""') + '"'
            ).fetchone()[0]
            for table in tables
        }
        return schema, counts
    finally:
        connection.close()


def test_real_universe_digest_and_baseline_denominators() -> None:
    ledger_root = Path(__file__).resolve().parents[1]
    registry_dir = ledger_root / "app" / "registry"
    report = build_coverage_census(
        registry_dir=registry_dir,
        universe_path=registry_dir / "coverage_universe.yaml",
        database_url=None,
    )

    assert report["universe"]["contentSha256"] == (
        "1ffa3438cb26853ea898894b8d4566d6c694760b8cff47a886923fbae9fc8593"
    )
    assert report["universe"]["approvalStatus"] == "draft_unapproved"
    assert report["manifest"]["denominators"]["universeBenchmarkIdCount"] == 42
    assert report["manifest"]["denominators"]["sourceRowCount"] == 53
    assert report["summary"]["statusCounts"]["known"] == 53
    assert report["summary"]["certificationAssessmentStatus"] == "not_assessed"
    assert report["summary"]["certifiedSourceCount"] is None
    assert report["summary"]["publishedSourceCount"] is None
    assert report["summary"]["reasonCounts"]["UNIVERSE_REVISION_UNAPPROVED"] == 1


def test_minimal_census_is_canonical_and_preserves_arbitrary_model_id(tmp_path: Path) -> None:
    registry_dir, universe_path = _make_fixture(tmp_path)
    first = build_coverage_census(
        registry_dir=registry_dir, universe_path=universe_path, database_url=None
    )
    second = build_coverage_census(
        registry_dir=registry_dir, universe_path=universe_path, database_url=None
    )

    assert first == second
    assert first["readiness"] == "ready"
    assert first["models"][0]["stableId"] == "Provider/Model-X"
    assert first["models"][0]["modelId"] == "Provider/Model-X"
    assert first["summary"]["statusCounts"] == {
        "known": 1,
        "watched": 0,
        "candidate": 0,
        "contract_ready": 0,
        "certified": 0,
        "captured": 0,
        "reviewed": 0,
        "published": 0,
        "deferred": 0,
        "terms_blocked": 0,
        "unsupported": 0,
    }
    assert canonical_coverage_json(first) == canonical_coverage_json(
        dict(reversed(list(first.items())))
    )
    assert coverage_census_digest(first) == first["manifest"]["contentSha256"]
    markdown = render_coverage_markdown(first)
    assert "not certification" in markdown
    assert "freshness: `not_assessed`" in markdown
    assert str(tmp_path) not in markdown
    assert markdown == render_coverage_markdown(first)


def test_registry_semantic_digest_ignores_only_row_and_alias_order() -> None:
    rows = [
        {
            "id": "z",
            "status": "active",
            "aliases": ["Zulu", "Z"],
            "parser_config": {"priority": ["first", "second"]},
        },
        {"id": "a", "status": "active", "aliases": ["A"]},
    ]
    reordered = [deepcopy(rows[1]), deepcopy(rows[0])]
    reordered[1]["aliases"].reverse()
    assert _registry_semantic_digest({"sources": rows}, "sources") == _registry_semantic_digest(
        {"sources": reordered}, "sources"
    )

    ordered_list_changed = deepcopy(rows)
    ordered_list_changed[0]["parser_config"]["priority"].reverse()
    assert _registry_semantic_digest(
        {"sources": rows}, "sources"
    ) != _registry_semantic_digest({"sources": ordered_list_changed}, "sources")


@pytest.mark.parametrize(
    "bad_text",
    [
        "benchmarks: [\n",
        "benchmarks:\n  - id: benchmark_one\n    id: benchmark_two\n    status: active\n",
    ],
)
def test_malformed_or_duplicate_key_yaml_is_rejected(tmp_path: Path, bad_text: str) -> None:
    registry_dir, universe_path = _make_fixture(tmp_path)
    (registry_dir / "benchmarks.yaml").write_text(bad_text, encoding="utf-8")
    with pytest.raises(CoverageCensusError):
        build_coverage_census(
            registry_dir=registry_dir,
            universe_path=universe_path,
            database_url=None,
        )


def test_unexpected_registry_top_level_data_is_rejected(tmp_path: Path) -> None:
    registry_dir, universe_path = _make_fixture(tmp_path)
    _write_yaml(
        registry_dir / "models.yaml",
        {"models": _default_models(), "generatedAt": "mutable-and-unbound"},
    )
    with pytest.raises(CoverageCensusError):
        build_coverage_census(
            registry_dir=registry_dir,
            universe_path=universe_path,
            database_url=None,
        )


def test_duplicate_registry_ids_are_all_conflicted_without_order_selection(tmp_path: Path) -> None:
    models = [
        {"id": "duplicate/Model", "status": "active", "aliases": ["First"]},
        {"id": "duplicate/Model", "status": "inactive", "aliases": ["Second"]},
    ]
    registry_dir, universe_path = _make_fixture(tmp_path, models=models)
    report = build_coverage_census(
        registry_dir=registry_dir, universe_path=universe_path, database_url=None
    )

    assert report["readiness"] == "blocked"
    duplicate_rows = [row for row in report["models"] if row["stableId"] == "duplicate/Model"]
    assert len(duplicate_rows) == 2
    assert {row["reportDisposition"] for row in duplicate_rows} == {"conflicted"}
    assert {row["coverageStatus"] for row in duplicate_rows} == {None}
    assert {row["reasonCode"] for row in duplicate_rows} == {"DUPLICATE_REGISTRY_ID"}
    assert report["manifest"]["denominators"]["modelRowCount"] == 2
    assert report["manifest"]["denominators"]["modelUniqueIdCount"] == 1


def test_invalid_registry_id_is_preserved_but_not_promoted_to_typed_id(tmp_path: Path) -> None:
    benchmarks = [{"id": "Bad/Benchmark", "status": "active", "aliases": []}]
    registry_dir, universe_path = _make_fixture(
        tmp_path,
        benchmarks=benchmarks,
        universe_benchmark_ids=["benchmark_one"],
    )
    report = build_coverage_census(
        registry_dir=registry_dir, universe_path=universe_path, database_url=None
    )

    row = report["benchmarks"][0]
    assert row["stableId"] == "Bad/Benchmark"
    assert row["benchmarkId"] is None
    assert row["reportDisposition"] == "invalid"
    assert row["reasonCode"] == "INVALID_REGISTRY_ID"
    assert report["readiness"] == "blocked"


def test_registry_member_outside_universe_is_blocked(tmp_path: Path) -> None:
    benchmarks = _default_benchmarks() + [
        {"id": "benchmark_two", "canonical_name": "Benchmark Two", "status": "active"}
    ]
    registry_dir, universe_path = _make_fixture(
        tmp_path,
        benchmarks=benchmarks,
        universe_benchmark_ids=["benchmark_one"],
    )
    report = build_coverage_census(
        registry_dir=registry_dir, universe_path=universe_path, database_url=None
    )

    outside = next(row for row in report["benchmarks"] if row["stableId"] == "benchmark_two")
    assert outside["reportDisposition"] == "outside_universe"
    assert outside["coverageStatus"] is None
    assert outside["reasonCode"] == "REGISTRY_BENCHMARK_OUTSIDE_UNIVERSE"
    assert any(
        issue["reasonCode"] == "REGISTRY_BENCHMARK_OUTSIDE_UNIVERSE"
        and outside["rowKey"] in issue["rowKeys"]
        for issue in report["issues"]
    )


def test_source_benchmark_must_resolve_to_one_eligible_universe_benchmark(tmp_path: Path) -> None:
    benchmarks = _default_benchmarks() + [
        {"id": "benchmark_two", "canonical_name": "Benchmark Two", "status": "active"}
    ]
    sources = _default_sources()
    sources[0]["benchmark_id"] = "benchmark_two"
    universe_sources = [
        {
            "sourceRouteId": "source_one",
            "benchmarkId": "benchmark_one",
            "registryStatus": "active",
        }
    ]
    registry_dir, universe_path = _make_fixture(
        tmp_path,
        benchmarks=benchmarks,
        sources=sources,
        universe_benchmark_ids=["benchmark_one"],
        universe_sources=universe_sources,
    )
    report = build_coverage_census(
        registry_dir=registry_dir, universe_path=universe_path, database_url=None
    )

    source = report["sources"][0]
    assert source["reportDisposition"] == "conflicted"
    assert source["reasonCode"] == "SOURCE_REFERENCES_BENCHMARK_OUTSIDE_UNIVERSE"
    assert source["coverageStatus"] is None


def _rewrite_universe(
    universe_path: Path, mutation: Callable[[dict[str, Any]], None]
) -> None:
    document = yaml.safe_load(universe_path.read_text(encoding="utf-8"))
    mutation(document)
    document["manifest"]["contentSha256"] = _self_digest(document)
    _write_yaml(universe_path, document)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda universe: universe["authority"].__setitem__("authorizesPublication", True),
        lambda universe: universe["manifest"].__setitem__("benchmarkCount", 99),
        lambda universe: universe["scope"].__setitem__("internetComplete", True),
        lambda universe: universe["sourceClasses"][0].__setitem__("priority", 2),
        lambda universe: universe["refreshPolicy"].__setitem__(
            "sourceRecheckAuthority", "configured_route_is_enough"
        ),
        lambda universe: universe["publicWording"].__setitem__("forbiddenClaims", []),
        lambda universe: universe["configuredSourceRoutes"][0].__setitem__(
            "benchmarkId", "unknown_benchmark"
        ),
    ],
    ids=[
        "publication-authority",
        "manifest-denominator",
        "internet-complete",
        "source-priority",
        "recheck-authority",
        "public-wording",
        "unknown-source-benchmark",
    ],
)
def test_redigested_unsafe_universe_is_rejected(
    tmp_path: Path, mutation: Callable[[dict[str, Any]], None]
) -> None:
    registry_dir, universe_path = _make_fixture(tmp_path)
    _rewrite_universe(universe_path, mutation)

    with pytest.raises(CoverageCensusError):
        build_coverage_census(
            registry_dir=registry_dir,
            universe_path=universe_path,
            database_url=None,
        )


def test_census_consumes_canonical_universe_semantic_validator(tmp_path: Path) -> None:
    registry_dir, universe_path = _make_fixture(tmp_path)
    _rewrite_universe(
        universe_path,
        lambda universe: universe["refreshPolicy"].__setitem__(
            "discoveryPlanningCadence", "PT0H"
        ),
    )

    with pytest.raises(CoverageCensusError, match="semantic validation failed.*greater than zero"):
        build_coverage_census(
            registry_dir=registry_dir,
            universe_path=universe_path,
            database_url=None,
        )


def test_draft_universe_is_projected_and_cannot_be_redigested_ready(tmp_path: Path) -> None:
    registry_dir, universe_path = _make_fixture(tmp_path, approval_status="draft_unapproved")
    report = build_coverage_census(
        registry_dir=registry_dir, universe_path=universe_path, database_url=None
    )
    assert report["universe"]["approvalStatus"] == "draft_unapproved"
    assert report["universe"]["effectiveOn"] is None
    assert report["universe"]["decisionReference"] is None
    assert report["readiness"] == "blocked"

    tampered = deepcopy(report)
    _remove_issue(tampered, "UNIVERSE_REVISION_UNAPPROVED")
    with pytest.raises(CoverageCensusError, match="approval issue"):
        validate_coverage_census(tampered)


def test_validator_rejects_redigested_duplicate_row_relabel(tmp_path: Path) -> None:
    models = [
        {"id": "duplicate/Model", "status": "active"},
        {"id": "duplicate/Model", "status": "inactive"},
    ]
    registry_dir, universe_path = _make_fixture(tmp_path, models=models)
    report = build_coverage_census(
        registry_dir=registry_dir, universe_path=universe_path, database_url=None
    )
    report["models"][0]["reportDisposition"] = "catalogued"
    report["models"][0]["reasonCode"] = "REGISTRY_MODEL_CATALOGUED"
    _redigest(report)
    with pytest.raises(CoverageCensusError, match="Duplicate registry IDs"):
        validate_coverage_census(report)


def test_validator_rejects_redigested_rejected_row_without_issue(tmp_path: Path) -> None:
    benchmarks = _default_benchmarks() + [{"id": "benchmark_two", "status": "active"}]
    registry_dir, universe_path = _make_fixture(
        tmp_path,
        benchmarks=benchmarks,
        universe_benchmark_ids=["benchmark_one"],
    )
    report = build_coverage_census(
        registry_dir=registry_dir, universe_path=universe_path, database_url=None
    )
    _remove_issue(report, "REGISTRY_BENCHMARK_OUTSIDE_UNIVERSE")
    with pytest.raises(CoverageCensusError, match="matching blocking issue"):
        validate_coverage_census(report)


@pytest.mark.parametrize(
    ("collection", "mutation"),
    [
        ("models", lambda row: row.__setitem__("coverageStatus", "configured")),
        ("benchmarks", lambda row: row.__setitem__("coverageStatus", "omitted")),
        ("sources", lambda row: row.__setitem__("reportDisposition", "catalogued")),
    ],
)
def test_validator_rejects_redigested_disposition_matrix_bypass(
    tmp_path: Path,
    collection: str,
    mutation: Callable[[dict[str, Any]], None],
) -> None:
    registry_dir, universe_path = _make_fixture(tmp_path)
    report = build_coverage_census(
        registry_dir=registry_dir, universe_path=universe_path, database_url=None
    )
    mutation(report[collection][0])
    _redigest(report)
    with pytest.raises(CoverageCensusError):
        validate_coverage_census(report)


@pytest.mark.parametrize(
    "binding",
    ["universe_digest", "legacy_digest", "legacy_reason", "legacy_path"],
)
def test_validator_rejects_redigested_input_projection_mismatch(
    tmp_path: Path, binding: str
) -> None:
    registry_dir, universe_path = _make_fixture(tmp_path)
    report = build_coverage_census(
        registry_dir=registry_dir, universe_path=universe_path, database_url=None
    )
    inputs = {row["inputId"]: row for row in report["inputs"]}
    if binding == "universe_digest":
        inputs["coverage_universe"]["contentSha256"] = "a" * 64
    elif binding == "legacy_digest":
        inputs["legacy_database"]["contentSha256"] = "a" * 64
    elif binding == "legacy_reason":
        inputs["legacy_database"]["reasonCode"] = "CONTRADICTORY_REASON"
    else:
        inputs["legacy_database"]["relativePath"] = "contradictory.sqlite"
    _redigest(report)
    with pytest.raises(CoverageCensusError, match="bind"):
        validate_coverage_census(report)


def test_validator_rejects_malformed_legacy_shape_as_coverage_error(tmp_path: Path) -> None:
    registry_dir, universe_path = _make_fixture(tmp_path)
    report = build_coverage_census(
        registry_dir=registry_dir, universe_path=universe_path, database_url=None
    )
    del report["legacyDatabase"]["tableCounts"]
    _redigest(report)
    with pytest.raises(CoverageCensusError):
        validate_coverage_census(report)


def test_markdown_escapes_untrusted_match_text(tmp_path: Path) -> None:
    models = [
        {"id": "model-one", "status": "active", "aliases": ["<img src=x onerror=boom>"]},
        {"id": "model-two", "status": "active", "aliases": ["<img src=x onerror=boom>"]},
    ]
    registry_dir, universe_path = _make_fixture(tmp_path, models=models)
    report = build_coverage_census(
        registry_dir=registry_dir, universe_path=universe_path, database_url=None
    )
    markdown = render_coverage_markdown(report)
    assert "<img" not in markdown
    assert "&lt;img src=x onerror=boom&gt;" in markdown


def test_persisted_coverage_census_example_validates() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    example_path = repository_root / "docs" / "contracts" / "examples" / "coverage-census-v1.valid.json"
    payload = json.loads(example_path.read_text(encoding="utf-8"))

    validate_coverage_census(payload)
    assert coverage_census_digest(payload) == payload["manifest"]["contentSha256"]


def test_canonical_digest_excludes_only_its_manifest_slot(tmp_path: Path) -> None:
    registry_dir, universe_path = _make_fixture(tmp_path)
    report = build_coverage_census(
        registry_dir=registry_dir, universe_path=universe_path, database_url=None
    )
    expected = coverage_census_digest(report)
    changed_slot = deepcopy(report)
    changed_slot["manifest"]["contentSha256"] = "f" * 64
    assert coverage_census_digest(changed_slot) == expected

    changed_content = deepcopy(report)
    changed_content["summary"]["configuredActiveSourceCount"] += 1
    assert coverage_census_digest(changed_content) != expected


def test_configured_absent_database_is_blocked_without_creation(tmp_path: Path) -> None:
    fixture_root = tmp_path / "fixture"
    fixture_root.mkdir()
    registry_dir, universe_path = _make_fixture(fixture_root)
    database_path = tmp_path / "missing.sqlite"
    before_names = sorted(path.name for path in tmp_path.iterdir())

    report = build_coverage_census(
        registry_dir=registry_dir,
        universe_path=universe_path,
        database_url=f"sqlite:///{database_path}",
    )

    assert report["legacyDatabase"]["status"] == "absent"
    assert report["legacyDatabase"]["kind"] == "absent"
    assert report["legacyDatabase"]["reasonCode"] == "LEGACY_DATABASE_ABSENT"
    assert report["readiness"] == "blocked"
    assert not database_path.exists()
    assert not any(path.exists() for path in _sidecars(database_path))
    assert sorted(path.name for path in tmp_path.iterdir()) == before_names


def test_invalid_database_bytes_are_quarantined_without_mutation(tmp_path: Path) -> None:
    fixture_root = tmp_path / "fixture"
    fixture_root.mkdir()
    registry_dir, universe_path = _make_fixture(fixture_root)
    database_path = tmp_path / "invalid.sqlite"
    database_path.write_bytes(b"not a sqlite database\x00with immutable evidence bytes")
    before = _fingerprint(database_path)
    before_names = sorted(path.name for path in tmp_path.iterdir())

    report = build_coverage_census(
        registry_dir=registry_dir,
        universe_path=universe_path,
        database_url=f"sqlite:///{database_path}",
    )

    assert report["legacyDatabase"]["status"] == "quarantined_invalid"
    assert report["legacyDatabase"]["kind"] == "invalid"
    assert report["legacyDatabase"]["reasonCode"] == "LEGACY_DATABASE_INVALID"
    assert _fingerprint(database_path) == before
    assert not any(path.exists() for path in _sidecars(database_path))
    assert sorted(path.name for path in tmp_path.iterdir()) == before_names


def test_database_sidecar_state_is_rejected_without_inspection_or_mutation(tmp_path: Path) -> None:
    fixture_root = tmp_path / "fixture"
    fixture_root.mkdir()
    registry_dir, universe_path = _make_fixture(fixture_root)
    database_path = tmp_path / "sidecar.sqlite"
    connection = sqlite3.connect(database_path)
    connection.execute("CREATE TABLE evidence (id TEXT PRIMARY KEY)")
    connection.commit()
    connection.close()
    wal_path = Path(f"{database_path}-wal")
    wal_path.write_bytes(b"unaccounted-wal-state")
    before_database = _fingerprint(database_path)
    before_wal = _fingerprint(wal_path)

    report = build_coverage_census(
        registry_dir=registry_dir,
        universe_path=universe_path,
        database_url=f"sqlite:///{database_path}",
    )

    assert report["legacyDatabase"]["reasonCode"] == "LEGACY_DATABASE_SIDECAR_STATE_UNSUPPORTED"
    assert report["legacyDatabase"]["status"] == "quarantined_invalid"
    assert _fingerprint(database_path) == before_database
    assert _fingerprint(wal_path) == before_wal


def test_current_database_inspection_preserves_bytes_schema_rows_mtime_and_sidecars(
    tmp_path: Path,
) -> None:
    fixture_root = tmp_path / "fixture"
    fixture_root.mkdir()
    registry_dir, universe_path = _make_fixture(fixture_root)
    database_path = tmp_path / "current.sqlite"
    database_url = f"sqlite:///{database_path}"
    assert initialize_database(database_url).kind == "current"
    assert inspect_database(database_url).kind == "current"
    before_file = _fingerprint(database_path)
    before_shape = _database_shape(database_path)
    before_names = sorted(path.name for path in tmp_path.iterdir())
    assert not any(path.exists() for path in _sidecars(database_path))

    report = build_coverage_census(
        registry_dir=registry_dir,
        universe_path=universe_path,
        database_url=database_url,
    )

    assert report["legacyDatabase"]["status"] == "current_read_only"
    assert report["legacyDatabase"]["kind"] == "versioned"
    assert report["legacyDatabase"]["integrityOk"] is True
    assert report["legacyDatabase"]["foreignKeyViolationCount"] == 0
    assert report["legacyDatabase"]["resultClaimQuarantineCount"] == 0
    assert report["legacyDatabase"]["registrySourceIdsMissingFromDatabase"] == ["source_one"]
    assert report["legacyDatabase"]["databaseSourceIdsMissingFromRegistry"] == []
    assert _fingerprint(database_path) == before_file
    assert _database_shape(database_path) == before_shape
    assert sorted(path.name for path in tmp_path.iterdir()) == before_names
    assert not any(path.exists() for path in _sidecars(database_path))


def test_clean_legacy_database_is_quarantined_read_only_without_migration(tmp_path: Path) -> None:
    fixture_root = tmp_path / "fixture"
    fixture_root.mkdir()
    registry_dir, universe_path = _make_fixture(fixture_root)
    database_path = tmp_path / "legacy.sqlite"
    database_url = f"sqlite:///{database_path}"
    command.upgrade(_alembic_config(database_url), "0001_legacy_schema")
    connection = sqlite3.connect(database_path)
    connection.execute("DROP TABLE alembic_version")
    connection.commit()
    connection.close()
    assert inspect_database(database_url).kind == "legacy_unversioned"
    before_file = _fingerprint(database_path)
    before_shape = _database_shape(database_path)
    before_names = sorted(path.name for path in tmp_path.iterdir())

    report = build_coverage_census(
        registry_dir=registry_dir,
        universe_path=universe_path,
        database_url=database_url,
    )

    assert report["legacyDatabase"]["status"] == "quarantined_read_only"
    assert report["legacyDatabase"]["kind"] == "legacy_unversioned"
    assert report["legacyDatabase"]["reasonCode"] == "LEGACY_DATABASE_REQUIRES_MIGRATION"
    assert report["readiness"] == "blocked"
    assert _fingerprint(database_path) == before_file
    assert _database_shape(database_path) == before_shape
    assert sorted(path.name for path in tmp_path.iterdir()) == before_names
    assert not any(path.exists() for path in _sidecars(database_path))


def test_fk_invalid_database_accounts_orphans_claims_and_source_divergence_without_writes(
    tmp_path: Path,
) -> None:
    fixture_root = tmp_path / "fixture"
    fixture_root.mkdir()
    registry_dir, universe_path = _make_fixture(fixture_root)
    database_path = tmp_path / "fk-invalid.sqlite"
    connection = sqlite3.connect(database_path)
    connection.executescript(
        """
        PRAGMA foreign_keys=OFF;
        CREATE TABLE official_sources (id TEXT PRIMARY KEY);
        CREATE TABLE result_claims (id TEXT PRIMARY KEY);
        CREATE TABLE claim_validations (
          id TEXT PRIMARY KEY,
          result_claim_id TEXT REFERENCES result_claims(id)
        );
        CREATE TABLE unrelated_parent (id TEXT PRIMARY KEY);
        CREATE TABLE unrelated_child (
          id TEXT PRIMARY KEY,
          parent_id TEXT REFERENCES unrelated_parent(id)
        );
        INSERT INTO official_sources(id) VALUES ('database_only_source');
        INSERT INTO result_claims(id) VALUES ('claim-one');
        INSERT INTO claim_validations(id, result_claim_id) VALUES ('validation-one', 'missing-claim');
        INSERT INTO unrelated_child(id, parent_id) VALUES ('child-one', 'missing-parent');
        """
    )
    connection.commit()
    connection.close()
    before_file = _fingerprint(database_path)
    before_shape = _database_shape(database_path)
    before_names = sorted(path.name for path in tmp_path.iterdir())

    report = build_coverage_census(
        registry_dir=registry_dir,
        universe_path=universe_path,
        database_url=f"sqlite:///{database_path}",
    )

    legacy = report["legacyDatabase"]
    assert legacy["status"] == "quarantined_invalid"
    assert legacy["kind"] == "invalid"
    assert legacy["foreignKeyViolationCount"] == 2
    assert legacy["orphanedReferenceCount"] == 1
    assert legacy["resultClaimQuarantineCount"] == 1
    assert legacy["registrySourceIdsMissingFromDatabase"] == ["source_one"]
    assert legacy["databaseSourceIdsMissingFromRegistry"] == ["database_only_source"]
    assert report["summary"]["resultClaimQuarantineCount"] == 1
    assert report["summary"]["reasonCounts"]["LEGACY_DATABASE_FOREIGN_KEY_VIOLATIONS"] == 1
    assert report["summary"]["reasonCounts"]["LEGACY_RESULT_CLAIMS_QUARANTINED"] == 1
    assert _fingerprint(database_path) == before_file
    assert _database_shape(database_path) == before_shape
    assert sorted(path.name for path in tmp_path.iterdir()) == before_names
    assert not any(path.exists() for path in _sidecars(database_path))

    tampered = deepcopy(report)
    tampered["legacyDatabase"]["status"] = "current_read_only"
    tampered["inputs"] = [
        {**row, "inspectionStatus": "read_only"}
        if row["inputId"] == "legacy_database"
        else row
        for row in tampered["inputs"]
    ]
    _redigest(tampered)
    with pytest.raises(CoverageCensusError, match="current_read_only"):
        validate_coverage_census(tampered)
