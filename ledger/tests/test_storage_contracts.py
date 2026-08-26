from pathlib import Path
from types import SimpleNamespace

import pytest

from app.storage.base import (
    OrphanInventoryReceipt,
    SnapshotStorageIntegrityError,
    SnapshotStorageProtocolError,
    SnapshotRetentionAdmin,
    SnapshotStorageRunner,
    StorageSecurityPosture,
    StorageObjectAddress,
    StorageObjectKind,
    StorageReadResult,
    StorageReadReceipt,
    StorageStoreReceipt,
    StorageVerificationReceipt,
)
from app.storage.local import LocalSnapshotStorage, compute_content_hash


def test_runner_storage_contract_excludes_retention_delete_and_admin_controls() -> None:
    runner_surface = set(SnapshotStorageRunner.__dict__)
    admin_surface = set(SnapshotRetentionAdmin.__dict__)

    assert {
        "store_snapshot",
        "read_snapshot",
        "verify_snapshot",
        "inventory_orphans",
    } <= runner_surface
    assert {"configure_retention", "delete_expired"} <= admin_surface
    assert not runner_surface.intersection(
        {"configure_retention", "delete_expired", "delete", "overwrite"}
    )

    posture = StorageSecurityPosture.application_only()
    assert posture.runner_capability == "object_read_write_list_only"
    assert posture.provider_retention_evidence == "external_evidence_required"
    assert posture.application_integrity_proof == "full_byte_sha256_read_back"
    assert posture.exposes_admin_controls is False
    assert posture.exposes_delete is False


def test_local_storage_implements_typed_deterministic_receipts_compatibly(
    tmp_path: Path,
) -> None:
    storage = LocalSnapshotStorage(tmp_path / "objects")
    raw_bytes = b"typed immutable local evidence"

    created = storage.store_snapshot(raw_bytes=raw_bytes)
    reused = storage.store_snapshot(raw_bytes=raw_bytes)
    reused_again = storage.store_snapshot(raw_bytes=raw_bytes)

    assert isinstance(storage, SnapshotStorageRunner)
    assert created.outcome == "created"
    assert reused.outcome == reused_again.outcome == "reused"
    assert reused.receipt_id == reused_again.receipt_id
    assert created.address == reused.address
    assert created.address.content_sha256 == compute_content_hash(raw_bytes)
    assert created.write_precondition == "atomic_no_replace"
    assert created.provider_retention_evidence == "external_evidence_required"

    read = storage.read_snapshot(
        uri=created.address.uri,
        content_sha256=created.address.content_sha256,
    )
    verified = storage.verify_snapshot(
        uri=created.address.uri,
        content_sha256=created.address.content_sha256,
    )
    assert read.raw_bytes == raw_bytes
    assert read.verification == verified
    assert read.receipt_id == storage.read_snapshot(
        uri=created.address.uri,
        content_sha256=created.address.content_sha256,
    ).receipt_id

    legacy_uri, legacy_hash = storage.save(
        official_source_id="source-a",
        raw_bytes=raw_bytes,
        extension="json",
    )
    assert (legacy_uri, legacy_hash) == (
        created.address.uri,
        created.address.content_sha256,
    )
    assert storage.read(legacy_uri) == raw_bytes
    assert storage.verify(uri=legacy_uri, content_hash=legacy_hash) == verified


def test_local_artifact_namespace_cannot_collide_with_snapshot_namespace(
    tmp_path: Path,
) -> None:
    storage = LocalSnapshotStorage(tmp_path)
    raw_bytes = b"same bytes, distinct governed object families"

    snapshot = storage.store_snapshot(raw_bytes=raw_bytes)
    artifact = storage.store_snapshot(
        raw_bytes=raw_bytes,
        object_kind=StorageObjectKind.ARTIFACT,
    )

    assert snapshot.address.content_sha256 == artifact.address.content_sha256
    assert snapshot.address.uri != artifact.address.uri
    assert snapshot.address.object_kind is StorageObjectKind.SNAPSHOT
    assert artifact.address.object_kind is StorageObjectKind.ARTIFACT


def test_local_orphan_inventory_is_read_only_exact_and_deterministic(tmp_path: Path) -> None:
    storage = LocalSnapshotStorage(tmp_path)
    referenced = storage.store_snapshot(raw_bytes=b"referenced")
    orphan = storage.store_snapshot(raw_bytes=b"orphan")
    missing_digest = compute_content_hash(b"missing")
    missing = storage.address_for_content_hash(missing_digest)

    first = storage.inventory_orphans(
        referenced_uris=[referenced.address.uri, missing.uri]
    )
    second = storage.inventory_orphans(
        referenced_uris=[missing.uri, referenced.address.uri]
    )

    assert first == second
    assert first.receipt_id == second.receipt_id
    assert first.pages_scanned == 1
    assert first.listed_count == 2
    assert first.referenced_count == 2
    assert first.orphan_objects == (orphan.address,)
    assert first.missing_references == (missing,)
    assert first.content_verification == "not_performed_inventory_only"

    with pytest.raises(SnapshotStorageIntegrityError, match="duplicate reference"):
        storage.inventory_orphans(
            referenced_uris=[referenced.address.uri, referenced.address.uri]
        )


def test_local_orphan_inventory_duplicate_reference_check_scales_linearly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    uri_hash_calls = 0

    class CountingUri(str):
        def __hash__(self) -> int:
            nonlocal uri_hash_calls
            uri_hash_calls += 1
            return super().__hash__()

    storage = LocalSnapshotStorage(tmp_path)
    addresses: dict[str, StorageObjectAddress] = {}
    reference_count = 64
    for index in range(reference_count):
        digest = f"{index + 1:064x}"
        key = f"{digest[:2]}/{digest[2:4]}/{digest}"
        uri = f"reference-{index}"
        addresses[uri] = StorageObjectAddress(
            provider="local",
            object_kind=StorageObjectKind.SNAPSHOT,
            uri=CountingUri(uri),
            key=key,
            content_sha256=digest,
        )

    monkeypatch.setattr(
        storage,
        "_canonical_address_from_uri",
        lambda uri, *, object_kind: addresses[uri],
    )

    with pytest.raises(SnapshotStorageIntegrityError, match="duplicate reference"):
        storage.inventory_orphans(
            referenced_uris=[*addresses, "reference-0"],
        )

    assert uri_hash_calls == 2 * reference_count + 1


def test_local_inventory_rejects_symlinked_fanout_directory(tmp_path: Path) -> None:
    storage = LocalSnapshotStorage(tmp_path / "objects")
    raw_bytes = b"outside object must not enter inventory"
    digest = compute_content_hash(raw_bytes)
    outside = tmp_path / "outside" / digest[2:4]
    outside.mkdir(parents=True)
    (outside / digest).write_bytes(raw_bytes)
    (storage.root / digest[:2]).symlink_to(outside.parent, target_is_directory=True)

    with pytest.raises(SnapshotStorageIntegrityError, match="symbolic link"):
        storage.inventory_orphans(referenced_uris=[])


def test_local_store_rejects_symlinked_fanout_without_writing_outside(tmp_path: Path) -> None:
    storage = LocalSnapshotStorage(tmp_path / "objects")
    raw_bytes = b"must stay within the configured root"
    digest = compute_content_hash(raw_bytes)
    outside = tmp_path / "outside"
    outside.mkdir()
    (storage.root / digest[:2]).symlink_to(outside, target_is_directory=True)

    with pytest.raises(SnapshotStorageIntegrityError, match="symbolic link|directory"):
        storage.store_snapshot(raw_bytes=raw_bytes)

    assert not (outside / digest[2:4] / digest).exists()
    assert not list(outside.rglob("*.tmp"))


def test_receipts_do_not_render_raw_evidence_and_reject_false_denominators(
    tmp_path: Path,
) -> None:
    storage_address = StorageObjectAddress(
        provider="local",
        object_kind=StorageObjectKind.SNAPSHOT,
        uri="/safe/aa/bb/" + "a" * 64,
        key="aa/bb/" + "a" * 64,
        content_sha256="a" * 64,
    )
    with pytest.raises(SnapshotStorageProtocolError, match="denominators"):
        OrphanInventoryReceipt.create(
            provider="local",
            object_kind=StorageObjectKind.SNAPSHOT,
            scope="snapshots",
            pages_scanned=1,
            listed_count=2,
            referenced_count=0,
            referenced_present=[],
            orphan_objects=[storage_address],
            missing_references=[],
        )

    storage = LocalSnapshotStorage(tmp_path / "receipt-repr-test")
    # Construct through the real adapter so the receipt remains fully bound.
    read = storage.read_snapshot(
        uri=storage.store_snapshot(raw_bytes=b"secret evidence bytes").address.uri,
        content_sha256=compute_content_hash(b"secret evidence bytes"),
    )
    assert "secret evidence bytes" not in repr(read)


def test_read_result_rejects_same_length_bytes_substituted_after_verification() -> None:
    expected_bytes = b"expected"
    substituted_bytes = b"altered!"
    digest = compute_content_hash(expected_bytes)
    address = StorageObjectAddress(
        provider="local",
        object_kind=StorageObjectKind.SNAPSHOT,
        uri="/safe/" + digest,
        key="aa/bb/" + digest,
        content_sha256=digest,
    )
    verification = StorageVerificationReceipt.create(
        address=address,
        expected_sha256=digest,
        observed_sha256=digest,
        byte_length=len(expected_bytes),
        metadata={},
    )

    with pytest.raises(SnapshotStorageIntegrityError, match="receipt digest"):
        StorageReadResult.create(
            raw_bytes=substituted_bytes,
            verification=verification,
        )


def test_receipt_public_constructor_cannot_forge_verification_identity() -> None:
    expected_bytes = b"expected"
    substituted_bytes = b"altered!"
    expected_digest = compute_content_hash(expected_bytes)
    substituted_digest = compute_content_hash(substituted_bytes)
    address = StorageObjectAddress(
        provider="local",
        object_kind=StorageObjectKind.SNAPSHOT,
        uri="/safe/" + expected_digest,
        key="aa/bb/" + expected_digest,
        content_sha256=expected_digest,
    )

    with pytest.raises(TypeError):
        StorageVerificationReceipt(
            receipt_id="forged",
            address=address,
            expected_sha256=expected_digest,
            observed_sha256=substituted_digest,
            byte_length=len(substituted_bytes),
            metadata_sha256="0" * 64,
        )


def test_composed_receipts_reject_verification_duck_objects() -> None:
    digest = compute_content_hash(b"expected")
    address = StorageObjectAddress(
        provider="local",
        object_kind=StorageObjectKind.SNAPSHOT,
        uri="/safe/" + digest,
        key="aa/bb/" + digest,
        content_sha256=digest,
    )
    forged = SimpleNamespace(
        receipt_id="storage-verification-v1:" + "0" * 64,
        address=address,
        expected_sha256=digest,
        observed_sha256=digest,
        byte_length=len(b"expected"),
        metadata_sha256="0" * 64,
        status="verified",
        proof="full_byte_sha256_read_back",
    )

    with pytest.raises(SnapshotStorageProtocolError, match="canonical verification"):
        StorageReadReceipt.create(verification=forged)
    with pytest.raises(SnapshotStorageProtocolError, match="canonical verification"):
        StorageStoreReceipt.create(
            outcome="created",
            verification=forged,
            write_precondition="atomic_no_replace",
        )


def test_orphan_receipt_rejects_noncanonical_empty_scope_identity() -> None:
    with pytest.raises(SnapshotStorageProtocolError, match="provider"):
        OrphanInventoryReceipt.create(
            provider="R2",
            object_kind=StorageObjectKind.SNAPSHOT,
            scope="snapshots",
            pages_scanned=0,
            listed_count=0,
            referenced_count=0,
            referenced_present=[],
            orphan_objects=[],
            missing_references=[],
        )


@pytest.mark.parametrize(
    "provider,key",
    [
        ("R2", "aa/bb/" + "a" * 64),
        ("r2", "../escape"),
        ("r2", "/absolute"),
        ("r2", "aa//" + "a" * 64),
        ("r2", "aa\\bb\\" + "a" * 64),
    ],
)
def test_object_address_rejects_noncanonical_provider_and_key(
    provider: str, key: str
) -> None:
    with pytest.raises(SnapshotStorageProtocolError, match="provider|key"):
        StorageObjectAddress(
            provider=provider,
            object_kind=StorageObjectKind.SNAPSHOT,
            uri="r2://bucket/safe",
            key=key,
            content_sha256="a" * 64,
        )
