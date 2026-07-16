"""Add PostgreSQL-native integrity guards and cross-dialect path indexes.

SQLite guards introduced by 0003-0008 remain unchanged. PostgreSQL reaches
this revision without installing SQLite trigger syntax, then receives native
PL/pgSQL guards with the same fail-closed trust boundary. Source, review, and
publication decision roots/successors also receive unique indexes so concurrent
transactions cannot create ambiguous leaves after both pass a row trigger.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from migrations._dialect import is_postgresql, is_sqlite


revision = "0009_postgresql_guardrails"
down_revision = "0008_claim_publication_chain_guards"
branch_labels = None
depends_on = None


def _create_path_indexes() -> None:
    indexes: tuple[tuple[str, str, list[str]], ...] = (
        ("ix_benchmarks_superseded_by", "benchmarks", ["superseded_by_benchmark_id"]),
        ("ix_model_entities_base", "model_entities", ["base_model_entity_id"]),
        ("ix_source_snapshots_official_source", "source_snapshots", ["official_source_id"]),
        ("ix_result_claims_official_source", "result_claims", ["official_source_id"]),
        ("ix_result_claims_benchmark", "result_claims", ["benchmark_id"]),
        ("ix_result_claims_model_entity", "result_claims", ["model_entity_id"]),
        ("ix_result_claims_source_decision", "result_claims", ["source_revision_decision_id"]),
        (
            "ix_claim_validations_claim_type_outcome",
            "claim_validations",
            ["result_claim_id", "validation_type", "outcome"],
        ),
        ("ix_claim_relationships_related", "claim_relationships", ["related_claim_id"]),
        ("ix_ingestion_runs_source_started", "ingestion_runs", ["official_source_id", "started_at"]),
        (
            "ix_source_revisions_supersedes",
            "official_source_revisions",
            ["supersedes_revision_id"],
        ),
        (
            "ix_source_decisions_revision_decided",
            "source_revision_decisions",
            ["source_revision_id", "decided_at", "id"],
        ),
        ("ix_claim_reviews_model", "claim_review_decisions", ["model_entity_id"]),
        ("ix_claim_reviews_benchmark", "claim_review_decisions", ["benchmark_id"]),
        (
            "ix_claim_reviews_claim_decided",
            "claim_review_decisions",
            ["result_claim_id", "decided_at", "id"],
        ),
        (
            "ix_claim_publications_review",
            "claim_publication_decisions",
            ["claim_review_decision_id"],
        ),
        (
            "ix_claim_publications_claim_decided",
            "claim_publication_decisions",
            ["result_claim_id", "decided_at", "id"],
        ),
    )
    for name, table, columns in indexes:
        op.create_index(name, table, columns, unique=False)

    # Trigger checks alone are subject to write skew. These indexes are the
    # concurrency-safe denominator for exactly one root and one successor.
    for name, table, columns, predicate in (
        (
            "uq_source_decision_root",
            "source_revision_decisions",
            ["source_revision_id"],
            "supersedes_decision_id IS NULL",
        ),
        (
            "uq_source_decision_successor",
            "source_revision_decisions",
            ["supersedes_decision_id"],
            "supersedes_decision_id IS NOT NULL",
        ),
        (
            "uq_claim_review_root",
            "claim_review_decisions",
            ["result_claim_id"],
            "supersedes_decision_id IS NULL",
        ),
        (
            "uq_claim_review_successor",
            "claim_review_decisions",
            ["supersedes_decision_id"],
            "supersedes_decision_id IS NOT NULL",
        ),
        (
            "uq_claim_publication_root",
            "claim_publication_decisions",
            ["result_claim_id"],
            "supersedes_decision_id IS NULL",
        ),
        (
            "uq_claim_publication_successor",
            "claim_publication_decisions",
            ["supersedes_decision_id"],
            "supersedes_decision_id IS NOT NULL",
        ),
    ):
        where = sa.text(predicate)
        op.create_index(
            name,
            table,
            columns,
            unique=True,
            postgresql_where=where,
            sqlite_where=where,
        )


def _create_sqlite_source_decision_guards() -> None:
    for trigger_name, table_name in (
        ("trg_benchmarks_id_no_update", "benchmarks"),
        ("trg_model_entities_id_no_update", "model_entities"),
    ):
        op.execute(
            f"""
            CREATE TRIGGER {trigger_name}
            BEFORE UPDATE OF id ON {table_name}
            FOR EACH ROW
            WHEN NEW.id IS NOT OLD.id
            BEGIN
                SELECT RAISE(ABORT, '{table_name} identity is immutable');
            END
            """
        )
    op.execute(
        """
        CREATE TRIGGER trg_result_claims_identity_no_update
        BEFORE UPDATE OF id, created_at ON result_claims
        FOR EACH ROW
        WHEN NEW.id IS NOT OLD.id OR NEW.created_at IS NOT OLD.created_at
        BEGIN
            SELECT RAISE(ABORT, 'result_claim identity and creation time are immutable');
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_source_revision_decisions_parent_insert
        BEFORE INSERT ON source_revision_decisions
        FOR EACH ROW
        WHEN NEW.supersedes_decision_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1
              FROM source_revision_decisions parent
              WHERE parent.id = NEW.supersedes_decision_id
                AND parent.source_revision_id = NEW.source_revision_id
          )
        BEGIN
            SELECT RAISE(
                ABORT,
                'source revision decision must supersede a decision for the same source revision'
            );
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_source_revision_decisions_linear_insert
        BEFORE INSERT ON source_revision_decisions
        FOR EACH ROW
        WHEN (
            NEW.supersedes_decision_id IS NULL
            AND EXISTS (
                SELECT 1 FROM source_revision_decisions existing
                WHERE existing.source_revision_id = NEW.source_revision_id
            )
        ) OR (
            NEW.supersedes_decision_id IS NOT NULL
            AND EXISTS (
                SELECT 1 FROM source_revision_decisions successor
                WHERE successor.supersedes_decision_id = NEW.supersedes_decision_id
            )
        )
        BEGIN
            SELECT RAISE(
                ABORT,
                'source revision decisions must form one append-only linear chain'
            );
        END
        """
    )


def _convert_postgresql_native_types() -> None:
    """Resolve the legacy JSON/timestamp portability seams at the PG head."""
    for table, column in (
        ("benchmarks", "known_metrics"),
        ("benchmarks", "known_splits"),
        ("benchmarks", "known_settings"),
        ("model_entities", "modalities"),
        ("official_sources", "parser_config"),
        ("source_snapshots", "fetch_metadata"),
        ("result_claims", "evidence_location"),
        ("ingestion_runs", "metadata"),
        ("official_source_revisions", "definition_json"),
        ("official_source_revisions", "parser_config"),
        ("source_revision_decisions", "basis_json"),
        ("claim_review_decisions", "basis_json"),
        ("claim_publication_decisions", "basis_json"),
    ):
        op.execute(
            f"ALTER TABLE {table} ALTER COLUMN {column} "
            f"TYPE JSONB USING {column}::jsonb"
        )

    # Earlier SQLite-first revisions stored naive UTC wall-clock values.
    # PostgreSQL upgrades interpret those retained values explicitly as UTC;
    # fresh databases are empty when this conversion runs.
    for table, column in (
        ("benchmarks", "created_at"),
        ("benchmarks", "updated_at"),
        ("model_entities", "created_at"),
        ("model_entities", "updated_at"),
        ("aliases", "created_at"),
        ("official_sources", "created_at"),
        ("official_sources", "updated_at"),
        ("source_snapshots", "captured_at"),
        ("source_snapshots", "created_at"),
        ("result_claims", "created_at"),
        ("claim_validations", "validated_at"),
        ("claim_relationships", "created_at"),
        ("ingestion_runs", "started_at"),
        ("ingestion_runs", "finished_at"),
        ("official_source_revisions", "created_at"),
        ("source_revision_decisions", "decided_at"),
        ("claim_review_decisions", "decided_at"),
        ("claim_publication_decisions", "decided_at"),
    ):
        op.execute(
            f"ALTER TABLE {table} ALTER COLUMN {column} "
            f"TYPE TIMESTAMPTZ USING {column} AT TIME ZONE 'UTC'"
        )


def _create_postgresql_guardrails() -> None:
    # One reusable mutation rejection function is safe because it references
    # no database objects and runs with invoker privileges.
    op.execute(
        """
        CREATE FUNCTION ledger_reject_append_only_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, public
        AS $function$
        BEGIN
            RAISE EXCEPTION '% is append-only', TG_TABLE_NAME
                USING ERRCODE = '23000';
        END;
        $function$
        """
    )
    for table in (
        "official_source_revisions",
        "source_revision_decisions",
        "source_snapshots",
        "claim_validations",
        "claim_relationships",
        "claim_review_decisions",
        "claim_publication_decisions",
    ):
        op.execute(
            f"""
            CREATE TRIGGER trg_{table}_no_mutation
            BEFORE UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION ledger_reject_append_only_mutation()
            """
        )
    # PostgreSQL's referential-integrity key-share probes require UPDATE on at
    # least one referenced column for the invoker. Runtime roles receive only
    # UPDATE(id), so these guards make that compatibility grant non-mutating.
    for trigger_name, table_name in (
        ("trg_benchmarks_id_no_update", "benchmarks"),
        ("trg_model_entities_id_no_update", "model_entities"),
    ):
        op.execute(
            f"""
            CREATE TRIGGER {trigger_name}
            BEFORE UPDATE OF id ON {table_name}
            FOR EACH ROW EXECUTE FUNCTION ledger_reject_append_only_mutation()
            """
        )

    op.execute(
        """
        CREATE FUNCTION ledger_validate_source_revision_definition()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, public
        AS $function$
        DECLARE
            logical_benchmark_id text;
        BEGIN
            SELECT benchmark_id INTO logical_benchmark_id
            FROM official_sources
            WHERE id = NEW.official_source_id;

            IF jsonb_typeof(NEW.definition_json) IS DISTINCT FROM 'object'
               OR (NEW.definition_json ->> 'benchmark_id') IS DISTINCT FROM logical_benchmark_id
               OR (NEW.definition_json ->> 'source_name') IS DISTINCT FROM NEW.source_name
               OR (NEW.definition_json ->> 'source_url') IS DISTINCT FROM NEW.source_url
               OR (NEW.definition_json ->> 'source_type') IS DISTINCT FROM NEW.source_type
               OR (NEW.definition_json ->> 'officialness_level') IS DISTINCT FROM NEW.officialness_level
               OR (NEW.definition_json ->> 'machine_readable')::boolean IS DISTINCT FROM NEW.machine_readable
               OR (NEW.definition_json ->> 'requires_auth')::boolean IS DISTINCT FROM NEW.requires_auth
               OR (NEW.definition_json ->> 'supports_history')::boolean IS DISTINCT FROM NEW.supports_history
               OR (NEW.definition_json ->> 'update_cadence') IS DISTINCT FROM NEW.update_cadence
               OR (NEW.definition_json ->> 'parser_name') IS DISTINCT FROM NEW.parser_name
               OR (NEW.definition_json ->> 'parser_version') IS DISTINCT FROM NEW.parser_version
               OR (NEW.definition_json -> 'parser_config')::jsonb IS DISTINCT FROM NEW.parser_config::jsonb
               OR (NEW.definition_json ->> 'status') IS DISTINCT FROM NEW.status
               OR (NEW.definition_json ->> 'notes') IS DISTINCT FROM NEW.notes
            THEN
                RAISE EXCEPTION 'source revision definition must match its immutable projection fields'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $function$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_official_source_revisions_definition_insert
        BEFORE INSERT ON official_source_revisions
        FOR EACH ROW EXECUTE FUNCTION ledger_validate_source_revision_definition()
        """
    )

    op.execute(
        """
        CREATE FUNCTION ledger_validate_source_decision_chain()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, public
        AS $function$
        BEGIN
            IF NEW.supersedes_decision_id IS NULL THEN
                IF EXISTS (
                    SELECT 1 FROM source_revision_decisions existing
                    WHERE existing.source_revision_id = NEW.source_revision_id
                ) THEN
                    RAISE EXCEPTION 'source revision decisions must form one append-only linear chain'
                        USING ERRCODE = '23514';
                END IF;
            ELSIF NOT EXISTS (
                SELECT 1 FROM source_revision_decisions parent
                WHERE parent.id = NEW.supersedes_decision_id
                  AND parent.source_revision_id = NEW.source_revision_id
            ) THEN
                RAISE EXCEPTION 'source revision decision must supersede a decision for the same source revision'
                    USING ERRCODE = '23514';
            ELSIF EXISTS (
                SELECT 1 FROM source_revision_decisions successor
                WHERE successor.supersedes_decision_id = NEW.supersedes_decision_id
            ) THEN
                RAISE EXCEPTION 'source revision decisions must form one append-only linear chain'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $function$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_source_revision_decisions_chain_insert
        BEFORE INSERT ON source_revision_decisions
        FOR EACH ROW EXECUTE FUNCTION ledger_validate_source_decision_chain()
        """
    )

    op.execute(
        """
        CREATE FUNCTION ledger_validate_source_links()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, public
        AS $function$
        BEGIN
            IF TG_TABLE_NAME = 'official_sources' THEN
                IF NEW.current_revision_id IS NOT NULL
                   AND NOT EXISTS (
                       SELECT 1 FROM official_source_revisions revision
                       WHERE revision.id = NEW.current_revision_id
                         AND revision.official_source_id = NEW.id
                   )
                THEN
                    RAISE EXCEPTION 'current_revision_id must belong to its logical source'
                        USING ERRCODE = '23514';
                END IF;
            ELSIF NOT EXISTS (
                SELECT 1 FROM official_source_revisions revision
                WHERE revision.id = NEW.source_revision_id
                  AND revision.official_source_id = NEW.official_source_id
            ) THEN
                RAISE EXCEPTION 'snapshot source revision must belong to its logical source'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $function$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_official_sources_current_revision
        BEFORE INSERT OR UPDATE OF current_revision_id ON official_sources
        FOR EACH ROW EXECUTE FUNCTION ledger_validate_source_links()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_source_snapshots_revision
        BEFORE INSERT OR UPDATE OF official_source_id, source_revision_id ON source_snapshots
        FOR EACH ROW EXECUTE FUNCTION ledger_validate_source_links()
        """
    )

    op.execute(
        """
        CREATE FUNCTION ledger_validate_source_projection_update()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, public
        AS $function$
        BEGIN
            IF NEW.id IS DISTINCT FROM OLD.id THEN
                RAISE EXCEPTION 'logical source id is immutable' USING ERRCODE = '23514';
            END IF;
            IF NEW.benchmark_id IS DISTINCT FROM OLD.benchmark_id THEN
                RAISE EXCEPTION 'logical source benchmark is immutable; create a new logical source id'
                    USING ERRCODE = '23514';
            END IF;
            IF NEW.source_name IS DISTINCT FROM OLD.source_name
               OR NEW.source_url IS DISTINCT FROM OLD.source_url
               OR NEW.source_type IS DISTINCT FROM OLD.source_type
               OR NEW.officialness_level IS DISTINCT FROM OLD.officialness_level
               OR NEW.machine_readable IS DISTINCT FROM OLD.machine_readable
               OR NEW.requires_auth IS DISTINCT FROM OLD.requires_auth
               OR NEW.supports_history IS DISTINCT FROM OLD.supports_history
               OR NEW.update_cadence IS DISTINCT FROM OLD.update_cadence
               OR NEW.parser_name IS DISTINCT FROM OLD.parser_name
               OR NEW.parser_version IS DISTINCT FROM OLD.parser_version
               OR NEW.parser_config::jsonb IS DISTINCT FROM OLD.parser_config::jsonb
               OR NEW.status IS DISTINCT FROM OLD.status
               OR NEW.notes IS DISTINCT FROM OLD.notes
               OR NEW.current_revision_id IS DISTINCT FROM OLD.current_revision_id
            THEN
                IF NOT EXISTS (
                    SELECT 1
                    FROM official_source_revisions revision
                    WHERE revision.id = NEW.current_revision_id
                      AND revision.official_source_id = NEW.id
                      AND revision.supersedes_revision_id IS NOT DISTINCT FROM OLD.current_revision_id
                      AND revision.revision_ordinal > COALESCE(
                          (
                              SELECT previous.revision_ordinal
                              FROM official_source_revisions previous
                              WHERE previous.id = OLD.current_revision_id
                          ),
                          0
                      )
                      AND revision.source_name IS NOT DISTINCT FROM NEW.source_name
                      AND revision.source_url IS NOT DISTINCT FROM NEW.source_url
                      AND revision.source_type IS NOT DISTINCT FROM NEW.source_type
                      AND revision.officialness_level IS NOT DISTINCT FROM NEW.officialness_level
                      AND revision.machine_readable IS NOT DISTINCT FROM NEW.machine_readable
                      AND revision.requires_auth IS NOT DISTINCT FROM NEW.requires_auth
                      AND revision.supports_history IS NOT DISTINCT FROM NEW.supports_history
                      AND revision.update_cadence IS NOT DISTINCT FROM NEW.update_cadence
                      AND revision.parser_name IS NOT DISTINCT FROM NEW.parser_name
                      AND revision.parser_version IS NOT DISTINCT FROM NEW.parser_version
                      AND revision.parser_config::jsonb = NEW.parser_config::jsonb
                      AND revision.status IS NOT DISTINCT FROM NEW.status
                      AND revision.notes IS NOT DISTINCT FROM NEW.notes
                      AND (
                          (
                              revision.status = 'retired'
                              AND EXISTS (
                                  SELECT 1 FROM source_revision_decisions decision
                                  WHERE decision.source_revision_id = revision.id
                                    AND decision.outcome = 'revoked'
                                    AND NOT EXISTS (
                                        SELECT 1 FROM source_revision_decisions successor
                                        WHERE successor.supersedes_decision_id = decision.id
                                    )
                              )
                          )
                          OR (
                              revision.status <> 'retired'
                              AND EXISTS (
                                  SELECT 1 FROM source_revision_decisions decision
                                  WHERE decision.source_revision_id = revision.id
                                    AND decision.outcome = 'quarantined'
                                    AND NOT EXISTS (
                                        SELECT 1 FROM source_revision_decisions successor
                                        WHERE successor.supersedes_decision_id = decision.id
                                    )
                              )
                          )
                      )
                ) THEN
                    RAISE EXCEPTION 'logical source definition is immutable unless it matches a new current source revision'
                        USING ERRCODE = '23514';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $function$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_official_sources_projection_no_update
        BEFORE UPDATE ON official_sources
        FOR EACH ROW EXECUTE FUNCTION ledger_validate_source_projection_update()
        """
    )

    op.execute(
        """
        CREATE FUNCTION ledger_validate_result_claim_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, public
        AS $function$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'result_claims are append-only' USING ERRCODE = '23000';
            END IF;
            IF NEW.id IS DISTINCT FROM OLD.id
               OR NEW.created_at IS DISTINCT FROM OLD.created_at
               OR NEW.source_snapshot_id IS DISTINCT FROM OLD.source_snapshot_id
               OR NEW.source_revision_decision_id IS DISTINCT FROM OLD.source_revision_decision_id
               OR NEW.official_source_id IS DISTINCT FROM OLD.official_source_id
               OR NEW.model_raw IS DISTINCT FROM OLD.model_raw
               OR NEW.benchmark_raw IS DISTINCT FROM OLD.benchmark_raw
               OR NEW.score_raw IS DISTINCT FROM OLD.score_raw
               OR NEW.metric_raw IS DISTINCT FROM OLD.metric_raw
               OR NEW.split_raw IS DISTINCT FROM OLD.split_raw
               OR NEW.setting_raw IS DISTINCT FROM OLD.setting_raw
               OR NEW.evaluation_version_raw IS DISTINCT FROM OLD.evaluation_version_raw
               OR NEW.rank_raw IS DISTINCT FROM OLD.rank_raw
               OR NEW.date_raw IS DISTINCT FROM OLD.date_raw
               OR NEW.score_numeric IS DISTINCT FROM OLD.score_numeric
               OR NEW.score_unit IS DISTINCT FROM OLD.score_unit
               OR NEW.evidence_text IS DISTINCT FROM OLD.evidence_text
               OR NEW.evidence_location::jsonb IS DISTINCT FROM OLD.evidence_location::jsonb
               OR NEW.capture_method IS DISTINCT FROM OLD.capture_method
               OR NEW.capture_confidence IS DISTINCT FROM OLD.capture_confidence
               OR NEW.officialness_level IS DISTINCT FROM OLD.officialness_level
               OR NEW.claim_fingerprint IS DISTINCT FROM OLD.claim_fingerprint
            THEN
                RAISE EXCEPTION 'result_claim raw evidence is immutable' USING ERRCODE = '23514';
            END IF;
            IF NEW.benchmark_id IS DISTINCT FROM OLD.benchmark_id
               OR NEW.model_entity_id IS DISTINCT FROM OLD.model_entity_id
               OR NEW.capture_status IS DISTINCT FROM OLD.capture_status
               OR NEW.scientific_status IS DISTINCT FROM OLD.scientific_status
            THEN
                RAISE EXCEPTION 'result_claim review projection is immutable; append a claim review decision'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $function$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_result_claims_no_mutation
        BEFORE UPDATE OR DELETE ON result_claims
        FOR EACH ROW EXECUTE FUNCTION ledger_validate_result_claim_mutation()
        """
    )
    op.execute(
        """
        CREATE FUNCTION ledger_validate_result_claim_admission()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, public
        AS $function$
        BEGIN
            IF NEW.source_revision_decision_id IS NULL
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
                         SELECT 1 FROM source_revision_decisions successor
                         WHERE successor.supersedes_decision_id = decision.id
                     )
                     AND 1 = (
                         SELECT COUNT(*)
                         FROM source_revision_decisions leaf
                         WHERE leaf.source_revision_id = snapshot.source_revision_id
                           AND NOT EXISTS (
                               SELECT 1 FROM source_revision_decisions successor
                               WHERE successor.supersedes_decision_id = leaf.id
                           )
                     )
               )
            THEN
                RAISE EXCEPTION 'new result claims require a current effective certified source decision for the snapshot revision'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $function$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_result_claims_admission_decision_insert
        BEFORE INSERT ON result_claims
        FOR EACH ROW EXECUTE FUNCTION ledger_validate_result_claim_admission()
        """
    )

    op.execute(
        """
        CREATE FUNCTION ledger_validate_claim_review_chain()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, public
        AS $function$
        BEGIN
            IF NEW.supersedes_decision_id IS NULL THEN
                IF EXISTS (
                    SELECT 1 FROM claim_review_decisions existing
                    WHERE existing.result_claim_id = NEW.result_claim_id
                ) THEN
                    RAISE EXCEPTION 'claim review decisions must form one append-only linear chain'
                        USING ERRCODE = '23514';
                END IF;
            ELSIF NOT EXISTS (
                SELECT 1 FROM claim_review_decisions parent
                WHERE parent.id = NEW.supersedes_decision_id
                  AND parent.result_claim_id = NEW.result_claim_id
            ) THEN
                RAISE EXCEPTION 'claim review decision must supersede a decision for the same claim'
                    USING ERRCODE = '23514';
            ELSIF EXISTS (
                SELECT 1 FROM claim_review_decisions successor
                WHERE successor.supersedes_decision_id = NEW.supersedes_decision_id
            ) THEN
                RAISE EXCEPTION 'claim review decisions must form one append-only linear chain'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $function$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_claim_review_decisions_chain_insert
        BEFORE INSERT ON claim_review_decisions
        FOR EACH ROW EXECUTE FUNCTION ledger_validate_claim_review_chain()
        """
    )

    op.execute(
        """
        CREATE FUNCTION ledger_validate_claim_publication_chain()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, public
        AS $function$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM claim_review_decisions review
                WHERE review.id = NEW.claim_review_decision_id
                  AND review.result_claim_id = NEW.result_claim_id
                  AND NOT EXISTS (
                      SELECT 1 FROM claim_review_decisions successor
                      WHERE successor.supersedes_decision_id = review.id
                  )
            ) THEN
                RAISE EXCEPTION 'claim publication decision must reference the current effective claim review decision'
                    USING ERRCODE = '23514';
            END IF;
            IF NEW.supersedes_decision_id IS NULL THEN
                IF EXISTS (
                    SELECT 1 FROM claim_publication_decisions existing
                    WHERE existing.result_claim_id = NEW.result_claim_id
                ) THEN
                    RAISE EXCEPTION 'claim publication decisions must form one append-only linear chain'
                        USING ERRCODE = '23514';
                END IF;
            ELSIF NOT EXISTS (
                SELECT 1 FROM claim_publication_decisions parent
                WHERE parent.id = NEW.supersedes_decision_id
                  AND parent.result_claim_id = NEW.result_claim_id
            ) THEN
                RAISE EXCEPTION 'claim publication decision must supersede a decision for the same claim'
                    USING ERRCODE = '23514';
            ELSIF EXISTS (
                SELECT 1 FROM claim_publication_decisions successor
                WHERE successor.supersedes_decision_id = NEW.supersedes_decision_id
            ) THEN
                RAISE EXCEPTION 'claim publication decisions must form one append-only linear chain'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $function$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_claim_publication_decisions_chain_insert
        BEFORE INSERT ON claim_publication_decisions
        FOR EACH ROW EXECUTE FUNCTION ledger_validate_claim_publication_chain()
        """
    )

    op.execute(
        """
        CREATE FUNCTION ledger_reject_ingestion_run_delete()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, public
        AS $function$
        BEGIN
            RAISE EXCEPTION 'ingestion_runs are retained evidence' USING ERRCODE = '23000';
        END;
        $function$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_ingestion_runs_no_delete
        BEFORE DELETE ON ingestion_runs
        FOR EACH ROW EXECUTE FUNCTION ledger_reject_ingestion_run_delete()
        """
    )
    for function_name in (
        "ledger_reject_append_only_mutation",
        "ledger_reject_ingestion_run_delete",
        "ledger_validate_claim_publication_chain",
        "ledger_validate_claim_review_chain",
        "ledger_validate_result_claim_admission",
        "ledger_validate_result_claim_mutation",
        "ledger_validate_source_decision_chain",
        "ledger_validate_source_links",
        "ledger_validate_source_projection_update",
        "ledger_validate_source_revision_definition",
    ):
        op.execute(f"REVOKE ALL ON FUNCTION {function_name}() FROM PUBLIC")


def upgrade() -> None:
    _create_path_indexes()
    if is_sqlite():
        _create_sqlite_source_decision_guards()
        return
    if not is_postgresql():
        raise RuntimeError("Ledger migrations support only SQLite and PostgreSQL.")

    op.create_foreign_key(
        "fk_result_claims_source_revision_decision",
        "result_claims",
        "source_revision_decisions",
        ["source_revision_decision_id"],
        ["id"],
    )
    _convert_postgresql_native_types()
    _create_postgresql_guardrails()


def downgrade() -> None:
    raise RuntimeError(
        "Ledger migrations are recovery-only: restore the verified pre-migration backup instead of downgrading."
    )
