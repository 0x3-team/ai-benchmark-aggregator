from pathlib import Path

import pytest
from sqlalchemy import func, select
from typer.testing import CliRunner

from app.cli import app
from app.db import models, repositories as repo
from app.db.engine import get_session
from app.ingestion.runner import run_ingestion


FIXTURE = Path(__file__).parent / "fixtures" / "fake_source.json"
runner = CliRunner()


def _unknown_claim(session):  # type: ignore[no-untyped-def]
    claim = session.scalar(
        select(models.ResultClaim).where(models.ResultClaim.model_raw == "Unknown-Model-X")
    )
    assert claim is not None
    return claim


def test_manual_model_mapping_is_append_only_and_does_not_promote_status(
    seeded_db, allow_quarantined_fixture_ingestion
):
    with get_session() as session:
        run_ingestion(session, source_id="fake_local_fixture", fixture_path=FIXTURE)
        claim = _unknown_claim(session)
        before = {
            "model_raw": claim.model_raw,
            "model_entity_id": claim.model_entity_id,
            "capture_status": claim.capture_status,
            "validations": session.scalar(
                select(func.count()).select_from(models.ClaimValidation).where(
                    models.ClaimValidation.result_claim_id == claim.id
                )
            ),
            "publication": session.scalar(
                select(func.count()).select_from(models.ClaimPublicationDecision).where(
                    models.ClaimPublicationDecision.result_claim_id == claim.id
                )
            ),
        }

        decision = repo.append_manual_model_mapping(
            session,
            result_claim_id=claim.id,
            model_entity_id="fake_model_1",
            actor="pytest",
        )
        session.refresh(claim)
        projection = repo.get_claim_review_projection(session, claim)

        assert decision.outcome == "identity_resolved"
        assert decision.reason_code == "manual_model_mapping"
        assert decision.model_entity_id == "fake_model_1"
        assert decision.supersedes_decision_id is None
        assert decision.basis_json["model_raw"] == before["model_raw"]
        assert claim.model_raw == before["model_raw"]
        assert claim.model_entity_id == before["model_entity_id"] is None
        assert claim.capture_status == before["capture_status"] == "parser_verified"
        assert projection.model_entity_id == "fake_model_1"
        assert projection.effective_decision_id == decision.id
        assert session.scalar(
            select(func.count()).select_from(models.ClaimValidation).where(
                models.ClaimValidation.result_claim_id == claim.id
            )
        ) == before["validations"]
        assert session.scalar(
            select(func.count()).select_from(models.ClaimPublicationDecision).where(
                models.ClaimPublicationDecision.result_claim_id == claim.id
            )
        ) == before["publication"]

        # Mapping resolves only identity. It does not alter the independent
        # capture status, validation history, or publication state.
        assert claim not in repo.list_review_queue(session)
        with pytest.raises(repo.ReviewWorkflowUnavailableError, match="Mutable model mapping"):
            repo.map_claim_model(session, claim.id, "fake_model_1")
        with pytest.raises(repo.ReviewWorkflowUnavailableError, match="Human-verification"):
            repo.mark_human_verified(session, claim.id)


def test_manual_model_mapping_cli_is_registered_and_preserves_claim_fields(
    seeded_db, allow_quarantined_fixture_ingestion
):
    with get_session() as session:
        run_ingestion(session, source_id="fake_local_fixture", fixture_path=FIXTURE)
        claim = _unknown_claim(session)
        claim_id = claim.id
        before_model = claim.model_entity_id
        before_status = claim.capture_status

    help_result = runner.invoke(app, ["review", "map-model", "--help"])
    result = runner.invoke(app, ["review", "map-model", claim_id, "fake_model_1", "--actor", "operator"])
    claim_detail = runner.invoke(app, ["claims", "show", claim_id])
    blocked_human = runner.invoke(app, ["review", "mark-human-verified", claim_id])
    blocked_bulk = runner.invoke(app, ["review", "auto-verify-matched"])

    assert help_result.exit_code == 0
    assert "Append a manual model-identity decision" in help_result.output
    assert result.exit_code == 0
    assert "Recorded manual model mapping" in result.output
    assert "captured claim and validation status are unchanged" in result.output
    assert claim_detail.exit_code == 0
    assert "captured_model_entity_id: None" in claim_detail.output
    assert "effective_model_entity_id: fake_model_1" in claim_detail.output
    assert blocked_human.exit_code == 2
    assert "disabled during Official-mode containment" in blocked_human.output
    assert blocked_bulk.exit_code == 2
    assert "bulk mapping must never promote" in blocked_bulk.output

    with get_session() as session:
        claim = session.get(models.ResultClaim, claim_id)
        assert claim is not None
        assert claim.model_entity_id == before_model is None
        assert claim.capture_status == before_status == "parser_verified"
        decisions = list(
            session.scalars(
                select(models.ClaimReviewDecision).where(
                    models.ClaimReviewDecision.result_claim_id == claim_id
                )
            )
        )
        assert len(decisions) == 1
        assert decisions[0].actor == "operator"
        assert decisions[0].model_entity_id == "fake_model_1"


def test_review_chain_requires_a_new_effective_decision_before_a_publication_record(
    seeded_db, allow_quarantined_fixture_ingestion
):
    with get_session() as session:
        run_ingestion(session, source_id="fake_local_fixture", fixture_path=FIXTURE)
        claim = _unknown_claim(session)
        first = repo.append_manual_model_mapping(
            session,
            result_claim_id=claim.id,
            model_entity_id="fake_model_1",
        )
        session.add(
            models.ClaimValidation(
                result_claim_id=claim.id,
                validation_type="adversarial_fixture",
                outcome="fail",
                validator="pytest",
                notes="A later validation failure requires a new review decision.",
            )
        )
        session.flush()
        reviewed = repo.append_claim_review_decision(
            session,
            result_claim_id=claim.id,
            outcome="validation_reviewed",
            reason_code="failed_validation_reviewed",
            basis_json={"reviewed_validation": "adversarial_fixture"},
            actor="pytest",
            supersedes_decision_id=first.id,
        )

        # A publication record cannot cite the stale identity decision. A
        # newly recorded review decision is required even for non-publishing
        # containment outcomes.
        with pytest.raises(repo.ClaimReviewChainError, match="current effective"):
            repo.append_claim_publication_decision(
                session,
                result_claim_id=claim.id,
                claim_review_decision_id=first.id,
                outcome="quarantined",
                policy_version="pytest-v1",
                reason_code="stale_review",
            )
        with pytest.raises(ValueError, match="Official publication approval is unavailable"):
            repo.append_claim_publication_decision(
                session,
                result_claim_id=claim.id,
                claim_review_decision_id=reviewed.id,
                outcome="approved",
                policy_version="pytest-v1",
                reason_code="attempted_promotion_after_failed_validation",
            )

        containment = repo.append_claim_publication_decision(
            session,
            result_claim_id=claim.id,
            claim_review_decision_id=reviewed.id,
            outcome="quarantined",
            policy_version="pytest-v1",
            reason_code="failed_validation_quarantined",
        )
        assert containment.outcome == "quarantined"
        assert containment.claim_review_decision_id == reviewed.id

        with pytest.raises(repo.ClaimReviewChainError, match="must supersede"):
            repo.append_claim_review_decision(
                session,
                result_claim_id=claim.id,
                outcome="needs_review",
                reason_code="parallel_branch",
            )
