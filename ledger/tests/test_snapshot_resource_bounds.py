"""F8 regression: bounded local snapshot storage and cumulative object budgets.

Local immutable SNAPSHOT objects must be streamed through descriptor-pinned
no-follow regular files with fixed positive read sizes only; the per-object cap
must reject over-cap objects (including in-place file growth beyond fstat) and
accept exact-cap; ``verify_snapshot`` must stream a digest without materializing
the object bytes; duplicate references must count once; the per-snapshot cap
must NOT apply to the ARTIFACT namespace (owned by F9/F19); descriptors must
close exactly once with no leaks.  The real checkpoint and restore object-copy
loops must enforce a cumulative unique-byte budget that fails closed: once an
over-budget unique copy would be written, the operation aborts with no success
receipt and no *current* over-budget copy, while any fully-written earlier
unique copies remain as bounded immutable partial state (R2 documents this
existing-failure-model behavior rather than claiming none can remain).  Unique
byte accounting uses an explicit running total and counts duplicate references
once.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import os
from pathlib import Path
import sqlite3

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.backup import (
    LocalRecoveryStore,
    RecoveryDomain,
    RecoveryPartialFailure,
    create_sqlite_checkpoint,
    restore_sqlite_checkpoint,
)
from app.db import models, operational_repositories, repositories
from app.schemas.operations_contracts import (
    contract_self_digest as operations_self_digest,
    derive_cycle_id,
)
from app.storage.base import (
    SnapshotStorageCollisionError,
    SnapshotStorageIntegrityError,
    StorageObjectKind,
    compute_content_hash,
)
from app.storage.local import LocalSnapshotStorage, _CHUNK_SIZE

LEDGER_ROOT = Path(__file__).resolve().parents[1]
CADENCE_SECONDS = 43_200
ANCHOR = datetime(2026, 1, 1, tzinfo=timezone.utc)
TRIGGER_LABEL = "trigger"
CREATED_AT = "2026-07-15T14:30:00Z"
RESTORE_STARTED_AT = "2026-07-15T15:00:00Z"
RESTORE_FINISHED_AT = "2026-07-15T15:00:04Z"


# ---------------------------------------------------------------------------
# Minimal shared helpers for real checkpoint/restore fixture data
# ---------------------------------------------------------------------------

def _alembic_config(database_url: str) -> Config:
    config = Config(str(LEDGER_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(LEDGER_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url)
    config.attributes["database_url"] = database_url
    return config


def _engine(database_path: Path) -> Engine:
    engine = create_engine(f"sqlite:///{database_path}", future=True)

    @event.listens_for(engine, "connect")
    def _foreign_keys(dbapi_connection, _connection_record):  # type: ignore[no-untyped-def]
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


def _utc_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _terminal_cycle_payload(
    *, environment: str, lane: str, slot_ordinal: int, schedule_policy_revision_id: str
) -> dict:
    scheduled = ANCHOR + timedelta(seconds=CADENCE_SECONDS * slot_ordinal)
    next_scheduled = scheduled + timedelta(seconds=CADENCE_SECONDS)
    payload: dict = {
        "schemaVersion": "1.0.0",
        "policyVersion": "scheduled-cycle-v1",
        "availability": "operations_record_only",
        "mode": "synthetic_fixture",
        "cycleId": derive_cycle_id(
            environment, lane, _utc_text(scheduled), schedule_policy_revision_id
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


def _append_terminal_cycle(session: Session, payload: dict) -> None:
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


def _sqlite_backup(source: Path, target: Path) -> None:
    with sqlite3.connect(source) as sc, sqlite3.connect(target) as tc:
        sc.backup(tc)


def _source_definition(source_id: str, benchmark_id: str) -> dict:
    return {
        "id": source_id,
        "benchmark_id": benchmark_id,
        "source_name": f"Disposable resource-bounds source {source_id}",
        "source_url": f"https://fixtures.example.test/{source_id}/results.json",
        "source_type": "api",
        "officialness_level": "O1",
        "machine_readable": True,
        "requires_auth": False,
        "supports_history": True,
        "update_cadence": "manual",
        "parser_name": "resource-bounds-fixture-json",
        "parser_version": "1",
        "parser_config": {},
        "status": "active",
        "notes": "Temporary F8 fixture only.",
    }


def _raw_bytes_for(snapshot: "models.SourceSnapshot", *, primary_store: LocalSnapshotStorage) -> int:
    """Return the VERIFIED byte length of one snapshot object already stored.

    Uses ``read_snapshot`` (not the un-verifying ``read``) so the reported
    length is bound to the object's integrity-verified content, not merely the
    bytes at the URI.
    """
    result = primary_store.read_snapshot(
        uri=snapshot.raw_content_uri,
        content_sha256=snapshot.content_hash,
    )
    return result.verification.byte_length


def _append_snapshot(
    *, database_path: Path, primary_store: LocalSnapshotStorage, source_id: str, raw_bytes: bytes
) -> models.SourceSnapshot:
    """Insert one retained source-snapshot row so a real checkpoint copies it."""
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
            snapshot = repositories.insert_snapshot(
                session,
                official_source_id=source_id,
                source_revision_id=reconciliation.revision.id,
                raw_content_uri=storage_receipt.address.uri,
                content_hash=storage_receipt.address.content_sha256,
                content_type="application/json",
                http_status=200,
                etag=None,
                last_modified_header=None,
                fetch_metadata={
                    "storageReceiptSha256": storage_receipt.receipt_id.split(":")[-1],
                    "storageVerificationReceiptSha256": (
                        storage_receipt.verification_receipt_id.split(":")[-1]
                    ),
                },
                parser_version="resource-bounds-fixture-json-v1",
            )
            snapshot_id = snapshot.id
        with Session(engine) as session:
            persisted = session.get(models.SourceSnapshot, snapshot_id)
            assert persisted is not None
            session.expunge(persisted)
            return persisted
    finally:
        engine.dispose()


@pytest.fixture(scope="module")
def _template_db(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, dict]:
    root = tmp_path_factory.mktemp("resource-bounds-template")
    database_path = root / "template.db"
    command.upgrade(_alembic_config(f"sqlite:///{database_path}"), "head")
    cycles = {
        TRIGGER_LABEL: _terminal_cycle_payload(
            environment="fixture-env",
            lane="recheck",
            slot_ordinal=390,
            schedule_policy_revision_id="fixture-recheck-policy-r1",
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


def _domains(tmp_path: Path) -> tuple[RecoveryDomain, LocalRecoveryStore, Path, Path]:
    primary_root = tmp_path / "primary-objects"
    recovery_root = tmp_path / "recovery-copy"
    primary = RecoveryDomain(
        failure_domain_id="fixture-primary-domain",
        store=LocalSnapshotStorage(primary_root),
    )
    recovery = LocalRecoveryStore(recovery_root, failure_domain_id="fixture-recovery-domain")
    return primary, recovery, primary_root, recovery_root


# ---------------------------------------------------------------------------
# Storage layer: bounded reads, exact/cap+1, mutation, artifact exclusion
# ---------------------------------------------------------------------------

class _GuardedFdOpener:
    """File-like proof that the streamer only issues fixed-size reads."""

    def __init__(self, raw: bytes, *, max_chunk: int) -> None:
        self._raw = raw
        self._offset = 0
        self._max_chunk = max_chunk
        self.reads: list[int] = []

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def read(self, size: int = -1) -> bytes:
        if size < 0 or size > self._max_chunk:
            raise AssertionError(f"unbounded read(size={size}) was issued")
        self.reads.append(size)
        if self._offset >= len(self._raw):
            return b""
        chunk = self._raw[self._offset : self._offset + size]
        self._offset += len(chunk)
        return chunk


def _relative_object_path(storage: LocalSnapshotStorage, uri: str) -> Path:
    return Path(uri)


def _count_open_fds() -> int:
    if not Path("/dev/fd").exists():
        return 0
    return len(list(Path("/dev/fd").iterdir()))


def test_snapshot_read_uses_fixed_chunk_reads_never_unbounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.storage.local as local_module

    storage = LocalSnapshotStorage(tmp_path / "objects")
    raw = b"x" * (local_module._CHUNK_SIZE * 5)
    receipt = storage.store_snapshot(raw_bytes=raw)

    guarded = _GuardedFdOpener(raw, max_chunk=local_module._CHUNK_SIZE)
    monkeypatch.setattr(local_module.os, "fdopen", lambda fd, *a, **k: guarded)

    read = storage.read_snapshot(
        uri=receipt.address.uri, content_sha256=receipt.address.content_sha256
    )
    assert read.raw_bytes == raw
    assert guarded.reads
    assert all(0 < size <= local_module._CHUNK_SIZE for size in guarded.reads)


def test_verify_snapshot_streams_without_materializing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.storage.local as local_module

    storage = LocalSnapshotStorage(tmp_path / "objects")
    raw = b"w" * 100_000
    receipt = storage.store_snapshot(raw_bytes=raw)

    guarded = _GuardedFdOpener(raw, max_chunk=local_module._CHUNK_SIZE)
    monkeypatch.setattr(local_module.os, "fdopen", lambda fd, *a, **k: guarded)

    verified = storage.verify_snapshot(
        uri=receipt.address.uri, content_sha256=receipt.address.content_sha256
    )
    assert verified.observed_sha256 == receipt.address.content_sha256
    assert verified.byte_length == len(raw)
    assert guarded.reads
    assert all(0 < size <= local_module._CHUNK_SIZE for size in guarded.reads)


def test_public_read_is_bounded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import app.storage.local as local_module

    storage = LocalSnapshotStorage(tmp_path / "objects")
    raw = b"v" * 50_000
    receipt = storage.store_snapshot(raw_bytes=raw)
    guarded = _GuardedFdOpener(raw, max_chunk=local_module._CHUNK_SIZE)
    monkeypatch.setattr(local_module.os, "fdopen", lambda fd, *a, **k: guarded)
    assert storage.read(receipt.address.uri) == raw


def test_over_cap_snapshot_rejected_before_retention(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.storage.local as local_module

    storage = LocalSnapshotStorage(tmp_path / "objects")
    monkeypatch.setattr(local_module, "MAX_SNAPSHOT_BYTES", 10)
    with pytest.raises(SnapshotStorageIntegrityError, match="snapshot byte cap"):
        storage.store_snapshot(raw_bytes=b"y" * 20)
    assert not any(
        p.is_file() and not p.name.startswith(".") for p in (tmp_path / "objects").rglob("*")
    )


def test_exact_cap_accepted_and_inplace_growth_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.storage.local as local_module

    storage = LocalSnapshotStorage(tmp_path / "objects")
    monkeypatch.setattr(local_module, "MAX_SNAPSHOT_BYTES", 16)
    raw = b"z" * 16  # exactly at cap — accepted
    receipt = storage.store_snapshot(raw_bytes=raw)
    assert storage.read_snapshot(
        uri=receipt.address.uri, content_sha256=receipt.address.content_sha256
    ).raw_bytes == raw

    # Stored file grows beyond the cap in place (fstat saw a small object): the
    # cap+1 streaming guard must still reject it.
    grown = b"z" * 17
    Path(_relative_object_path(storage, receipt.address.uri)).write_bytes(grown)
    with pytest.raises(SnapshotStorageIntegrityError, match="snapshot byte cap"):
        storage.verify_snapshot(
            uri=receipt.address.uri, content_sha256=receipt.address.content_sha256
        )


def test_cap_plus_one_rejects_inplace_growth(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import app.storage.local as local_module

    storage = LocalSnapshotStorage(tmp_path / "objects")
    monkeypatch.setattr(local_module, "MAX_SNAPSHOT_BYTES", 8)
    receipt = storage.store_snapshot(raw_bytes=b"a" * 8)
    path = Path(_relative_object_path(storage, receipt.address.uri))
    path.write_bytes(b"a" * 50)  # grow in place to well over the cap
    with pytest.raises(SnapshotStorageIntegrityError, match="snapshot byte cap"):
        storage.read_snapshot(
            uri=receipt.address.uri, content_sha256=receipt.address.content_sha256
        )


def test_mutation_changes_digest_and_fails_closed(tmp_path: Path) -> None:
    storage = LocalSnapshotStorage(tmp_path / "objects")
    raw = b"original evidence bytes"
    receipt = storage.store_snapshot(raw_bytes=raw)
    Path(_relative_object_path(storage, receipt.address.uri)).write_bytes(raw + b"-tampered")
    with pytest.raises(SnapshotStorageIntegrityError, match="not expected digest"):
        storage.verify_snapshot(
            uri=receipt.address.uri, content_sha256=receipt.address.content_sha256
        )
    with pytest.raises(SnapshotStorageIntegrityError, match="not expected digest"):
        storage.read_snapshot(
            uri=receipt.address.uri, content_sha256=receipt.address.content_sha256
        )


def test_snapshot_reuse_collision_detection_surfaces_collision_error(tmp_path: Path) -> None:
    storage = LocalSnapshotStorage(tmp_path / "objects")
    raw = b"expected bytes for a snapshot"
    digest = compute_content_hash(raw)
    addr = storage.address_for_content_hash(digest)
    path = Path(addr.uri)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"different bytes at the canonical address")
    with pytest.raises(SnapshotStorageCollisionError, match="not expected digest"):
        storage.store_snapshot(raw_bytes=raw)


def test_artifact_namespace_is_not_capped_by_per_object_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.storage.local as local_module

    storage = LocalSnapshotStorage(tmp_path / "objects")
    monkeypatch.setattr(local_module, "MAX_SNAPSHOT_BYTES", 16)
    large = b"artifact-bytes-are-not-snapshot-capped" * 4  # > cap
    artifact = storage.store_snapshot(
        raw_bytes=large, object_kind=StorageObjectKind.ARTIFACT
    )
    assert artifact.address.object_kind is StorageObjectKind.ARTIFACT
    assert artifact.byte_length == len(large)
    with pytest.raises(SnapshotStorageIntegrityError, match="snapshot byte cap"):
        storage.store_snapshot(raw_bytes=large, object_kind=StorageObjectKind.SNAPSHOT)


def test_fixed_chunk_size_is_positive_and_under_cap(tmp_path) -> None:
    import app.storage.local as local_module

    assert local_module._CHUNK_SIZE > 0
    assert local_module.MAX_SNAPSHOT_BYTES >= local_module._CHUNK_SIZE


def test_capped_stream_issue_requests_at_most_cap_plus_one_total(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The capped reader requests `min(_CHUNK_SIZE, cap+1-total)` so it consumes
    at most cap+1 bytes, never cap+CHUNK_SIZE: a file well over the cap in place
    must stop at exactly cap+1 bytes requested."""
    from app.storage.local import _sha256_stream

    class _Probe:
        def __init__(self, total: int) -> None:
            self._remaining = total
            self.requests: list[int] = []

        def read(self, size: int = -1) -> bytes:
            self.requests.append(size)
            if self._remaining <= 0:
                return b""
            take = min(self._remaining, size)
            self._remaining -= take
            return b"p" * take

    cap = 1000
    probe = _Probe(total=cap * 10)  # file is huge; must stop at cap+1
    digest, byte_count, over_cap = _sha256_stream(probe, cap=cap)
    assert over_cap is True
    assert byte_count == cap + 1  # exactly cap+1, not cap + _CHUNK_SIZE
    assert probe.requests
    assert all(0 < r <= _CHUNK_SIZE for r in probe.requests)
    # The final request is clamped to the remaining budget, never a full chunk
    # that would overshoot the cap.
    assert max(probe.requests) <= cap + 1


def test_exact_cap_read_does_not_trip_over_cap(tmp_path) -> None:
    from app.storage.local import _sha256_stream

    class _Fixed:
        def __init__(self, raw: bytes) -> None:
            self._raw = raw
            self._off = 0

        def read(self, size: int = -1) -> bytes:
            chunk = self._raw[self._off : self._off + size]
            self._off += len(chunk)
            return chunk

    raw = b"q" * 1000
    digest, byte_count, over_cap = _sha256_stream(_Fixed(raw), cap=1000)
    assert over_cap is False
    assert byte_count == 1000
    assert digest == hashlib.sha256(raw).hexdigest()


def test_sha256_stream_needs_hashlib_in_scope(tmp_path) -> None:
    import app.storage.local as local_module

    raw = b"streamed hash correctness"
    from io import BytesIO

    digest, byte_count, over_cap = local_module._sha256_stream(
        BytesIO(raw), cap=None
    )
    assert digest == hashlib.sha256(raw).hexdigest()
    assert byte_count == len(raw)
    assert over_cap is False


def test_verify_target_from_parent_has_no_fd_leak(tmp_path) -> None:
    """The reuse-race verifier must not leak the leaf descriptor: repeated
    invocations against a parent directory fd must not grow open descriptors
    (this is a no-leak check, not an EXACTLY-ONCE proof — the +1 aggregate
    tolerance could not distinguish close-once from close-many)."""
    storage_path = tmp_path / "objects"
    storage = LocalSnapshotStorage(storage_path)
    raw = b"reuse-verifier must close its leaf descriptor"
    digest = compute_content_hash(raw)
    target = storage.address_for_content_hash(digest)
    path = Path(target.uri)
    path.parent.mkdir(parents=True)
    path.write_bytes(raw)  # an existing canonical target

    parent_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    baseline = _count_open_fds()
    try:
        for _ in range(25):
            storage._verify_target_from_parent(parent_fd, path, digest, cap=None)
    finally:
        os.close(parent_fd)
    # parent_fd is closed by the finally, so a non-leaking verifier ends at
    # baseline - 1 (we do NOT allow any net growth).
    assert _count_open_fds() <= baseline


def test_verify_target_from_parent_has_no_fd_leak_on_over_cap(tmp_path, monkeypatch) -> None:
    """Even when the verifier rejects an over-cap target, its leaf descriptor
    must be closed (no leak on the failure path)."""
    import app.storage.local as local_module

    storage_path = tmp_path / "objects"
    storage = LocalSnapshotStorage(storage_path)
    small_cap = 8
    monkeypatch.setattr(local_module, "MAX_SNAPSHOT_BYTES", small_cap)
    raw = b"over the tiny cap for leak-checking" * 16
    digest = compute_content_hash(raw)
    target = storage.address_for_content_hash(digest)
    path = Path(target.uri)
    path.parent.mkdir(parents=True)
    path.write_bytes(raw)

    reuse_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    baseline = _count_open_fds()
    try:
        for _ in range(25):
            with pytest.raises(SnapshotStorageIntegrityError, match="snapshot byte cap"):
                storage._verify_target_from_parent(reuse_fd, path, digest, cap=small_cap)
    finally:
        os.close(reuse_fd)
    # Repeatedly failing verifications must not grow open descriptors.
    assert _count_open_fds() <= baseline


# ---------------------------------------------------------------------------
# Backup-service loops: cumulative unique-byte budget over real checkpoint/restore
# ---------------------------------------------------------------------------

def test_checkpoint_cumulative_budget_fails_closed_before_success_receipt(
    tmp_path: Path,
    _template_db: tuple[Path, dict],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Real checkpoint loop: two unique snapshots exceed a small cumulative cap and
    the checkpoint aborts with no success receipt and no *current* over-budget
    copy.  The first unique copy fits and is written before the overflow; the
    second is refused before its write, so the recovery store holds bounded
    immutable partial state (the first unique snapshot + the relational blob),
    not the over-budget second snapshot and not a published checkpoint."""
    import app.backup.service as svc

    template, cycles = _template_db
    database_path = tmp_path / "source.db"
    _sqlite_backup(template, database_path)
    primary, recovery, _primary_root, _recovery_root = _domains(tmp_path)

    one = _append_snapshot(
        database_path=database_path,
        primary_store=primary.store,
        source_id="resource-budget-a",
        raw_bytes=b'{"fixture":"a"}\n',
    )
    two = _append_snapshot(
        database_path=database_path,
        primary_store=primary.store,
        source_id="resource-budget-b",
        raw_bytes=b'{"fixture":"bb"}\n',
    )
    assert one.content_hash != two.content_hash

    # enumerate_referenced_objects sorts by reference_id (SourceSnapshot.id is
    # UUID4, NOT insertion order), so determine the actual first/second copies by
    # id so "first fits / second overflows" is deterministic.
    first, second = sorted((one, two), key=lambda s: s.id)
    first_len = _raw_bytes_for(first, primary_store=primary.store)
    # Cap to exactly the first object's verified length: it fits; the second
    # unique object (different digest) overflows the cumulative budget.
    monkeypatch.setattr(svc, "MAX_UNIQUE_SNAPSHOT_BYTES", first_len)

    with pytest.raises(RecoveryPartialFailure):
        create_sqlite_checkpoint(
            database_path=database_path,
            trigger_cycle=cycles[TRIGGER_LABEL],
            primary_store=primary,
            recovery_store=recovery,
            created_at=CREATED_AT,
        )
    # The relational copy precedes object budget enforcement and is legitimately
    # retained; the checkpoint *publication* happens only AFTER the object loop,
    # so an over-budget abort must leave exactly that one relational blob and no
    # published checkpoint, and no success receipt.
    artifact_inventory = recovery.inventory_orphans(
        referenced_uris=(), object_kind=StorageObjectKind.ARTIFACT
    )
    assert artifact_inventory.listed_count == 1

    # References are processed in sorted (reference_type, reference_id) order, so
    # ``first`` fits the cumulative cap exactly and is written before the
    # overflow; ``second`` is charged next, blows the cap, and is REFUSED before
    # its write.  Exactly the first bounded snapshot remains with BOTH its digest
    # pinned and the second explicitly ABSENT — documenting (not denying) the
    # existing partial-state failure model.
    snapshot_inventory = recovery.inventory_orphans(
        referenced_uris=(), object_kind=StorageObjectKind.SNAPSHOT
    )
    assert snapshot_inventory.listed_count == 1
    remaining = snapshot_inventory.orphan_objects[0]
    assert remaining.content_sha256 == first.content_hash
    assert remaining.content_sha256 != second.content_hash
    assert second.content_hash not in {
        item.content_sha256 for item in snapshot_inventory.orphan_objects
    }


def test_restore_under_cap_succeeds_and_over_cap_leaves_bounded_partial(
    tmp_path: Path,
    _template_db: tuple[Path, dict],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Relational restore runs BEFORE the object-copy budget loop.

    A real over-cap checkpoint must therefore STILL create the relational DB
    target (that step already completed), must not produce a success receipt,
    and must leave the snapshot copies bounded: the first sorted unique object
    (which fits the cumulative cap) is written, the second is refused before its
    write.  This mirrors the checkpoint's partial-state failure model rather than
    claiming no relational target or no partial object copy."""
    import app.backup.service as svc

    template, cycles = _template_db
    database_path = tmp_path / "source.db"
    _sqlite_backup(template, database_path)
    primary, recovery, _primary_root, _recovery_root = _domains(tmp_path)

    one = _append_snapshot(
        database_path=database_path,
        primary_store=primary.store,
        source_id="restore-budget-a",
        raw_bytes=b'{"restore":"a"}\n',
    )
    two = _append_snapshot(
        database_path=database_path,
        primary_store=primary.store,
        source_id="restore-budget-b",
        raw_bytes=b'{"restore":"bb"}\n',
    )
    assert one.content_hash != two.content_hash
    # Restore object order follows the manifest's sorted-by-reference_id (UUID4
    # id) order; make the overflow target the ACTUAL first object by id.
    first, second = sorted((one, two), key=lambda s: s.id)
    first_len = _raw_bytes_for(first, primary_store=primary.store)
    checkpoint = create_sqlite_checkpoint(
        database_path=database_path,
        trigger_cycle=cycles[TRIGGER_LABEL],
        primary_store=primary,
        recovery_store=recovery,
        created_at=CREATED_AT,
    )
    restore_store = LocalRecoveryStore(
        tmp_path / "restored-objects", failure_domain_id="fixture-new-object-target-domain"
    )
    restored_database = tmp_path / "restored.db"
    # Under-cap: restore succeeds with a full success receipt and both refs.
    receipt = restore_sqlite_checkpoint(
        checkpoint=checkpoint,
        recovery_store=recovery,
        restore_store=restore_store,
        database_target=restored_database,
        target_id="fixture-restored-target",
        started_at=RESTORE_STARTED_AT,
        finished_at=RESTORE_FINISHED_AT,
    )
    assert receipt["objectRestore"]["allVerified"] is True
    assert receipt["objectRestore"]["objectReferenceCount"] == 2

    # Cap the cumulative budget to EXACTLY the first object's verified bytes so
    # the second unique object overflows in the restore object loop.
    monkeypatch.setattr(svc, "MAX_UNIQUE_SNAPSHOT_BYTES", first_len)
    fresh_restore = LocalRecoveryStore(
        tmp_path / "restored-objects-2", failure_domain_id="fixture-new-object-target-domain-2"
    )
    over_database = tmp_path / "restored-2.db"
    with pytest.raises(RecoveryPartialFailure, match="BYTE_BUDGET_OVERFLOW"):
        restore_sqlite_checkpoint(
            checkpoint=checkpoint,
            recovery_store=recovery,
            restore_store=fresh_restore,
            database_target=over_database,
            target_id="fixture-restored-target-2",
            started_at=RESTORE_STARTED_AT,
            finished_at=RESTORE_FINISHED_AT,
        )
    # Relational restore ran BEFORE the object loop, so the DB target EXISTS
    # even though the overall restore produced no success receipt.
    assert over_database.exists()
    # The first object (actual first by id) was written (bounded partial); the
    # second was refused before its write and is therefore ABSENT.
    restored_snapshot = fresh_restore.inventory_orphans(
        referenced_uris=(), object_kind=StorageObjectKind.SNAPSHOT
    )
    assert restored_snapshot.listed_count == 1
    assert restored_snapshot.orphan_objects[0].content_sha256 == first.content_hash
    assert second.content_hash not in {
        item.content_sha256 for item in restored_snapshot.orphan_objects
    }


def test_real_checkpoint_and_restore_deduplicate_identical_rows(
    tmp_path: Path,
    _template_db: tuple[Path, dict],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two source_snapshot rows sharing identical bytes (same URI + digest) are
    one unique object: a cumulative cap of exactly len(raw) must admit both
    references, and checkpoint+restore must both report 2 references / 1 unique
    object.  A helper-only dedup test is NOT sufficient — this drives the real
    checkpoint and restore loops."""
    import app.backup.service as svc

    database_path = tmp_path / "source.db"
    template, cycles = _template_db
    _sqlite_backup(template, database_path)
    primary, recovery, _primary_root, _recovery_root = _domains(tmp_path)

    raw = b'{"fixture":"identical-dedup"}\n'
    # The cumulative cap is EXACTLY the single unique object's verified bytes:
    # dedup must ensure the second reference is free (counted once) rather than
    # overflowing.  Set it before BOTH checkpoint and restore.
    monkeypatch.setattr(svc, "MAX_UNIQUE_SNAPSHOT_BYTES", len(raw))
    _append_snapshot(
        database_path=database_path,
        primary_store=primary.store,
        source_id="dedup-source-a",
        raw_bytes=raw,
    )
    _append_snapshot(
        database_path=database_path,
        primary_store=primary.store,
        source_id="dedup-source-b",
        raw_bytes=raw,
    )
    checkpoint = create_sqlite_checkpoint(
        database_path=database_path,
        trigger_cycle=cycles[TRIGGER_LABEL],
        primary_store=primary,
        recovery_store=recovery,
        created_at=CREATED_AT,
    )
    manifest = checkpoint["objectManifest"]
    assert manifest["objectReferenceCount"] == 2
    assert manifest["uniqueObjectCount"] == 1

    restore_store = LocalRecoveryStore(
        tmp_path / "restored-objects", failure_domain_id="fixture-dedup-restore-domain"
    )
    receipt = restore_sqlite_checkpoint(
        checkpoint=checkpoint,
        recovery_store=recovery,
        restore_store=restore_store,
        database_target=tmp_path / "dedup-restored.db",
        target_id="fixture-dedup-restored-target",
        started_at=RESTORE_STARTED_AT,
        finished_at=RESTORE_FINISHED_AT,
    )
    assert receipt["objectRestore"]["objectReferenceCount"] == 2
    assert receipt["objectRestore"]["uniqueObjectCount"] == 1
    # Only one physical object was stored in the restore target.
    restored_snapshot = restore_store.inventory_orphans(
        referenced_uris=(), object_kind=StorageObjectKind.SNAPSHOT
    )
    assert restored_snapshot.listed_count == 1


def test_stream_object_growth_after_fstat_requests_exactly_cap_plus_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The PUBLIC ``_stream_object`` (not just ``_sha256_stream``) must clamp its
    requests to ``min(_CHUNK_SIZE, cap+1-total)`` against IN-PLACE file growth:
    fstat pre-checks a small real on-disk object, but the handle is swapped for a
    guarded reader that serves bytes far past the cap.  The reader must be driven
    by the profile's OWN cap+1 clamp (never cap+CHUNK), and _stream_object must
    reject the object."""
    import app.storage.local as local_module

    class _Growing:
        """Returns far more bytes than the fstat-reported size claims."""

        def __init__(self, actual: int, max_chunk: int) -> None:
            self._actual = actual
            self._max_chunk = max_chunk
            self.pos = 0
            self.requests: list[int] = []

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

        def read(self, size: int = -1) -> bytes:
            if size < 0 or size > self._max_chunk:
                raise AssertionError(f"unbounded read(size={size}) issued")
            self.requests.append(size)
            if self.pos >= self._actual:
                return b""
            take = min(self._actual - self.pos, size)
            self.pos += take
            return b"g" * take

    storage = LocalSnapshotStorage(tmp_path / "objects")
    cap = 1000
    monkeypatch.setattr(local_module, "MAX_SNAPSHOT_BYTES", cap)

    small_raw = b"g" * 16  # real file: small enough to pass the fstat precheck
    digest = compute_content_hash(small_raw)
    address = storage.address_for_content_hash(digest)
    path = Path(address.uri)
    path.parent.mkdir(parents=True)
    path.write_bytes(small_raw)

    # Swap the fstat'd handle for a reader that yields bytes far beyond the cap.
    growing = _Growing(
        actual=16 + local_module._CHUNK_SIZE * 4, max_chunk=local_module._CHUNK_SIZE
    )
    monkeypatch.setattr(local_module.os, "fdopen", lambda fd, *a, **k: growing)

    with pytest.raises(SnapshotStorageIntegrityError, match="snapshot byte cap"):
        storage._stream_object(path, cap=cap, materialize=False)
    # Requests are bounded: never a full chunk beyond the cap, total <= cap+1.
    assert growing.requests
    assert all(0 < r <= local_module._CHUNK_SIZE for r in growing.requests)
    assert max(growing.requests) <= cap + 1
    assert sum(growing.requests) <= cap + 1


def test_cumulative_budget_counts_duplicate_references_once(tmp_path, monkeypatch) -> None:
    """A manifest citing the same snapshot twice charges its bytes exactly once."""
    import app.backup.service as svc

    monkeypatch.setattr(svc, "MAX_UNIQUE_SNAPSHOT_BYTES", 2048)
    raw = b"u" * 1024
    records: dict = {}
    digest = compute_content_hash(raw)
    total = svc._charge_snapshot_bytes(
        key=("file:///a", digest),
        verified_byte_length=len(raw),
        charged=records,
        charging_bytes=0,
    )
    assert total == 1024
    both = svc._charge_snapshot_bytes(
        key=("file:///a", digest),
        verified_byte_length=len(raw),
        charged=records,
        charging_bytes=total,
    )
    assert both == 1024  # duplicate reference: unchanged running total
    assert len(records) == 1
    assert sum(records.values()) == 1024


def test_cumulative_budget_exact_under_cap_receipt_equivalent(tmp_path, monkeypatch) -> None:
    import app.backup.service as svc

    monkeypatch.setattr(svc, "MAX_UNIQUE_SNAPSHOT_BYTES", 100)
    raw = b"z" * 100
    records: dict = {}
    digest = compute_content_hash(raw)
    total = svc._charge_snapshot_bytes(
        key=("file:///x", digest),
        verified_byte_length=len(raw),
        charged=records,
        charging_bytes=0,
    )
    assert total == 100
    # Second reference is a duplicate: free, never overflows.
    final = svc._charge_snapshot_bytes(
        key=("file:///x", digest),
        verified_byte_length=len(raw),
        charged=records,
        charging_bytes=total,
    )
    assert final == 100
    assert sum(records.values()) == 100


def test_cumulative_budget_overflow_fails_before_charging(tmp_path, monkeypatch) -> None:
    """Once the running total plus the next copy exceeds the cap, the helper
    raises WITHOUT recording the current copy (so its write is never reached)."""
    import app.backup.service as svc

    monkeypatch.setattr(svc, "MAX_UNIQUE_SNAPSHOT_BYTES", 10)
    records: dict = {}
    first = svc._charge_snapshot_bytes(
        key=("file:///a", compute_content_hash(b"x" * 8)),
        verified_byte_length=8,
        charged=records,
        charging_bytes=0,
    )
    assert first == 8
    with pytest.raises(RecoveryPartialFailure, match="BYTE_BUDGET_OVERFLOW"):
        svc._charge_snapshot_bytes(
            key=("file:///b", compute_content_hash(b"y" * 8)),
            verified_byte_length=8,
            charged=records,
            charging_bytes=first,
        )
    # The over-budget object was never recorded.
    assert len(records) == 1