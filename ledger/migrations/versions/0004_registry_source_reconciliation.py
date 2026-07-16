"""Permit only revision-backed source projection updates and registry retirement."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from migrations._dialect import is_postgresql, is_sqlite


revision = "0004_registry_source_reconciliation"
down_revision = "0003_snapshot_revision_identity"
branch_labels = None
depends_on = None


def _create_revision_reference_triggers() -> None:
    """Restore guards on tables that reference a batch-rebuilt revision table."""
    op.execute(
        """
        CREATE TRIGGER trg_official_sources_current_revision_insert
        BEFORE INSERT ON official_sources
        FOR EACH ROW
        WHEN NEW.current_revision_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM official_source_revisions revision
              WHERE revision.id = NEW.current_revision_id
                AND revision.official_source_id = NEW.id
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
              SELECT 1 FROM official_source_revisions revision
              WHERE revision.id = NEW.current_revision_id
                AND revision.official_source_id = NEW.id
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
            SELECT 1 FROM official_source_revisions revision
            WHERE revision.id = NEW.source_revision_id
              AND revision.official_source_id = NEW.official_source_id
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
            SELECT 1 FROM official_source_revisions revision
            WHERE revision.id = NEW.source_revision_id
              AND revision.official_source_id = NEW.official_source_id
        )
        BEGIN
            SELECT RAISE(ABORT, 'snapshot source revision must belong to its logical source');
        END
        """
    )


def upgrade() -> None:
    if is_postgresql():
        # Alembic's default version column is VARCHAR(32), but the existing
        # descriptive forward-only revision IDs intentionally exceed that
        # limit. Widen before Alembic records this revision.
        op.alter_column(
            "alembic_version",
            "version_num",
            existing_type=sa.String(length=32),
            type_=sa.String(length=128),
            nullable=False,
        )
    op.add_column(
        "official_sources",
        sa.Column("registry_managed", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    # A source may legitimately return to an earlier byte-identical definition
    # after being retired. Revision ordinal/lineage, rather than definition
    # hash uniqueness, is the historical identity. Batch recreation also drops
    # the source-revision triggers, so recreate those guards below.
    if is_sqlite():
        # SQLite refuses a source-revision table rename while triggers on
        # other tables reference it. Drop and restore those guards around the
        # batch rebuild; their definitions remain owned by this chain.
        for trigger_name in (
            "trg_official_sources_current_revision_insert",
            "trg_official_sources_current_revision_update",
            "trg_source_snapshots_revision_insert",
            "trg_source_snapshots_revision_update",
        ):
            op.execute(f"DROP TRIGGER {trigger_name}")
        with op.batch_alter_table("official_source_revisions", recreate="always") as batch_op:
            batch_op.drop_constraint("uq_source_revision_definition", type_="unique")
    else:
        op.drop_constraint(
            "uq_source_revision_definition",
            "official_source_revisions",
            type_="unique",
        )
        return
    op.execute(
        """
        CREATE TRIGGER trg_official_source_revisions_no_update
        BEFORE UPDATE ON official_source_revisions
        FOR EACH ROW
        BEGIN
            SELECT RAISE(ABORT, 'official_source_revisions are append-only');
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_official_source_revisions_no_delete
        BEFORE DELETE ON official_source_revisions
        FOR EACH ROW
        BEGIN
            SELECT RAISE(ABORT, 'official_source_revisions are append-only');
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_official_source_revisions_definition_insert
        BEFORE INSERT ON official_source_revisions
        FOR EACH ROW
        WHEN json_valid(NEW.definition_json) = 0
          OR json_extract(NEW.definition_json, '$.benchmark_id') IS NOT (
              SELECT benchmark_id FROM official_sources WHERE id = NEW.official_source_id
          )
          OR json_extract(NEW.definition_json, '$.source_name') IS NOT NEW.source_name
          OR json_extract(NEW.definition_json, '$.source_url') IS NOT NEW.source_url
          OR json_extract(NEW.definition_json, '$.source_type') IS NOT NEW.source_type
          OR json_extract(NEW.definition_json, '$.officialness_level') IS NOT NEW.officialness_level
          OR json_extract(NEW.definition_json, '$.machine_readable') IS NOT NEW.machine_readable
          OR json_extract(NEW.definition_json, '$.requires_auth') IS NOT NEW.requires_auth
          OR json_extract(NEW.definition_json, '$.supports_history') IS NOT NEW.supports_history
          OR json_extract(NEW.definition_json, '$.update_cadence') IS NOT NEW.update_cadence
          OR json_extract(NEW.definition_json, '$.parser_name') IS NOT NEW.parser_name
          OR json_extract(NEW.definition_json, '$.parser_version') IS NOT NEW.parser_version
          OR json(NEW.parser_config) IS NOT json(json_extract(NEW.definition_json, '$.parser_config'))
          OR json_extract(NEW.definition_json, '$.status') IS NOT NEW.status
          OR json_extract(NEW.definition_json, '$.notes') IS NOT NEW.notes
        BEGIN
            SELECT RAISE(
                ABORT,
                'source revision definition must match its immutable projection fields'
            );
        END
        """
    )
    _create_revision_reference_triggers()
    op.execute("DROP TRIGGER trg_official_sources_definition_no_update")
    op.execute(
        """
        CREATE TRIGGER trg_official_sources_id_no_update
        BEFORE UPDATE OF id ON official_sources
        FOR EACH ROW
        BEGIN
            SELECT RAISE(ABORT, 'logical source id is immutable');
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_official_sources_benchmark_no_update
        BEFORE UPDATE OF benchmark_id ON official_sources
        FOR EACH ROW
        WHEN NEW.benchmark_id IS NOT OLD.benchmark_id
        BEGIN
            SELECT RAISE(ABORT, 'logical source benchmark is immutable; create a new logical source id');
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_official_sources_projection_no_update
        BEFORE UPDATE OF
            source_name, source_url, source_type, officialness_level,
            machine_readable, requires_auth, supports_history, update_cadence,
            parser_name, parser_version, parser_config, status, notes,
            current_revision_id
        ON official_sources
        FOR EACH ROW
        WHEN (
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
            NEW.notes IS NOT OLD.notes OR
            NEW.current_revision_id IS NOT OLD.current_revision_id
        ) AND NOT EXISTS (
            SELECT 1
            FROM official_source_revisions revision
            WHERE revision.id = NEW.current_revision_id
              AND revision.official_source_id = NEW.id
              AND revision.supersedes_revision_id IS OLD.current_revision_id
              AND revision.revision_ordinal > COALESCE(
                  (
                      SELECT previous.revision_ordinal
                      FROM official_source_revisions previous
                      WHERE previous.id = OLD.current_revision_id
                  ),
                  0
              )
              AND revision.source_name IS NEW.source_name
              AND revision.source_url IS NEW.source_url
              AND revision.source_type IS NEW.source_type
              AND revision.officialness_level IS NEW.officialness_level
              AND revision.machine_readable IS NEW.machine_readable
              AND revision.requires_auth IS NEW.requires_auth
              AND revision.supports_history IS NEW.supports_history
              AND revision.update_cadence IS NEW.update_cadence
              AND revision.parser_name IS NEW.parser_name
              AND revision.parser_version IS NEW.parser_version
              AND revision.parser_config IS NEW.parser_config
              AND revision.status IS NEW.status
              AND revision.notes IS NEW.notes
              AND (
                  (
                      revision.status = 'retired'
                      AND EXISTS (
                          SELECT 1
                          FROM source_revision_decisions decision
                          WHERE decision.source_revision_id = revision.id
                            AND decision.outcome = 'revoked'
                      )
                  )
                  OR (
                      revision.status IS NOT 'retired'
                      AND EXISTS (
                          SELECT 1
                          FROM source_revision_decisions decision
                          WHERE decision.source_revision_id = revision.id
                            AND decision.outcome = 'quarantined'
                      )
                  )
              )
        )
        BEGIN
            SELECT RAISE(
                ABORT,
                'logical source definition is immutable unless it matches a new current source revision'
            );
        END
        """
    )


def downgrade() -> None:
    raise RuntimeError("Ledger migrations are recovery-only: restore the verified pre-migration backup instead of downgrading.")
