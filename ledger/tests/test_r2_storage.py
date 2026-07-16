from __future__ import annotations

import base64
import hashlib
from collections.abc import Mapping
from io import BytesIO
from typing import Any

import pytest

from app.storage.base import (
    SnapshotStorageCollisionError,
    SnapshotStorageIntegrityError,
    SnapshotStorageMetadataError,
    SnapshotStorageMissingError,
    SnapshotStorageProtocolError,
    SnapshotStorageRunner,
    SnapshotStorageUnavailableError,
    StorageObjectKind,
    compute_content_hash,
)
from app.storage.r2 import R2SnapshotStorage


class FakeS3Error(RuntimeError):
    def __init__(self, *, status: int, code: str) -> None:
        super().__init__(f"fake S3 error {status} {code}")
        self.response = {
            "ResponseMetadata": {"HTTPStatusCode": status},
            "Error": {"Code": code},
        }


class FakeS3Client:
    def __init__(self, *, page_size: int = 100) -> None:
        self.objects: dict[str, dict[str, Any]] = {}
        self.page_size = page_size
        self.put_calls: list[dict[str, Any]] = []
        self.get_calls: list[dict[str, Any]] = []
        self.list_calls: list[dict[str, Any]] = []
        self.read_bodies: list[BytesIO] = []
        self.put_error: Exception | None = None
        self.get_error: Exception | None = None
        self.omit_next_token = False
        self.repeat_next_token = False
        self.inject_duplicate_key = False
        self.put_status: int | None = None
        self.get_status: int | None = None
        self.list_status: int | None = None
        self.key_count_override: object | None = None
        self.untruncated_next_token: str | None = None

    def put_object(self, **kwargs: Any) -> Mapping[str, Any]:
        self.put_calls.append(dict(kwargs))
        if self.put_error is not None:
            raise self.put_error
        key = kwargs["Key"]
        if key in self.objects:
            raise FakeS3Error(status=412, code="PreconditionFailed")
        assert kwargs["IfNoneMatch"] == "*"
        self.objects[key] = {
            "Body": bytes(kwargs["Body"]),
            "Metadata": dict(kwargs["Metadata"]),
            "ContentLength": len(kwargs["Body"]),
        }
        response: dict[str, Any] = {"ETag": '"fake-etag"'}
        if self.put_status is not None:
            response["ResponseMetadata"] = {"HTTPStatusCode": self.put_status}
        return response

    def get_object(self, **kwargs: Any) -> Mapping[str, Any]:
        self.get_calls.append(dict(kwargs))
        if self.get_error is not None:
            raise self.get_error
        key = kwargs["Key"]
        if key not in self.objects:
            raise FakeS3Error(status=404, code="NoSuchKey")
        record = self.objects[key]
        body = BytesIO(record["Body"])
        self.read_bodies.append(body)
        response = {
            "Body": body,
            "Metadata": dict(record["Metadata"]),
            "ContentLength": record["ContentLength"],
        }
        if self.get_status is not None:
            response["ResponseMetadata"] = {"HTTPStatusCode": self.get_status}
        return response

    def list_objects_v2(self, **kwargs: Any) -> Mapping[str, Any]:
        self.list_calls.append(dict(kwargs))
        prefix = kwargs["Prefix"]
        keys = sorted(key for key in self.objects if key.startswith(prefix))
        offset = int(kwargs.get("ContinuationToken", "0"))
        page = keys[offset : offset + self.page_size]
        if self.inject_duplicate_key and offset > 0 and keys:
            page = [keys[0], *page]
        next_offset = offset + self.page_size
        truncated = next_offset < len(keys)
        response: dict[str, Any] = {
            "Contents": [{"Key": key} for key in page],
            "IsTruncated": truncated,
        }
        if self.key_count_override is not None:
            response["KeyCount"] = self.key_count_override
        if not truncated and self.untruncated_next_token is not None:
            response["NextContinuationToken"] = self.untruncated_next_token
        if truncated and not self.omit_next_token:
            response["NextContinuationToken"] = (
                str(offset) if self.repeat_next_token else str(next_offset)
            )
        if self.list_status is not None:
            response["ResponseMetadata"] = {"HTTPStatusCode": self.list_status}
        return response


def _storage(client: FakeS3Client) -> R2SnapshotStorage:
    return R2SnapshotStorage(
        client=client,
        bucket="benchmark-evidence",
        prefix="immutable/v1",
    )


def test_r2_store_uses_conditional_create_and_application_read_back_sha256() -> None:
    client = FakeS3Client()
    storage = _storage(client)
    raw_bytes = b"immutable R2 evidence"

    receipt = storage.store_snapshot(raw_bytes=raw_bytes)

    assert isinstance(storage, SnapshotStorageRunner)
    assert receipt.outcome == "created"
    assert receipt.write_precondition == "if_none_match_wildcard"
    assert receipt.address.uri.startswith("r2://benchmark-evidence/immutable/v1/snapshot/sha256/")
    assert receipt.address.key.endswith(receipt.address.content_sha256)
    assert client.put_calls == [
        {
            "Bucket": "benchmark-evidence",
            "Key": receipt.address.key,
            "Body": raw_bytes,
            "IfNoneMatch": "*",
            "Metadata": {
                "storage-contract": "immutable-object-v1",
                "object-kind": "snapshot",
                "content-sha256": compute_content_hash(raw_bytes),
                "byte-length": str(len(raw_bytes)),
            },
            "ChecksumSHA256": base64.b64encode(hashlib.sha256(raw_bytes).digest()).decode("ascii"),
        }
    ]
    assert client.get_calls == [
        {"Bucket": "benchmark-evidence", "Key": receipt.address.key}
    ]
    assert len(client.read_bodies) == 1
    assert client.read_bodies[0].closed
    assert storage.security_posture.provider_retention_evidence == "external_evidence_required"
    assert storage.security_posture.application_integrity_proof == "full_byte_sha256_read_back"
    assert not hasattr(storage, "delete")
    assert not hasattr(storage, "overwrite")
    assert not hasattr(storage, "configure_retention")


def test_r2_exact_duplicate_is_reused_only_after_full_read_back_verification() -> None:
    client = FakeS3Client()
    storage = _storage(client)
    raw_bytes = b"exact duplicate"

    created = storage.store_snapshot(raw_bytes=raw_bytes)
    reused = storage.store_snapshot(raw_bytes=raw_bytes)
    reused_again = storage.store_snapshot(raw_bytes=raw_bytes)

    assert created.outcome == "created"
    assert reused.outcome == reused_again.outcome == "reused"
    assert reused.receipt_id == reused_again.receipt_id
    assert created.address == reused.address
    assert len(client.objects) == 1
    assert len(client.put_calls) == 3
    assert len(client.get_calls) == 3


def test_r2_duplicate_with_conflicting_bytes_fails_as_collision() -> None:
    client = FakeS3Client()
    storage = _storage(client)
    raw_bytes = b"expected immutable bytes"
    created = storage.store_snapshot(raw_bytes=raw_bytes)
    client.objects[created.address.key]["Body"] = b"tampered"
    client.objects[created.address.key]["ContentLength"] = len(b"tampered")

    with pytest.raises(SnapshotStorageCollisionError, match="not expected digest"):
        storage.store_snapshot(raw_bytes=raw_bytes)


def test_r2_verified_read_rejects_tamper_missing_and_conflicting_metadata() -> None:
    client = FakeS3Client()
    storage = _storage(client)
    created = storage.store_snapshot(raw_bytes=b"evidence")
    key = created.address.key

    client.objects[key]["Body"] = b"tampered"
    client.objects[key]["ContentLength"] = len(b"tampered")
    with pytest.raises(SnapshotStorageIntegrityError, match="not expected digest"):
        storage.verify_snapshot(
            uri=created.address.uri,
            content_sha256=created.address.content_sha256,
        )

    client.objects[key]["Body"] = b"evidence"
    client.objects[key]["ContentLength"] = len(b"evidence")
    client.objects[key]["Metadata"]["content-sha256"] = "f" * 64
    with pytest.raises(SnapshotStorageMetadataError, match="metadata"):
        storage.read_snapshot(
            uri=created.address.uri,
            content_sha256=created.address.content_sha256,
        )

    client.objects[key]["Metadata"] = {
        "Content-Sha256": created.address.content_sha256,
        "content-sha256": created.address.content_sha256,
        "storage-contract": "immutable-object-v1",
        "object-kind": "snapshot",
        "byte-length": str(len(b"evidence")),
    }
    with pytest.raises(SnapshotStorageMetadataError, match="duplicate"):
        storage.read_snapshot(
            uri=created.address.uri,
            content_sha256=created.address.content_sha256,
        )

    client.objects[key]["Metadata"] = {
        "storage-contract": "immutable-object-v1",
        "object-kind": "snapshot",
        "content-sha256": created.address.content_sha256,
        "byte-length": str(len(b"evidence")),
    }
    client.objects[key]["ContentLength"] = len(b"evidence") + 1
    with pytest.raises(SnapshotStorageIntegrityError, match="ContentLength"):
        storage.read_snapshot(
            uri=created.address.uri,
            content_sha256=created.address.content_sha256,
        )

    del client.objects[key]
    with pytest.raises(SnapshotStorageMissingError, match="missing"):
        storage.verify_snapshot(
            uri=created.address.uri,
            content_sha256=created.address.content_sha256,
        )


@pytest.mark.parametrize(
    "bucket,prefix",
    [
        ("../unsafe", "immutable/v1"),
        ("ABCD", "immutable/v1"),
        ("ab", "immutable/v1"),
        ("a" * 64, "immutable/v1"),
        ("-unsafe", "immutable/v1"),
        ("unsafe-", "immutable/v1"),
        ("unsafe.bucket", "immutable/v1"),
        ("safe", "/absolute"),
        ("safe", "immutable/../escape"),
        ("safe", "immutable//v1"),
    ],
)
def test_r2_rejects_unsafe_bucket_and_prefix_configuration(bucket: str, prefix: str) -> None:
    with pytest.raises(SnapshotStorageProtocolError, match="bucket|prefix"):
        R2SnapshotStorage(client=FakeS3Client(), bucket=bucket, prefix=prefix)


def test_r2_rejects_noncanonical_or_substituted_uris() -> None:
    storage = _storage(FakeS3Client())
    digest = compute_content_hash(b"safe")
    address = storage.address_for_content_hash(digest)

    for unsafe in (
        address.uri.replace("benchmark-evidence", "other-bucket"),
        address.uri + "?version=mutable",
        address.uri.replace("/sha256/", "/sha256/../"),
        address.uri.replace(digest, "A" * 64),
    ):
        with pytest.raises(SnapshotStorageIntegrityError, match="canonical|bucket|SHA-256"):
            storage.verify_snapshot(uri=unsafe, content_sha256=digest)

    for malformed in (
        "r2://[invalid/immutable/v1/snapshot/sha256/aa/aa/" + digest,
        "r2://benchmark-evidence:not-a-port/immutable/v1/snapshot/sha256/aa/aa/" + digest,
    ):
        with pytest.raises(SnapshotStorageIntegrityError, match="malformed|canonical"):
            storage.verify_snapshot(uri=malformed, content_sha256=digest)

    with pytest.raises(SnapshotStorageIntegrityError, match="malformed"):
        storage.read("r2://[invalid")


def test_r2_orphan_inventory_follows_every_page_and_balances_missing_references() -> None:
    client = FakeS3Client(page_size=1)
    storage = _storage(client)
    stored = [storage.store_snapshot(raw_bytes=value) for value in (b"one", b"two", b"three")]
    missing = storage.address_for_content_hash(compute_content_hash(b"missing"))

    receipt = storage.inventory_orphans(
        referenced_uris=[stored[1].address.uri, missing.uri]
    )

    assert receipt.pages_scanned == 3
    assert receipt.listed_count == 3
    assert receipt.referenced_count == 2
    assert receipt.referenced_present == (stored[1].address,)
    assert receipt.orphan_objects == tuple(
        sorted((stored[0].address, stored[2].address), key=lambda item: item.key)
    )
    assert receipt.missing_references == (missing,)
    assert [call.get("ContinuationToken") for call in client.list_calls] == [None, "1", "2"]

    with pytest.raises(SnapshotStorageIntegrityError, match="duplicate reference"):
        storage.inventory_orphans(
            referenced_uris=[stored[1].address.uri, stored[1].address.uri]
        )

    artifact = storage.store_snapshot(
        raw_bytes=b"artifact",
        object_kind=StorageObjectKind.ARTIFACT,
    )
    with pytest.raises(SnapshotStorageIntegrityError, match="different object kind"):
        storage.inventory_orphans(referenced_uris=[artifact.address.uri])


@pytest.mark.parametrize("fault", ["missing_cursor", "repeated_cursor", "duplicate_key"])
def test_r2_orphan_inventory_fails_closed_on_malformed_pagination(fault: str) -> None:
    client = FakeS3Client(page_size=1)
    storage = _storage(client)
    storage.store_snapshot(raw_bytes=b"one")
    storage.store_snapshot(raw_bytes=b"two")
    if fault == "missing_cursor":
        client.omit_next_token = True
    elif fault == "repeated_cursor":
        client.repeat_next_token = True
    else:
        client.inject_duplicate_key = True

    with pytest.raises(SnapshotStorageProtocolError, match="cursor|duplicate"):
        storage.inventory_orphans(referenced_uris=[])


@pytest.mark.parametrize("key_count", [5, -1, True, "0"])
def test_r2_orphan_inventory_rejects_contradictory_key_count(key_count: object) -> None:
    client = FakeS3Client()
    client.key_count_override = key_count
    storage = _storage(client)

    with pytest.raises(SnapshotStorageProtocolError, match="KeyCount"):
        storage.inventory_orphans(referenced_uris=[])


def test_r2_orphan_inventory_rejects_cursor_on_untruncated_page() -> None:
    client = FakeS3Client()
    client.untruncated_next_token = "unexpected"
    storage = _storage(client)

    with pytest.raises(SnapshotStorageProtocolError, match="continuation cursor"):
        storage.inventory_orphans(referenced_uris=[])


def test_r2_nonprecondition_provider_failure_is_not_misreported_as_reuse() -> None:
    client = FakeS3Client()
    client.put_error = FakeS3Error(status=500, code="InternalError")
    storage = _storage(client)

    with pytest.raises(SnapshotStorageUnavailableError, match="put_object"):
        storage.store_snapshot(raw_bytes=b"not stored")
    assert not client.objects


def test_r2_contradictory_provider_error_envelopes_fail_closed() -> None:
    client = FakeS3Client()
    storage = _storage(client)
    client.put_error = FakeS3Error(status=500, code="PreconditionFailed")
    with pytest.raises(SnapshotStorageUnavailableError, match="put_object"):
        storage.store_snapshot(raw_bytes=b"must not be called reuse")
    assert not client.get_calls

    address = storage.address_for_content_hash(compute_content_hash(b"missing"))
    for error in (
        FakeS3Error(status=500, code="NoSuchKey"),
        FakeS3Error(status=404, code="InternalError"),
    ):
        client.get_error = error
        with pytest.raises(SnapshotStorageUnavailableError, match="get_object"):
            storage.verify_snapshot(
                uri=address.uri,
                content_sha256=address.content_sha256,
            )


def test_r2_non_success_mapping_envelopes_fail_closed() -> None:
    put_client = FakeS3Client()
    put_client.put_status = 412
    with pytest.raises(SnapshotStorageProtocolError, match="non-success"):
        _storage(put_client).store_snapshot(raw_bytes=b"contradictory put")
    assert not put_client.get_calls

    get_client = FakeS3Client()
    get_storage = _storage(get_client)
    stored = get_storage.store_snapshot(raw_bytes=b"contradictory get")
    get_client.get_status = 404
    with pytest.raises(SnapshotStorageProtocolError, match="non-success"):
        get_storage.read_snapshot(
            uri=stored.address.uri,
            content_sha256=stored.address.content_sha256,
        )

    list_client = FakeS3Client()
    list_storage = _storage(list_client)
    list_client.list_status = 500
    with pytest.raises(SnapshotStorageProtocolError, match="non-success"):
        list_storage.inventory_orphans(referenced_uris=[])
