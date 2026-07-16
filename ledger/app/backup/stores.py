"""Delete/admin-free storage bindings used by recovery copy mechanics."""

from __future__ import annotations

import re
import inspect
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from app.storage.base import (
    OrphanInventoryReceipt,
    SnapshotStorageRunner,
    StorageObjectKind,
    StorageReadResult,
    StorageSecurityPosture,
    StorageStoreReceipt,
    StorageVerificationReceipt,
)
from app.storage.local import LocalSnapshotStorage

from .errors import RecoveryTargetError


_DOMAIN_ID = re.compile(r"[a-z0-9][a-z0-9._-]{0,127}")
_FORBIDDEN_CAPABILITIES = frozenset(
    {
        "admin",
        "admin_client",
        "client",
        "client_handle",
        "configure_retention",
        "delete",
        "delete_expired",
        "delete_object",
        "delete_snapshot",
        "overwrite",
        "overwrite_snapshot",
        "provider_admin",
        "provider_client",
        "put_retention_policy",
        "retention_admin",
        "set_bucket_policy",
        "set_lifecycle",
    }
)
_RUNNER_METHODS = (
    "store_snapshot",
    "read_snapshot",
    "verify_snapshot",
    "inventory_orphans",
)
_MISSING = object()


@dataclass(frozen=True, slots=True)
class RecoveryDomain:
    """One declared storage domain with application-only immutable operations.

    A distinct identifier is a routing assertion, not proof of infrastructure
    independence.  That proof remains ``external_evidence_required`` even for
    different local roots or differently configured injected clients.
    """

    failure_domain_id: str
    store: SnapshotStorageRunner
    independence_evidence: str = "external_evidence_required"

    def __post_init__(self) -> None:
        if (
            type(self.failure_domain_id) is not str
            or _DOMAIN_ID.fullmatch(self.failure_domain_id) is None
        ):
            raise RecoveryTargetError("Failure-domain ID is not canonical.")
        if self.independence_evidence != "external_evidence_required":
            raise RecoveryTargetError(
                "Application code cannot assert provider failure-domain independence."
            )
        store_type = type(self.store)
        # Static inspection is intentional: an injected property must neither
        # hide a capability nor execute merely because the store is admitted.
        invalid_methods: list[str] = []
        for name in _RUNNER_METHODS:
            member = inspect.getattr_static(store_type, name, _MISSING)
            if member is _MISSING:
                member = inspect.getattr_static(self.store, name, _MISSING)
            if isinstance(member, (staticmethod, classmethod)):
                member = member.__func__
            if member is _MISSING or isinstance(member, property) or not callable(member):
                invalid_methods.append(name)
        if invalid_methods:
            raise RecoveryTargetError(
                "Recovery store lacks callable immutable runner methods: "
                + ", ".join(invalid_methods)
            )
        exposed = sorted(
            name
            for name in _FORBIDDEN_CAPABILITIES
            if inspect.getattr_static(store_type, name, _MISSING) is not _MISSING
            or inspect.getattr_static(self.store, name, _MISSING) is not _MISSING
        )
        if exposed:
            raise RecoveryTargetError(
                "Recovery store exposes forbidden delete/admin capability: "
                + ", ".join(exposed)
            )
        posture = inspect.getattr_static(store_type, "security_posture", _MISSING)
        if type(posture) is not StorageSecurityPosture or posture != StorageSecurityPosture.application_only():
            raise RecoveryTargetError(
                "Recovery store must declare the canonical application-only posture."
            )


class LocalRecoveryStore:
    """Local content-addressed mechanics with no independence claim.

    Separate roots are useful for deterministic tests and operator rehearsal.
    They are not evidence that two provider/account/control-plane failure
    domains are independent.
    """

    independence_evidence = "external_evidence_required"
    security_posture = StorageSecurityPosture.application_only()

    def __init__(self, root: Path, *, failure_domain_id: str) -> None:
        if type(failure_domain_id) is not str or _DOMAIN_ID.fullmatch(failure_domain_id) is None:
            raise RecoveryTargetError("Failure-domain ID is not canonical.")
        self.failure_domain_id = failure_domain_id
        # Admission and containment checks must not create a caller-supplied
        # directory.  The local fixture is materialized only by the first
        # authorized storage operation after domains have been reconciled.
        self.root = Path(root).expanduser().resolve(strict=False)
        self._storage_instance: LocalSnapshotStorage | None = None

    def _storage(self) -> LocalSnapshotStorage:
        storage = self._storage_instance
        if storage is None:
            storage = LocalSnapshotStorage(self.root)
            self._storage_instance = storage
        return storage

    def store_snapshot(
        self,
        *,
        raw_bytes: bytes,
        object_kind: StorageObjectKind = StorageObjectKind.SNAPSHOT,
    ) -> StorageStoreReceipt:
        return self._storage().store_snapshot(raw_bytes=raw_bytes, object_kind=object_kind)

    def read_snapshot(self, *, uri: str, content_sha256: str) -> StorageReadResult:
        return self._storage().read_snapshot(uri=uri, content_sha256=content_sha256)

    def verify_snapshot(
        self, *, uri: str, content_sha256: str
    ) -> StorageVerificationReceipt:
        return self._storage().verify_snapshot(uri=uri, content_sha256=content_sha256)

    def inventory_orphans(
        self,
        *,
        referenced_uris: Iterable[str],
        object_kind: StorageObjectKind = StorageObjectKind.SNAPSHOT,
    ) -> OrphanInventoryReceipt:
        return self._storage().inventory_orphans(
            referenced_uris=referenced_uris,
            object_kind=object_kind,
        )


def coerce_recovery_domain(value: RecoveryDomain | LocalRecoveryStore) -> RecoveryDomain:
    if isinstance(value, RecoveryDomain):
        return value
    if isinstance(value, LocalRecoveryStore):
        return RecoveryDomain(
            failure_domain_id=value.failure_domain_id,
            store=value,
            independence_evidence=value.independence_evidence,
        )
    raise RecoveryTargetError("Recovery domain binding is not supported.")


def require_distinct_domains(
    left: RecoveryDomain | LocalRecoveryStore,
    right: RecoveryDomain | LocalRecoveryStore,
) -> tuple[RecoveryDomain, RecoveryDomain]:
    first = coerce_recovery_domain(left)
    second = coerce_recovery_domain(right)
    if first.failure_domain_id == second.failure_domain_id:
        raise RecoveryTargetError("Recovery copies require distinct failure-domain IDs.")
    if first.store is second.store:
        raise RecoveryTargetError("Recovery copies cannot reuse the same store instance.")
    first_root = inspect.getattr_static(first.store, "root", None)
    second_root = inspect.getattr_static(second.store, "root", None)
    if first_root is not None and second_root is not None:
        resolved_first = Path(first_root).resolve()
        resolved_second = Path(second_root).resolve()
        if (
            resolved_first == resolved_second
            or resolved_first in resolved_second.parents
            or resolved_second in resolved_first.parents
        ):
            raise RecoveryTargetError(
                "Distinct local recovery roots cannot overlap or contain one another."
            )
    return first, second


__all__ = [
    "LocalRecoveryStore",
    "RecoveryDomain",
    "coerce_recovery_domain",
    "require_distinct_domains",
]
