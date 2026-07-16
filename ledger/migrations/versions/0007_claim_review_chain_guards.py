"""Freeze captured claim projections and enforce linear review decisions."""

from __future__ import annotations

from alembic import op

from migrations._dialect import is_sqlite


revision = "0007_claim_review_chain_guards"
down_revision = "0006_effective_claim_admission_guard"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not is_sqlite():
        return
    # Raw source evidence was already immutable.  The admitted identity and
    # capture-status projection must be immutable too: later correction or
    # review belongs to a new ClaimReviewDecision, never an UPDATE of the
    # captured observation.  Existing values are deliberately preserved.
    op.execute(
        """
        CREATE TRIGGER trg_result_claims_review_projection_no_update
        BEFORE UPDATE OF benchmark_id, model_entity_id, capture_status, scientific_status
        ON result_claims
        FOR EACH ROW
        WHEN
            NEW.benchmark_id IS NOT OLD.benchmark_id OR
            NEW.model_entity_id IS NOT OLD.model_entity_id OR
            NEW.capture_status IS NOT OLD.capture_status OR
            NEW.scientific_status IS NOT OLD.scientific_status
        BEGIN
            SELECT RAISE(
                ABORT,
                'result_claim review projection is immutable; append a claim review decision'
            );
        END
        """
    )

    # A review supersession must stay within one claim and may only extend its
    # current leaf.  This prevents the repository's effective-decision reader
    # from having to guess between parallel decision branches.
    op.execute(
        """
        CREATE TRIGGER trg_claim_review_decisions_parent_insert
        BEFORE INSERT ON claim_review_decisions
        FOR EACH ROW
        WHEN NEW.supersedes_decision_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1
              FROM claim_review_decisions parent
              WHERE parent.id = NEW.supersedes_decision_id
                AND parent.result_claim_id = NEW.result_claim_id
          )
        BEGIN
            SELECT RAISE(ABORT, 'claim review decision must supersede a decision for the same claim');
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_claim_review_decisions_linear_insert
        BEFORE INSERT ON claim_review_decisions
        FOR EACH ROW
        WHEN (
            NEW.supersedes_decision_id IS NULL
            AND EXISTS (
                SELECT 1
                FROM claim_review_decisions existing
                WHERE existing.result_claim_id = NEW.result_claim_id
            )
        ) OR (
            NEW.supersedes_decision_id IS NOT NULL
            AND EXISTS (
                SELECT 1
                FROM claim_review_decisions successor
                WHERE successor.supersedes_decision_id = NEW.supersedes_decision_id
            )
        )
        BEGIN
            SELECT RAISE(ABORT, 'claim review decisions must form one append-only linear chain');
        END
        """
    )

    # Even containment-only publication decisions must cite the latest review
    # decision.  A future publication gate therefore cannot revive a stale
    # decision that predates a failed validation or later review without a new
    # recorded supersession.
    op.execute(
        """
        CREATE TRIGGER trg_claim_publication_decisions_current_review_insert
        BEFORE INSERT ON claim_publication_decisions
        FOR EACH ROW
        WHEN NOT EXISTS (
            SELECT 1
            FROM claim_review_decisions review
            WHERE review.id = NEW.claim_review_decision_id
              AND review.result_claim_id = NEW.result_claim_id
              AND NOT EXISTS (
                  SELECT 1
                  FROM claim_review_decisions successor
                  WHERE successor.supersedes_decision_id = review.id
              )
        )
        BEGIN
            SELECT RAISE(
                ABORT,
                'claim publication decision must reference the current effective claim review decision'
            );
        END
        """
    )


def downgrade() -> None:
    raise RuntimeError(
        "Ledger migrations are recovery-only: restore the verified pre-migration backup instead of downgrading."
    )
