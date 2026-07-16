"""Safe SQLite backup, byte-derived inventory, lineage audit, and fresh restore.

All inventory queries run against immutable backup/restored bytes.  The live
source connection is used only by SQLite's consistent backup API; it is never
used for a racing post-backup count or object-reference query.
"""

from __future__ import annotations

import hashlib
import os
import platform
import sqlite3
import stat
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator
from urllib.parse import urlsplit

from app.schemas.operations_contracts import (
    OperationsContractError,
    canonical_json as canonical_operations_json,
    validate_scheduled_cycle,
)
from app.schemas.recovery_contracts import (
    canonical_recovery_json,
    recovery_cycle_set_digest,
)
from app.storage.base import compute_content_hash

from .errors import (
    RecoveryCancelled,
    RecoveryIntegrityError,
    RecoveryPartialFailure,
    RecoveryTargetError,
    UnsupportedRecoveryArtifact,
)
from .protocols import (
    RelationalBackupArtifact,
    RelationalInspectionResult,
    RelationalIntegrityResult,
)
from .semantic_inspection import (
    audit_semantic_lineages,
    build_cycle_inventory,
    build_table_inventory,
    enumerate_referenced_objects,
    expected_head_columns,
    table_inventory_digest,
)


_HEAD_REVISION = "0010_operational_persistence"
_DRIVER_ID = "sqlite-python-stdlib"
_DRIVER_VERSION = "1.0.0"
_FORMAT = "sqlite3_backup_image"
_FORMAT_VERSION = "sqlite-file-format-3"
_ARTIFACT_TYPE = "sqlite_database"
_TOOL_NAME = "python-sqlite3-backup-api"
_SQLITE_HEADER = b"SQLite format 3\x00"
# Reviewed Alembic head (0010) executable schema: 36 application/Alembic
# tables, 66 named indexes, 99 append-only/lineage triggers, and no views.
# SQLite/SQLAlchemy can serialize the two foreign keys on the reconstructed
# official_source_revisions table in either order; these are the only two
# reviewed, semantically identical serializations (confirmed across isolated
# hash seeds).  Every other sqlite_schema definition is exact.  An extra or
# weakened trigger/index/view/constraint therefore remains outside the set.
_HEAD_SCHEMA_SHA256_ALLOWLIST = frozenset(
    {
        "3747b1abe4e90ae30de795de321766250267084a723c6b0b0f027b1728724292",
        "8d845810a4fb4d4aa7f3cb1c388140da2137f24d3f27afc83afe9e43b358cac6",
    }
)
_REQUIRED_TRIGGERS = {
    "trg_claim_publication_decisions_linear_insert",
    "trg_claim_publication_decisions_parent_insert",
    "trg_claim_review_decisions_linear_insert",
    "trg_claim_review_decisions_parent_insert",
    "trg_identity_decisions_chain_insert",
    "trg_notification_receipts_reference_insert",
    "trg_ops_incident_events_chain_insert",
    "trg_review_work_item_events_chain_insert",
    "trg_scheduled_cycles_terminal_insert",
    "trg_source_revision_decisions_linear_insert",
    "trg_source_revision_decisions_parent_insert",
}


def redact_database_locator(locator: object) -> str:
    """Return a stable diagnostic label without a path, DSN, query, or secret."""

    if isinstance(locator, Path):
        return "sqlite-file:<redacted>"
    if isinstance(locator, str):
        try:
            parsed = urlsplit(locator)
            base_scheme = parsed.scheme.lower().split("+", 1)[0]
            hostname = parsed.hostname
            port = parsed.port
        except ValueError:
            return "database:<redacted>"
        if base_scheme in {"postgresql", "postgres", "mysql"} and hostname:
            if not all(character.isalnum() or character in ".:-" for character in hostname):
                return f"{base_scheme}:<redacted>"
            authority = hostname if port is None else f"{hostname}:{port}"
            return f"{base_scheme}://{authority}/<redacted>"
        if base_scheme == "sqlite":
            return "sqlite:<redacted>"
    return "database:<redacted>"


def _sqlite_locator_identity(path: Path) -> str:
    identity = {
        "identityType": "sqlite_resolved_locator_v1",
        "resolvedPath": str(path.expanduser().resolve(strict=False)),
    }
    return hashlib.sha256(canonical_recovery_json(identity).encode("ascii")).hexdigest()


def _cancel(
    cancel_requested: Callable[[], bool] | None,
    *,
    phase: str,
    target_created: bool = False,
) -> None:
    if cancel_requested is not None and cancel_requested():
        raise RecoveryCancelled(
            phase=phase,
            relational_target_created=target_created,
        )


def _require_regular_source(path: Path) -> Path:
    candidate = Path(path).expanduser()
    try:
        metadata = candidate.lstat()
    except FileNotFoundError:
        raise RecoveryTargetError("SQLite backup source does not exist.") from None
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise RecoveryTargetError("SQLite backup source must be a regular non-symlink file.")
    return candidate.resolve()


@contextmanager
def _read_only_connection(path: Path) -> Iterator[sqlite3.Connection]:
    uri = path.resolve().as_uri() + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    try:
        connection.execute("PRAGMA query_only=ON")
        connection.execute("PRAGMA foreign_keys=ON")
        yield connection
    finally:
        connection.close()


def _write_private_file(path: Path, raw_bytes: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    try:
        view = memoryview(raw_bytes)
        written = 0
        while written < len(view):
            count = os.write(descriptor, view[written:])
            if count <= 0:
                raise OSError("short write")
            written += count
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _schema_sha256(connection: sqlite3.Connection) -> str:
    rows = connection.execute(
        """
        SELECT type, name, tbl_name, sql
        FROM sqlite_schema
        WHERE name NOT LIKE 'sqlite_%'
          AND type IN ('table', 'index', 'trigger', 'view')
        ORDER BY type, name, tbl_name
        """
    ).fetchall()
    material = [
        {"type": row[0], "name": row[1], "tableName": row[2], "sql": row[3]}
        for row in rows
    ]
    return hashlib.sha256(canonical_recovery_json(material).encode("ascii")).hexdigest()


def _rows(connection: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    cursor = connection.execute(f"SELECT * FROM {_quote_identifier(table)}")
    names = [description[0] for description in cursor.description]
    return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]


def _inspect_sqlite_path(path: Path, artifact: RelationalBackupArtifact) -> RelationalInspectionResult:
    raw_bytes = path.read_bytes()
    if raw_bytes != artifact.raw_bytes or compute_content_hash(raw_bytes) != compute_content_hash(artifact.raw_bytes):
        raise RecoveryIntegrityError("Staged SQLite bytes differ from the typed backup artifact.")
    expected = expected_head_columns()
    with _read_only_connection(path) as connection:
        integrity_rows = connection.execute("PRAGMA integrity_check").fetchall()
        if integrity_rows != [("ok",)]:
            raise RecoveryIntegrityError("SQLite integrity_check did not return exactly ok.")
        foreign_key_violations = connection.execute("PRAGMA foreign_key_check").fetchall()
        if foreign_key_violations:
            raise RecoveryIntegrityError("SQLite foreign_key_check reported violations.")
        actual_tables = tuple(
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_schema WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        )
        if set(actual_tables) != set(expected):
            raise RecoveryIntegrityError("SQLite head has missing or extra application tables.")
        for table_name, expected_columns in expected.items():
            actual_columns = tuple(
                sorted(
                    row[1]
                    for row in connection.execute(
                        f"PRAGMA table_xinfo({_quote_identifier(table_name)})"
                    ).fetchall()
                )
            )
            if actual_columns != expected_columns:
                raise RecoveryIntegrityError(
                    f"SQLite table {table_name!r} has missing or extra columns."
                )
        revisions = connection.execute("SELECT version_num FROM alembic_version").fetchall()
        if revisions != [(_HEAD_REVISION,)]:
            raise RecoveryIntegrityError("SQLite backup is not at the single supported schema head.")
        triggers = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_schema WHERE type='trigger'"
            )
        }
        if not _REQUIRED_TRIGGERS.issubset(triggers):
            raise RecoveryIntegrityError("SQLite head is missing required integrity triggers.")
        schema_sha256 = _schema_sha256(connection)
        if schema_sha256 not in _HEAD_SCHEMA_SHA256_ALLOWLIST:
            raise RecoveryIntegrityError(
                "SQLite executable schema does not match the reviewed Alembic head."
            )
        semantic_rows = {
            table_name: _rows(connection, table_name) for table_name in sorted(expected)
        }
        tables = build_table_inventory(semantic_rows)
        lineage = audit_semantic_lineages(semantic_rows)
        cycles, payloads = build_cycle_inventory(semantic_rows["scheduled_cycles"])
        objects = enumerate_referenced_objects(semantic_rows["source_snapshots"])
        return RelationalInspectionResult(
            artifact=artifact,
            inspection_engine_version=sqlite3.sqlite_version,
            inspection_tool_version=platform.python_version(),
            schema_revision=_HEAD_REVISION,
            schema_sha256=schema_sha256,
            table_inventory_sha256=table_inventory_digest(tables),
            tables=tables,
            integrity=RelationalIntegrityResult(
                backend="sqlite",
                consistency_check="ok",
                foreign_key_violation_count=0,
                lineage_families=lineage,
            ),
            cycles=cycles,
            cycle_payloads=payloads,
            referenced_objects=objects,
            governed_artifact_count=0,
        )


class SQLiteBackupRestoreDriver:
    """Standard-library SQLite adapter with no delete, downgrade, or overwrite path."""

    driver_id = _DRIVER_ID
    driver_version = _DRIVER_VERSION
    engine_name = "sqlite"
    engine_version = sqlite3.sqlite_version
    tool_name = _TOOL_NAME
    tool_version = platform.python_version()
    artifact_type = _ARTIFACT_TYPE
    format = _FORMAT
    format_version = _FORMAT_VERSION

    def create_backup(
        self,
        source: object,
        *,
        cancel_requested: Callable[[], bool] | None = None,
    ) -> RelationalBackupArtifact:
        if not isinstance(source, Path):
            raise RecoveryTargetError("SQLite driver source must be a pathlib.Path.")
        source_path = _require_regular_source(source)
        _cancel(cancel_requested, phase="before_relational_backup")
        with tempfile.TemporaryDirectory(prefix="ledger-recovery-sqlite-") as temporary:
            staged = Path(temporary) / "backup.sqlite3"
            try:
                with _read_only_connection(source_path) as source_connection:
                    destination = sqlite3.connect(staged)
                    try:
                        def progress(_status: int, _remaining: int, _total: int) -> None:
                            _cancel(cancel_requested, phase="relational_backup")

                        source_connection.backup(destination, pages=256, progress=progress)
                    finally:
                        destination.close()
            except RecoveryCancelled:
                raise
            except (sqlite3.DatabaseError, OSError):
                raise RecoveryPartialFailure(
                    "SQLITE_BACKUP_FAILED", phase="relational_backup"
                ) from None
            raw_bytes = staged.read_bytes()
        if not raw_bytes.startswith(_SQLITE_HEADER):
            raise RecoveryIntegrityError("SQLite backup artifact lacks the file-format header.")
        return RelationalBackupArtifact(
            driver_id=self.driver_id,
            driver_version=self.driver_version,
            engine_name=self.engine_name,
            engine_version=self.engine_version,
            tool_name=self.tool_name,
            tool_version=self.tool_version,
            artifact_type=self.artifact_type,
            format=self.format,
            format_version=self.format_version,
            source_database_identity_sha256=_sqlite_locator_identity(source_path),
            raw_bytes=raw_bytes,
        )

    def _require_artifact(self, artifact: RelationalBackupArtifact) -> None:
        expected = (
            self.driver_id,
            self.driver_version,
            self.engine_name,
            self.tool_name,
            self.artifact_type,
            self.format,
            self.format_version,
        )
        actual = (
            artifact.driver_id,
            artifact.driver_version,
            artifact.engine_name,
            artifact.tool_name,
            artifact.artifact_type,
            artifact.format,
            artifact.format_version,
        )
        if actual != expected:
            raise UnsupportedRecoveryArtifact(
                "Relational backup driver/engine/artifact format is unsupported."
            )
        if (
            not artifact.engine_version.startswith("3.")
            or not artifact.tool_version
            or artifact.tool_version.split(".", 1)[0]
            != self.tool_version.split(".", 1)[0]
        ):
            raise UnsupportedRecoveryArtifact(
                "SQLite producer engine/tool version is outside the deliberate compatibility range."
            )
        if not artifact.raw_bytes.startswith(_SQLITE_HEADER):
            raise RecoveryIntegrityError("Relational backup bytes are not a SQLite image.")

    def inspect_artifact(
        self,
        artifact: RelationalBackupArtifact,
        *,
        inspection_target: object | None = None,
        target_id: str | None = None,
        cancel_requested: Callable[[], bool] | None = None,
    ) -> RelationalInspectionResult:
        if inspection_target is not None or target_id is not None:
            raise RecoveryTargetError(
                "SQLite archive inspection does not accept an external inspection target."
            )
        _cancel(cancel_requested, phase="before_relational_inspection")
        self._require_artifact(artifact)
        with tempfile.TemporaryDirectory(prefix="ledger-recovery-inspect-") as temporary:
            staged = Path(temporary) / "inspection.sqlite3"
            _write_private_file(staged, artifact.raw_bytes)
            return _inspect_sqlite_path(staged, artifact)

    def restore_new_target(
        self,
        artifact: RelationalBackupArtifact,
        target: object,
        *,
        target_id: str,
        cancel_requested: Callable[[], bool] | None = None,
    ) -> RelationalInspectionResult:
        self._require_artifact(artifact)
        if not isinstance(target, Path):
            raise RecoveryTargetError("SQLite restore target must be a pathlib.Path.")
        if type(target_id) is not str or not target_id:
            raise RecoveryTargetError("SQLite restore target needs an opaque stable ID.")
        target_path = Path(target).expanduser()
        if target_path.exists() or target_path.is_symlink():
            raise RecoveryTargetError("SQLite restore target already exists.")
        if _sqlite_locator_identity(target_path) == artifact.source_database_identity_sha256:
            raise RecoveryTargetError("SQLite restore target resolves to the backup source locator.")
        _cancel(cancel_requested, phase="before_relational_restore")
        try:
            _write_private_file(target_path, artifact.raw_bytes)
            _cancel(
                cancel_requested,
                phase="after_relational_restore_write",
                target_created=True,
            )
            restored_bytes = target_path.read_bytes()
            if (
                len(restored_bytes) != len(artifact.raw_bytes)
                or compute_content_hash(restored_bytes)
                != compute_content_hash(artifact.raw_bytes)
            ):
                raise RecoveryIntegrityError(
                    "Fresh SQLite restore target differs in length or full-byte digest."
                )
            restored_artifact = RelationalBackupArtifact(
                driver_id=artifact.driver_id,
                driver_version=artifact.driver_version,
                engine_name=artifact.engine_name,
                engine_version=artifact.engine_version,
                tool_name=artifact.tool_name,
                tool_version=artifact.tool_version,
                artifact_type=artifact.artifact_type,
                format=artifact.format,
                format_version=artifact.format_version,
                source_database_identity_sha256=artifact.source_database_identity_sha256,
                raw_bytes=restored_bytes,
            )
            return _inspect_sqlite_path(target_path, restored_artifact)
        except (RecoveryCancelled, RecoveryIntegrityError, RecoveryTargetError):
            raise
        except OSError:
            raise RecoveryPartialFailure(
                "SQLITE_RESTORE_WRITE_FAILED",
                phase="relational_restore",
                relational_target_created=target_path.exists(),
            ) from None


def cycle_documents(
    inspection: RelationalInspectionResult,
) -> list[dict[str, Any]]:
    return [
        {
            "environment": item.environment,
            "lane": item.lane,
            "cycleId": item.cycle_id,
            "scheduledFor": item.scheduled_for,
            "schedulePolicyRevisionId": item.schedule_policy_revision_id,
            "contentSha256": item.content_sha256,
        }
        for item in inspection.cycles
    ]


def cycle_watermarks(cycles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for cycle in cycles:
        groups.setdefault((cycle["environment"], cycle["lane"]), []).append(cycle)
    watermarks: list[dict[str, Any]] = []
    for (environment, lane), rows in sorted(groups.items()):
        ordered = sorted(
            rows,
            key=lambda item: (item["scheduledFor"], item["cycleId"]),
        )
        first, last = ordered[0], ordered[-1]
        watermarks.append(
            {
                "environment": environment,
                "lane": lane,
                "completedCycleCount": len(ordered),
                "earliestScheduledFor": first["scheduledFor"],
                "earliestCycleId": first["cycleId"],
                "latestScheduledFor": last["scheduledFor"],
                "latestCycleId": last["cycleId"],
                "latestCycleContentSha256": last["contentSha256"],
                "cycleSetSha256": recovery_cycle_set_digest(ordered),
            }
        )
    return watermarks


def exact_trigger_payload(
    inspection: RelationalInspectionResult,
    trigger_cycle: dict[str, Any],
) -> dict[str, Any]:
    try:
        validate_scheduled_cycle(trigger_cycle)
    except OperationsContractError as exc:
        raise RecoveryIntegrityError("Trigger is not a terminal scheduled-cycle-v1 document.") from exc
    exact = [
        payload
        for payload in inspection.cycle_payloads
        if payload.get("cycleId") == trigger_cycle["cycleId"]
        and payload.get("manifest", {}).get("contentSha256")
        == trigger_cycle["manifest"]["contentSha256"]
    ]
    if len(exact) != 1:
        raise RecoveryIntegrityError(
            "Trigger cycle is stale, absent, duplicated, or digest-ambiguous in backup bytes."
        )
    if canonical_operations_json(exact[0]) != canonical_operations_json(trigger_cycle):
        raise RecoveryIntegrityError("Trigger cycle payload is not an exact backup-byte match.")
    same_lane = [
        item
        for item in inspection.cycles
        if item.environment == trigger_cycle["environment"]
        and item.lane == trigger_cycle["lane"]
    ]
    latest_time = max(item.scheduled_for for item in same_lane)
    latest = [item for item in same_lane if item.scheduled_for == latest_time]
    if len(latest) != 1 or latest[0].cycle_id != trigger_cycle["cycleId"]:
        raise RecoveryIntegrityError(
            "Trigger cycle is not the unambiguous latest completed cycle for its lane."
        )
    return exact[0]


__all__ = [
    "SQLiteBackupRestoreDriver",
    "cycle_documents",
    "cycle_watermarks",
    "exact_trigger_payload",
    "redact_database_locator",
]
