from __future__ import annotations

from uuid import UUID

import pytest
from sqlalchemy import func, select

from app.db import models, repositories as repo
from app.db.engine import get_session
from app.ingestion import runner as ingestion_runner
from app.ingestion.extractors.normalize import compute_claim_fingerprint
from app.ingestion.runner import IngestionBlockedError, run_ingestion
from app.schemas.boundary import ResultClaimInput


def _count(session, model) -> int:  # type: ignore[no-untyped-def]
    return session.scalar(select(func.count()).select_from(model)) or 0


def _discovery_source(*, status: str, notes: str | None, parser_config: dict[str, object]) -> dict[str, object]:
    return {
        "id": "hf-discovery-transition-fixture",
        "benchmark_id": "hf_official_benchmarks",
        "source_name": "HF discovery transition fixture",
        "source_url": "https://example.invalid/api/datasets?filter=benchmark:official",
        "source_type": "hf_benchmark_api",
        "officialness_level": "O5",
        "machine_readable": True,
        "requires_auth": False,
        "supports_history": False,
        "update_cadence": "daily",
        "parser_name": "hf_benchmark_api",
        "parser_config": parser_config,
        "status": status,
        "notes": notes,
    }


def test_retiring_discovery_source_appends_a_revision_and_retains_old_snapshot(seeded_db):
    active = _discovery_source(status="active", notes=None, parser_config={"mode": "discovery"})
    retired = _discovery_source(
        status="inactive",
        notes="Retired LDR-06: dataset discovery is not result evidence.",
        parser_config={
            "mode": "discovery",
            "retirement_reason": "dataset discovery metadata is not benchmark result evidence",
        },
    )
    with get_session() as session:
        initial = repo.reconcile_official_source(session, active, registry_managed=True)
        snapshot = repo.insert_snapshot(
            session,
            official_source_id=initial.source.id,
            source_revision_id=initial.revision.id,
            raw_content_uri="file:///test-only/hf-discovery.json",
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
        # This stands in for an old discovery pseudo-claim that was accepted
        # before this route was retired. It must remain queryable evidence, not
        # be deleted or rewritten by the source transition.
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
            model_raw="dataset/example",
            benchmark_raw="hf_official_benchmarks",
            score_raw="n/a",
            evidence_location={"type": "json_path_v1", "record_path": "$[0]"},
            capture_method="legacy_discovery",
            capture_confidence=0.5,
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
        assert result.revision.notes == retired["notes"]
        assert result.revision.parser_config["retirement_reason"] == retired["parser_config"][
            "retirement_reason"
        ]
        assert snapshot.source_revision_id == initial.revision.id
        preserved_claim = session.get(models.ResultClaim, claim_row.id)
        assert preserved_claim is not None
        assert (
            preserved_claim.source_snapshot_id,
            preserved_claim.model_raw,
            preserved_claim.score_raw,
        ) == (snapshot.id, "dataset/example", "n/a")
        assert decision is not None
        assert (decision.outcome, decision.reason_code) == ("quarantined", "registry_definition_changed")


def test_retired_discovery_source_never_dispatches_or_writes(seeded_db, monkeypatch):
    with get_session() as session:
        before = {
            "runs": _count(session, models.IngestionRun),
            "snapshots": _count(session, models.SourceSnapshot),
            "claims": _count(session, models.ResultClaim),
        }
        monkeypatch.setattr(
            ingestion_runner,
            "get_adapter",
            lambda *_args, **_kwargs: pytest.fail("inactive discovery source must not dispatch an adapter"),
        )

        with pytest.raises(IngestionBlockedError, match="No production-eligible source"):
            run_ingestion(session, source_id="hf_official_benchmark_discovery", dry_run=True)

        assert {
            "runs": _count(session, models.IngestionRun),
            "snapshots": _count(session, models.SourceSnapshot),
            "claims": _count(session, models.ResultClaim),
        } == before
