"""Provider-neutral contracts for immutable snapshot and artifact bytes.

The runner-facing protocol is deliberately smaller than an object-store SDK.
It can create a content-addressed object, perform verified reads, and inventory
orphans.  It cannot overwrite or delete objects and cannot configure provider
retention, lifecycle, credentials, buckets, or access policy.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import MISSING, dataclass, field, fields
from enum import Enum
from typing import Iterable, Mapping, Protocol, runtime_checkable


_SHA256_HEX = re.compile(r"[0-9a-f]{64}")
_PROVIDER_ID = re.compile(r"[a-z][a-z0-9_-]*")


class SnapshotStorageError(RuntimeError):
    """Base class for immutable object-storage failures."""


class SnapshotStorageIntegrityError(SnapshotStorageError):
    """Persisted bytes cannot prove the full SHA-256 identity recorded for them."""


class SnapshotStorageCollisionError(SnapshotStorageIntegrityError):
    """A content-addressed target exists with bytes for a different digest."""


class SnapshotStorageMissingError(SnapshotStorageIntegrityError):
    """An immutable object required by a receipt is missing."""


class SnapshotStorageMetadataError(SnapshotStorageIntegrityError):
    """Object metadata conflicts with its canonical content identity."""


class SnapshotStorageProtocolError(SnapshotStorageError):
    """The injected provider client returned an invalid or unsafe response."""


class SnapshotStorageUnavailableError(SnapshotStorageError):
    """The injected provider client could not complete an operation."""


class StorageObjectKind(str, Enum):
    SNAPSHOT = "snapshot"
    ARTIFACT = "artifact"


def compute_content_hash(raw_bytes: bytes) -> str:
    if not isinstance(raw_bytes, bytes):
        raise TypeError("Immutable object content must be bytes.")
    return hashlib.sha256(raw_bytes).hexdigest()


def require_full_sha256(content_sha256: str) -> str:
    if not isinstance(content_sha256, str) or not _SHA256_HEX.fullmatch(content_sha256):
        raise SnapshotStorageIntegrityError(
            "Object content hash must be a full lowercase SHA-256 digest."
        )
    return content_sha256


def canonical_metadata_sha256(metadata: Mapping[str, str]) -> str:
    if not isinstance(metadata, Mapping):
        raise SnapshotStorageMetadataError("Object metadata must be a string mapping.")
    canonical: dict[str, str] = {}
    for key, value in metadata.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise SnapshotStorageMetadataError("Object metadata keys and values must be strings.")
        canonical[key] = value
    raw = json.dumps(
        canonical,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")
    return hashlib.sha256(raw).hexdigest()


def _receipt_id(receipt_type: str, payload: Mapping[str, object]) -> str:
    raw = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")
    return f"{receipt_type}:{hashlib.sha256(raw).hexdigest()}"


def _construct_validated(cls, **values):
    """Construct one frozen, non-public-init receipt and run its invariants."""
    instance = object.__new__(cls)
    remaining = dict(values)
    for definition in fields(cls):
        if definition.name in remaining:
            value = remaining.pop(definition.name)
        elif definition.default is not MISSING:
            value = definition.default
        elif definition.default_factory is not MISSING:
            value = definition.default_factory()
        else:
            raise TypeError(f"Missing required receipt field: {definition.name}")
        object.__setattr__(instance, definition.name, value)
    if remaining:
        raise TypeError(f"Unknown receipt fields: {sorted(remaining)}")
    instance.__post_init__()
    return instance


def _require_nonnegative_integer(value: object, *, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise SnapshotStorageProtocolError(f"{label} must be a nonnegative integer.")
    return value


@dataclass(frozen=True, slots=True)
class StorageObjectAddress:
    provider: str
    object_kind: StorageObjectKind
    uri: str
    key: str
    content_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.provider, str) or not _PROVIDER_ID.fullmatch(self.provider):
            raise SnapshotStorageProtocolError("Storage provider identifier is not canonical.")
        if (
            not isinstance(self.object_kind, StorageObjectKind)
            or not isinstance(self.uri, str)
            or not self.uri
            or any(character.isspace() or ord(character) < 32 for character in self.uri)
        ):
            raise SnapshotStorageProtocolError("Storage object URI is required.")
        if not isinstance(self.key, str) or not self.key or self.key.startswith("/"):
            raise SnapshotStorageProtocolError("Storage object key is not canonical.")
        key_parts = self.key.split("/")
        if (
            any(part in {"", ".", ".."} for part in key_parts)
            or "\\" in self.key
            or any(character.isspace() or ord(character) < 32 for character in self.key)
        ):
            raise SnapshotStorageProtocolError("Storage object key is not canonical.")
        require_full_sha256(self.content_sha256)


def _address_payload(address: StorageObjectAddress) -> dict[str, object]:
    return {
        "provider": address.provider,
        "objectKind": address.object_kind.value,
        "uri": address.uri,
        "key": address.key,
        "contentSha256": address.content_sha256,
    }


@dataclass(frozen=True, slots=True, init=False)
class StorageVerificationReceipt:
    receipt_id: str
    address: StorageObjectAddress
    expected_sha256: str
    observed_sha256: str
    byte_length: int
    metadata_sha256: str
    status: str = "verified"
    proof: str = "full_byte_sha256_read_back"

    def __post_init__(self) -> None:
        if not isinstance(self.address, StorageObjectAddress):
            raise SnapshotStorageProtocolError("Verification address is not canonical.")
        expected = require_full_sha256(self.expected_sha256)
        observed = require_full_sha256(self.observed_sha256)
        metadata_digest = require_full_sha256(self.metadata_sha256)
        if expected != self.address.content_sha256 or observed != expected:
            raise SnapshotStorageIntegrityError(
                "Verification receipt digests must match the canonical object identity."
            )
        _require_nonnegative_integer(self.byte_length, label="Verified object byte length")
        if self.status != "verified" or self.proof != "full_byte_sha256_read_back":
            raise SnapshotStorageProtocolError("Verification receipt status or proof is not canonical.")
        payload = {
            "schemaVersion": "storage-verification-receipt-v1",
            "address": _address_payload(self.address),
            "expectedSha256": expected,
            "observedSha256": observed,
            "byteLength": self.byte_length,
            "metadataSha256": metadata_digest,
            "status": self.status,
            "proof": self.proof,
        }
        if self.receipt_id != _receipt_id("storage-verification-v1", payload):
            raise SnapshotStorageIntegrityError(
                "Verification receipt identifier is not bound to its canonical payload."
            )

    @classmethod
    def create(
        cls,
        *,
        address: StorageObjectAddress,
        expected_sha256: str,
        observed_sha256: str,
        byte_length: int,
        metadata: Mapping[str, str],
    ) -> StorageVerificationReceipt:
        expected = require_full_sha256(expected_sha256)
        observed = require_full_sha256(observed_sha256)
        if expected != address.content_sha256 or observed != expected:
            raise SnapshotStorageIntegrityError(
                "Verification receipt digests must match the canonical object identity."
            )
        if not isinstance(byte_length, int) or isinstance(byte_length, bool) or byte_length < 0:
            raise SnapshotStorageProtocolError("Verified object byte length must be nonnegative.")
        metadata_digest = canonical_metadata_sha256(metadata)
        payload = {
            "schemaVersion": "storage-verification-receipt-v1",
            "address": _address_payload(address),
            "expectedSha256": expected,
            "observedSha256": observed,
            "byteLength": byte_length,
            "metadataSha256": metadata_digest,
            "status": "verified",
            "proof": "full_byte_sha256_read_back",
        }
        return _construct_validated(
            cls,
            receipt_id=_receipt_id("storage-verification-v1", payload),
            address=address,
            expected_sha256=expected,
            observed_sha256=observed,
            byte_length=byte_length,
            metadata_sha256=metadata_digest,
        )


@dataclass(frozen=True, slots=True, init=False)
class StorageReadReceipt:
    receipt_id: str
    verification_receipt_id: str
    address: StorageObjectAddress
    byte_length: int

    def __post_init__(self) -> None:
        if not isinstance(self.address, StorageObjectAddress):
            raise SnapshotStorageProtocolError("Read receipt address is not canonical.")
        _require_nonnegative_integer(self.byte_length, label="Read object byte length")
        if not isinstance(self.verification_receipt_id, str) or not re.fullmatch(
            r"storage-verification-v1:[0-9a-f]{64}", self.verification_receipt_id
        ):
            raise SnapshotStorageIntegrityError(
                "Read receipt verification identifier is not canonical."
            )
        payload = {
            "schemaVersion": "storage-read-receipt-v1",
            "verificationReceiptId": self.verification_receipt_id,
            "contentSha256": self.address.content_sha256,
            "byteLength": self.byte_length,
        }
        if self.receipt_id != _receipt_id("storage-read-v1", payload):
            raise SnapshotStorageIntegrityError(
                "Read receipt identifier is not bound to its canonical payload."
            )

    @classmethod
    def create(cls, *, verification: StorageVerificationReceipt) -> StorageReadReceipt:
        if not isinstance(verification, StorageVerificationReceipt):
            raise SnapshotStorageProtocolError(
                "Read receipt requires a canonical verification receipt instance."
            )
        payload = {
            "schemaVersion": "storage-read-receipt-v1",
            "verificationReceiptId": verification.receipt_id,
            "contentSha256": verification.observed_sha256,
            "byteLength": verification.byte_length,
        }
        return _construct_validated(
            cls,
            receipt_id=_receipt_id("storage-read-v1", payload),
            verification_receipt_id=verification.receipt_id,
            address=verification.address,
            byte_length=verification.byte_length,
        )


@dataclass(frozen=True, slots=True, init=False)
class StorageReadResult:
    """Verified bytes plus a receipt that never embeds or renders those bytes."""

    raw_bytes: bytes = field(repr=False)
    receipt: StorageReadReceipt
    verification: StorageVerificationReceipt

    def __post_init__(self) -> None:
        if not isinstance(self.raw_bytes, bytes):
            raise SnapshotStorageProtocolError("Verified object body must be bytes.")
        if not isinstance(self.verification, StorageVerificationReceipt):
            raise SnapshotStorageProtocolError("Verified read is missing a canonical verification receipt.")
        if not isinstance(self.receipt, StorageReadReceipt):
            raise SnapshotStorageProtocolError("Verified read is missing a canonical read receipt.")
        if len(self.raw_bytes) != self.verification.byte_length:
            raise SnapshotStorageIntegrityError(
                "Verified read length does not match its verification receipt."
            )
        if compute_content_hash(self.raw_bytes) != self.verification.observed_sha256:
            raise SnapshotStorageIntegrityError(
                "Verified read bytes do not match their verification receipt digest."
            )
        if self.receipt != StorageReadReceipt.create(verification=self.verification):
            raise SnapshotStorageIntegrityError(
                "Verified read receipt is not bound to its verification receipt."
            )

    @classmethod
    def create(
        cls, *, raw_bytes: bytes, verification: StorageVerificationReceipt
    ) -> StorageReadResult:
        if not isinstance(raw_bytes, bytes):
            raise SnapshotStorageProtocolError("Verified object body must be bytes.")
        if len(raw_bytes) != verification.byte_length:
            raise SnapshotStorageIntegrityError(
                "Verified read length does not match its verification receipt."
            )
        if compute_content_hash(raw_bytes) != verification.observed_sha256:
            raise SnapshotStorageIntegrityError(
                "Verified read bytes do not match their verification receipt digest."
            )
        return _construct_validated(
            cls,
            raw_bytes=raw_bytes,
            receipt=StorageReadReceipt.create(verification=verification),
            verification=verification,
        )

    @property
    def receipt_id(self) -> str:
        return self.receipt.receipt_id


@dataclass(frozen=True, slots=True, init=False)
class StorageStoreReceipt:
    receipt_id: str
    outcome: str
    address: StorageObjectAddress
    byte_length: int
    write_precondition: str
    verification_receipt_id: str
    provider_retention_evidence: str = "external_evidence_required"

    def __post_init__(self) -> None:
        if self.outcome not in {"created", "reused"}:
            raise SnapshotStorageProtocolError("Store outcome must be created or reused.")
        if not isinstance(self.address, StorageObjectAddress):
            raise SnapshotStorageProtocolError("Store receipt address is not canonical.")
        _require_nonnegative_integer(self.byte_length, label="Stored object byte length")
        if self.write_precondition not in {"atomic_no_replace", "if_none_match_wildcard"}:
            raise SnapshotStorageProtocolError("Unsupported immutable write precondition.")
        if not isinstance(self.verification_receipt_id, str) or not re.fullmatch(
            r"storage-verification-v1:[0-9a-f]{64}", self.verification_receipt_id
        ):
            raise SnapshotStorageIntegrityError(
                "Store receipt verification identifier is not canonical."
            )
        if self.provider_retention_evidence != "external_evidence_required":
            raise SnapshotStorageProtocolError(
                "Provider retention evidence cannot be inferred by the application adapter."
            )
        payload = {
            "schemaVersion": "storage-store-receipt-v1",
            "outcome": self.outcome,
            "address": _address_payload(self.address),
            "byteLength": self.byte_length,
            "writePrecondition": self.write_precondition,
            "verificationReceiptId": self.verification_receipt_id,
            "providerRetentionEvidence": self.provider_retention_evidence,
        }
        if self.receipt_id != _receipt_id("storage-store-v1", payload):
            raise SnapshotStorageIntegrityError(
                "Store receipt identifier is not bound to its canonical payload."
            )

    @classmethod
    def create(
        cls,
        *,
        outcome: str,
        verification: StorageVerificationReceipt,
        write_precondition: str,
    ) -> StorageStoreReceipt:
        if not isinstance(verification, StorageVerificationReceipt):
            raise SnapshotStorageProtocolError(
                "Store receipt requires a canonical verification receipt instance."
            )
        if outcome not in {"created", "reused"}:
            raise SnapshotStorageProtocolError("Store outcome must be created or reused.")
        if write_precondition not in {"atomic_no_replace", "if_none_match_wildcard"}:
            raise SnapshotStorageProtocolError("Unsupported immutable write precondition.")
        payload = {
            "schemaVersion": "storage-store-receipt-v1",
            "outcome": outcome,
            "address": _address_payload(verification.address),
            "byteLength": verification.byte_length,
            "writePrecondition": write_precondition,
            "verificationReceiptId": verification.receipt_id,
            "providerRetentionEvidence": "external_evidence_required",
        }
        return _construct_validated(
            cls,
            receipt_id=_receipt_id("storage-store-v1", payload),
            outcome=outcome,
            address=verification.address,
            byte_length=verification.byte_length,
            write_precondition=write_precondition,
            verification_receipt_id=verification.receipt_id,
        )


@dataclass(frozen=True, slots=True, init=False)
class OrphanInventoryReceipt:
    receipt_id: str
    provider: str
    object_kind: StorageObjectKind
    scope: str
    pages_scanned: int
    listed_count: int
    referenced_count: int
    referenced_present: tuple[StorageObjectAddress, ...]
    orphan_objects: tuple[StorageObjectAddress, ...]
    missing_references: tuple[StorageObjectAddress, ...]
    content_verification: str = "not_performed_inventory_only"

    def __post_init__(self) -> None:
        if not isinstance(self.provider, str) or not _PROVIDER_ID.fullmatch(self.provider):
            raise SnapshotStorageProtocolError("Inventory provider is not canonical.")
        if not isinstance(self.object_kind, StorageObjectKind):
            raise SnapshotStorageProtocolError(
                "Inventory object kind must be a StorageObjectKind value."
            )
        if (
            not isinstance(self.scope, str)
            or not self.scope
            or any(character.isspace() or ord(character) < 32 for character in self.scope)
        ):
            raise SnapshotStorageProtocolError("Inventory provider and scope are required.")
        for label, value in (
            ("Inventory pages scanned", self.pages_scanned),
            ("Inventory listed count", self.listed_count),
            ("Inventory referenced count", self.referenced_count),
        ):
            _require_nonnegative_integer(value, label=label)
        groups = (
            self.referenced_present,
            self.orphan_objects,
            self.missing_references,
        )
        if any(not isinstance(group, tuple) for group in groups):
            raise SnapshotStorageProtocolError("Inventory address groups must be canonical tuples.")
        combined = (*self.referenced_present, *self.orphan_objects, *self.missing_references)
        if any(not isinstance(item, StorageObjectAddress) for item in combined):
            raise SnapshotStorageProtocolError("Inventory contains a noncanonical address.")
        if any(item.provider != self.provider for item in combined):
            raise SnapshotStorageProtocolError("Inventory address provider does not match its scope.")
        if any(item.object_kind is not self.object_kind for item in combined):
            raise SnapshotStorageProtocolError("Inventory address kind does not match its scope.")
        if any(tuple(sorted(group, key=lambda item: item.key)) != group for group in groups):
            raise SnapshotStorageProtocolError("Inventory address groups must use canonical key order.")
        if len({item.key for item in combined}) != len(combined):
            raise SnapshotStorageProtocolError("Inventory contains a duplicate or substituted key.")
        if len({item.uri for item in combined}) != len(combined):
            raise SnapshotStorageProtocolError("Inventory contains a duplicate or substituted URI.")
        if self.listed_count != len(self.referenced_present) + len(self.orphan_objects) or (
            self.referenced_count
            != len(self.referenced_present) + len(self.missing_references)
        ):
            raise SnapshotStorageProtocolError(
                "Inventory denominators do not exactly reconcile listed, referenced, orphan, and missing sets."
            )
        if self.content_verification != "not_performed_inventory_only":
            raise SnapshotStorageProtocolError("Inventory cannot claim content verification.")
        payload = {
            "schemaVersion": "storage-orphan-inventory-receipt-v1",
            "provider": self.provider,
            "objectKind": self.object_kind.value,
            "scope": self.scope,
            "pagesScanned": self.pages_scanned,
            "listedCount": self.listed_count,
            "referencedCount": self.referenced_count,
            "referencedPresent": [_address_payload(item) for item in self.referenced_present],
            "orphanObjects": [_address_payload(item) for item in self.orphan_objects],
            "missingReferences": [_address_payload(item) for item in self.missing_references],
            "contentVerification": self.content_verification,
        }
        if self.receipt_id != _receipt_id("storage-orphan-inventory-v1", payload):
            raise SnapshotStorageIntegrityError(
                "Inventory receipt identifier is not bound to its canonical payload."
            )

    @classmethod
    def create(
        cls,
        *,
        provider: str,
        object_kind: StorageObjectKind,
        scope: str,
        pages_scanned: int,
        listed_count: int,
        referenced_count: int,
        referenced_present: Iterable[StorageObjectAddress],
        orphan_objects: Iterable[StorageObjectAddress],
        missing_references: Iterable[StorageObjectAddress],
    ) -> OrphanInventoryReceipt:
        if not isinstance(provider, str) or not _PROVIDER_ID.fullmatch(provider):
            raise SnapshotStorageProtocolError("Inventory provider is not canonical.")
        if not isinstance(object_kind, StorageObjectKind):
            raise SnapshotStorageProtocolError(
                "Inventory object kind must be a StorageObjectKind value."
            )
        if (
            not isinstance(scope, str)
            or not scope
            or any(character.isspace() or ord(character) < 32 for character in scope)
        ):
            raise SnapshotStorageProtocolError("Inventory provider and scope are required.")
        counts = (pages_scanned, listed_count, referenced_count)
        if any(not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in counts):
            raise SnapshotStorageProtocolError("Inventory counts must be nonnegative integers.")
        present = tuple(sorted(referenced_present, key=lambda item: item.key))
        orphans = tuple(sorted(orphan_objects, key=lambda item: item.key))
        missing = tuple(sorted(missing_references, key=lambda item: item.key))
        combined = (*present, *orphans, *missing)
        if any(item.provider != provider for item in combined):
            raise SnapshotStorageProtocolError("Inventory address provider does not match its scope.")
        if any(item.object_kind is not object_kind for item in combined):
            raise SnapshotStorageProtocolError("Inventory address kind does not match its scope.")
        if len({item.key for item in combined}) != len(combined):
            raise SnapshotStorageProtocolError("Inventory contains a duplicate or substituted key.")
        if len({item.uri for item in combined}) != len(combined):
            raise SnapshotStorageProtocolError("Inventory contains a duplicate or substituted URI.")
        if listed_count != len(present) + len(orphans) or referenced_count != len(present) + len(
            missing
        ):
            raise SnapshotStorageProtocolError(
                "Inventory denominators do not exactly reconcile listed, referenced, orphan, and missing sets."
            )
        payload = {
            "schemaVersion": "storage-orphan-inventory-receipt-v1",
            "provider": provider,
            "objectKind": object_kind.value,
            "scope": scope,
            "pagesScanned": pages_scanned,
            "listedCount": listed_count,
            "referencedCount": referenced_count,
            "referencedPresent": [_address_payload(item) for item in present],
            "orphanObjects": [_address_payload(item) for item in orphans],
            "missingReferences": [_address_payload(item) for item in missing],
            "contentVerification": "not_performed_inventory_only",
        }
        return _construct_validated(
            cls,
            receipt_id=_receipt_id("storage-orphan-inventory-v1", payload),
            provider=provider,
            object_kind=object_kind,
            scope=scope,
            pages_scanned=pages_scanned,
            listed_count=listed_count,
            referenced_count=referenced_count,
            referenced_present=present,
            orphan_objects=orphans,
            missing_references=missing,
        )


@dataclass(frozen=True, slots=True)
class StorageSecurityPosture:
    runner_capability: str
    provider_retention_evidence: str
    application_integrity_proof: str
    exposes_admin_controls: bool
    exposes_delete: bool

    @classmethod
    def application_only(cls) -> StorageSecurityPosture:
        return cls(
            runner_capability="object_read_write_list_only",
            provider_retention_evidence="external_evidence_required",
            application_integrity_proof="full_byte_sha256_read_back",
            exposes_admin_controls=False,
            exposes_delete=False,
        )


@runtime_checkable
class SnapshotStorageRunner(Protocol):
    """Delete/admin-free immutable object operations available to a runner."""

    def store_snapshot(
        self,
        *,
        raw_bytes: bytes,
        object_kind: StorageObjectKind = StorageObjectKind.SNAPSHOT,
    ) -> StorageStoreReceipt: ...

    def read_snapshot(
        self, *, uri: str, content_sha256: str
    ) -> StorageReadResult: ...

    def verify_snapshot(
        self, *, uri: str, content_sha256: str
    ) -> StorageVerificationReceipt: ...

    def inventory_orphans(
        self,
        *,
        referenced_uris: Iterable[str],
        object_kind: StorageObjectKind = StorageObjectKind.SNAPSHOT,
    ) -> OrphanInventoryReceipt: ...


@runtime_checkable
class SnapshotRetentionAdmin(Protocol):
    """Separate administrative authority; never accepted by the runner path."""

    def configure_retention(self, *, prefix: str, policy: Mapping[str, object]) -> object: ...

    def delete_expired(self, *, prefix: str, authorization_receipt_id: str) -> object: ...
