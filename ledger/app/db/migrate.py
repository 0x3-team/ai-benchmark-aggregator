"""Fail-closed SQLite and PostgreSQL migration helpers.

The ledger does not auto-upgrade an existing database.  A populated legacy
database must first pass a read-only preflight, be copied with SQLite's backup
API, and be upgraded in a staged sibling file before an atomic replacement.
That design prevents an interrupted migration from becoming a repair task for
the source evidence database. PostgreSQL initialization and explicit
expected-revision upgrades use one caller-owned transaction, an advisory lock,
and exact head inventory before commit; SQLite copy semantics never carry over
to PostgreSQL.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from urllib.parse import quote, unquote
from uuid import uuid4

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect as sqlalchemy_inspect, text
from sqlalchemy.engine import Connection, make_url
from sqlalchemy.pool import NullPool

from app.db.postgresql import (
    POSTGRESQL_JSONB_COLUMNS,
    POSTGRESQL_DEFERRABLE_CONSTRAINTS,
    POSTGRESQL_INITIALLY_DEFERRED_CONSTRAINTS,
    POSTGRESQL_LEGACY_NULLABLE_TIMESTAMP_COLUMNS,
    POSTGRESQL_MIGRATION_LOCK_KEY,
    POSTGRESQL_OPERATIONAL_CONSTRAINT_INVENTORY_SHA256,
    POSTGRESQL_OPERATIONAL_INDEX_INVENTORY_SHA256,
    POSTGRESQL_OPERATIONAL_TABLES,
    POSTGRESQL_OPERATIONAL_TRIGGER_INVENTORY_SHA256,
    POSTGRESQL_REQUIRED_COLUMN_DEFAULTS,
    POSTGRESQL_REQUIRED_CONSTRAINTS,
    POSTGRESQL_REQUIRED_CONSTRAINT_TABLES,
    POSTGRESQL_REQUIRED_FUNCTION_FINGERPRINTS,
    POSTGRESQL_REQUIRED_FUNCTIONS,
    POSTGRESQL_REQUIRED_INDEXES,
    POSTGRESQL_REQUIRED_TABLES,
    POSTGRESQL_REQUIRED_TRIGGER_BINDINGS,
    POSTGRESQL_REQUIRED_TRIGGERS,
    POSTGRESQL_SCHEMA,
    POSTGRESQL_TIMESTAMPTZ_COLUMNS,
    is_postgresql_url,
    redacted_postgresql_url,
)
from app.db.models import Base


_LEDGER_ROOT = Path(__file__).resolve().parents[2]
_ALEMBIC_INI = _LEDGER_ROOT / "alembic.ini"
_MIGRATIONS_DIR = _LEDGER_ROOT / "migrations"
_LEGACY_BASELINE = "0001_legacy_schema"


class DatabaseMigrationError(RuntimeError):
    """A migration request that is unsafe, unsupported, or failed validation."""


@dataclass(frozen=True)
class DatabaseStatus:
    kind: str
    database_url: str
    path: str | None
    revision: str | None
    tables: tuple[str, ...]
    integrity_ok: bool
    foreign_key_violations: int
    detail: str | None = None

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class MigrationReceipt:
    database_path: str
    backup_path: str
    input_sha256: str
    output_sha256: str
    from_revision: str
    to_revision: str
    integrity_ok: bool
    foreign_key_violations: int

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


# A populated, unversioned database is stamped only when its table and column
# set exactly matches this pre-governance baseline.  Unknown/partial schemas
# must be investigated, never guessed into a revision.
_LEGACY_COLUMNS: dict[str, frozenset[str]] = {
    "aliases": frozenset(
        {
            "id", "entity_type", "entity_id", "alias_text", "alias_source", "source_url",
            "confidence", "is_official_alias", "created_at",
        }
    ),
    "benchmarks": frozenset(
        {
            "id", "canonical_name", "display_name", "benchmark_family", "description",
            "owner_name", "owner_type", "official_home_url", "official_repo_url",
            "official_dataset_url", "official_leaderboard_url", "official_docs_url",
            "has_official_leaderboard", "has_official_result_api", "has_official_result_files",
            "has_private_test_set", "primary_metric", "known_metrics", "known_splits",
            "known_settings", "status", "superseded_by_benchmark_id", "created_at", "updated_at",
        }
    ),
    "claim_relationships": frozenset(
        {"id", "claim_id", "related_claim_id", "relationship_type", "notes", "created_at"}
    ),
    "claim_validations": frozenset(
        {"id", "result_claim_id", "validation_type", "outcome", "validator", "notes", "validated_at"}
    ),
    "ingestion_runs": frozenset(
        {
            "id", "started_at", "finished_at", "run_type", "status", "official_source_id",
            "sources_checked", "snapshots_created", "snapshots_reused", "claims_extracted",
            "claims_inserted", "claims_unchanged", "claims_needing_review", "error_message", "metadata",
        }
    ),
    "model_entities": frozenset(
        {
            "id", "canonical_name", "display_name", "entity_type", "provider", "developer",
            "model_family", "access_type", "official_model_url", "official_docs_url",
            "official_card_url", "official_repo_url", "official_hf_repo", "api_model_id",
            "api_version", "endpoint_fingerprint", "artifact_hash", "weights_revision",
            "tokenizer_revision", "base_model_entity_id", "release_date", "deprecation_date",
            "status", "context_window", "modalities", "license", "created_at", "updated_at",
        }
    ),
    "official_sources": frozenset(
        {
            "id", "benchmark_id", "source_name", "source_url", "source_type",
            "officialness_level", "machine_readable", "requires_auth", "supports_history",
            "update_cadence", "parser_name", "parser_version", "parser_config", "status",
            "notes", "created_at", "updated_at",
        }
    ),
    "result_claims": frozenset(
        {
            "id", "source_snapshot_id", "official_source_id", "benchmark_id", "model_entity_id",
            "model_raw", "benchmark_raw", "score_raw", "metric_raw", "split_raw", "setting_raw",
            "rank_raw", "date_raw", "score_numeric", "score_unit", "evidence_text",
            "evidence_location", "capture_method", "capture_confidence", "capture_status",
            "scientific_status", "officialness_level", "claim_fingerprint", "created_at",
        }
    ),
    "source_snapshots": frozenset(
        {
            "id", "official_source_id", "captured_at", "raw_content_uri", "rendered_screenshot_uri",
            "content_hash", "content_type", "http_status", "etag", "last_modified_header",
            "fetch_metadata", "parser_version", "created_at",
        }
    ),
}
_LEGACY_TABLES = frozenset(_LEGACY_COLUMNS)


def _sqlite_path(database_url: str) -> Path:
    if database_url == "sqlite:///:memory:" or database_url.endswith(":memory:"):
        raise DatabaseMigrationError("In-memory SQLite is unsupported for durable ledger migrations.")
    if not database_url.startswith("sqlite:///"):
        raise DatabaseMigrationError("Only file-backed SQLite URLs are supported by the ledger migration service.")
    raw_path = unquote(database_url[len("sqlite:///") :].split("?", 1)[0])
    if not raw_path:
        raise DatabaseMigrationError("SQLite database URL must include a file path.")
    return Path(raw_path).expanduser().resolve()


def _read_only_connection(path: Path) -> sqlite3.Connection:
    uri = f"file:{quote(str(path))}?mode=ro"
    return sqlite3.connect(uri, uri=True)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _catalog_inventory_sha256(rows: list[list[object]]) -> str:
    """Hash a deterministically sorted, JSON-safe PostgreSQL catalog census."""

    canonical_rows = sorted(
        rows,
        key=lambda row: json.dumps(
            row,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ),
    )
    encoded = json.dumps(
        canonical_rows,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _alembic_config(database_url: str) -> Config:
    config = Config(str(_ALEMBIC_INI))
    config.set_main_option("script_location", str(_MIGRATIONS_DIR))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    config.attributes["database_url"] = database_url
    return config


def head_revision() -> str:
    head = ScriptDirectory.from_config(_alembic_config("sqlite:////dev/null")).get_current_head()
    if head is None:
        raise DatabaseMigrationError("No Alembic head revision is available.")
    return head


def _known_revision(revision: str) -> bool:
    """Return whether a stored Alembic revision belongs to this ledger chain."""
    script = ScriptDirectory.from_config(_alembic_config("sqlite:////dev/null"))
    return revision in {candidate.revision for candidate in script.walk_revisions()}


def supports_copy_migration(status: DatabaseStatus) -> bool:
    """Whether a read-only preflight state is eligible for a staged copy upgrade."""
    return status.path is not None and (status.kind == "legacy_unversioned" or (
        status.kind == "versioned_but_not_head"
        and status.revision is not None
        and _known_revision(status.revision)
    ))


def redacted_database_url(database_url: str) -> str:
    """Return an operator-safe locator for CLI receipts."""
    if is_postgresql_url(database_url):
        return redacted_postgresql_url(database_url)
    try:
        path = _sqlite_path(database_url)
    except DatabaseMigrationError:
        return "<unsupported database URL>"
    return f"sqlite:///{path}"


def _table_names(connection: sqlite3.Connection) -> tuple[str, ...]:
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    return tuple(row[0] for row in rows)


def _legacy_signature_matches(connection: sqlite3.Connection, tables: tuple[str, ...]) -> bool:
    if frozenset(tables) != _LEGACY_TABLES:
        return False
    # Batch table reconstruction cannot safely promise to preserve unknown
    # user-defined indexes, views, or triggers.  Treat their presence as an
    # unmodelled legacy state instead of silently discarding them.
    auxiliary_objects = connection.execute(
        """
        SELECT name FROM sqlite_master
        WHERE type IN ('index', 'trigger', 'view')
          AND name NOT LIKE 'sqlite_%'
        """
    ).fetchall()
    if auxiliary_objects:
        return False
    for table, expected_columns in _LEGACY_COLUMNS.items():
        actual_columns = frozenset(row[1] for row in connection.execute(f"PRAGMA table_info({table})"))
        if actual_columns != expected_columns:
            return False
    return True


def _inspect_sqlite_database(database_url: str) -> DatabaseStatus:
    """Run a read-only schema/integrity preflight without repairing anything."""
    path = _sqlite_path(database_url)
    if not path.exists():
        return DatabaseStatus(
            kind="empty",
            database_url=database_url,
            path=str(path),
            revision=None,
            tables=(),
            integrity_ok=True,
            foreign_key_violations=0,
            detail="Database file does not exist yet.",
        )

    try:
        with _read_only_connection(path) as connection:
            tables = _table_names(connection)
            integrity_rows = connection.execute("PRAGMA integrity_check").fetchall()
            integrity_ok = integrity_rows == [("ok",)]
            fk_violations = len(connection.execute("PRAGMA foreign_key_check").fetchall())
            if not integrity_ok:
                return DatabaseStatus(
                    "invalid", database_url, str(path), None, tables, False, fk_violations,
                    "SQLite integrity_check failed.",
                )
            if fk_violations:
                return DatabaseStatus(
                    "invalid", database_url, str(path), None, tables, True, fk_violations,
                    "SQLite foreign_key_check reported violations; migration is refused.",
                )
            if not tables:
                return DatabaseStatus("empty", database_url, str(path), None, tables, True, 0)

            if "alembic_version" in tables:
                revisions = connection.execute("SELECT version_num FROM alembic_version").fetchall()
                if len(revisions) != 1 or not revisions[0][0]:
                    return DatabaseStatus(
                        "invalid", database_url, str(path), None, tables, True, 0,
                        "alembic_version must contain exactly one non-empty revision.",
                    )
                revision = str(revisions[0][0])
                if revision == head_revision():
                    return DatabaseStatus("current", database_url, str(path), revision, tables, True, 0)
                return DatabaseStatus(
                    "versioned_but_not_head", database_url, str(path), revision, tables, True, 0,
                    "Versioned database is not at the ledger migration head; explicit recovery review is required.",
                )

            if _legacy_signature_matches(connection, tables):
                return DatabaseStatus(
                    "legacy_unversioned", database_url, str(path), None, tables, True, 0,
                    "Exact pre-governance baseline detected; migration is allowed only through a staged copy rehearsal.",
                )
            return DatabaseStatus(
                "unsupported", database_url, str(path), None, tables, True, 0,
                "Schema does not exactly match the known legacy baseline and is not versioned.",
            )
    except sqlite3.DatabaseError as exc:
        return DatabaseStatus(
            "invalid", database_url, str(path), None, (), False, 0, f"SQLite preflight failed: {exc}"
        )


def _postgresql_status_from_connection(
    connection: Connection,
    *,
    database_url: str,
) -> DatabaseStatus:
    """Inspect only the active PostgreSQL schema on an existing connection."""
    safe_url = redacted_database_url(database_url)
    schema = connection.execute(text("SELECT current_schema()")).scalar_one_or_none()
    if schema != POSTGRESQL_SCHEMA:
        return DatabaseStatus(
            "invalid",
            safe_url,
            None,
            None,
            (),
            False,
            0,
            f"PostgreSQL current_schema() must be {POSTGRESQL_SCHEMA!r}; migration is refused.",
        )
    inspector = sqlalchemy_inspect(connection)
    tables = tuple(sorted(inspector.get_table_names(schema=schema)))
    if not tables:
        return DatabaseStatus("empty", safe_url, None, None, (), True, 0)
    if "alembic_version" not in tables:
        return DatabaseStatus(
            "unsupported",
            safe_url,
            None,
            None,
            tables,
            True,
            0,
            "Populated PostgreSQL schema has no Alembic version; automatic stamping is forbidden.",
        )
    revisions = connection.execute(text("SELECT version_num FROM alembic_version")).scalars().all()
    if len(revisions) != 1 or not revisions[0]:
        return DatabaseStatus(
            "invalid",
            safe_url,
            None,
            None,
            tables,
            True,
            0,
            "alembic_version must contain exactly one non-empty revision.",
        )
    revision = str(revisions[0])
    if revision == head_revision():
        required_tables = POSTGRESQL_REQUIRED_TABLES | {"alembic_version"}
        actual_tables = frozenset(tables)
        if actual_tables != required_tables:
            missing = sorted(required_tables - actual_tables)
            extra = sorted(actual_tables - required_tables)
            return DatabaseStatus(
                "invalid",
                safe_url,
                None,
                revision,
                tables,
                False,
                0,
                f"PostgreSQL head table inventory mismatch (missing={missing}, extra={extra}).",
            )

        table_states = {
            str(table_name): (
                str(relation_kind),
                str(persistence),
                bool(row_security),
                bool(force_row_security),
                bool(is_partition),
                str(replica_identity),
                bool(has_rules),
                str(owner_name),
            )
            for (
                table_name,
                relation_kind,
                persistence,
                row_security,
                force_row_security,
                is_partition,
                replica_identity,
                has_rules,
                owner_name,
            ) in connection.execute(
                text(
                    """
                    SELECT
                        relation.relname,
                        relation.relkind,
                        relation.relpersistence,
                        relation.relrowsecurity,
                        relation.relforcerowsecurity,
                        relation.relispartition,
                        relation.relreplident,
                        relation.relhasrules,
                        pg_get_userbyid(relation.relowner)
                    FROM pg_class relation
                    JOIN pg_namespace namespace ON namespace.oid = relation.relnamespace
                    WHERE namespace.nspname = :schema
                      AND relation.relname = ANY(:table_names)
                    """
                ),
                {
                    "schema": POSTGRESQL_SCHEMA,
                    "table_names": sorted(required_tables),
                },
            )
        }
        table_owners = {state[-1] for state in table_states.values()}
        bad_table_states = sorted(
            table_name
            for table_name in required_tables
            if table_states.get(table_name, ())[:-1]
            != ("r", "p", False, False, False, "d", False)
        )
        inheritance_edges = int(
            connection.execute(
                text(
                    """
                    WITH required_relations AS (
                        SELECT relation.oid
                        FROM pg_class relation
                        JOIN pg_namespace namespace
                          ON namespace.oid = relation.relnamespace
                        WHERE namespace.nspname = :schema
                          AND relation.relname = ANY(:table_names)
                    )
                    SELECT COUNT(*)
                    FROM pg_inherits inheritance
                    WHERE inheritance.inhparent IN (SELECT oid FROM required_relations)
                       OR inheritance.inhrelid IN (SELECT oid FROM required_relations)
                    """
                ),
                {
                    "schema": POSTGRESQL_SCHEMA,
                    "table_names": sorted(required_tables),
                },
            ).scalar_one()
        )
        if bad_table_states or inheritance_edges or len(table_owners) != 1:
            return DatabaseStatus(
                "invalid",
                safe_url,
                None,
                revision,
                tables,
                False,
                0,
                "PostgreSQL head table kind/persistence/RLS/partition/inheritance/"
                "replica/rule/owner posture mismatch: "
                f"{bad_table_states or sorted(table_owners)}; inheritance_edges={inheritance_edges}.",
            )
        table_owner = next(iter(table_owners))

        constraint_rows = list(
            connection.execute(
                text(
                    """
                    SELECT
                        constraint_catalog.conname,
                        table_relation.relname,
                        pg_get_constraintdef(constraint_catalog.oid),
                        constraint_catalog.convalidated,
                        constraint_catalog.condeferrable,
                        constraint_catalog.condeferred,
                        constraint_catalog.contype,
                        backing_index.indisvalid,
                        backing_index.indisready,
                        backing_index.indislive
                    FROM pg_constraint constraint_catalog
                    JOIN pg_namespace namespace
                      ON namespace.oid = constraint_catalog.connamespace
                    JOIN pg_class table_relation
                      ON table_relation.oid = constraint_catalog.conrelid
                    LEFT JOIN pg_index backing_index
                      ON backing_index.indexrelid = constraint_catalog.conindid
                    WHERE namespace.nspname = :schema
                      AND constraint_catalog.contype <> 't'
                    """
                ),
                {"schema": POSTGRESQL_SCHEMA},
            )
        )
        actual_constraints: dict[str, tuple[object, ...]] = {}
        duplicate_constraints: set[str] = set()
        operational_constraint_inventory: list[list[object]] = []
        for (
            name,
            table_name,
            definition,
            validated,
            deferrable,
            initially_deferred,
            constraint_type,
            index_valid,
            index_ready,
            index_live,
        ) in constraint_rows:
            name = str(name)
            if name in actual_constraints:
                duplicate_constraints.add(name)
            actual_constraints[name] = (
                str(table_name),
                str(definition),
                bool(validated),
                bool(deferrable),
                bool(initially_deferred),
                str(constraint_type),
                bool(index_valid),
                bool(index_ready),
                bool(index_live),
            )
            if str(table_name) in POSTGRESQL_OPERATIONAL_TABLES:
                operational_constraint_inventory.append(
                    [
                        name,
                        str(table_name),
                        str(definition),
                        bool(validated),
                        bool(deferrable),
                        bool(initially_deferred),
                        str(constraint_type),
                        bool(index_valid),
                        bool(index_ready),
                        bool(index_live),
                    ]
                )
        expected_constraint_types = {
            name: (
                "p"
                if definition.startswith("PRIMARY KEY")
                else "f"
                if definition.startswith("FOREIGN KEY")
                else "u"
            )
            for name, definition in POSTGRESQL_REQUIRED_CONSTRAINTS.items()
        }
        bad_constraints = sorted(
            name
            for name, expected in POSTGRESQL_REQUIRED_CONSTRAINTS.items()
            if actual_constraints.get(name)
            != (
                POSTGRESQL_REQUIRED_CONSTRAINT_TABLES[name],
                expected,
                True,
                name in POSTGRESQL_DEFERRABLE_CONSTRAINTS,
                name in POSTGRESQL_INITIALLY_DEFERRED_CONSTRAINTS,
                expected_constraint_types[name],
                True,
                True,
                True,
            )
        )
        bad_constraints.extend(
            sorted(
                name
                for name in set(actual_constraints) - set(POSTGRESQL_REQUIRED_CONSTRAINTS)
                if actual_constraints[name][0] not in POSTGRESQL_OPERATIONAL_TABLES
            )
        )
        bad_constraints.extend(sorted(duplicate_constraints))
        if bad_constraints:
            return DatabaseStatus(
                "invalid",
                safe_url,
                None,
                revision,
                tables,
                False,
                0,
                f"PostgreSQL head has missing or changed required constraints: {bad_constraints}.",
            )
        actual_deferrable = {
            name
            for name, state in actual_constraints.items()
            if state[0] in POSTGRESQL_OPERATIONAL_TABLES and state[3]
        }
        actual_initially_deferred = {
            name
            for name, state in actual_constraints.items()
            if state[0] in POSTGRESQL_OPERATIONAL_TABLES and state[4]
        }
        if (
            actual_deferrable != POSTGRESQL_DEFERRABLE_CONSTRAINTS
            or actual_initially_deferred
            != POSTGRESQL_INITIALLY_DEFERRED_CONSTRAINTS
            or _catalog_inventory_sha256(operational_constraint_inventory)
            != POSTGRESQL_OPERATIONAL_CONSTRAINT_INVENTORY_SHA256
        ):
            return DatabaseStatus(
                "invalid",
                safe_url,
                None,
                revision,
                tables,
                False,
                0,
                "PostgreSQL operational constraint inventory or exact deferrability posture changed.",
            )

        # Foreign keys are executable through PostgreSQL's internal RI
        # triggers.  ``pg_constraint`` can remain byte-for-byte correct while
        # an owner disables one of those triggers, so constraint metadata alone
        # is not proof that the relationship is enforced.  Exact constraints
        # above rule out extra/substituted FKs; this check binds every one to
        # its complete, normally-enabled trigger quartet and deferral posture.
        foreign_key_trigger_rows: dict[str, list[tuple[object, ...]]] = {}
        for (
            constraint_name,
            constraint_table,
            trigger_table,
            function_name,
            enabled,
            trigger_deferrable,
            trigger_initially_deferred,
        ) in connection.execute(
            text(
                """
                SELECT
                    constraint_catalog.conname,
                    constraint_relation.relname,
                    trigger_relation.relname,
                    function_catalog.proname,
                    trigger_catalog.tgenabled,
                    trigger_catalog.tgdeferrable,
                    trigger_catalog.tginitdeferred
                FROM pg_constraint constraint_catalog
                JOIN pg_namespace namespace
                  ON namespace.oid = constraint_catalog.connamespace
                JOIN pg_class constraint_relation
                  ON constraint_relation.oid = constraint_catalog.conrelid
                JOIN pg_trigger trigger_catalog
                  ON trigger_catalog.tgconstraint = constraint_catalog.oid
                 AND trigger_catalog.tgisinternal
                JOIN pg_class trigger_relation
                  ON trigger_relation.oid = trigger_catalog.tgrelid
                JOIN pg_proc function_catalog
                  ON function_catalog.oid = trigger_catalog.tgfoid
                WHERE namespace.nspname = :schema
                  AND constraint_catalog.contype = 'f'
                """
            ),
            {"schema": POSTGRESQL_SCHEMA},
        ):
            foreign_key_trigger_rows.setdefault(str(constraint_name), []).append(
                (
                    str(constraint_table),
                    str(trigger_table),
                    str(function_name),
                    str(enabled),
                    bool(trigger_deferrable),
                    bool(trigger_initially_deferred),
                )
            )
        expected_ri_functions = {
            "RI_FKey_check_ins",
            "RI_FKey_check_upd",
            "RI_FKey_noaction_del",
            "RI_FKey_noaction_upd",
        }
        foreign_key_constraints = {
            name: state
            for name, state in actual_constraints.items()
            if state[5] == "f"
        }
        bad_foreign_key_triggers = sorted(
            name
            for name, state in foreign_key_constraints.items()
            if (
                len(foreign_key_trigger_rows.get(name, ())) != 4
                or {
                    row[2] for row in foreign_key_trigger_rows.get(name, ())
                }
                != expected_ri_functions
                or any(
                    row[0] != state[0]
                    or row[3] != "O"
                    or row[4] != state[3]
                    or row[5] != state[4]
                    for row in foreign_key_trigger_rows.get(name, ())
                )
            )
        )
        bad_foreign_key_triggers.extend(
            sorted(set(foreign_key_trigger_rows) - set(foreign_key_constraints))
        )
        if bad_foreign_key_triggers:
            return DatabaseStatus(
                "invalid",
                safe_url,
                None,
                revision,
                tables,
                False,
                0,
                "PostgreSQL foreign-key enforcement trigger state changed: "
                f"{bad_foreign_key_triggers}.",
            )

        actual_indexes = {
            str(index_name): (
                str(table_name),
                tuple(str(column) for column in columns),
                bool(is_unique),
                str(predicate) if predicate is not None else None,
                bool(is_valid),
                bool(is_ready),
                bool(is_live),
                str(index_definition),
                int(key_attribute_count),
                int(total_attribute_count),
                bool(has_no_expressions),
                bool(is_immediate),
                str(access_method),
            )
            for (
                index_name,
                table_name,
                is_unique,
                predicate,
                is_valid,
                is_ready,
                is_live,
                index_definition,
                key_attribute_count,
                total_attribute_count,
                has_no_expressions,
                is_immediate,
                access_method,
                columns,
            ) in connection.execute(
                text(
                    """
                    SELECT
                        index_relation.relname,
                        table_relation.relname,
                        index_catalog.indisunique,
                        pg_get_expr(index_catalog.indpred, index_catalog.indrelid),
                        index_catalog.indisvalid,
                        index_catalog.indisready,
                        index_catalog.indislive,
                        pg_get_indexdef(index_catalog.indexrelid),
                        index_catalog.indnkeyatts,
                        index_catalog.indnatts,
                        index_catalog.indexprs IS NULL,
                        index_catalog.indimmediate,
                        access_method.amname,
                        ARRAY(
                            SELECT attribute.attname
                            FROM unnest(index_catalog.indkey) WITH ORDINALITY AS key(attnum, ordinal)
                            JOIN pg_attribute attribute
                              ON attribute.attrelid = index_catalog.indrelid
                             AND attribute.attnum = key.attnum
                            ORDER BY key.ordinal
                        )
                    FROM pg_index index_catalog
                    JOIN pg_class index_relation ON index_relation.oid = index_catalog.indexrelid
                    JOIN pg_class table_relation ON table_relation.oid = index_catalog.indrelid
                    JOIN pg_am access_method ON access_method.oid = index_relation.relam
                    JOIN pg_namespace namespace ON namespace.oid = table_relation.relnamespace
                    WHERE namespace.nspname = :schema
                    """
                ),
                {"schema": POSTGRESQL_SCHEMA},
            )
        }
        bad_indexes = sorted(
            name
            for name, expected in POSTGRESQL_REQUIRED_INDEXES.items()
            if actual_indexes.get(name)
            != (
                *expected,
                True,
                True,
                True,
                "CREATE "
                + ("UNIQUE " if expected[2] else "")
                + f"INDEX {name} ON {POSTGRESQL_SCHEMA}.{expected[0]} USING btree "
                + f"({', '.join(expected[1])})"
                + (f" WHERE {expected[3]}" if expected[3] is not None else ""),
                len(expected[1]),
                len(expected[1]),
                True,
                True,
                "btree",
            )
        )
        if bad_indexes:
            return DatabaseStatus(
                "invalid",
                safe_url,
                None,
                revision,
                tables,
                False,
                0,
                f"PostgreSQL head has missing or changed required indexes: {bad_indexes}.",
            )

        operational_index_inventory = [
            [
                str(index_name),
                str(table_name),
                bool(is_unique),
                str(predicate) if predicate is not None else None,
                bool(is_valid),
                bool(is_ready),
                bool(is_live),
                str(index_definition),
                int(key_attribute_count),
                int(total_attribute_count),
                bool(has_no_expressions),
                bool(is_immediate),
                str(access_method),
                [str(column) for column in columns],
            ]
            for (
                index_name,
                table_name,
                is_unique,
                predicate,
                is_valid,
                is_ready,
                is_live,
                index_definition,
                key_attribute_count,
                total_attribute_count,
                has_no_expressions,
                is_immediate,
                access_method,
                columns,
            ) in connection.execute(
                text(
                    """
                    SELECT
                        index_relation.relname,
                        table_relation.relname,
                        index_catalog.indisunique,
                        pg_get_expr(index_catalog.indpred, index_catalog.indrelid),
                        index_catalog.indisvalid,
                        index_catalog.indisready,
                        index_catalog.indislive,
                        pg_get_indexdef(index_catalog.indexrelid),
                        index_catalog.indnkeyatts,
                        index_catalog.indnatts,
                        index_catalog.indexprs IS NULL,
                        index_catalog.indimmediate,
                        access_method.amname,
                        ARRAY(
                            SELECT attribute.attname
                            FROM unnest(index_catalog.indkey) WITH ORDINALITY
                                AS key(attnum, ordinal)
                            JOIN pg_attribute attribute
                              ON attribute.attrelid = index_catalog.indrelid
                             AND attribute.attnum = key.attnum
                            ORDER BY key.ordinal
                        )
                    FROM pg_index index_catalog
                    JOIN pg_class index_relation
                      ON index_relation.oid = index_catalog.indexrelid
                    JOIN pg_class table_relation
                      ON table_relation.oid = index_catalog.indrelid
                    JOIN pg_am access_method ON access_method.oid = index_relation.relam
                    JOIN pg_namespace namespace
                      ON namespace.oid = table_relation.relnamespace
                    LEFT JOIN pg_constraint constraint_catalog
                      ON constraint_catalog.conindid = index_catalog.indexrelid
                    WHERE namespace.nspname = :schema
                      AND table_relation.relname = ANY(:table_names)
                      AND constraint_catalog.oid IS NULL
                    """
                ),
                {
                    "schema": POSTGRESQL_SCHEMA,
                    "table_names": sorted(POSTGRESQL_OPERATIONAL_TABLES),
                },
            )
        ]
        if (
            _catalog_inventory_sha256(operational_index_inventory)
            != POSTGRESQL_OPERATIONAL_INDEX_INVENTORY_SHA256
        ):
            return DatabaseStatus(
                "invalid",
                safe_url,
                None,
                revision,
                tables,
                False,
                0,
                "PostgreSQL operational index inventory changed.",
            )

        trigger_rows = list(
            connection.execute(
                text(
                    """
                    SELECT
                        trigger_catalog.tgname,
                        table_relation.relname,
                        function_catalog.proname,
                        trigger_catalog.tgtype,
                        ARRAY(
                            SELECT attribute.attname
                            FROM unnest(trigger_catalog.tgattr) WITH ORDINALITY
                                AS trigger_column(attnum, ordinal)
                            JOIN pg_attribute attribute
                              ON attribute.attrelid = trigger_catalog.tgrelid
                             AND attribute.attnum = trigger_column.attnum
                            ORDER BY trigger_column.ordinal
                        ),
                        trigger_catalog.tgenabled,
                        trigger_catalog.tgqual IS NULL
                    FROM pg_trigger trigger_catalog
                    JOIN pg_class table_relation
                      ON table_relation.oid = trigger_catalog.tgrelid
                    JOIN pg_namespace namespace
                      ON namespace.oid = table_relation.relnamespace
                    JOIN pg_proc function_catalog
                      ON function_catalog.oid = trigger_catalog.tgfoid
                    WHERE namespace.nspname = :schema
                      AND NOT trigger_catalog.tgisinternal
                    """
                ),
                {
                    "schema": POSTGRESQL_SCHEMA,
                },
            )
        )
        actual_triggers: dict[str, tuple[object, ...]] = {}
        duplicate_triggers: set[str] = set()
        for name, table_name, function_name, trigger_type, columns, enabled, no_when in trigger_rows:
            name = str(name)
            if name in actual_triggers:
                duplicate_triggers.add(name)
            actual_triggers[name] = (
                str(table_name),
                str(function_name),
                int(trigger_type),
                tuple(str(column) for column in columns),
                str(enabled),
                bool(no_when),
            )
        bad_triggers = sorted(
            name
            for name, expected in POSTGRESQL_REQUIRED_TRIGGER_BINDINGS.items()
            if actual_triggers.get(name) != (*expected, "O", True)
        )
        bad_triggers.extend(sorted(duplicate_triggers))
        bad_triggers.extend(
            sorted(
                name
                for name in set(actual_triggers) - POSTGRESQL_REQUIRED_TRIGGERS
                if actual_triggers[name][0] not in POSTGRESQL_OPERATIONAL_TABLES
            )
        )
        if bad_triggers:
            return DatabaseStatus(
                "invalid",
                safe_url,
                None,
                revision,
                tables,
                False,
                0,
                "PostgreSQL head has missing, disabled, or changed required triggers: "
                f"{sorted(set(bad_triggers))}.",
            )
        operational_trigger_inventory = [
            [
                str(name),
                str(table_name),
                str(function_name),
                int(trigger_type),
                [str(column) for column in columns],
                str(enabled),
                bool(no_when),
            ]
            for (
                name,
                table_name,
                function_name,
                trigger_type,
                columns,
                enabled,
                no_when,
            ) in trigger_rows
            if str(table_name) in POSTGRESQL_OPERATIONAL_TABLES
        ]
        if (
            _catalog_inventory_sha256(operational_trigger_inventory)
            != POSTGRESQL_OPERATIONAL_TRIGGER_INVENTORY_SHA256
        ):
            return DatabaseStatus(
                "invalid",
                safe_url,
                None,
                revision,
                tables,
                False,
                0,
                "PostgreSQL operational trigger inventory changed.",
            )

        function_rows = list(
            connection.execute(
                text(
                    """
                    SELECT
                        p.proname,
                        p.proconfig,
                        EXISTS (
                            SELECT 1
                            FROM aclexplode(
                                COALESCE(
                                    p.proacl,
                                    acldefault('f', p.proowner)
                                )
                            ) AS privilege
                            WHERE privilege.grantee = 0
                              AND privilege.privilege_type = 'EXECUTE'
                        ),
                        p.prosrc,
                        language.lanname,
                        p.prosecdef,
                        p.provolatile,
                        pg_get_function_result(p.oid),
                        p.pronargs,
                        p.prokind,
                        pg_get_userbyid(p.proowner)
                    FROM pg_proc p
                    JOIN pg_namespace n ON n.oid = p.pronamespace
                    JOIN pg_language language ON language.oid = p.prolang
                    WHERE n.nspname = :schema
                      AND p.proname = ANY(:function_names)
                    """
                ),
                {
                    "schema": POSTGRESQL_SCHEMA,
                    "function_names": sorted(POSTGRESQL_REQUIRED_FUNCTIONS),
                },
            )
        )
        guard_function_security: dict[str, tuple[object, ...]] = {}
        duplicate_functions: set[str] = set()
        for (
            function_name,
            config,
            public_execute,
            source,
            language,
            security_definer,
            volatility,
            result_type,
            argument_count,
            function_kind,
            function_owner,
        ) in function_rows:
            function_name = str(function_name)
            if function_name in guard_function_security:
                duplicate_functions.add(function_name)
            guard_function_security[function_name] = (
                tuple(config or ()),
                bool(public_execute),
                hashlib.sha256(str(source).encode("utf-8")).hexdigest(),
                str(language),
                bool(security_definer),
                str(volatility),
                str(result_type),
                int(argument_count),
                str(function_kind),
                str(function_owner),
            )
        bad_function_security = sorted(
            function_name
            for function_name in POSTGRESQL_REQUIRED_FUNCTIONS
            if guard_function_security.get(function_name)
            != (
                ("search_path=pg_catalog, public",),
                False,
                POSTGRESQL_REQUIRED_FUNCTION_FINGERPRINTS[function_name],
                "plpgsql",
                False,
                "v",
                "trigger",
                0,
                "f",
                table_owner,
            )
        )
        bad_function_security.extend(sorted(duplicate_functions))
        if bad_function_security:
            return DatabaseStatus(
                "invalid",
                safe_url,
                None,
                revision,
                tables,
                False,
                0,
                "PostgreSQL guard function body/signature/search_path/EXECUTE policy mismatch: "
                f"{sorted(set(bad_function_security))}.",
            )

        expected_columns: dict[tuple[str, str], tuple[str, bool, str | None, str, str]] = {
            ("alembic_version", "version_num"): (
                "character varying(128)",
                False,
                None,
                "",
                "",
            )
        }
        for table_name in POSTGRESQL_REQUIRED_TABLES:
            model_table = Base.metadata.tables[table_name]
            for column in model_table.columns:
                compiled_type = str(
                    column.type.compile(dialect=connection.dialect)
                ).lower()
                if compiled_type.startswith("varchar("):
                    compiled_type = "character varying" + compiled_type.removeprefix("varchar")
                elif compiled_type == "float":
                    compiled_type = "double precision"
                expected_nullable = (
                    True
                    if (table_name, column.name)
                    in POSTGRESQL_LEGACY_NULLABLE_TIMESTAMP_COLUMNS
                    else bool(column.nullable)
                )
                expected_columns[(table_name, column.name)] = (
                    compiled_type,
                    expected_nullable,
                    POSTGRESQL_REQUIRED_COLUMN_DEFAULTS.get((table_name, column.name)),
                    "",
                    "",
                )
        actual_columns = {
            (str(table_name), str(column_name)): (
                str(type_name).lower(),
                not bool(not_null),
                str(default_expression) if default_expression is not None else None,
                str(generated_kind),
                str(identity_kind),
            )
            for (
                table_name,
                column_name,
                type_name,
                not_null,
                default_expression,
                generated_kind,
                identity_kind,
            ) in connection.execute(
                text(
                    """
                    SELECT
                        table_relation.relname,
                        attribute.attname,
                        format_type(attribute.atttypid, attribute.atttypmod),
                        attribute.attnotnull,
                        pg_get_expr(column_default.adbin, column_default.adrelid),
                        attribute.attgenerated,
                        attribute.attidentity
                    FROM pg_attribute attribute
                    JOIN pg_class table_relation
                      ON table_relation.oid = attribute.attrelid
                    JOIN pg_namespace namespace
                      ON namespace.oid = table_relation.relnamespace
                    LEFT JOIN pg_attrdef column_default
                      ON column_default.adrelid = attribute.attrelid
                     AND column_default.adnum = attribute.attnum
                    WHERE namespace.nspname = :schema
                      AND table_relation.relkind = 'r'
                      AND attribute.attnum > 0
                      AND NOT attribute.attisdropped
                    """
                ),
                {"schema": POSTGRESQL_SCHEMA},
            )
        }
        bad_columns = sorted(
            set(expected_columns) ^ set(actual_columns)
            | {
                column
                for column, expected in expected_columns.items()
                if actual_columns.get(column) != expected
            }
        )
        if bad_columns:
            return DatabaseStatus(
                "invalid",
                safe_url,
                None,
                revision,
                tables,
                False,
                0,
                "PostgreSQL head column type/nullability/default/generated/identity "
                f"inventory mismatch: {bad_columns}.",
            )

        column_types = {
            (str(table_name), str(column_name)): str(data_type)
            for table_name, column_name, data_type in connection.execute(
                text(
                    """
                    SELECT table_name, column_name, data_type
                    FROM information_schema.columns
                    WHERE table_schema = :schema
                    """
                ),
                {"schema": POSTGRESQL_SCHEMA},
            )
        }
        bad_json = sorted(
            column for column in POSTGRESQL_JSONB_COLUMNS if column_types.get(column) != "jsonb"
        )
        bad_time = sorted(
            column
            for column in POSTGRESQL_TIMESTAMPTZ_COLUMNS
            if column_types.get(column) != "timestamp with time zone"
        )
        if bad_json or bad_time:
            return DatabaseStatus(
                "invalid",
                safe_url,
                None,
                revision,
                tables,
                False,
                0,
                f"PostgreSQL native type inventory mismatch (jsonb={bad_json}, timestamptz={bad_time}).",
            )
        return DatabaseStatus("current", safe_url, None, revision, tables, True, 0)
    if not _known_revision(revision):
        return DatabaseStatus(
            "invalid",
            safe_url,
            None,
            revision,
            tables,
            True,
            0,
            "PostgreSQL Alembic revision is not part of the ledger's serialized chain.",
        )
    return DatabaseStatus(
        "versioned_but_not_head",
        safe_url,
        None,
        revision,
        tables,
        True,
        0,
        "PostgreSQL schema is on a known prior revision; an explicit expected-revision upgrade is required.",
    )


def _inspect_postgresql_database(database_url: str) -> DatabaseStatus:
    safe_url = redacted_database_url(database_url)
    try:
        engine = create_engine(database_url, poolclass=NullPool, future=True)
        with engine.connect() as connection:
            return _postgresql_status_from_connection(connection, database_url=database_url)
    except Exception as exc:
        # Never place driver/provider exception text in a durable receipt: it
        # can echo the full DSN, socket path, TLS key, or provider routing data.
        return DatabaseStatus(
            "unavailable",
            safe_url,
            None,
            None,
            (),
            False,
            0,
            f"PostgreSQL inspection failed closed ({type(exc).__name__}); no migration was attempted.",
        )


def inspect_database(database_url: str) -> DatabaseStatus:
    """Inspect SQLite read-only or PostgreSQL fail-closed without schema writes."""
    if is_postgresql_url(database_url):
        return _inspect_postgresql_database(database_url)
    try:
        backend = make_url(database_url).get_backend_name()
    except Exception as exc:
        raise DatabaseMigrationError("Database URL is invalid or unsupported.") from exc
    if backend != "sqlite":
        raise DatabaseMigrationError("Only SQLite and PostgreSQL database URLs are supported.")
    return _inspect_sqlite_database(database_url)


def _backup_sqlite(source: Path, destination: Path) -> None:
    """Take a checkpoint-aware SQLite backup rather than copying database bytes."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise DatabaseMigrationError(f"Backup destination already exists: {destination}")
    with _read_only_connection(source) as source_connection, sqlite3.connect(destination) as destination_connection:
        source_connection.backup(destination_connection)


def _table_counts(path: Path, tables: tuple[str, ...]) -> dict[str, int]:
    with _read_only_connection(path) as connection:
        return {
            table: int(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
            for table in tables
        }


def _verified_backup(source: Path, backup_dir: Path) -> Path:
    backup_dir = backup_dir.expanduser().resolve()
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = backup_dir / f"{source.stem}.pre-migration.{_sha256(source)[:16]}.db"
    _backup_sqlite(source, backup)
    if _sha256(source) != _sha256(backup):
        # SQLite backups can legitimately arrange pages differently.  The
        # logical checks below are the authoritative comparison, while this
        # condition catches a truncated/corrupt output before staging begins.
        backup_status = inspect_database(f"sqlite:///{backup}")
        source_status = inspect_database(f"sqlite:///{source}")
        if (
            not backup_status.integrity_ok
            or backup_status.foreign_key_violations
            or backup_status.tables != source_status.tables
            or _table_counts(backup, backup_status.tables) != _table_counts(source, source_status.tables)
        ):
            raise DatabaseMigrationError("SQLite backup verification failed; source database was not migrated.")
    return backup


def _upgrade_empty_database(database_url: str) -> None:
    command.upgrade(_alembic_config(database_url), "head")


def _upgrade_postgresql_under_lock(
    database_url: str,
    *,
    expected_revision: str | None,
    allow_empty: bool,
) -> DatabaseStatus:
    """Upgrade one explicit PostgreSQL target under a session advisory lock."""
    safe_url = redacted_database_url(database_url)
    try:
        engine = create_engine(database_url, poolclass=NullPool, future=True)
        with engine.connect() as connection:
            acquired = bool(
                connection.execute(
                    text("SELECT pg_try_advisory_lock(:lock_key)"),
                    {"lock_key": POSTGRESQL_MIGRATION_LOCK_KEY},
                ).scalar_one()
            )
            connection.commit()
            if not acquired:
                raise DatabaseMigrationError(
                    "Another PostgreSQL ledger migration holds the advisory lock; no migration was attempted."
                )
            try:
                status = _postgresql_status_from_connection(connection, database_url=database_url)
                connection.commit()
                if status.kind == "current":
                    return status
                if status.kind == "empty":
                    if not allow_empty:
                        raise DatabaseMigrationError(
                            "Expected a known prior PostgreSQL revision, but the target schema is empty."
                        )
                elif status.kind == "versioned_but_not_head":
                    if expected_revision is None:
                        raise DatabaseMigrationError(
                            "A populated PostgreSQL upgrade requires an exact expected_revision."
                        )
                    if status.revision != expected_revision:
                        raise DatabaseMigrationError(
                            "PostgreSQL revision changed since preflight; no migration was attempted."
                        )
                else:
                    raise DatabaseMigrationError(
                        "PostgreSQL target is not eligible for a forward upgrade: "
                        f"{status.kind}: {status.detail or 'no additional detail'}"
                    )

                config = _alembic_config(database_url)
                config.attributes["connection"] = connection
                migration_transaction = connection.begin()
                try:
                    # Alembic participates in this caller-owned transaction;
                    # the exact head inventory is inspected before commit so a
                    # forged/stale prior schema cannot leave a partial head.
                    command.upgrade(config, "head")
                    upgraded = _postgresql_status_from_connection(
                        connection, database_url=database_url
                    )
                    if upgraded.kind != "current":
                        raise DatabaseMigrationError(
                            "PostgreSQL migration did not reach the exact ledger head; "
                            "the migration transaction was rolled back."
                        )
                    migration_transaction.commit()
                except Exception:
                    if migration_transaction.is_active:
                        migration_transaction.rollback()
                    raise
                return upgraded
            finally:
                # Session advisory locks survive rollback. Clear a failed
                # transaction first, then release the exact lock before the
                # NullPool connection closes.
                if connection.in_transaction():
                    connection.rollback()
                connection.execute(
                    text("SELECT pg_advisory_unlock(:lock_key)"),
                    {"lock_key": POSTGRESQL_MIGRATION_LOCK_KEY},
                )
                connection.commit()
    except DatabaseMigrationError:
        raise
    except Exception as exc:
        raise DatabaseMigrationError(
            f"PostgreSQL migration failed closed for {safe_url} ({type(exc).__name__}); "
            "no success receipt was emitted."
        ) from exc


def upgrade_postgresql_database(
    database_url: str,
    *,
    expected_revision: str,
) -> DatabaseStatus:
    """Explicitly advance one known PostgreSQL revision to head.

    Unlike SQLite copy migration, PostgreSQL upgrades are transactional and
    serialized in-place. The caller must pass the exact preflight revision;
    backup/restore evidence remains an operator gate outside this helper.
    """
    if not is_postgresql_url(database_url):
        raise DatabaseMigrationError("upgrade_postgresql_database requires a PostgreSQL URL.")
    if not expected_revision or not _known_revision(expected_revision):
        raise DatabaseMigrationError("expected_revision must name a known ledger revision.")
    return _upgrade_postgresql_under_lock(
        database_url,
        expected_revision=expected_revision,
        allow_empty=False,
    )


def initialize_database(database_url: str) -> DatabaseStatus:
    """Create only an empty database; never auto-upgrade populated evidence."""
    if is_postgresql_url(database_url):
        return _upgrade_postgresql_under_lock(
            database_url,
            expected_revision=None,
            allow_empty=True,
        )
    status = inspect_database(database_url)
    if status.kind == "current":
        return status
    if status.kind != "empty":
        raise DatabaseMigrationError(
            "init-db only initializes an empty database. Existing databases must pass "
            "`benchmark-ledger db preflight` and be migrated as a verified copy; "
            f"observed {status.kind}: {status.detail or 'no additional detail'}"
        )
    _upgrade_empty_database(database_url)
    upgraded = inspect_database(database_url)
    if upgraded.kind != "current":
        raise DatabaseMigrationError(
            f"Fresh database did not reach the migration head: {upgraded.kind} {upgraded.detail or ''}".strip()
        )
    return upgraded


def _stage_path(database_path: Path) -> Path:
    return database_path.with_name(f".{database_path.name}.migrating-{uuid4().hex}")


def migrate_legacy_copy(database_url: str, *, backup_dir: Path) -> MigrationReceipt:
    """Migrate a validated legacy or known-versioned *copy* atomically.

    Callers must pass a disposable copy, never the production/evidence original.
    The function nevertheless creates an independent SQLite backup and leaves
    the supplied file untouched until the staged upgrade reaches head and its
    integrity checks pass.
    """
    source_status = inspect_database(database_url)
    if source_status.kind == "legacy_unversioned":
        from_revision = _LEGACY_BASELINE
    elif supports_copy_migration(source_status):
        assert source_status.revision is not None
        from_revision = source_status.revision
    else:
        raise DatabaseMigrationError(
            "Only an exact, integrity-clean legacy baseline or known prior ledger revision "
            "can be migrated as a copy; "
            f"observed {source_status.kind}: {source_status.detail or 'no additional detail'}"
        )
    database_path = _sqlite_path(database_url)
    for suffix in ("-wal", "-shm", "-journal"):
        if database_path.with_name(database_path.name + suffix).exists():
            raise DatabaseMigrationError(
                "Refusing to atomically replace a database with SQLite sidecar files present. "
                "Close all writers and create a fresh copy before rehearsal."
            )

    input_hash = _sha256(database_path)
    backup_path = _verified_backup(database_path, backup_dir)
    staged_path = _stage_path(database_path)
    try:
        _backup_sqlite(database_path, staged_path)
        staged_url = f"sqlite:///{staged_path}"
        staged_status = inspect_database(staged_url)
        if (
            staged_status.kind != source_status.kind
            or staged_status.revision != source_status.revision
        ):
            raise DatabaseMigrationError(
                "Staged SQLite backup did not retain the validated source state; source was not replaced."
            )
        config = _alembic_config(staged_url)
        if source_status.kind == "legacy_unversioned":
            command.stamp(config, _LEGACY_BASELINE)
        command.upgrade(config, "head")
        upgraded = inspect_database(staged_url)
        if upgraded.kind != "current" or not upgraded.integrity_ok or upgraded.foreign_key_violations:
            raise DatabaseMigrationError(
                "Staged migration failed postflight validation; source copy was not replaced."
            )
        os.replace(staged_path, database_path)
        output_status = inspect_database(database_url)
        if output_status.kind != "current" or not output_status.integrity_ok or output_status.foreign_key_violations:
            raise DatabaseMigrationError(
                "Atomic replacement completed but postflight validation failed; restore the verified backup."
            )
        return MigrationReceipt(
            database_path=str(database_path),
            backup_path=str(backup_path),
            input_sha256=input_hash,
            output_sha256=_sha256(database_path),
            from_revision=from_revision,
            to_revision=head_revision(),
            integrity_ok=output_status.integrity_ok,
            foreign_key_violations=output_status.foreign_key_violations,
        )
    except Exception:
        # The original path is unchanged until os.replace.  Preserve the
        # verified backup and remove only the disposable staged file.
        if staged_path.exists():
            staged_path.unlink()
        raise
