"""Provider-neutral checkpoint/copy/restore orchestration with SQLite wrappers."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import inspect
from pathlib import Path
import re
from typing import Any, Callable, Mapping

from app.schemas.recovery_contracts import (
    RecoveryContractError,
    canonical_recovery_json,
    derive_checkpoint_id,
    derive_restore_receipt_id,
    recovery_contract_digest,
    recovery_cycle_set_digest,
    recovery_object_set_digest,
    parse_canonical_recovery_bytes,
    validate_checkpoint_manifest,
    validate_restore_receipt,
)
from app.storage.base import (
    OrphanInventoryReceipt,
    StorageObjectKind,
    StorageReadResult,
    StorageStoreReceipt,
    compute_content_hash,
)

from .errors import (
    RecoveryCancelled,
    RecoveryIntegrityError,
    RecoveryPartialFailure,
    RecoveryReplayConflict,
    RecoveryTargetError,
    UnsupportedRecoveryArtifact,
)
from .protocols import (
    ReferencedObject,
    RelationalBackupArtifact,
    RelationalBackupRestoreDriver,
    RelationalInspectionResult,
)
from .semantic_inspection import LINEAGE_TABLES, table_inventory_documents
from .sqlite_driver import (
    SQLiteBackupRestoreDriver,
    cycle_documents,
    cycle_watermarks,
    exact_trigger_payload,
)
from .stores import (
    LocalRecoveryStore,
    RecoveryDomain,
    require_distinct_domains,
)


_STABLE_ID = re.compile(r"[a-z0-9][a-z0-9._-]{0,127}")


def _authority() -> dict[str, Any]:
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


def _check_cancelled(
    cancel_requested: Callable[[], bool] | None,
    *,
    phase: str,
    completed_object_count: int = 0,
    target_created: bool = False,
) -> None:
    if cancel_requested is not None and cancel_requested():
        raise RecoveryCancelled(
            phase=phase,
            completed_object_count=completed_object_count,
            relational_target_created=target_created,
        )


def _redacted_partial_failure(
    reason_code: str,
    *,
    phase: str,
    completed_object_count: int = 0,
    target_created: bool = False,
) -> RecoveryPartialFailure:
    return RecoveryPartialFailure(
        reason_code,
        phase=phase,
        completed_object_count=completed_object_count,
        relational_target_created=target_created,
    )


def _verified_read(
    domain: RecoveryDomain,
    *,
    uri: str,
    content_sha256: str,
    expected_kind: StorageObjectKind,
    phase: str = "immutable_readback",
    target_created: bool = False,
) -> StorageReadResult:
    try:
        result = domain.store.read_snapshot(uri=uri, content_sha256=content_sha256)
    except Exception:
        # Provider/client exceptions are untrusted and may contain credentials,
        # signed URLs, or raw DSNs.  Never retain their text or cause chain.
        raise _redacted_partial_failure(
            "RECOVERY_STORE_READ_FAILED",
            phase=phase,
            target_created=target_created,
        ) from None
    if not isinstance(result, StorageReadResult):
        raise RecoveryIntegrityError("Injected store returned an untyped read result.")
    address = result.verification.address
    if (
        address.uri != uri
        or address.content_sha256 != content_sha256
        or address.object_kind is not expected_kind
        or result.verification.observed_sha256 != content_sha256
        or len(result.raw_bytes) != result.verification.byte_length
        or compute_content_hash(result.raw_bytes) != content_sha256
    ):
        raise RecoveryIntegrityError("Injected store read substituted an address, digest, kind, or size.")
    return result


def _copy_bytes(
    domain: RecoveryDomain,
    *,
    raw_bytes: bytes,
    object_kind: StorageObjectKind,
) -> dict[str, Any]:
    expected_sha = compute_content_hash(raw_bytes)
    try:
        receipt = domain.store.store_snapshot(
            raw_bytes=raw_bytes,
            object_kind=object_kind,
        )
    except Exception:
        raise _redacted_partial_failure(
            "RECOVERY_STORE_WRITE_FAILED",
            phase="immutable_conditional_copy",
        ) from None
    if not isinstance(receipt, StorageStoreReceipt):
        raise RecoveryIntegrityError("Injected store returned an untyped store receipt.")
    if (
        receipt.address.content_sha256 != expected_sha
        or receipt.address.object_kind is not object_kind
        or receipt.byte_length != len(raw_bytes)
        or receipt.provider_retention_evidence != "external_evidence_required"
        or receipt.write_precondition not in {"atomic_no_replace", "if_none_match_wildcard"}
    ):
        raise RecoveryIntegrityError("Immutable store receipt conflicts with copied bytes.")
    read_back = _verified_read(
        domain,
        uri=receipt.address.uri,
        content_sha256=expected_sha,
        expected_kind=object_kind,
    )
    if receipt.verification_receipt_id != read_back.verification.receipt_id:
        raise RecoveryIntegrityError("Store receipt does not bind the independent read-back proof.")
    return {
        "failureDomainId": domain.failure_domain_id,
        "provider": receipt.address.provider,
        "objectKind": object_kind.value,
        "uri": receipt.address.uri,
        "key": receipt.address.key,
        "contentSha256": expected_sha,
        "byteLength": len(raw_bytes),
        "writePrecondition": receipt.write_precondition,
        "verificationReceiptId": read_back.verification.receipt_id,
    }


def _verified_manifest_copy(
    domain: RecoveryDomain,
    copy: Mapping[str, Any],
    *,
    expected_kind: StorageObjectKind,
    expected_sha256: str,
    phase: str,
    target_created: bool = False,
) -> StorageReadResult:
    """Re-resolve every recorded address field and its verification receipt."""

    result = _verified_read(
        domain,
        uri=copy["uri"],
        content_sha256=expected_sha256,
        expected_kind=expected_kind,
        phase=phase,
        target_created=target_created,
    )
    address = result.verification.address
    expected = {
        "failureDomainId": domain.failure_domain_id,
        "provider": address.provider,
        "objectKind": address.object_kind.value,
        "uri": address.uri,
        "key": address.key,
        "contentSha256": address.content_sha256,
        "byteLength": result.verification.byte_length,
        "verificationReceiptId": result.verification.receipt_id,
    }
    for field, observed in expected.items():
        if copy.get(field) != observed:
            raise RecoveryIntegrityError(
                "Immutable recovery-copy metadata does not re-resolve from stored bytes."
            )
    return result


def _inventory(
    domain: RecoveryDomain,
    *,
    referenced_uris: tuple[str, ...],
    object_kind: StorageObjectKind,
    phase: str,
    target_created: bool = False,
) -> OrphanInventoryReceipt:
    try:
        receipt = domain.store.inventory_orphans(
            referenced_uris=referenced_uris,
            object_kind=object_kind,
        )
    except Exception:
        raise _redacted_partial_failure(
            "RECOVERY_STORE_INVENTORY_FAILED",
            phase=phase,
            target_created=target_created,
        ) from None
    if not isinstance(receipt, OrphanInventoryReceipt):
        raise RecoveryIntegrityError("Recovery store returned an untyped inventory receipt.")
    return receipt


def _require_fresh_target_store(domain: RecoveryDomain) -> None:
    root = _static_local_root(domain)
    if root is not None and root.exists():
        try:
            if root.is_symlink() or not root.is_dir() or any(root.iterdir()):
                raise RecoveryTargetError(
                    "Restore object target must be exactly fresh before relational restore."
                )
        except RecoveryTargetError:
            raise
        except OSError:
            raise _redacted_partial_failure(
                "RECOVERY_STORE_INVENTORY_FAILED",
                phase="restore_target_freshness",
            ) from None
    for kind in (StorageObjectKind.SNAPSHOT, StorageObjectKind.ARTIFACT):
        receipt = _inventory(
            domain,
            referenced_uris=(),
            object_kind=kind,
            phase="restore_target_freshness",
        )
        if (
            receipt.listed_count != 0
            or receipt.referenced_count != 0
            or receipt.referenced_present
            or receipt.orphan_objects
            or receipt.missing_references
        ):
            raise RecoveryTargetError(
                "Restore object target must be exactly fresh before relational restore."
            )


def _verify_exact_target_store(
    domain: RecoveryDomain,
    *,
    snapshot_uris: tuple[str, ...],
    target_created: bool,
) -> None:
    unique_snapshot_uris = tuple(sorted(set(snapshot_uris)))
    snapshots = _inventory(
        domain,
        referenced_uris=unique_snapshot_uris,
        object_kind=StorageObjectKind.SNAPSHOT,
        phase="restore_target_reconciliation",
        target_created=target_created,
    )
    artifacts = _inventory(
        domain,
        referenced_uris=(),
        object_kind=StorageObjectKind.ARTIFACT,
        phase="restore_target_reconciliation",
        target_created=target_created,
    )
    if (
        snapshots.listed_count != len(unique_snapshot_uris)
        or snapshots.referenced_count != len(unique_snapshot_uris)
        or len(snapshots.referenced_present) != len(unique_snapshot_uris)
        or snapshots.orphan_objects
        or snapshots.missing_references
        or artifacts.listed_count != 0
        or artifacts.referenced_count != 0
        or artifacts.referenced_present
        or artifacts.orphan_objects
        or artifacts.missing_references
    ):
        raise RecoveryIntegrityError(
            "Restore target contains missing, substituted, or unmanifested immutable bytes."
        )
    root = _static_local_root(domain)
    if root is not None:
        expected_paths = {
            Path(address.uri).resolve(strict=False)
            for address in snapshots.referenced_present
        }
        try:
            observed_paths: set[Path] = set()
            for path in root.rglob("*"):
                if path.is_symlink():
                    raise RecoveryIntegrityError(
                        "Restore target contains an unmanifested symbolic link."
                    )
                if path.is_file():
                    observed_paths.add(path.resolve(strict=False))
            if observed_paths != expected_paths:
                raise RecoveryIntegrityError(
                    "Restore target contains unmanifested local object bytes."
                )
        except RecoveryIntegrityError:
            raise
        except OSError:
            raise _redacted_partial_failure(
                "RECOVERY_STORE_INVENTORY_FAILED",
                phase="restore_target_reconciliation",
                target_created=target_created,
            ) from None


def _static_local_root(domain: RecoveryDomain) -> Path | None:
    value = inspect.getattr_static(domain.store, "root", None)
    return value if isinstance(value, Path) else None


def _paths_overlap(left: Path, right: Path) -> bool:
    resolved_left = left.expanduser().resolve(strict=False)
    resolved_right = right.expanduser().resolve(strict=False)
    return (
        resolved_left == resolved_right
        or resolved_left in resolved_right.parents
        or resolved_right in resolved_left.parents
    )


def _validate_restore_target_id(target_id: str) -> None:
    if type(target_id) is not str or _STABLE_ID.fullmatch(target_id) is None:
        raise RecoveryTargetError("Restore target ID is not canonical.")


def _validate_new_path_target(database_target: Path) -> Path:
    if not isinstance(database_target, Path):
        raise RecoveryTargetError("SQLite restore target must be a pathlib.Path.")
    candidate = database_target.expanduser()
    if candidate.exists() or candidate.is_symlink():
        raise RecoveryTargetError("SQLite restore target already exists.")
    return candidate.resolve(strict=False)


def _validate_explicit_restore_timing(
    *,
    started_at: str | None,
    finished_at: str | None,
) -> tuple[datetime, datetime] | None:
    if (started_at is None) != (finished_at is None):
        raise RecoveryTargetError(
            "Restore timing must supply both explicit timestamps or neither."
        )
    if started_at is None:
        return None
    try:
        started = datetime.strptime(started_at, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
        finished = datetime.strptime(finished_at, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except (TypeError, ValueError):
        raise RecoveryTargetError(
            "Restore timing must be canonical second-precision UTC."
        ) from None
    if finished < started:
        raise RecoveryTargetError("Restore finish cannot precede its start.")
    return started, finished


def _real_utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _canonical_utc_second(value: datetime) -> tuple[datetime, str]:
    normalized = value.astimezone(timezone.utc).replace(microsecond=0)
    return normalized, normalized.strftime("%Y-%m-%dT%H:%M:%SZ")


def _sample_trusted_utc_clock(
    utc_now: Callable[[], datetime],
    *,
    phase: str,
    target_created: bool,
) -> tuple[datetime, str]:
    try:
        observed = utc_now()
        if type(observed) is not datetime or observed.tzinfo is None:
            raise ValueError
        if observed.utcoffset() is None:
            raise ValueError
        return _canonical_utc_second(observed)
    except Exception:
        if target_created:
            raise _redacted_partial_failure(
                "RECOVERY_CLOCK_FAILED",
                phase=phase,
                target_created=True,
            ) from None
        raise RecoveryTargetError(
            "Trusted restore UTC clock failed before target mutation."
        ) from None




def _lineage_document(inspection: RelationalInspectionResult) -> dict[str, Any]:
    families = [
        {
            "family": item.family,
            "rootCount": item.root_count,
            "leafCount": item.leaf_count,
            "rowCount": item.row_count,
        }
        for item in inspection.integrity.lineage_families
    ]
    families.sort(key=lambda item: item["family"])
    if tuple(item["family"] for item in families) != LINEAGE_TABLES:
        raise RecoveryIntegrityError("Relational driver omitted a semantic lineage family.")
    return {
        "status": "passed",
        "familyCount": len(families),
        "rowCount": sum(item["rowCount"] for item in families),
        "families": families,
    }


def _integrity_document(inspection: RelationalInspectionResult) -> dict[str, Any]:
    if inspection.integrity.foreign_key_violation_count != 0:
        raise RecoveryIntegrityError("Relational inspection reported foreign-key violations.")
    if inspection.integrity.backend == "sqlite":
        if inspection.integrity.consistency_check != "ok":
            raise RecoveryIntegrityError("SQLite integrity status is not ok.")
        return {
            "sqliteIntegrityCheck": "ok",
            "foreignKeyViolationCount": 0,
            "semanticLineageAudit": _lineage_document(inspection),
        }
    if inspection.integrity.backend == "postgresql":
        if inspection.integrity.consistency_check != "passed":
            raise RecoveryIntegrityError("PostgreSQL consistency status is not passed.")
        return {
            "postgresqlConsistencyCheck": "passed",
            "foreignKeyViolationCount": 0,
            "semanticLineageAudit": _lineage_document(inspection),
        }
    raise UnsupportedRecoveryArtifact("Relational integrity backend is unsupported.")


def _schema_algorithm(artifact: RelationalBackupArtifact) -> str:
    if artifact.artifact_type == "sqlite_database":
        return "sha256-canonical-sqlite-schema-v1"
    if artifact.artifact_type == "postgresql_database":
        return "sha256-canonical-postgresql-schema-v1"
    raise UnsupportedRecoveryArtifact("Relational artifact type is unsupported.")


def _relational_base(inspection: RelationalInspectionResult) -> dict[str, Any]:
    artifact = inspection.artifact
    return {
        "artifactType": artifact.artifact_type,
        "driverId": artifact.driver_id,
        "driverVersion": artifact.driver_version,
        "engineName": artifact.engine_name,
        "engineVersion": artifact.engine_version,
        "inspectionEngineVersion": inspection.inspection_engine_version,
        "toolName": artifact.tool_name,
        "toolVersion": artifact.tool_version,
        "inspectionToolVersion": inspection.inspection_tool_version,
        "format": artifact.format,
        "formatVersion": artifact.format_version,
        "sourceDatabaseIdentitySha256": artifact.source_database_identity_sha256,
        "schemaRevision": inspection.schema_revision,
        "schemaDigestAlgorithm": _schema_algorithm(artifact),
        "rowsetDigestAlgorithm": "sha256-canonical-typed-rowset-v1",
        "byteLength": len(artifact.raw_bytes),
        "schemaSha256": inspection.schema_sha256,
        "tableInventorySha256": inspection.table_inventory_sha256,
        "tables": table_inventory_documents(inspection.tables),
        "integrity": _integrity_document(inspection),
    }


def _semantic_object_documents(
    references: tuple[ReferencedObject, ...],
) -> list[dict[str, Any]]:
    result = [
        {
            "referenceType": item.reference_type,
            "referenceId": item.reference_id,
            "sourceLogicalUri": item.source_logical_uri,
            "contentSha256": item.content_sha256,
        }
        for item in references
    ]
    result.sort(key=lambda item: (item["referenceType"], item["referenceId"]))
    return result


def _publish_or_replay_checkpoint(
    recovery: RecoveryDomain,
    checkpoint: dict[str, Any],
) -> dict[str, Any]:
    """Publish one canonical manifest per trigger using only immutable APIs.

    Artifact inventory plus full verified reads makes the replay fence
    restart-safe without a mutable index or a first/latest ordering rule.
    Relational archives are skipped because they are not canonical recovery
    JSON.  A second valid manifest for the same trigger is accepted only when
    its complete canonical bytes are identical.
    """

    candidate_bytes = canonical_recovery_json(checkpoint).encode("ascii")
    trigger = checkpoint["triggerCycle"]
    trigger_identity = (
        trigger["cycleId"],
        trigger["manifest"]["contentSha256"],
    )
    inventory = _inventory(
        recovery,
        referenced_uris=(),
        object_kind=StorageObjectKind.ARTIFACT,
        phase="checkpoint_publication_scan",
    )
    for address in inventory.orphan_objects:
        read = _verified_read(
            recovery,
            uri=address.uri,
            content_sha256=address.content_sha256,
            expected_kind=StorageObjectKind.ARTIFACT,
            phase="checkpoint_publication_scan",
        )
        try:
            existing = parse_canonical_recovery_bytes(read.raw_bytes)
        except RecoveryContractError:
            continue
        if existing.get("policyVersion") != "recovery-checkpoint-v1":
            continue
        existing_trigger = existing.get("triggerCycle")
        existing_identity = None
        if type(existing_trigger) is dict:
            existing_manifest = existing_trigger.get("manifest")
            if type(existing_manifest) is dict:
                existing_identity = (
                    existing_trigger.get("cycleId"),
                    existing_manifest.get("contentSha256"),
                )
        if existing_identity != trigger_identity:
            continue
        try:
            validate_checkpoint_manifest(existing)
        except RecoveryContractError:
            raise RecoveryReplayConflict(
                "Stored checkpoint publication for this trigger is invalid."
            ) from None
        if canonical_recovery_json(existing) != candidate_bytes.decode("ascii"):
            raise RecoveryReplayConflict(
                "Checkpoint publication conflicts with the deterministic trigger identity."
            )
        return deepcopy(existing)

    _copy_bytes(
        recovery,
        raw_bytes=candidate_bytes,
        object_kind=StorageObjectKind.ARTIFACT,
    )
    return deepcopy(checkpoint)


def _require_published_checkpoint(
    recovery: RecoveryDomain,
    checkpoint: Mapping[str, Any],
) -> None:
    """Prove the caller document is the one immutable published manifest.

    Recovery never trusts a merely well-formed, re-signed caller mapping.  It
    inventories every recovery artifact, fully verifies its bytes, and accepts
    exactly one canonical checkpoint for the supplied trigger identity.  A
    missing, invalid, or conflicting same-trigger publication fails closed;
    artifact enumeration order has no effect on the result.
    """

    expected = canonical_recovery_json(dict(checkpoint)).encode("ascii")
    trigger = checkpoint["triggerCycle"]
    trigger_identity = (
        trigger["cycleId"],
        trigger["manifest"]["contentSha256"],
    )
    matches: list[bytes] = []
    inventory = _inventory(
        recovery,
        referenced_uris=(),
        object_kind=StorageObjectKind.ARTIFACT,
        phase="checkpoint_publication_resolution",
    )
    for address in inventory.orphan_objects:
        read = _verified_read(
            recovery,
            uri=address.uri,
            content_sha256=address.content_sha256,
            expected_kind=StorageObjectKind.ARTIFACT,
            phase="checkpoint_publication_resolution",
        )
        try:
            candidate = parse_canonical_recovery_bytes(read.raw_bytes)
        except RecoveryContractError:
            continue
        if candidate.get("policyVersion") != "recovery-checkpoint-v1":
            continue
        candidate_trigger = candidate.get("triggerCycle")
        candidate_manifest = (
            candidate_trigger.get("manifest")
            if type(candidate_trigger) is dict
            else None
        )
        candidate_identity = (
            candidate_trigger.get("cycleId")
            if type(candidate_trigger) is dict
            else None,
            candidate_manifest.get("contentSha256")
            if type(candidate_manifest) is dict
            else None,
        )
        if candidate_identity != trigger_identity:
            continue
        try:
            validate_checkpoint_manifest(candidate)
        except RecoveryContractError:
            raise RecoveryIntegrityError(
                "Published checkpoint for the requested trigger is invalid."
            ) from None
        matches.append(read.raw_bytes)
    if len(matches) != 1 or matches[0] != expected:
        raise RecoveryIntegrityError(
            "Supplied checkpoint does not re-resolve to exactly one immutable publication."
        )


def create_checkpoint_with_driver(
    *,
    driver: RelationalBackupRestoreDriver,
    database_source: object,
    trigger_cycle: Mapping[str, Any],
    primary_store: RecoveryDomain | LocalRecoveryStore,
    recovery_store: RecoveryDomain | LocalRecoveryStore,
    created_at: str,
    inspection_target: object | None = None,
    inspection_target_id: str | None = None,
    cancel_requested: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """Generic internal checkpoint path shared by reviewed relational drivers."""

    primary, recovery = require_distinct_domains(primary_store, recovery_store)
    _check_cancelled(cancel_requested, phase="before_checkpoint")
    artifact = driver.create_backup(database_source, cancel_requested=cancel_requested)
    if not isinstance(artifact, RelationalBackupArtifact):
        raise RecoveryIntegrityError("Relational driver returned an untyped backup artifact.")
    inspection = driver.inspect_artifact(
        artifact,
        inspection_target=inspection_target,
        target_id=inspection_target_id,
        cancel_requested=cancel_requested,
    )
    if not isinstance(inspection, RelationalInspectionResult) or inspection.artifact != artifact:
        raise RecoveryIntegrityError("Relational driver inspection is untyped or binds other bytes.")
    trigger = exact_trigger_payload(inspection, dict(trigger_cycle))
    cycles = cycle_documents(inspection)
    cycle_set_sha = recovery_cycle_set_digest(cycles)
    try:
        created = datetime.strptime(created_at, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
        scheduled = datetime.strptime(
            trigger["slot"]["scheduledFor"], "%Y-%m-%dT%H:%M:%SZ"
        ).replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        raise RecoveryTargetError(
            "Checkpoint timing must be canonical second-precision UTC."
        ) from None
    if created < scheduled:
        raise RecoveryTargetError(
            "Checkpoint creation cannot precede its completed trigger cycle."
        )

    relational_copy = _copy_bytes(
        recovery,
        raw_bytes=artifact.raw_bytes,
        object_kind=StorageObjectKind.ARTIFACT,
    )
    _check_cancelled(cancel_requested, phase="after_relational_copy")

    objects: list[dict[str, Any]] = []
    copy_cache: dict[tuple[str, str], tuple[dict[str, Any], int]] = {}
    for reference in inspection.referenced_objects:
        if reference.reference_type != "source_snapshot_raw" or reference.object_kind != "snapshot":
            raise UnsupportedRecoveryArtifact("Database contains an unsupported opaque artifact reference.")
        cache_key = (reference.source_logical_uri, reference.content_sha256)
        cached = copy_cache.get(cache_key)
        if cached is None:
            source_read = _verified_read(
                primary,
                uri=reference.source_logical_uri,
                content_sha256=reference.content_sha256,
                expected_kind=StorageObjectKind.SNAPSHOT,
            )
            recovery_copy = _copy_bytes(
                recovery,
                raw_bytes=source_read.raw_bytes,
                object_kind=StorageObjectKind.SNAPSHOT,
            )
            cached = (recovery_copy, len(source_read.raw_bytes))
            copy_cache[cache_key] = cached
        recovery_copy, byte_length = cached
        objects.append(
            {
                "referenceType": reference.reference_type,
                "referenceId": reference.reference_id,
                "sourceLogicalUri": reference.source_logical_uri,
                "objectKind": reference.object_kind,
                "contentSha256": reference.content_sha256,
                "byteLength": byte_length,
                "recoveryCopy": deepcopy(recovery_copy),
            }
        )
        _check_cancelled(
            cancel_requested,
            phase="object_recovery_copy",
            completed_object_count=len(objects),
        )
    objects.sort(key=lambda item: (item["referenceType"], item["referenceId"]))
    if inspection.governed_artifact_count != 0:
        raise UnsupportedRecoveryArtifact(
            "Current DATA-10 contract has no governed release-artifact table/referent."
        )
    object_set_sha = recovery_object_set_digest(objects)

    relational = _relational_base(inspection)
    physical_sha = compute_content_hash(artifact.raw_bytes)
    relational.update(
        {
            "artifactId": "relational-backup_" + physical_sha,
            "contentSha256": physical_sha,
            "recoveryCopy": relational_copy,
        }
    )
    trigger_document = {
        "cycleId": trigger["cycleId"],
        "manifest": {
            "contentSha256": trigger["manifest"]["contentSha256"],
        },
        "environment": trigger["environment"],
        "lane": trigger["lane"],
        "schedulePolicyRevisionId": trigger["schedulePolicyRevisionId"],
        "scheduledFor": trigger["slot"]["scheduledFor"],
        "nextScheduledFor": trigger["slot"]["nextScheduledFor"],
        "state": "terminal",
        "mode": trigger["mode"],
    }
    checkpoint_id = derive_checkpoint_id(
        cycle_id=trigger_document["cycleId"],
        cycle_sha256=trigger_document["manifest"]["contentSha256"],
        cycle_set_sha256=cycle_set_sha,
        table_inventory_sha256=inspection.table_inventory_sha256,
        object_set_sha256=object_set_sha,
    )
    checkpoint: dict[str, Any] = {
        "schemaVersion": "1.0.0",
        "policyVersion": "recovery-checkpoint-v1",
        "availability": "recovery_evidence_only",
        "mode": trigger["mode"],
        "checkpointId": checkpoint_id,
        "createdAt": created_at,
        "triggerCycle": trigger_document,
        "cycleInventory": {
            "completedCycleCount": len(cycles),
            "cycleSetSha256": cycle_set_sha,
            "cycles": cycles,
            "watermarks": cycle_watermarks(cycles),
        },
        "relationalBackup": relational,
        "objectManifest": {
            "sourceSnapshotRowCount": len(objects),
            "governedArtifactCount": 0,
            "objectReferenceCount": len(objects),
            "uniqueObjectCount": len(
                {
                    (item["recoveryCopy"]["uri"], item["contentSha256"])
                    for item in objects
                }
            ),
            "objectSetSha256": object_set_sha,
            "objects": objects,
        },
        "failureDomains": {
            "source": primary.failure_domain_id,
            "recovery": recovery.failure_domain_id,
            "declaredDistinct": True,
            "independenceEvidence": "external_evidence_required",
        },
        "recoveryObjective": {
            "maximumCompletedCyclesLost": 1,
            "status": "target_only_unproven",
            "productionClaim": False,
        },
        "authority": _authority(),
        "manifest": {
            "algorithm": "sha256-canonical-recovery-json-v1",
            "contentSha256": "0" * 64,
            "tableCount": len(inspection.tables),
            "objectReferenceCount": len(objects),
        },
    }
    checkpoint["manifest"]["contentSha256"] = recovery_contract_digest(checkpoint)
    validate_checkpoint_manifest(checkpoint)
    return _publish_or_replay_checkpoint(recovery, checkpoint)


def create_sqlite_checkpoint(
    *,
    database_path: Path,
    trigger_cycle: Mapping[str, Any],
    primary_store: RecoveryDomain | LocalRecoveryStore,
    recovery_store: RecoveryDomain | LocalRecoveryStore,
    created_at: str,
    cancel_requested: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    return create_checkpoint_with_driver(
        driver=SQLiteBackupRestoreDriver(),
        database_source=Path(database_path),
        trigger_cycle=trigger_cycle,
        primary_store=primary_store,
        recovery_store=recovery_store,
        created_at=created_at,
        cancel_requested=cancel_requested,
    )


def assert_checkpoint_replay(
    existing: Mapping[str, Any], candidate: Mapping[str, Any]
) -> dict[str, Any]:
    """Accept byte-exact replay only; never choose first/latest by creation order."""

    try:
        validate_checkpoint_manifest(existing)
        validate_checkpoint_manifest(candidate)
    except RecoveryContractError as exc:
        raise RecoveryReplayConflict("Checkpoint replay includes an invalid contract.") from exc
    existing_document = dict(existing)
    candidate_document = dict(candidate)
    if (
        existing_document["triggerCycle"]["cycleId"]
        != candidate_document["triggerCycle"]["cycleId"]
        or existing_document["triggerCycle"]["manifest"]["contentSha256"]
        != candidate_document["triggerCycle"]["manifest"]["contentSha256"]
        or existing_document["checkpointId"] != candidate_document["checkpointId"]
        or canonical_recovery_json(existing_document)
        != canonical_recovery_json(candidate_document)
    ):
        raise RecoveryReplayConflict(
            "Checkpoint publication conflicts with the deterministic trigger identity."
        )
    return deepcopy(existing_document)


def _compare_restored_relational(
    checkpoint_relational: Mapping[str, Any], inspection: RelationalInspectionResult
) -> None:
    restored = _relational_base(inspection)
    comparisons = {
        "artifactType": restored["artifactType"],
        "driverId": restored["driverId"],
        "driverVersion": restored["driverVersion"],
        "engineName": restored["engineName"],
        "engineVersion": restored["engineVersion"],
        "inspectionEngineVersion": restored["inspectionEngineVersion"],
        "toolName": restored["toolName"],
        "toolVersion": restored["toolVersion"],
        "inspectionToolVersion": restored["inspectionToolVersion"],
        "format": restored["format"],
        "formatVersion": restored["formatVersion"],
        "sourceDatabaseIdentitySha256": restored["sourceDatabaseIdentitySha256"],
        "schemaRevision": restored["schemaRevision"],
        "schemaDigestAlgorithm": restored["schemaDigestAlgorithm"],
        "rowsetDigestAlgorithm": restored["rowsetDigestAlgorithm"],
        "schemaSha256": restored["schemaSha256"],
        "tableInventorySha256": restored["tableInventorySha256"],
        "tables": restored["tables"],
        "integrity": restored["integrity"],
    }
    for field, observed in comparisons.items():
        if checkpoint_relational[field] != observed:
            raise RecoveryIntegrityError(
                f"Fresh relational restore differs from checkpoint field {field}."
            )


def _require_driver_binding(
    driver: RelationalBackupRestoreDriver,
    checkpoint_relational: Mapping[str, Any],
) -> None:
    """Fail before target mutation when a checkpoint is routed to another driver."""

    try:
        conforms = isinstance(driver, RelationalBackupRestoreDriver)
    except Exception:
        conforms = False
    if not conforms:
        raise UnsupportedRecoveryArtifact(
            "Relational restore driver does not implement the typed recovery protocol."
        ) from None
    fields = (
        ("driverId", "driver_id"),
        ("driverVersion", "driver_version"),
        ("engineName", "engine_name"),
        ("toolName", "tool_name"),
        ("artifactType", "artifact_type"),
        ("format", "format"),
        ("formatVersion", "format_version"),
    )
    try:
        restore = getattr(driver, "restore_new_target")
        observed = {field: getattr(driver, attribute) for field, attribute in fields}
    except Exception:
        raise UnsupportedRecoveryArtifact(
            "Relational restore driver does not expose the required typed binding."
        ) from None
    if not callable(restore) or any(
        type(value) is not str or value != checkpoint_relational[field]
        for field, value in observed.items()
    ):
        raise UnsupportedRecoveryArtifact(
            "Relational restore driver does not match the checkpoint artifact binding."
        )


def restore_checkpoint_with_driver(
    *,
    driver: RelationalBackupRestoreDriver,
    checkpoint: Mapping[str, Any],
    recovery_store: RecoveryDomain | LocalRecoveryStore,
    restore_store: RecoveryDomain | LocalRecoveryStore,
    relational_target: object,
    target_id: str,
    started_at: str | None = None,
    finished_at: str | None = None,
    utc_now: Callable[[], datetime] | None = None,
    cancel_requested: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """Restore one checkpoint through its explicitly bound relational driver.

    Provider-specific target admission and freshness remain the driver's
    responsibility.  Path targets receive the existing local containment and
    no-replace preflight in addition to that driver boundary.

    Supplying both timestamps retains the deterministic evidence-construction
    path.  Omitting both measures the local operation using ``utc_now`` (or the
    real UTC clock), with canonical second-precision receipt timestamps.
    """

    _validate_restore_target_id(target_id)
    explicit_timing = _validate_explicit_restore_timing(
        started_at=started_at,
        finished_at=finished_at,
    )
    if relational_target is None:
        raise RecoveryTargetError("Relational restore target is required.")
    target_path = (
        _validate_new_path_target(relational_target)
        if isinstance(relational_target, Path)
        else None
    )
    driver_target = target_path if target_path is not None else relational_target
    document = deepcopy(dict(checkpoint))
    try:
        validate_checkpoint_manifest(document)
    except RecoveryContractError as exc:
        raise RecoveryIntegrityError("Restore refuses an invalid checkpoint manifest.") from exc
    _require_driver_binding(driver, document["relationalBackup"])
    recovery, target_store = require_distinct_domains(recovery_store, restore_store)
    if recovery.failure_domain_id != document["failureDomains"]["recovery"]:
        raise RecoveryIntegrityError("Recovery store domain does not match the checkpoint.")
    if target_store.failure_domain_id == document["failureDomains"]["source"]:
        raise RecoveryTargetError(
            "Restore object target cannot reuse the checkpoint source domain."
        )
    _require_published_checkpoint(recovery, document)
    if target_path is not None:
        for domain in (recovery, target_store):
            root = _static_local_root(domain)
            if root is not None and _paths_overlap(target_path, root):
                raise RecoveryTargetError(
                    "Relational restore target cannot overlap a recovery object root."
                )
    if explicit_timing is None:
        clock = utc_now if utc_now is not None else _real_utc_now
        if not callable(clock):
            raise RecoveryTargetError("Trusted restore UTC clock must be callable.")
        started, receipt_started_at = _sample_trusted_utc_clock(
            clock,
            phase="restore_timing_start",
            target_created=False,
        )
    else:
        started, explicit_finished = explicit_timing
        _, receipt_started_at = _canonical_utc_second(started)
    _require_fresh_target_store(target_store)
    _check_cancelled(cancel_requested, phase="before_restore")

    relational = document["relationalBackup"]
    recovery_copy = relational["recoveryCopy"]
    backup_read = _verified_manifest_copy(
        recovery,
        recovery_copy,
        expected_kind=StorageObjectKind.ARTIFACT,
        expected_sha256=relational["contentSha256"],
        phase="relational_recovery_read",
    )
    if len(backup_read.raw_bytes) != relational["byteLength"]:
        raise RecoveryIntegrityError("Relational recovery copy byte length is wrong.")
    artifact = RelationalBackupArtifact(
        driver_id=relational["driverId"],
        driver_version=relational["driverVersion"],
        engine_name=relational["engineName"],
        engine_version=relational["engineVersion"],
        tool_name=relational["toolName"],
        tool_version=relational["toolVersion"],
        artifact_type=relational["artifactType"],
        format=relational["format"],
        format_version=relational["formatVersion"],
        source_database_identity_sha256=relational["sourceDatabaseIdentitySha256"],
        raw_bytes=backup_read.raw_bytes,
    )
    restored = driver.restore_new_target(
        artifact,
        driver_target,
        target_id=target_id,
        cancel_requested=cancel_requested,
    )
    if not isinstance(restored, RelationalInspectionResult):
        raise RecoveryIntegrityError(
            "Relational restore driver returned an untyped inspection result."
        )
    _compare_restored_relational(relational, restored)
    expected_cycles = cycle_documents(restored)
    if expected_cycles != document["cycleInventory"]["cycles"]:
        raise RecoveryIntegrityError("Restored terminal-cycle denominator differs from checkpoint.")
    restored_refs = _semantic_object_documents(restored.referenced_objects)
    checkpoint_refs = _semantic_object_documents(
        tuple(
            ReferencedObject(
                item["referenceType"],
                item["referenceId"],
                item["sourceLogicalUri"],
                item["objectKind"],
                item["contentSha256"],
            )
            for item in document["objectManifest"]["objects"]
        )
    )
    if restored_refs != checkpoint_refs:
        raise RecoveryIntegrityError(
            "Restored database object denominator differs from checkpoint manifest."
        )

    restored_objects: list[dict[str, Any]] = []
    restore_cache: dict[tuple[str, str], tuple[dict[str, Any], int]] = {}
    for item in document["objectManifest"]["objects"]:
        recovery_object = item["recoveryCopy"]
        cache_key = (recovery_object["uri"], item["contentSha256"])
        cached = restore_cache.get(cache_key)
        if cached is None:
            recovered = _verified_manifest_copy(
                recovery,
                recovery_object,
                expected_kind=StorageObjectKind.SNAPSHOT,
                expected_sha256=item["contentSha256"],
                phase="object_recovery_read",
                target_created=True,
            )
            restored_copy = _copy_bytes(
                target_store,
                raw_bytes=recovered.raw_bytes,
                object_kind=StorageObjectKind.SNAPSHOT,
            )
            cached = (restored_copy, len(recovered.raw_bytes))
            restore_cache[cache_key] = cached
        restored_copy, byte_length = cached
        if byte_length != item["byteLength"]:
            raise RecoveryIntegrityError("Restored object byte length differs from checkpoint.")
        restored_objects.append(
            {
                "referenceType": item["referenceType"],
                "referenceId": item["referenceId"],
                "sourceLogicalUri": item["sourceLogicalUri"],
                "contentSha256": item["contentSha256"],
                "byteLength": byte_length,
                "recoveryCopyUri": recovery_object["uri"],
                "restoredCopy": deepcopy(restored_copy),
            }
        )
        _check_cancelled(
            cancel_requested,
            phase="object_restore",
            completed_object_count=len(restored_objects),
            target_created=True,
        )
    restored_objects.sort(key=lambda item: (item["referenceType"], item["referenceId"]))
    object_set_sha = recovery_object_set_digest(restored_objects)
    if object_set_sha != document["objectManifest"]["objectSetSha256"]:
        raise RecoveryIntegrityError("Restored object reference set digest differs from checkpoint.")
    _verify_exact_target_store(
        target_store,
        snapshot_uris=tuple(
            item["restoredCopy"]["uri"] for item in restored_objects
        ),
        target_created=True,
    )
    relational_restore = _relational_base(restored)
    relational_restore.update(
        {
            "sourceBackupContentSha256": relational["contentSha256"],
            "restoredContentSha256": compute_content_hash(restored.artifact.raw_bytes),
            "matchesCheckpoint": True,
        }
    )
    if explicit_timing is None:
        finished, receipt_finished_at = _sample_trusted_utc_clock(
            clock,
            phase="restore_timing_finish",
            target_created=True,
        )
        if finished < started:
            raise _redacted_partial_failure(
                "RECOVERY_CLOCK_NON_MONOTONIC",
                phase="restore_timing_finish",
                target_created=True,
            ) from None
    else:
        finished = explicit_finished
        _, receipt_finished_at = _canonical_utc_second(finished)
    checkpoint_sha = document["manifest"]["contentSha256"]
    receipt_id = derive_restore_receipt_id(
        checkpoint_id=document["checkpointId"],
        checkpoint_sha256=checkpoint_sha,
        target_id=target_id,
        object_set_sha256=object_set_sha,
    )
    receipt: dict[str, Any] = {
        "schemaVersion": "1.0.0",
        "policyVersion": "recovery-restore-receipt-v1",
        "availability": "recovery_evidence_only",
        "mode": document["mode"],
        "receiptId": receipt_id,
        "startedAt": receipt_started_at,
        "finishedAt": receipt_finished_at,
        "durationMs": int((finished - started).total_seconds() * 1000),
        "checkpoint": {
            "checkpointId": document["checkpointId"],
            "contentSha256": checkpoint_sha,
            "triggerCycleId": document["triggerCycle"]["cycleId"],
            "triggerCycleContentSha256": document["triggerCycle"]["manifest"][
                "contentSha256"
            ],
        },
        "target": {
            "targetId": target_id,
            "freshRelationalTarget": True,
            "recoveryMapOnly": True,
            "cutoverAuthorized": False,
        },
        "failureDomains": {
            "recovery": recovery.failure_domain_id,
            "restore": target_store.failure_domain_id,
            "declaredDistinct": True,
            "independenceEvidence": "external_evidence_required",
        },
        "relationalRestore": relational_restore,
        "objectRestore": {
            "objectReferenceCount": len(restored_objects),
            "uniqueObjectCount": len(
                {
                    (item["restoredCopy"]["uri"], item["contentSha256"])
                    for item in restored_objects
                }
            ),
            "objectSetSha256": object_set_sha,
            "objects": restored_objects,
            "allVerified": True,
        },
        "recoveryAssessment": {
            "maximumCompletedCyclesLostTarget": 1,
            "rpoStatus": "target_not_proven",
            "rtoStatus": "target_not_proven",
            "providerIndependenceStatus": "external_evidence_required",
            "runtimeLocatorCutoverStatus": "not_authorized",
        },
        "authority": _authority(),
        "manifest": {
            "algorithm": "sha256-canonical-recovery-json-v1",
            "contentSha256": "0" * 64,
            "tableCount": len(restored.tables),
            "objectReferenceCount": len(restored_objects),
        },
    }
    receipt["manifest"]["contentSha256"] = recovery_contract_digest(receipt)
    validate_restore_receipt(receipt)
    return receipt


def restore_sqlite_checkpoint(
    *,
    checkpoint: Mapping[str, Any],
    recovery_store: RecoveryDomain | LocalRecoveryStore,
    restore_store: RecoveryDomain | LocalRecoveryStore,
    database_target: Path,
    target_id: str,
    started_at: str | None = None,
    finished_at: str | None = None,
    utc_now: Callable[[], datetime] | None = None,
    cancel_requested: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """Compatibility wrapper for the reviewed SQLite recovery driver."""

    if not isinstance(database_target, Path):
        raise RecoveryTargetError("SQLite restore target must be a pathlib.Path.")
    return restore_checkpoint_with_driver(
        driver=SQLiteBackupRestoreDriver(),
        checkpoint=checkpoint,
        recovery_store=recovery_store,
        restore_store=restore_store,
        relational_target=database_target,
        target_id=target_id,
        started_at=started_at,
        finished_at=finished_at,
        utc_now=utc_now,
        cancel_requested=cancel_requested,
    )


__all__ = [
    "assert_checkpoint_replay",
    "create_checkpoint_with_driver",
    "create_sqlite_checkpoint",
    "restore_checkpoint_with_driver",
    "restore_sqlite_checkpoint",
]
