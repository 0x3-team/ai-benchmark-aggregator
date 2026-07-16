"""Bind newly admitted claims to a certified source decision and identity version."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from migrations._dialect import is_sqlite


revision = "0005_claim_admission_provenance"
down_revision = "0004_registry_source_reconciliation"
branch_labels = None
depends_on = None


def _replace_result_claim_guards() -> None:
    # The raw-evidence guard was introduced in 0003.  Adding columns with
    # SQLite ALTER TABLE preserves historic rows, then this replacement makes
    # the new provenance and evaluation-version fields equally immutable.
    op.execute("DROP TRIGGER IF EXISTS trg_result_claims_raw_no_update")
    op.execute(
        """
        CREATE TRIGGER trg_result_claims_raw_no_update
        BEFORE UPDATE OF
            source_snapshot_id, source_revision_decision_id, official_source_id,
            model_raw, benchmark_raw, score_raw, metric_raw, split_raw,
            setting_raw, evaluation_version_raw, rank_raw, date_raw,
            score_numeric, score_unit, evidence_text, evidence_location,
            capture_method, capture_confidence, officialness_level,
            claim_fingerprint
        ON result_claims
        FOR EACH ROW
        WHEN
            NEW.source_snapshot_id IS NOT OLD.source_snapshot_id OR
            NEW.source_revision_decision_id IS NOT OLD.source_revision_decision_id OR
            NEW.official_source_id IS NOT OLD.official_source_id OR
            NEW.model_raw IS NOT OLD.model_raw OR
            NEW.benchmark_raw IS NOT OLD.benchmark_raw OR
            NEW.score_raw IS NOT OLD.score_raw OR
            NEW.metric_raw IS NOT OLD.metric_raw OR
            NEW.split_raw IS NOT OLD.split_raw OR
            NEW.setting_raw IS NOT OLD.setting_raw OR
            NEW.evaluation_version_raw IS NOT OLD.evaluation_version_raw OR
            NEW.rank_raw IS NOT OLD.rank_raw OR
            NEW.date_raw IS NOT OLD.date_raw OR
            NEW.score_numeric IS NOT OLD.score_numeric OR
            NEW.score_unit IS NOT OLD.score_unit OR
            NEW.evidence_text IS NOT OLD.evidence_text OR
            NEW.evidence_location IS NOT OLD.evidence_location OR
            NEW.capture_method IS NOT OLD.capture_method OR
            NEW.capture_confidence IS NOT OLD.capture_confidence OR
            NEW.officialness_level IS NOT OLD.officialness_level OR
            NEW.claim_fingerprint IS NOT OLD.claim_fingerprint
        BEGIN
            SELECT RAISE(ABORT, 'result_claim raw evidence is immutable');
        END
        """
    )
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
              WHERE decision.id = NEW.source_revision_decision_id
                AND decision.source_revision_id = snapshot.source_revision_id
                AND snapshot.official_source_id = NEW.official_source_id
          )
        BEGIN
            SELECT RAISE(
                ABORT,
                'new result claims require a source decision for the snapshot revision'
            );
        END
        """
    )


def upgrade() -> None:
    # Nullable fields preserve legacy evidence byte-for-byte.  The insert
    # trigger below applies only to future claims and requires an explicit
    # source-revision decision bound to the snapshot's revision.
    op.add_column(
        "result_claims",
        sa.Column("source_revision_decision_id", sa.String(length=36), nullable=True),
    )
    op.add_column(
        "result_claims",
        sa.Column("evaluation_version_raw", sa.String(length=128), nullable=True),
    )
    if is_sqlite():
        _replace_result_claim_guards()


def downgrade() -> None:
    raise RuntimeError(
        "Ledger migrations are recovery-only: restore the verified pre-migration backup instead of downgrading."
    )
