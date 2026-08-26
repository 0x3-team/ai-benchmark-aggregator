"""Adversarial target-perspective acceptance for DATA-10 recovery.

This suite deliberately creates only Alembic-managed temporary SQLite files
and local content-addressed stores.  It never opens the configured ledger
database.  Local evidence proves recovery mechanics, not provider failure-
domain independence or a production RPO/RTO.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
from typing import Any

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.backup import (
    LocalRecoveryStore,
    RecoveryCancelled,
    RecoveryDomain,
    RecoveryError,
    RecoveryIntegrityError,
    RecoveryPartialFailure,
    RecoveryTargetError,
    UnsupportedRecoveryArtifact,
    assert_checkpoint_replay,
    canonical_recovery_json,
    create_sqlite_checkpoint,
    redact_database_locator,
    recovery_cycle_set_digest,
    recovery_contract_digest,
    recovery_object_set_digest,
    recovery_table_inventory_digest,
    restore_sqlite_checkpoint,
    validate_checkpoint_manifest,
    validate_restore_receipt,
)
from app.db import models, operational_repositories, repositories
from app.schemas.operations_contracts import (
    contract_self_digest as operations_self_digest,
    derive_cycle_id,
)
from app.storage.base import (
    SnapshotStorageRunner,
    StorageObjectKind,
    StorageSecurityPosture,
    compute_content_hash,
)
from app.storage.local import LocalSnapshotStorage


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
LEDGER_ROOT = REPOSITORY_ROOT / "ledger"
SHA256 = re.compile(r"^[0-9a-f]{64}$")
CREATED_AT = "2026-07-15T14:30:00Z"
RESTORE_STARTED_AT = "2026-07-15T15:00:00Z"
RESTORE_FINISHED_AT = "2026-07-15T15:00:04Z"
ANCHOR = datetime(2026, 1, 1, tzinfo=timezone.utc)
CADENCE_SECONDS = 43_200
TRIGGER_LABEL = "trigger"


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


def _utc_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _terminal_cycle_payload(
    *,
    environment: str,
    lane: str,
    slot_ordinal: int,
    schedule_policy_revision_id: str,
) -> dict[str, Any]:
    scheduled = ANCHOR + timedelta(seconds=CADENCE_SECONDS * slot_ordinal)
    next_scheduled = scheduled + timedelta(seconds=CADENCE_SECONDS)
    payload: dict[str, Any] = {
        "schemaVersion": "1.0.0",
        "policyVersion": "scheduled-cycle-v1",
        "availability": "operations_record_only",
        "mode": "synthetic_fixture",
        "cycleId": derive_cycle_id(
            environment,
            lane,
            _utc_text(scheduled),
            schedule_policy_revision_id,
        ),
        "environment": environment,
        "lane": lane,
        "schedulePolicyRevisionId": schedule_policy_revision_id,
        "slot": {
            "anchorUtc": _utc_text(ANCHOR),
            "cadenceSeconds": CADENCE_SECONDS,
            "slotOrdinal": slot_ordinal,
            "scheduledFor": _utc_text(scheduled),
            "nextScheduledFor": _utc_text(next_scheduled),
            "completionWindowEndsAt": _utc_text(scheduled + timedelta(hours=2)),
            "catchUpDisposition": "scheduled",
            "missedSlotCount": 0,
        },
        "wakeups": [
            {
                "wakeupId": f"fixture-wakeup-{lane}-{slot_ordinal}",
                "kind": "manual_fixture",
                "observedAt": _utc_text(scheduled + timedelta(seconds=1)),
                "opaqueTriggerId": f"fixture-trigger-{lane}-{slot_ordinal}",
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


def _append_terminal_cycle(session: Session, payload: dict[str, Any]) -> None:
    cycle_intent, jobs = operational_repositories.append_scheduled_cycle_intent(
        session,
        environment=payload["environment"],
        lane=payload["lane"],
        scheduled_for=payload["slot"]["scheduledFor"],
        schedule_policy_revision_id=payload["schedulePolicyRevisionId"],
        mode=payload["mode"],
        job_targets=[],
    )
    assert cycle_intent.cycle_id == payload["cycleId"]
    assert jobs == ()
    terminal = operational_repositories.append_scheduled_cycle(session, payload)
    assert terminal.content_sha256 == payload["manifest"]["contentSha256"]


@pytest.fixture(scope="module")
def database_template(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[Path, dict[str, dict[str, Any]]]:
    root = tmp_path_factory.mktemp("recovery-adversarial-template")
    database_path = root / "template.db"
    command.upgrade(
        _alembic_config(f"sqlite:///{database_path}"),
        "head",
    )
    cycles = {
        "older-same-lane": _terminal_cycle_payload(
            environment="fixture-env",
            lane="recheck",
            slot_ordinal=388,
            schedule_policy_revision_id="fixture-recheck-policy-r1",
        ),
        "older-other-lane": _terminal_cycle_payload(
            environment="fixture-env",
            lane="discovery",
            slot_ordinal=389,
            schedule_policy_revision_id="fixture-discovery-policy-r1",
        ),
        TRIGGER_LABEL: _terminal_cycle_payload(
            environment="fixture-env",
            lane="recheck",
            slot_ordinal=390,
            schedule_policy_revision_id="fixture-recheck-policy-r1",
        ),
        # This intentionally post-dates the trigger.  A checkpoint is bound to
        # one trigger cycle but inventories every completed cycle in its bytes.
        "newer-other-lane": _terminal_cycle_payload(
            environment="fixture-env",
            lane="maintenance",
            slot_ordinal=391,
            schedule_policy_revision_id="fixture-maintenance-policy-r1",
        ),
    }
    engine = _engine(database_path)
    try:
        with Session(engine) as session, session.begin():
            for cycle in cycles.values():
                _append_terminal_cycle(session, cycle)
    finally:
        engine.dispose()
    return database_path, cycles


def _sqlite_backup(source: Path, target: Path) -> None:
    with sqlite3.connect(source) as source_connection, sqlite3.connect(
        target
    ) as target_connection:
        source_connection.backup(target_connection)


@pytest.fixture()
def disposable_database(
    tmp_path: Path,
    database_template: tuple[Path, dict[str, dict[str, Any]]],
) -> tuple[Path, dict[str, dict[str, Any]]]:
    template, cycles = database_template
    database_path = tmp_path / "source.db"
    _sqlite_backup(template, database_path)
    return database_path, deepcopy(cycles)


@pytest.fixture()
def local_domains(
    tmp_path: Path,
) -> tuple[RecoveryDomain, LocalRecoveryStore, Path, Path]:
    primary_root = tmp_path / "primary-objects"
    recovery_root = tmp_path / "recovery-copy"
    primary = RecoveryDomain(
        failure_domain_id="fixture-primary-domain",
        store=LocalSnapshotStorage(primary_root),
    )
    recovery = LocalRecoveryStore(
        recovery_root,
        failure_domain_id="fixture-recovery-domain",
    )
    return primary, recovery, primary_root, recovery_root


def _capture(
    *,
    database_path: Path,
    cycles: Mapping[str, Mapping[str, Any]],
    primary_store: RecoveryDomain | LocalRecoveryStore,
    recovery_store: RecoveryDomain | LocalRecoveryStore,
    created_at: str = CREATED_AT,
    cancel_requested: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    return create_sqlite_checkpoint(
        database_path=database_path,
        trigger_cycle=cycles[TRIGGER_LABEL],
        primary_store=primary_store,
        recovery_store=recovery_store,
        created_at=created_at,
        cancel_requested=cancel_requested,
    )


def _walk(value: Any) -> Iterator[Any]:
    yield value
    if isinstance(value, Mapping):
        for nested in value.values():
            yield from _walk(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _walk(nested)


def _records_with_keys(document: Mapping[str, Any], keys: set[str]) -> list[dict[str, Any]]:
    return [
        dict(value)
        for value in _walk(document)
        if isinstance(value, Mapping) and keys <= set(value)
    ]


def _find_content_file(root: Path, digest: str) -> Path:
    assert SHA256.fullmatch(digest)
    matches = [
        path
        for path in root.rglob("*")
        if path.is_file() and path.name == digest
    ]
    assert len(matches) == 1, f"expected one full-digest recovery key for {digest}"
    return matches[0]


def _head_revision(database_path: Path) -> str:
    with sqlite3.connect(database_path) as connection:
        row = connection.execute("SELECT version_num FROM alembic_version").fetchone()
    assert row is not None and isinstance(row[0], str)
    return row[0]


def _table_inventory(checkpoint: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    records = _records_with_keys(
        checkpoint,
        {"tableName", "rowCount", "rowsetSha256"},
    )
    assert records, "checkpoint must expose per-table row counts and rowset digests"
    result: dict[str, dict[str, Any]] = {}
    for record in records:
        table_name = record["tableName"]
        assert isinstance(table_name, str)
        assert table_name not in result, f"duplicate table inventory: {table_name}"
        result[table_name] = record
    return result


def _source_definition(source_id: str, benchmark_id: str) -> dict[str, Any]:
    return {
        "id": source_id,
        "benchmark_id": benchmark_id,
        "source_name": f"Disposable recovery source {source_id}",
        "source_url": f"https://fixtures.example.test/{source_id}/results.json",
        "source_type": "api",
        "officialness_level": "O1",
        "machine_readable": True,
        "requires_auth": False,
        "supports_history": True,
        "update_cadence": "manual",
        "parser_name": "recovery-fixture-json",
        "parser_version": "1",
        "parser_config": {},
        "status": "active",
        "notes": "Temporary DATA-10 fixture only.",
    }


def _append_unreferenced_snapshot(
    *,
    database_path: Path,
    primary_store: LocalSnapshotStorage,
    source_id: str,
    raw_bytes: bytes,
    rendered_screenshot_uri: str | None = None,
) -> models.SourceSnapshot:
    """Append one retained snapshot and deliberately no claim/reference row."""

    storage_receipt = primary_store.store_snapshot(raw_bytes=raw_bytes)
    benchmark_id = f"benchmark-{source_id}"
    engine = _engine(database_path)
    try:
        with Session(engine) as session, session.begin():
            repositories.upsert_benchmark(
                session,
                {
                    "id": benchmark_id,
                    "canonical_name": benchmark_id,
                    "display_name": f"Fixture {benchmark_id}",
                },
            )
            reconciliation = repositories.reconcile_official_source(
                session,
                _source_definition(source_id, benchmark_id),
            )
            snapshot_fields = {
                "official_source_id": source_id,
                "source_revision_id": reconciliation.revision.id,
                "raw_content_uri": storage_receipt.address.uri,
                "content_hash": storage_receipt.address.content_sha256,
                "content_type": "application/json",
                "http_status": 200,
                "etag": None,
                "last_modified_header": None,
                "fetch_metadata": {
                    "storageReceiptSha256": storage_receipt.receipt_id.split(":")[-1],
                    "storageVerificationReceiptSha256": (
                        storage_receipt.verification_receipt_id.split(":")[-1]
                    ),
                },
                "parser_version": "recovery-fixture-json-v1",
            }
            if rendered_screenshot_uri is None:
                snapshot = repositories.insert_snapshot(session, **snapshot_fields)
            else:
                # Source snapshots are append-only after their first flush.  A
                # malformed screenshot reference therefore has to be part of
                # the original retained row for the recovery audit to see it.
                snapshot = models.SourceSnapshot(
                    **snapshot_fields,
                    rendered_screenshot_uri=rendered_screenshot_uri,
                )
                session.add(snapshot)
                session.flush()
            snapshot_id = snapshot.id
        with Session(engine) as session:
            persisted = session.get(models.SourceSnapshot, snapshot_id)
            assert persisted is not None
            session.expunge(persisted)
            return persisted
    finally:
        engine.dispose()


def _resign_recovery_contract(document: dict[str, Any]) -> dict[str, Any]:
    document["manifest"]["contentSha256"] = "0" * 64
    document["manifest"]["contentSha256"] = recovery_contract_digest(document)
    return document


class _DelegatingStore:
    """Small adversarial wrapper that retains the runner-only store surface."""

    security_posture = StorageSecurityPosture.application_only()

    def __init__(self, delegate: LocalRecoveryStore | LocalSnapshotStorage) -> None:
        self.delegate = delegate
        self.root = delegate.root

    def store_snapshot(
        self,
        *,
        raw_bytes: bytes,
        object_kind: StorageObjectKind = StorageObjectKind.SNAPSHOT,
    ):  # type: ignore[no-untyped-def]
        return self.delegate.store_snapshot(
            raw_bytes=raw_bytes,
            object_kind=object_kind,
        )

    def read_snapshot(self, *, uri: str, content_sha256: str):  # type: ignore[no-untyped-def]
        return self.delegate.read_snapshot(uri=uri, content_sha256=content_sha256)

    def verify_snapshot(self, *, uri: str, content_sha256: str):  # type: ignore[no-untyped-def]
        return self.delegate.verify_snapshot(uri=uri, content_sha256=content_sha256)

    def inventory_orphans(
        self,
        *,
        referenced_uris,
        object_kind: StorageObjectKind = StorageObjectKind.SNAPSHOT,
    ):  # type: ignore[no-untyped-def]
        return self.delegate.inventory_orphans(
            referenced_uris=referenced_uris,
            object_kind=object_kind,
        )


class _MutateSourceOnReadStore(_DelegatingStore):
    def __init__(
        self,
        delegate: LocalSnapshotStorage,
        mutation: Callable[[], None],
    ) -> None:
        super().__init__(delegate)
        self.mutation = mutation
        self.mutated = False

    def read_snapshot(self, *, uri: str, content_sha256: str):  # type: ignore[no-untyped-def]
        if not self.mutated:
            self.mutated = True
            self.mutation()
        return super().read_snapshot(uri=uri, content_sha256=content_sha256)


class _CancelAfterFirstWriteStore(_DelegatingStore):
    def __init__(self, delegate: LocalRecoveryStore) -> None:
        super().__init__(delegate)
        self.write_observed = False

    def store_snapshot(
        self,
        *,
        raw_bytes: bytes,
        object_kind: StorageObjectKind = StorageObjectKind.SNAPSHOT,
    ):  # type: ignore[no-untyped-def]
        receipt = super().store_snapshot(raw_bytes=raw_bytes, object_kind=object_kind)
        self.write_observed = True
        return receipt


class _FailAfterFirstWriteStore(_DelegatingStore):
    def __init__(self, delegate: LocalRecoveryStore) -> None:
        super().__init__(delegate)
        self.write_count = 0

    def store_snapshot(
        self,
        *,
        raw_bytes: bytes,
        object_kind: StorageObjectKind = StorageObjectKind.SNAPSHOT,
    ):  # type: ignore[no-untyped-def]
        receipt = super().store_snapshot(raw_bytes=raw_bytes, object_kind=object_kind)
        self.write_count += 1
        if self.write_count == 1:
            raise OSError("injected partial-write interruption")
        return receipt


class _CorruptAfterClaimedSuccessStore(_DelegatingStore):
    """Return a once-valid receipt only after corrupting its retained bytes."""

    def store_snapshot(
        self,
        *,
        raw_bytes: bytes,
        object_kind: StorageObjectKind = StorageObjectKind.SNAPSHOT,
    ):  # type: ignore[no-untyped-def]
        receipt = super().store_snapshot(raw_bytes=raw_bytes, object_kind=object_kind)
        Path(receipt.address.uri).write_bytes(b"x" * max(1, len(raw_bytes)))
        return receipt


class _ExplodingCapabilityDescriptor:
    def __get__(self, _instance, _owner):  # type: ignore[no-untyped-def]
        raise AssertionError("capability descriptor must not be executed during admission")


class _ForbiddenCapabilityStore(_DelegatingStore):
    overwrite = _ExplodingCapabilityDescriptor()
    configure_retention = _ExplodingCapabilityDescriptor()

    def __init__(self, delegate: LocalRecoveryStore) -> None:
        super().__init__(delegate)
        self.store_called = False

    def store_snapshot(
        self,
        *,
        raw_bytes: bytes,
        object_kind: StorageObjectKind = StorageObjectKind.SNAPSHOT,
    ):  # type: ignore[no-untyped-def]
        self.store_called = True
        return super().store_snapshot(raw_bytes=raw_bytes, object_kind=object_kind)


class _SecretFailingStore(_DelegatingStore):
    secret = "provider-password-must-not-escape"

    def store_snapshot(
        self,
        *,
        raw_bytes: bytes,
        object_kind: StorageObjectKind = StorageObjectKind.SNAPSHOT,
    ):  # type: ignore[no-untyped-def]
        raise OSError(
            "postgresql://backup_user:"
            f"{self.secret}@provider.invalid/ledger?token={self.secret}"
        )


def _restore(
    *,
    checkpoint: Mapping[str, Any],
    recovery_store: RecoveryDomain | LocalRecoveryStore,
    restore_store: RecoveryDomain | LocalRecoveryStore,
    database_target: Path,
    target_id: str = "fixture-new-target-a",
    cancel_requested: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    return restore_sqlite_checkpoint(
        checkpoint=checkpoint,
        recovery_store=recovery_store,
        restore_store=restore_store,
        database_target=database_target,
        target_id=target_id,
        started_at=RESTORE_STARTED_AT,
        finished_at=RESTORE_FINISHED_AT,
        cancel_requested=cancel_requested,
    )


def test_recovery_store_runner_surface_is_delete_admin_and_overwrite_free(
    tmp_path: Path,
) -> None:
    store = LocalRecoveryStore(
        tmp_path / "recovery",
        failure_domain_id="fixture-recovery-domain",
    )

    assert isinstance(store, SnapshotStorageRunner)
    assert store.security_posture.exposes_admin_controls is False
    assert store.security_posture.exposes_delete is False
    for forbidden_name in (
        "delete",
        "delete_snapshot",
        "overwrite",
        "overwrite_snapshot",
        "configure_retention",
        "delete_expired",
        "admin_client",
    ):
        assert not hasattr(store, forbidden_name)


def test_checkpoint_binds_exact_terminal_trigger_and_backup_cycle_census(
    disposable_database: tuple[Path, dict[str, dict[str, Any]]],
    local_domains: tuple[RecoveryDomain, LocalRecoveryStore, Path, Path],
) -> None:
    database_path, cycles = disposable_database
    primary, recovery, _primary_root, _recovery_root = local_domains

    checkpoint = _capture(
        database_path=database_path,
        cycles=cycles,
        primary_store=primary,
        recovery_store=recovery,
    )
    validate_checkpoint_manifest(checkpoint)

    serialized = json.dumps(checkpoint, sort_keys=True, separators=(",", ":"))
    trigger = cycles[TRIGGER_LABEL]
    assert trigger["cycleId"] in serialized
    assert trigger["manifest"]["contentSha256"] in serialized
    for cycle in cycles.values():
        assert cycle["cycleId"] in serialized
        assert cycle["manifest"]["contentSha256"] in serialized

    table_inventory = _table_inventory(checkpoint)
    assert table_inventory["scheduled_cycles"]["rowCount"] == len(cycles)
    backup_path = Path(checkpoint["relationalBackup"]["recoveryCopy"]["uri"])
    assert hashlib.sha256(backup_path.read_bytes()).hexdigest() == checkpoint[
        "relationalBackup"
    ]["contentSha256"]
    with sqlite3.connect(backup_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM scheduled_cycles").fetchone() == (
            len(cycles),
        )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda trigger: trigger.update(state="running"),
        lambda trigger: trigger["manifest"].update(contentSha256="0" * 64),
        lambda trigger: trigger.update(cycleId="cycle_" + "f" * 64),
    ],
    ids=("nonterminal", "wrong-digest", "absent-cycle"),
)
def test_checkpoint_rejects_nonterminal_or_inexact_trigger_cycle(
    disposable_database: tuple[Path, dict[str, dict[str, Any]]],
    local_domains: tuple[RecoveryDomain, LocalRecoveryStore, Path, Path],
    mutation: Callable[[dict[str, Any]], None],
) -> None:
    database_path, cycles = disposable_database
    primary, recovery, _primary_root, _recovery_root = local_domains
    mutation(cycles[TRIGGER_LABEL])

    with pytest.raises((RecoveryIntegrityError, RecoveryError, ValueError)):
        _capture(
            database_path=database_path,
            cycles=cycles,
            primary_store=primary,
            recovery_store=recovery,
        )


def test_checkpoint_inventory_covers_every_application_and_alembic_table(
    disposable_database: tuple[Path, dict[str, dict[str, Any]]],
    local_domains: tuple[RecoveryDomain, LocalRecoveryStore, Path, Path],
) -> None:
    database_path, cycles = disposable_database
    primary, recovery, _primary_root, _recovery_root = local_domains
    checkpoint = _capture(
        database_path=database_path,
        cycles=cycles,
        primary_store=primary,
        recovery_store=recovery,
    )

    inventory = _table_inventory(checkpoint)
    expected_tables = set(models.Base.metadata.tables) | {"alembic_version"}
    assert set(inventory) == expected_tables
    for table_name, row in inventory.items():
        assert type(row["rowCount"]) is int and row["rowCount"] >= 0, table_name
        assert SHA256.fullmatch(row["rowsetSha256"]), table_name
        assert isinstance(row["columnNames"], list) and row["columnNames"], table_name
        assert len(row["columnNames"]) == len(set(row["columnNames"])), table_name
    assert checkpoint["relationalBackup"]["tableInventorySha256"] == (
        recovery_table_inventory_digest(checkpoint["relationalBackup"]["tables"])
    )
    assert (
        checkpoint["relationalBackup"]["schemaDigestAlgorithm"]
        == "sha256-canonical-sqlite-schema-v1"
    )
    assert (
        checkpoint["relationalBackup"]["rowsetDigestAlgorithm"]
        == "sha256-canonical-typed-rowset-v1"
    )
    assert checkpoint["relationalBackup"]["schemaRevision"] == _head_revision(database_path)


def test_cycle_inventory_has_backup_derived_denominator_digest_and_group_watermarks(
    disposable_database: tuple[Path, dict[str, dict[str, Any]]],
    local_domains: tuple[RecoveryDomain, LocalRecoveryStore, Path, Path],
) -> None:
    database_path, cycles = disposable_database
    primary, recovery, _primary_root, _recovery_root = local_domains
    checkpoint = _capture(
        database_path=database_path,
        cycles=cycles,
        primary_store=primary,
        recovery_store=recovery,
    )
    inventory = checkpoint["cycleInventory"]

    assert inventory["completedCycleCount"] == len(cycles)
    assert inventory["cycleSetSha256"] == recovery_cycle_set_digest(inventory["cycles"])
    assert {item["cycleId"] for item in inventory["cycles"]} == {
        cycle["cycleId"] for cycle in cycles.values()
    }
    recheck = [
        watermark
        for watermark in inventory["watermarks"]
        if watermark["environment"] == "fixture-env" and watermark["lane"] == "recheck"
    ]
    assert len(recheck) == 1
    assert recheck[0]["completedCycleCount"] == 2
    assert recheck[0]["latestCycleId"] == cycles[TRIGGER_LABEL]["cycleId"]
    assert recheck[0]["latestScheduledFor"] == cycles[TRIGGER_LABEL]["slot"]["scheduledFor"]


def test_rowset_digest_is_order_independent_and_preserves_json_scalar_types(
    database_template: tuple[Path, dict[str, dict[str, Any]]],
    tmp_path: Path,
) -> None:
    template, cycles = database_template

    def checkpoint_for(
        label: str,
        *,
        reverse: bool,
        typed_value: int | str,
    ) -> dict[str, Any]:
        database_path = tmp_path / f"{label}.db"
        _sqlite_backup(template, database_path)
        rows = [
            models.Benchmark(
                id="stable-a",
                canonical_name="stable-a",
                display_name="Stable A",
                known_metrics=[typed_value, True, None, "1"],
                created_at=ANCHOR,
                updated_at=ANCHOR,
            ),
            models.Benchmark(
                id="stable-b",
                canonical_name="stable-b",
                display_name="Stable B",
                known_metrics=[2, False, None, "2"],
                created_at=ANCHOR,
                updated_at=ANCHOR,
            ),
        ]
        engine = _engine(database_path)
        try:
            with Session(engine) as session, session.begin():
                session.add_all(list(reversed(rows)) if reverse else rows)
        finally:
            engine.dispose()
        primary = RecoveryDomain(
            failure_domain_id=f"primary-{label}",
            store=LocalSnapshotStorage(tmp_path / f"primary-{label}"),
        )
        recovery = LocalRecoveryStore(
            tmp_path / f"recovery-{label}",
            failure_domain_id=f"recovery-{label}",
        )
        return _capture(
            database_path=database_path,
            cycles=cycles,
            primary_store=primary,
            recovery_store=recovery,
        )

    forward = checkpoint_for("forward", reverse=False, typed_value=1)
    reversed_insert = checkpoint_for("reversed", reverse=True, typed_value=1)
    string_typed = checkpoint_for("string-typed", reverse=False, typed_value="1")

    forward_digest = _table_inventory(forward)["benchmarks"]["rowsetSha256"]
    assert _table_inventory(reversed_insert)["benchmarks"]["rowsetSha256"] == forward_digest
    assert _table_inventory(string_typed)["benchmarks"]["rowsetSha256"] != forward_digest


def test_zero_referenced_objects_is_an_explicit_zero_denominator(
    disposable_database: tuple[Path, dict[str, dict[str, Any]]],
    local_domains: tuple[RecoveryDomain, LocalRecoveryStore, Path, Path],
) -> None:
    database_path, cycles = disposable_database
    primary, recovery, _primary_root, _recovery_root = local_domains
    checkpoint = _capture(
        database_path=database_path,
        cycles=cycles,
        primary_store=primary,
        recovery_store=recovery,
    )

    snapshot_counts = _records_with_keys(checkpoint, {"sourceSnapshotRowCount"})
    artifact_counts = _records_with_keys(checkpoint, {"governedArtifactCount"})
    assert len(snapshot_counts) == 1
    assert snapshot_counts[0]["sourceSnapshotRowCount"] == 0
    assert len(artifact_counts) == 1
    assert artifact_counts[0]["governedArtifactCount"] == 0
    assert not _records_with_keys(
        checkpoint,
        {"referenceType", "referenceId", "sourceLogicalUri", "byteLength", "contentSha256"},
    )


def test_same_declared_or_aliased_local_failure_domain_is_rejected(
    disposable_database: tuple[Path, dict[str, dict[str, Any]]],
    tmp_path: Path,
) -> None:
    database_path, cycles = disposable_database
    shared_root = tmp_path / "shared-store"
    primary_store = LocalSnapshotStorage(shared_root)
    primary = RecoveryDomain(
        failure_domain_id="same-domain",
        store=primary_store,
    )

    same_declared = LocalRecoveryStore(
        tmp_path / "declared-alias",
        failure_domain_id="same-domain",
    )
    with pytest.raises((RecoveryIntegrityError, RecoveryError, ValueError)):
        _capture(
            database_path=database_path,
            cycles=cycles,
            primary_store=primary,
            recovery_store=same_declared,
        )

    os.symlink(shared_root, tmp_path / "filesystem-alias", target_is_directory=True)
    aliased = LocalRecoveryStore(
        tmp_path / "filesystem-alias",
        failure_domain_id="different-label-cannot-hide-an-alias",
    )
    with pytest.raises((RecoveryIntegrityError, RecoveryError, ValueError)):
        _capture(
            database_path=database_path,
            cycles=cycles,
            primary_store=primary,
            recovery_store=aliased,
        )

    primary_parent_root = tmp_path / "primary-parent"
    primary_parent = RecoveryDomain(
        failure_domain_id="primary-parent-domain",
        store=LocalSnapshotStorage(primary_parent_root),
    )
    nested_recovery = LocalRecoveryStore(
        primary_parent_root / "nested-recovery",
        failure_domain_id="nested-recovery-domain",
    )
    with pytest.raises((RecoveryIntegrityError, RecoveryError, ValueError)):
        _capture(
            database_path=database_path,
            cycles=cycles,
            primary_store=primary_parent,
            recovery_store=nested_recovery,
        )

    recovery_parent_root = tmp_path / "recovery-parent"
    recovery_parent = LocalRecoveryStore(
        recovery_parent_root,
        failure_domain_id="recovery-parent-domain",
    )
    nested_primary = RecoveryDomain(
        failure_domain_id="nested-primary-domain",
        store=LocalSnapshotStorage(recovery_parent_root / "nested-primary"),
    )
    with pytest.raises((RecoveryIntegrityError, RecoveryError, ValueError)):
        _capture(
            database_path=database_path,
            cycles=cycles,
            primary_store=nested_primary,
            recovery_store=recovery_parent,
        )


def test_store_with_hidden_overwrite_or_admin_descriptor_is_rejected_before_use(
    tmp_path: Path,
) -> None:
    forbidden = _ForbiddenCapabilityStore(
        LocalRecoveryStore(
            tmp_path / "recovery",
            failure_domain_id="fixture-recovery-domain",
        )
    )
    with pytest.raises((RecoveryIntegrityError, RecoveryError, ValueError)):
        RecoveryDomain(
            failure_domain_id="fixture-recovery-domain",
            store=forbidden,
        )
    assert forbidden.store_called is False


def test_database_locator_redaction_never_leaks_password_or_query_secret() -> None:
    secret = "correct-horse-battery-staple"
    locator = (
        "postgresql+psycopg://recovery_user:"
        f"{secret}@db.internal:5432/ledger?sslmode=require&token={secret}"
    )
    redacted = redact_database_locator(locator)

    assert secret not in redacted
    assert "token=" not in redacted
    assert "db.internal" in redacted


def test_checkpoint_and_failure_text_do_not_expose_source_database_path_secret(
    database_template: tuple[Path, dict[str, dict[str, Any]]],
    tmp_path: Path,
) -> None:
    template, cycles = database_template
    secret = "dsn-secret-correct-horse"
    secret_root = tmp_path / f"database-password-{secret}"
    secret_root.mkdir()
    database_path = secret_root / "source.db"
    _sqlite_backup(template, database_path)
    primary = RecoveryDomain(
        failure_domain_id="fixture-primary-domain",
        store=LocalSnapshotStorage(tmp_path / "primary"),
    )
    recovery = LocalRecoveryStore(
        tmp_path / "recovery",
        failure_domain_id="fixture-recovery-domain",
    )

    checkpoint = _capture(
        database_path=database_path,
        cycles=cycles,
        primary_store=primary,
        recovery_store=recovery,
    )
    assert secret not in json.dumps(checkpoint, sort_keys=True)

    attacked_cycles = deepcopy(cycles)
    attacked_cycles[TRIGGER_LABEL]["cycleId"] = "cycle_" + "e" * 64
    with pytest.raises(RecoveryError) as failure:
        _capture(
            database_path=database_path,
            cycles=attacked_cycles,
            primary_store=primary,
            recovery_store=recovery,
        )
    assert secret not in str(failure.value)


def test_injected_store_exception_is_wrapped_without_provider_secret_text(
    disposable_database: tuple[Path, dict[str, dict[str, Any]]],
    local_domains: tuple[RecoveryDomain, LocalRecoveryStore, Path, Path],
) -> None:
    database_path, cycles = disposable_database
    primary, recovery, _primary_root, _recovery_root = local_domains
    failing_store = _SecretFailingStore(recovery)
    failing_domain = RecoveryDomain(
        failure_domain_id="fixture-recovery-domain",
        store=failing_store,
    )

    with pytest.raises(RecoveryPartialFailure) as failure:
        _capture(
            database_path=database_path,
            cycles=cycles,
            primary_store=primary,
            recovery_store=failing_domain,
        )
    assert failing_store.secret not in str(failure.value)
    assert "postgresql://" not in str(failure.value)
    assert failure.value.__cause__ is None or failing_store.secret not in str(
        failure.value.__cause__
    )


def test_local_checkpoint_cannot_claim_provider_independence_or_production_rpo_rto(
    disposable_database: tuple[Path, dict[str, dict[str, Any]]],
    local_domains: tuple[RecoveryDomain, LocalRecoveryStore, Path, Path],
) -> None:
    database_path, cycles = disposable_database
    primary, recovery, _primary_root, _recovery_root = local_domains
    checkpoint = _capture(
        database_path=database_path,
        cycles=cycles,
        primary_store=primary,
        recovery_store=recovery,
    )
    rendered = json.dumps(checkpoint, sort_keys=True).lower()

    assert "local" in rendered
    assert "external_evidence_required" in rendered
    for forbidden_claim in (
        '"providerindependenceproven": true',
        '"productionrpomet": true',
        '"productionrtomet": true',
        '"rpoproven": true',
        '"rtoproven": true',
    ):
        assert forbidden_claim not in rendered.replace(" ", "")


def test_every_retained_snapshot_is_copied_once_even_without_a_claim(
    disposable_database: tuple[Path, dict[str, dict[str, Any]]],
    local_domains: tuple[RecoveryDomain, LocalRecoveryStore, Path, Path],
) -> None:
    database_path, cycles = disposable_database
    primary, recovery, _primary_root, recovery_root = local_domains
    assert isinstance(primary.store, LocalSnapshotStorage)
    raw_bytes = b'{"fixture":"retained-unreferenced-snapshot"}\n'
    snapshot = _append_unreferenced_snapshot(
        database_path=database_path,
        primary_store=primary.store,
        source_id="recovery-source-a",
        raw_bytes=raw_bytes,
    )

    engine = _engine(database_path)
    try:
        with Session(engine) as session:
            assert session.scalar(select(func.count()).select_from(models.ResultClaim)) == 0
    finally:
        engine.dispose()

    checkpoint = _capture(
        database_path=database_path,
        cycles=cycles,
        primary_store=primary,
        recovery_store=recovery,
    )
    validate_checkpoint_manifest(checkpoint)

    objects = checkpoint["objectManifest"]["objects"]
    assert checkpoint["objectManifest"]["sourceSnapshotRowCount"] == 1
    assert checkpoint["objectManifest"]["governedArtifactCount"] == 0
    assert len(objects) == 1
    assert objects[0]["referenceType"] == "source_snapshot_raw"
    assert objects[0]["referenceId"] == snapshot.id
    assert objects[0]["sourceLogicalUri"] == snapshot.raw_content_uri
    assert Path(objects[0]["sourceLogicalUri"]).name == snapshot.content_hash
    assert objects[0]["contentSha256"] == compute_content_hash(raw_bytes)
    assert objects[0]["byteLength"] == len(raw_bytes)
    assert objects[0]["recoveryCopy"]["contentSha256"] == compute_content_hash(raw_bytes)
    assert objects[0]["recoveryCopy"]["byteLength"] == len(raw_bytes)
    assert objects[0]["recoveryCopy"]["key"]
    copied = _find_content_file(recovery_root, compute_content_hash(raw_bytes))
    assert copied.read_bytes() == raw_bytes


def test_equal_bytes_for_two_snapshot_identities_are_enumerated_twice_but_stored_once(
    disposable_database: tuple[Path, dict[str, dict[str, Any]]],
    local_domains: tuple[RecoveryDomain, LocalRecoveryStore, Path, Path],
) -> None:
    database_path, cycles = disposable_database
    primary, recovery, _primary_root, recovery_root = local_domains
    assert isinstance(primary.store, LocalSnapshotStorage)
    raw_bytes = b'{"fixture":"shared-content-two-logical-snapshots"}\n'
    first = _append_unreferenced_snapshot(
        database_path=database_path,
        primary_store=primary.store,
        source_id="recovery-source-first",
        raw_bytes=raw_bytes,
    )
    second = _append_unreferenced_snapshot(
        database_path=database_path,
        primary_store=primary.store,
        source_id="recovery-source-second",
        raw_bytes=raw_bytes,
    )

    checkpoint = _capture(
        database_path=database_path,
        cycles=cycles,
        primary_store=primary,
        recovery_store=recovery,
    )
    objects = checkpoint["objectManifest"]["objects"]
    assert checkpoint["objectManifest"]["sourceSnapshotRowCount"] == 2
    assert checkpoint["objectManifest"]["objectReferenceCount"] == 2
    assert checkpoint["objectManifest"]["uniqueObjectCount"] == 1
    assert checkpoint["objectManifest"]["objectSetSha256"] == (
        recovery_object_set_digest(objects)
    )
    assert [item["referenceId"] for item in objects] == sorted([first.id, second.id])
    assert {item["contentSha256"] for item in objects} == {
        compute_content_hash(raw_bytes)
    }
    assert len({item["recoveryCopy"]["key"] for item in objects}) == 1
    assert _find_content_file(recovery_root, compute_content_hash(raw_bytes)).read_bytes() == raw_bytes


def test_missing_source_snapshot_bytes_fail_without_a_checkpoint_publication(
    disposable_database: tuple[Path, dict[str, dict[str, Any]]],
    local_domains: tuple[RecoveryDomain, LocalRecoveryStore, Path, Path],
) -> None:
    database_path, cycles = disposable_database
    primary, recovery, _primary_root, recovery_root = local_domains
    assert isinstance(primary.store, LocalSnapshotStorage)
    raw_bytes = b'{"fixture":"will-be-missing"}\n'
    snapshot = _append_unreferenced_snapshot(
        database_path=database_path,
        primary_store=primary.store,
        source_id="recovery-source-missing",
        raw_bytes=raw_bytes,
    )
    Path(snapshot.raw_content_uri).unlink()

    with pytest.raises((RecoveryIntegrityError, RecoveryPartialFailure, RecoveryError)):
        _capture(
            database_path=database_path,
            cycles=cycles,
            primary_store=primary,
            recovery_store=recovery,
        )

    # A relational staging copy may remain for exact resume, but a successful
    # self-digested checkpoint contract must not have been published.
    assert not any(
        b"recovery-checkpoint-v1" in path.read_bytes()
        for path in recovery_root.rglob("*")
        if path.is_file()
    )


def test_non_null_rendered_screenshot_without_typed_digest_contract_fails_closed(
    disposable_database: tuple[Path, dict[str, dict[str, Any]]],
    local_domains: tuple[RecoveryDomain, LocalRecoveryStore, Path, Path],
) -> None:
    database_path, cycles = disposable_database
    primary, recovery, _primary_root, _recovery_root = local_domains
    assert isinstance(primary.store, LocalSnapshotStorage)
    raw_bytes = b'{"fixture":"raw-has-digest-but-screenshot-does-not"}\n'
    raw_receipt = primary.store.store_snapshot(raw_bytes=raw_bytes)
    _append_unreferenced_snapshot(
        database_path=database_path,
        primary_store=primary.store,
        source_id="recovery-source-screenshot",
        raw_bytes=raw_bytes,
        rendered_screenshot_uri=raw_receipt.address.uri,
    )

    with pytest.raises((UnsupportedRecoveryArtifact, RecoveryIntegrityError, RecoveryError)):
        _capture(
            database_path=database_path,
            cycles=cycles,
            primary_store=primary,
            recovery_store=recovery,
        )


def test_opaque_model_artifact_hash_is_not_promoted_to_a_governed_artifact(
    disposable_database: tuple[Path, dict[str, dict[str, Any]]],
    local_domains: tuple[RecoveryDomain, LocalRecoveryStore, Path, Path],
) -> None:
    database_path, cycles = disposable_database
    primary, recovery, _primary_root, _recovery_root = local_domains
    engine = _engine(database_path)
    try:
        with Session(engine) as session, session.begin():
            session.add(
                models.ModelEntity(
                    id="fixture-model-with-opaque-artifact",
                    canonical_name="fixture-model-with-opaque-artifact",
                    display_name="Fixture model with opaque artifact",
                    entity_type="model",
                    artifact_hash="a" * 64,
                )
            )
    finally:
        engine.dispose()

    checkpoint = _capture(
        database_path=database_path,
        cycles=cycles,
        primary_store=primary,
        recovery_store=recovery,
    )
    assert checkpoint["objectManifest"]["governedArtifactCount"] == 0
    assert checkpoint["objectManifest"]["objects"] == []


def test_inventory_is_derived_from_backup_bytes_not_a_racing_source_database(
    disposable_database: tuple[Path, dict[str, dict[str, Any]]],
    local_domains: tuple[RecoveryDomain, LocalRecoveryStore, Path, Path],
) -> None:
    database_path, cycles = disposable_database
    primary, recovery, _primary_root, _recovery_root = local_domains
    assert isinstance(primary.store, LocalSnapshotStorage)
    _append_unreferenced_snapshot(
        database_path=database_path,
        primary_store=primary.store,
        source_id="recovery-race-source",
        raw_bytes=b'{"fixture":"forces-post-backup-read"}\n',
    )

    late_cycle = _terminal_cycle_payload(
        environment="fixture-env",
        lane="discovery",
        slot_ordinal=392,
        schedule_policy_revision_id="fixture-discovery-policy-r1",
    )

    def mutate_source_after_backup() -> None:
        engine = _engine(database_path)
        try:
            with Session(engine) as session, session.begin():
                _append_terminal_cycle(session, late_cycle)
                repositories.upsert_benchmark(
                    session,
                    {
                        "id": "late-racing-benchmark",
                        "canonical_name": "late-racing-benchmark",
                        "display_name": "Late racing benchmark",
                    },
                )
        finally:
            engine.dispose()

    racing_primary = RecoveryDomain(
        failure_domain_id=primary.failure_domain_id,
        store=_MutateSourceOnReadStore(primary.store, mutate_source_after_backup),
    )
    checkpoint = _capture(
        database_path=database_path,
        cycles=cycles,
        primary_store=racing_primary,
        recovery_store=recovery,
    )

    assert racing_primary.store.mutated is True
    inventory = _table_inventory(checkpoint)
    assert inventory["scheduled_cycles"]["rowCount"] == len(cycles)
    assert inventory["benchmarks"]["rowCount"] == 1  # snapshot's benchmark only
    assert late_cycle["cycleId"] not in canonical_recovery_json(checkpoint)
    engine = _engine(database_path)
    try:
        with Session(engine) as session:
            assert (
                session.scalar(select(func.count()).select_from(models.ScheduledCycle))
                == len(cycles) + 1
            )
            assert session.scalar(select(func.count()).select_from(models.Benchmark)) == 2
    finally:
        engine.dispose()


def test_checkpoint_exact_replay_is_deterministic_and_changed_publication_conflicts(
    disposable_database: tuple[Path, dict[str, dict[str, Any]]],
    local_domains: tuple[RecoveryDomain, LocalRecoveryStore, Path, Path],
) -> None:
    database_path, cycles = disposable_database
    primary, recovery, _primary_root, _recovery_root = local_domains
    first = _capture(
        database_path=database_path,
        cycles=cycles,
        primary_store=primary,
        recovery_store=recovery,
    )
    replay = _capture(
        database_path=database_path,
        cycles=cycles,
        primary_store=primary,
        recovery_store=recovery,
    )
    assert_checkpoint_replay(first, replay)
    assert replay == first

    with pytest.raises((RecoveryIntegrityError, RecoveryError, ValueError)):
        _capture(
            database_path=database_path,
            cycles=cycles,
            primary_store=primary,
            recovery_store=recovery,
            created_at="2026-07-15T14:31:00Z",
        )


def test_cancelled_or_partial_checkpoint_never_masquerades_as_published_and_can_resume(
    disposable_database: tuple[Path, dict[str, dict[str, Any]]],
    local_domains: tuple[RecoveryDomain, LocalRecoveryStore, Path, Path],
) -> None:
    database_path, cycles = disposable_database
    primary, recovery, _primary_root, _recovery_root = local_domains
    cancel_store = _CancelAfterFirstWriteStore(recovery)
    cancel_domain = RecoveryDomain(
        failure_domain_id="fixture-recovery-domain",
        store=cancel_store,
    )

    with pytest.raises(RecoveryCancelled):
        _capture(
            database_path=database_path,
            cycles=cycles,
            primary_store=primary,
            recovery_store=cancel_domain,
            cancel_requested=lambda: cancel_store.write_observed,
        )

    resumed = _capture(
        database_path=database_path,
        cycles=cycles,
        primary_store=primary,
        recovery_store=recovery,
    )
    validate_checkpoint_manifest(resumed)

    other_recovery = LocalRecoveryStore(
        recovery.root.parent / "partial-recovery",
        failure_domain_id="fixture-partial-recovery-domain",
    )
    partial_domain = RecoveryDomain(
        failure_domain_id="fixture-partial-recovery-domain",
        store=_FailAfterFirstWriteStore(other_recovery),
    )
    with pytest.raises((RecoveryPartialFailure, RecoveryIntegrityError, RecoveryError)):
        _capture(
            database_path=database_path,
            cycles=cycles,
            primary_store=primary,
            recovery_store=partial_domain,
        )


def test_store_receipt_is_not_trusted_without_full_independent_readback(
    disposable_database: tuple[Path, dict[str, dict[str, Any]]],
    local_domains: tuple[RecoveryDomain, LocalRecoveryStore, Path, Path],
) -> None:
    database_path, cycles = disposable_database
    primary, recovery, _primary_root, _recovery_root = local_domains
    corrupting_domain = RecoveryDomain(
        failure_domain_id="fixture-recovery-domain",
        store=_CorruptAfterClaimedSuccessStore(recovery),
    )

    with pytest.raises((RecoveryIntegrityError, RecoveryPartialFailure, RecoveryError)):
        _capture(
            database_path=database_path,
            cycles=cycles,
            primary_store=primary,
            recovery_store=corrupting_domain,
        )


def test_recovery_copy_locators_prove_conditional_content_addressing_without_order_outcome(
    disposable_database: tuple[Path, dict[str, dict[str, Any]]],
    local_domains: tuple[RecoveryDomain, LocalRecoveryStore, Path, Path],
) -> None:
    database_path, cycles = disposable_database
    primary, recovery, _primary_root, _recovery_root = local_domains
    assert isinstance(primary.store, LocalSnapshotStorage)
    _append_unreferenced_snapshot(
        database_path=database_path,
        primary_store=primary.store,
        source_id="conditional-address-source",
        raw_bytes=b'{"fixture":"conditional-address"}\n',
    )
    checkpoint = _capture(
        database_path=database_path,
        cycles=cycles,
        primary_store=primary,
        recovery_store=recovery,
    )
    copies = [checkpoint["relationalBackup"]["recoveryCopy"]] + [
        item["recoveryCopy"] for item in checkpoint["objectManifest"]["objects"]
    ]
    for copy_locator in copies:
        assert SHA256.fullmatch(copy_locator["contentSha256"])
        assert copy_locator["contentSha256"] in copy_locator["key"]
        assert copy_locator["byteLength"] >= 0
        assert copy_locator["writePrecondition"] in {
            "atomic_no_replace",
            "if_none_match_wildcard",
        }
        assert re.fullmatch(
            r"storage-verification-v1:[0-9a-f]{64}",
            copy_locator["verificationReceiptId"],
        )
        assert "outcome" not in copy_locator
        assert "storeReceiptId" not in copy_locator
    for value in _walk(checkpoint):
        if not isinstance(value, Mapping):
            continue
        for key, field_value in value.items():
            if key.endswith("Sha256") and field_value is not None:
                assert isinstance(field_value, str) and SHA256.fullmatch(field_value), key


def test_existing_wrong_bytes_at_content_address_are_never_overwritten_or_repaired(
    disposable_database: tuple[Path, dict[str, dict[str, Any]]],
    local_domains: tuple[RecoveryDomain, LocalRecoveryStore, Path, Path],
) -> None:
    database_path, cycles = disposable_database
    primary, recovery, _primary_root, _recovery_root = local_domains
    checkpoint = _capture(
        database_path=database_path,
        cycles=cycles,
        primary_store=primary,
        recovery_store=recovery,
    )
    recovery_database = Path(checkpoint["relationalBackup"]["recoveryCopy"]["uri"])
    collided = b"attacker bytes occupying a full-digest recovery key"
    recovery_database.write_bytes(collided)

    with pytest.raises((RecoveryIntegrityError, RecoveryPartialFailure, RecoveryError)):
        _capture(
            database_path=database_path,
            cycles=cycles,
            primary_store=primary,
            recovery_store=recovery,
        )
    assert recovery_database.read_bytes() == collided


def test_happy_restore_uses_new_targets_preserves_source_uri_and_maps_restored_address(
    disposable_database: tuple[Path, dict[str, dict[str, Any]]],
    local_domains: tuple[RecoveryDomain, LocalRecoveryStore, Path, Path],
    tmp_path: Path,
) -> None:
    database_path, cycles = disposable_database
    primary, recovery, primary_root, recovery_root = local_domains
    assert isinstance(primary.store, LocalSnapshotStorage)
    raw_bytes = b'{"fixture":"restore-object-mapping"}\n'
    snapshot = _append_unreferenced_snapshot(
        database_path=database_path,
        primary_store=primary.store,
        source_id="recovery-restore-source",
        raw_bytes=raw_bytes,
    )
    checkpoint = _capture(
        database_path=database_path,
        cycles=cycles,
        primary_store=primary,
        recovery_store=recovery,
    )
    source_database_sha256 = hashlib.sha256(database_path.read_bytes()).hexdigest()
    source_object_sha256 = hashlib.sha256(Path(snapshot.raw_content_uri).read_bytes()).hexdigest()
    recovery_files_before = {
        path.relative_to(recovery_root): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in recovery_root.rglob("*")
        if path.is_file()
    }

    restore_store = LocalRecoveryStore(
        tmp_path / "restored-objects",
        failure_domain_id="fixture-new-object-target-domain",
    )
    restored_database = tmp_path / "restored.db"
    receipt = _restore(
        checkpoint=checkpoint,
        recovery_store=recovery,
        restore_store=restore_store,
        database_target=restored_database,
    )
    validate_restore_receipt(receipt)
    assert receipt["manifest"]["contentSha256"] == recovery_contract_digest(receipt)
    assert canonical_recovery_json(receipt) == canonical_recovery_json(deepcopy(receipt))
    assert receipt["durationMs"] == 4_000
    relational_restore = receipt["relationalRestore"]
    assert relational_restore["matchesCheckpoint"] is True
    assert relational_restore["schemaRevision"] == checkpoint["relationalBackup"][
        "schemaRevision"
    ]
    assert relational_restore["schemaSha256"] == checkpoint["relationalBackup"][
        "schemaSha256"
    ]
    assert relational_restore["tableInventorySha256"] == checkpoint[
        "relationalBackup"
    ]["tableInventorySha256"]
    assert (
        relational_restore["schemaDigestAlgorithm"]
        == "sha256-canonical-sqlite-schema-v1"
    )
    assert (
        relational_restore["rowsetDigestAlgorithm"]
        == "sha256-canonical-typed-rowset-v1"
    )
    assert relational_restore["integrity"]["sqliteIntegrityCheck"] == "ok"
    assert relational_restore["integrity"]["foreignKeyViolationCount"] == 0
    semantic_audit = relational_restore["integrity"]["semanticLineageAudit"]
    assert semantic_audit["status"] == "passed"
    assert semantic_audit["familyCount"] == len(semantic_audit["families"])
    assert semantic_audit["rowCount"] == sum(
        family["rowCount"] for family in semantic_audit["families"]
    )
    assert {
        "source_revision_decisions",
        "claim_review_decisions",
        "claim_publication_decisions",
        "identity_decisions",
        "ops_incident_events",
        "review_work_item_events",
        "notification_receipts",
    } <= {family["family"] for family in semantic_audit["families"]}
    assert receipt["objectRestore"]["allVerified"] is True
    assert receipt["objectRestore"]["objectReferenceCount"] == 1

    with sqlite3.connect(restored_database) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("SELECT COUNT(*) FROM scheduled_cycles").fetchone() == (
            len(cycles),
        )
        restored_row = connection.execute(
            "SELECT raw_content_uri, content_hash FROM source_snapshots WHERE id = ?",
            (snapshot.id,),
        ).fetchone()
    assert restored_row == (snapshot.raw_content_uri, snapshot.content_hash)

    restored_mappings = _records_with_keys(
        receipt,
        {"sourceLogicalUri", "contentSha256", "restoredCopy"},
    )
    assert len(restored_mappings) == 1
    mapping = restored_mappings[0]
    assert mapping["sourceLogicalUri"] == snapshot.raw_content_uri
    assert mapping["contentSha256"] == snapshot.content_hash
    assert mapping["restoredCopy"]["uri"] != snapshot.raw_content_uri
    assert mapping["restoredCopy"]["contentSha256"] == snapshot.content_hash
    assert Path(mapping["restoredCopy"]["uri"]).read_bytes() == raw_bytes

    # Recovery is verification, not a hidden runtime cutover or old-target mutation.
    assert hashlib.sha256(database_path.read_bytes()).hexdigest() == source_database_sha256
    assert hashlib.sha256(Path(snapshot.raw_content_uri).read_bytes()).hexdigest() == source_object_sha256
    assert primary_root.exists()
    assert {
        path.relative_to(recovery_root): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in recovery_root.rglob("*")
        if path.is_file()
    } == recovery_files_before
    rendered = json.dumps(receipt, sort_keys=True).lower().replace(" ", "")
    assert '"runtimecutoverperformed":true' not in rendered
    assert '"providerindependenceproven":true' not in rendered
    assert '"productionrpomet":true' not in rendered
    assert '"productionrtomet":true' not in rendered


@pytest.mark.parametrize(
    "forgery",
    ("inventory-failed", "objects-unverified", "duration-mismatch", "digest-substitution"),
)
def test_forged_restore_success_receipt_is_rejected_even_when_resigned(
    disposable_database: tuple[Path, dict[str, dict[str, Any]]],
    local_domains: tuple[RecoveryDomain, LocalRecoveryStore, Path, Path],
    tmp_path: Path,
    forgery: str,
) -> None:
    database_path, cycles = disposable_database
    primary, recovery, _primary_root, _recovery_root = local_domains
    checkpoint = _capture(
        database_path=database_path,
        cycles=cycles,
        primary_store=primary,
        recovery_store=recovery,
    )
    restore_store = LocalRecoveryStore(
        tmp_path / f"restore-objects-{forgery}",
        failure_domain_id=f"fixture-new-target-domain-{forgery}",
    )
    receipt = _restore(
        checkpoint=checkpoint,
        recovery_store=recovery,
        restore_store=restore_store,
        database_target=tmp_path / f"restored-{forgery}.db",
        target_id=f"target-{forgery}",
    )
    forged = deepcopy(receipt)
    if forgery == "inventory-failed":
        forged["relationalRestore"]["matchesCheckpoint"] = False
    elif forgery == "objects-unverified":
        forged["objectRestore"]["allVerified"] = False
    elif forgery == "duration-mismatch":
        forged["durationMs"] += 1
    else:
        forged["relationalRestore"]["sourceBackupContentSha256"] = "d" * 64

    with pytest.raises((RecoveryIntegrityError, RecoveryError, ValueError, TypeError)):
        _resign_recovery_contract(forged)
        validate_restore_receipt(forged)


def test_restore_refuses_same_recovery_nonempty_and_old_database_targets_without_mutation(
    disposable_database: tuple[Path, dict[str, dict[str, Any]]],
    local_domains: tuple[RecoveryDomain, LocalRecoveryStore, Path, Path],
    tmp_path: Path,
) -> None:
    database_path, cycles = disposable_database
    primary, recovery, _primary_root, _recovery_root = local_domains
    checkpoint = _capture(
        database_path=database_path,
        cycles=cycles,
        primary_store=primary,
        recovery_store=recovery,
    )
    restore_store = LocalRecoveryStore(
        tmp_path / "restore-objects",
        failure_domain_id="fixture-new-object-target-domain",
    )

    same_before = database_path.read_bytes()
    with pytest.raises(RecoveryTargetError):
        _restore(
            checkpoint=checkpoint,
            recovery_store=recovery,
            restore_store=restore_store,
            database_target=database_path,
            target_id="same-source-target",
        )
    assert database_path.read_bytes() == same_before

    alias_target = tmp_path / "source-database-alias.db"
    os.symlink(database_path, alias_target)
    with pytest.raises(RecoveryTargetError):
        _restore(
            checkpoint=checkpoint,
            recovery_store=recovery,
            restore_store=restore_store,
            database_target=alias_target,
            target_id="same-source-alias-target",
        )
    assert database_path.read_bytes() == same_before
    assert alias_target.is_symlink()

    recovery_database = Path(checkpoint["relationalBackup"]["recoveryCopy"]["uri"])
    recovery_before = recovery_database.read_bytes()
    with pytest.raises(RecoveryTargetError):
        _restore(
            checkpoint=checkpoint,
            recovery_store=recovery,
            restore_store=restore_store,
            database_target=recovery_database,
            target_id="same-recovery-target",
        )
    assert recovery_database.read_bytes() == recovery_before

    nonempty = tmp_path / "nonempty-target.db"
    nonempty.write_bytes(b"operator-owned sentinel; do not delete or reset")
    sentinel = nonempty.read_bytes()
    with pytest.raises(RecoveryTargetError):
        _restore(
            checkpoint=checkpoint,
            recovery_store=recovery,
            restore_store=restore_store,
            database_target=nonempty,
            target_id="nonempty-target",
        )
    assert nonempty.read_bytes() == sentinel

    old_target = tmp_path / "old-target.db"
    _sqlite_backup(database_path, old_target)
    old_bytes = old_target.read_bytes()
    old_revision = _head_revision(old_target)
    with pytest.raises(RecoveryTargetError):
        _restore(
            checkpoint=checkpoint,
            recovery_store=recovery,
            restore_store=restore_store,
            database_target=old_target,
            target_id="old-versioned-target",
        )
    assert old_target.read_bytes() == old_bytes
    assert _head_revision(old_target) == old_revision


def test_restore_refuses_old_same_or_nested_object_domains_even_with_zero_objects(
    disposable_database: tuple[Path, dict[str, dict[str, Any]]],
    local_domains: tuple[RecoveryDomain, LocalRecoveryStore, Path, Path],
    tmp_path: Path,
) -> None:
    database_path, cycles = disposable_database
    primary, recovery, _primary_root, recovery_root = local_domains
    checkpoint = _capture(
        database_path=database_path,
        cycles=cycles,
        primary_store=primary,
        recovery_store=recovery,
    )
    recovery_bytes_before = {
        path.relative_to(recovery_root): path.read_bytes()
        for path in recovery_root.rglob("*")
        if path.is_file()
    }

    attempts: list[tuple[RecoveryDomain | LocalRecoveryStore, str]] = [
        (recovery, "same-recovery-store"),
        (primary, "old-primary-store"),
        (
            LocalRecoveryStore(
                recovery_root / "nested-target",
                failure_domain_id="nested-target-label",
            ),
            "nested-under-recovery",
        ),
    ]
    for restore_store, target_id in attempts:
        target = tmp_path / f"{target_id}.db"
        with pytest.raises(RecoveryTargetError):
            _restore(
                checkpoint=checkpoint,
                recovery_store=recovery,
                restore_store=restore_store,
                database_target=target,
                target_id=target_id,
            )
        assert not target.exists()
    assert {
        path.relative_to(recovery_root): path.read_bytes()
        for path in recovery_root.rglob("*")
        if path.is_file()
    } == recovery_bytes_before


def test_manifest_without_relational_backup_bytes_cannot_restore(
    disposable_database: tuple[Path, dict[str, dict[str, Any]]],
    local_domains: tuple[RecoveryDomain, LocalRecoveryStore, Path, Path],
    tmp_path: Path,
) -> None:
    database_path, cycles = disposable_database
    primary, recovery, _primary_root, _recovery_root = local_domains
    checkpoint = _capture(
        database_path=database_path,
        cycles=cycles,
        primary_store=primary,
        recovery_store=recovery,
    )
    Path(checkpoint["relationalBackup"]["recoveryCopy"]["uri"]).unlink()
    restore_store = LocalRecoveryStore(
        tmp_path / "restore-objects",
        failure_domain_id="fixture-new-object-target-domain",
    )

    with pytest.raises((RecoveryIntegrityError, RecoveryPartialFailure, RecoveryError)):
        _restore(
            checkpoint=checkpoint,
            recovery_store=recovery,
            restore_store=restore_store,
            database_target=tmp_path / "must-not-succeed.db",
        )


@pytest.mark.parametrize("replacement", [b"tampered", b"", b"not a sqlite backup"])
def test_tampered_or_substituted_relational_backup_bytes_fail_closed(
    disposable_database: tuple[Path, dict[str, dict[str, Any]]],
    local_domains: tuple[RecoveryDomain, LocalRecoveryStore, Path, Path],
    tmp_path: Path,
    replacement: bytes,
) -> None:
    database_path, cycles = disposable_database
    primary, recovery, _primary_root, _recovery_root = local_domains
    checkpoint = _capture(
        database_path=database_path,
        cycles=cycles,
        primary_store=primary,
        recovery_store=recovery,
    )
    recovery_database = Path(checkpoint["relationalBackup"]["recoveryCopy"]["uri"])
    recovery_database.write_bytes(replacement)
    restore_store = LocalRecoveryStore(
        tmp_path / "restore-objects",
        failure_domain_id="fixture-new-object-target-domain",
    )

    with pytest.raises((RecoveryIntegrityError, RecoveryPartialFailure, RecoveryError)):
        _restore(
            checkpoint=checkpoint,
            recovery_store=recovery,
            restore_store=restore_store,
            database_target=tmp_path / "must-not-succeed.db",
        )


def test_tampered_recovery_object_fails_and_partial_target_is_never_reused(
    disposable_database: tuple[Path, dict[str, dict[str, Any]]],
    local_domains: tuple[RecoveryDomain, LocalRecoveryStore, Path, Path],
    tmp_path: Path,
) -> None:
    database_path, cycles = disposable_database
    primary, recovery, _primary_root, _recovery_root = local_domains
    assert isinstance(primary.store, LocalSnapshotStorage)
    raw_bytes = b'{"fixture":"tampered-recovery-object"}\n'
    _append_unreferenced_snapshot(
        database_path=database_path,
        primary_store=primary.store,
        source_id="recovery-tamper-source",
        raw_bytes=raw_bytes,
    )
    checkpoint = _capture(
        database_path=database_path,
        cycles=cycles,
        primary_store=primary,
        recovery_store=recovery,
    )
    object_copy = checkpoint["objectManifest"]["objects"][0]["recoveryCopy"]
    object_path = Path(object_copy["uri"])
    original_object_bytes = object_path.read_bytes()
    object_path.write_bytes(b"substituted bytes with the wrong full digest")
    restore_store = LocalRecoveryStore(
        tmp_path / "restore-objects",
        failure_domain_id="fixture-new-object-target-domain",
    )
    target = tmp_path / "partial-target.db"

    with pytest.raises((RecoveryIntegrityError, RecoveryPartialFailure, RecoveryError)):
        _restore(
            checkpoint=checkpoint,
            recovery_store=recovery,
            restore_store=restore_store,
            database_target=target,
        )

    # Repairing an adversarial fixture does not make an already-touched target fresh.
    object_path.write_bytes(original_object_bytes)
    if target.exists():
        partial_bytes = target.read_bytes()
        with pytest.raises(RecoveryTargetError):
            _restore(
                checkpoint=checkpoint,
                recovery_store=recovery,
                restore_store=restore_store,
                database_target=target,
            )
        assert target.read_bytes() == partial_bytes


def test_restore_target_object_store_must_be_fresh_and_has_no_extra_bytes(
    disposable_database: tuple[Path, dict[str, dict[str, Any]]],
    local_domains: tuple[RecoveryDomain, LocalRecoveryStore, Path, Path],
    tmp_path: Path,
) -> None:
    database_path, cycles = disposable_database
    primary, recovery, _primary_root, _recovery_root = local_domains
    checkpoint = _capture(
        database_path=database_path,
        cycles=cycles,
        primary_store=primary,
        recovery_store=recovery,
    )
    restore_store = LocalRecoveryStore(
        tmp_path / "nonempty-restore-objects",
        failure_domain_id="fixture-new-object-target-domain",
    )
    extra = restore_store.store_snapshot(raw_bytes=b"unmanifested extra target bytes")
    extra_before = Path(extra.address.uri).read_bytes()

    with pytest.raises(RecoveryTargetError):
        _restore(
            checkpoint=checkpoint,
            recovery_store=recovery,
            restore_store=restore_store,
            database_target=tmp_path / "must-not-succeed.db",
        )
    assert Path(extra.address.uri).read_bytes() == extra_before


def test_cancelled_restore_emits_no_success_and_requires_a_new_target_to_resume(
    disposable_database: tuple[Path, dict[str, dict[str, Any]]],
    local_domains: tuple[RecoveryDomain, LocalRecoveryStore, Path, Path],
    tmp_path: Path,
) -> None:
    database_path, cycles = disposable_database
    primary, recovery, _primary_root, _recovery_root = local_domains
    assert isinstance(primary.store, LocalSnapshotStorage)
    _append_unreferenced_snapshot(
        database_path=database_path,
        primary_store=primary.store,
        source_id="recovery-cancel-restore-source",
        raw_bytes=b'{"fixture":"cancel-restore-after-object-write"}\n',
    )
    checkpoint = _capture(
        database_path=database_path,
        cycles=cycles,
        primary_store=primary,
        recovery_store=recovery,
    )
    underlying = LocalRecoveryStore(
        tmp_path / "cancelled-restore-objects",
        failure_domain_id="fixture-cancelled-target-domain",
    )
    cancelling = _CancelAfterFirstWriteStore(underlying)
    cancelling_domain = RecoveryDomain(
        failure_domain_id="fixture-cancelled-target-domain",
        store=cancelling,
    )
    cancelled_target = tmp_path / "cancelled-target.db"

    with pytest.raises(RecoveryCancelled):
        _restore(
            checkpoint=checkpoint,
            recovery_store=recovery,
            restore_store=cancelling_domain,
            database_target=cancelled_target,
            target_id="cancelled-target",
            cancel_requested=lambda: cancelling.write_observed,
        )

    if cancelled_target.exists():
        cancelled_bytes = cancelled_target.read_bytes()
        with pytest.raises(RecoveryTargetError):
            _restore(
                checkpoint=checkpoint,
                recovery_store=recovery,
                restore_store=cancelling_domain,
                database_target=cancelled_target,
                target_id="cancelled-target",
            )
        assert cancelled_target.read_bytes() == cancelled_bytes

    clean_store = LocalRecoveryStore(
        tmp_path / "resumed-restore-objects",
        failure_domain_id="fixture-resumed-target-domain",
    )
    receipt = _restore(
        checkpoint=checkpoint,
        recovery_store=recovery,
        restore_store=clean_store,
        database_target=tmp_path / "resumed-target.db",
        target_id="resumed-new-target",
    )
    validate_restore_receipt(receipt)


def _resign_object_manifest(checkpoint: dict[str, Any]) -> dict[str, Any]:
    object_manifest = checkpoint["objectManifest"]
    object_manifest["objectSetSha256"] = recovery_object_set_digest(
        object_manifest["objects"]
    )
    return _resign_recovery_contract(checkpoint)


@pytest.mark.parametrize(
    "attack",
    ("missing", "extra", "substituted-identity", "substituted-uri"),
)
def test_restore_recomputes_object_denominator_from_database_backup_not_manifest_claims(
    disposable_database: tuple[Path, dict[str, dict[str, Any]]],
    local_domains: tuple[RecoveryDomain, LocalRecoveryStore, Path, Path],
    tmp_path: Path,
    attack: str,
) -> None:
    database_path, cycles = disposable_database
    primary, recovery, _primary_root, _recovery_root = local_domains
    assert isinstance(primary.store, LocalSnapshotStorage)
    _append_unreferenced_snapshot(
        database_path=database_path,
        primary_store=primary.store,
        source_id="recovery-manifest-attack-source",
        raw_bytes=b'{"fixture":"manifest-object-denominator"}\n',
    )
    checkpoint = _capture(
        database_path=database_path,
        cycles=cycles,
        primary_store=primary,
        recovery_store=recovery,
    )
    attacked = deepcopy(checkpoint)
    manifest = attacked["objectManifest"]
    original = deepcopy(manifest["objects"][0])

    if attack == "missing":
        manifest.update(
            {
                "sourceSnapshotRowCount": 0,
                "objectReferenceCount": 0,
                "uniqueObjectCount": 0,
                "objects": [],
            }
        )
    elif attack == "extra":
        extra = deepcopy(original)
        extra["referenceId"] = "fabricated-extra-snapshot"
        manifest["objects"].append(extra)
        manifest["objects"].sort(key=lambda item: (item["referenceType"], item["referenceId"]))
        manifest["sourceSnapshotRowCount"] = 2
        manifest["objectReferenceCount"] = 2
        manifest["uniqueObjectCount"] = 1
    elif attack == "substituted-identity":
        manifest["objects"][0]["referenceId"] = "substituted-snapshot-identity"
    else:
        manifest["objects"][0]["sourceLogicalUri"] = (
            "/opaque/substituted/source/locator"
        )
    _resign_object_manifest(attacked)

    restore_store = LocalRecoveryStore(
        tmp_path / f"restore-objects-{attack}",
        failure_domain_id=f"fixture-new-target-domain-{attack}",
    )
    with pytest.raises((RecoveryIntegrityError, RecoveryPartialFailure, RecoveryError)):
        _restore(
            checkpoint=attacked,
            recovery_store=recovery,
            restore_store=restore_store,
            database_target=tmp_path / f"attacked-{attack}.db",
            target_id=f"attacked-{attack}",
        )


def test_reordered_or_duplicate_object_entries_never_select_by_first_or_latest_order(
    disposable_database: tuple[Path, dict[str, dict[str, Any]]],
    local_domains: tuple[RecoveryDomain, LocalRecoveryStore, Path, Path],
) -> None:
    database_path, cycles = disposable_database
    primary, recovery, _primary_root, _recovery_root = local_domains
    assert isinstance(primary.store, LocalSnapshotStorage)
    for suffix in ("a", "b"):
        _append_unreferenced_snapshot(
            database_path=database_path,
            primary_store=primary.store,
            source_id=f"recovery-order-source-{suffix}",
            raw_bytes=f'{{"fixture":"ordered-{suffix}"}}\n'.encode(),
        )
    checkpoint = _capture(
        database_path=database_path,
        cycles=cycles,
        primary_store=primary,
        recovery_store=recovery,
    )
    assert len(checkpoint["objectManifest"]["objects"]) == 2

    reordered = deepcopy(checkpoint)
    reordered["objectManifest"]["objects"].reverse()
    _resign_object_manifest(reordered)
    with pytest.raises((RecoveryIntegrityError, RecoveryError, ValueError)):
        validate_checkpoint_manifest(reordered)

    correct = checkpoint["objectManifest"]["objects"][0]
    substituted = deepcopy(correct)
    substituted["sourceLogicalUri"] = "/attacker/substitution"
    for candidates in ([correct, substituted], [substituted, correct]):
        duplicate = deepcopy(checkpoint)
        duplicate["objectManifest"]["objects"] = deepcopy(candidates)
        duplicate["objectManifest"]["sourceSnapshotRowCount"] = 2
        duplicate["objectManifest"]["objectReferenceCount"] = 2
        duplicate["objectManifest"]["uniqueObjectCount"] = 1
        _resign_object_manifest(duplicate)
        with pytest.raises((RecoveryIntegrityError, RecoveryError, ValueError)):
            validate_checkpoint_manifest(duplicate)


@pytest.mark.parametrize(
    "attack",
    ("row-count", "schema-revision", "database-digest", "database-key"),
)
def test_restore_recomputes_schema_inventory_and_database_identity_from_bytes(
    disposable_database: tuple[Path, dict[str, dict[str, Any]]],
    local_domains: tuple[RecoveryDomain, LocalRecoveryStore, Path, Path],
    tmp_path: Path,
    attack: str,
) -> None:
    database_path, cycles = disposable_database
    primary, recovery, _primary_root, _recovery_root = local_domains
    checkpoint = _capture(
        database_path=database_path,
        cycles=cycles,
        primary_store=primary,
        recovery_store=recovery,
    )
    attacked = deepcopy(checkpoint)
    relational = attacked["relationalBackup"]
    if attack == "row-count":
        table = next(row for row in relational["tables"] if row["tableName"] == "scheduled_cycles")
        table["rowCount"] += 1
        relational["tableInventorySha256"] = recovery_table_inventory_digest(
            relational["tables"]
        )
    elif attack == "schema-revision":
        relational["schemaRevision"] = "0009_postgresql_guardrails"
    elif attack == "database-digest":
        relational["contentSha256"] = "f" * 64
        relational["recoveryCopy"]["contentSha256"] = "f" * 64
    else:
        relational["recoveryCopy"]["key"] = "fabricated/reordered/database-key"
    _resign_recovery_contract(attacked)

    restore_store = LocalRecoveryStore(
        tmp_path / f"restore-objects-{attack}",
        failure_domain_id=f"fixture-new-target-domain-{attack}",
    )
    with pytest.raises((RecoveryIntegrityError, RecoveryPartialFailure, RecoveryError)):
        _restore(
            checkpoint=attacked,
            recovery_store=recovery,
            restore_store=restore_store,
            database_target=tmp_path / f"attacked-{attack}.db",
            target_id=f"attacked-{attack}",
        )


def test_validator_rejects_tampering_even_when_outer_contract_is_resigned(
    disposable_database: tuple[Path, dict[str, dict[str, Any]]],
    local_domains: tuple[RecoveryDomain, LocalRecoveryStore, Path, Path],
) -> None:
    database_path, cycles = disposable_database
    primary, recovery, _primary_root, _recovery_root = local_domains
    checkpoint = _capture(
        database_path=database_path,
        cycles=cycles,
        primary_store=primary,
        recovery_store=recovery,
    )
    attacked = deepcopy(checkpoint)
    attacked["relationalBackup"]["byteLength"] += 1
    _resign_recovery_contract(attacked)

    with pytest.raises((RecoveryIntegrityError, RecoveryError, ValueError)):
        validate_checkpoint_manifest(attacked)


@pytest.mark.parametrize(
    "target",
    (
        "relational-content",
        "relational-copy-content",
        "trigger-content",
        "negative-byte-length",
        "boolean-byte-length",
    ),
)
def test_checkpoint_contract_requires_full_sha256_and_strict_byte_count_types(
    disposable_database: tuple[Path, dict[str, dict[str, Any]]],
    local_domains: tuple[RecoveryDomain, LocalRecoveryStore, Path, Path],
    target: str,
) -> None:
    database_path, cycles = disposable_database
    primary, recovery, _primary_root, _recovery_root = local_domains
    checkpoint = _capture(
        database_path=database_path,
        cycles=cycles,
        primary_store=primary,
        recovery_store=recovery,
    )
    attacked = deepcopy(checkpoint)
    if target == "relational-content":
        attacked["relationalBackup"]["contentSha256"] = "a" * 63
    elif target == "relational-copy-content":
        attacked["relationalBackup"]["recoveryCopy"]["contentSha256"] = "a" * 63
    elif target == "trigger-content":
        attacked["triggerCycle"]["manifest"]["contentSha256"] = "a" * 63
    elif target == "negative-byte-length":
        attacked["relationalBackup"]["byteLength"] = -1
    else:
        attacked["relationalBackup"]["byteLength"] = True
    with pytest.raises((RecoveryIntegrityError, RecoveryError, ValueError, TypeError)):
        _resign_recovery_contract(attacked)
        validate_checkpoint_manifest(attacked)


@pytest.mark.parametrize(
    ("algorithm_key", "attack"),
    (
        ("schemaDigestAlgorithm", "remove"),
        ("schemaDigestAlgorithm", "substitute"),
        ("rowsetDigestAlgorithm", "remove"),
        ("rowsetDigestAlgorithm", "substitute"),
    ),
)
def test_resigned_checkpoint_cannot_remove_or_substitute_digest_algorithms(
    disposable_database: tuple[Path, dict[str, dict[str, Any]]],
    local_domains: tuple[RecoveryDomain, LocalRecoveryStore, Path, Path],
    algorithm_key: str,
    attack: str,
) -> None:
    database_path, cycles = disposable_database
    primary, recovery, _primary_root, _recovery_root = local_domains
    checkpoint = _capture(
        database_path=database_path,
        cycles=cycles,
        primary_store=primary,
        recovery_store=recovery,
    )
    attacked = deepcopy(checkpoint)
    if attack == "remove":
        del attacked["relationalBackup"][algorithm_key]
    else:
        attacked["relationalBackup"][algorithm_key] = "sha256-attacker-substitution-v9"

    with pytest.raises((RecoveryIntegrityError, RecoveryError, ValueError, TypeError)):
        _resign_recovery_contract(attacked)
        validate_checkpoint_manifest(attacked)


@pytest.mark.parametrize("defect", ("extra-table", "old-revision", "foreign-key"))
def test_checkpoint_rejects_nonexact_schema_revision_inventory_or_foreign_keys(
    disposable_database: tuple[Path, dict[str, dict[str, Any]]],
    local_domains: tuple[RecoveryDomain, LocalRecoveryStore, Path, Path],
    defect: str,
) -> None:
    database_path, cycles = disposable_database
    primary, recovery, _primary_root, _recovery_root = local_domains
    with sqlite3.connect(database_path) as connection:
        if defect == "extra-table":
            connection.execute(
                "CREATE TABLE attacker_extra_table (id TEXT PRIMARY KEY, payload TEXT)"
            )
            connection.execute(
                "INSERT INTO attacker_extra_table (id, payload) VALUES ('x', 'opaque')"
            )
        elif defect == "old-revision":
            connection.execute(
                "UPDATE alembic_version SET version_num = '0009_postgresql_guardrails'"
            )
        else:
            connection.execute("PRAGMA foreign_keys=OFF")
            connection.execute(
                """
                INSERT INTO model_entities (
                    id, canonical_name, display_name, entity_type,
                    base_model_entity_id, status, modalities
                ) VALUES (
                    'fk-invalid-model', 'fk-invalid-model', 'FK invalid model', 'model',
                    'missing-parent-model', 'active', '[]'
                )
                """
            )
        connection.commit()

    with pytest.raises((RecoveryIntegrityError, RecoveryError, ValueError)):
        _capture(
            database_path=database_path,
            cycles=cycles,
            primary_store=primary,
            recovery_store=recovery,
        )


def test_matching_rowset_digest_cannot_replace_semantic_lineage_audit(
    disposable_database: tuple[Path, dict[str, dict[str, Any]]],
    local_domains: tuple[RecoveryDomain, LocalRecoveryStore, Path, Path],
) -> None:
    database_path, cycles = disposable_database
    primary, recovery, _primary_root, _recovery_root = local_domains
    assert isinstance(primary.store, LocalSnapshotStorage)
    _append_unreferenced_snapshot(
        database_path=database_path,
        primary_store=primary.store,
        source_id="semantic-audit-source",
        raw_bytes=b'{"fixture":"semantic-audit"}\n',
    )

    engine = _engine(database_path)
    try:
        with Session(engine) as session, session.begin():
            revision_id = session.scalar(
                select(models.OfficialSourceRow.current_revision_id).where(
                    models.OfficialSourceRow.id == "semantic-audit-source"
                )
            )
            assert isinstance(revision_id, str)
            root = session.scalar(
                select(models.SourceRevisionDecision).where(
                    models.SourceRevisionDecision.source_revision_id == revision_id,
                    models.SourceRevisionDecision.supersedes_decision_id.is_(None),
                )
            )
            assert root is not None
            repositories.append_source_revision_decision(
                session,
                source_revision_id=revision_id,
                outcome="revoked",
                policy_version="adversarial-fixture-v1",
                reason_code="semantic_chronology_probe",
                actor="pytest-adversary",
                supersedes_decision_id=root.id,
            )
    finally:
        engine.dispose()

    # Preserve the exact trigger/schema inventory while backdating the child
    # decision ahead of its parent. Relational uniqueness/FK/integrity checks
    # remain green; only the semantic chronology audit can reject it.
    with sqlite3.connect(database_path) as connection:
        trigger_row = connection.execute(
            """
            SELECT sql FROM sqlite_master
            WHERE type = 'trigger' AND name = 'trg_source_revision_decisions_no_update'
            """
        ).fetchone()
        assert trigger_row is not None and isinstance(trigger_row[0], str)
        trigger_sql = trigger_row[0]
        connection.execute("DROP TRIGGER trg_source_revision_decisions_no_update")
        connection.execute(
            """
            UPDATE source_revision_decisions
            SET decided_at = CASE
                WHEN supersedes_decision_id IS NULL
                    THEN '2026-07-15 14:10:00.000000'
                ELSE '2026-07-15 14:00:00.000000'
            END
            WHERE source_revision_id = (
                SELECT current_revision_id FROM official_sources
                WHERE id = 'semantic-audit-source'
            )
            """
        )
        connection.execute(trigger_sql)
        connection.commit()
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='trigger' AND name=?",
            ("trg_source_revision_decisions_no_update",),
        ).fetchone() == (1,)

    with pytest.raises((RecoveryIntegrityError, RecoveryError, ValueError)):
        _capture(
            database_path=database_path,
            cycles=cycles,
            primary_store=primary,
            recovery_store=recovery,
        )


def test_checkpoint_semantic_audit_keeps_exact_seven_family_zero_row_denominator(
    disposable_database: tuple[Path, dict[str, dict[str, Any]]],
    local_domains: tuple[RecoveryDomain, LocalRecoveryStore, Path, Path],
) -> None:
    database_path, cycles = disposable_database
    primary, recovery, _primary_root, _recovery_root = local_domains
    checkpoint = _capture(
        database_path=database_path,
        cycles=cycles,
        primary_store=primary,
        recovery_store=recovery,
    )
    audit = checkpoint["relationalBackup"]["integrity"]["semanticLineageAudit"]
    assert audit["status"] == "passed"
    assert audit["familyCount"] == 7
    assert len(audit["families"]) == 7
    assert {
        "source_revision_decisions",
        "claim_review_decisions",
        "claim_publication_decisions",
        "identity_decisions",
        "ops_incident_events",
        "review_work_item_events",
        "notification_receipts",
    } == {family["family"] for family in audit["families"]}

    attacked = deepcopy(checkpoint)
    attacked_audit = attacked["relationalBackup"]["integrity"][
        "semanticLineageAudit"
    ]
    omitted = next(
        family for family in attacked_audit["families"] if family["rowCount"] == 0
    )
    attacked_audit["families"].remove(omitted)
    attacked_audit["familyCount"] -= 1
    _resign_recovery_contract(attacked)
    with pytest.raises((RecoveryIntegrityError, RecoveryError, ValueError)):
        validate_checkpoint_manifest(attacked)


def test_checkpoint_created_at_cannot_predate_its_exact_trigger_slot(
    disposable_database: tuple[Path, dict[str, dict[str, Any]]],
    local_domains: tuple[RecoveryDomain, LocalRecoveryStore, Path, Path],
) -> None:
    database_path, cycles = disposable_database
    primary, recovery, _primary_root, _recovery_root = local_domains
    checkpoint = _capture(
        database_path=database_path,
        cycles=cycles,
        primary_store=primary,
        recovery_store=recovery,
    )
    attacked = deepcopy(checkpoint)
    attacked["createdAt"] = "2026-07-14T23:59:59Z"
    _resign_recovery_contract(attacked)

    with pytest.raises((RecoveryIntegrityError, RecoveryError, ValueError)):
        validate_checkpoint_manifest(attacked)
