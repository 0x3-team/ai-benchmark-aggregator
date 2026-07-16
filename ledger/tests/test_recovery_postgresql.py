"""PostgreSQL 16 target acceptance for provider-neutral DATA-10 recovery.

Unit tests below never open PostgreSQL.  Two real-service nodes are opt-in
through two independent triplets of explicit, distinct, disposable database
URLs.  The recovery node consumes two fresh targets; the adversary node leaves
its publication and large object intact.  The parent acceptance run owns all
cluster-level cleanup after evidence capture.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from app.backup import (
    LocalRecoveryStore,
    RecoveryDomain,
    create_checkpoint_with_driver,
    restore_checkpoint_with_driver,
    validate_checkpoint_manifest,
    validate_restore_receipt,
)
from app.backup.errors import (
    RecoveryCancelled,
    RecoveryIntegrityError,
    RecoveryPartialFailure,
    RecoveryTargetError,
    UnsupportedRecoveryArtifact,
)
from app.backup.postgresql_driver import (
    PG_DUMP_PATH,
    PG_RESTORE_PATH,
    PostgreSQLBackupRestoreDriver,
    PostgreSQLConnectionSpec,
    _CANONICAL_EMPTY_DATABASE_SCOPE,
    _DATABASE_SCOPE_FIELD_NAMES,
    _DATABASE_SCOPE_SQL,
    _DatabaseFacts,
    _StrictHeadProof,
    _archive_restore_argv,
    _assert_safe_backup_source_scope,
    _canonical_database_identity_sha256,
    _consumed_target_marker,
    _consume_fresh_target,
    _filter_public_schema_toc,
    _normalize_schema_dump,
    _run_pg_tool,
    _validate_public_relation_rows,
)
from app.backup.protocols import RelationalBackupArtifact
from app.backup.semantic_inspection import LINEAGE_TABLES, expected_head_columns
from app.db import models, operational_repositories, repositories
from app.db.migrate import inspect_database
from app.db.postgresql import (
    POSTGRESQL_OPERATIONAL_CONSTRAINT_INVENTORY_SHA256,
    POSTGRESQL_OPERATIONAL_INDEX_INVENTORY_SHA256,
    POSTGRESQL_REQUIRED_CONSTRAINTS,
    POSTGRESQL_REQUIRED_CONSTRAINT_TABLES,
    POSTGRESQL_REQUIRED_INDEXES,
)
from app.schemas.operations_contracts import (
    contract_self_digest as operations_self_digest,
    derive_cycle_id,
)
from app.schemas.recovery_contracts import (
    canonical_recovery_json,
    parse_canonical_recovery_bytes,
    recovery_contract_digest,
)
from app.storage.base import StorageObjectKind, compute_content_hash
from app.storage.local import LocalSnapshotStorage


_SOURCE_ENV = "TEST_POSTGRESQL_RECOVERY_SOURCE_URL"
_INSPECTION_ENV = "TEST_POSTGRESQL_RECOVERY_INSPECTION_URL"
_RESTORE_ENV = "TEST_POSTGRESQL_RECOVERY_RESTORE_URL"
_ADVERSARY_SOURCE_ENV = "TEST_POSTGRESQL_RECOVERY_ADVERSARY_SOURCE_URL"
_ADVERSARY_PUBLICATION_ENV = (
    "TEST_POSTGRESQL_RECOVERY_ADVERSARY_PUBLICATION_URL"
)
_ADVERSARY_LARGE_OBJECT_ENV = (
    "TEST_POSTGRESQL_RECOVERY_ADVERSARY_LARGE_OBJECT_URL"
)
_RECOVERY_ENV_NAMES = (_SOURCE_ENV, _INSPECTION_ENV, _RESTORE_ENV)
_ADVERSARY_ENV_NAMES = (
    _ADVERSARY_SOURCE_ENV,
    _ADVERSARY_PUBLICATION_ENV,
    _ADVERSARY_LARGE_OBJECT_ENV,
)
_UTC = timezone.utc
_ANCHOR = datetime(2026, 1, 1, tzinfo=_UTC)
_CADENCE_SECONDS = 43_200
_SNAPSHOT_RAW_BYTES = (
    b'{"fixture":"data10-postgresql-recovery","score_raw":"91.20"}'
)


def _toc(*entries: str) -> bytes:
    lines = [
        "; PostgreSQL database dump",
        ";",
        *entries,
        "",
    ]
    return "\n".join(lines).encode("utf-8")


def _canonical_database_scope_row() -> tuple[object, ...]:
    return tuple(
        getattr(_CANONICAL_EMPTY_DATABASE_SCOPE, name)
        for name in _DATABASE_SCOPE_FIELD_NAMES
    )


def _unit_postgresql_artifact() -> RelationalBackupArtifact:
    return RelationalBackupArtifact(
        driver_id="postgresql-pg-tools",
        driver_version="1.0.0",
        engine_name="postgresql",
        engine_version="16.10",
        tool_name="pg_dump-pg_restore",
        tool_version="16.10",
        artifact_type="postgresql_database",
        format="postgresql_custom_archive",
        format_version="pg_dump-custom-v1",
        source_database_identity_sha256="b" * 64,
        raw_bytes=b"PGDMP unit fixture",
    )


def _recovery_authority() -> dict[str, object]:
    return {
        "classification": "recovery_evidence_only",
        "certifiesSources": False,
        "authorizesCapture": False,
        "authorizesPublication": False,
        "frontendLoadable": False,
        "authorizesCutover": False,
        "provesProviderIndependence": False,
        "provesProductionRpoRto": False,
    }


class _TwoSampleUtcClock:
    def __init__(self, started: datetime, finished: datetime) -> None:
        self._observations = (started, finished)
        self.calls = 0

    def __call__(self) -> datetime:
        if self.calls >= len(self._observations):
            raise AssertionError("restore sampled its trusted UTC clock more than twice")
        observation = self._observations[self.calls]
        self.calls += 1
        return observation


def test_connection_spec_builds_a_minimal_explicit_libpq_environment() -> None:
    spec = PostgreSQLConnectionSpec.from_url(
        "postgresql+psycopg://ledger_user:very-secret@db.example.test:5433/ledger_restore"
        "?sslmode=verify-full&sslrootcert=%2Fprivate%2Fca.pem"
    )

    environment = spec.libpq_environment(application_name="ledger-recovery-test")

    assert environment == {
        "LANG": "C",
        "LC_ALL": "C",
        "PGAPPNAME": "ledger-recovery-test",
        "PGCONNECT_TIMEOUT": "10",
        "PGDATABASE": "ledger_restore",
        "PGHOST": "db.example.test",
        "PGPASSWORD": "very-secret",
        "PGPORT": "5433",
        "PGSSLMODE": "verify-full",
        "PGSSLROOTCERT": "/private/ca.pem",
        "PGUSER": "ledger_user",
        "TZ": "UTC",
    }
    assert "PATH" not in environment
    assert "PGOPTIONS" not in environment
    assert "PGSERVICE" not in environment
    assert "PGSERVICEFILE" not in environment
    assert "DATABASE_URL" not in environment
    assert "very-secret" not in repr(spec)


@pytest.mark.parametrize(
    "query",
    [
        "service=provider",
        "servicefile=%2Fprivate%2Fservice.conf",
        "options=-c%20search_path%3Dattacker",
        "passfile=%2Fprivate%2Fpgpass",
        "target_session_attrs=read-write",
    ],
)
def test_connection_spec_rejects_implicit_or_unreviewed_libpq_inputs(query: str) -> None:
    with pytest.raises(RecoveryTargetError, match="unsupported PostgreSQL connection option"):
        PostgreSQLConnectionSpec.from_url(
            f"postgresql+psycopg://ledger_user@/ledger_disposable?"
            f"host=%2Ftmp%2Fpg&port=55441&{query}"
        )


def test_connection_spec_requires_explicit_network_tls_and_fixed_driver() -> None:
    with pytest.raises(RecoveryTargetError, match="verify-full"):
        PostgreSQLConnectionSpec.from_url(
            "postgresql+psycopg://ledger_user@db.example.test:5432/ledger_restore"
        )
    with pytest.raises(RecoveryTargetError, match="psycopg"):
        PostgreSQLConnectionSpec.from_url(
            "postgresql://ledger_user@/ledger_restore?host=%2Ftmp%2Fpg&port=5432"
        )


def test_direct_connection_spec_cannot_bypass_validation() -> None:
    with pytest.raises(RecoveryTargetError):
        PostgreSQLConnectionSpec(
            database="ledger\nsubstituted",
            user="ledger_user",
            host="/tmp/pg",
            port=5432,
        )
    with pytest.raises(RecoveryTargetError, match="verify-full"):
        PostgreSQLConnectionSpec(
            database="ledger",
            user="ledger_user",
            host="db.example.test",
            port=5432,
        )


def test_psycopg_connection_path_refuses_ambient_pg_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = PostgreSQLConnectionSpec.from_url(
        "postgresql+psycopg://ledger_user@/ledger_disposable"
        "?host=%2Ftmp%2Fpg&port=55441"
    )
    monkeypatch.setenv("PGOPTIONS", "-c search_path=attacker")

    with pytest.raises(RecoveryTargetError, match="Ambient PG"):
        spec.connection_kwargs(application_name="data10-unit")
    assert "PGOPTIONS" not in spec.libpq_environment(application_name="data10-unit")

    monkeypatch.delenv("PGOPTIONS")
    kwargs = spec.connection_kwargs(application_name="data10-unit")
    assert kwargs["connect_timeout"] == 10
    assert kwargs["options"] == (
        "-c statement_timeout=60000 -c lock_timeout=5000 "
        "-c idle_in_transaction_session_timeout=60000"
    )


def test_database_identity_hash_is_exactly_the_two_immutable_catalog_values() -> None:
    expected = hashlib.sha256(
        canonical_recovery_json(
            {"databaseOid": "16391", "systemIdentifier": "7465029242204061530"}
        ).encode("ascii")
    ).hexdigest()

    assert (
        _canonical_database_identity_sha256("7465029242204061530", "16391")
        == expected
    )
    assert (
        _canonical_database_identity_sha256("7465029242204061530", "16392")
        != expected
    )


def test_consumed_target_marker_binds_target_id_and_archive_digest() -> None:
    digest = "a" * 64
    marker = _consumed_target_marker("inspection-target-01", digest)

    assert marker == canonical_recovery_json(
        {
            "archiveSha256": digest,
            "kind": "ai_benchmark_recovery_consumed_v1",
            "targetId": "inspection-target-01",
        }
    )
    assert _consumed_target_marker("inspection-target-02", digest) != marker
    assert _consumed_target_marker("inspection-target-01", "b" * 64) != marker
    with pytest.raises(RecoveryTargetError):
        _consumed_target_marker("Not Canonical", digest)


def test_shared_database_comment_refuses_consumed_target_before_writing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = _consumed_target_marker("already-consumed", "a" * 64)
    statements: list[str] = []

    class FakeResult:
        def __init__(self, row: tuple[object, ...]) -> None:
            self._row = row

        def fetchone(self) -> tuple[object, ...]:
            return self._row

    class FakeConnection:
        def execute(self, statement: object) -> FakeResult:
            rendered = str(statement)
            statements.append(rendered)
            if "pg_control_system" in rendered:
                assert "shobj_description(database_catalog.oid, 'pg_database')" in rendered
                return FakeResult(
                    (
                        "ledger_disposable_consumed",
                        "7465029242204061530",
                        "16391",
                        "160010",
                        marker,
                        "ledger_owner",
                        "ledger_owner",
                        False,
                    )
                )
            if "WITH target_namespace" in rendered:
                return FakeResult((0,))
            if "nspname <> 'public'" in rendered:
                return FakeResult((0,))
            if "WITH current_database_catalog" in rendered:
                return FakeResult(_canonical_database_scope_row())
            if "nspname = 'public'" in rendered and "COUNT(*)" in rendered:
                return FakeResult((1,))
            raise AssertionError(f"unexpected catalog statement: {rendered}")

        def close(self) -> None:
            return None

    connection = FakeConnection()
    monkeypatch.setattr(
        "app.backup.postgresql_driver._open_connection",
        lambda *_args, **_kwargs: connection,
    )
    spec = PostgreSQLConnectionSpec.from_url(
        "postgresql+psycopg://ledger_owner@/ledger_disposable_consumed"
        "?host=%2Ftmp%2Fpg&port=55441"
    )
    artifact = _unit_postgresql_artifact()

    with pytest.raises(RecoveryTargetError, match="already consumed"):
        _consume_fresh_target(spec, artifact=artifact, target_id="must-not-write")

    assert len(statements) == 5
    assert not any(statement.lstrip().startswith("COMMENT") for statement in statements)


def test_database_scope_census_names_every_reviewed_no_namespace_surface() -> None:
    for catalog in (
        "pg_database",
        "pg_namespace",
        "aclexplode",
        "pg_extension",
        "pg_language",
        "pg_publication",
        "pg_publication_rel",
        "pg_publication_namespace",
        "pg_subscription",
        "pg_subscription_rel",
        "pg_event_trigger",
        "pg_largeobject_metadata",
        "pg_largeobject",
        "pg_db_role_setting",
        "pg_foreign_data_wrapper",
        "pg_foreign_server",
        "pg_user_mapping",
        "pg_default_acl",
        "pg_seclabel",
        "pg_shseclabel",
        "pg_transform",
        "pg_cast",
        "pg_am",
        "pg_policy",
        "pg_rewrite",
        "pg_prepared_xacts",
        "pg_replication_slots",
    ):
        assert catalog in _DATABASE_SCOPE_SQL
    assert "pg_database_owner" in _DATABASE_SCOPE_SQL
    assert "plpgsql" in _DATABASE_SCOPE_SQL
    assert "oid >= 16384" in _DATABASE_SCOPE_SQL
    assert _CANONICAL_EMPTY_DATABASE_SCOPE.is_canonical_empty


@pytest.mark.parametrize("field_name", _DATABASE_SCOPE_FIELD_NAMES)
def test_each_database_scope_fact_rejects_before_durable_marker(
    monkeypatch: pytest.MonkeyPatch,
    field_name: str,
) -> None:
    clean_value = getattr(_CANONICAL_EMPTY_DATABASE_SCOPE, field_name)
    if type(clean_value) is bool:
        contaminated_value: bool | int = not clean_value
    elif field_name == "database_connection_limit":
        contaminated_value = 0
    else:
        contaminated_value = clean_value + 1
    contaminated_scope = replace(
        _CANONICAL_EMPTY_DATABASE_SCOPE,
        **{field_name: contaminated_value},
    )
    assert contaminated_scope.fingerprint_sha256 != (
        _CANONICAL_EMPTY_DATABASE_SCOPE.fingerprint_sha256
    )
    facts = _DatabaseFacts(
        database_name="ledger_disposable_contaminated",
        identity_sha256="c" * 64,
        engine_version="16.10",
        database_comment=None,
        database_owner="ledger_owner",
        current_user="ledger_owner",
        is_template=False,
        public_object_count=0,
        extra_non_system_schema_count=0,
        database_scope=contaminated_scope,
    )
    statements: list[object] = []

    class NoWriteConnection:
        def execute(self, statement: object) -> None:
            statements.append(statement)
            raise AssertionError("contaminated target reached durable marker write")

        def close(self) -> None:
            return None

    monkeypatch.setattr(
        "app.backup.postgresql_driver._open_connection",
        lambda *_args, **_kwargs: NoWriteConnection(),
    )
    monkeypatch.setattr(
        "app.backup.postgresql_driver._database_facts",
        lambda _connection: facts,
    )
    spec = PostgreSQLConnectionSpec.from_url(
        "postgresql+psycopg://ledger_owner@/ledger_disposable_contaminated"
        "?host=%2Ftmp%2Fpg&port=55441"
    )

    with pytest.raises(RecoveryTargetError, match="database-scoped state"):
        _consume_fresh_target(
            spec,
            artifact=_unit_postgresql_artifact(),
            target_id="must-reject-contamination",
        )

    assert statements == []


def test_backup_source_allows_provider_acl_routing_but_not_omitted_state() -> None:
    provider_specific_source = replace(
        _CANONICAL_EMPTY_DATABASE_SCOPE,
        database_acl_is_null=False,
        database_allows_connections=False,
        database_connection_limit=25,
        public_schema_acl_is_canonical=False,
    )

    assert not provider_specific_source.is_canonical_empty
    assert provider_specific_source.is_safe_backup_source
    _assert_safe_backup_source_scope(
        _DatabaseFacts(
            database_name="source",
            identity_sha256="d" * 64,
            engine_version="16.10",
            database_comment=None,
            database_owner="provider_owner",
            current_user="provider_owner",
            is_template=False,
            public_object_count=1,
            extra_non_system_schema_count=0,
            database_scope=provider_specific_source,
        )
    )
    for contaminated_source in (
        replace(provider_specific_source, database_role_setting_count=1),
        replace(provider_specific_source, publication_count=1),
        replace(provider_specific_source, large_object_count=1),
    ):
        assert not contaminated_source.is_safe_backup_source
        with pytest.raises(RecoveryTargetError, match="omitted"):
            _assert_safe_backup_source_scope(
                _DatabaseFacts(
                    database_name="source",
                    identity_sha256="d" * 64,
                    engine_version="16.10",
                    database_comment=None,
                    database_owner="provider_owner",
                    current_user="provider_owner",
                    is_template=False,
                    public_object_count=1,
                    extra_non_system_schema_count=0,
                    database_scope=contaminated_source,
                )
            )


def test_archive_toc_filter_omits_exactly_public_schema_and_retains_everything_else() -> None:
    raw = _toc(
        "6; 2615 2200 SCHEMA - public pg_database_owner",
        "215; 1259 18001 TABLE public alembic_version source_owner",
        "4210; 0 18001 TABLE DATA public alembic_version source_owner",
    )

    filtered = _filter_public_schema_toc(raw)

    assert b"SCHEMA - public" not in filtered
    assert b"TABLE public alembic_version" in filtered
    assert b"TABLE DATA public alembic_version" in filtered
    assert len(filtered.splitlines()) == len(raw.splitlines()) - 1


@pytest.mark.parametrize(
    "entries",
    [
        (
            "215; 1259 18001 TABLE public alembic_version source_owner",
            "4210; 0 18001 TABLE DATA public alembic_version source_owner",
        ),
        (
            "6; 2615 2200 SCHEMA - public pg_database_owner",
            "7; 2615 2200 SCHEMA - public pg_database_owner",
            "215; 1259 18001 TABLE public alembic_version source_owner",
            "4210; 0 18001 TABLE DATA public alembic_version source_owner",
        ),
        (
            "6; 2615 2200 SCHEMA - public pg_database_owner",
            "215; 1259 18001 TABLE public alembic_version source_owner",
        ),
    ],
)
def test_archive_toc_filter_rejects_missing_duplicate_or_incomplete_denominator(
    entries: tuple[str, ...],
) -> None:
    with pytest.raises(RecoveryIntegrityError):
        _filter_public_schema_toc(_toc(*entries))


@pytest.mark.parametrize(
    "forbidden",
    [
        "301; 0 0 ACL public TABLE result_claims source_owner",
        "302; 0 0 DEFAULT ACL - DEFAULT PRIVILEGES FOR TABLES source_owner",
        "303; 0 0 DATABASE - ledger source_owner",
        "304; 0 0 COMMENT - DATABASE ledger source_owner",
        "305; 3079 18100 EXTENSION - unreviewed_extension source_owner",
    ],
)
def test_archive_toc_proves_role_acl_and_database_posture_are_not_carried(
    forbidden: str,
) -> None:
    raw = _toc(
        "6; 2615 2200 SCHEMA - public pg_database_owner",
        "215; 1259 18001 TABLE public alembic_version source_owner",
        "4210; 0 18001 TABLE DATA public alembic_version source_owner",
        forbidden,
    )
    with pytest.raises(UnsupportedRecoveryArtifact):
        _filter_public_schema_toc(raw)


def _strict_head_proof() -> _StrictHeadProof:
    return _StrictHeadProof(
        schema_revision="0010_operational_persistence",
        operational_constraint_inventory_sha256=(
            POSTGRESQL_OPERATIONAL_CONSTRAINT_INVENTORY_SHA256
        ),
        operational_index_inventory_sha256=(
            POSTGRESQL_OPERATIONAL_INDEX_INVENTORY_SHA256
        ),
    )


def _reviewed_nonoperational_relation_rows() -> list[tuple[str, str, str | None]]:
    rows = [(name, "r", None) for name in expected_head_columns()]
    rows.extend(
        (name, "i", definition[0])
        for name, definition in POSTGRESQL_REQUIRED_INDEXES.items()
    )
    rows.extend(
        (
            name,
            "i",
            POSTGRESQL_REQUIRED_CONSTRAINT_TABLES[name],
        )
        for name, definition in POSTGRESQL_REQUIRED_CONSTRAINTS.items()
        if definition.startswith(("PRIMARY KEY", "UNIQUE"))
    )
    return rows


def test_relation_census_uses_pinned_operational_proof_without_weakening_legacy_names() -> None:
    rows = _reviewed_nonoperational_relation_rows()
    # Operational names are accepted only in their reviewed table domain; the
    # strict proof represents the existing exact operational catalog digests.
    rows.append(("scheduled_cycles_pkey", "i", "scheduled_cycles"))

    _validate_public_relation_rows(rows, strict_head_proof=_strict_head_proof())


def test_relation_census_rejects_extra_or_missing_nonoperational_index() -> None:
    rows = _reviewed_nonoperational_relation_rows()
    missing = rows[:-1]
    extra = [*rows, ("attacker_extra_index", "i", "result_claims")]

    with pytest.raises(RecoveryIntegrityError, match="index denominator"):
        _validate_public_relation_rows(missing, strict_head_proof=_strict_head_proof())
    with pytest.raises(RecoveryIntegrityError, match="index denominator"):
        _validate_public_relation_rows(extra, strict_head_proof=_strict_head_proof())


def test_relation_census_rejects_forged_operational_inventory_proof() -> None:
    forged = replace(
        _strict_head_proof(),
        operational_index_inventory_sha256="0" * 64,
    )
    with pytest.raises(RecoveryIntegrityError, match="pinned strict-head proof"):
        _validate_public_relation_rows(
            _reviewed_nonoperational_relation_rows(),
            strict_head_proof=forged,
        )


def test_restore_argv_is_fixed_single_transaction_and_has_no_dsn_or_destructive_flag() -> None:
    argv = _archive_restore_argv(
        database_name="ledger_disposable_restore",
        archive_path="/private/tmp/archive.dump",
        toc_path="/private/tmp/archive.list",
    )

    assert argv[0] == str(PG_RESTORE_PATH)
    assert "--exit-on-error" in argv
    assert "--single-transaction" in argv
    assert "--schema=public" in argv
    assert "--no-owner" in argv
    assert "--no-privileges" in argv
    assert "--clean" not in argv
    assert "--create" not in argv
    assert "--if-exists" not in argv
    assert not any("postgresql://" in value or "secret" in value for value in argv)


def test_tool_paths_are_fixed_absolute_postgresql_paths() -> None:
    assert PG_DUMP_PATH == PG_DUMP_PATH.resolve()
    assert PG_RESTORE_PATH == PG_RESTORE_PATH.resolve()
    assert str(PG_DUMP_PATH) == "/usr/lib/postgresql/16/bin/pg_dump"
    assert str(PG_RESTORE_PATH) == "/usr/lib/postgresql/16/bin/pg_restore"


class _FakeProcess:
    def __init__(self, *, returncode: int | None, stderr: bytes = b"") -> None:
        self.pid = 424242
        self.returncode = returncode
        self._stderr = stderr
        self.waited = False

    def communicate(self, *, timeout: float):  # type: ignore[no-untyped-def]
        if self.returncode is None:
            raise __import__("subprocess").TimeoutExpired("fixed-tool", timeout)
        return b"", self._stderr

    def wait(self, *, timeout: float) -> int:
        self.waited = True
        self.returncode = -15
        return self.returncode

    def poll(self) -> int | None:
        return self.returncode


def test_running_tool_cancellation_stops_its_isolated_process_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = _FakeProcess(returncode=None)
    popen_kwargs: dict[str, object] = {}
    signals: list[tuple[int, int]] = []

    def fake_popen(*_args, **kwargs):  # type: ignore[no-untyped-def]
        popen_kwargs.update(kwargs)
        return process

    monkeypatch.setattr("app.backup.postgresql_driver.subprocess.Popen", fake_popen)
    monkeypatch.setattr(
        "app.backup.postgresql_driver.os.killpg",
        lambda pid, sent_signal: signals.append((pid, sent_signal)),
    )
    polls = iter((False, True))

    with pytest.raises(RecoveryCancelled) as cancelled:
        _run_pg_tool(
            (str(PG_DUMP_PATH), "--version"),
            environment={"LANG": "C", "LC_ALL": "C", "TZ": "UTC"},
            phase="unit-running-tool",
            timeout_seconds=1,
            cancel_requested=lambda: next(polls),
            target_created=True,
        )

    assert cancelled.value.relational_target_created is True
    assert popen_kwargs["start_new_session"] is True
    assert popen_kwargs["close_fds"] is True
    assert popen_kwargs["stderr"] == __import__("subprocess").DEVNULL
    assert signals == [(424242, __import__("signal").SIGTERM)]
    assert process.waited is True


def test_failed_tool_discards_secret_bearing_stderr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = _FakeProcess(
        returncode=1,
        stderr=b"postgresql://ledger:very-secret@private.example/ledger",
    )
    monkeypatch.setattr(
        "app.backup.postgresql_driver.subprocess.Popen",
        lambda *_args, **_kwargs: process,
    )

    with pytest.raises(RecoveryPartialFailure) as failed:
        _run_pg_tool(
            (str(PG_RESTORE_PATH), "--version"),
            environment={"LANG": "C", "LC_ALL": "C", "TZ": "UTC"},
            phase="unit-failed-tool",
            timeout_seconds=1,
        )

    assert "very-secret" not in str(failed.value)
    assert "postgresql://" not in str(failed.value)
    assert failed.value.__cause__ is None


def test_unexpected_live_process_error_is_reaped_and_redacted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = _FakeProcess(returncode=None)
    signals: list[tuple[int, int]] = []

    def explode(*, timeout: float):  # type: ignore[no-untyped-def]
        raise ValueError("postgresql://ledger:very-secret@private.example/ledger")

    process.communicate = explode  # type: ignore[method-assign]
    monkeypatch.setattr(
        "app.backup.postgresql_driver.subprocess.Popen",
        lambda *_args, **_kwargs: process,
    )
    monkeypatch.setattr(
        "app.backup.postgresql_driver.os.killpg",
        lambda pid, sent_signal: signals.append((pid, sent_signal)),
    )

    with pytest.raises(RecoveryPartialFailure) as failed:
        _run_pg_tool(
            (str(PG_DUMP_PATH), "--version"),
            environment={"LANG": "C", "LC_ALL": "C", "TZ": "UTC"},
            phase="unit-unexpected-tool-error",
            timeout_seconds=1,
        )

    assert signals == [(424242, __import__("signal").SIGTERM)]
    assert process.waited is True
    assert "very-secret" not in str(failed.value)
    assert failed.value.__cause__ is None


def test_schema_dump_normalizes_only_one_matching_restrict_nonce_pair() -> None:
    raw = (
        "-- PostgreSQL database dump\n"
        "\\restrict h7J5oQ\n"
        "CREATE TABLE public.example (id integer);\n"
        "\\unrestrict h7J5oQ\n"
    ).encode("utf-8")

    normalized = _normalize_schema_dump(raw)

    assert b"h7J5oQ" not in normalized
    assert normalized.count(b"DATA10_RESTRICT_NONCE") == 2
    with pytest.raises(RecoveryIntegrityError, match="restrict"):
        _normalize_schema_dump(raw.replace(b"\\unrestrict h7J5oQ", b"\\unrestrict wrong"))
    with pytest.raises(RecoveryIntegrityError, match="restrict"):
        _normalize_schema_dump(raw + b"\\restrict second\n\\unrestrict second\n")


def test_schema_dump_rejects_owner_acl_or_session_authorization_statements() -> None:
    template = b"\\restrict nonce\n%s\n\\unrestrict nonce\n"
    for statement in (
        b"ALTER TABLE public.example OWNER TO source_owner;",
        b"GRANT SELECT ON TABLE public.example TO reader;",
        b"REVOKE ALL ON FUNCTION public.guard() FROM PUBLIC;",
        b"SET SESSION AUTHORIZATION source_owner;",
        b"ALTER DEFAULT PRIVILEGES GRANT SELECT ON TABLES TO reader;",
    ):
        with pytest.raises(UnsupportedRecoveryArtifact):
            _normalize_schema_dump(template % statement)


def _utc_text(value: datetime) -> str:
    return value.astimezone(_UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _terminal_cycle_payload() -> dict[str, Any]:
    environment = "data10-pg-fixture"
    lane = "discovery"
    policy = "data10-pg-schedule-policy-v1"
    ordinal = 401
    scheduled = _ANCHOR + timedelta(seconds=_CADENCE_SECONDS * ordinal)
    following = scheduled + timedelta(seconds=_CADENCE_SECONDS)
    payload: dict[str, Any] = {
        "schemaVersion": "1.0.0",
        "policyVersion": "scheduled-cycle-v1",
        "availability": "operations_record_only",
        "mode": "synthetic_fixture",
        "cycleId": derive_cycle_id(environment, lane, _utc_text(scheduled), policy),
        "environment": environment,
        "lane": lane,
        "schedulePolicyRevisionId": policy,
        "slot": {
            "anchorUtc": _utc_text(_ANCHOR),
            "cadenceSeconds": _CADENCE_SECONDS,
            "slotOrdinal": ordinal,
            "scheduledFor": _utc_text(scheduled),
            "nextScheduledFor": _utc_text(following),
            "completionWindowEndsAt": _utc_text(scheduled + timedelta(hours=2)),
            "catchUpDisposition": "scheduled",
            "missedSlotCount": 0,
        },
        "wakeups": [
            {
                "wakeupId": "data10-pg-fixture-wakeup-401",
                "kind": "manual_fixture",
                "observedAt": _utc_text(scheduled + timedelta(seconds=1)),
                "opaqueTriggerId": "data10-pg-fixture-trigger-401",
                "deliveryAttempt": 1,
                "authoritative": False,
            }
        ],
        "state": "terminal",
        "jobs": [],
        "counts": {
            "expected": 0,
            "due": 0,
            "notDue": 0,
            "blocked": 0,
            "terminal": 0,
            "succeeded": 0,
            "reviewRequired": 0,
            "failed": 0,
        },
        "authority": {
            "classification": "schedule_receipt_only",
            "certifiesSources": False,
            "authorizesCapture": False,
            "authorizesPublication": False,
            "frontendLoadable": False,
            "wakeupAuthoritative": False,
        },
        "manifest": {
            "algorithm": "sha256-canonical-operations-json-v1",
            "contentSha256": "0" * 64,
            "jobCount": 0,
            "wakeupCount": 1,
        },
    }
    payload["manifest"]["contentSha256"] = operations_self_digest(payload)
    return payload


def _source_definition() -> dict[str, Any]:
    return {
        "id": "data10-pg-source",
        "benchmark_id": "data10-pg-benchmark",
        "source_name": "Disposable DATA-10 PostgreSQL source",
        "source_url": "https://fixtures.example.test/data10-pg-source/results.json",
        "source_type": "api",
        "officialness_level": "O1",
        "machine_readable": True,
        "requires_auth": False,
        "supports_history": True,
        "update_cadence": "manual",
        "parser_name": "data10-pg-fixture-json",
        "parser_version": "1",
        "parser_config": {},
        "status": "active",
        "notes": "Disposable recovery fixture only; not certified or publishable.",
    }


def _seed_source(
    source_url: str, *, primary_object_root: Path
) -> tuple[dict[str, Any], str, str]:
    engine = create_engine(source_url, future=True, poolclass=NullPool)
    storage = LocalSnapshotStorage(primary_object_root)
    stored = storage.store_snapshot(raw_bytes=_SNAPSHOT_RAW_BYTES)
    cycle_payload = _terminal_cycle_payload()
    try:
        with Session(engine) as session, session.begin():
            if (
                session.scalar(select(func.count()).select_from(models.ScheduledCycle))
                or session.scalar(select(func.count()).select_from(models.SourceSnapshot))
            ):
                pytest.fail(
                    "PostgreSQL recovery source must start with zero terminal cycles and snapshots"
                )
            repositories.upsert_benchmark(
                session,
                {
                    "id": "data10-pg-benchmark",
                    "canonical_name": "data10-pg-benchmark",
                    "display_name": "Disposable DATA-10 PostgreSQL benchmark",
                },
            )
            reconciliation = repositories.reconcile_official_source(
                session, _source_definition()
            )
            snapshot = repositories.insert_snapshot(
                session,
                official_source_id="data10-pg-source",
                source_revision_id=reconciliation.revision.id,
                raw_content_uri=stored.address.uri,
                content_hash=stored.address.content_sha256,
                content_type="application/json",
                http_status=200,
                etag=None,
                last_modified_header=None,
                fetch_metadata={
                    "storageReceiptSha256": stored.receipt_id.split(":")[-1],
                    "storageVerificationReceiptSha256": (
                        stored.verification_receipt_id.split(":")[-1]
                    ),
                },
                parser_version="data10-pg-fixture-json-v1",
            )
            intent, jobs = operational_repositories.append_scheduled_cycle_intent(
                session,
                environment=cycle_payload["environment"],
                lane=cycle_payload["lane"],
                scheduled_for=cycle_payload["slot"]["scheduledFor"],
                schedule_policy_revision_id=cycle_payload[
                    "schedulePolicyRevisionId"
                ],
                mode=cycle_payload["mode"],
                job_targets=[],
            )
            assert intent.cycle_id == cycle_payload["cycleId"] and jobs == ()
            terminal = operational_repositories.append_scheduled_cycle(
                session, cycle_payload
            )
            assert terminal.content_sha256 == cycle_payload["manifest"]["contentSha256"]
            snapshot_id = snapshot.id
    finally:
        engine.dispose()
    assert Path(stored.address.uri).read_bytes() == _SNAPSHOT_RAW_BYTES
    return cycle_payload, snapshot_id, stored.address.content_sha256


def _target_security_facts(database_url: str) -> tuple[set[str], int, int]:
    engine = create_engine(database_url, future=True, poolclass=NullPool)
    try:
        with engine.connect() as connection:
            owners = {
                str(row[0])
                for row in connection.execute(
                    text(
                        """
                        SELECT DISTINCT pg_get_userbyid(relation.relowner)
                        FROM pg_class AS relation
                        JOIN pg_namespace AS namespace
                          ON namespace.oid = relation.relnamespace
                        WHERE namespace.nspname = 'public'
                          AND relation.relkind IN ('r', 'S')
                        """
                    )
                )
            }
            explicit_table_acl_rows = int(
                connection.execute(
                    text(
                        """
                        SELECT COUNT(*)
                        FROM pg_class AS relation
                        JOIN pg_namespace AS namespace
                          ON namespace.oid = relation.relnamespace
                        WHERE namespace.nspname = 'public'
                          AND relation.relkind = 'r'
                          AND relation.relacl IS NOT NULL
                        """
                    )
                ).scalar_one()
            )
            public_function_execute = int(
                connection.execute(
                    text(
                        """
                        SELECT COUNT(*)
                        FROM pg_proc AS function_object
                        JOIN pg_namespace AS namespace
                          ON namespace.oid = function_object.pronamespace
                        WHERE namespace.nspname = 'public'
                          AND has_function_privilege(
                              'public', function_object.oid, 'EXECUTE'
                          )
                        """
                    )
                ).scalar_one()
            )
            return owners, explicit_table_acl_rows, public_function_execute
    finally:
        engine.dispose()


def _recovery_urls() -> tuple[str, str, str]:
    values = tuple(os.getenv(name) for name in _RECOVERY_ENV_NAMES)
    if not all(values):
        pytest.skip(
            "real PostgreSQL recovery requires all three explicit "
            "TEST_POSTGRESQL_RECOVERY_*_URL values"
        )
    source, inspection, restore = values
    assert source is not None and inspection is not None and restore is not None
    parsed = tuple(make_url(value) for value in (source, inspection, restore))
    names = tuple(item.database or "" for item in parsed)
    if len(set(names)) != 3 or any("disposable" not in name for name in names):
        pytest.fail(
            "PostgreSQL recovery target test refuses non-distinct or non-disposable databases"
        )
    _refuse_cross_node_database_aliases(
        names,
        other_environment_names=_ADVERSARY_ENV_NAMES,
    )
    return source, inspection, restore


def _refuse_cross_node_database_aliases(
    names: tuple[str, str, str],
    *,
    other_environment_names: tuple[str, str, str],
) -> None:
    other_urls = tuple(
        value
        for environment_name in other_environment_names
        if (value := os.getenv(environment_name))
    )
    other_names = tuple(
        make_url(database_url).database or "" for database_url in other_urls
    )
    combined_names = (*names, *other_names)
    if len(set(combined_names)) != len(combined_names):
        pytest.fail(
            "PostgreSQL real-service tests require six mutually distinct "
            "database names across both opt-in nodes"
        )


def _adversary_urls() -> tuple[str, str, str]:
    values = tuple(
        os.getenv(name)
        for name in _ADVERSARY_ENV_NAMES
    )
    if not all(values):
        pytest.skip(
            "real PostgreSQL scope adversaries require all three explicit "
            "TEST_POSTGRESQL_RECOVERY_ADVERSARY_*_URL values"
        )
    source, publication, large_object = values
    assert source is not None and publication is not None and large_object is not None
    parsed = tuple(make_url(value) for value in (source, publication, large_object))
    names = tuple(item.database or "" for item in parsed)
    if len(set(names)) != 3 or any("disposable" not in name for name in names):
        pytest.fail(
            "PostgreSQL scope-adversary test refuses non-distinct or "
            "non-disposable databases"
        )
    _refuse_cross_node_database_aliases(
        names,
        other_environment_names=_RECOVERY_ENV_NAMES,
    )
    return source, publication, large_object


@pytest.mark.parametrize("populated_clean_environment", _RECOVERY_ENV_NAMES)
def test_adversary_urls_refuse_alias_with_any_populated_clean_recovery_url(
    monkeypatch: pytest.MonkeyPatch,
    populated_clean_environment: str,
) -> None:
    for environment_name in (*_RECOVERY_ENV_NAMES, *_ADVERSARY_ENV_NAMES):
        monkeypatch.delenv(environment_name, raising=False)
    adversary_urls = (
        "postgresql+psycopg://owner@/ledger_disposable_adversary_source"
        "?host=%2Ftmp%2Fpg&port=55441",
        "postgresql+psycopg://owner@/ledger_disposable_adversary_publication"
        "?host=%2Ftmp%2Fpg&port=55441",
        "postgresql+psycopg://owner@/ledger_disposable_adversary_large_object"
        "?host=%2Ftmp%2Fpg&port=55441",
    )
    for environment_name, database_url in zip(
        _ADVERSARY_ENV_NAMES,
        adversary_urls,
        strict=True,
    ):
        monkeypatch.setenv(environment_name, database_url)
    monkeypatch.setenv(populated_clean_environment, adversary_urls[1])

    with pytest.raises(pytest.fail.Exception, match="six mutually distinct"):
        _adversary_urls()


def _database_adversary_facts(database_url: str) -> tuple[object, int, int, int]:
    engine = create_engine(database_url, future=True, poolclass=NullPool)
    try:
        with engine.connect() as connection:
            row = connection.execute(
                text(
                    """
                    SELECT
                        shobj_description(database_catalog.oid, 'pg_database'),
                        (SELECT COUNT(*) FROM pg_publication),
                        (SELECT COUNT(*) FROM pg_largeobject_metadata),
                        (
                            SELECT COUNT(*)
                            FROM pg_class AS relation
                            JOIN pg_namespace AS namespace
                              ON namespace.oid = relation.relnamespace
                            WHERE namespace.nspname = 'public'
                        )
                    FROM pg_database AS database_catalog
                    WHERE database_catalog.datname = current_database()
                    """
                )
            ).one()
            return row[0], int(row[1]), int(row[2]), int(row[3])
    finally:
        engine.dispose()


def _install_database_scope_adversaries(
    publication_url: str,
    large_object_url: str,
) -> int:
    publication_engine = create_engine(
        publication_url,
        future=True,
        poolclass=NullPool,
    )
    large_object_engine = create_engine(
        large_object_url,
        future=True,
        poolclass=NullPool,
    )
    try:
        with publication_engine.begin() as connection:
            connection.execute(
                text(
                    "CREATE PUBLICATION data10_recovery_scope_adversary"
                )
            )
        with large_object_engine.begin() as connection:
            large_object_oid = int(
                connection.execute(text("SELECT lo_create(0)")).scalar_one()
            )
    finally:
        publication_engine.dispose()
        large_object_engine.dispose()
    return large_object_oid


def test_real_postgresql_database_scope_adversaries_refuse_before_marker_or_restore(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_url, publication_url, large_object_url = _adversary_urls()
    assert _database_adversary_facts(publication_url) == (None, 0, 0, 0)
    assert _database_adversary_facts(large_object_url) == (None, 0, 0, 0)
    large_object_oid = _install_database_scope_adversaries(
        publication_url,
        large_object_url,
    )
    assert large_object_oid > 0
    assert _database_adversary_facts(publication_url) == (None, 1, 0, 0)
    assert _database_adversary_facts(large_object_url) == (None, 0, 1, 0)

    driver = PostgreSQLBackupRestoreDriver()
    artifact = driver.create_backup(PostgreSQLConnectionSpec.from_url(source_url))
    forbidden_pg_restore_calls: list[tuple[str, ...]] = []

    def guard_target_pg_restore(
        argv: tuple[str, ...],
        **kwargs: object,
    ) -> bytes:
        if argv[0] == str(PG_RESTORE_PATH) and "--version" not in argv:
            forbidden_pg_restore_calls.append(argv)
            raise AssertionError(
                "database-scope contamination reached pg_restore archive/target path"
            )
        return _run_pg_tool(argv, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(
        "app.backup.postgresql_driver._run_pg_tool",
        guard_target_pg_restore,
    )
    for target_url, target_id in (
        (publication_url, "must-refuse-publication"),
        (large_object_url, "must-refuse-large-object"),
    ):
        with pytest.raises(RecoveryTargetError, match="database-scoped state"):
            driver.restore_new_target(
                artifact,
                PostgreSQLConnectionSpec.from_url(target_url),
                target_id=target_id,
            )

    assert forbidden_pg_restore_calls == []
    assert _database_adversary_facts(publication_url) == (None, 1, 0, 0)
    assert _database_adversary_facts(large_object_url) == (None, 0, 1, 0)


def test_real_postgresql_custom_archive_restores_two_new_targets_from_archive_bytes(
    tmp_path: Path,
) -> None:
    source_url, inspection_url, restore_url = _recovery_urls()
    source = PostgreSQLConnectionSpec.from_url(source_url)
    inspection_target = PostgreSQLConnectionSpec.from_url(inspection_url)
    restore_target = PostgreSQLConnectionSpec.from_url(restore_url)
    primary_root = tmp_path / "primary-content-addressed-objects"
    cycle_payload, snapshot_id, snapshot_sha256 = _seed_source(
        source_url,
        primary_object_root=primary_root,
    )
    primary_store = RecoveryDomain(
        failure_domain_id="data10-pg-primary-local",
        store=LocalSnapshotStorage(primary_root),
    )
    recovery_store = LocalRecoveryStore(
        tmp_path / "recovery-content-addressed-objects",
        failure_domain_id="data10-pg-recovery-local",
    )
    restore_store = LocalRecoveryStore(
        tmp_path / "restore-content-addressed-objects",
        failure_domain_id="data10-pg-restore-local",
    )
    source_security = _target_security_facts(source_url)
    assert inspect_database(source_url).kind == "current"
    driver = PostgreSQLBackupRestoreDriver()

    checkpoint = create_checkpoint_with_driver(
        driver=driver,
        database_source=source,
        trigger_cycle=cycle_payload,
        primary_store=primary_store,
        recovery_store=recovery_store,
        created_at=cycle_payload["slot"]["completionWindowEndsAt"],
        inspection_target=inspection_target,
        inspection_target_id="data10-pg-inspection-01",
    )
    validate_checkpoint_manifest(checkpoint)

    expected_cycle = {
        "environment": cycle_payload["environment"],
        "lane": cycle_payload["lane"],
        "cycleId": cycle_payload["cycleId"],
        "scheduledFor": cycle_payload["slot"]["scheduledFor"],
        "schedulePolicyRevisionId": cycle_payload["schedulePolicyRevisionId"],
        "contentSha256": cycle_payload["manifest"]["contentSha256"],
    }
    assert checkpoint["triggerCycle"] == {
        "cycleId": cycle_payload["cycleId"],
        "manifest": {
            "contentSha256": cycle_payload["manifest"]["contentSha256"],
        },
        "environment": cycle_payload["environment"],
        "lane": cycle_payload["lane"],
        "schedulePolicyRevisionId": cycle_payload["schedulePolicyRevisionId"],
        "scheduledFor": cycle_payload["slot"]["scheduledFor"],
        "nextScheduledFor": cycle_payload["slot"]["nextScheduledFor"],
        "state": "terminal",
        "mode": "synthetic_fixture",
    }
    assert checkpoint["cycleInventory"]["completedCycleCount"] == 1
    assert checkpoint["cycleInventory"]["cycles"] == [expected_cycle]
    assert checkpoint["cycleInventory"]["watermarks"] == [
        {
            "environment": cycle_payload["environment"],
            "lane": cycle_payload["lane"],
            "completedCycleCount": 1,
            "earliestScheduledFor": cycle_payload["slot"]["scheduledFor"],
            "earliestCycleId": cycle_payload["cycleId"],
            "latestScheduledFor": cycle_payload["slot"]["scheduledFor"],
            "latestCycleId": cycle_payload["cycleId"],
            "latestCycleContentSha256": cycle_payload["manifest"]["contentSha256"],
            "cycleSetSha256": checkpoint["cycleInventory"]["cycleSetSha256"],
        }
    ]

    checkpoint_relational = checkpoint["relationalBackup"]
    expected_columns = expected_head_columns()
    checkpoint_tables = checkpoint_relational["tables"]
    assert tuple(item["tableName"] for item in checkpoint_tables) == tuple(
        sorted(expected_columns)
    )
    assert {
        item["tableName"]: tuple(item["columnNames"]) for item in checkpoint_tables
    } == expected_columns
    nonempty_tables = {
        "alembic_version",
        "benchmarks",
        "official_source_revisions",
        "official_sources",
        "scheduled_cycle_intent_completions",
        "scheduled_cycle_intents",
        "scheduled_cycles",
        "source_revision_decisions",
        "source_snapshots",
    }
    assert {
        item["tableName"]: item["rowCount"] for item in checkpoint_tables
    } == {
        table_name: int(table_name in nonempty_tables)
        for table_name in sorted(expected_columns)
    }
    expected_lineages = [
        {
            "family": family,
            "rootCount": int(family == "source_revision_decisions"),
            "leafCount": int(family == "source_revision_decisions"),
            "rowCount": int(family == "source_revision_decisions"),
        }
        for family in LINEAGE_TABLES
    ]
    checkpoint_integrity = checkpoint_relational["integrity"]
    assert checkpoint_integrity == {
        "postgresqlConsistencyCheck": "passed",
        "foreignKeyViolationCount": 0,
        "semanticLineageAudit": {
            "status": "passed",
            "familyCount": 7,
            "rowCount": 1,
            "families": expected_lineages,
        },
    }

    assert checkpoint["objectManifest"]["sourceSnapshotRowCount"] == 1
    assert checkpoint["objectManifest"]["governedArtifactCount"] == 0
    assert checkpoint["objectManifest"]["objectReferenceCount"] == 1
    assert checkpoint["objectManifest"]["uniqueObjectCount"] == 1
    checkpoint_object = checkpoint["objectManifest"]["objects"][0]
    assert {
        key: checkpoint_object[key]
        for key in (
            "referenceType",
            "referenceId",
            "objectKind",
            "contentSha256",
            "byteLength",
        )
    } == {
        "referenceType": "source_snapshot_raw",
        "referenceId": snapshot_id,
        "objectKind": "snapshot",
        "contentSha256": snapshot_sha256,
        "byteLength": len(_SNAPSHOT_RAW_BYTES),
    }
    assert Path(checkpoint_object["sourceLogicalUri"]).is_relative_to(
        primary_root.resolve()
    )
    recovery_snapshot = checkpoint_object["recoveryCopy"]
    recovery_snapshot_read = recovery_store.read_snapshot(
        uri=recovery_snapshot["uri"],
        content_sha256=recovery_snapshot["contentSha256"],
    )
    assert recovery_snapshot_read.raw_bytes == _SNAPSHOT_RAW_BYTES
    assert (
        recovery_snapshot_read.verification.receipt_id
        == recovery_snapshot["verificationReceiptId"]
    )

    checkpoint_bytes = canonical_recovery_json(checkpoint).encode("ascii")
    assert parse_canonical_recovery_bytes(checkpoint_bytes) == checkpoint
    assert checkpoint["manifest"] == {
        "algorithm": "sha256-canonical-recovery-json-v1",
        "contentSha256": recovery_contract_digest(checkpoint),
        "tableCount": len(expected_columns),
        "objectReferenceCount": 1,
    }
    assert checkpoint["failureDomains"] == {
        "source": "data10-pg-primary-local",
        "recovery": "data10-pg-recovery-local",
        "declaredDistinct": True,
        "independenceEvidence": "external_evidence_required",
    }
    assert checkpoint["recoveryObjective"] == {
        "maximumCompletedCyclesLost": 1,
        "status": "target_only_unproven",
        "productionClaim": False,
    }
    assert checkpoint["authority"] == _recovery_authority()

    artifact_inventory = recovery_store.inventory_orphans(
        referenced_uris=(),
        object_kind=StorageObjectKind.ARTIFACT,
    )
    assert artifact_inventory.listed_count == 2
    assert len(artifact_inventory.orphan_objects) == 2
    published_documents: list[dict[str, Any]] = []
    for address in artifact_inventory.orphan_objects:
        stored_artifact = recovery_store.read_snapshot(
            uri=address.uri,
            content_sha256=address.content_sha256,
        )
        try:
            candidate = parse_canonical_recovery_bytes(stored_artifact.raw_bytes)
        except ValueError:
            continue
        if candidate.get("policyVersion") == "recovery-checkpoint-v1":
            published_documents.append(candidate)
            assert stored_artifact.raw_bytes == checkpoint_bytes
    assert published_documents == [checkpoint]

    recovery_archive = checkpoint_relational["recoveryCopy"]
    archive_read = recovery_store.read_snapshot(
        uri=recovery_archive["uri"],
        content_sha256=recovery_archive["contentSha256"],
    )
    assert archive_read.verification.receipt_id == recovery_archive[
        "verificationReceiptId"
    ]
    artifact = RelationalBackupArtifact(
        driver_id=checkpoint_relational["driverId"],
        driver_version=checkpoint_relational["driverVersion"],
        engine_name=checkpoint_relational["engineName"],
        engine_version=checkpoint_relational["engineVersion"],
        tool_name=checkpoint_relational["toolName"],
        tool_version=checkpoint_relational["toolVersion"],
        artifact_type=checkpoint_relational["artifactType"],
        format=checkpoint_relational["format"],
        format_version=checkpoint_relational["formatVersion"],
        source_database_identity_sha256=checkpoint_relational[
            "sourceDatabaseIdentitySha256"
        ],
        raw_bytes=archive_read.raw_bytes,
    )
    assert artifact.raw_bytes.startswith(b"PGDMP")
    assert compute_content_hash(artifact.raw_bytes) == checkpoint_relational[
        "contentSha256"
    ]
    assert checkpoint_relational["artifactId"] == (
        "relational-backup_" + compute_content_hash(artifact.raw_bytes)
    )

    clock = _TwoSampleUtcClock(
        datetime(2026, 7, 22, 15, 0, 0, 900_000, tzinfo=_UTC),
        datetime(2026, 7, 22, 15, 0, 4, 100_000, tzinfo=_UTC),
    )
    receipt = restore_checkpoint_with_driver(
        driver=driver,
        checkpoint=checkpoint,
        recovery_store=recovery_store,
        restore_store=restore_store,
        relational_target=restore_target,
        target_id="data10-pg-restore-01",
        utc_now=clock,
    )
    validate_restore_receipt(receipt)

    receipt_bytes = canonical_recovery_json(receipt).encode("ascii")
    assert parse_canonical_recovery_bytes(receipt_bytes) == receipt
    assert receipt["manifest"] == {
        "algorithm": "sha256-canonical-recovery-json-v1",
        "contentSha256": recovery_contract_digest(receipt),
        "tableCount": len(expected_columns),
        "objectReferenceCount": 1,
    }
    assert clock.calls == 2
    assert receipt["startedAt"] == "2026-07-22T15:00:00Z"
    assert receipt["finishedAt"] == "2026-07-22T15:00:04Z"
    assert receipt["durationMs"] == 4_000
    assert receipt["checkpoint"] == {
        "checkpointId": checkpoint["checkpointId"],
        "contentSha256": checkpoint["manifest"]["contentSha256"],
        "triggerCycleId": cycle_payload["cycleId"],
        "triggerCycleContentSha256": cycle_payload["manifest"]["contentSha256"],
    }
    assert receipt["target"] == {
        "targetId": "data10-pg-restore-01",
        "freshRelationalTarget": True,
        "recoveryMapOnly": True,
        "cutoverAuthorized": False,
    }
    assert receipt["failureDomains"] == {
        "recovery": "data10-pg-recovery-local",
        "restore": "data10-pg-restore-local",
        "declaredDistinct": True,
        "independenceEvidence": "external_evidence_required",
    }
    assert receipt["recoveryAssessment"] == {
        "maximumCompletedCyclesLostTarget": 1,
        "rpoStatus": "target_not_proven",
        "rtoStatus": "target_not_proven",
        "providerIndependenceStatus": "external_evidence_required",
        "runtimeLocatorCutoverStatus": "not_authorized",
    }
    assert receipt["authority"] == _recovery_authority()

    receipt_relational = receipt["relationalRestore"]
    checkpoint_restore_base = {
        key: value
        for key, value in checkpoint_relational.items()
        if key not in {"artifactId", "contentSha256", "recoveryCopy"}
    }
    assert set(receipt_relational) == set(checkpoint_restore_base) | {
        "sourceBackupContentSha256",
        "restoredContentSha256",
        "matchesCheckpoint",
    }
    assert {
        key: receipt_relational[key] for key in checkpoint_restore_base
    } == checkpoint_restore_base
    assert receipt_relational["sourceBackupContentSha256"] == checkpoint_relational[
        "contentSha256"
    ]
    assert receipt_relational["restoredContentSha256"] == checkpoint_relational[
        "contentSha256"
    ]
    assert receipt_relational["matchesCheckpoint"] is True

    assert receipt["objectRestore"]["objectReferenceCount"] == 1
    assert receipt["objectRestore"]["uniqueObjectCount"] == 1
    assert receipt["objectRestore"]["objectSetSha256"] == checkpoint[
        "objectManifest"
    ]["objectSetSha256"]
    assert receipt["objectRestore"]["allVerified"] is True
    restored_object = receipt["objectRestore"]["objects"][0]
    assert {
        key: restored_object[key]
        for key in (
            "referenceType",
            "referenceId",
            "sourceLogicalUri",
            "contentSha256",
            "byteLength",
            "recoveryCopyUri",
        )
    } == {
        "referenceType": checkpoint_object["referenceType"],
        "referenceId": snapshot_id,
        "sourceLogicalUri": checkpoint_object["sourceLogicalUri"],
        "contentSha256": snapshot_sha256,
        "byteLength": len(_SNAPSHOT_RAW_BYTES),
        "recoveryCopyUri": recovery_snapshot["uri"],
    }
    restored_copy = restored_object["restoredCopy"]
    restored_snapshot_read = restore_store.read_snapshot(
        uri=restored_copy["uri"],
        content_sha256=restored_copy["contentSha256"],
    )
    assert restored_snapshot_read.raw_bytes == _SNAPSHOT_RAW_BYTES
    assert (
        restored_snapshot_read.verification.receipt_id
        == restored_copy["verificationReceiptId"]
    )

    # The archive intentionally does not restore source owners or table ACLs.
    # The literal PUBLIC-function revoke is only a target safety floor; strict
    # executable-state inspection passes without creating roles or grants.
    inspection_security = _target_security_facts(inspection_url)
    restore_security = _target_security_facts(restore_url)
    assert source_security[1:] == (len(expected_columns), 0)
    assert inspection_security[1:] == (0, 0)
    assert restore_security[1:] == (0, 0)
    assert inspection_security[0] == {inspection_target.user}
    assert restore_security[0] == {restore_target.user}
    assert inspection_security[0] != source_security[0]
    assert restore_security[0] != source_security[0]
    assert inspect_database(inspection_url).kind == "current"
    assert inspect_database(restore_url).kind == "current"

    with pytest.raises(RecoveryTargetError, match="source database"):
        driver.restore_new_target(
            artifact,
            source,
            target_id="must-refuse-source-identity-before-mutation",
        )
    with pytest.raises(RecoveryTargetError, match="already consumed"):
        driver.restore_new_target(
            artifact,
            restore_target,
            target_id="must-not-reuse-consumed-target",
        )

    # Metadata substitution remains fail closed even when bytes are unchanged.
    forged = replace(artifact, tool_version="16.0")
    with pytest.raises(UnsupportedRecoveryArtifact):
        driver.inspect_artifact(
            forged,
            inspection_target=restore_target,
            target_id="must-not-reuse-consumed-target",
        )
