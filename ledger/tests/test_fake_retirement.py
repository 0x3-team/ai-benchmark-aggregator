from __future__ import annotations

from uuid import UUID

import pytest
from sqlalchemy import func, select

from app.db import models, repositories as repo
from app.db.engine import get_session
from app.ingestion import runner as ingestion_runner
from app.ingestion.extractors.normalize import compute_claim_fingerprint
from app.ingestion.policy import can_ingest_source, source_admission_reason
from app.ingestion.runner import IngestionBlockedError, run_ingestion
from app.schemas.boundary import OfficialSource, ResultClaimInput


def _count(session, model) -> int:  # type: ignore[no-untyped-def]
    return session.scalar(select(func.count()).select_from(model)) or 0


def _source(*, status: str, notes: str | None, parser_config: dict[str, object]) -> dict[str, object]:
    return {
        "id": "fake-route-transition-fixture",
        "benchmark_id": "hf_official_benchmarks",
        "source_name": "Fake route transition fixture",
        "source_url": "file://fake-route-transition-fixture",
        "source_type": "fake",
        "officialness_level": "O5",
        "machine_readable": True,
        "requires_auth": False,
        "supports_history": False,
        "update_cadence": "manual",
        "parser_name": "fake",
        "parser_config": parser_config,
        "status": status,
        "notes": notes,
    }


def _temporary_test_fixture_successor() -> dict[str, object]:
    return {
        "id": "fake_local_fixture",
        "benchmark_id": "hf_official_benchmarks",
        "source_name": "Temporary fake fixture successor",
        "source_url": "file://fake",
        "source_type": "fake",
        "officialness_level": "O5",
        "machine_readable": True,
        "requires_auth": False,
        "supports_history": False,
        "update_cadence": "manual",
        "parser_name": "fake",
        "parser_config": {"mode": "test_fixture_only"},
        "status": "active",
        "notes": "Temporary test-only successor; never a production source.",
    }


def test_retiring_fake_route_appends_a_revision_and_preserves_historical_evidence(seeded_db):
    active = _source(status="active", notes=None, parser_config={"mode": "test_fixture_only"})
    retired = _source(
        status="inactive",
        notes="Retired LDR-06: synthetic fixture values are not official result evidence.",
        parser_config={
            "mode": "retired",
            "retirement_reason": "synthetic fixture data is never Official benchmark evidence",
        },
    )
    with get_session() as session:
        initial = repo.reconcile_official_source(session, active, registry_managed=True)
        snapshot = repo.insert_snapshot(
            session,
            official_source_id=initial.source.id,
            source_revision_id=initial.revision.id,
            raw_content_uri="file:///test-only/fake-route.json",
            content_hash="d" * 64,
            content_type="application/json",
            http_status=200,
            etag=None,
            last_modified_header=None,
            fetch_metadata={"fixture": True},
        )
        initial_decision = session.scalar(
            select(models.SourceRevisionDecision).where(
                models.SourceRevisionDecision.source_revision_id == initial.revision.id
            )
        )
        assert initial_decision is not None
        # This models a historical test record from before the canonical route
        # was retired. Retirement must preserve raw ledger evidence verbatim.
        historical_decision = models.SourceRevisionDecision(
            source_revision_id=initial.revision.id,
            outcome="certified",
            policy_version="test-historical-claim-v1",
            reason_code="test_historical_claim",
            basis_json={"fixture": True},
            actor="pytest",
            supersedes_decision_id=initial_decision.id,
        )
        session.add(historical_decision)
        session.flush()
        historical_claim = ResultClaimInput(
            source_snapshot_id=UUID(snapshot.id),
            source_revision_decision_id=UUID(historical_decision.id),
            official_source_id=initial.source.id,
            benchmark_id=initial.source.benchmark_id,
            model_raw="Fake-Model-1",
            benchmark_raw="hf_official_benchmarks",
            score_raw="42.50",
            evidence_location={"type": "json_path_v1", "record_path": "$.leaderboard[0]"},
            capture_method="legacy_synthetic_fixture",
            capture_confidence=1.0,
            capture_status="parser_verified",
            officialness_level=initial.source.officialness_level,
        )
        historical_claim.claim_fingerprint = compute_claim_fingerprint(historical_claim)
        claim_row, inserted = repo.insert_claim_if_new(session, historical_claim)
        assert inserted is True

        result = repo.reconcile_official_source(session, retired, registry_managed=True)
        decision = session.scalar(
            select(models.SourceRevisionDecision).where(
                models.SourceRevisionDecision.source_revision_id == result.revision.id
            )
        )

        assert result.disposition == "revised"
        assert result.revision.revision_ordinal == initial.revision.revision_ordinal + 1
        assert result.revision.supersedes_revision_id == initial.revision.id
        assert result.source.current_revision_id == result.revision.id
        assert result.source.status == "inactive"
        assert result.revision.status == "inactive"
        assert result.revision.parser_config["mode"] == "retired"
        assert snapshot.source_revision_id == initial.revision.id
        preserved_claim = session.get(models.ResultClaim, claim_row.id)
        assert preserved_claim is not None
        assert (
            preserved_claim.source_snapshot_id,
            preserved_claim.model_raw,
            preserved_claim.score_raw,
        ) == (snapshot.id, "Fake-Model-1", "42.50")
        assert decision is not None
        assert (decision.outcome, decision.reason_code) == ("quarantined", "registry_definition_changed")


def test_retired_fake_route_never_dispatches_or_writes(seeded_db, monkeypatch):
    with get_session() as session:
        before = {
            "runs": _count(session, models.IngestionRun),
            "snapshots": _count(session, models.SourceSnapshot),
            "claims": _count(session, models.ResultClaim),
        }
        monkeypatch.setattr(
            ingestion_runner,
            "get_adapter",
            lambda *_args, **_kwargs: pytest.fail("inactive fake route must not dispatch an adapter"),
        )

        with pytest.raises(IngestionBlockedError, match="No production-eligible source"):
            run_ingestion(session, source_id="fake_local_fixture", dry_run=True)

        assert {
            "runs": _count(session, models.IngestionRun),
            "snapshots": _count(session, models.SourceSnapshot),
            "claims": _count(session, models.ResultClaim),
        } == before


def test_unpatched_runner_rejects_an_active_test_fixture_successor_before_dispatch_or_write(
    seeded_db, monkeypatch
):
    with get_session() as session:
        repo.reconcile_official_source(session, _temporary_test_fixture_successor())
        before = {
            "runs": _count(session, models.IngestionRun),
            "snapshots": _count(session, models.SourceSnapshot),
            "claims": _count(session, models.ResultClaim),
        }
        monkeypatch.setattr(
            ingestion_runner,
            "get_adapter",
            lambda *_args, **_kwargs: pytest.fail("unpatched fake source must not dispatch an adapter"),
        )

        with pytest.raises(IngestionBlockedError, match="source type 'fake' is quarantined"):
            run_ingestion(session, source_id="fake_local_fixture", dry_run=True)

        assert {
            "runs": _count(session, models.IngestionRun),
            "snapshots": _count(session, models.SourceSnapshot),
            "claims": _count(session, models.ResultClaim),
        } == before


def test_fixture_bypass_is_explicit_temporary_and_still_policy_quarantined(
    seeded_db, allow_quarantined_fixture_ingestion
):
    with get_session() as session:
        source_row = session.get(models.OfficialSourceRow, "fake_local_fixture")
        assert source_row is not None
        revision = repo.get_current_source_revision(session, source_row.id)
        source = OfficialSource(
            id=source_row.id,
            source_name=revision.source_name,
            source_url=revision.source_url,
            source_type=revision.source_type,
            officialness_level=revision.officialness_level,
            machine_readable=revision.machine_readable,
            requires_auth=revision.requires_auth,
            supports_history=revision.supports_history,
            update_cadence=revision.update_cadence,
            parser_name=revision.parser_name,
            parser_version=revision.parser_version,
            parser_config=revision.parser_config,
            status=revision.status,
            benchmark_id=source_row.benchmark_id,
            notes=revision.notes,
        )

        assert source.status == "active"
        assert source.parser_config["mode"] == "test_fixture_only"
        assert can_ingest_source(source) is False
        assert source_admission_reason(source) == "source type 'fake' is quarantined"
