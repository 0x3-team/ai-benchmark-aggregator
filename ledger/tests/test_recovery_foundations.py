"""Focused DATA-10 recovery-foundation tests on disposable local resources.

These tests create an Alembic-managed SQLite database and temporary object
roots only.  They never open the configured or quarantined ledger database and
do not represent local mechanics as provider/RPO/RTO proof.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any

from alembic import command
from alembic.config import Config
import pytest
from jsonschema import Draft202012Validator, FormatChecker
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.backup import (
    LocalRecoveryStore,
    RecoveryDomain,
    RecoveryIntegrityError,
    RecoveryPartialFailure,
    RecoveryReplayConflict,
    RecoveryTargetError,
    SQLiteBackupRestoreDriver,
    UnsupportedRecoveryArtifact,
    canonical_recovery_json,
    create_sqlite_checkpoint,
    recovery_contract_digest,
    recovery_table_inventory_digest,
    restore_checkpoint_with_driver,
    restore_sqlite_checkpoint,
    validate_checkpoint_manifest,
    validate_restore_receipt,
)
from app.backup import sqlite_driver
from app.backup.stores import require_distinct_domains
from app.db import operational_repositories
from app.schemas.operations_contracts import contract_self_digest, derive_cycle_id
from app.schemas.recovery_contracts import parse_canonical_recovery_bytes
from app.storage.base import StorageObjectKind, StorageSecurityPosture
from app.storage.local import LocalSnapshotStorage


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
LEDGER_ROOT = REPOSITORY_ROOT / "ledger"
CONTRACT_ROOT = REPOSITORY_ROOT / "docs" / "contracts"
CREATED_AT = "2026-07-15T14:30:00Z"
STARTED_AT = "2026-07-15T15:00:00Z"
FINISHED_AT = "2026-07-15T15:00:04Z"
ANCHOR = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _alembic_config(database_url: str) -> Config:
    config = Config(str(LEDGER_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(LEDGER_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url)
    config.attributes["database_url"] = database_url
    return config


def _engine(database_path: Path) -> Engine:
    engine = create_engine(f"sqlite:///{database_path}", future=True)

    @event.listens_for(engine, "connect")
    def _foreign_keys(dbapi_connection, _connection_record) -> None:  # type: ignore[no-untyped-def]
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


def _utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _terminal_cycle() -> dict[str, Any]:
    scheduled = ANCHOR + timedelta(days=195)
    next_scheduled = scheduled + timedelta(hours=12)
    payload: dict[str, Any] = {
        "schemaVersion": "1.0.0",
        "policyVersion": "scheduled-cycle-v1",
        "availability": "operations_record_only",
        "mode": "synthetic_fixture",
        "cycleId": derive_cycle_id(
            "fixture-env",
            "recheck",
            _utc(scheduled),
            "fixture-recheck-policy-r1",
        ),
        "environment": "fixture-env",
        "lane": "recheck",
        "schedulePolicyRevisionId": "fixture-recheck-policy-r1",
        "slot": {
            "anchorUtc": _utc(ANCHOR),
            "cadenceSeconds": 43_200,
            "slotOrdinal": 390,
            "scheduledFor": _utc(scheduled),
            "nextScheduledFor": _utc(next_scheduled),
            "completionWindowEndsAt": _utc(scheduled + timedelta(hours=2)),
            "catchUpDisposition": "scheduled",
            "missedSlotCount": 0,
        },
        "wakeups": [
            {
                "wakeupId": "fixture-wakeup-recheck-390",
                "kind": "manual_fixture",
                "observedAt": _utc(scheduled + timedelta(seconds=1)),
                "opaqueTriggerId": "fixture-trigger-recheck-390",
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
    payload["manifest"]["contentSha256"] = contract_self_digest(payload)
    return payload


def _sqlite_backup(source: Path, target: Path) -> None:
    with sqlite3.connect(source) as source_connection, sqlite3.connect(
        target
    ) as target_connection:
        source_connection.backup(target_connection)


@pytest.fixture(scope="module")
def database_template(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, dict[str, Any]]:
    root = tmp_path_factory.mktemp("recovery-foundation-template")
    database_path = root / "template.db"
    command.upgrade(_alembic_config(f"sqlite:///{database_path}"), "head")
    trigger = _terminal_cycle()
    engine = _engine(database_path)
    try:
        with Session(engine) as session, session.begin():
            intent, jobs = operational_repositories.append_scheduled_cycle_intent(
                session,
                environment=trigger["environment"],
                lane=trigger["lane"],
                scheduled_for=trigger["slot"]["scheduledFor"],
                schedule_policy_revision_id=trigger["schedulePolicyRevisionId"],
                mode=trigger["mode"],
                job_targets=[],
            )
            assert intent.cycle_id == trigger["cycleId"] and jobs == ()
            operational_repositories.append_scheduled_cycle(session, trigger)
    finally:
        engine.dispose()
    return database_path, trigger


@pytest.fixture()
def local_fixture(
    tmp_path: Path,
    database_template: tuple[Path, dict[str, Any]],
) -> tuple[Path, dict[str, Any], RecoveryDomain, LocalRecoveryStore]:
    template, trigger = database_template
    database_path = tmp_path / "source.db"
    _sqlite_backup(template, database_path)
    primary = RecoveryDomain(
        failure_domain_id="fixture-primary-domain",
        store=LocalSnapshotStorage(tmp_path / "primary"),
    )
    recovery = LocalRecoveryStore(
        tmp_path / "recovery",
        failure_domain_id="fixture-recovery-domain",
    )
    return database_path, deepcopy(trigger), primary, recovery


def _capture(
    fixture: tuple[Path, dict[str, Any], RecoveryDomain, LocalRecoveryStore],
    *,
    created_at: str = CREATED_AT,
    database_path: Path | None = None,
    recovery_store: LocalRecoveryStore | RecoveryDomain | None = None,
) -> dict[str, Any]:
    source, trigger, primary, recovery = fixture
    return create_sqlite_checkpoint(
        database_path=database_path or source,
        trigger_cycle=trigger,
        primary_store=primary,
        recovery_store=recovery_store or recovery,
        created_at=created_at,
    )


def _restore(
    checkpoint: dict[str, Any],
    recovery: LocalRecoveryStore,
    restore_store: LocalRecoveryStore | RecoveryDomain,
    database_target: Path,
    *,
    target_id: str = "fixture-new-target",
    started_at: str = STARTED_AT,
    finished_at: str = FINISHED_AT,
) -> dict[str, Any]:
    return restore_sqlite_checkpoint(
        checkpoint=checkpoint,
        recovery_store=recovery,
        restore_store=restore_store,
        database_target=database_target,
        target_id=target_id,
        started_at=started_at,
        finished_at=finished_at,
    )


class _ProviderSpecificTarget:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path


class _OpaqueTargetSQLiteDriver(SQLiteBackupRestoreDriver):
    driver_id = SQLiteBackupRestoreDriver.driver_id
    driver_version = SQLiteBackupRestoreDriver.driver_version
    engine_name = SQLiteBackupRestoreDriver.engine_name
    engine_version = SQLiteBackupRestoreDriver.engine_version
    tool_name = SQLiteBackupRestoreDriver.tool_name
    tool_version = SQLiteBackupRestoreDriver.tool_version
    artifact_type = SQLiteBackupRestoreDriver.artifact_type
    format = SQLiteBackupRestoreDriver.format
    format_version = SQLiteBackupRestoreDriver.format_version

    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.inner = SQLiteBackupRestoreDriver()
        self.restore_called = False
        self.received_target: object | None = None
        self.received_artifact: object | None = None

    def restore_new_target(  # type: ignore[no-untyped-def]
        self,
        artifact,
        target,
        *,
        target_id,
        cancel_requested=None,
    ):
        self.events.append("driver_restore")
        self.restore_called = True
        self.received_target = target
        self.received_artifact = artifact
        if not isinstance(target, _ProviderSpecificTarget):
            raise AssertionError("generic restore substituted the provider target")
        return self.inner.restore_new_target(
            artifact,
            target.database_path,
            target_id=target_id,
            cancel_requested=cancel_requested,
        )


class _WrongBoundDriver(_OpaqueTargetSQLiteDriver):
    artifact_type = "postgresql_database"


class _WrongResultArtifactDriver(_OpaqueTargetSQLiteDriver):
    def restore_new_target(self, artifact, target, *, target_id, cancel_requested=None):  # type: ignore[no-untyped-def]
        inspected = super().restore_new_target(
            artifact,
            target,
            target_id=target_id,
            cancel_requested=cancel_requested,
        )
        return replace(
            inspected,
            artifact=replace(inspected.artifact, driver_id="substituted-driver"),
        )


class _RecordingRecoveryStore:
    security_posture = StorageSecurityPosture.application_only()

    def __init__(self, inner: LocalRecoveryStore, events: list[str]) -> None:
        self.inner = inner
        self.root = inner.root
        self.events = events

    def store_snapshot(self, *, raw_bytes: bytes, object_kind=StorageObjectKind.SNAPSHOT):  # type: ignore[no-untyped-def]
        self.events.append(f"store:{object_kind.value}")
        return self.inner.store_snapshot(raw_bytes=raw_bytes, object_kind=object_kind)

    def read_snapshot(self, *, uri: str, content_sha256: str):  # type: ignore[no-untyped-def]
        self.events.append("read")
        return self.inner.read_snapshot(uri=uri, content_sha256=content_sha256)

    def verify_snapshot(self, *, uri: str, content_sha256: str):  # type: ignore[no-untyped-def]
        self.events.append("verify")
        return self.inner.verify_snapshot(uri=uri, content_sha256=content_sha256)

    def inventory_orphans(self, *, referenced_uris, object_kind=StorageObjectKind.SNAPSHOT):  # type: ignore[no-untyped-def]
        self.events.append(f"inventory:{object_kind.value}")
        return self.inner.inventory_orphans(
            referenced_uris=referenced_uris,
            object_kind=object_kind,
        )


class _SequenceClock:
    def __init__(self, events: list[str], *observations: object) -> None:
        self.events = events
        self.observations = list(observations)
        self.calls = 0

    def __call__(self) -> datetime:
        self.events.append(f"clock:{self.calls}")
        self.calls += 1
        observation = self.observations.pop(0)
        if isinstance(observation, BaseException):
            raise observation
        assert isinstance(observation, datetime)
        return observation


def test_sqlite_driver_has_one_semantic_algorithm_owner() -> None:
    for dead_duplicate in (
        "_expected_columns",
        "_table_inventory",
        "_audit_lineage",
        "_cycle_inventory",
        "_referenced_objects",
    ):
        assert not hasattr(sqlite_driver, dead_duplicate)


def test_recovery_schemas_and_examples_are_closed_parseable_and_semantic() -> None:
    records = (
        ("recovery-checkpoint-v1", validate_checkpoint_manifest),
        ("recovery-restore-receipt-v1", validate_restore_receipt),
    )
    for stem, validator in records:
        schema = json.loads((CONTRACT_ROOT / f"{stem}.schema.json").read_text())
        example = json.loads(
            (CONTRACT_ROOT / "examples" / f"{stem}.valid.json").read_text()
        )
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert schema["additionalProperties"] is False
        assert set(schema["required"]) == set(schema["properties"])
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(
            schema,
            format_checker=FormatChecker(),
        ).validate(example)
        validator(example)
        assert example["availability"] == "recovery_evidence_only"
        assert example["authority"]["authorizesCutover"] is False
        assert example["authority"]["provesProviderIndependence"] is False
        assert example["authority"]["provesProductionRpoRto"] is False

    checkpoint = json.loads(
        (CONTRACT_ROOT / "examples" / "recovery-checkpoint-v1.valid.json").read_text()
    )
    receipt = json.loads(
        (
            CONTRACT_ROOT
            / "examples"
            / "recovery-restore-receipt-v1.valid.json"
        ).read_text()
    )
    assert receipt["checkpoint"]["checkpointId"] == checkpoint["checkpointId"]
    assert receipt["checkpoint"]["contentSha256"] == checkpoint["manifest"][
        "contentSha256"
    ]


def test_checkpoint_validator_requires_exact_head_table_denominator() -> None:
    checkpoint = json.loads(
        (CONTRACT_ROOT / "examples" / "recovery-checkpoint-v1.valid.json").read_text()
    )
    checkpoint["relationalBackup"]["tables"].pop()
    checkpoint["manifest"]["tableCount"] -= 1
    checkpoint["relationalBackup"]["tableInventorySha256"] = (
        recovery_table_inventory_digest(checkpoint["relationalBackup"]["tables"])
    )
    checkpoint["manifest"]["contentSha256"] = "0" * 64
    checkpoint["manifest"]["contentSha256"] = recovery_contract_digest(checkpoint)

    with pytest.raises(ValueError):
        validate_checkpoint_manifest(checkpoint)


def test_rejected_nested_local_domain_is_lazy_and_does_not_create_root(
    tmp_path: Path,
) -> None:
    primary_root = tmp_path / "primary"
    primary = RecoveryDomain(
        failure_domain_id="primary-domain",
        store=LocalSnapshotStorage(primary_root),
    )
    nested_root = primary_root / "must-not-be-created"
    recovery = LocalRecoveryStore(
        nested_root,
        failure_domain_id="recovery-domain",
    )
    assert not nested_root.exists()

    with pytest.raises(RecoveryTargetError):
        require_distinct_domains(primary, recovery)

    assert not nested_root.exists()


def test_invalid_checkpoint_time_fails_before_recovery_root_materializes(
    local_fixture: tuple[Path, dict[str, Any], RecoveryDomain, LocalRecoveryStore],
) -> None:
    recovery = local_fixture[3]
    assert not recovery.root.exists()

    with pytest.raises(RecoveryTargetError):
        _capture(local_fixture, created_at="2026-07-14T23:59:59Z")

    assert not recovery.root.exists()


@pytest.mark.parametrize(
    "schema_attack",
    (
        "CREATE VIEW attacker_view AS SELECT cycle_id FROM scheduled_cycles",
        "CREATE INDEX attacker_index ON scheduled_cycles (lane)",
        "CREATE TRIGGER attacker_trigger AFTER INSERT ON benchmarks BEGIN SELECT 1; END",
        "DROP TRIGGER trg_source_snapshots_revision_update",
    ),
    ids=("extra-view", "extra-index", "extra-trigger", "missing-head-trigger"),
)
def test_checkpoint_rejects_any_nonexact_executable_head_schema(
    local_fixture: tuple[Path, dict[str, Any], RecoveryDomain, LocalRecoveryStore],
    schema_attack: str,
) -> None:
    with sqlite3.connect(local_fixture[0]) as connection:
        connection.execute(schema_attack)
        connection.commit()

    with pytest.raises(RecoveryIntegrityError):
        _capture(local_fixture)

    assert not local_fixture[3].root.exists()


def test_checkpoint_publication_replays_across_a_new_store_instance_and_conflicts(
    local_fixture: tuple[Path, dict[str, Any], RecoveryDomain, LocalRecoveryStore],
) -> None:
    first = _capture(local_fixture)
    recovery = local_fixture[3]
    restarted = LocalRecoveryStore(
        recovery.root,
        failure_domain_id=recovery.failure_domain_id,
    )
    replay = _capture(local_fixture, recovery_store=restarted)
    assert replay == first

    inventory = restarted.inventory_orphans(
        referenced_uris=(),
        object_kind=StorageObjectKind.ARTIFACT,
    )
    publications: list[dict[str, Any]] = []
    for address in inventory.orphan_objects:
        read = restarted.read_snapshot(
            uri=address.uri,
            content_sha256=address.content_sha256,
        )
        try:
            candidate = parse_canonical_recovery_bytes(read.raw_bytes)
        except ValueError:
            continue
        if candidate.get("policyVersion") == "recovery-checkpoint-v1":
            publications.append(candidate)
    assert publications == [first]

    with pytest.raises(RecoveryReplayConflict):
        _capture(
            local_fixture,
            created_at="2026-07-15T14:31:00Z",
            recovery_store=restarted,
        )


def test_checkpoint_source_database_identity_survives_restart_and_blocks_rebinding(
    local_fixture: tuple[Path, dict[str, Any], RecoveryDomain, LocalRecoveryStore],
    tmp_path: Path,
) -> None:
    first = _capture(local_fixture)
    original_identity = first["relationalBackup"]["sourceDatabaseIdentitySha256"]
    copied_source = tmp_path / "same-bytes-different-source.db"
    _sqlite_backup(local_fixture[0], copied_source)
    restarted = LocalRecoveryStore(
        local_fixture[3].root,
        failure_domain_id=local_fixture[3].failure_domain_id,
    )

    with pytest.raises(RecoveryReplayConflict):
        _capture(
            local_fixture,
            database_path=copied_source,
            recovery_store=restarted,
        )

    assert len(original_identity) == 64


@pytest.mark.parametrize(
    ("target_id", "started_at", "finished_at"),
    (
        ("INVALID TARGET", STARTED_AT, FINISHED_AT),
        ("valid-target", "not-a-time", FINISHED_AT),
        ("valid-target", FINISHED_AT, STARTED_AT),
    ),
)
def test_restore_validates_operator_input_before_any_target_mutation(
    local_fixture: tuple[Path, dict[str, Any], RecoveryDomain, LocalRecoveryStore],
    tmp_path: Path,
    target_id: str,
    started_at: str,
    finished_at: str,
) -> None:
    checkpoint = _capture(local_fixture)
    restore_store = LocalRecoveryStore(
        tmp_path / "restore-objects",
        failure_domain_id="fixture-restore-domain",
    )
    database_target = tmp_path / "restore.db"

    with pytest.raises(RecoveryTargetError):
        _restore(
            checkpoint,
            local_fixture[3],
            restore_store,
            database_target,
            target_id=target_id,
            started_at=started_at,
            finished_at=finished_at,
        )

    assert not database_target.exists()
    assert not restore_store.root.exists()


def test_restore_rejects_database_target_nested_in_recovery_root_without_mutation(
    local_fixture: tuple[Path, dict[str, Any], RecoveryDomain, LocalRecoveryStore],
    tmp_path: Path,
) -> None:
    checkpoint = _capture(local_fixture)
    recovery = local_fixture[3]
    before = {
        path.relative_to(recovery.root): path.read_bytes()
        for path in recovery.root.rglob("*")
        if path.is_file()
    }
    restore_store = LocalRecoveryStore(
        tmp_path / "restore-objects",
        failure_domain_id="fixture-restore-domain",
    )
    database_target = recovery.root / "nested" / "restore.db"

    with pytest.raises(RecoveryTargetError):
        _restore(checkpoint, recovery, restore_store, database_target)

    assert not database_target.exists()
    assert not restore_store.root.exists()
    assert before == {
        path.relative_to(recovery.root): path.read_bytes()
        for path in recovery.root.rglob("*")
        if path.is_file()
    }


def test_restore_refuses_noncanonical_target_bytes_before_relational_mutation(
    local_fixture: tuple[Path, dict[str, Any], RecoveryDomain, LocalRecoveryStore],
    tmp_path: Path,
) -> None:
    checkpoint = _capture(local_fixture)
    restore_store = LocalRecoveryStore(
        tmp_path / "restore-objects",
        failure_domain_id="fixture-restore-domain",
    )
    restore_store.root.mkdir(parents=True)
    sentinel = restore_store.root / "operator-owned-sentinel"
    sentinel.write_bytes(b"never delete or reset")
    database_target = tmp_path / "restore.db"

    with pytest.raises(RecoveryTargetError):
        _restore(checkpoint, local_fixture[3], restore_store, database_target)

    assert not database_target.exists()
    assert sentinel.read_bytes() == b"never delete or reset"


def test_restore_rebinds_manifest_verification_receipt_before_relational_mutation(
    local_fixture: tuple[Path, dict[str, Any], RecoveryDomain, LocalRecoveryStore],
    tmp_path: Path,
) -> None:
    checkpoint = _capture(local_fixture)
    attacked = deepcopy(checkpoint)
    attacked["relationalBackup"]["recoveryCopy"]["verificationReceiptId"] = (
        "storage-verification-v1:" + "f" * 64
    )
    attacked["manifest"]["contentSha256"] = "0" * 64
    attacked["manifest"]["contentSha256"] = recovery_contract_digest(attacked)
    validate_checkpoint_manifest(attacked)
    restore_store = LocalRecoveryStore(
        tmp_path / "restore-objects",
        failure_domain_id="fixture-restore-domain",
    )
    database_target = tmp_path / "restore.db"

    with pytest.raises((RecoveryIntegrityError, RecoveryPartialFailure)):
        _restore(attacked, local_fixture[3], restore_store, database_target)

    assert not database_target.exists()


def test_happy_restore_recomputes_identity_inventory_and_exact_target_bytes(
    local_fixture: tuple[Path, dict[str, Any], RecoveryDomain, LocalRecoveryStore],
    tmp_path: Path,
) -> None:
    checkpoint = _capture(local_fixture)
    restore_store = LocalRecoveryStore(
        tmp_path / "restore-objects",
        failure_domain_id="fixture-restore-domain",
    )
    database_target = tmp_path / "restore.db"

    receipt = _restore(checkpoint, local_fixture[3], restore_store, database_target)

    validate_restore_receipt(receipt)
    assert database_target.is_file()
    assert receipt["relationalRestore"]["sourceDatabaseIdentitySha256"] == (
        checkpoint["relationalBackup"]["sourceDatabaseIdentitySha256"]
    )
    assert receipt["relationalRestore"]["matchesCheckpoint"] is True
    assert receipt["objectRestore"]["allVerified"] is True
    assert receipt["objectRestore"]["objectReferenceCount"] == 0
    assert not any(path.is_file() for path in restore_store.root.rglob("*"))
    assert "external_evidence_required" in canonical_recovery_json(receipt)


def test_generic_restore_dispatches_opaque_target_and_measures_full_mutating_path(
    local_fixture: tuple[Path, dict[str, Any], RecoveryDomain, LocalRecoveryStore],
    tmp_path: Path,
) -> None:
    checkpoint = _capture(local_fixture)
    events: list[str] = []
    driver = _OpaqueTargetSQLiteDriver(events)
    target = _ProviderSpecificTarget(tmp_path / "generic-restore.db")
    restore_inner = LocalRecoveryStore(
        tmp_path / "generic-restore-objects",
        failure_domain_id="fixture-generic-restore-domain",
    )
    restore_store = RecoveryDomain(
        failure_domain_id=restore_inner.failure_domain_id,
        store=_RecordingRecoveryStore(restore_inner, events),
    )
    clock = _SequenceClock(
        events,
        datetime(2026, 7, 15, 15, 0, 0, 900_000, tzinfo=timezone.utc),
        datetime(2026, 7, 15, 15, 0, 4, 100_000, tzinfo=timezone.utc),
    )

    receipt = restore_checkpoint_with_driver(
        driver=driver,  # type: ignore[arg-type]
        checkpoint=checkpoint,
        recovery_store=local_fixture[3],
        restore_store=restore_store,
        relational_target=target,
        target_id="fixture-generic-target",
        utc_now=clock,
    )

    validate_restore_receipt(receipt)
    assert driver.received_target is target
    assert driver.received_artifact is not None
    assert driver.received_artifact.artifact_type == checkpoint["relationalBackup"][  # type: ignore[union-attr]
        "artifactType"
    ]
    assert target.database_path.is_file()
    assert receipt["startedAt"] == "2026-07-15T15:00:00Z"
    assert receipt["finishedAt"] == "2026-07-15T15:00:04Z"
    assert receipt["durationMs"] == 4_000
    assert events[0] == "clock:0"
    assert events.index("clock:0") < events.index("inventory:snapshot")
    assert events.index("driver_restore") < len(events) - 1
    assert events[-1] == "clock:1"
    assert events.count("inventory:snapshot") == 2
    assert events.count("inventory:artifact") == 2


def test_generic_restore_rejects_wrong_driver_binding_before_clock_or_mutation(
    local_fixture: tuple[Path, dict[str, Any], RecoveryDomain, LocalRecoveryStore],
    tmp_path: Path,
) -> None:
    checkpoint = _capture(local_fixture)
    events: list[str] = []
    driver = _WrongBoundDriver(events)
    target = _ProviderSpecificTarget(tmp_path / "wrong-driver.db")
    restore_store = LocalRecoveryStore(
        tmp_path / "wrong-driver-objects",
        failure_domain_id="fixture-wrong-driver-domain",
    )
    clock = _SequenceClock(
        events,
        datetime(2026, 7, 15, 15, 0, 0, tzinfo=timezone.utc),
    )

    with pytest.raises(UnsupportedRecoveryArtifact):
        restore_checkpoint_with_driver(
            driver=driver,  # type: ignore[arg-type]
            checkpoint=checkpoint,
            recovery_store=local_fixture[3],
            restore_store=restore_store,
            relational_target=target,
            target_id="fixture-wrong-driver-target",
            utc_now=clock,
        )

    assert events == []
    assert driver.restore_called is False
    assert not target.database_path.exists()
    assert not restore_store.root.exists()


def test_generic_restore_rejects_driver_substituted_result_artifact(
    local_fixture: tuple[Path, dict[str, Any], RecoveryDomain, LocalRecoveryStore],
    tmp_path: Path,
) -> None:
    checkpoint = _capture(local_fixture)
    driver = _WrongResultArtifactDriver([])
    target = _ProviderSpecificTarget(tmp_path / "wrong-result.db")
    restore_store = LocalRecoveryStore(
        tmp_path / "wrong-result-objects",
        failure_domain_id="fixture-wrong-result-domain",
    )

    with pytest.raises(RecoveryIntegrityError):
        restore_checkpoint_with_driver(
            driver=driver,  # type: ignore[arg-type]
            checkpoint=checkpoint,
            recovery_store=local_fixture[3],
            restore_store=restore_store,
            relational_target=target,
            target_id="fixture-wrong-result-target",
            started_at=STARTED_AT,
            finished_at=FINISHED_AT,
        )

    assert driver.restore_called is True
    assert target.database_path.is_file()


def test_measured_restore_clock_start_failure_precedes_any_target_mutation(
    local_fixture: tuple[Path, dict[str, Any], RecoveryDomain, LocalRecoveryStore],
    tmp_path: Path,
) -> None:
    checkpoint = _capture(local_fixture)
    events: list[str] = []
    driver = _OpaqueTargetSQLiteDriver(events)
    target = _ProviderSpecificTarget(tmp_path / "clock-start-failure.db")
    restore_store = LocalRecoveryStore(
        tmp_path / "clock-start-failure-objects",
        failure_domain_id="fixture-clock-start-failure-domain",
    )
    clock = _SequenceClock(events, RuntimeError("clock-secret-must-not-escape"))

    with pytest.raises(RecoveryTargetError) as failure:
        restore_checkpoint_with_driver(
            driver=driver,  # type: ignore[arg-type]
            checkpoint=checkpoint,
            recovery_store=local_fixture[3],
            restore_store=restore_store,
            relational_target=target,
            target_id="fixture-clock-start-failure-target",
            utc_now=clock,
        )

    assert "clock-secret" not in str(failure.value)
    assert failure.value.__cause__ is None
    assert events == ["clock:0"]
    assert not target.database_path.exists()
    assert not restore_store.root.exists()


@pytest.mark.parametrize(
    ("finish_observation", "reason_code"),
    (
        (RuntimeError("clock-secret-must-not-escape"), "RECOVERY_CLOCK_FAILED"),
        (
            datetime(2026, 7, 15, 14, 59, 59, tzinfo=timezone.utc),
            "RECOVERY_CLOCK_NON_MONOTONIC",
        ),
    ),
    ids=("finish-failure", "non-monotonic"),
)
def test_measured_restore_clock_finish_failure_retains_partial_target_without_receipt(
    local_fixture: tuple[Path, dict[str, Any], RecoveryDomain, LocalRecoveryStore],
    tmp_path: Path,
    finish_observation: object,
    reason_code: str,
) -> None:
    checkpoint = _capture(local_fixture)
    events: list[str] = []
    driver = _OpaqueTargetSQLiteDriver(events)
    target = _ProviderSpecificTarget(tmp_path / f"{reason_code}.db")
    restore_inner = LocalRecoveryStore(
        tmp_path / f"{reason_code}-objects",
        failure_domain_id=f"fixture-{reason_code.lower()}-domain",
    )
    restore_store = RecoveryDomain(
        failure_domain_id=restore_inner.failure_domain_id,
        store=_RecordingRecoveryStore(restore_inner, events),
    )
    clock = _SequenceClock(
        events,
        datetime(2026, 7, 15, 15, 0, 0, tzinfo=timezone.utc),
        finish_observation,
    )

    with pytest.raises(RecoveryPartialFailure) as failure:
        restore_checkpoint_with_driver(
            driver=driver,  # type: ignore[arg-type]
            checkpoint=checkpoint,
            recovery_store=local_fixture[3],
            restore_store=restore_store,
            relational_target=target,
            target_id="fixture-clock-finish-failure-target",
            utc_now=clock,
        )

    assert failure.value.reason_code == reason_code
    assert failure.value.relational_target_created is True
    assert failure.value.__cause__ is None
    assert "clock-secret" not in str(failure.value)
    assert events[-1] == "clock:1"
    assert events.index("driver_restore") < events.index("clock:1")
    assert target.database_path.is_file()


def test_sqlite_wrapper_is_receipt_equivalent_to_generic_explicit_timing(
    local_fixture: tuple[Path, dict[str, Any], RecoveryDomain, LocalRecoveryStore],
    tmp_path: Path,
) -> None:
    checkpoint = _capture(local_fixture)
    generic_store = LocalRecoveryStore(
        tmp_path / "generic-equivalence-objects",
        failure_domain_id="fixture-equivalence-domain",
    )
    wrapper_store = LocalRecoveryStore(
        tmp_path / "wrapper-equivalence-objects",
        failure_domain_id="fixture-equivalence-domain",
    )
    generic_target = tmp_path / "generic-equivalence.db"
    wrapper_target = tmp_path / "wrapper-equivalence.db"

    generic = restore_checkpoint_with_driver(
        driver=SQLiteBackupRestoreDriver(),
        checkpoint=checkpoint,
        recovery_store=local_fixture[3],
        restore_store=generic_store,
        relational_target=generic_target,
        target_id="fixture-equivalence-target",
        started_at=STARTED_AT,
        finished_at=FINISHED_AT,
    )
    wrapped = restore_sqlite_checkpoint(
        checkpoint=checkpoint,
        recovery_store=local_fixture[3],
        restore_store=wrapper_store,
        database_target=wrapper_target,
        target_id="fixture-equivalence-target",
        started_at=STARTED_AT,
        finished_at=FINISHED_AT,
    )

    assert wrapped == generic
    assert generic_target.is_file()
    assert wrapper_target.is_file()


class _SecretFailingStore:
    security_posture = StorageSecurityPosture.application_only()

    def __init__(self, root: Path) -> None:
        self.root = root
        self.secret = "provider-password-must-not-escape"

    def store_snapshot(self, *, raw_bytes: bytes, object_kind=StorageObjectKind.SNAPSHOT):  # type: ignore[no-untyped-def]
        raise OSError(f"postgresql://user:{self.secret}@provider.invalid/db")

    def read_snapshot(self, *, uri: str, content_sha256: str):  # type: ignore[no-untyped-def]
        raise AssertionError("read must not follow failed write")

    def verify_snapshot(self, *, uri: str, content_sha256: str):  # type: ignore[no-untyped-def]
        raise AssertionError("verify must not follow failed write")

    def inventory_orphans(self, *, referenced_uris, object_kind=StorageObjectKind.SNAPSHOT):  # type: ignore[no-untyped-def]
        raise AssertionError("inventory is not used before the failed relational copy")


def test_generic_provider_exception_is_redacted_without_secret_cause(
    local_fixture: tuple[Path, dict[str, Any], RecoveryDomain, LocalRecoveryStore],
    tmp_path: Path,
) -> None:
    failing = _SecretFailingStore(tmp_path / "provider")
    recovery = RecoveryDomain(
        failure_domain_id="fixture-recovery-domain",
        store=failing,  # type: ignore[arg-type]
    )

    with pytest.raises(RecoveryPartialFailure) as failure:
        _capture(local_fixture, recovery_store=recovery)

    assert failing.secret not in str(failure.value)
    assert failure.value.__cause__ is None
    assert not failing.root.exists()
