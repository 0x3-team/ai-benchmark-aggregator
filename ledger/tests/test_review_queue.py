from pathlib import Path
import os
import pwd

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
    # F17: caller-supplied --actor must be rejected before any row is written.
    forged = runner.invoke(
        app,
        ["review", "map-model", claim_id, "fake_model_1", "--actor", "operator"],
        env={"USER": "forged-user", "LOGNAME": "forged-logname"},
    )
    result = runner.invoke(
        app,
        ["review", "map-model", claim_id, "fake_model_1"],
        env={"USER": "forged-user", "LOGNAME": "forged-logname"},
    )
    claim_detail = runner.invoke(app, ["claims", "show", claim_id])
    blocked_human = runner.invoke(app, ["review", "mark-human-verified", claim_id])
    blocked_bulk = runner.invoke(app, ["review", "auto-verify-matched"])

    assert help_result.exit_code == 0
    assert "Append a manual model-identity decision" in help_result.output
    assert forged.exit_code == 2
    assert "No such option" in forged.output
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
        # F17: the persisted actor is the canonical OS-bound principal
        # (posix:euid=<euid>;name=<name>), not the forged USER/LOGNAME value.
        euid = os.geteuid()
        expected_actor = f"posix:euid={euid};name={pwd.getpwuid(euid).pw_name}"
        assert decisions[0].actor == expected_actor
        assert decisions[0].actor != "forged-user"
        assert decisions[0].actor != "forged-logname"
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


def test_cli_queue_shows_continuation_for_empty_but_unexhausted_page(
    seeded_db, allow_quarantined_fixture_ingestion, tmp_path: Path
):
    """CLI renders continuation when a bounded page yields zero eligible items.

    Regression for the defect where the CLI printed "Review queue empty" and
    returned as soon as a bounded page had no eligible items, hiding later work.
    """
    from app.db import repositories as _repo
    from app.db import models as _models
    from app.db.engine import get_session

    # Create claims via the institutional ingestion path, then resolve the model
    # identity of enough claims so the first page (limit=3) is a zero-eligible
    # but non-exhausted page, proving the CLI surfaces a usable continuation.
    with get_session() as session:
        run_ingestion(session, source_id="fake_local_fixture", fixture_path=FIXTURE)

    # Resolve only the single newest claim so limit=1 yields a zero-eligible
    # first window while an older eligible row remains -> a usable cursor.
    with get_session() as session:
        newest = session.scalars(
            select(_models.ResultClaim)
            .order_by(_models.ResultClaim.created_at.desc(), _models.ResultClaim.id.desc())
            .limit(1)
        ).first()
        assert newest is not None
        if session.get(_models.ModelEntity, "cli-resolved-model") is None:
            session.add(
                _models.ModelEntity(
                    id="cli-resolved-model",
                    canonical_name="cli-resolved",
                    display_name="CLI resolved",
                    entity_type="model",
                )
            )
        session.flush()
        _repo.append_manual_model_mapping(
            session, result_claim_id=newest.id, model_entity_id="cli-resolved-model", actor="pytest"
        )
        session.flush()

    result = runner.invoke(app, ["review", "queue", "--limit", "1"])
    assert result.exit_code == 0
    # The first window reads 1 (newest, now ineligible) but older rows remain.
    assert "Next cursor" in result.output
    assert "Continuation available" in result.output
    assert "Review queue empty." not in result.output

    # Continue with the cursor.  The remaining rows may be ineligible too, so
    # drain until an eligible "Claim ID" appears.  A truly exhausted page prints
    # "Review queue empty." and emits no cursor — that is only reached at the
    # true end of the queue and is the *correct* terminal rendering, never a
    # false early "empty" while ``Next cursor`` remained available.
    import re as _re

    m = _re.search(r"Next cursor: (\S+)", result.output)
    assert m is not None
    nxt = m.group(1)
    found_eligible = False
    result2 = result
    for _ in range(8):
        result2 = runner.invoke(app, ["review", "queue", "--limit", "1", "--cursor", nxt])
        assert result2.exit_code == 0
        if "Claim ID:" in result2.output:
            found_eligible = True
            break
        m2 = _re.search(r"Next cursor: (\S+)", result2.output)
        if m2 is None:
            # No cursor -> truly exhausted; only allowed as the terminal state.
            assert "Review queue empty." in result2.output or "exhausted" in result2.output
            break
        nxt = m2.group(1)
    # We reached an eligible claim (regression goal) OR legitimately drained the
    # whole queue through continuation pages without ever a stale early "empty".
    assert found_eligible or "Next cursor" not in result2.output
