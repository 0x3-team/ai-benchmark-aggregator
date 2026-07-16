"""Offline contract tests for the LDR-08 candidate feed projection."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json

import pytest
from sqlalchemy import func, select
from typer.testing import CliRunner

from app.cli import app
from app.db import models, repositories as repo
from app.db.engine import get_session
from app.export.official_json import (
    FeedConflictError,
    FeedProjectionError,
    canonical_official_feed_json,
    official_feed_digest,
    project_official_feed,
    validate_official_feed,
)
from app.ingestion.admission import ADMISSION_POLICY_SCHEMA
from app.reporting.legacy_inventory import (
    LegacyInventoryError,
    build_legacy_inventory_report,
    canonical_legacy_inventory_json,
    legacy_inventory_digest,
    validate_legacy_inventory_report,
)


BENCHMARK_ID = "hf_official_benchmarks"


def _source_data(source_id: str, *, source_url: str | None = None) -> dict[str, object]:
    return {
        "id": source_id,
        "benchmark_id": BENCHMARK_ID,
        "source_name": f"Candidate Feed Fixture {source_id}",
        "source_url": source_url or f"https://official.example/{source_id}.json",
        "source_type": "api",
        "officialness_level": "O5",
        "machine_readable": True,
        "requires_auth": False,
        "supports_history": True,
        "update_cadence": "manual",
        "parser_name": "candidate_feed_fixture",
        "parser_version": "fixture-v1",
        "parser_config": {"fixture": "official-feed-projection"},
        "status": "active",
        "notes": "Offline LDR-08 fixture only.",
    }


def _policy(
    revision: models.OfficialSourceRevision,
    *,
    metric: str | None,
    split: str | None,
    setting: str | None,
    evaluation_version: str | None,
    score_unit: str | None,
    valid: bool = True,
) -> dict[str, object]:
    return {
        "schema": ADMISSION_POLICY_SCHEMA,
        "definition_hash": revision.definition_hash if valid else "0" * 64,
        "source_kind": "official_reported_result",
        "adapter": {
            "parser_name": revision.parser_name,
            "parser_version": revision.parser_version,
        },
        "approved_source_urls": [revision.source_url],
        "approved_final_urls": [revision.source_url],
        "locator_types": ["json_path_v1"],
        "evidence_contracts": {
            "json_path_v1": {
                "record_path_template": "$.records[{row_index}]",
                "fields": {"model_raw": "model", "score_raw": "score"},
            }
        },
        "dimensions": {
            "benchmark_raw": {
                "mode": "revision_constant",
                "value": "Candidate feed fixture benchmark",
                "allowed_values": ["Candidate feed fixture benchmark"],
            },
            "metric_raw": {
                "mode": "revision_constant",
                "value": metric,
                "allowed_values": [metric],
            },
            "split_raw": {
                "mode": "revision_constant",
                "value": split,
                "allowed_values": [split],
            },
            "setting_raw": {
                "mode": "revision_constant",
                "value": setting,
                "allowed_values": [setting],
            },
            "evaluation_version_raw": {
                "mode": "revision_constant",
                "value": evaluation_version,
                "allowed_values": [evaluation_version],
            },
        },
        "numeric": {"lexeme": "decimal", "score_unit": score_unit},
        "fetch": {"max_bytes": 5 * 1024 * 1024},
    }


def _certified_source(
    session,
    *,
    source_id: str,
    metric: str | None = "accuracy",
    split: str | None = "test",
    setting: str | None = "default",
    evaluation_version: str | None = "v1",
    score_unit: str | None = "percent",
    policy_valid: bool = True,
) -> tuple[models.OfficialSourceRow, models.OfficialSourceRevision, models.SourceRevisionDecision]:  # type: ignore[no-untyped-def]
    reconciled = repo.reconcile_official_source(session, _source_data(source_id))
    initial = session.scalar(
        select(models.SourceRevisionDecision).where(
            models.SourceRevisionDecision.source_revision_id == reconciled.revision.id
        )
    )
    assert initial is not None
    certified = models.SourceRevisionDecision(
        source_revision_id=reconciled.revision.id,
        outcome="certified",
        policy_version=ADMISSION_POLICY_SCHEMA,
        reason_code="fixture_certification",
        basis_json={
            "source_admission": _policy(
                reconciled.revision,
                metric=metric,
                split=split,
                setting=setting,
                evaluation_version=evaluation_version,
                score_unit=score_unit,
                valid=policy_valid,
            )
        },
        actor="pytest",
        supersedes_decision_id=initial.id,
    )
    session.add(certified)
    session.flush()
    return reconciled.source, reconciled.revision, certified


def _model(session, model_id: str) -> models.ModelEntity:  # type: ignore[no-untyped-def]
    row = session.get(models.ModelEntity, model_id)
    if row is None:
        row = models.ModelEntity(
            id=model_id,
            canonical_name=model_id,
            display_name=f"Display {model_id}",
            entity_type="model",
            provider="Fixture provider",
            model_family="Fixture family",
            status="active",
        )
        session.add(row)
        session.flush()
    return row


def _candidate_claim(
    session,
    *,
    suffix: str,
    source: models.OfficialSourceRow,
    revision: models.OfficialSourceRevision,
    certified: models.SourceRevisionDecision,
    model_id: str | None = "feed-model",
    review_model_id: str | None | object = ...,  # Ellipsis means captured model mapping.
    metric: str | None = "accuracy",
    split: str | None = "test",
    setting: str | None = "default",
    evaluation_version: str | None = "v1",
    score_numeric: float | None = 91.25,
    score_raw: str = "91.2500",
    validation_outcomes: tuple[str, ...] = ("pass",),
    review_outcome: str = "validation_reviewed",
    publication_outcome: str = "approved",
    evidence_location: dict[str, object] | None = None,
    review_dimensions: dict[str, str | None] | None = None,
    capture_method: str = "candidate_feed_fixture",
    capture_status: str = "unreviewed",
) -> models.ResultClaim:  # type: ignore[no-untyped-def]
    if model_id is not None:
        _model(session, model_id)
    if review_model_id is ...:
        review_model_id = model_id
    if isinstance(review_model_id, str):
        _model(session, review_model_id)

    content_hash = hashlib.sha256(f"snapshot:{suffix}".encode()).hexdigest()
    snapshot = models.SourceSnapshot(
        official_source_id=source.id,
        source_revision_id=revision.id,
        raw_content_uri=f"file:///offline-fixtures/{suffix}.json",
        content_hash=content_hash,
        content_type="application/json",
        fetch_metadata={"fixture": True, "verbatim": True},
        parser_version="fixture-v1",
    )
    session.add(snapshot)
    session.flush()
    claim = models.ResultClaim(
        source_snapshot_id=snapshot.id,
        source_revision_decision_id=certified.id,
        official_source_id=source.id,
        benchmark_id=BENCHMARK_ID,
        model_entity_id=model_id,
        model_raw=f"Raw {suffix}",
        benchmark_raw="Candidate feed fixture benchmark",
        score_raw=score_raw,
        metric_raw=metric,
        split_raw=split,
        setting_raw=setting,
        evaluation_version_raw=evaluation_version,
        score_numeric=score_numeric,
        score_unit="percent",
        evidence_text=f"Raw {suffix} reported {score_raw}",
        evidence_location=evidence_location
        or {
            "type": "json_path_v1",
            "record_path": "$.records[0]",
            "fields": {"model_raw": "model", "score_raw": "score"},
        },
        capture_method=capture_method,
        capture_confidence=1.0,
        capture_status=capture_status,
        scientific_status="unknown",
        officialness_level="O5",
        claim_fingerprint=hashlib.sha256(f"claim:{suffix}".encode()).hexdigest(),
    )
    session.add(claim)
    session.flush()
    for index, outcome in enumerate(validation_outcomes):
        session.add(
            models.ClaimValidation(
                result_claim_id=claim.id,
                validation_type=f"fixture-{index}",
                outcome=outcome,
                validator="pytest",
                notes="Offline candidate feed fixture.",
            )
        )
    session.flush()

    dimensions = review_dimensions or {}
    review = repo.append_claim_review_decision(
        session,
        result_claim_id=claim.id,
        model_entity_id=review_model_id if isinstance(review_model_id, str) else None,
        benchmark_id=dimensions.get("benchmark_id"),
        metric=dimensions.get("metric"),
        split=dimensions.get("split"),
        setting=dimensions.get("setting"),
        evaluation_version=dimensions.get("evaluation_version"),
        outcome=review_outcome,
        reason_code="fixture_review",
        actor="pytest",
    )
    # There is intentionally no production approval writer during
    # containment. This direct ORM row is a clearly scoped hypothetical
    # approval fixture for testing the read-only projection contract.
    publication = models.ClaimPublicationDecision(
        result_claim_id=claim.id,
        claim_review_decision_id=review.id,
        outcome=publication_outcome,
        policy_version="fixture-publication-v1",
        reason_code="fixture_publication",
        basis_json={"fixture": True},
        actor="pytest",
    )
    session.add(publication)
    session.flush()
    return claim


def _counts(session) -> dict[str, int]:  # type: ignore[no-untyped-def]
    return {
        table.__tablename__: int(session.scalar(select(func.count()).select_from(table)) or 0)
        for table in (
            models.SourceSnapshot,
            models.ResultClaim,
            models.ClaimValidation,
            models.ClaimReviewDecision,
            models.ClaimPublicationDecision,
        )
    }


def test_candidate_projection_is_deterministic_complete_and_read_only(seeded_db):
    with get_session() as session:
        source, revision, certified = _certified_source(session, source_id="feed-happy")
        claim = _candidate_claim(
            session,
            suffix="happy",
            source=source,
            revision=revision,
            certified=certified,
        )
        before = _counts(session)
        first = project_official_feed(session)
        second = project_official_feed(session)

        assert _counts(session) == before
        assert canonical_official_feed_json(first) == canonical_official_feed_json(second)
        assert first["manifest"]["contentSha256"] == official_feed_digest(first)
        assert first["manifest"]["scoreCount"] == 1
        assert first["excludedClaims"] == []
        assert "generatedAt" not in first
        assert first["scores"] == [
            {
                "cell": {
                    "modelId": "feed-model",
                    "benchmarkId": BENCHMARK_ID,
                    "metric": "accuracy",
                    "split": "test",
                    "setting": "default",
                    "evaluationVersion": "v1",
                },
                "claimId": claim.id,
                "value": 91.25,
                "scoreRaw": "91.2500",
                "scoreUnit": "percent",
                "evidenceText": "Raw happy reported 91.2500",
                "evidenceLocation": {
                    "type": "json_path_v1",
                    "record_path": "$.records[0]",
                    "fields": {"model_raw": "model", "score_raw": "score"},
                },
                "provenance": first["scores"][0]["provenance"],
            }
        ]
        assert first["scores"][0]["provenance"]["officialSourceId"] == source.id
        assert first["scores"][0]["provenance"]["sourceRevisionId"] == revision.id
        assert first["scores"][0]["provenance"]["sourceRevisionDecisionId"] == certified.id
        assert first["sourceManifest"][0]["snapshotContentSha256"]
        assert validate_official_feed(first) == first


def test_projection_uses_capture_time_revision_after_catalog_advances(seeded_db):
    with get_session() as session:
        source, revision, certified = _certified_source(session, source_id="feed-history")
        _candidate_claim(
            session,
            suffix="history",
            source=source,
            revision=revision,
            certified=certified,
        )
        original_url = revision.source_url
        updated = _source_data(source.id, source_url="https://official.example/feed-history-v2.json")
        updated["parser_version"] = "fixture-v2"
        repo.reconcile_official_source(session, updated)

        payload = project_official_feed(session)
        assert payload["scores"] and payload["excludedClaims"] == []
        assert payload["sourceManifest"][0]["sourceRevisionId"] == revision.id
        assert payload["sourceManifest"][0]["sourceUrl"] == original_url


def test_projection_fails_with_a_sorted_conflict_report_not_a_partial_feed(seeded_db):
    with get_session() as session:
        source, revision, certified = _certified_source(session, source_id="feed-conflict")
        first = _candidate_claim(
            session,
            suffix="conflict-first",
            source=source,
            revision=revision,
            certified=certified,
            score_numeric=90.0,
            score_raw="90.0",
        )
        second = _candidate_claim(
            session,
            suffix="conflict-second",
            source=source,
            revision=revision,
            certified=certified,
            score_numeric=91.0,
            score_raw="91.0",
        )

        with pytest.raises(FeedConflictError) as raised:
            project_official_feed(session)
        report = raised.value.report
        assert report["status"] == "conflict"
        assert "scores" not in report
        assert report["excludedClaims"] == []
        assert report["conflicts"] == [
            {
                "cell": {
                    "modelId": "feed-model",
                    "benchmarkId": BENCHMARK_ID,
                    "metric": "accuracy",
                    "split": "test",
                    "setting": "default",
                    "evaluationVersion": "v1",
                },
                "claims": report["conflicts"][0]["claims"],
            }
        ]
        assert [row["claimId"] for row in report["conflicts"][0]["claims"]] == sorted(
            (first.id, second.id)
        )


@pytest.mark.parametrize(
    ("label", "claim_kwargs", "expected_reason"),
    [
        ("no-validation", {"validation_outcomes": ()}, "VALIDATION_MISSING"),
        (
            "identity-only-review",
            {"review_outcome": "identity_resolved"},
            "REVIEW_NOT_VALIDATION_REVIEWED",
        ),
        (
            "quarantined-publication",
            {"publication_outcome": "quarantined"},
            "PUBLICATION_NOT_APPROVED",
        ),
        (
            "unresolved-model",
            {"model_id": None, "review_model_id": None},
            "DISPLAY_IDENTITY_UNRESOLVED",
        ),
        (
            "incomplete-evidence",
            {"evidence_location": {"type": ""}},
            "EVIDENCE_LOCATION_INCOMPLETE",
        ),
        (
            "contract-mismatch",
            {
                "evidence_location": {
                    "type": "json_path_v1",
                    "record_path": "$.other[0]",
                    "fields": {"model_raw": "model", "score_raw": "score"},
                }
            },
            "EVIDENCE_LOCATION_CONTRACT_MISMATCH",
        ),
    ],
)
def test_projection_excludes_each_missing_eligibility_gate(
    seeded_db, label: str, claim_kwargs: dict[str, object], expected_reason: str
):
    with get_session() as session:
        source, revision, certified = _certified_source(session, source_id=f"feed-gate-{label}")
        _candidate_claim(
            session,
            suffix=f"gate-{label}",
            source=source,
            revision=revision,
            certified=certified,
            **claim_kwargs,
        )
        payload = project_official_feed(session)
        assert payload["scores"] == []
        assert payload["excludedClaims"][0]["reasonCode"] == expected_reason


def test_projection_requires_capture_time_certification_policy(seeded_db):
    with get_session() as session:
        source, revision, certified = _certified_source(
            session, source_id="feed-invalid-policy", policy_valid=False
        )
        _candidate_claim(
            session,
            suffix="invalid-policy",
            source=source,
            revision=revision,
            certified=certified,
        )
        payload = project_official_feed(session)
        assert payload["scores"] == []
        assert payload["excludedClaims"] == [
            {"claimId": payload["excludedClaims"][0]["claimId"], "reasonCode": "SOURCE_CERTIFICATION_POLICY_INVALID"}
        ]


def test_projection_excludes_a_capture_revision_revoked_after_ingestion(seeded_db):
    with get_session() as session:
        source, revision, certified = _certified_source(session, source_id="feed-revoked-capture")
        _candidate_claim(
            session,
            suffix="revoked-capture",
            source=source,
            revision=revision,
            certified=certified,
        )
        session.add(
            models.SourceRevisionDecision(
                source_revision_id=revision.id,
                outcome="revoked",
                policy_version="fixture-revocation-v1",
                reason_code="fixture_source_revocation",
                basis_json={"fixture": True},
                actor="pytest",
                supersedes_decision_id=certified.id,
            )
        )
        session.flush()

        payload = project_official_feed(session)
        assert payload["scores"] == []
        assert payload["excludedClaims"][0]["reasonCode"] == "SOURCE_DECISION_NOT_CERTIFIED"


def test_projection_keeps_dimension_variants_and_effective_review_identity_distinct(seeded_db):
    with get_session() as session:
        source, revision, certified = _certified_source(session, source_id="feed-dimensions")
        _candidate_claim(
            session,
            suffix="dimension-accuracy",
            source=source,
            revision=revision,
            certified=certified,
            metric="accuracy",
        )
        # The source fixture declares one metric per revision, so use a
        # second certified source for the distinct metric dimension.
        source_two, revision_two, certified_two = _certified_source(
            session, source_id="feed-dimensions-f1", metric="f1"
        )
        _candidate_claim(
            session,
            suffix="dimension-f1",
            source=source_two,
            revision=revision_two,
            certified=certified_two,
            metric="f1",
        )

        payload = project_official_feed(session)
        assert [row["cell"]["metric"] for row in payload["scores"]] == ["accuracy", "f1"]


def test_projection_uses_append_only_review_identity_and_dimensions(seeded_db):
    with get_session() as session:
        source, revision, certified = _certified_source(session, source_id="feed-review-projection")
        claim = _candidate_claim(
            session,
            suffix="review-projection",
            source=source,
            revision=revision,
            certified=certified,
            model_id=None,
            review_model_id="reviewed-model",
            review_dimensions={"metric": "reviewed-accuracy"},
        )

        payload = project_official_feed(session)
        assert claim.model_entity_id is None
        assert payload["scores"][0]["cell"]["modelId"] == "reviewed-model"
        assert payload["scores"][0]["cell"]["metric"] == "reviewed-accuracy"


def test_feed_validator_rejects_duplicate_cells_and_digest_tampering(seeded_db):
    with get_session() as session:
        source, revision, certified = _certified_source(session, source_id="feed-validator")
        _candidate_claim(
            session,
            suffix="validator",
            source=source,
            revision=revision,
            certified=certified,
        )
        payload = project_official_feed(session)

        duplicate = deepcopy(payload)
        duplicate["scores"].append(deepcopy(duplicate["scores"][0]))
        with pytest.raises(FeedProjectionError, match="repeat a claim id|sorted and unique"):
            validate_official_feed(duplicate)

        tampered = deepcopy(payload)
        tampered["scores"][0]["scoreRaw"] = "tampered"
        with pytest.raises(FeedProjectionError, match="digest"):
            validate_official_feed(tampered)

        inconsistent_provenance = deepcopy(payload)
        inconsistent_provenance["scores"][0]["provenance"]["sourceUrl"] = "https://wrong.example/"
        inconsistent_provenance["manifest"]["contentSha256"] = official_feed_digest(
            inconsistent_provenance
        )
        with pytest.raises(FeedProjectionError, match="does not match its source manifest"):
            validate_official_feed(inconsistent_provenance)

        contradictory = deepcopy(payload)
        contradictory["excludedClaims"].append(
            {"claimId": contradictory["scores"][0]["claimId"], "reasonCode": "contradiction"}
        )
        contradictory["manifest"]["contentSha256"] = official_feed_digest(contradictory)
        with pytest.raises(FeedProjectionError, match="both select and exclude"):
            validate_official_feed(contradictory)


def test_legacy_inventory_accounts_for_every_claim_and_orphan_snapshot_without_writing(seeded_db):
    with get_session() as session:
        source, revision, certified = _certified_source(session, source_id="inventory-accounting")
        candidate = _candidate_claim(
            session,
            suffix="inventory-candidate",
            source=source,
            revision=revision,
            certified=certified,
        )
        excluded = _candidate_claim(
            session,
            suffix="inventory-no-validation",
            source=source,
            revision=revision,
            certified=certified,
            validation_outcomes=(),
        )
        orphan = models.SourceSnapshot(
            official_source_id=source.id,
            source_revision_id=revision.id,
            raw_content_uri="file:///offline-fixtures/orphan.json",
            content_hash=hashlib.sha256(b"orphan").hexdigest(),
            content_type="application/json",
            fetch_metadata={"fixture": True},
            parser_version="fixture-v1",
        )
        session.add(orphan)
        session.flush()
        before = _counts(session)

        first = build_legacy_inventory_report(session)
        second = build_legacy_inventory_report(session)

        assert _counts(session) == before
        assert canonical_legacy_inventory_json(first) == canonical_legacy_inventory_json(second)
        assert first["availability"] == "report_only"
        assert first["manifest"]["contentSha256"] == legacy_inventory_digest(first)
        assert first["manifest"] == {
            **first["manifest"],
            "claimCount": 2,
            "snapshotCount": 3,
            "candidateClaimCount": 1,
            "excludedClaimCount": 1,
            "conflictedClaimCount": 0,
            "conflictCellCount": 0,
        }
        claims = {row["claimId"]: row for row in first["claims"]}
        assert claims[candidate.id]["reportDisposition"] == "candidate"
        assert claims[candidate.id]["omissionReasonCode"] is None
        assert claims[excluded.id]["reportDisposition"] == "omitted"
        assert claims[excluded.id]["omissionReasonCode"] == "VALIDATION_MISSING"
        assert claims[candidate.id]["evidence"]["locationSha256"]
        assert claims[candidate.id]["evidence"]["evidenceTextSha256"]
        assert next(row for row in first["snapshots"] if row["snapshotId"] == orphan.id)[
            "claimCount"
        ] == 0
        assert first["summary"]["reportOnlyQuarantine"] is True
        assert validate_legacy_inventory_report(first) == first


def test_legacy_inventory_reports_all_conflicted_candidates_without_partial_selection(seeded_db):
    with get_session() as session:
        source, revision, certified = _certified_source(session, source_id="inventory-conflict")
        first_claim = _candidate_claim(
            session,
            suffix="inventory-conflict-one",
            source=source,
            revision=revision,
            certified=certified,
            score_numeric=90.0,
        )
        second_claim = _candidate_claim(
            session,
            suffix="inventory-conflict-two",
            source=source,
            revision=revision,
            certified=certified,
            score_numeric=91.0,
        )

        report = build_legacy_inventory_report(session)

        assert report["summary"]["candidateProjectionStatus"] == "conflict"
        assert report["summary"]["selectedCellCount"] == 0
        assert report["manifest"]["candidateClaimCount"] == 0
        assert report["manifest"]["conflictedClaimCount"] == 2
        assert report["conflicts"][0]["claimIds"] == sorted((first_claim.id, second_claim.id))
        assert {
            row["claimId"]: (row["reportDisposition"], row["omissionReasonCode"])
            for row in report["claims"]
        } == {
            first_claim.id: ("conflicted", "DISPLAY_CELL_CONFLICT"),
            second_claim.id: ("conflicted", "DISPLAY_CELL_CONFLICT"),
        }
        with pytest.raises(FeedConflictError):
            project_official_feed(session)


def test_legacy_inventory_surfaces_derived_synthetic_and_provisional_observations(seeded_db):
    with get_session() as session:
        source, revision, certified = _certified_source(
            session, source_id="inventory-legacy-signals", policy_valid=False
        )
        claim = _candidate_claim(
            session,
            suffix="inventory-derived",
            source=source,
            revision=revision,
            certified=certified,
            capture_method="legacy_synthetic_derived",
            capture_status="needs_review",
            evidence_location={"type": "derived_analytics", "record_path": "$.derived"},
        )

        report = build_legacy_inventory_report(session)
        row = report["claims"][0]

        assert row["claimId"] == claim.id
        assert row["reportDisposition"] == "omitted"
        assert row["omissionReasonCode"] == "SOURCE_CERTIFICATION_POLICY_INVALID"
        assert row["observedRiskSignals"] == [
            "DERIVED_CAPTURE_METHOD",
            "DERIVED_EVIDENCE_LOCATION",
            "PROVISIONAL_CAPTURE_STATUS",
            "SYNTHETIC_CAPTURE_METHOD",
        ]


def test_legacy_inventory_validator_and_cli_remain_read_only_and_export_stays_disabled(seeded_db):
    with get_session() as session:
        source, revision, certified = _certified_source(session, source_id="inventory-cli")
        _candidate_claim(
            session,
            suffix="inventory-cli",
            source=source,
            revision=revision,
            certified=certified,
        )
        before = _counts(session)

    result = CliRunner().invoke(app, ["reports", "legacy-inventory"])
    assert result.exit_code == 0, result.output
    report = json.loads(result.output)
    assert report["availability"] == "report_only"
    assert report["manifest"]["candidateClaimCount"] == 1
    assert "export-official-json" in CliRunner().invoke(app, ["--help"]).output
    export = CliRunner().invoke(app, ["export-official-json"])
    assert export.exit_code == 2

    with get_session() as session:
        assert _counts(session) == before

    duplicate = deepcopy(report)
    duplicate["claims"].append(deepcopy(duplicate["claims"][0]))
    duplicate["manifest"]["contentSha256"] = legacy_inventory_digest(duplicate)
    with pytest.raises(LegacyInventoryError, match="sorted and unique"):
        validate_legacy_inventory_report(duplicate)
