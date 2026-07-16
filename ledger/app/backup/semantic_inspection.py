"""Dialect-neutral semantic inventory and lineage algorithms for DATA-10.

Drivers supply query results as ordinary row mappings after restoring or
staging their physical archive.  This module owns the one declared typed-row
normalization algorithm, exact application-table denominator, decision/event
lineage audit, terminal-cycle inventory, and external-object enumeration.
Backend-specific catalog/integrity proof remains the driver's responsibility.
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
from datetime import date, datetime, timezone
from typing import Any, Mapping, Sequence

from sqlalchemy import Boolean, Date, DateTime, Float, Integer, JSON, String

from app.db.models import Base
from app.schemas.operations_contracts import OperationsContractError, validate_scheduled_cycle
from app.schemas.recovery_contracts import canonical_recovery_json, recovery_table_inventory_digest

from .errors import RecoveryIntegrityError, UnsupportedRecoveryArtifact
from .protocols import (
    CycleInventoryEntry,
    LineageFamilyResult,
    ReferencedObject,
    TableInventoryEntry,
)


ROWSET_DIGEST_ALGORITHM = "sha256-canonical-typed-rowset-v1"
LINEAGE_TABLES = (
    "claim_publication_decisions",
    "claim_review_decisions",
    "identity_decisions",
    "notification_receipts",
    "ops_incident_events",
    "review_work_item_events",
    "source_revision_decisions",
)


def expected_head_columns() -> dict[str, tuple[str, ...]]:
    expected = {
        str(table.name): tuple(sorted(str(column.name) for column in table.columns))
        for table in Base.metadata.tables.values()
    }
    expected["alembic_version"] = ("version_num",)
    return expected


def _json_value(value: Any, *, label: str) -> Any:
    if isinstance(value, (str, bytes, bytearray)):
        try:
            return json.loads(value)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RecoveryIntegrityError(f"{label} contains invalid JSON.") from exc
    if value is None or type(value) in (dict, list, str, bool, int, float):
        return value
    raise RecoveryIntegrityError(f"{label} contains an unsupported JSON representation.")


def _typed_json(value: Any, *, label: str) -> dict[str, Any]:
    if value is None:
        return {"type": "null"}
    if type(value) is bool:
        return {"type": "boolean", "value": value}
    if type(value) is int:
        return {"type": "integer", "value": str(value)}
    if type(value) is float:
        if not math.isfinite(value):
            raise RecoveryIntegrityError(f"{label} contains a non-finite JSON number.")
        return {"type": "real", "value": value.hex()}
    if type(value) is str:
        return {"type": "string", "value": value}
    if type(value) is list:
        return {
            "type": "array",
            "value": [
                _typed_json(item, label=f"{label}[{index}]")
                for index, item in enumerate(value)
            ],
        }
    if type(value) is dict:
        if any(type(key) is not str for key in value):
            raise RecoveryIntegrityError(f"{label} contains a non-string JSON key.")
        return {
            "type": "object",
            "value": [
                {"key": key, "value": _typed_json(value[key], label=f"{label}.{key}")}
                for key in sorted(value)
            ],
        }
    raise RecoveryIntegrityError(f"{label} contains an unsupported JSON type.")


def normalize_datetime(value: Any, *, label: str) -> str:
    if isinstance(value, datetime):
        parsed = value
    elif type(value) is str:
        candidate = value.strip().replace(" ", "T")
        if candidate.endswith("Z"):
            candidate = candidate[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError as exc:
            raise RecoveryIntegrityError(f"{label} contains an invalid datetime.") from exc
    else:
        raise RecoveryIntegrityError(f"{label} contains an unsupported datetime value.")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _normalize_date(value: Any, *, label: str) -> str:
    if isinstance(value, datetime):
        parsed = value.date()
    elif isinstance(value, date):
        parsed = value
    elif type(value) is str:
        try:
            parsed = date.fromisoformat(value)
        except ValueError as exc:
            raise RecoveryIntegrityError(f"{label} contains an invalid date.") from exc
    else:
        raise RecoveryIntegrityError(f"{label} contains an unsupported date value.")
    return parsed.isoformat()


def canonical_typed_value(value: Any, column: Any, *, label: str) -> dict[str, Any]:
    """Normalize one SQL value using the reviewed ORM semantic column type."""

    column_type = column.type
    if value is None:
        return {"semanticType": "null", "value": None}
    if isinstance(column_type, JSON):
        return {
            "semanticType": "json",
            "value": _typed_json(_json_value(value, label=label), label=label),
        }
    if isinstance(column_type, DateTime):
        return {"semanticType": "datetime_utc", "value": normalize_datetime(value, label=label)}
    if isinstance(column_type, Date):
        return {"semanticType": "date", "value": _normalize_date(value, label=label)}
    if isinstance(column_type, Boolean):
        if type(value) is bool:
            normalized = value
        elif type(value) is int and value in {0, 1}:
            normalized = bool(value)
        else:
            raise RecoveryIntegrityError(f"{label} contains a noncanonical boolean.")
        return {"semanticType": "boolean", "value": normalized}
    if isinstance(column_type, Integer):
        if type(value) is not int:
            raise RecoveryIntegrityError(f"{label} contains a non-integer value.")
        return {"semanticType": "integer", "value": str(value)}
    if isinstance(column_type, Float):
        if type(value) not in {int, float}:
            raise RecoveryIntegrityError(f"{label} contains a nonnumeric real value.")
        numeric = float(value)
        if not math.isfinite(numeric):
            raise RecoveryIntegrityError(f"{label} contains a non-finite real value.")
        return {"semanticType": "real", "value": numeric.hex()}
    if isinstance(column_type, String):
        if type(value) is not str:
            raise RecoveryIntegrityError(f"{label} contains a non-text value.")
        return {"semanticType": "text", "value": value}
    if type(value) is bytes:
        return {
            "semanticType": "bytes",
            "value": base64.b64encode(value).decode("ascii"),
        }
    raise RecoveryIntegrityError(f"{label} uses an unsupported relational value type.")


def build_table_inventory(
    rows_by_table: Mapping[str, Sequence[Mapping[str, Any]]],
) -> tuple[TableInventoryEntry, ...]:
    """Hash every expected table without PK/order assumptions.

    Canonical row encodings are sorted before hashing, so database result order
    is irrelevant while duplicate row multiplicity is preserved.
    """

    expected = expected_head_columns()
    if set(rows_by_table) != set(expected):
        raise RecoveryIntegrityError("Semantic table rows have a missing or extra table.")
    models = {str(table.name): table for table in Base.metadata.tables.values()}
    inventory: list[TableInventoryEntry] = []
    for table_name in sorted(expected):
        columns = expected[table_name]
        encoded_rows: list[str] = []
        for row_index, row in enumerate(rows_by_table[table_name]):
            if set(row) != set(columns):
                raise RecoveryIntegrityError(f"{table_name} row has missing or extra columns.")
            encoded: list[dict[str, Any]] = []
            for column_name in columns:
                if table_name == "alembic_version":
                    if type(row[column_name]) is not str:
                        raise RecoveryIntegrityError("alembic_version is not text.")
                    typed = {"semanticType": "text", "value": row[column_name]}
                else:
                    typed = canonical_typed_value(
                        row[column_name],
                        models[table_name].columns[column_name],
                        label=f"{table_name}.{column_name}[{row_index}]",
                    )
                encoded.append({"column": column_name, **typed})
            encoded_rows.append(canonical_recovery_json(encoded))
        encoded_rows.sort()
        digest = hashlib.sha256(
            ("[" + ",".join(encoded_rows) + "]").encode("ascii")
        ).hexdigest()
        inventory.append(
            TableInventoryEntry(table_name, columns, len(encoded_rows), digest)
        )
    return tuple(inventory)


def table_inventory_documents(
    tables: Sequence[TableInventoryEntry],
) -> list[dict[str, Any]]:
    return [
        {
            "tableName": str(item.table_name),
            "columnNames": [str(name) for name in item.column_names],
            "rowCount": item.row_count,
            "rowsetSha256": item.rowset_sha256,
        }
        for item in tables
    ]


def table_inventory_digest(tables: Sequence[TableInventoryEntry]) -> str:
    return recovery_table_inventory_digest(table_inventory_documents(tables))


def _as_datetime(value: Any, *, label: str) -> datetime:
    return datetime.strptime(
        normalize_datetime(value, label=label), "%Y-%m-%dT%H:%M:%S.%fZ"
    ).replace(tzinfo=timezone.utc)


def _linear(
    raw_rows: Sequence[Mapping[str, Any]],
    *,
    family: str,
    id_field: str,
    parent_field: str,
    entity_fields: tuple[str, ...],
    root_group_fields: tuple[str, ...] | None = None,
    sequence_field: str | None = None,
    time_field: str | None = None,
    strict_time: bool = False,
    state_fields: tuple[str, str] | None = None,
    allow_multiple_roots: bool = False,
) -> LineageFamilyResult:
    rows = [dict(row) for row in raw_rows]
    by_id: dict[str, dict[str, Any]] = {}
    children: dict[str, list[str]] = {}
    for row in rows:
        identity = row[id_field]
        if type(identity) is not str or not identity or identity in by_id:
            raise RecoveryIntegrityError(f"{family} contains a duplicate/invalid identity.")
        by_id[identity] = row
        children[identity] = []
    for row in rows:
        identity = row[id_field]
        parent_id = row[parent_field]
        if parent_id is None:
            if sequence_field and row[sequence_field] != 1:
                raise RecoveryIntegrityError(f"{family} root sequence is invalid.")
            if state_fields and row[state_fields[0]] is not None:
                raise RecoveryIntegrityError(f"{family} root prior state is not null.")
            continue
        parent = by_id.get(parent_id) if type(parent_id) is str else None
        if parent is None or parent_id == identity:
            raise RecoveryIntegrityError(f"{family} has a missing/self predecessor.")
        if any(row[field] != parent[field] for field in entity_fields):
            raise RecoveryIntegrityError(f"{family} predecessor crosses an entity root.")
        children[parent_id].append(identity)
        if len(children[parent_id]) > 1:
            raise RecoveryIntegrityError(f"{family} predecessor branches.")
        if sequence_field and row[sequence_field] != parent[sequence_field] + 1:
            raise RecoveryIntegrityError(f"{family} sequence is not contiguous.")
        if state_fields and row[state_fields[0]] != parent[state_fields[1]]:
            raise RecoveryIntegrityError(f"{family} state lineage does not join.")
        if time_field and row[time_field] is not None and parent[time_field] is not None:
            child_time = _as_datetime(row[time_field], label=f"{family}.{time_field}")
            parent_time = _as_datetime(parent[time_field], label=f"{family}.{time_field}")
            if child_time < parent_time or (strict_time and child_time == parent_time):
                raise RecoveryIntegrityError(f"{family} chronology is invalid.")
    roots = [row for row in rows if row[parent_field] is None]
    leaves = [row for row in rows if not children[row[id_field]]]
    group_fields = root_group_fields or entity_fields
    if rows and not allow_multiple_roots:
        entities = {tuple(row[field] for field in group_fields) for row in rows}
        root_entities = [tuple(row[field] for field in group_fields) for row in roots]
        leaf_entities = [tuple(row[field] for field in group_fields) for row in leaves]
        if len(root_entities) != len(set(root_entities)) or set(root_entities) != entities:
            raise RecoveryIntegrityError(f"{family} has multiple/missing roots.")
        if len(leaf_entities) != len(set(leaf_entities)) or set(leaf_entities) != entities:
            raise RecoveryIntegrityError(f"{family} has multiple/missing effective leaves.")
    elif allow_multiple_roots and len(roots) != len(leaves):
        raise RecoveryIntegrityError(f"{family} recovery chains have multiple leaves.")
    for identity in by_id:
        seen: set[str] = set()
        current: str | None = identity
        while current is not None:
            if current in seen:
                raise RecoveryIntegrityError(f"{family} contains a predecessor cycle.")
            seen.add(current)
            current = by_id[current][parent_field]
    return LineageFamilyResult(family, len(roots), len(leaves), len(rows))


def audit_semantic_lineages(
    rows_by_table: Mapping[str, Sequence[Mapping[str, Any]]],
) -> tuple[LineageFamilyResult, ...]:
    required = set(LINEAGE_TABLES) | {"notification_intents"}
    if not required.issubset(rows_by_table):
        raise RecoveryIntegrityError("Semantic lineage input omits a required family table.")
    review_rows = rows_by_table["claim_review_decisions"]
    publication_rows = rows_by_table["claim_publication_decisions"]
    reviews = {row["id"]: row for row in review_rows}
    for publication in publication_rows:
        review = reviews.get(publication["claim_review_decision_id"])
        if review is None or review["result_claim_id"] != publication["result_claim_id"]:
            raise RecoveryIntegrityError("Publication references another/missing claim review.")
        if publication["decided_at"] is not None and review["decided_at"] is not None:
            if _as_datetime(publication["decided_at"], label="publication.decided_at") < _as_datetime(
                review["decided_at"], label="review.decided_at"
            ):
                raise RecoveryIntegrityError("Publication predates its review evidence.")
    notification_rows = rows_by_table["notification_receipts"]
    intents = {row["intent_id"]: row for row in rows_by_table["notification_intents"]}
    receipts = {row["receipt_id"]: row for row in notification_rows}
    for receipt in notification_rows:
        intent = intents.get(receipt["intent_id"])
        if intent is None or intent["incident_id"] != receipt["incident_id"] or intent["route_id"] != receipt["route_id"]:
            raise RecoveryIntegrityError("Notification receipt references another/missing intent.")
        prior_id = receipt["prior_receipt_id"]
        if prior_id is not None:
            prior = receipts.get(prior_id)
            if prior is None or prior["intent_id"] == receipt["intent_id"] or receipt["outcome"] != "recovery_delivered":
                raise RecoveryIntegrityError("Notification recovery predecessor is invalid.")
    results = [
        _linear(rows_by_table["source_revision_decisions"], family="source_revision_decisions", id_field="id", parent_field="supersedes_decision_id", entity_fields=("source_revision_id",), time_field="decided_at"),
        _linear(review_rows, family="claim_review_decisions", id_field="id", parent_field="supersedes_decision_id", entity_fields=("result_claim_id",), time_field="decided_at"),
        _linear(publication_rows, family="claim_publication_decisions", id_field="id", parent_field="supersedes_decision_id", entity_fields=("result_claim_id",), time_field="decided_at"),
        _linear(rows_by_table["identity_decisions"], family="identity_decisions", id_field="decision_id", parent_field="expected_prior_decision_id", entity_fields=("candidate_reference", "observation_reference", "identity_item_fingerprint_sha256"), root_group_fields=("candidate_reference",), sequence_field="decision_sequence", time_field="decided_at", strict_time=True),
        _linear(rows_by_table["ops_incident_events"], family="ops_incident_events", id_field="event_id", parent_field="expected_prior_event_id", entity_fields=("incident_id",), sequence_field="event_ordinal", time_field="occurred_at", state_fields=("from_state", "to_state")),
        _linear(rows_by_table["review_work_item_events"], family="review_work_item_events", id_field="event_id", parent_field="expected_prior_event_id", entity_fields=("work_item_id",), sequence_field="event_ordinal", time_field="occurred_at", state_fields=("from_state", "to_state")),
        _linear(notification_rows, family="notification_receipts", id_field="receipt_id", parent_field="prior_receipt_id", entity_fields=("incident_id", "route_id"), time_field="finished_at", allow_multiple_roots=True),
    ]
    results.sort(key=lambda item: item.family)
    if tuple(item.family for item in results) != LINEAGE_TABLES:
        raise RecoveryIntegrityError("Semantic lineage denominator is incomplete.")
    return tuple(results)


def build_cycle_inventory(
    raw_rows: Sequence[Mapping[str, Any]],
) -> tuple[tuple[CycleInventoryEntry, ...], tuple[dict[str, object], ...]]:
    entries: list[CycleInventoryEntry] = []
    payloads: list[dict[str, object]] = []
    for raw in raw_rows:
        row = dict(raw)
        document = _json_value(row["payload_json"], label="scheduled_cycles.payload_json")
        if type(document) is not dict:
            raise RecoveryIntegrityError("Scheduled cycle payload is not an object.")
        try:
            validate_scheduled_cycle(document)
        except OperationsContractError as exc:
            raise RecoveryIntegrityError("Stored terminal cycle payload is invalid.") from exc
        scheduled = normalize_datetime(row["scheduled_for"], label="scheduled_cycles.scheduled_for").replace(".000000Z", "Z")
        exact = (
            row["cycle_id"], row["environment"], row["lane"], scheduled,
            row["schedule_policy_revision_id"], row["mode"], row["content_sha256"],
        )
        expected = (
            document["cycleId"], document["environment"], document["lane"], document["slot"]["scheduledFor"],
            document["schedulePolicyRevisionId"], document["mode"], document["manifest"]["contentSha256"],
        )
        if exact != expected:
            raise RecoveryIntegrityError("Scheduled cycle columns do not bind their payload.")
        entries.append(CycleInventoryEntry(row["environment"], row["lane"], row["cycle_id"], scheduled, row["schedule_policy_revision_id"], row["content_sha256"]))
        payloads.append(document)
    paired = sorted(zip(entries, payloads, strict=True), key=lambda pair: (pair[0].environment, pair[0].lane, pair[0].scheduled_for, pair[0].cycle_id))
    return tuple(pair[0] for pair in paired), tuple(pair[1] for pair in paired)


def enumerate_referenced_objects(
    raw_rows: Sequence[Mapping[str, Any]],
) -> tuple[ReferencedObject, ...]:
    references: list[ReferencedObject] = []
    seen: set[str] = set()
    for raw in raw_rows:
        row = dict(raw)
        if row["rendered_screenshot_uri"] is not None:
            raise UnsupportedRecoveryArtifact("rendered_screenshot_uri lacks a typed digest referent.")
        identity, uri, digest = row["id"], row["raw_content_uri"], row["content_hash"]
        if type(identity) is not str or not identity or identity in seen or type(uri) is not str or not uri or type(digest) is not str or len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise RecoveryIntegrityError("Source snapshot object reference is malformed.")
        seen.add(identity)
        references.append(ReferencedObject("source_snapshot_raw", identity, uri, "snapshot", digest))
    references.sort(key=lambda item: (item.reference_type, item.reference_id))
    return tuple(references)


__all__ = [
    "LINEAGE_TABLES",
    "ROWSET_DIGEST_ALGORITHM",
    "audit_semantic_lineages",
    "build_cycle_inventory",
    "build_table_inventory",
    "canonical_typed_value",
    "enumerate_referenced_objects",
    "expected_head_columns",
    "normalize_datetime",
    "table_inventory_digest",
    "table_inventory_documents",
]
