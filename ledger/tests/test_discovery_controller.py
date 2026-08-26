from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.db import models
from app.db.engine import get_session
from app.db.operational_repositories import OperationalReplayConflict
from app.discovery import (
    build_fixture_connectors,
    load_manifest,
    run_discovery_cycle,
)
from app.runtime.dependencies import contained_runtime_dependencies
from app.scheduling.slots import slot_for_ordinal
from discovery_fixtures import (
    build_candidate_spec,
    build_target,
    standard_observations,
    write_manifest_root,
)

FORBIDDEN_TABLES = (
    models.ResultClaim,
    models.SourceSnapshot,
    models.SourceRevisionDecision,
    models.ClaimReviewDecision,
    models.ClaimPublicationDecision,
    models.ClaimValidation,
    models.IngestionRun,
)


def _count(session, model) -> int:
    return session.scalar(select(func.count()).select_from(model))


def _run(root: Path, ordinal: int):
    manifest = load_manifest(root)
    slot = slot_for_ordinal(manifest.anchor_utc, manifest.cadence_seconds, ordinal)
    connectors = build_fixture_connectors(contained_runtime_dependencies())
    with get_session() as session:
        return run_discovery_cycle(
            session,
            manifest=manifest,
            slot=slot,
            connectors=connectors,
            fixture_root=Path(root),
        )


def test_first_cycle_persists_intents_and_candidates_with_balanced_counts(
    tmp_db, tmp_path
) -> None:
    root = write_manifest_root(
        tmp_path / "fx", observations=standard_observations("example-target-v1")
    )
    report = _run(root, 0)
    assert report.counts == {
        "expectedTargetCount": 1,
        "dueCount": 1,
        "notDueCount": 0,
        "blockedCount": 0,
        "checkedCount": 1,
        "failedCount": 0,
        "unchangedCount": 0,
        "changedCount": 1,
        "reviewRequiredCount": 0,
        "newCandidateCount": 1,
        "replayedCandidateCount": 0,
    }
    assert report.records[0].run_outcome == "changed"
    assert report.records[0].candidate_ids[0].startswith("cand-")
    with get_session() as session:
        assert _count(session, models.ScheduledCycleIntent) == 1
        assert _count(session, models.ScheduledCycleIntentCompletion) == 1
        assert _count(session, models.ScheduledJobIntent) == 1
        assert _count(session, models.DiscoveryCandidate) == 1
        for model in FORBIDDEN_TABLES:
            assert _count(session, model) == 0, model.__tablename__


def test_replaying_the_same_slot_creates_no_duplicates(tmp_db, tmp_path) -> None:
    root = write_manifest_root(
        tmp_path / "fx", observations=standard_observations("example-target-v1")
    )
    first = _run(root, 0)
    second = _run(root, 0)
    assert first.cycle_id == second.cycle_id
    assert second.records[0].run_outcome == "unchanged"
    assert second.counts["newCandidateCount"] == 0
    assert second.counts["replayedCandidateCount"] == 1
    with get_session() as session:
        assert _count(session, models.ScheduledCycleIntent) == 1
        assert _count(session, models.ScheduledJobIntent) == 1
        assert _count(session, models.DiscoveryCandidate) == 1


def test_two_deterministic_cycles_produce_one_run_each(tmp_db, tmp_path) -> None:
    root = write_manifest_root(
        tmp_path / "fx", observations=standard_observations("example-target-v1")
    )
    first = _run(root, 0)
    second = _run(root, 1)
    assert first.cycle_id != second.cycle_id
    assert second.records[0].run_outcome == "unchanged"
    with get_session() as session:
        assert _count(session, models.ScheduledCycleIntent) == 2
        assert _count(session, models.ScheduledJobIntent) == 2
        # Same connector output at a new slot is still the same candidate.
        assert _count(session, models.DiscoveryCandidate) == 1


def test_mutated_manifest_on_a_replayed_slot_fails_closed(tmp_db, tmp_path) -> None:
    root = write_manifest_root(
        tmp_path / "fx", observations=standard_observations("example-target-v1")
    )
    _run(root, 0)
    root = write_manifest_root(
        tmp_path / "fx",
        targets={
            "example-target-v1": build_target("example-target-v1"),
            "second-target-v1": build_target("second-target-v1"),
        },
        observations=standard_observations("example-target-v1", "second-target-v1"),
    )
    with pytest.raises(OperationalReplayConflict):
        _run(root, 0)


def test_unknown_connector_target_fails_explicitly(tmp_db, tmp_path) -> None:
    root = write_manifest_root(
        tmp_path / "fx",
        targets={
            "ghost-target-v1": build_target(
                "ghost-target-v1", connector_id="ghost-connector"
            )
        },
    )
    report = _run(root, 0)
    assert report.records[0].run_outcome == "failed"
    assert report.records[0].failure_reason_code == "CONNECTOR_UNKNOWN"
    assert report.counts["failedCount"] == 1
    assert report.counts["expectedTargetCount"] == report.counts["dueCount"]


def test_missing_static_observation_fails_closed(tmp_db, tmp_path) -> None:
    root = write_manifest_root(tmp_path / "fx", observations={})
    report = _run(root, 0)
    assert report.records[0].run_outcome == "failed"
    assert report.records[0].failure_reason_code == "MISSING_FIXTURE_OBSERVATION"
    with get_session() as session:
        assert _count(session, models.DiscoveryCandidate) == 0


def test_review_required_observation_has_its_own_bucket(tmp_db, tmp_path) -> None:
    observations = {
        "example-target-v1": {
            "candidates": [build_candidate_spec("example-target-v1-source")],
            "reviewRequired": True,
        }
    }
    root = write_manifest_root(tmp_path / "fx", observations=observations)
    report = _run(root, 0)
    assert report.records[0].run_outcome == "review_required"
    assert report.counts["reviewRequiredCount"] == 1
    assert report.counts["newCandidateCount"] == 1


def test_blocked_and_not_due_targets_are_explicit_never_silent(tmp_db, tmp_path) -> None:
    root = write_manifest_root(
        tmp_path / "fx",
        targets={
            "configured-target-v1": build_target("configured-target-v1"),
            "paused-target-v1": build_target("paused-target-v1", status="paused"),
            "daily-target-v1": build_target("daily-target-v1", cadence="P1D"),
        },
        observations=standard_observations("configured-target-v1"),
    )
    report = _run(root, 1)
    by_revision = {record.target_revision_id: record for record in report.records}
    assert by_revision["paused-target-v1"].run_outcome == "blocked"
    assert by_revision["paused-target-v1"].disposition_reason_code == "OPERATOR_PAUSED"
    assert by_revision["daily-target-v1"].run_outcome == "not_due"
    assert by_revision["daily-target-v1"].candidate_ids == ()
    assert by_revision["configured-target-v1"].run_outcome == "changed"
    counts = report.counts
    assert counts["expectedTargetCount"] == 3
    assert (
        counts["expectedTargetCount"]
        == counts["dueCount"] + counts["notDueCount"] + counts["blockedCount"]
    )
    assert counts["dueCount"] == counts["checkedCount"] + counts["failedCount"]
