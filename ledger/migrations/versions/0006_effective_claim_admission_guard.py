"""Harden future claim inserts against stale or superseded source decisions."""

from __future__ import annotations

from alembic import op

from migrations._dialect import is_sqlite


revision = "0006_effective_claim_admission_guard"
down_revision = "0005_claim_admission_provenance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 0005 made a decision reference mandatory. This successor also proves
    # that it is the single effective certified leaf for the *current* source
    # revision. Historic rows are deliberately untouched: the guard applies
    # only to future inserts and cannot rewrite legacy evidence.
    if not is_sqlite():
        return
    op.execute("DROP TRIGGER IF EXISTS trg_result_claims_admission_decision_insert")
    op.execute(
        """
        CREATE TRIGGER trg_result_claims_admission_decision_insert
        BEFORE INSERT ON result_claims
        FOR EACH ROW
        WHEN NEW.source_revision_decision_id IS NULL
          OR NOT EXISTS (
              SELECT 1
              FROM source_revision_decisions decision
              JOIN source_snapshots snapshot ON snapshot.id = NEW.source_snapshot_id
              JOIN official_sources source ON source.id = snapshot.official_source_id
              WHERE decision.id = NEW.source_revision_decision_id
                AND decision.source_revision_id = snapshot.source_revision_id
                AND snapshot.official_source_id = NEW.official_source_id
                AND source.current_revision_id = snapshot.source_revision_id
                AND decision.outcome = 'certified'
                AND NOT EXISTS (
                    SELECT 1
                    FROM source_revision_decisions successor
                    WHERE successor.supersedes_decision_id = decision.id
                )
                AND 1 = (
                    SELECT COUNT(*)
                    FROM source_revision_decisions leaf
                    WHERE leaf.source_revision_id = snapshot.source_revision_id
                      AND NOT EXISTS (
                          SELECT 1
                          FROM source_revision_decisions successor
                          WHERE successor.supersedes_decision_id = leaf.id
                      )
                )
          )
        BEGIN
            SELECT RAISE(
                ABORT,
                'new result claims require a current effective certified source decision for the snapshot revision'
            );
        END
        """
    )


def downgrade() -> None:
    raise RuntimeError(
        "Ledger migrations are recovery-only: restore the verified pre-migration backup instead of downgrading."
    )
