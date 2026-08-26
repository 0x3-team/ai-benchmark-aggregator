"""Narrow ingestion-run updates and freeze run history on PostgreSQL.

The ingestion runner inserts a ``running`` row and finalizes it once.  This
revision keeps SQLite unchanged while PostgreSQL rejects identity rewrites,
updates to terminal rows, and any second finalization.
"""

from __future__ import annotations

from alembic import op

from migrations._dialect import is_postgresql


revision = "0011_ingestion_run_hardening"
down_revision = "0010_operational_persistence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not is_postgresql():
        return

    op.execute(
        """
        CREATE FUNCTION ledger_validate_ingestion_run_finalization()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, public
        AS $function$
        BEGIN
            IF OLD.status IS DISTINCT FROM 'running'
               OR OLD.finished_at IS NOT NULL
               OR NEW.status IS NULL
               OR NEW.status NOT IN ('completed', 'partial', 'failed')
               OR NEW.finished_at IS NULL
               OR NEW.id IS DISTINCT FROM OLD.id
               OR NEW.started_at IS DISTINCT FROM OLD.started_at
               OR NEW.run_type IS DISTINCT FROM OLD.run_type
               OR NEW.official_source_id IS DISTINCT FROM OLD.official_source_id
            THEN
                RAISE EXCEPTION
                    'ingestion run identity/history is immutable; only one terminal finalization is allowed'
                    USING ERRCODE = '23000';
            END IF;
            RETURN NEW;
        END;
        $function$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_ingestion_runs_finalize_once
        BEFORE UPDATE ON ingestion_runs
        FOR EACH ROW EXECUTE FUNCTION ledger_validate_ingestion_run_finalization()
        """
    )
    op.execute(
        "REVOKE ALL ON FUNCTION ledger_validate_ingestion_run_finalization() FROM PUBLIC"
    )


def downgrade() -> None:
    raise RuntimeError(
        "Ledger migrations are recovery-only: restore the verified pre-migration backup instead of downgrading."
    )
