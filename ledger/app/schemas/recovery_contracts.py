"""Pure validators for provider-neutral DATA-10 recovery evidence.

The contracts in this module are deliberately authority-free.  They describe
what immutable bytes were copied and what a fresh-target restore re-resolved;
they do not prove provider failure-domain separation, retention, RPO/RTO, a
runtime cutover, source certification, or publication authority.
"""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Mapping
from urllib.parse import urlsplit


class RecoveryContractError(ValueError):
    """A recovery manifest/receipt is malformed, noncanonical, or tampered."""


_ALGORITHM = "sha256-canonical-recovery-json-v1"
_SHA256 = re.compile(r"[0-9a-f]{64}")
_STABLE_ID = re.compile(r"[a-z0-9][a-z0-9._-]{0,127}")
_CHECKPOINT_ID = re.compile(r"recovery-checkpoint_[0-9a-f]{64}")
_RESTORE_ID = re.compile(r"recovery-restore_[0-9a-f]{64}")
_STORAGE_RECEIPT_ID = re.compile(r"storage-verification-v1:[0-9a-f]{64}")
_UTC = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
_LINEAGE_FAMILIES = {
    "source_revision_decisions",
    "claim_review_decisions",
    "claim_publication_decisions",
    "identity_decisions",
    "ops_incident_events",
    "review_work_item_events",
    "notification_receipts",
}
_HEAD_TABLES = (
    "alembic_version",
    "aliases",
    "benchmark_definition_revisions",
    "benchmarks",
    "claim_publication_decisions",
    "claim_relationships",
    "claim_review_decisions",
    "claim_validations",
    "discovery_candidates",
    "evaluation_subject_revisions",
    "extraction_batches",
    "identity_decisions",
    "ingestion_runs",
    "model_entities",
    "notification_intents",
    "notification_outbox_batches",
    "notification_outbox_items",
    "notification_receipts",
    "official_source_revisions",
    "official_sources",
    "ops_incident_events",
    "ops_incidents",
    "result_claims",
    "review_work_item_events",
    "review_work_items",
    "scheduled_cycle_intent_completions",
    "scheduled_cycle_intents",
    "scheduled_cycles",
    "scheduled_job_attempts",
    "scheduled_job_intents",
    "scheduled_job_lease_events",
    "scheduled_job_leases",
    "source_check_receipts",
    "source_contract_envelopes",
    "source_revision_decisions",
    "source_snapshots",
)


def _fail(path: str, message: str) -> None:
    raise RecoveryContractError(f"{path}: {message}")


def _walk_json(value: Any, path: str = "$") -> None:
    if value is None or type(value) in (str, bool, int):
        return
    if type(value) is list:
        for index, item in enumerate(value):
            _walk_json(item, f"{path}[{index}]")
        return
    if type(value) is dict:
        for key, item in value.items():
            if type(key) is not str:
                _fail(path, "object keys must be strings")
            _walk_json(item, f"{path}.{key}")
        return
    _fail(path, f"unsupported canonical JSON type {type(value).__name__}")


def canonical_recovery_json(value: Any) -> str:
    """Return the exact compact ASCII representation used by DATA-10 digests."""

    _walk_json(value)
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def recovery_contract_digest(payload: Mapping[str, Any]) -> str:
    """Compute a self-digest after replacing manifest.contentSha256 with null."""

    if type(payload) is not dict:
        _fail("$", "contract must be an ordinary object")
    material = deepcopy(payload)
    manifest = material.get("manifest")
    if type(manifest) is not dict or "contentSha256" not in manifest:
        _fail("$.manifest.contentSha256", "is required for self-digesting")
    manifest["contentSha256"] = None
    return hashlib.sha256(canonical_recovery_json(material).encode("ascii")).hexdigest()


def recovery_table_inventory_digest(tables: list[dict[str, Any]]) -> str:
    """Digest the complete sorted table/count/rowset inventory."""

    return hashlib.sha256(canonical_recovery_json(tables).encode("ascii")).hexdigest()


def recovery_cycle_set_digest(cycles: list[dict[str, Any]]) -> str:
    """Digest exact terminal cycle identities, never their insertion order."""

    return hashlib.sha256(canonical_recovery_json(cycles).encode("ascii")).hexdigest()


def recovery_object_set_digest(objects: list[dict[str, Any]]) -> str:
    """Digest database logical object references independently of copy locators."""

    semantic = [
        {
            "referenceType": item["referenceType"],
            "referenceId": item["referenceId"],
            "sourceLogicalUri": item["sourceLogicalUri"],
            "contentSha256": item["contentSha256"],
        }
        for item in objects
    ]
    return hashlib.sha256(canonical_recovery_json(semantic).encode("ascii")).hexdigest()


def parse_canonical_recovery_bytes(raw_bytes: bytes) -> dict[str, Any]:
    """Parse only canonical contract bytes; pretty/reordered encodings are rejected."""

    if type(raw_bytes) is not bytes:
        _fail("$", "canonical contract input must be bytes")
    try:
        payload = json.loads(raw_bytes.decode("ascii"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RecoveryContractError("$: invalid ASCII JSON contract") from exc
    if type(payload) is not dict:
        _fail("$", "contract must decode to an object")
    if raw_bytes != canonical_recovery_json(payload).encode("ascii"):
        _fail("$", "contract bytes are not canonical recovery JSON")
    return payload


def _object(value: Any, path: str, keys: set[str]) -> dict[str, Any]:
    if type(value) is not dict:
        _fail(path, "must be an ordinary object")
    actual = set(value)
    if actual != keys:
        _fail(path, f"requires exact keys {sorted(keys)}; got {sorted(actual)}")
    return value


def _array(value: Any, path: str) -> list[Any]:
    if type(value) is not list:
        _fail(path, "must be an array")
    return value


def _constant(value: Any, expected: Any, path: str) -> None:
    if type(value) is not type(expected) or value != expected:
        _fail(path, f"must be exactly {expected!r}")


def _enum(value: Any, allowed: set[str], path: str) -> str:
    if type(value) is not str or value not in allowed:
        _fail(path, f"must be one of {sorted(allowed)}")
    return value


def _text(value: Any, path: str) -> str:
    if type(value) is not str or not value or any(ord(char) < 32 for char in value):
        _fail(path, "must be non-empty control-free text")
    return value


def _stable_id(value: Any, path: str) -> str:
    if type(value) is not str or _STABLE_ID.fullmatch(value) is None:
        _fail(path, "must be a canonical stable identifier")
    return value


def _sha256(value: Any, path: str) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        _fail(path, "must be a full lowercase SHA-256 digest")
    return value


def _count(value: Any, path: str) -> int:
    if type(value) is not int or value < 0:
        _fail(path, "must be a nonnegative integer")
    return value


def _utc(value: Any, path: str) -> datetime:
    if type(value) is not str or _UTC.fullmatch(value) is None:
        _fail(path, "must be canonical second-precision UTC")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise RecoveryContractError(f"{path}: invalid UTC timestamp") from exc


def _safe_locator(value: Any, path: str) -> str:
    locator = _text(value, path)
    parsed = urlsplit(locator)
    if parsed.scheme and (parsed.username is not None or parsed.password is not None):
        _fail(path, "must not contain user information or credentials")
    if parsed.query or parsed.fragment:
        _fail(path, "must not contain query or fragment material")
    return locator


def _sorted_unique(
    rows: list[dict[str, Any]], *, path: str, key: Any
) -> None:
    keys = [key(row) for row in rows]
    if keys != sorted(keys):
        _fail(path, "must use canonical sorted order")
    if len(keys) != len(set(keys)):
        _fail(path, "contains a duplicate logical identity")


def _validate_copy(value: Any, path: str, *, domain_id: str, kind: str) -> dict[str, Any]:
    copy = _object(
        value,
        path,
        {
            "failureDomainId",
            "provider",
            "objectKind",
            "uri",
            "key",
            "contentSha256",
            "byteLength",
            "writePrecondition",
            "verificationReceiptId",
        },
    )
    _constant(copy["failureDomainId"], domain_id, f"{path}.failureDomainId")
    _stable_id(copy["provider"], f"{path}.provider")
    _constant(copy["objectKind"], kind, f"{path}.objectKind")
    _safe_locator(copy["uri"], f"{path}.uri")
    key = _text(copy["key"], f"{path}.key")
    if key.startswith("/") or "\\" in key or any(
        part in {"", ".", ".."} for part in key.split("/")
    ):
        _fail(f"{path}.key", "must be a canonical relative object key")
    _sha256(copy["contentSha256"], f"{path}.contentSha256")
    _count(copy["byteLength"], f"{path}.byteLength")
    _enum(
        copy["writePrecondition"],
        {"atomic_no_replace", "if_none_match_wildcard"},
        f"{path}.writePrecondition",
    )
    receipt = copy["verificationReceiptId"]
    if type(receipt) is not str or _STORAGE_RECEIPT_ID.fullmatch(receipt) is None:
        _fail(f"{path}.verificationReceiptId", "must be a typed storage verification receipt ID")
    return copy


def _validate_lineage(value: Any, path: str) -> dict[str, Any]:
    lineage = _object(value, path, {"status", "familyCount", "rowCount", "families"})
    _constant(lineage["status"], "passed", f"{path}.status")
    families = _array(lineage["families"], f"{path}.families")
    parsed: list[dict[str, Any]] = []
    for index, raw in enumerate(families):
        row_path = f"{path}.families[{index}]"
        row = _object(raw, row_path, {"family", "rootCount", "leafCount", "rowCount"})
        _enum(
            row["family"],
            _LINEAGE_FAMILIES,
            f"{row_path}.family",
        )
        for field in ("rootCount", "leafCount", "rowCount"):
            _count(row[field], f"{row_path}.{field}")
        if row["rowCount"] and (not row["rootCount"] or not row["leafCount"]):
            _fail(row_path, "non-empty lineage needs roots and leaves")
        parsed.append(row)
    _sorted_unique(parsed, path=f"{path}.families", key=lambda item: item["family"])
    if {item["family"] for item in parsed} != _LINEAGE_FAMILIES:
        _fail(f"{path}.families", "must retain the exact seven-family lineage denominator")
    _constant(lineage["familyCount"], len(parsed), f"{path}.familyCount")
    _constant(
        lineage["rowCount"],
        sum(row["rowCount"] for row in parsed),
        f"{path}.rowCount",
    )
    return lineage


def _validate_integrity(value: Any, path: str, *, backend: str) -> dict[str, Any]:
    status_field = (
        "sqliteIntegrityCheck" if backend == "sqlite" else "postgresqlConsistencyCheck"
    )
    integrity = _object(
        value,
        path,
        {status_field, "foreignKeyViolationCount", "semanticLineageAudit"},
    )
    _constant(
        integrity[status_field],
        "ok" if backend == "sqlite" else "passed",
        f"{path}.{status_field}",
    )
    _constant(integrity["foreignKeyViolationCount"], 0, f"{path}.foreignKeyViolationCount")
    _validate_lineage(integrity["semanticLineageAudit"], f"{path}.semanticLineageAudit")
    return integrity


def _validate_relational_metadata(value: dict[str, Any], path: str) -> str:
    artifact_type = _enum(
        value["artifactType"],
        {"sqlite_database", "postgresql_database"},
        f"{path}.artifactType",
    )
    if artifact_type == "sqlite_database":
        _constant(value["driverId"], "sqlite-python-stdlib", f"{path}.driverId")
        _constant(value["driverVersion"], "1.0.0", f"{path}.driverVersion")
        _constant(value["engineName"], "sqlite", f"{path}.engineName")
        if type(value["engineVersion"]) is not str or re.fullmatch(
            r"3\.\d+\.\d+", value["engineVersion"]
        ) is None:
            _fail(f"{path}.engineVersion", "must be an exact supported SQLite 3 version")
        if type(value["inspectionEngineVersion"]) is not str or re.fullmatch(
            r"3\.\d+\.\d+", value["inspectionEngineVersion"]
        ) is None:
            _fail(
                f"{path}.inspectionEngineVersion",
                "must be an exact supported SQLite 3 inspection version",
            )
        _constant(
            value["toolName"], "python-sqlite3-backup-api", f"{path}.toolName"
        )
        if type(value["toolVersion"]) is not str or re.fullmatch(
            r"3\.\d+\.\d+", value["toolVersion"]
        ) is None:
            _fail(f"{path}.toolVersion", "must be an exact supported Python 3 tool version")
        if type(value["inspectionToolVersion"]) is not str or re.fullmatch(
            r"3\.\d+\.\d+", value["inspectionToolVersion"]
        ) is None:
            _fail(
                f"{path}.inspectionToolVersion",
                "must be an exact supported Python 3 inspection tool version",
            )
        _constant(value["format"], "sqlite3_backup_image", f"{path}.format")
        _constant(value["formatVersion"], "sqlite-file-format-3", f"{path}.formatVersion")
        _constant(
            value["schemaDigestAlgorithm"],
            "sha256-canonical-sqlite-schema-v1",
            f"{path}.schemaDigestAlgorithm",
        )
        backend = "sqlite"
    else:
        _constant(value["driverId"], "postgresql-pg-tools", f"{path}.driverId")
        _constant(value["driverVersion"], "1.0.0", f"{path}.driverVersion")
        _constant(value["engineName"], "postgresql", f"{path}.engineName")
        if type(value["engineVersion"]) is not str or re.fullmatch(
            r"16\.\d+(?:\.\d+)?", value["engineVersion"]
        ) is None:
            _fail(f"{path}.engineVersion", "must be an exact supported PostgreSQL 16 version")
        if type(value["inspectionEngineVersion"]) is not str or re.fullmatch(
            r"16\.\d+(?:\.\d+)?", value["inspectionEngineVersion"]
        ) is None:
            _fail(
                f"{path}.inspectionEngineVersion",
                "must be an exact supported PostgreSQL 16 inspection target version",
            )
        _constant(value["toolName"], "pg_dump-pg_restore", f"{path}.toolName")
        if type(value["toolVersion"]) is not str or re.fullmatch(
            r"16\.\d+(?:\.\d+)?", value["toolVersion"]
        ) is None:
            _fail(f"{path}.toolVersion", "must be an exact supported pg_dump/pg_restore 16 version")
        if type(value["inspectionToolVersion"]) is not str or re.fullmatch(
            r"16\.\d+(?:\.\d+)?", value["inspectionToolVersion"]
        ) is None:
            _fail(
                f"{path}.inspectionToolVersion",
                "must be an exact supported pg_restore 16 inspection tool version",
            )
        _constant(value["format"], "postgresql_custom_archive", f"{path}.format")
        _constant(value["formatVersion"], "pg_dump-custom-v1", f"{path}.formatVersion")
        _constant(
            value["schemaDigestAlgorithm"],
            "sha256-canonical-postgresql-schema-v1",
            f"{path}.schemaDigestAlgorithm",
        )
        backend = "postgresql"
    _constant(
        value["rowsetDigestAlgorithm"],
        "sha256-canonical-typed-rowset-v1",
        f"{path}.rowsetDigestAlgorithm",
    )
    return backend


def _validate_tables(value: Any, path: str) -> list[dict[str, Any]]:
    tables = _array(value, path)
    parsed: list[dict[str, Any]] = []
    for index, raw in enumerate(tables):
        row_path = f"{path}[{index}]"
        row = _object(raw, row_path, {"tableName", "columnNames", "rowCount", "rowsetSha256"})
        _stable_id(row["tableName"], f"{row_path}.tableName")
        columns = _array(row["columnNames"], f"{row_path}.columnNames")
        for col_index, column in enumerate(columns):
            _stable_id(column, f"{row_path}.columnNames[{col_index}]")
        if columns != sorted(columns) or len(columns) != len(set(columns)):
            _fail(f"{row_path}.columnNames", "must be sorted and unique")
        _count(row["rowCount"], f"{row_path}.rowCount")
        _sha256(row["rowsetSha256"], f"{row_path}.rowsetSha256")
        parsed.append(row)
    _sorted_unique(parsed, path=path, key=lambda item: item["tableName"])
    if tuple(item["tableName"] for item in parsed) != _HEAD_TABLES:
        _fail(path, "must retain the exact reviewed Alembic-head table denominator")
    return parsed


def _validate_authority(value: Any, path: str = "$.authority") -> None:
    authority = _object(
        value,
        path,
        {
            "classification",
            "certifiesSources",
            "authorizesCapture",
            "authorizesPublication",
            "frontendLoadable",
            "authorizesCutover",
            "provesProviderIndependence",
            "provesProductionRpoRto",
        },
    )
    _constant(authority["classification"], "recovery_evidence_only", f"{path}.classification")
    for field in authority.keys() - {"classification"}:
        _constant(authority[field], False, f"{path}.{field}")


def _verify_self_digest(payload: dict[str, Any]) -> None:
    declared = payload["manifest"]["contentSha256"]
    actual = recovery_contract_digest(payload)
    if declared != actual:
        _fail(
            "$.manifest.contentSha256",
            f"self-digest mismatch (declared {declared}, computed {actual})",
        )


def derive_checkpoint_id(
    *,
    cycle_id: str,
    cycle_sha256: str,
    cycle_set_sha256: str,
    table_inventory_sha256: str,
    object_set_sha256: str,
) -> str:
    material = {
        "identityKind": "recovery-checkpoint-v1",
        "cycleId": cycle_id,
        "cycleSha256": cycle_sha256,
        "cycleSetSha256": cycle_set_sha256,
        "tableInventorySha256": table_inventory_sha256,
        "objectSetSha256": object_set_sha256,
    }
    return "recovery-checkpoint_" + hashlib.sha256(
        canonical_recovery_json(material).encode("ascii")
    ).hexdigest()


def validate_checkpoint_manifest(payload: Mapping[str, Any]) -> None:
    """Validate one immutable per-cycle checkpoint/object manifest."""

    _walk_json(payload)
    root = _object(
        payload,
        "$",
        {
            "schemaVersion",
            "policyVersion",
            "availability",
            "mode",
            "checkpointId",
            "createdAt",
            "triggerCycle",
            "cycleInventory",
            "relationalBackup",
            "objectManifest",
            "failureDomains",
            "recoveryObjective",
            "authority",
            "manifest",
        },
    )
    _constant(root["schemaVersion"], "1.0.0", "$.schemaVersion")
    _constant(root["policyVersion"], "recovery-checkpoint-v1", "$.policyVersion")
    _constant(root["availability"], "recovery_evidence_only", "$.availability")
    mode = _enum(root["mode"], {"synthetic_fixture", "shadow", "production"}, "$.mode")
    if type(root["checkpointId"]) is not str or _CHECKPOINT_ID.fullmatch(root["checkpointId"]) is None:
        _fail("$.checkpointId", "must be a deterministic recovery checkpoint ID")
    created_at = _utc(root["createdAt"], "$.createdAt")

    trigger = _object(
        root["triggerCycle"],
        "$.triggerCycle",
        {
            "cycleId",
            "manifest",
            "environment",
            "lane",
            "schedulePolicyRevisionId",
            "scheduledFor",
            "nextScheduledFor",
            "state",
            "mode",
        },
    )
    _stable_id(trigger["cycleId"], "$.triggerCycle.cycleId")
    trigger_manifest = _object(
        trigger["manifest"],
        "$.triggerCycle.manifest",
        {"contentSha256"},
    )
    trigger_sha = _sha256(
        trigger_manifest["contentSha256"],
        "$.triggerCycle.manifest.contentSha256",
    )
    _stable_id(trigger["environment"], "$.triggerCycle.environment")
    _enum(trigger["lane"], {"discovery", "recheck", "maintenance"}, "$.triggerCycle.lane")
    _stable_id(trigger["schedulePolicyRevisionId"], "$.triggerCycle.schedulePolicyRevisionId")
    scheduled = _utc(trigger["scheduledFor"], "$.triggerCycle.scheduledFor")
    next_scheduled = _utc(trigger["nextScheduledFor"], "$.triggerCycle.nextScheduledFor")
    if next_scheduled <= scheduled:
        _fail("$.triggerCycle.nextScheduledFor", "must be after the trigger slot")
    if created_at < scheduled:
        _fail("$.createdAt", "cannot precede the completed trigger cycle")
    _constant(trigger["state"], "terminal", "$.triggerCycle.state")
    _constant(trigger["mode"], mode, "$.triggerCycle.mode")

    cycle_inventory = _object(
        root["cycleInventory"],
        "$.cycleInventory",
        {"completedCycleCount", "cycleSetSha256", "cycles", "watermarks"},
    )
    completed_count = _count(
        cycle_inventory["completedCycleCount"], "$.cycleInventory.completedCycleCount"
    )
    if completed_count < 1:
        _fail("$.cycleInventory.completedCycleCount", "must include the trigger cycle")
    cycle_set_sha = _sha256(cycle_inventory["cycleSetSha256"], "$.cycleInventory.cycleSetSha256")
    cycles = _array(cycle_inventory["cycles"], "$.cycleInventory.cycles")
    parsed_cycles: list[dict[str, Any]] = []
    for index, raw in enumerate(cycles):
        path = f"$.cycleInventory.cycles[{index}]"
        row = _object(
            raw,
            path,
            {
                "environment",
                "lane",
                "cycleId",
                "scheduledFor",
                "schedulePolicyRevisionId",
                "contentSha256",
            },
        )
        _stable_id(row["environment"], f"{path}.environment")
        _enum(row["lane"], {"discovery", "recheck", "maintenance"}, f"{path}.lane")
        _stable_id(row["cycleId"], f"{path}.cycleId")
        _utc(row["scheduledFor"], f"{path}.scheduledFor")
        _stable_id(row["schedulePolicyRevisionId"], f"{path}.schedulePolicyRevisionId")
        _sha256(row["contentSha256"], f"{path}.contentSha256")
        parsed_cycles.append(row)
    _sorted_unique(
        parsed_cycles,
        path="$.cycleInventory.cycles",
        key=lambda item: (
            item["environment"],
            item["lane"],
            item["scheduledFor"],
            item["cycleId"],
        ),
    )
    _constant(completed_count, len(parsed_cycles), "$.cycleInventory.completedCycleCount")
    _constant(
        cycle_set_sha,
        recovery_cycle_set_digest(parsed_cycles),
        "$.cycleInventory.cycleSetSha256",
    )
    watermarks = _array(cycle_inventory["watermarks"], "$.cycleInventory.watermarks")
    parsed_watermarks: list[dict[str, Any]] = []
    for index, raw in enumerate(watermarks):
        path = f"$.cycleInventory.watermarks[{index}]"
        row = _object(
            raw,
            path,
            {
                "environment",
                "lane",
                "completedCycleCount",
                "earliestScheduledFor",
                "earliestCycleId",
                "latestScheduledFor",
                "latestCycleId",
                "latestCycleContentSha256",
                "cycleSetSha256",
            },
        )
        _stable_id(row["environment"], f"{path}.environment")
        _enum(row["lane"], {"discovery", "recheck", "maintenance"}, f"{path}.lane")
        if _count(row["completedCycleCount"], f"{path}.completedCycleCount") < 1:
            _fail(f"{path}.completedCycleCount", "watermark group cannot be empty")
        earliest = _utc(row["earliestScheduledFor"], f"{path}.earliestScheduledFor")
        latest = _utc(row["latestScheduledFor"], f"{path}.latestScheduledFor")
        if earliest > latest:
            _fail(path, "earliest watermark cannot follow latest watermark")
        _stable_id(row["earliestCycleId"], f"{path}.earliestCycleId")
        _stable_id(row["latestCycleId"], f"{path}.latestCycleId")
        _sha256(row["latestCycleContentSha256"], f"{path}.latestCycleContentSha256")
        _sha256(row["cycleSetSha256"], f"{path}.cycleSetSha256")
        parsed_watermarks.append(row)
    _sorted_unique(
        parsed_watermarks,
        path="$.cycleInventory.watermarks",
        key=lambda item: (item["environment"], item["lane"]),
    )
    _constant(
        completed_count,
        sum(item["completedCycleCount"] for item in parsed_watermarks),
        "$.cycleInventory.completedCycleCount",
    )
    grouped_cycles: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for cycle in parsed_cycles:
        grouped_cycles.setdefault((cycle["environment"], cycle["lane"]), []).append(cycle)
    if set(grouped_cycles) != {
        (item["environment"], item["lane"]) for item in parsed_watermarks
    }:
        _fail("$.cycleInventory.watermarks", "must account for every environment/lane cycle group")
    for watermark in parsed_watermarks:
        group = grouped_cycles[(watermark["environment"], watermark["lane"])]
        first, last = group[0], group[-1]
        expected = {
            "completedCycleCount": len(group),
            "earliestScheduledFor": first["scheduledFor"],
            "earliestCycleId": first["cycleId"],
            "latestScheduledFor": last["scheduledFor"],
            "latestCycleId": last["cycleId"],
            "latestCycleContentSha256": last["contentSha256"],
            "cycleSetSha256": recovery_cycle_set_digest(group),
        }
        for field, expected_value in expected.items():
            _constant(
                watermark[field],
                expected_value,
                f"$.cycleInventory.watermarks.{watermark['environment']}.{watermark['lane']}.{field}",
            )
    trigger_matches = [
        item
        for item in parsed_cycles
        if item["cycleId"] == trigger["cycleId"]
        and item["contentSha256"] == trigger_sha
        and item["environment"] == trigger["environment"]
        and item["lane"] == trigger["lane"]
        and item["scheduledFor"] == trigger["scheduledFor"]
        and item["schedulePolicyRevisionId"] == trigger["schedulePolicyRevisionId"]
    ]
    if len(trigger_matches) != 1:
        _fail("$.triggerCycle", "must exactly re-resolve once in the backup cycle denominator")
    trigger_group = grouped_cycles[(trigger["environment"], trigger["lane"])]
    latest_time = max(item["scheduledFor"] for item in trigger_group)
    latest_rows = [item for item in trigger_group if item["scheduledFor"] == latest_time]
    if len(latest_rows) != 1 or latest_rows[0]["cycleId"] != trigger["cycleId"]:
        _fail("$.triggerCycle", "must be the unambiguous latest completed cycle for its lane")

    domains = _object(
        root["failureDomains"],
        "$.failureDomains",
        {"source", "recovery", "declaredDistinct", "independenceEvidence"},
    )
    source_domain = _stable_id(domains["source"], "$.failureDomains.source")
    recovery_domain = _stable_id(domains["recovery"], "$.failureDomains.recovery")
    if source_domain == recovery_domain:
        _fail("$.failureDomains", "source and recovery IDs must be declared distinct")
    _constant(domains["declaredDistinct"], True, "$.failureDomains.declaredDistinct")
    _constant(
        domains["independenceEvidence"],
        "external_evidence_required",
        "$.failureDomains.independenceEvidence",
    )

    relational = _object(
        root["relationalBackup"],
        "$.relationalBackup",
        {
            "artifactType",
            "artifactId",
            "driverId",
            "driverVersion",
            "engineName",
            "engineVersion",
            "inspectionEngineVersion",
            "toolName",
            "toolVersion",
            "inspectionToolVersion",
            "format",
            "formatVersion",
            "sourceDatabaseIdentitySha256",
            "schemaRevision",
            "schemaDigestAlgorithm",
            "rowsetDigestAlgorithm",
            "contentSha256",
            "byteLength",
            "schemaSha256",
            "tableInventorySha256",
            "tables",
            "integrity",
            "recoveryCopy",
        },
    )
    backend = _validate_relational_metadata(relational, "$.relationalBackup")
    _stable_id(relational["artifactId"], "$.relationalBackup.artifactId")
    _stable_id(relational["schemaRevision"], "$.relationalBackup.schemaRevision")
    _sha256(
        relational["sourceDatabaseIdentitySha256"],
        "$.relationalBackup.sourceDatabaseIdentitySha256",
    )
    relational_sha = _sha256(relational["contentSha256"], "$.relationalBackup.contentSha256")
    relational_length = _count(relational["byteLength"], "$.relationalBackup.byteLength")
    _sha256(relational["schemaSha256"], "$.relationalBackup.schemaSha256")
    table_inventory_sha = _sha256(
        relational["tableInventorySha256"], "$.relationalBackup.tableInventorySha256"
    )
    tables = _validate_tables(relational["tables"], "$.relationalBackup.tables")
    _constant(
        table_inventory_sha,
        recovery_table_inventory_digest(tables),
        "$.relationalBackup.tableInventorySha256",
    )
    _validate_integrity(
        relational["integrity"], "$.relationalBackup.integrity", backend=backend
    )
    relational_copy = _validate_copy(
        relational["recoveryCopy"],
        "$.relationalBackup.recoveryCopy",
        domain_id=recovery_domain,
        kind="artifact",
    )
    _constant(relational_copy["contentSha256"], relational_sha, "$.relationalBackup.recoveryCopy.contentSha256")
    _constant(relational_copy["byteLength"], relational_length, "$.relationalBackup.recoveryCopy.byteLength")

    object_manifest = _object(
        root["objectManifest"],
        "$.objectManifest",
        {
            "sourceSnapshotRowCount",
            "governedArtifactCount",
            "objectReferenceCount",
            "uniqueObjectCount",
            "objectSetSha256",
            "objects",
        },
    )
    snapshot_count = _count(
        object_manifest["sourceSnapshotRowCount"], "$.objectManifest.sourceSnapshotRowCount"
    )
    _constant(object_manifest["governedArtifactCount"], 0, "$.objectManifest.governedArtifactCount")
    reference_count = _count(
        object_manifest["objectReferenceCount"], "$.objectManifest.objectReferenceCount"
    )
    unique_count = _count(
        object_manifest["uniqueObjectCount"], "$.objectManifest.uniqueObjectCount"
    )
    object_set_sha = _sha256(object_manifest["objectSetSha256"], "$.objectManifest.objectSetSha256")
    objects = _array(object_manifest["objects"], "$.objectManifest.objects")
    parsed_objects: list[dict[str, Any]] = []
    unique_objects: set[tuple[str, str]] = set()
    for index, raw in enumerate(objects):
        path = f"$.objectManifest.objects[{index}]"
        row = _object(
            raw,
            path,
            {
                "referenceType",
                "referenceId",
                "sourceLogicalUri",
                "objectKind",
                "contentSha256",
                "byteLength",
                "recoveryCopy",
            },
        )
        _constant(row["referenceType"], "source_snapshot_raw", f"{path}.referenceType")
        _stable_id(row["referenceId"], f"{path}.referenceId")
        _safe_locator(row["sourceLogicalUri"], f"{path}.sourceLogicalUri")
        _constant(row["objectKind"], "snapshot", f"{path}.objectKind")
        digest = _sha256(row["contentSha256"], f"{path}.contentSha256")
        byte_length = _count(row["byteLength"], f"{path}.byteLength")
        copy = _validate_copy(
            row["recoveryCopy"], f"{path}.recoveryCopy", domain_id=recovery_domain, kind="snapshot"
        )
        _constant(copy["contentSha256"], digest, f"{path}.recoveryCopy.contentSha256")
        _constant(copy["byteLength"], byte_length, f"{path}.recoveryCopy.byteLength")
        unique_objects.add((copy["uri"], digest))
        parsed_objects.append(row)
    _sorted_unique(
        parsed_objects,
        path="$.objectManifest.objects",
        key=lambda item: (item["referenceType"], item["referenceId"]),
    )
    _constant(reference_count, len(parsed_objects), "$.objectManifest.objectReferenceCount")
    _constant(snapshot_count, reference_count, "$.objectManifest.sourceSnapshotRowCount")
    _constant(unique_count, len(unique_objects), "$.objectManifest.uniqueObjectCount")
    _constant(
        object_set_sha,
        recovery_object_set_digest(parsed_objects),
        "$.objectManifest.objectSetSha256",
    )

    objective = _object(
        root["recoveryObjective"],
        "$.recoveryObjective",
        {"maximumCompletedCyclesLost", "status", "productionClaim"},
    )
    _constant(objective["maximumCompletedCyclesLost"], 1, "$.recoveryObjective.maximumCompletedCyclesLost")
    _constant(objective["status"], "target_only_unproven", "$.recoveryObjective.status")
    _constant(objective["productionClaim"], False, "$.recoveryObjective.productionClaim")
    _validate_authority(root["authority"])

    manifest = _object(
        root["manifest"],
        "$.manifest",
        {
            "algorithm",
            "contentSha256",
            "tableCount",
            "objectReferenceCount",
        },
    )
    _constant(manifest["algorithm"], _ALGORITHM, "$.manifest.algorithm")
    _sha256(manifest["contentSha256"], "$.manifest.contentSha256")
    _constant(manifest["tableCount"], len(tables), "$.manifest.tableCount")
    _constant(manifest["objectReferenceCount"], reference_count, "$.manifest.objectReferenceCount")
    expected_checkpoint_id = derive_checkpoint_id(
        cycle_id=trigger["cycleId"],
        cycle_sha256=trigger_sha,
        cycle_set_sha256=cycle_set_sha,
        table_inventory_sha256=table_inventory_sha,
        object_set_sha256=object_set_sha,
    )
    _constant(root["checkpointId"], expected_checkpoint_id, "$.checkpointId")
    _verify_self_digest(root)


def derive_restore_receipt_id(
    *, checkpoint_id: str, checkpoint_sha256: str, target_id: str, object_set_sha256: str
) -> str:
    material = {
        "identityKind": "recovery-restore-receipt-v1",
        "checkpointId": checkpoint_id,
        "checkpointSha256": checkpoint_sha256,
        "targetId": target_id,
        "objectSetSha256": object_set_sha256,
    }
    return "recovery-restore_" + hashlib.sha256(
        canonical_recovery_json(material).encode("ascii")
    ).hexdigest()


def validate_restore_receipt(payload: Mapping[str, Any]) -> None:
    """Validate one successful fresh-target restore/recovery-map receipt."""

    _walk_json(payload)
    root = _object(
        payload,
        "$",
        {
            "schemaVersion",
            "policyVersion",
            "availability",
            "mode",
            "receiptId",
            "startedAt",
            "finishedAt",
            "durationMs",
            "checkpoint",
            "target",
            "failureDomains",
            "relationalRestore",
            "objectRestore",
            "recoveryAssessment",
            "authority",
            "manifest",
        },
    )
    _constant(root["schemaVersion"], "1.0.0", "$.schemaVersion")
    _constant(root["policyVersion"], "recovery-restore-receipt-v1", "$.policyVersion")
    _constant(root["availability"], "recovery_evidence_only", "$.availability")
    _enum(root["mode"], {"synthetic_fixture", "shadow", "production"}, "$.mode")
    if type(root["receiptId"]) is not str or _RESTORE_ID.fullmatch(root["receiptId"]) is None:
        _fail("$.receiptId", "must be a deterministic recovery restore ID")
    started = _utc(root["startedAt"], "$.startedAt")
    finished = _utc(root["finishedAt"], "$.finishedAt")
    if finished < started:
        _fail("$.finishedAt", "cannot precede restore start")
    duration = _count(root["durationMs"], "$.durationMs")
    _constant(duration, int((finished - started).total_seconds() * 1000), "$.durationMs")

    checkpoint = _object(
        root["checkpoint"],
        "$.checkpoint",
        {"checkpointId", "contentSha256", "triggerCycleId", "triggerCycleContentSha256"},
    )
    if type(checkpoint["checkpointId"]) is not str or _CHECKPOINT_ID.fullmatch(checkpoint["checkpointId"]) is None:
        _fail("$.checkpoint.checkpointId", "must be a checkpoint ID")
    checkpoint_sha = _sha256(checkpoint["contentSha256"], "$.checkpoint.contentSha256")
    _stable_id(checkpoint["triggerCycleId"], "$.checkpoint.triggerCycleId")
    _sha256(checkpoint["triggerCycleContentSha256"], "$.checkpoint.triggerCycleContentSha256")

    target = _object(
        root["target"],
        "$.target",
        {"targetId", "freshRelationalTarget", "recoveryMapOnly", "cutoverAuthorized"},
    )
    target_id = _stable_id(target["targetId"], "$.target.targetId")
    _constant(target["freshRelationalTarget"], True, "$.target.freshRelationalTarget")
    _constant(target["recoveryMapOnly"], True, "$.target.recoveryMapOnly")
    _constant(target["cutoverAuthorized"], False, "$.target.cutoverAuthorized")

    domains = _object(
        root["failureDomains"],
        "$.failureDomains",
        {"recovery", "restore", "declaredDistinct", "independenceEvidence"},
    )
    recovery_domain = _stable_id(domains["recovery"], "$.failureDomains.recovery")
    restore_domain = _stable_id(domains["restore"], "$.failureDomains.restore")
    if recovery_domain == restore_domain:
        _fail("$.failureDomains", "recovery and restore IDs must be distinct")
    _constant(domains["declaredDistinct"], True, "$.failureDomains.declaredDistinct")
    _constant(domains["independenceEvidence"], "external_evidence_required", "$.failureDomains.independenceEvidence")

    relational = _object(
        root["relationalRestore"],
        "$.relationalRestore",
        {
            "artifactType",
            "driverId",
            "driverVersion",
            "engineName",
            "engineVersion",
            "inspectionEngineVersion",
            "toolName",
            "toolVersion",
            "inspectionToolVersion",
            "format",
            "formatVersion",
            "sourceDatabaseIdentitySha256",
            "schemaRevision",
            "schemaDigestAlgorithm",
            "rowsetDigestAlgorithm",
            "sourceBackupContentSha256",
            "restoredContentSha256",
            "byteLength",
            "schemaSha256",
            "tableInventorySha256",
            "tables",
            "integrity",
            "matchesCheckpoint",
        },
    )
    backend = _validate_relational_metadata(relational, "$.relationalRestore")
    _stable_id(relational["schemaRevision"], "$.relationalRestore.schemaRevision")
    _sha256(
        relational["sourceDatabaseIdentitySha256"],
        "$.relationalRestore.sourceDatabaseIdentitySha256",
    )
    source_sha = _sha256(relational["sourceBackupContentSha256"], "$.relationalRestore.sourceBackupContentSha256")
    _constant(relational["restoredContentSha256"], source_sha, "$.relationalRestore.restoredContentSha256")
    _count(relational["byteLength"], "$.relationalRestore.byteLength")
    _sha256(relational["schemaSha256"], "$.relationalRestore.schemaSha256")
    _sha256(relational["tableInventorySha256"], "$.relationalRestore.tableInventorySha256")
    tables = _validate_tables(relational["tables"], "$.relationalRestore.tables")
    _constant(
        relational["tableInventorySha256"],
        recovery_table_inventory_digest(tables),
        "$.relationalRestore.tableInventorySha256",
    )
    _validate_integrity(
        relational["integrity"], "$.relationalRestore.integrity", backend=backend
    )
    _constant(relational["matchesCheckpoint"], True, "$.relationalRestore.matchesCheckpoint")

    object_restore = _object(
        root["objectRestore"],
        "$.objectRestore",
        {
            "objectReferenceCount",
            "uniqueObjectCount",
            "objectSetSha256",
            "objects",
            "allVerified",
        },
    )
    reference_count = _count(object_restore["objectReferenceCount"], "$.objectRestore.objectReferenceCount")
    unique_count = _count(object_restore["uniqueObjectCount"], "$.objectRestore.uniqueObjectCount")
    object_set_sha = _sha256(object_restore["objectSetSha256"], "$.objectRestore.objectSetSha256")
    restored_objects = _array(object_restore["objects"], "$.objectRestore.objects")
    parsed_objects: list[dict[str, Any]] = []
    unique_restored: set[tuple[str, str]] = set()
    for index, raw in enumerate(restored_objects):
        path = f"$.objectRestore.objects[{index}]"
        row = _object(
            raw,
            path,
            {
                "referenceType",
                "referenceId",
                "sourceLogicalUri",
                "contentSha256",
                "byteLength",
                "recoveryCopyUri",
                "restoredCopy",
            },
        )
        _constant(row["referenceType"], "source_snapshot_raw", f"{path}.referenceType")
        _stable_id(row["referenceId"], f"{path}.referenceId")
        _safe_locator(row["sourceLogicalUri"], f"{path}.sourceLogicalUri")
        _safe_locator(row["recoveryCopyUri"], f"{path}.recoveryCopyUri")
        digest = _sha256(row["contentSha256"], f"{path}.contentSha256")
        byte_length = _count(row["byteLength"], f"{path}.byteLength")
        copy = _validate_copy(
            row["restoredCopy"], f"{path}.restoredCopy", domain_id=restore_domain, kind="snapshot"
        )
        _constant(copy["contentSha256"], digest, f"{path}.restoredCopy.contentSha256")
        _constant(copy["byteLength"], byte_length, f"{path}.restoredCopy.byteLength")
        unique_restored.add((copy["uri"], digest))
        parsed_objects.append(row)
    _sorted_unique(
        parsed_objects,
        path="$.objectRestore.objects",
        key=lambda item: (item["referenceType"], item["referenceId"]),
    )
    _constant(reference_count, len(parsed_objects), "$.objectRestore.objectReferenceCount")
    _constant(unique_count, len(unique_restored), "$.objectRestore.uniqueObjectCount")
    _constant(object_restore["allVerified"], True, "$.objectRestore.allVerified")
    _constant(
        object_set_sha,
        recovery_object_set_digest(parsed_objects),
        "$.objectRestore.objectSetSha256",
    )

    assessment = _object(
        root["recoveryAssessment"],
        "$.recoveryAssessment",
        {
            "maximumCompletedCyclesLostTarget",
            "rpoStatus",
            "rtoStatus",
            "providerIndependenceStatus",
            "runtimeLocatorCutoverStatus",
        },
    )
    _constant(assessment["maximumCompletedCyclesLostTarget"], 1, "$.recoveryAssessment.maximumCompletedCyclesLostTarget")
    _constant(assessment["rpoStatus"], "target_not_proven", "$.recoveryAssessment.rpoStatus")
    _constant(assessment["rtoStatus"], "target_not_proven", "$.recoveryAssessment.rtoStatus")
    _constant(assessment["providerIndependenceStatus"], "external_evidence_required", "$.recoveryAssessment.providerIndependenceStatus")
    _constant(assessment["runtimeLocatorCutoverStatus"], "not_authorized", "$.recoveryAssessment.runtimeLocatorCutoverStatus")
    _validate_authority(root["authority"])

    manifest = _object(
        root["manifest"],
        "$.manifest",
        {"algorithm", "contentSha256", "tableCount", "objectReferenceCount"},
    )
    _constant(manifest["algorithm"], _ALGORITHM, "$.manifest.algorithm")
    _sha256(manifest["contentSha256"], "$.manifest.contentSha256")
    _constant(manifest["tableCount"], len(tables), "$.manifest.tableCount")
    _constant(manifest["objectReferenceCount"], reference_count, "$.manifest.objectReferenceCount")

    expected_receipt_id = derive_restore_receipt_id(
        checkpoint_id=checkpoint["checkpointId"],
        checkpoint_sha256=checkpoint_sha,
        target_id=target_id,
        object_set_sha256=object_set_sha,
    )
    _constant(root["receiptId"], expected_receipt_id, "$.receiptId")
    _verify_self_digest(root)


__all__ = [
    "RecoveryContractError",
    "canonical_recovery_json",
    "derive_checkpoint_id",
    "derive_restore_receipt_id",
    "parse_canonical_recovery_bytes",
    "recovery_contract_digest",
    "recovery_cycle_set_digest",
    "recovery_object_set_digest",
    "recovery_table_inventory_digest",
    "validate_checkpoint_manifest",
    "validate_restore_receipt",
]
