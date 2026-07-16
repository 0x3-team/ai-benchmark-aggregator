"""Narrow relational recovery seam for future reviewed provider drivers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class RelationalBackupArtifact:
    """Private archive bytes plus typed physical format metadata."""

    driver_id: str
    driver_version: str
    engine_name: str
    engine_version: str
    tool_name: str
    tool_version: str
    artifact_type: str
    format: str
    format_version: str
    source_database_identity_sha256: str
    raw_bytes: bytes = field(repr=False)


@dataclass(frozen=True, slots=True)
class TableInventoryEntry:
    table_name: str
    column_names: tuple[str, ...]
    row_count: int
    rowset_sha256: str


@dataclass(frozen=True, slots=True)
class LineageFamilyResult:
    family: str
    root_count: int
    leaf_count: int
    row_count: int


@dataclass(frozen=True, slots=True)
class RelationalIntegrityResult:
    backend: str
    consistency_check: str
    foreign_key_violation_count: int
    lineage_families: tuple[LineageFamilyResult, ...]


@dataclass(frozen=True, slots=True)
class CycleInventoryEntry:
    environment: str
    lane: str
    cycle_id: str
    scheduled_for: str
    schedule_policy_revision_id: str
    content_sha256: str


@dataclass(frozen=True, slots=True)
class ReferencedObject:
    reference_type: str
    reference_id: str
    source_logical_uri: str
    object_kind: str
    content_sha256: str


@dataclass(frozen=True, slots=True)
class RelationalInspectionResult:
    artifact: RelationalBackupArtifact
    inspection_engine_version: str
    inspection_tool_version: str
    schema_revision: str
    schema_sha256: str
    table_inventory_sha256: str
    tables: tuple[TableInventoryEntry, ...]
    integrity: RelationalIntegrityResult
    cycles: tuple[CycleInventoryEntry, ...]
    cycle_payloads: tuple[dict[str, object], ...] = field(repr=False)
    referenced_objects: tuple[ReferencedObject, ...] = ()
    governed_artifact_count: int = 0


@runtime_checkable
class RelationalBackupRestoreDriver(Protocol):
    """Provider-neutral driver boundary; it contains no shell or DSN receipt.

    A future PostgreSQL implementation must use reviewed argv/tool bindings or
    a library API and return only typed archive/staged results.  This protocol
    does not itself authorize a live connection or provider operation.
    """

    driver_id: str
    driver_version: str
    engine_name: str
    engine_version: str
    tool_name: str
    tool_version: str
    artifact_type: str
    format: str
    format_version: str

    def create_backup(
        self,
        source: object,
        *,
        cancel_requested: Callable[[], bool] | None = None,
    ) -> RelationalBackupArtifact: ...

    def inspect_artifact(
        self,
        artifact: RelationalBackupArtifact,
        *,
        inspection_target: object | None = None,
        target_id: str | None = None,
        cancel_requested: Callable[[], bool] | None = None,
    ) -> RelationalInspectionResult: ...

    def restore_new_target(
        self,
        artifact: RelationalBackupArtifact,
        target: object,
        *,
        target_id: str,
        cancel_requested: Callable[[], bool] | None = None,
    ) -> RelationalInspectionResult: ...


__all__ = [
    "CycleInventoryEntry",
    "LineageFamilyResult",
    "ReferencedObject",
    "RelationalBackupArtifact",
    "RelationalBackupRestoreDriver",
    "RelationalInspectionResult",
    "RelationalIntegrityResult",
    "TableInventoryEntry",
]
