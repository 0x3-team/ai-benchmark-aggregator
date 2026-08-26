from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from io import StringIO
import json
import os
from pathlib import Path
from threading import Barrier

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from app.db import models, repositories
from app.db.migrate import (
    DatabaseMigrationError,
    head_revision,
    initialize_database,
    inspect_database,
    redacted_database_url,
    upgrade_postgresql_database,
)
from app.db.postgresql import POSTGRESQL_MIGRATION_LOCK_KEY, render_least_privilege_role_sql
from postgresql_test_support import skip_or_fail


_ROOT = Path(__file__).resolve().parents[1]
_TARGET_ENV = "TEST_POSTGRESQL_URL"
_RESET_ENV = "TEST_POSTGRESQL_ALLOW_RESET"
_TEST_ROLES = {
    "migrator": "test_ledger_migrator",
    "ingestion": "test_ledger_ingestion",
    "governance": "test_ledger_governance",
    "artifact": "test_ledger_artifact",
    "audit": "test_ledger_audit",
}


def _config(database_url: str, *, output_buffer: StringIO | None = None) -> Config:
    config = Config(str(_ROOT / "alembic.ini"), output_buffer=output_buffer)
    config.set_main_option("script_location", str(_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    config.attributes["database_url"] = database_url
    return config


def _target_url() -> str:
    database_url = os.environ.get(_TARGET_ENV)
    if not database_url:
        skip_or_fail(
            f"real PostgreSQL proof not emitted: {_TARGET_ENV} is unset; "
            "offline DDL and SQLite are not PostgreSQL substitutes"
        )
    if os.environ.get(_RESET_ENV) != "1":
        pytest.fail(
            f"{_RESET_ENV}=1 is required because this harness drops and recreates only the target public schema"
        )
    url = make_url(database_url)
    if url.get_backend_name() != "postgresql":
        pytest.fail(f"{_TARGET_ENV} must be an explicit PostgreSQL URL")
    database_name = (url.database or "").lower()
    if not any(
        marker in database_name
        for marker in ("test", "disposable", "phase2a", "phase2b")
    ):
        pytest.fail("refusing destructive target harness: database name lacks a disposable/test marker")
    return database_url


def _engine(database_url: str):
    return create_engine(database_url, future=True, poolclass=NullPool)


def _reset_public_schema(database_url: str) -> None:
    engine = _engine(database_url)
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        connection.exec_driver_sql("DROP SCHEMA IF EXISTS public CASCADE")
        connection.exec_driver_sql("CREATE SCHEMA public")
    engine.dispose()


def _drop_test_roles(database_url: str) -> None:
    engine = _engine(database_url)
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        for role in reversed(tuple(_TEST_ROLES.values())):
            exists = connection.execute(
                text("SELECT 1 FROM pg_roles WHERE rolname = :role"), {"role": role}
            ).scalar_one_or_none()
            if exists:
                connection.exec_driver_sql(f"DROP OWNED BY {role}")
                connection.exec_driver_sql(f"DROP ROLE {role}")
    engine.dispose()


def _assert_rejected(engine, sql: str, *, match: str, params: dict[str, object] | None = None) -> None:
    with engine.connect() as connection:
        with pytest.raises(DBAPIError) as caught:
            connection.execute(text(sql), params or {})
            connection.commit()
        connection.rollback()
    assert match in str(caught.value)


def _seed_admissible_claim(engine) -> dict[str, str]:
    definition = {
        "benchmark_id": "b1",
        "source_name": "Official source",
        "source_url": "https://official.example/results.json",
        "source_type": "api",
        "officialness_level": "O5",
        "machine_readable": True,
        "requires_auth": False,
        "supports_history": True,
        "update_cadence": None,
        "parser_name": "fixture",
        "parser_version": "1",
        "parser_config": {},
        "status": "active",
        "notes": None,
    }
    encoded = json.dumps(definition, sort_keys=True, separators=(",", ":"))
    with engine.begin() as connection:
        connection.execute(
            text("INSERT INTO benchmarks (id, canonical_name, display_name) VALUES ('b1', 'bench', 'Bench')")
        )
        connection.execute(
            text(
                "INSERT INTO model_entities (id, canonical_name, display_name, entity_type) "
                "VALUES ('m1', 'model', 'Model', 'model')"
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO official_sources (
                    id, benchmark_id, source_name, source_url, source_type,
                    officialness_level, machine_readable, requires_auth,
                    supports_history, parser_name, parser_version, parser_config, status
                ) VALUES (
                    's1', 'b1', 'Official source', 'https://official.example/results.json',
                    'api', 'O5', true, false, true, 'fixture', '1', '{}', 'active'
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO official_source_revisions (
                    id, official_source_id, revision_ordinal, definition_hash,
                    definition_json, source_name, source_url, source_type,
                    officialness_level, machine_readable, requires_auth,
                    supports_history, parser_name, parser_version, parser_config,
                    status, origin
                ) VALUES (
                    'revision-1', 's1', 1, :definition_hash, CAST(:definition AS jsonb),
                    'Official source', 'https://official.example/results.json', 'api',
                    'O5', true, false, true, 'fixture', '1', '{}', 'active', 'test'
                )
                """
            ),
            {"definition_hash": "a" * 64, "definition": encoded},
        )
        connection.execute(
            text(
                """
                INSERT INTO source_revision_decisions (
                    id, source_revision_id, outcome, policy_version, reason_code, basis_json
                ) VALUES ('decision-quarantine', 'revision-1', 'quarantined', 'test-v1', 'initial', '{}')
                """
            )
        )
        connection.execute(
            text("UPDATE official_sources SET current_revision_id = 'revision-1' WHERE id = 's1'")
        )
        connection.execute(
            text(
                """
                INSERT INTO source_revision_decisions (
                    id, source_revision_id, outcome, policy_version, reason_code,
                    basis_json, supersedes_decision_id
                ) VALUES (
                    'decision-certified', 'revision-1', 'certified', 'test-v1',
                    'reviewed', '{}', 'decision-quarantine'
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO source_snapshots (
                    id, official_source_id, source_revision_id, raw_content_uri,
                    content_hash, fetch_metadata
                ) VALUES (
                    'snapshot-1', 's1', 'revision-1', 'r2://snapshots/fixture',
                    :content_hash, '{}'
                )
                """
            ),
            {"content_hash": "b" * 64},
        )
        connection.execute(
            text(
                """
                INSERT INTO result_claims (
                    id, source_snapshot_id, source_revision_decision_id,
                    official_source_id, benchmark_id, model_entity_id,
                    model_raw, benchmark_raw, score_raw, metric_raw,
                    evidence_location, capture_method, capture_status,
                    claim_fingerprint
                ) VALUES (
                    'claim-1', 'snapshot-1', 'decision-certified', 's1', 'b1', 'm1',
                    'Model Raw', 'Bench Raw', '77.0', 'accuracy',
                    CAST(:evidence AS jsonb), 'fixture', 'parser_verified', :fingerprint
                )
                """
            ),
            {"evidence": '{"row":1}', "fingerprint": "c" * 64},
        )
    return {
        "source_revision_id": "revision-1",
        "certified_decision_id": "decision-certified",
        "claim_id": "claim-1",
    }


def test_offline_postgresql_ddl_compiles_without_claiming_real_target_proof():
    output = StringIO()
    url = (
        "postgresql://ledger:REDACTED@127.0.0.1:5432/disposable"
        "?application_name=ledger%2Fmigration"
    )
    command.upgrade(_config(url, output_buffer=output), "head", sql=True)
    ddl = output.getvalue()
    assert "0009_postgresql_guardrails" in ddl
    assert "0010_operational_persistence" in ddl
    assert "0011_ingestion_run_hardening" in ddl
    assert "ledger_validate_result_claim_admission" in ddl
    assert "ledger_validate_ingestion_run_finalization" in ddl
    assert "trg_ingestion_runs_finalize_once" in ddl
    assert "ledger_validate_operational_completion" in ddl
    assert "ledger_validate_job_lease_projection" in ddl
    assert "trg_scheduled_cycles_terminal_insert" in ddl
    assert "trg_outbox_batches_completion_insert" in ddl
    assert "DEFERRABLE INITIALLY DEFERRED" in ddl
    assert "TYPE JSONB" in ddl
    assert "TYPE TIMESTAMPTZ" in ddl
    # 0012 is intentionally a PostgreSQL no-op: its revision must advance the
    # offline version chain, but its SQLite-only guard (RAISE(ABORT, ...)) must
    # not leak any real SQL into the offline PostgreSQL DDL.
    assert "0012_sqlite_ingestion_run_hardening" in ddl
    assert "RAISE(ABORT" not in ddl


def test_offline_migration_rejects_unsupported_dialect_before_emitting_ddl():
    with pytest.raises(RuntimeError, match="only SQLite and PostgreSQL"):
        command.upgrade(
            _config("mysql://ledger:REDACTED@127.0.0.1/disposable"),
            "head",
            sql=True,
        )


def test_postgresql_url_redaction_and_role_contract_are_secret_free_and_split():
    rendered = redacted_database_url(
        "postgresql+psycopg://runner:top-secret@db.example/ledger?sslkey=private.pem&token=abc"
    )
    assert "top-secret" not in rendered
    assert "private.pem" not in rendered
    assert "token" not in rendered

    sql = render_least_privilege_role_sql()
    assert "benchmark_ledger_ingestion" in sql
    assert "benchmark_ledger_governance" in sql
    assert "benchmark_ledger_artifact" in sql
    assert "benchmark_ledger_audit" in sql
    assert "GRANT INSERT ON public.result_claims" not in sql  # multi-table grant, checked below
    ingestion_grant = next(line for line in sql.splitlines() if line.startswith("GRANT INSERT ON"))
    assert "public.result_claims" in ingestion_grant
    assert "claim_review_decisions" not in ingestion_grant
    governance_grant = [line for line in sql.splitlines() if line.startswith("GRANT INSERT ON")][1]
    assert "benchmark_definition_revisions" in governance_grant
    assert "evaluation_subject_revisions" in governance_grant
    assert "identity_decisions" in governance_grant
    assert "review_work_item_events" in governance_grant
    assert "claim_review_decisions" not in governance_grant
    assert "claim_publication_decisions" not in governance_grant
    assert "source_revision_decisions" not in governance_grant
    assert "result_claims" not in governance_grant
    assert (
        "GRANT UPDATE ON public.scheduled_job_leases TO benchmark_ledger_ingestion;"
        in sql
    )
    assert (
        "GRANT UPDATE ON public.ingestion_runs TO benchmark_ledger_ingestion;"
        not in sql
    )
    assert (
        "GRANT UPDATE (finished_at, status, sources_checked, snapshots_created, "
        "snapshots_reused, claims_extracted, claims_inserted, claims_unchanged, "
        "claims_needing_review, error_message, metadata) ON public.ingestion_runs "
        "TO benchmark_ledger_ingestion;"
    ) in sql
    artifact_grant = next(
        line
        for line in sql.splitlines()
        if line.startswith("GRANT SELECT ON")
        and line.endswith("TO benchmark_ledger_artifact;")
    )
    assert "scheduled_job_leases" not in artifact_grant
    assert "ops_incidents" not in artifact_grant
    with pytest.raises(ValueError, match="lowercase PostgreSQL identifier"):
        render_least_privilege_role_sql(schema='public; DROP SCHEMA public')
    with pytest.raises(ValueError, match="must be distinct"):
        render_least_privilege_role_sql(
            migrator_role="duplicate_role",
            ingestion_role="duplicate_role",
        )


def test_real_postgresql_strict_status_rejects_executable_schema_drift():
    database_url = _target_url()
    drift_owner_role = "test_ledger_guard_owner"
    _reset_public_schema(database_url)
    engine = _engine(database_url)
    try:
        assert initialize_database(database_url).kind == "current"

        with engine.begin() as connection:
            connection.exec_driver_sql(
                "ALTER TABLE result_claims DISABLE TRIGGER trg_result_claims_no_mutation"
            )
        disabled = inspect_database(database_url)
        assert disabled.kind == "invalid"
        assert "disabled" in (disabled.detail or "")
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "ALTER TABLE result_claims ENABLE TRIGGER trg_result_claims_no_mutation"
            )
        assert inspect_database(database_url).kind == "current"

        with engine.begin() as connection:
            connection.exec_driver_sql(
                "ALTER TABLE result_claims ALTER COLUMN score_raw DROP NOT NULL"
            )
        nullable_raw = inspect_database(database_url)
        assert nullable_raw.kind == "invalid"
        assert "nullability" in (nullable_raw.detail or "")
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "ALTER TABLE result_claims ALTER COLUMN score_raw SET NOT NULL"
            )
        assert inspect_database(database_url).kind == "current"

        with engine.begin() as connection:
            connection.exec_driver_sql(
                "ALTER TABLE result_claims ALTER COLUMN created_at "
                "SET DEFAULT TIMESTAMPTZ '2000-01-01 00:00:00+00'"
            )
        fixed_audit_time = inspect_database(database_url)
        assert fixed_audit_time.kind == "invalid"
        assert "default" in (fixed_audit_time.detail or "")
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "ALTER TABLE result_claims ALTER COLUMN created_at SET DEFAULT CURRENT_TIMESTAMP"
            )
        assert inspect_database(database_url).kind == "current"

        with engine.begin() as connection:
            connection.exec_driver_sql("ALTER TABLE claim_validations SET UNLOGGED")
        unlogged_evidence = inspect_database(database_url)
        assert unlogged_evidence.kind == "invalid"
        assert "persistence" in (unlogged_evidence.detail or "")
        with engine.begin() as connection:
            connection.exec_driver_sql("ALTER TABLE claim_validations SET LOGGED")
        assert inspect_database(database_url).kind == "current"

        with engine.begin() as connection:
            connection.exec_driver_sql("ALTER TABLE result_claims ENABLE ROW LEVEL SECURITY")
            connection.exec_driver_sql("ALTER TABLE result_claims FORCE ROW LEVEL SECURITY")
        hidden_evidence = inspect_database(database_url)
        assert hidden_evidence.kind == "invalid"
        assert "RLS" in (hidden_evidence.detail or "")
        with engine.begin() as connection:
            connection.exec_driver_sql("ALTER TABLE result_claims NO FORCE ROW LEVEL SECURITY")
            connection.exec_driver_sql("ALTER TABLE result_claims DISABLE ROW LEVEL SECURITY")
        assert inspect_database(database_url).kind == "current"

        with engine.begin() as connection:
            connection.exec_driver_sql("CREATE SCHEMA adv_inheritance")
            connection.exec_driver_sql(
                "CREATE TABLE adv_inheritance.injected_claims () INHERITS (public.result_claims)"
            )
            connection.exec_driver_sql(
                """
                INSERT INTO adv_inheritance.injected_claims (
                    id, source_snapshot_id, official_source_id, model_raw,
                    benchmark_raw, score_raw, evidence_location,
                    capture_method, claim_fingerprint
                ) VALUES (
                    'inherited-injection', 'missing-snapshot', 'missing-source',
                    'Injected Raw', 'Injected Bench', '999', '{}',
                    'bypass',
                    '9999999999999999999999999999999999999999999999999999999999999999'
                )
                """
            )
            assert connection.exec_driver_sql(
                "SELECT COUNT(*) FROM public.result_claims "
                "WHERE id = 'inherited-injection'"
            ).scalar_one() == 1
            assert connection.exec_driver_sql(
                "SELECT COUNT(*) FROM ONLY public.result_claims "
                "WHERE id = 'inherited-injection'"
            ).scalar_one() == 0
        inherited_bypass = inspect_database(database_url)
        assert inherited_bypass.kind == "invalid"
        assert "inheritance" in (inherited_bypass.detail or "")
        with engine.begin() as connection:
            connection.exec_driver_sql("DROP SCHEMA adv_inheritance CASCADE")
        assert inspect_database(database_url).kind == "current"

        with engine.begin() as connection:
            connection.exec_driver_sql("DROP INDEX uq_claim_review_root")
            connection.exec_driver_sql(
                """
                CREATE UNIQUE INDEX uq_claim_review_root
                ON claim_review_decisions (result_claim_id, ((id || '')))
                WHERE supersedes_decision_id IS NULL
                """
            )
        weakened_root_guard = inspect_database(database_url)
        assert weakened_root_guard.kind == "invalid"
        assert "indexes" in (weakened_root_guard.detail or "")
        with engine.begin() as connection:
            connection.exec_driver_sql("DROP INDEX uq_claim_review_root")
            connection.exec_driver_sql(
                """
                CREATE UNIQUE INDEX uq_claim_review_root
                ON claim_review_decisions (result_claim_id)
                WHERE supersedes_decision_id IS NULL
                """
            )
        assert inspect_database(database_url).kind == "current"

        for state_column in ("indisvalid", "indisready", "indislive"):
            with engine.begin() as connection:
                connection.exec_driver_sql(
                    f"""
                    UPDATE pg_index SET {state_column} = false
                    WHERE indexrelid = 'uq_source_decision_successor'::regclass
                    """
                )
            unusable_index = inspect_database(database_url)
            assert unusable_index.kind == "invalid"
            assert "indexes" in (unusable_index.detail or "")
            with engine.begin() as connection:
                connection.exec_driver_sql(
                    f"""
                    UPDATE pg_index SET {state_column} = true
                    WHERE indexrelid = 'uq_source_decision_successor'::regclass
                    """
                )
            assert inspect_database(database_url).kind == "current"

        with engine.begin() as connection:
            connection.exec_driver_sql(
                "ALTER TABLE claim_review_decisions "
                "DROP CONSTRAINT claim_review_decisions_result_claim_id_fkey"
            )
            connection.exec_driver_sql(
                """
                ALTER TABLE claim_publication_decisions
                ADD CONSTRAINT claim_review_decisions_result_claim_id_fkey
                FOREIGN KEY (result_claim_id) REFERENCES result_claims(id)
                """
            )
        relocated_constraint = inspect_database(database_url)
        assert relocated_constraint.kind == "invalid"
        assert "constraints" in (relocated_constraint.detail or "")
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "ALTER TABLE claim_publication_decisions "
                "DROP CONSTRAINT claim_review_decisions_result_claim_id_fkey"
            )
            connection.exec_driver_sql(
                """
                ALTER TABLE claim_review_decisions
                ADD CONSTRAINT claim_review_decisions_result_claim_id_fkey
                FOREIGN KEY (result_claim_id) REFERENCES result_claims(id)
                """
            )
        assert inspect_database(database_url).kind == "current"

        with engine.begin() as connection:
            connection.exec_driver_sql(
                """
                CREATE FUNCTION zz_adv_after_admission()
                RETURNS trigger LANGUAGE plpgsql
                SET search_path = pg_catalog, public
                AS $function$ BEGIN NEW.source_revision_decision_id := NULL; RETURN NEW; END; $function$
                """
            )
            connection.exec_driver_sql(
                """
                CREATE TRIGGER zz_adv_after_admission
                BEFORE INSERT ON result_claims
                FOR EACH ROW EXECUTE FUNCTION zz_adv_after_admission()
                """
            )
        extra_trigger = inspect_database(database_url)
        assert extra_trigger.kind == "invalid"
        assert "triggers" in (extra_trigger.detail or "")
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "DROP TRIGGER zz_adv_after_admission ON result_claims"
            )
            connection.exec_driver_sql("DROP FUNCTION zz_adv_after_admission()")
        assert inspect_database(database_url).kind == "current"

        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            connection.exec_driver_sql(f"DROP ROLE IF EXISTS {drift_owner_role}")
            connection.exec_driver_sql(f"CREATE ROLE {drift_owner_role} NOLOGIN")
            connection.exec_driver_sql(
                "ALTER FUNCTION ledger_validate_result_claim_mutation() "
                f"OWNER TO {drift_owner_role}"
            )
        owner_drift = inspect_database(database_url)
        assert owner_drift.kind == "invalid"
        assert "function" in (owner_drift.detail or "")
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            connection.exec_driver_sql(
                "ALTER FUNCTION ledger_validate_result_claim_mutation() OWNER TO CURRENT_USER"
            )
            connection.exec_driver_sql(f"DROP ROLE {drift_owner_role}")
        assert inspect_database(database_url).kind == "current"

        with engine.begin() as connection:
            connection.exec_driver_sql(
                """
                CREATE OR REPLACE FUNCTION ledger_validate_result_claim_mutation()
                RETURNS trigger LANGUAGE plpgsql
                SET search_path = pg_catalog, public
                AS $function$ BEGIN RETURN NEW; END; $function$
                """
            )
        replaced_body = inspect_database(database_url)
        assert replaced_body.kind == "invalid"
        assert "function body" in (replaced_body.detail or "")
    finally:
        with engine.begin() as connection:
            connection.exec_driver_sql("DROP SCHEMA IF EXISTS adv_inheritance CASCADE")
        engine.dispose()
        _reset_public_schema(database_url)
        cleanup_engine = _engine(database_url)
        with cleanup_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            if connection.execute(
                text("SELECT 1 FROM pg_roles WHERE rolname = :role"),
                {"role": drift_owner_role},
            ).scalar_one_or_none():
                connection.exec_driver_sql(f"DROP OWNED BY {drift_owner_role}")
                connection.exec_driver_sql(f"DROP ROLE {drift_owner_role}")
        cleanup_engine.dispose()


def test_real_postgresql_fresh_head_and_direct_integrity_bypasses():
    database_url = _target_url()
    _reset_public_schema(database_url)
    try:
        status = initialize_database(database_url)
        assert status.kind == "current"
        assert status.revision == head_revision()
        assert status.integrity_ok
        engine = _engine(database_url)
        with engine.connect() as lock_holder:
            lock_holder.execute(
                text("SELECT pg_advisory_lock(:lock_key)"),
                {"lock_key": POSTGRESQL_MIGRATION_LOCK_KEY},
            )
            lock_holder.commit()
            try:
                with pytest.raises(DatabaseMigrationError, match="holds the advisory lock"):
                    initialize_database(database_url)
            finally:
                lock_holder.execute(
                    text("SELECT pg_advisory_unlock(:lock_key)"),
                    {"lock_key": POSTGRESQL_MIGRATION_LOCK_KEY},
                )
                lock_holder.commit()
        ids = _seed_admissible_claim(engine)

        _assert_rejected(
            engine,
            "UPDATE result_claims SET score_raw = '999' WHERE id = 'claim-1'",
            match="raw evidence is immutable",
        )
        _assert_rejected(
            engine,
            "UPDATE result_claims SET id = 'claim-rewritten' WHERE id = 'claim-1'",
            match="raw evidence is immutable",
        )
        _assert_rejected(
            engine,
            "UPDATE result_claims SET created_at = now() + interval '1 day' WHERE id = 'claim-1'",
            match="raw evidence is immutable",
        )
        _assert_rejected(
            engine,
            "DELETE FROM source_snapshots WHERE id = 'snapshot-1'",
            match="append-only",
        )
        _assert_rejected(
            engine,
            "UPDATE official_sources SET source_url = 'https://attacker.example' WHERE id = 's1'",
            match="logical source definition is immutable",
        )
        _assert_rejected(
            engine,
            """
            INSERT INTO source_revision_decisions (
                id, source_revision_id, outcome, policy_version, reason_code, basis_json
            ) VALUES ('decision-second-root', 'revision-1', 'certified', 'test-v1', 'branch', '{}')
            """,
            match="linear chain",
        )

        other_definition = {
            "benchmark_id": "b1",
            "source_name": "Other official source",
            "source_url": "https://official.example/other.json",
            "source_type": "api",
            "officialness_level": "O5",
            "machine_readable": True,
            "requires_auth": False,
            "supports_history": True,
            "update_cadence": None,
            "parser_name": "fixture",
            "parser_version": "1",
            "parser_config": {},
            "status": "active",
            "notes": None,
        }
        with engine.begin() as connection:
            connection.exec_driver_sql(
                """
                INSERT INTO official_sources (
                    id, benchmark_id, source_name, source_url, source_type,
                    officialness_level, machine_readable, requires_auth,
                    supports_history, parser_name, parser_version, parser_config, status
                ) VALUES (
                    's2', 'b1', 'Other official source',
                    'https://official.example/other.json', 'api', 'O5', true,
                    false, true, 'fixture', '1', '{}', 'active'
                )
                """
            )
            connection.execute(
                text(
                    """
                    INSERT INTO official_source_revisions (
                        id, official_source_id, revision_ordinal, definition_hash,
                        definition_json, source_name, source_url, source_type,
                        officialness_level, machine_readable, requires_auth,
                        supports_history, parser_name, parser_version, parser_config,
                        status, origin
                    ) VALUES (
                        'revision-2', 's2', 1, :definition_hash,
                        CAST(:definition AS jsonb), 'Other official source',
                        'https://official.example/other.json', 'api', 'O5', true,
                        false, true, 'fixture', '1', '{}', 'active', 'test'
                    )
                    """
                ),
                {
                    "definition_hash": "d" * 64,
                    "definition": json.dumps(
                        other_definition, sort_keys=True, separators=(",", ":")
                    ),
                },
            )
            connection.exec_driver_sql(
                """
                INSERT INTO source_revision_decisions (
                    id, source_revision_id, outcome, policy_version, reason_code, basis_json
                ) VALUES (
                    'decision-other-root', 'revision-2', 'quarantined',
                    'test-v1', 'initial', '{}'
                )
                """
            )
        _assert_rejected(
            engine,
            """
            INSERT INTO source_revision_decisions (
                id, source_revision_id, outcome, policy_version, reason_code,
                basis_json, supersedes_decision_id
            ) VALUES (
                'decision-foreign-parent', 'revision-2', 'quarantined',
                'test-v1', 'foreign', '{}', 'decision-certified'
            )
            """,
            match="same source revision",
        )

        barrier = Barrier(2)

        def append_competing_successor(decision_id: str) -> tuple[str, str]:
            try:
                with engine.begin() as connection:
                    connection.exec_driver_sql("SET LOCAL lock_timeout = '5s'")
                    connection.exec_driver_sql("SET LOCAL statement_timeout = '10s'")
                    barrier.wait(timeout=5)
                    connection.execute(
                        text(
                            """
                            INSERT INTO source_revision_decisions (
                                id, source_revision_id, outcome, policy_version,
                                reason_code, basis_json, supersedes_decision_id
                            ) VALUES (
                                :id, 'revision-2', 'quarantined', 'test-v1',
                                'concurrent', '{}', 'decision-other-root'
                            )
                            """
                        ),
                        {"id": decision_id},
                    )
                return ("committed", decision_id)
            except DBAPIError as exc:
                return ("rejected", str(exc))

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(
                executor.map(
                    append_competing_successor,
                    ("decision-concurrent-a", "decision-concurrent-b"),
                )
            )
        assert [outcome for outcome, _detail in outcomes].count("committed") == 1
        assert [outcome for outcome, _detail in outcomes].count("rejected") == 1
        rejection = next(detail for outcome, detail in outcomes if outcome == "rejected")
        assert "linear chain" in rejection or "duplicate key" in rejection

        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO claim_review_decisions (
                        id, result_claim_id, outcome, reason_code, basis_json
                    ) VALUES ('review-1', 'claim-1', 'validation_reviewed', 'reviewed', '{}')
                    """
                )
            )
            connection.execute(
                text(
                    """
                    INSERT INTO claim_publication_decisions (
                        id, result_claim_id, claim_review_decision_id, outcome,
                        policy_version, reason_code, basis_json
                    ) VALUES (
                        'publication-1', 'claim-1', 'review-1', 'quarantined',
                        'test-v1', 'reviewed', '{}'
                    )
                    """
                )
            )
        _assert_rejected(
            engine,
            """
            INSERT INTO claim_review_decisions (
                id, result_claim_id, outcome, reason_code, basis_json
            ) VALUES ('review-second-root', 'claim-1', 'needs_review', 'branch', '{}')
            """,
            match="linear chain",
        )
        _assert_rejected(
            engine,
            """
            INSERT INTO claim_publication_decisions (
                id, result_claim_id, claim_review_decision_id, outcome,
                policy_version, reason_code, basis_json
            ) VALUES (
                'publication-second-root', 'claim-1', 'review-1', 'quarantined',
                'test-v1', 'branch', '{}'
            )
            """,
            match="linear chain",
        )

        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO source_revision_decisions (
                        id, source_revision_id, outcome, policy_version, reason_code,
                        basis_json, supersedes_decision_id
                    ) VALUES (
                        'decision-revoked', 'revision-1', 'revoked', 'test-v1',
                        'stale', '{}', 'decision-certified'
                    )
                    """
                )
            )
        _assert_rejected(
            engine,
            """
            INSERT INTO result_claims (
                id, source_snapshot_id, source_revision_decision_id, official_source_id,
                model_raw, benchmark_raw, score_raw, evidence_location,
                capture_method, claim_fingerprint
            ) VALUES (
                'claim-stale', 'snapshot-1', :decision_id, 's1', 'Raw', 'Bench',
                '78.0', '{}', 'fixture', :fingerprint
            )
            """,
            params={"decision_id": ids["certified_decision_id"], "fingerprint": "d" * 64},
            match="current effective certified",
        )
        engine.dispose()
    finally:
        _reset_public_schema(database_url)


def test_real_postgresql_known_revision_upgrade_and_forged_head_fail_closed():
    database_url = _target_url()
    _reset_public_schema(database_url)
    try:
        command.upgrade(_config(database_url), "0008_claim_publication_chain_guards")
        before = inspect_database(database_url)
        assert before.kind == "versioned_but_not_head"
        with pytest.raises(DatabaseMigrationError, match="revision changed"):
            upgrade_postgresql_database(database_url, expected_revision="0007_claim_review_chain_guards")
        assert inspect_database(database_url).revision == "0008_claim_publication_chain_guards"

        engine = _engine(database_url)
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "ALTER TABLE result_claims "
                "DROP CONSTRAINT result_claims_source_snapshot_id_fkey"
            )
        with pytest.raises(DatabaseMigrationError, match="rolled back"):
            upgrade_postgresql_database(
                database_url, expected_revision="0008_claim_publication_chain_guards"
            )
        assert inspect_database(database_url).revision == "0008_claim_publication_chain_guards"
        with engine.connect() as connection:
            assert connection.execute(
                text(
                    "SELECT COUNT(*) FROM pg_proc p "
                    "WHERE p.proname = 'ledger_validate_result_claim_admission'"
                )
            ).scalar_one() == 0
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "ALTER TABLE result_claims "
                "ADD CONSTRAINT result_claims_source_snapshot_id_fkey "
                "FOREIGN KEY (source_snapshot_id) REFERENCES source_snapshots(id)"
            )
        engine.dispose()

        upgraded = upgrade_postgresql_database(
            database_url, expected_revision="0008_claim_publication_chain_guards"
        )
        assert upgraded.kind == "current"
        assert upgraded.integrity_ok

        engine = _engine(database_url)
        with engine.begin() as connection:
            connection.exec_driver_sql("DROP INDEX ix_result_claims_official_source")
        broken_index = inspect_database(database_url)
        assert broken_index.kind == "invalid"
        assert not broken_index.integrity_ok
        assert "required indexes" in (broken_index.detail or "")
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "CREATE INDEX ix_result_claims_official_source "
                "ON result_claims (official_source_id)"
            )
        assert inspect_database(database_url).kind == "current"

        with engine.begin() as connection:
            connection.exec_driver_sql(
                "ALTER TABLE result_claims "
                "DROP CONSTRAINT result_claims_source_snapshot_id_fkey"
            )
        broken_fk = inspect_database(database_url)
        assert broken_fk.kind == "invalid"
        assert not broken_fk.integrity_ok
        assert "required constraints" in (broken_fk.detail or "")
        engine.dispose()

        _reset_public_schema(database_url)
        engine = _engine(database_url)
        with engine.begin() as connection:
            connection.exec_driver_sql("CREATE TABLE alembic_version (version_num varchar(128) primary key)")
            connection.execute(
                text("INSERT INTO alembic_version (version_num) VALUES (:head)"),
                {"head": head_revision()},
            )
        forged = inspect_database(database_url)
        assert forged.kind == "invalid"
        assert not forged.integrity_ok
        assert "table inventory mismatch" in (forged.detail or "")
        engine.dispose()
    finally:
        _reset_public_schema(database_url)


def test_real_postgresql_0001_rows_upgrade_without_rewriting_raw_evidence():
    database_url = _target_url()
    _reset_public_schema(database_url)
    try:
        command.upgrade(_config(database_url), "0001_legacy_schema")
        engine = _engine(database_url)
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "INSERT INTO benchmarks (id, canonical_name, display_name) "
                "VALUES ('b1', 'bench', 'Bench')"
            )
            connection.exec_driver_sql(
                "INSERT INTO model_entities (id, canonical_name, display_name, entity_type) "
                "VALUES ('m1', 'model', 'Model', 'model')"
            )
            connection.exec_driver_sql(
                """
                INSERT INTO official_sources (
                    id, benchmark_id, source_name, source_url, source_type,
                    officialness_level, parser_config, status
                ) VALUES (
                    's1', 'b1', 'Legacy source', 'https://official.example/legacy.json',
                    'api', 'O5', '{}', 'active'
                )
                """
            )
            connection.exec_driver_sql(
                """
                INSERT INTO source_snapshots (
                    id, official_source_id, raw_content_uri, content_hash, fetch_metadata
                ) VALUES (
                    'snapshot-legacy', 's1', 'file:///immutable/legacy.json',
                    'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', '{}'
                )
                """
            )
            connection.exec_driver_sql(
                """
                INSERT INTO result_claims (
                    id, source_snapshot_id, official_source_id, benchmark_id,
                    model_entity_id, model_raw, benchmark_raw, score_raw,
                    evidence_location, capture_method, claim_fingerprint
                ) VALUES (
                    'claim-legacy', 'snapshot-legacy', 's1', 'b1', 'm1',
                    'Model Raw Exact', 'Bench Raw Exact', '77.000', '{}',
                    'legacy-fixture',
                    'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb'
                )
                """
            )
        engine.dispose()

        upgraded = upgrade_postgresql_database(
            database_url, expected_revision="0001_legacy_schema"
        )
        assert upgraded.kind == "current"
        engine = _engine(database_url)
        with engine.connect() as connection:
            raw = connection.execute(
                text(
                    "SELECT model_raw, benchmark_raw, score_raw, source_revision_decision_id "
                    "FROM result_claims WHERE id = 'claim-legacy'"
                )
            ).one()
            assert raw == ("Model Raw Exact", "Bench Raw Exact", "77.000", None)
            assert connection.execute(
                text("SELECT outcome FROM source_revision_decisions")
            ).scalar_one() == "quarantined"
            assert connection.execute(
                text(
                    "SELECT outcome FROM claim_publication_decisions "
                    "WHERE result_claim_id = 'claim-legacy'"
                )
            ).scalar_one() == "quarantined"
            captured_at = connection.execute(
                text("SELECT captured_at FROM source_snapshots WHERE id = 'snapshot-legacy'")
            ).scalar_one()
            assert captured_at.tzinfo is not None
        engine.dispose()
    finally:
        _reset_public_schema(database_url)


def test_real_postgresql_wrong_search_path_and_role_bypasses_fail_closed():
    database_url = _target_url()
    _drop_test_roles(database_url)
    _reset_public_schema(database_url)
    engine = None
    try:
        initialize_database(database_url)
        engine = _engine(database_url)
        _seed_admissible_claim(engine)
        with engine.begin() as connection:
            connection.exec_driver_sql("DROP SCHEMA IF EXISTS test_ledger_shadow CASCADE")
            connection.exec_driver_sql("CREATE SCHEMA test_ledger_shadow")
        shadow_url = make_url(database_url).update_query_dict(
            {"options": "-csearch_path=test_ledger_shadow"}
        )
        wrong_schema = inspect_database(shadow_url.render_as_string(hide_password=False))
        assert wrong_schema.kind == "invalid"
        assert not wrong_schema.integrity_ok
        assert "current_schema()" in (wrong_schema.detail or "")

        role_sql = render_least_privilege_role_sql(
            migrator_role=_TEST_ROLES["migrator"],
            ingestion_role=_TEST_ROLES["ingestion"],
            governance_role=_TEST_ROLES["governance"],
            artifact_role=_TEST_ROLES["artifact"],
            audit_role=_TEST_ROLES["audit"],
        )
        with engine.begin() as connection:
            connection.exec_driver_sql(role_sql)
            connection.exec_driver_sql(
                f"GRANT UPDATE ON public.benchmarks TO {_TEST_ROLES['ingestion']}"
            )
            # Reapplying the declarative contract must remove stale/broad
            # grants rather than merely layering narrow grants on top.
            connection.exec_driver_sql(role_sql)
            assert connection.execute(
                text(
                    "SELECT pg_get_userbyid(relowner) FROM pg_class "
                    "WHERE relnamespace = 'public'::regnamespace "
                    "AND relname = 'result_claims'"
                )
            ).scalar_one() == _TEST_ROLES["migrator"]

        with engine.begin() as connection:
            connection.exec_driver_sql(
                f"GRANT {_TEST_ROLES['migrator']} TO {_TEST_ROLES['ingestion']}"
            )
        with engine.connect() as connection:
            with pytest.raises(DBAPIError, match="pre-existing memberships"):
                connection.exec_driver_sql(role_sql)
            connection.rollback()
        with engine.begin() as connection:
            connection.exec_driver_sql(
                f"REVOKE {_TEST_ROLES['migrator']} FROM {_TEST_ROLES['ingestion']}"
            )
            connection.exec_driver_sql(role_sql)
            role_attributes = {
                str(role): (bool(inherit), bool(bypass_rls))
                for role, inherit, bypass_rls in connection.execute(
                    text(
                        "SELECT rolname, rolinherit, rolbypassrls FROM pg_roles "
                        "WHERE rolname = ANY(:roles)"
                    ),
                    {"roles": list(_TEST_ROLES.values())},
                )
            }
            assert role_attributes == {
                role: (False, False) for role in _TEST_ROLES.values()
            }

        with engine.begin() as connection:
            connection.exec_driver_sql(
                f"ALTER SCHEMA public OWNER TO {_TEST_ROLES['ingestion']}"
            )
        with engine.connect() as connection:
            with pytest.raises(DBAPIError, match="must not own"):
                connection.exec_driver_sql(role_sql)
            connection.rollback()
        with engine.begin() as connection:
            connection.exec_driver_sql("ALTER SCHEMA public OWNER TO CURRENT_USER")
            connection.exec_driver_sql(role_sql)

        with engine.begin() as connection:
            connection.exec_driver_sql(f"SET LOCAL ROLE {_TEST_ROLES['ingestion']}")
            connection.exec_driver_sql(
                "INSERT INTO ingestion_runs (id, run_type, status) "
                "VALUES ('role-run-positive', 'fixture', 'running')"
            )
            connection.exec_driver_sql(
                """
                INSERT INTO source_snapshots (
                    id, official_source_id, source_revision_id, raw_content_uri,
                    content_hash, fetch_metadata
                ) VALUES (
                    'role-snapshot-positive', 's1', 'revision-1',
                    'r2://snapshots/role-positive',
                    'ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff', '{}'
                )
                """
            )
            connection.exec_driver_sql(
                """
                UPDATE ingestion_runs
                SET status = 'completed',
                    finished_at = now(),
                    sources_checked = 1,
                    snapshots_created = 1,
                    snapshots_reused = 0,
                    claims_extracted = 1,
                    claims_inserted = 1,
                    claims_unchanged = 0,
                    claims_needing_review = 0,
                    error_message = NULL,
                    metadata = '{"role_finalized": true}'::jsonb
                WHERE id = 'role-run-positive'
                """
            )
        with engine.connect() as connection:
            transaction = connection.begin()
            connection.exec_driver_sql(f"SET LOCAL ROLE {_TEST_ROLES['ingestion']}")
            with pytest.raises(DBAPIError, match="identity/history"):
                connection.exec_driver_sql(
                    "UPDATE ingestion_runs SET metadata = '{}'::jsonb "
                    "WHERE id = 'role-run-positive'"
                )
            transaction.rollback()
        with engine.connect() as connection:
            transaction = connection.begin()
            connection.exec_driver_sql(f"SET LOCAL ROLE {_TEST_ROLES['ingestion']}")
            with pytest.raises(DBAPIError, match="permission denied"):
                connection.exec_driver_sql(
                    "UPDATE ingestion_runs SET run_type = 'rewritten' "
                    "WHERE id = 'role-run-positive'"
                )
            transaction.rollback()
        with engine.begin() as connection:
            connection.exec_driver_sql(f"SET LOCAL ROLE {_TEST_ROLES['governance']}")
            connection.exec_driver_sql(
                """
                INSERT INTO review_work_items (
                    work_item_id, work_item_fingerprint_sha256, environment,
                    work_class, reason_code, publication_blocking,
                    first_contract_sha256
                ) VALUES (
                    'role-work-positive',
                    'dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd',
                    'fixture-shadow', 'model_system_identity',
                    'MODEL_AMBIGUOUS', true,
                    'eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee'
                )
                """
            )
        with engine.connect() as connection:
            assert connection.execute(
                text(
                    "SELECT has_table_privilege(:role, "
                    "'public.scheduled_job_leases', 'UPDATE')"
                ),
                {"role": _TEST_ROLES["ingestion"]},
            ).scalar_one()
            assert not connection.execute(
                text(
                    "SELECT has_column_privilege(:role, "
                    "'public.scheduled_job_intents', 'lane', 'UPDATE')"
                ),
                {"role": _TEST_ROLES["ingestion"]},
            ).scalar_one()
            assert connection.execute(
                text(
                    "SELECT has_column_privilege(:role, "
                    "'public.ingestion_runs', 'metadata', 'UPDATE')"
                ),
                {"role": _TEST_ROLES["ingestion"]},
            ).scalar_one()
            assert not connection.execute(
                text(
                    "SELECT has_column_privilege(:role, "
                    "'public.ingestion_runs', 'run_type', 'UPDATE')"
                ),
                {"role": _TEST_ROLES["ingestion"]},
            ).scalar_one()
        for read_role in (_TEST_ROLES["artifact"], _TEST_ROLES["audit"]):
            with engine.begin() as connection:
                connection.exec_driver_sql(f"SET LOCAL ROLE {read_role}")
                assert connection.exec_driver_sql(
                    "SELECT COUNT(*) FROM result_claims"
                ).scalar_one() == 1
        with engine.begin() as connection:
            connection.exec_driver_sql(f"SET LOCAL ROLE {_TEST_ROLES['migrator']}")
            connection.exec_driver_sql("CREATE TABLE role_migrator_probe (id integer primary key)")
            connection.exec_driver_sql("DROP TABLE role_migrator_probe")
            connection.exec_driver_sql(
                "ALTER TABLE result_claims ADD COLUMN role_migrator_probe integer"
            )
            connection.exec_driver_sql(
                "ALTER TABLE result_claims DROP COLUMN role_migrator_probe"
            )

        role_probes = (
            (
                _TEST_ROLES["ingestion"],
                "INSERT INTO claim_review_decisions "
                "(id, result_claim_id, outcome, reason_code, basis_json) "
                "VALUES ('role-review', 'claim-1', 'needs_review', 'forbidden', '{}')",
            ),
            (
                _TEST_ROLES["ingestion"],
                "INSERT INTO aliases (id, entity_type, entity_id, alias_text) "
                "VALUES ('role-alias', 'model', 'm1', 'forbidden')",
            ),
            (
                _TEST_ROLES["ingestion"],
                "UPDATE result_claims SET score_raw = '999' WHERE id = 'claim-1'",
            ),
            (
                _TEST_ROLES["ingestion"],
                "UPDATE benchmarks SET display_name = 'forbidden' WHERE id = 'b1'",
            ),
            (
                _TEST_ROLES["governance"],
                "INSERT INTO claim_review_decisions "
                "(id, result_claim_id, outcome, reason_code, basis_json) "
                "VALUES ('role-review-governance', 'claim-1', 'needs_review', "
                "'forbidden', '{}')",
            ),
            (
                _TEST_ROLES["governance"],
                "INSERT INTO source_revision_decisions "
                "(id, source_revision_id, outcome, policy_version, reason_code, basis_json) "
                "VALUES ('role-certification', 'revision-1', 'certified', "
                "'forbidden', 'forbidden', '{}')",
            ),
            (
                _TEST_ROLES["governance"],
                "INSERT INTO claim_publication_decisions (id) "
                "VALUES ('role-publication')",
            ),
            (
                _TEST_ROLES["governance"],
                "INSERT INTO result_claims "
                "(id, source_snapshot_id, official_source_id, model_raw, benchmark_raw, "
                "score_raw, evidence_location, capture_method, claim_fingerprint) "
                "VALUES ('role-claim', 'snapshot-1', 's1', 'Raw', 'Bench', '1', '{}', 'x', '"
                + "e" * 64
                + "')",
            ),
            (
                _TEST_ROLES["artifact"],
                "INSERT INTO ingestion_runs (id, run_type, status) VALUES ('role-run-a', 'x', 'running')",
            ),
            (
                _TEST_ROLES["artifact"],
                "SELECT COUNT(*) FROM ops_incidents",
            ),
            (
                _TEST_ROLES["ingestion"],
                "UPDATE scheduled_job_intents SET lane = 'forbidden'",
            ),
            (
                _TEST_ROLES["audit"],
                "INSERT INTO ingestion_runs (id, run_type, status) VALUES ('role-run-b', 'x', 'running')",
            ),
        )
        for role, statement in role_probes:
            with engine.connect() as connection:
                transaction = connection.begin()
                connection.exec_driver_sql(f"SET LOCAL ROLE {role}")
                with pytest.raises(DBAPIError, match="permission denied"):
                    connection.exec_driver_sql(statement)
                transaction.rollback()
        for statement in (
            "UPDATE benchmarks SET id = 'forbidden-benchmark' WHERE id = 'b1'",
            "UPDATE model_entities SET id = 'forbidden-model' WHERE id = 'm1'",
        ):
            with engine.connect() as connection:
                transaction = connection.begin()
                connection.exec_driver_sql(f"SET LOCAL ROLE {_TEST_ROLES['ingestion']}")
                with pytest.raises(DBAPIError, match="append-only"):
                    connection.exec_driver_sql(statement)
                transaction.rollback()
    finally:
        if engine is not None:
            with engine.begin() as connection:
                connection.exec_driver_sql("DROP SCHEMA IF EXISTS test_ledger_shadow CASCADE")
            engine.dispose()
        _reset_public_schema(database_url)
        _drop_test_roles(database_url)


def test_real_postgresql_repository_serializes_source_revision_allocation_and_native_types():
    database_url = _target_url()
    _reset_public_schema(database_url)
    engine = _engine(database_url)
    try:
        initialize_database(database_url)
        with Session(engine) as session:
            repositories.upsert_benchmark(
                session,
                {
                    "id": "repo-benchmark",
                    "canonical_name": "repo-benchmark",
                    "display_name": "Repository benchmark",
                    "known_metrics": [{"name": "accuracy", "higher_is_better": True}],
                },
            )
            created = repositories.reconcile_official_source(
                session,
                {
                    "id": "repo-source",
                    "benchmark_id": "repo-benchmark",
                    "source_name": "Repository source",
                    "source_url": "https://official.example/repository.json",
                    "source_type": "api",
                    "officialness_level": "O5",
                    "machine_readable": True,
                    "requires_auth": False,
                    "supports_history": True,
                    "parser_name": "fixture",
                    "parser_version": "1",
                    "parser_config": {"path": ["results"]},
                    "status": "active",
                    "notes": "initial",
                },
            )
            assert created.disposition == "created"
            session.commit()

        barrier = Barrier(2)

        def reconcile_note(note: str) -> tuple[str, str]:
            with Session(engine) as session:
                session.execute(text("SET LOCAL lock_timeout = '5s'"))
                session.execute(text("SET LOCAL statement_timeout = '10s'"))
                barrier.wait(timeout=5)
                result = repositories.reconcile_official_source(
                    session,
                    {"id": "repo-source", "notes": note},
                )
                revision_id = result.revision.id
                disposition = result.disposition
                session.commit()
                return disposition, revision_id

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(
                executor.map(reconcile_note, ("concurrent-a", "concurrent-b"))
            )
        assert [disposition for disposition, _revision_id in outcomes] == [
            "revised",
            "revised",
        ]

        with Session(engine) as session:
            source = session.get(models.OfficialSourceRow, "repo-source")
            benchmark = session.get(models.Benchmark, "repo-benchmark")
            revisions = list(
                session.scalars(
                    select(models.OfficialSourceRevision)
                    .where(
                        models.OfficialSourceRevision.official_source_id
                        == "repo-source"
                    )
                    .order_by(models.OfficialSourceRevision.revision_ordinal)
                )
            )

            assert source is not None
            assert benchmark is not None
            assert benchmark.known_metrics == [
                {"name": "accuracy", "higher_is_better": True}
            ]
            assert [revision.revision_ordinal for revision in revisions] == [1, 2, 3]
            assert revisions[0].supersedes_revision_id is None
            assert revisions[1].supersedes_revision_id == revisions[0].id
            assert revisions[2].supersedes_revision_id == revisions[1].id
            assert source.current_revision_id == revisions[2].id
            assert {revision.notes for revision in revisions[1:]} == {
                "concurrent-a",
                "concurrent-b",
            }
            assert all(
                revision.definition_json["parser_config"] == {"path": ["results"]}
                for revision in revisions
            )
            assert all(
                revision.created_at.tzinfo is not None
                and revision.created_at.utcoffset() is not None
                for revision in revisions
            )
            run = repositories.create_ingestion_run(
                session,
                run_type="repository_native_type_probe",
                official_source_id="repo-source",
            )
            repositories.finish_ingestion_run(
                session,
                run,
                status="completed",
                metadata={"nested": {"verified": True}},
            )
            session.commit()
            session.refresh(run)
            assert run.finished_at is not None
            assert run.finished_at.tzinfo is not None
            assert run.finished_at.utcoffset() is not None
            assert run.metadata_json == {"nested": {"verified": True}}
    finally:
        engine.dispose()
        _reset_public_schema(database_url)
