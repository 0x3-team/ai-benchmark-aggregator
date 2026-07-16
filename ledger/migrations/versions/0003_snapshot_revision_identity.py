"""Bind snapshots to immutable source revisions and enforce append-only rows."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from migrations._dialect import is_offline, is_sqlite


revision = "0003_snapshot_revision_identity"
down_revision = "0002_governance_history"
branch_labels = None
depends_on = None


def _create_append_only_triggers() -> None:
    immutable_tables = (
        "official_source_revisions",
        "source_revision_decisions",
        "source_snapshots",
        "claim_validations",
        "claim_relationships",
        "claim_review_decisions",
        "claim_publication_decisions",
    )
    for table in immutable_tables:
        op.execute(
            f"""
            CREATE TRIGGER trg_{table}_no_update
            BEFORE UPDATE ON {table}
            FOR EACH ROW
            BEGIN
                SELECT RAISE(ABORT, '{table} is append-only');
            END
            """
        )
        op.execute(
            f"""
            CREATE TRIGGER trg_{table}_no_delete
            BEFORE DELETE ON {table}
            FOR EACH ROW
            BEGIN
                SELECT RAISE(ABORT, '{table} is append-only');
            END
            """
        )

    op.execute(
        """
        CREATE TRIGGER trg_result_claims_raw_no_update
        BEFORE UPDATE OF
            source_snapshot_id, official_source_id, model_raw, benchmark_raw,
            score_raw, metric_raw, split_raw, setting_raw, rank_raw, date_raw,
            score_numeric, score_unit, evidence_text, evidence_location,
            capture_method, capture_confidence, officialness_level,
            claim_fingerprint
        ON result_claims
        FOR EACH ROW
        WHEN
            NEW.source_snapshot_id IS NOT OLD.source_snapshot_id OR
            NEW.official_source_id IS NOT OLD.official_source_id OR
            NEW.model_raw IS NOT OLD.model_raw OR
            NEW.benchmark_raw IS NOT OLD.benchmark_raw OR
            NEW.score_raw IS NOT OLD.score_raw OR
            NEW.metric_raw IS NOT OLD.metric_raw OR
            NEW.split_raw IS NOT OLD.split_raw OR
            NEW.setting_raw IS NOT OLD.setting_raw OR
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
    op.execute(
        """
        CREATE TRIGGER trg_ingestion_runs_no_delete
        BEFORE DELETE ON ingestion_runs
        FOR EACH ROW
        BEGIN
            SELECT RAISE(ABORT, 'ingestion_runs are retained evidence');
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_official_sources_definition_no_update
        BEFORE UPDATE OF
            benchmark_id, source_name, source_url, source_type, officialness_level,
            machine_readable, requires_auth, supports_history, update_cadence,
            parser_name, parser_version, parser_config, status, notes
        ON official_sources
        FOR EACH ROW
        WHEN
            NEW.benchmark_id IS NOT OLD.benchmark_id OR
            NEW.source_name IS NOT OLD.source_name OR
            NEW.source_url IS NOT OLD.source_url OR
            NEW.source_type IS NOT OLD.source_type OR
            NEW.officialness_level IS NOT OLD.officialness_level OR
            NEW.machine_readable IS NOT OLD.machine_readable OR
            NEW.requires_auth IS NOT OLD.requires_auth OR
            NEW.supports_history IS NOT OLD.supports_history OR
            NEW.update_cadence IS NOT OLD.update_cadence OR
            NEW.parser_name IS NOT OLD.parser_name OR
            NEW.parser_version IS NOT OLD.parser_version OR
            NEW.parser_config IS NOT OLD.parser_config OR
            NEW.status IS NOT OLD.status OR
            NEW.notes IS NOT OLD.notes
        BEGIN
            SELECT RAISE(ABORT, 'logical source definition is immutable; create a source revision');
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_result_claims_no_delete
        BEFORE DELETE ON result_claims
        FOR EACH ROW
        BEGIN
            SELECT RAISE(ABORT, 'result_claims are append-only');
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_official_sources_current_revision_insert
        BEFORE INSERT ON official_sources
        FOR EACH ROW
        WHEN NEW.current_revision_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM official_source_revisions r
              WHERE r.id = NEW.current_revision_id
                AND r.official_source_id = NEW.id
          )
        BEGIN
            SELECT RAISE(ABORT, 'current_revision_id must belong to its logical source');
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_official_sources_current_revision_update
        BEFORE UPDATE OF current_revision_id ON official_sources
        FOR EACH ROW
        WHEN NEW.current_revision_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM official_source_revisions r
              WHERE r.id = NEW.current_revision_id
                AND r.official_source_id = NEW.id
          )
        BEGIN
            SELECT RAISE(ABORT, 'current_revision_id must belong to its logical source');
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_source_snapshots_revision_insert
        BEFORE INSERT ON source_snapshots
        FOR EACH ROW
        WHEN NOT EXISTS (
            SELECT 1 FROM official_source_revisions r
            WHERE r.id = NEW.source_revision_id
              AND r.official_source_id = NEW.official_source_id
        )
        BEGIN
            SELECT RAISE(ABORT, 'snapshot source revision must belong to its logical source');
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_source_snapshots_revision_update
        BEFORE UPDATE OF official_source_id, source_revision_id ON source_snapshots
        FOR EACH ROW
        WHEN NOT EXISTS (
            SELECT 1 FROM official_source_revisions r
            WHERE r.id = NEW.source_revision_id
              AND r.official_source_id = NEW.official_source_id
        )
        BEGIN
            SELECT RAISE(ABORT, 'snapshot source revision must belong to its logical source');
        END
        """
    )


def upgrade() -> None:
    if not is_offline():
        bind = op.get_bind()
        missing = bind.execute(
            sa.text("SELECT COUNT(*) FROM source_snapshots WHERE source_revision_id IS NULL")
        ).scalar_one()
        if missing:
            raise RuntimeError(
                "Cannot enforce snapshot revision identity: legacy backfill left "
                f"{missing} source snapshot(s) without a source revision. Restore the backup and investigate."
            )

    if is_sqlite():
        # Alembic's batch mode reconstructs SQLite's constrained table. It
        # changes only the schema: data was populated by 0002 and is copied
        # byte-for-byte.
        with op.batch_alter_table("source_snapshots", recreate="always") as batch_op:
            batch_op.drop_constraint("uq_source_hash", type_="unique")
            batch_op.alter_column(
                "source_revision_id",
                existing_type=sa.String(length=36),
                nullable=False,
            )
            batch_op.create_foreign_key(
                "fk_source_snapshots_source_revision",
                "official_source_revisions",
                ["source_revision_id"],
                ["id"],
            )
            batch_op.create_unique_constraint(
                "uq_source_revision_hash", ["source_revision_id", "content_hash"]
            )
    else:
        op.drop_constraint("uq_source_hash", "source_snapshots", type_="unique")
        op.alter_column(
            "source_snapshots",
            "source_revision_id",
            existing_type=sa.String(length=36),
            nullable=False,
        )
        op.create_foreign_key(
            "fk_source_snapshots_source_revision",
            "source_snapshots",
            "official_source_revisions",
            ["source_revision_id"],
            ["id"],
        )
        op.create_unique_constraint(
            "uq_source_revision_hash",
            "source_snapshots",
            ["source_revision_id", "content_hash"],
        )
    if is_sqlite():
        _create_append_only_triggers()


def downgrade() -> None:
    raise RuntimeError("Ledger migrations are recovery-only: restore the verified pre-migration backup instead of downgrading.")
