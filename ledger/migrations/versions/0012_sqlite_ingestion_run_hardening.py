"""Freeze one ingestion-run finalization on SQLite.

0011 installed the finalize-once guard on PostgreSQL only.  This forward-only
revision brings the same immutability to SQLite so both dialects reject
identity rewrites, updates to terminal rows, and any second finalization:
the runner inserts a ``running`` row and finalizes it exactly once into
``completed``/``partial``/``failed`` with a non-null ``finished_at``.
"""

from __future__ import annotations

from alembic import op

from migrations._dialect import is_sqlite


revision = "0012_sqlite_ingestion_run_hardening"
down_revision = "0011_ingestion_run_hardening"
branch_labels = None
depends_on = None

# Stable error text shared by every rejected mutation, matching the
# PostgreSQL 0011 guard so both engines surface the same contract.
_FINALIZE_ERROR = "ingestion run identity/history is immutable; only one terminal finalization is allowed"


def upgrade() -> None:
    if not is_sqlite():
        return
    op.execute(
        f"""
        CREATE TRIGGER trg_ingestion_runs_finalize_once
        BEFORE UPDATE ON ingestion_runs
        FOR EACH ROW
        WHEN NEW.id IS NOT OLD.id
          OR NEW.started_at IS NOT OLD.started_at
          OR NEW.run_type IS NOT OLD.run_type
          OR NEW.official_source_id IS NOT OLD.official_source_id
          OR OLD.status IS NOT 'running'
          OR OLD.finished_at IS NOT NULL
          OR NEW.status IS NULL
          OR NEW.status NOT IN ('completed', 'partial', 'failed')
          OR NEW.finished_at IS NULL
        BEGIN
            SELECT RAISE(ABORT, '{_FINALIZE_ERROR}');
        END
        """
    )


def downgrade() -> None:
    raise RuntimeError(
        "Ledger migrations are recovery-only: restore the verified pre-migration backup instead of downgrading."
    )