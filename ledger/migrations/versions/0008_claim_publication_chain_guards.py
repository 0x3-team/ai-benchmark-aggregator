"""Enforce one append-only publication-decision chain per claim."""

from __future__ import annotations

from alembic import op

from migrations._dialect import is_sqlite


revision = "0008_claim_publication_chain_guards"
down_revision = "0007_claim_review_chain_guards"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not is_sqlite():
        return
    # Publication decisions are evidence just like review decisions.  The
    # 0007 guard already requires every new publication decision to cite the
    # current review leaf.  These two guards additionally prevent a caller
    # from creating competing publication leaves, which would otherwise make
    # an export's eligibility depend on query ordering.
    op.execute(
        """
        CREATE TRIGGER trg_claim_publication_decisions_parent_insert
        BEFORE INSERT ON claim_publication_decisions
        FOR EACH ROW
        WHEN NEW.supersedes_decision_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1
              FROM claim_publication_decisions parent
              WHERE parent.id = NEW.supersedes_decision_id
                AND parent.result_claim_id = NEW.result_claim_id
          )
        BEGIN
            SELECT RAISE(
                ABORT,
                'claim publication decision must supersede a decision for the same claim'
            );
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_claim_publication_decisions_linear_insert
        BEFORE INSERT ON claim_publication_decisions
        FOR EACH ROW
        WHEN (
            NEW.supersedes_decision_id IS NULL
            AND EXISTS (
                SELECT 1
                FROM claim_publication_decisions existing
                WHERE existing.result_claim_id = NEW.result_claim_id
            )
        ) OR (
            NEW.supersedes_decision_id IS NOT NULL
            AND EXISTS (
                SELECT 1
                FROM claim_publication_decisions successor
                WHERE successor.supersedes_decision_id = NEW.supersedes_decision_id
            )
        )
        BEGIN
            SELECT RAISE(
                ABORT,
                'claim publication decisions must form one append-only linear chain'
            );
        END
        """
    )


def downgrade() -> None:
    raise RuntimeError(
        "Ledger migrations are recovery-only: restore the verified pre-migration backup instead of downgrading."
    )
