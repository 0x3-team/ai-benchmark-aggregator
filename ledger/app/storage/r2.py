"""Injected Cloudflare R2/S3-compatible immutable object storage.

This module constructs no SDK client, reads no environment variables, embeds no
credentials, and performs no bucket administration.  Its injected client is
used only for conditional object creation, verified reads, and paginated list
operations.  Provider bucket-lock and ACL evidence remains an external release
gate; application receipts prove only full-byte SHA-256 read-back.
"""

from __future__ import annotations

import base64
import hashlib
import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Protocol
from urllib.parse import urlsplit

from .base import (
    OrphanInventoryReceipt,
    SnapshotStorageCollisionError,
    SnapshotStorageIntegrityError,
    SnapshotStorageMetadataError,
    SnapshotStorageMissingError,
    SnapshotStorageProtocolError,
    SnapshotStorageUnavailableError,
    StorageObjectAddress,
    StorageObjectKind,
    StorageReadResult,
    StorageSecurityPosture,
    StorageStoreReceipt,
    StorageVerificationReceipt,
    compute_content_hash,
    require_full_sha256,
)


_SAFE_COMPONENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_R2_BUCKET = re.compile(r"[a-z0-9](?:[a-z0-9-]{1,61}[a-z0-9])")
_CONTRACT_METADATA = "immutable-object-v1"


class R2ObjectClient(Protocol):
    """Minimal injected S3-compatible object client; no delete/admin methods."""

    def put_object(self, **kwargs: object) -> Mapping[str, object]: ...

    def get_object(self, **kwargs: object) -> Mapping[str, object]: ...

    def list_objects_v2(self, **kwargs: object) -> Mapping[str, object]: ...


class R2SnapshotStorage:
    """Content-addressed immutable snapshot/artifact storage over R2's S3 API."""

    security_posture = StorageSecurityPosture.application_only()

    def __init__(
        self,
        *,
        client: R2ObjectClient,
        bucket: str,
        prefix: str = "immutable/v1",
        max_inventory_pages: int = 10_000,
    ) -> None:
        if not isinstance(bucket, str) or not _R2_BUCKET.fullmatch(bucket):
            raise SnapshotStorageProtocolError(
                "R2 bucket must be 3-63 lowercase alphanumeric/hyphen characters "
                "and begin and end with an alphanumeric character."
            )
        if not isinstance(prefix, str) or not prefix:
            raise SnapshotStorageProtocolError("R2 object prefix is required.")
        parts = prefix.split("/")
        if any(not self._is_safe_component(part) for part in parts):
            raise SnapshotStorageProtocolError("R2 object prefix is not a safe canonical path.")
        if (
            not isinstance(max_inventory_pages, int)
            or isinstance(max_inventory_pages, bool)
            or max_inventory_pages < 1
        ):
            raise SnapshotStorageProtocolError("R2 inventory page bound must be positive.")
        self._client = client
        self.bucket = bucket
        self.prefix = prefix
        self.max_inventory_pages = max_inventory_pages

    @staticmethod
    def _is_safe_component(value: object) -> bool:
        return isinstance(value, str) and bool(_SAFE_COMPONENT.fullmatch(value)) and value not in {
            ".",
            "..",
        }

    @staticmethod
    def _require_object_kind(object_kind: StorageObjectKind) -> StorageObjectKind:
        if not isinstance(object_kind, StorageObjectKind):
            raise SnapshotStorageProtocolError("Object kind must be a StorageObjectKind value.")
        return object_kind

    def _kind_prefix(self, object_kind: StorageObjectKind) -> str:
        kind = self._require_object_kind(object_kind)
        return f"{self.prefix}/{kind.value}/sha256"

    def address_for_content_hash(
        self,
        content_sha256: str,
        *,
        object_kind: StorageObjectKind = StorageObjectKind.SNAPSHOT,
    ) -> StorageObjectAddress:
        digest = require_full_sha256(content_sha256)
        kind = self._require_object_kind(object_kind)
        key = f"{self._kind_prefix(kind)}/{digest[:2]}/{digest[2:4]}/{digest}"
        return StorageObjectAddress(
            provider="r2",
            object_kind=kind,
            uri=f"r2://{self.bucket}/{key}",
            key=key,
            content_sha256=digest,
        )

    @staticmethod
    def _canonical_metadata(
        address: StorageObjectAddress, byte_length: int
    ) -> dict[str, str]:
        return {
            "storage-contract": _CONTRACT_METADATA,
            "object-kind": address.object_kind.value,
            "content-sha256": address.content_sha256,
            "byte-length": str(byte_length),
        }

    def store_snapshot(
        self,
        *,
        raw_bytes: bytes,
        object_kind: StorageObjectKind = StorageObjectKind.SNAPSHOT,
    ) -> StorageStoreReceipt:
        kind = self._require_object_kind(object_kind)
        content_sha256 = compute_content_hash(raw_bytes)
        address = self.address_for_content_hash(content_sha256, object_kind=kind)
        metadata = self._canonical_metadata(address, len(raw_bytes))
        try:
            response = self._client.put_object(
                Bucket=self.bucket,
                Key=address.key,
                Body=raw_bytes,
                IfNoneMatch="*",
                Metadata=metadata,
                ChecksumSHA256=base64.b64encode(hashlib.sha256(raw_bytes).digest()).decode("ascii"),
            )
        except Exception as exc:
            if self._is_precondition_failed(exc):
                outcome = "reused"
            else:
                raise SnapshotStorageUnavailableError(
                    "R2 put_object failed before an immutable object was accepted."
                ) from exc
        else:
            if not isinstance(response, Mapping):
                raise SnapshotStorageProtocolError("R2 put_object returned a non-mapping response.")
            self._validate_success_response(response, operation="put_object")
            outcome = "created"

        try:
            read_receipt = self.read_snapshot(
                uri=address.uri,
                content_sha256=content_sha256,
            )
        except SnapshotStorageIntegrityError as exc:
            if outcome == "reused":
                raise SnapshotStorageCollisionError(
                    f"Existing immutable R2 object at {address.uri} is not expected digest "
                    f"{content_sha256}."
                ) from exc
            raise
        return StorageStoreReceipt.create(
            outcome=outcome,
            verification=read_receipt.verification,
            write_precondition="if_none_match_wildcard",
        )

    def read_snapshot(self, *, uri: str, content_sha256: str) -> StorageReadResult:
        address = self._address_from_uri(uri, expected_sha256=content_sha256)
        try:
            response = self._client.get_object(Bucket=self.bucket, Key=address.key)
        except Exception as exc:
            if self._is_missing(exc):
                raise SnapshotStorageMissingError(
                    f"Required immutable R2 object is missing: {address.uri}"
                ) from exc
            raise SnapshotStorageUnavailableError("R2 get_object failed.") from exc
        if not isinstance(response, Mapping):
            raise SnapshotStorageProtocolError("R2 get_object returned a non-mapping response.")
        self._validate_success_response(response, operation="get_object")

        raw_bytes = self._read_body(response.get("Body"))
        content_length = response.get("ContentLength")
        if (
            not isinstance(content_length, int)
            or isinstance(content_length, bool)
            or content_length < 0
            or content_length != len(raw_bytes)
        ):
            raise SnapshotStorageIntegrityError(
                "R2 ContentLength conflicts with the full read-back byte length."
            )

        metadata = self._normalize_metadata(response.get("Metadata"))
        expected_metadata = self._canonical_metadata(address, len(raw_bytes))
        if metadata != expected_metadata:
            raise SnapshotStorageMetadataError(
                "R2 object metadata conflicts with its canonical content identity."
            )

        observed_sha256 = compute_content_hash(raw_bytes)
        if observed_sha256 != address.content_sha256:
            raise SnapshotStorageIntegrityError(
                f"R2 object at {address.uri} hashes to {observed_sha256}, not expected digest "
                f"{address.content_sha256}."
            )
        verification = StorageVerificationReceipt.create(
            address=address,
            expected_sha256=address.content_sha256,
            observed_sha256=observed_sha256,
            byte_length=len(raw_bytes),
            metadata=metadata,
        )
        return StorageReadResult.create(raw_bytes=raw_bytes, verification=verification)

    def verify_snapshot(
        self, *, uri: str, content_sha256: str
    ) -> StorageVerificationReceipt:
        return self.read_snapshot(
            uri=uri, content_sha256=content_sha256
        ).verification

    def inventory_orphans(
        self,
        *,
        referenced_uris: Iterable[str],
        object_kind: StorageObjectKind = StorageObjectKind.SNAPSHOT,
    ) -> OrphanInventoryReceipt:
        """List every page and reconcile exact canonical references without mutation."""
        kind = self._require_object_kind(object_kind)
        referenced: dict[str, StorageObjectAddress] = {}
        referenced_uri_set: set[str] = set()
        for uri in referenced_uris:
            if not isinstance(uri, str):
                raise SnapshotStorageIntegrityError("R2 inventory references must be canonical URIs.")
            final_component = self._digest_from_uri(uri)
            address = self._address_from_uri(uri, expected_sha256=final_component)
            if address.key in referenced or address.uri in referenced_uri_set:
                raise SnapshotStorageIntegrityError(
                    "R2 orphan inventory contains a duplicate reference URI or key."
                )
            if address.object_kind is not kind:
                raise SnapshotStorageIntegrityError(
                    "R2 orphan inventory reference belongs to a different object kind."
                )
            referenced[address.key] = address
            referenced_uri_set.add(address.uri)

        listed: dict[str, StorageObjectAddress] = {}
        continuation_token: str | None = None
        observed_tokens: set[str] = set()
        pages_scanned = 0
        list_prefix = f"{self._kind_prefix(kind)}/"
        while True:
            if pages_scanned >= self.max_inventory_pages:
                raise SnapshotStorageProtocolError(
                    "R2 orphan inventory exceeded its configured page bound."
                )
            request: dict[str, object] = {
                "Bucket": self.bucket,
                "Prefix": list_prefix,
            }
            if continuation_token is not None:
                request["ContinuationToken"] = continuation_token
            try:
                response = self._client.list_objects_v2(**request)
            except Exception as exc:
                raise SnapshotStorageUnavailableError("R2 list_objects_v2 failed.") from exc
            pages_scanned += 1
            if not isinstance(response, Mapping):
                raise SnapshotStorageProtocolError(
                    "R2 list_objects_v2 returned a non-mapping response."
                )
            self._validate_success_response(response, operation="list_objects_v2")
            contents = response.get("Contents", [])
            if not isinstance(contents, Sequence) or isinstance(contents, (str, bytes, bytearray)):
                raise SnapshotStorageProtocolError("R2 list page Contents is not a sequence.")
            if "KeyCount" in response:
                key_count = response["KeyCount"]
                if (
                    not isinstance(key_count, int)
                    or isinstance(key_count, bool)
                    or key_count < 0
                    or key_count != len(contents)
                ):
                    raise SnapshotStorageProtocolError(
                        "R2 list page KeyCount contradicts its Contents denominator."
                    )
            for entry in contents:
                if not isinstance(entry, Mapping) or not isinstance(entry.get("Key"), str):
                    raise SnapshotStorageProtocolError("R2 list page contains an invalid object key.")
                key = entry["Key"]
                address = self._address_from_key(key, object_kind=kind)
                if address.key in listed:
                    raise SnapshotStorageProtocolError(
                        "R2 list pagination returned a duplicate object key."
                    )
                listed[address.key] = address

            truncated = response.get("IsTruncated")
            if not isinstance(truncated, bool):
                raise SnapshotStorageProtocolError("R2 list page lacks a boolean IsTruncated value.")
            if not truncated:
                if response.get("NextContinuationToken") not in (None, ""):
                    raise SnapshotStorageProtocolError(
                        "Untruncated R2 list page returned a contradictory continuation cursor."
                    )
                break
            next_token = response.get("NextContinuationToken")
            if not isinstance(next_token, str) or not next_token:
                raise SnapshotStorageProtocolError(
                    "Truncated R2 list page is missing its continuation cursor."
                )
            if next_token == continuation_token or next_token in observed_tokens:
                raise SnapshotStorageProtocolError("R2 list pagination repeated a cursor.")
            observed_tokens.add(next_token)
            continuation_token = next_token

        orphan_keys = listed.keys() - referenced.keys()
        missing_keys = referenced.keys() - listed.keys()
        present_keys = referenced.keys() & listed.keys()
        if any(referenced[key] != listed[key] for key in present_keys):
            raise SnapshotStorageIntegrityError(
                "R2 orphan inventory found a substituted referenced object identity."
            )
        return OrphanInventoryReceipt.create(
            provider="r2",
            object_kind=kind,
            scope=list_prefix,
            pages_scanned=pages_scanned,
            listed_count=len(listed),
            referenced_count=len(referenced),
            referenced_present=(referenced[key] for key in present_keys),
            orphan_objects=(listed[key] for key in orphan_keys),
            missing_references=(referenced[key] for key in missing_keys),
        )

    def save(
        self,
        *,
        official_source_id: str,
        raw_bytes: bytes,
        extension: str,
    ) -> tuple[str, str]:
        """Legacy runner compatibility until CFG-01 consumes the typed protocol."""
        _ = official_source_id, extension
        receipt = self.store_snapshot(raw_bytes=raw_bytes)
        return receipt.address.uri, receipt.address.content_sha256

    def read(self, uri: str) -> bytes:
        """Legacy compatibility with application digest verification from the key."""
        final_component = self._digest_from_uri(uri)
        return self.read_snapshot(uri=uri, content_sha256=final_component).raw_bytes

    def verify(self, *, uri: str, content_hash: str) -> StorageVerificationReceipt:
        """Legacy runner compatibility until CFG-01 consumes the typed protocol."""
        return self.verify_snapshot(uri=uri, content_sha256=content_hash)

    def _address_from_uri(
        self, uri: str, *, expected_sha256: str
    ) -> StorageObjectAddress:
        expected = require_full_sha256(expected_sha256)
        if not isinstance(uri, str):
            raise SnapshotStorageIntegrityError("R2 object URI must be canonical text.")
        try:
            parsed = urlsplit(uri)
            parsed_port = parsed.port
        except (ValueError, UnicodeError) as exc:
            raise SnapshotStorageIntegrityError("R2 object URI is malformed.") from exc
        if (
            parsed.scheme != "r2"
            or parsed.netloc != self.bucket
            or parsed.query
            or parsed.fragment
            or parsed.username is not None
            or parsed.password is not None
            or parsed_port is not None
        ):
            raise SnapshotStorageIntegrityError(
                "R2 object URI has a substituted bucket or noncanonical components."
            )
        key = parsed.path.removeprefix("/")
        address = self._address_from_key_for_digest(key, expected)
        if uri != address.uri:
            raise SnapshotStorageIntegrityError("R2 object URI is not canonical.")
        return address

    @staticmethod
    def _digest_from_uri(uri: str) -> str:
        if not isinstance(uri, str):
            raise SnapshotStorageIntegrityError("R2 object URI must be canonical text.")
        try:
            parsed = urlsplit(uri)
            _ = parsed.port
        except (ValueError, UnicodeError) as exc:
            raise SnapshotStorageIntegrityError("R2 object URI is malformed.") from exc
        return require_full_sha256(parsed.path.rsplit("/", 1)[-1])

    def _address_from_key(
        self, key: str, *, object_kind: StorageObjectKind
    ) -> StorageObjectAddress:
        if not isinstance(key, str):
            raise SnapshotStorageProtocolError("R2 object key must be text.")
        final_component = key.rsplit("/", 1)[-1]
        address = self._address_from_key_for_digest(key, final_component)
        if address.object_kind is not object_kind:
            raise SnapshotStorageProtocolError(
                "R2 list returned an object outside the requested canonical kind scope."
            )
        return address

    def _address_from_key_for_digest(
        self, key: str, expected_sha256: str
    ) -> StorageObjectAddress:
        expected = require_full_sha256(expected_sha256)
        candidates = (
            self.address_for_content_hash(expected, object_kind=StorageObjectKind.SNAPSHOT),
            self.address_for_content_hash(expected, object_kind=StorageObjectKind.ARTIFACT),
        )
        for candidate in candidates:
            if candidate.key == key:
                return candidate
        raise SnapshotStorageIntegrityError(
            "R2 object key is not a canonical full-SHA-256 storage key."
        )

    @staticmethod
    def _normalize_metadata(value: object) -> dict[str, str]:
        if not isinstance(value, Mapping):
            raise SnapshotStorageMetadataError("R2 object metadata is missing or malformed.")
        normalized: dict[str, str] = {}
        for raw_key, raw_value in value.items():
            if not isinstance(raw_key, str) or not isinstance(raw_value, str):
                raise SnapshotStorageMetadataError("R2 object metadata must contain strings.")
            key = raw_key.lower()
            if key in normalized:
                raise SnapshotStorageMetadataError(
                    "R2 object metadata contains duplicate case-insensitive keys."
                )
            normalized[key] = raw_value
        return normalized

    @staticmethod
    def _validate_success_response(
        response: Mapping[str, object], *, operation: str
    ) -> None:
        """Reject contradictory SDK response envelopes even without an exception."""
        if response.get("Error") is not None:
            raise SnapshotStorageProtocolError(
                f"R2 {operation} returned an error envelope as a successful response."
            )
        response_metadata = response.get("ResponseMetadata")
        if response_metadata is None:
            # Minimal injected clients may omit SDK transport metadata. Full
            # byte/metadata verification remains mandatory for object reads.
            return
        if not isinstance(response_metadata, Mapping):
            raise SnapshotStorageProtocolError(
                f"R2 {operation} returned malformed response metadata."
            )
        status = response_metadata.get("HTTPStatusCode")
        if (
            not isinstance(status, int)
            or isinstance(status, bool)
            or not 200 <= status < 300
        ):
            raise SnapshotStorageProtocolError(
                f"R2 {operation} returned a non-success response envelope."
            )

    @staticmethod
    def _read_body(value: object) -> bytes:
        if isinstance(value, bytes):
            return value
        read = getattr(value, "read", None)
        if not callable(read):
            raise SnapshotStorageProtocolError("R2 object body is not readable bytes.")
        close = getattr(value, "close", None)
        try:
            raw_bytes = read()
        finally:
            if callable(close):
                try:
                    close()
                except Exception as exc:
                    raise SnapshotStorageProtocolError(
                        "R2 object body could not be closed after read-back."
                    ) from exc
        if not isinstance(raw_bytes, bytes):
            raise SnapshotStorageProtocolError("R2 object body reader did not return bytes.")
        return raw_bytes

    @classmethod
    def _is_precondition_failed(cls, exc: Exception) -> bool:
        status, code = cls._provider_error(exc)
        return status == 412 and code in {None, "PreconditionFailed", "412"}

    @classmethod
    def _is_missing(cls, exc: Exception) -> bool:
        status, code = cls._provider_error(exc)
        return status == 404 and code in {None, "NoSuchKey", "NotFound", "404"}

    @staticmethod
    def _provider_error(exc: Exception) -> tuple[int | None, str | None]:
        response = getattr(exc, "response", None)
        if not isinstance(response, Mapping):
            return None, None
        metadata = response.get("ResponseMetadata")
        error = response.get("Error")
        status = metadata.get("HTTPStatusCode") if isinstance(metadata, Mapping) else None
        code = error.get("Code") if isinstance(error, Mapping) else None
        return (
            status if isinstance(status, int) and not isinstance(status, bool) else None,
            code if isinstance(code, str) else None,
        )
