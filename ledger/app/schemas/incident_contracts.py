"""Pure semantic validators for incident, review, and notification contracts.

These helpers intentionally perform no I/O and grant no operational authority.
They validate immutable projections and append-only event chains using only the
Python standard library.  Source-controlled text is not part of any durable
payload: all operator context is expressed through typed IDs and stable codes.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import re
from typing import Any


class IncidentContractError(ValueError):
    """Raised when an incident/notification contract fails closed."""


_ALGORITHM = "sha256-canonical-incident-json-v1"
_STABLE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_REASON = re.compile(r"^[A-Z][A-Z0-9_]{2,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_TAG_VALUE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")

_INCIDENT_CODES = {
    "DISCOVERY": {"NEW_CANDIDATE", "CANDIDATE_DRIFT", "ORIGIN_UNREACHABLE", "DUPLICATE"},
    "SOURCE_POLICY": {
        "TERMS_UNKNOWN", "TERMS_CHANGED", "PERMISSION_REQUIRED", "CERT_EXPIRED",
        "REVISION_UNCERTIFIED",
    },
    "FETCH": {
        "TRANSPORT_UNAVAILABLE", "TRANSIENT", "RATE_LIMITED", "POLICY_BLOCK",
        "CONTENT_MISMATCH", "UNSAFE_REDIRECT",
    },
    "SNAPSHOT": {"WRITE_FAILED", "HASH_MISMATCH", "OBJECT_MISSING"},
    "STORAGE": {"WRITE_FAILED", "HASH_MISMATCH", "OBJECT_MISSING", "RETENTION_VIOLATION", "ORPHAN_DETECTED"},
    "SCHEMA": {"SCHEMA_DRIFT", "CONTRACT_MISMATCH"},
    "EVIDENCE": {"LOCATOR_UNRESOLVABLE", "RAW_VALUE_MISMATCH", "CONTRACT_MISMATCH"},
    "VALIDATION": {"CLAIM_REJECTED", "NO_PASS", "NONFINITE_SCORE", "DIMENSION_UNAPPROVED"},
    "IDENTITY": {"MODEL_UNRESOLVED", "MODEL_AMBIGUOUS", "BENCHMARK_UNRESOLVED", "SYSTEM_COMPOSITION_UNKNOWN"},
    "CONFLICT": {"DISPLAY_CELL_DUPLICATE", "DECISION_CHAIN_AMBIGUOUS", "FINGERPRINT_COLLISION"},
    "SCHEDULER": {"DISPATCH_MISSED", "LEASE_LOST", "DUPLICATE_DELIVERY", "QUEUE_BACKLOG", "WATCHDOG_MISSING_RECEIPT"},
    "DATABASE": {"UNAVAILABLE", "CONSTRAINT_FAILED", "MIGRATION_FAILED", "RESTORE_FAILED"},
    "ARTIFACT": {"BUILD_FAILED", "DIGEST_MISMATCH", "UNAUTHORIZED", "REVOCATION_FAILED", "WITHDRAWAL_FAILED"},
    "PUBLICATION": {"BUILD_FAILED", "DIGEST_MISMATCH", "UNAUTHORIZED", "REVOCATION_FAILED", "WITHDRAWAL_FAILED"},
    "FRONTEND": {"ARTIFACT_LOAD_FAILED", "AUTHORIZATION_MISMATCH", "CACHE_STALE", "SILENT_FALLBACK_ATTEMPT"},
    "SECURITY": {"CREDENTIAL_EXPOSURE", "UNSAFE_EGRESS", "PRIVACY_POLICY_VIOLATION", "ALERT_INJECTION"},
    "NOTIFY": {"DELIVERY_FAILED", "DEAD_LETTERED", "WATCHDOG_FAILED"},
}
_DEFAULT_SEVERITY = {
    **{(family, code): "SEV3" for family, codes in _INCIDENT_CODES.items() for code in codes},
    **{("SECURITY", code): "SEV0" for code in _INCIDENT_CODES["SECURITY"]},
    **{("DATABASE", code): "SEV1" for code in _INCIDENT_CODES["DATABASE"]},
    **{("ARTIFACT", code): "SEV1" for code in _INCIDENT_CODES["ARTIFACT"]},
    **{("PUBLICATION", code): "SEV1" for code in _INCIDENT_CODES["PUBLICATION"]},
    **{("NOTIFY", code): "SEV1" for code in _INCIDENT_CODES["NOTIFY"]},
    **{
        (family, code): "SEV2"
        for family in ("SOURCE_POLICY", "FETCH", "SNAPSHOT", "STORAGE", "SCHEMA", "EVIDENCE", "VALIDATION", "CONFLICT", "SCHEDULER", "FRONTEND")
        for code in _INCIDENT_CODES[family]
    },
}
_SEVERITY_RANK = {"SEV0": 0, "SEV1": 1, "SEV2": 2, "SEV3": 3}
_INCIDENT_STATES = {"OPEN", "ACKNOWLEDGED", "INVESTIGATING", "MITIGATED", "RESOLVED", "CLOSED"}
_INCIDENT_TRANSITIONS = {
    "OPENED": (None, "OPEN"),
    "ACKNOWLEDGED": ("OPEN", "ACKNOWLEDGED"),
    "INVESTIGATION_STARTED": ("ACKNOWLEDGED", "INVESTIGATING"),
    "MITIGATED": ("INVESTIGATING", "MITIGATED"),
    "RESOLVED": ("MITIGATED", "RESOLVED"),
    "CLOSED": ("RESOLVED", "CLOSED"),
    "REOPENED": ({"RESOLVED", "CLOSED"}, "OPEN"),
}
_REFERENCE_TYPES = {
    "cycle", "job", "attempt", "source", "source_revision", "benchmark",
    "artifact", "database", "notification_intent", "notification_route", "backup",
}
_WORK_CLASSES = {
    "source_candidate", "terms_certification", "source_contract_evidence_drift",
    "model_system_identity", "validation", "display_conflict",
    "publication_artifact", "incident_followup",
}
_WORK_STATES = {"OPEN", "CLAIMED", "DEFERRED", "RESOLVED", "REJECTED", "BLOCKED"}
_WORK_TRANSITIONS = {
    "CREATED": (None, "OPEN"),
    "CLAIMED": ({"OPEN", "DEFERRED"}, "CLAIMED"),
    "DEFERRED": ({"OPEN", "CLAIMED"}, "DEFERRED"),
    "RESOLVED": ({"OPEN", "CLAIMED", "DEFERRED"}, "RESOLVED"),
    "REJECTED": ({"OPEN", "CLAIMED", "DEFERRED"}, "REJECTED"),
    "BLOCKED": ({"OPEN", "CLAIMED", "DEFERRED"}, "BLOCKED"),
    "REOPENED": ({"DEFERRED", "RESOLVED", "REJECTED", "BLOCKED"}, "OPEN"),
}

_AUTHORITY_KEYS = {
    "classification", "certifiesSources", "authorizesCapture", "authorizesPublication",
    "frontendLoadable", "mutatesEvidence", "timeoutMayApprove",
}


def _fail(path: str, message: str) -> None:
    raise IncidentContractError(f"{path}: {message}")


def _walk(value: Any, path: str = "$") -> None:
    if value is None or type(value) in (str, bool, int):
        return
    if type(value) is float:
        if not math.isfinite(value):
            _fail(path, "non-finite numbers are forbidden")
        return
    if type(value) is list:
        for index, item in enumerate(value):
            _walk(item, f"{path}[{index}]")
        return
    if type(value) is dict:
        for key, item in value.items():
            if type(key) is not str:
                _fail(path, "object keys must be strings")
            _walk(item, f"{path}.{key}")
        return
    _fail(path, f"unsupported JSON type {type(value).__name__}")


def canonical_json(value: Any) -> str:
    _walk(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def _numbered_row_key(value: Any, field: str) -> tuple[int, int, str]:
    """Sort numbered rows deterministically without trusting their shape."""
    if type(value) is dict and type(value.get(field)) is int:
        return (0, value[field], canonical_json(value))
    return (1, 0, canonical_json(value))


def _normalized(payload: dict[str, Any]) -> dict[str, Any]:
    material = deepcopy(payload)
    manifest = material.get("manifest")
    if type(manifest) is not dict or "contentSha256" not in manifest:
        _fail("$.manifest.contentSha256", "is required")
    manifest["contentSha256"] = None
    policy = material.get("policyVersion")
    if policy == "ops-incident-v1":
        for field in ("affectedRefs", "tags", "containmentRefs", "resolutionEvidenceRefs"):
            if type(material.get(field)) is list:
                material[field] = sorted(material[field], key=canonical_json)
        if type(material.get("events")) is list:
            material["events"] = sorted(material["events"], key=lambda row: _numbered_row_key(row, "eventOrdinal"))
    elif policy == "review-work-item-v1":
        if type(material.get("subjectRefs")) is list:
            material["subjectRefs"] = sorted(material["subjectRefs"], key=canonical_json)
        if type(material.get("events")) is list:
            material["events"] = sorted(material["events"], key=lambda row: _numbered_row_key(row, "eventOrdinal"))
    elif policy == "notification-receipt-v1" and type(material.get("attempts")) is list:
        material["attempts"] = sorted(material["attempts"], key=lambda row: _numbered_row_key(row, "attemptNumber"))
    return material


def contract_self_digest(payload: dict[str, Any]) -> str:
    if type(payload) is not dict:
        _fail("$", "contract must be an object")
    return hashlib.sha256(canonical_json(_normalized(payload)).encode()).hexdigest()


def _digest(kind: str, material: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json({"identityKind": kind, **material}).encode()).hexdigest()


def _object(value: Any, path: str, keys: set[str]) -> dict[str, Any]:
    if type(value) is not dict:
        _fail(path, "must be an object")
    present = set(value)
    if present != keys:
        missing, extra = sorted(keys - present), sorted(present - keys)
        _fail(path, f"fields mismatch; missing={missing}, extra={extra}")
    return value


def _array(value: Any, path: str, minimum: int = 0) -> list[Any]:
    if type(value) is not list or len(value) < minimum:
        _fail(path, f"must be an array with at least {minimum} item(s)")
    return value


def _constant(value: Any, expected: Any, path: str) -> None:
    if type(value) is not type(expected) or value != expected:
        _fail(path, f"must equal {expected!r}")


def _enum(value: Any, allowed: set[str], path: str) -> str:
    if type(value) is not str or value not in allowed:
        _fail(path, f"must be one of {sorted(allowed)}")
    return value


def _stable(value: Any, path: str, nullable: bool = False) -> str | None:
    if nullable and value is None:
        return None
    if type(value) is not str or _STABLE_ID.fullmatch(value) is None:
        _fail(path, "must be a stable lowercase identifier")
    return value


def _reason(value: Any, path: str) -> str:
    if type(value) is not str or _REASON.fullmatch(value) is None:
        _fail(path, "must be a stable uppercase code")
    return value


def _sha(value: Any, path: str, nullable: bool = False) -> str | None:
    if nullable and value is None:
        return None
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        _fail(path, "must be a lowercase SHA-256")
    return value


def _integer(value: Any, path: str, minimum: int = 0, maximum: int | None = None) -> int:
    if type(value) is not int or value < minimum or (maximum is not None and value > maximum):
        _fail(path, "must be a bounded integer")
    return value


def _utc(value: Any, path: str, nullable: bool = False) -> datetime | None:
    if nullable and value is None:
        return None
    if type(value) is not str or _UTC.fullmatch(value) is None:
        _fail(path, "must be canonical UTC YYYY-MM-DDTHH:MM:SSZ")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        _fail(path, "must be a valid UTC timestamp")


def _authority(value: Any) -> None:
    authority = _object(value, "$.authority", _AUTHORITY_KEYS)
    _constant(authority["classification"], "operations_record_only", "$.authority.classification")
    for key in _AUTHORITY_KEYS - {"classification"}:
        _constant(authority[key], False, f"$.authority.{key}")


def _manifest(value: Any, counts: dict[str, int]) -> None:
    manifest = _object(value, "$.manifest", {"algorithm", "contentSha256", *counts})
    _constant(manifest["algorithm"], _ALGORITHM, "$.manifest.algorithm")
    _sha(manifest["contentSha256"], "$.manifest.contentSha256")
    for key, expected in counts.items():
        _constant(manifest[key], expected, f"$.manifest.{key}")


def _verify_digest(payload: dict[str, Any]) -> None:
    actual = contract_self_digest(payload)
    if payload["manifest"]["contentSha256"] != actual:
        _fail("$.manifest.contentSha256", "self-digest mismatch")


def _reference(value: Any, path: str) -> dict[str, Any]:
    ref = _object(value, path, {"referenceType", "referenceId"})
    _enum(ref["referenceType"], _REFERENCE_TYPES, f"{path}.referenceType")
    _stable(ref["referenceId"], f"{path}.referenceId")
    return ref


def _references(value: Any, path: str, minimum: int = 0) -> list[dict[str, Any]]:
    rows = _array(value, path, minimum)
    seen: set[tuple[str, str]] = set()
    result = []
    for index, raw in enumerate(rows):
        ref = _reference(raw, f"{path}[{index}]")
        key = (ref["referenceType"], ref["referenceId"])
        if key in seen:
            _fail(f"{path}[{index}]", "duplicate typed reference")
        seen.add(key)
        result.append(ref)
    return result


def incident_fingerprint(payload: dict[str, Any]) -> str:
    refs = payload.get("affectedRefs")
    if type(refs) is not list:
        _fail("$.affectedRefs", "is required for fingerprinting")
    return _digest(
        "ops-incident-fingerprint-v1",
        {
            "environment": payload.get("environment"),
            "family": payload.get("family"),
            "incidentCode": payload.get("incidentCode"),
            "causeCode": payload.get("causeCode"),
            "affectedRefs": sorted(refs, key=canonical_json),
        },
    )


def derive_incident_event_id(fingerprint: str, ordinal: int, expected_prior: str | None, event_type: str, occurred_at: str) -> str:
    _sha(fingerprint, "fingerprint")
    _integer(ordinal, "ordinal", 1)
    return "incident-event-" + _digest(
        "ops-incident-event-v1",
        {"fingerprint": fingerprint, "ordinal": ordinal, "expectedPriorEventId": expected_prior, "eventType": event_type, "occurredAt": occurred_at},
    )


def _evidence_ref(value: Any, path: str, nullable: bool = False) -> dict[str, Any] | None:
    if nullable and value is None:
        return None
    ref = _object(value, path, {"evidenceId", "contentSha256"})
    _stable(ref["evidenceId"], f"{path}.evidenceId")
    _sha(ref["contentSha256"], f"{path}.contentSha256")
    return ref


def validate_ops_incident(payload: dict[str, Any]) -> None:
    _walk(payload)
    root = _object(payload, "$", {
        "schemaVersion", "policyVersion", "availability", "mode", "incidentId",
        "incidentFingerprintSha256", "family", "incidentCode", "causeCode",
        "severity", "severityBasis", "severityDecisionReference", "environment",
        "ownerRole", "assigneeId", "currentState", "occurrenceCount",
        "firstOccurredAt", "lastOccurredAt", "runbookId", "nextActionCode",
        "nextReviewAt", "affectedRefs", "tags", "containmentRefs",
        "resolutionEvidenceRefs", "sla", "events", "authority", "manifest",
    })
    _constant(root["schemaVersion"], "1.0.0", "$.schemaVersion")
    _constant(root["policyVersion"], "ops-incident-v1", "$.policyVersion")
    _constant(root["availability"], "operations_record_only", "$.availability")
    _enum(root["mode"], {"synthetic_fixture", "shadow", "production"}, "$.mode")
    family = _enum(root["family"], set(_INCIDENT_CODES), "$.family")
    code = _enum(root["incidentCode"], _INCIDENT_CODES[family], "$.incidentCode")
    _reason(root["causeCode"], "$.causeCode")
    severity = _enum(root["severity"], set(_SEVERITY_RANK), "$.severity")
    basis = _enum(root["severityBasis"], {"taxonomy_default", "escalated_by_decision"}, "$.severityBasis")
    decision = _stable(root["severityDecisionReference"], "$.severityDecisionReference", True)
    default = _DEFAULT_SEVERITY[(family, code)]
    if basis == "taxonomy_default":
        if severity != default or decision is not None:
            _fail("$.severity", f"taxonomy default is {default} with no decision reference")
    elif decision is None or _SEVERITY_RANK[severity] >= _SEVERITY_RANK[default]:
        _fail("$.severity", "escalation requires a decision and a strictly more severe value")
    _stable(root["environment"], "$.environment")
    _stable(root["ownerRole"], "$.ownerRole")
    _stable(root["assigneeId"], "$.assigneeId", True)
    _enum(root["currentState"], _INCIDENT_STATES, "$.currentState")
    _stable(root["runbookId"], "$.runbookId")
    _reason(root["nextActionCode"], "$.nextActionCode")
    _utc(root["nextReviewAt"], "$.nextReviewAt", True)
    refs = _references(root["affectedRefs"], "$.affectedRefs", 1)

    fingerprint = incident_fingerprint(root)
    _constant(root["incidentFingerprintSha256"], fingerprint, "$.incidentFingerprintSha256")
    _constant(root["incidentId"], "incident-" + fingerprint, "$.incidentId")

    tags = _array(root["tags"], "$.tags")
    tag_keys: set[str] = set()
    tag_values: dict[str, str] = {}
    for index, raw in enumerate(tags):
        path = f"$.tags[{index}]"
        tag = _object(raw, path, {"tagKey", "tagValue"})
        key = _enum(tag["tagKey"], {"area", "sev", "state", "owner", "source", "cause"}, f"{path}.tagKey")
        if key in tag_keys:
            _fail(path, "duplicate tag key")
        tag_keys.add(key)
        if type(tag["tagValue"]) is not str or _TAG_VALUE.fullmatch(tag["tagValue"]) is None:
            _fail(f"{path}.tagValue", "must be a safe stable tag value")
        tag_values[key] = tag["tagValue"]
    reserved_tag_facts = {
        "area": family.lower(), "sev": severity, "state": root["currentState"],
        "owner": root["ownerRole"], "cause": root["causeCode"],
    }
    for key, expected in reserved_tag_facts.items():
        if key in tag_values and tag_values[key] != expected:
            _fail("$.tags", f"reserved {key} tag contradicts the incident fact")
    if "source" in tag_values:
        source_ids = {
            ref["referenceId"] for ref in refs
            if ref["referenceType"] in {"source", "source_revision"}
        }
        if tag_values["source"] not in source_ids:
            _fail("$.tags", "source tag must match an exact affected source/source_revision reference")

    containment = _array(root["containmentRefs"], "$.containmentRefs")
    containment_ids: set[str] = set()
    for index, raw in enumerate(containment):
        path = f"$.containmentRefs[{index}]"
        row = _object(raw, path, {"containmentId", "actionType", "decisionReference", "affectedRef"})
        item_id = _stable(row["containmentId"], f"{path}.containmentId")
        if item_id in containment_ids:
            _fail(path, "duplicate containment reference")
        containment_ids.add(item_id)
        _enum(row["actionType"], {"paused", "quarantined", "revoked", "withdrawn"}, f"{path}.actionType")
        _stable(row["decisionReference"], f"{path}.decisionReference")
        contained_ref = _reference(row["affectedRef"], f"{path}.affectedRef")
        if (contained_ref["referenceType"], contained_ref["referenceId"]) not in {
            (ref["referenceType"], ref["referenceId"]) for ref in refs
        }:
            _fail(f"{path}.affectedRef", "containment must target an exact affected reference")

    evidence_rows = _array(root["resolutionEvidenceRefs"], "$.resolutionEvidenceRefs")
    evidence_by_id: dict[str, str] = {}
    for index, raw in enumerate(evidence_rows):
        ref = _evidence_ref(raw, f"$.resolutionEvidenceRefs[{index}]")
        assert ref is not None
        if ref["evidenceId"] in evidence_by_id:
            _fail(f"$.resolutionEvidenceRefs[{index}]", "duplicate resolution evidence")
        evidence_by_id[ref["evidenceId"]] = ref["contentSha256"]

    events = _array(root["events"], "$.events", 1)
    prior_id: str | None = None
    prior_state: str | None = None
    prior_time: datetime | None = None
    occurrence_times: list[datetime] = []
    episode_started_at: datetime | None = None
    ack_at: datetime | None = None
    mitigated_at: datetime | None = None
    for index, raw in enumerate(sorted(events, key=lambda event: _numbered_row_key(event, "eventOrdinal"))):
        path = f"$.events[{index}]"
        event = _object(raw, path, {
            "eventId", "eventOrdinal", "eventType", "expectedPriorEventId",
            "fromState", "toState", "occurredAt", "actorRole", "reasonCode",
            "acknowledgementEvidenceRef", "resolutionEvidenceRef", "safeContext",
        })
        ordinal = _integer(event["eventOrdinal"], f"{path}.eventOrdinal", 1)
        if ordinal != index + 1:
            _fail(f"{path}.eventOrdinal", "event ordinals must be contiguous")
        _constant(event["expectedPriorEventId"], prior_id, f"{path}.expectedPriorEventId")
        event_type = _enum(event["eventType"], set(_INCIDENT_TRANSITIONS) | {"OCCURRENCE_RECORDED"}, f"{path}.eventType")
        from_state = event["fromState"]
        if from_state is not None:
            _enum(from_state, _INCIDENT_STATES, f"{path}.fromState")
        to_state = _enum(event["toState"], _INCIDENT_STATES, f"{path}.toState")
        if event_type == "OCCURRENCE_RECORDED":
            if prior_state in {None, "RESOLVED", "CLOSED"} or from_state != prior_state or to_state != prior_state:
                _fail(path, "resolved/closed occurrences must REOPEN; active occurrences preserve state")
        else:
            expected_from, expected_to = _INCIDENT_TRANSITIONS[event_type]
            from_is_legal = from_state in expected_from if isinstance(expected_from, set) else from_state == expected_from
            if not from_is_legal or to_state != expected_to or from_state != prior_state:
                _fail(path, "illegal incident state transition")
        occurred = _utc(event["occurredAt"], f"{path}.occurredAt")
        assert occurred is not None
        if prior_time is not None and occurred < prior_time:
            _fail(f"{path}.occurredAt", "events cannot go backwards")
        _stable(event["actorRole"], f"{path}.actorRole")
        _reason(event["reasonCode"], f"{path}.reasonCode")
        ack_ref = _evidence_ref(event["acknowledgementEvidenceRef"], f"{path}.acknowledgementEvidenceRef", True)
        resolution_ref = _evidence_ref(event["resolutionEvidenceRef"], f"{path}.resolutionEvidenceRef", True)
        if event_type == "ACKNOWLEDGED":
            if ack_ref is None or resolution_ref is not None:
                _fail(path, "acknowledgement requires separate acknowledgement evidence only")
            ack_at = occurred
        elif event_type == "RESOLVED":
            if (
                resolution_ref is None
                or ack_ref is not None
                or evidence_by_id.get(resolution_ref["evidenceId"]) != resolution_ref["contentSha256"]
            ):
                _fail(path, "resolution requires listed target-perspective resolution evidence only")
        elif ack_ref is not None or resolution_ref is not None:
            _fail(path, "evidence fields are reserved for acknowledgement/resolution transitions")
        context = _object(event["safeContext"], f"{path}.safeContext", {"contextCode", "sourceControlledDataIncluded"})
        _reason(context["contextCode"], f"{path}.safeContext.contextCode")
        _constant(context["sourceControlledDataIncluded"], False, f"{path}.safeContext.sourceControlledDataIncluded")
        expected_event_id = derive_incident_event_id(fingerprint, ordinal, prior_id, event_type, event["occurredAt"])
        _constant(event["eventId"], expected_event_id, f"{path}.eventId")
        if event_type in {"OPENED", "OCCURRENCE_RECORDED", "REOPENED"}:
            occurrence_times.append(occurred)
        if event_type in {"OPENED", "REOPENED"}:
            episode_started_at = occurred
        if event_type == "REOPENED":
            # SLA facts describe the current occurrence, not a previously closed one.
            ack_at = None
            mitigated_at = None
        if event_type == "MITIGATED":
            mitigated_at = occurred
        prior_id, prior_state, prior_time = event["eventId"], to_state, occurred

    _constant(root["currentState"], prior_state, "$.currentState")
    _constant(root["occurrenceCount"], len(occurrence_times), "$.occurrenceCount")
    _constant(root["firstOccurredAt"], occurrence_times[0].strftime("%Y-%m-%dT%H:%M:%SZ"), "$.firstOccurredAt")
    _constant(root["lastOccurredAt"], occurrence_times[-1].strftime("%Y-%m-%dT%H:%M:%SZ"), "$.lastOccurredAt")
    assert episode_started_at is not None

    sla = _object(root["sla"], "$.sla", {
        "policyStatus", "policyRevisionId", "policyDecisionReference", "calculationStatus",
        "clockType", "businessCalendarId", "timeZone", "acknowledgeWithinSeconds",
        "mitigateWithinSeconds", "acknowledgeDueAt", "mitigateDueAt",
        "acknowledgedAt", "mitigatedAt", "acknowledgedOnTime", "mitigatedOnTime",
    })
    status = _enum(sla["policyStatus"], {"provisional_unapproved", "approved"}, "$.sla.policyStatus")
    _stable(sla["policyRevisionId"], "$.sla.policyRevisionId")
    sla_decision = _stable(sla["policyDecisionReference"], "$.sla.policyDecisionReference", True)
    if (status == "approved") != (sla_decision is not None):
        _fail("$.sla.policyDecisionReference", "approved SLA policy requires a decision; provisional forbids one")
    clock = _enum(sla["clockType"], {"elapsed_utc", "business_calendar"}, "$.sla.clockType")
    calc = _enum(sla["calculationStatus"], {"provisional", "blocked_business_calendar", "active", "assessed"}, "$.sla.calculationStatus")
    business_id = _stable(sla["businessCalendarId"], "$.sla.businessCalendarId", True)
    zone = _stable(sla["timeZone"], "$.sla.timeZone", True)
    ack_seconds = sla["acknowledgeWithinSeconds"]
    mitigate_seconds = sla["mitigateWithinSeconds"]
    for key, value in (("acknowledgeWithinSeconds", ack_seconds), ("mitigateWithinSeconds", mitigate_seconds)):
        if value is not None:
            _integer(value, f"$.sla.{key}", 1)
    parsed_times = {
        key: _utc(sla[key], f"$.sla.{key}", True)
        for key in ("acknowledgeDueAt", "mitigateDueAt", "acknowledgedAt", "mitigatedAt")
    }
    for key in ("acknowledgedOnTime", "mitigatedOnTime"):
        if sla[key] not in {None, True, False}:
            _fail(f"$.sla.{key}", "must be null or boolean")
    if status == "provisional_unapproved" and calc not in {"provisional", "blocked_business_calendar"}:
        _fail("$.sla.calculationStatus", "unapproved SLA policy cannot claim active/assessed calculation")
    if status == "approved" and calc not in {"active", "assessed"}:
        _fail("$.sla.calculationStatus", "approved SLA policy must calculate active or assessed facts")
    if severity in {"SEV2", "SEV3"}:
        if clock != "business_calendar":
            _fail("$.sla.clockType", "SEV2/3 require an approved business-calendar policy")
        if calc == "blocked_business_calendar":
            if any(value is not None for value in (business_id, zone, ack_seconds, mitigate_seconds, sla["acknowledgeDueAt"], sla["mitigateDueAt"], sla["acknowledgedOnTime"], sla["mitigatedOnTime"])):
                _fail("$.sla", "blocked business-calendar SLA facts must remain unknown")
        elif business_id is None or zone is None:
            _fail("$.sla", "business-calendar calculation requires approved calendar and timezone IDs")
    else:
        expected = {"SEV0": (900, 3600), "SEV1": (1800, 14400)}[severity]
        if clock != "elapsed_utc" or (ack_seconds, mitigate_seconds) != expected:
            _fail("$.sla", "elapsed UTC severity targets contradict the taxonomy")
        if calc == "blocked_business_calendar":
            _fail("$.sla.calculationStatus", "elapsed UTC SLA cannot be blocked on a business calendar")
    if calc in {"provisional", "blocked_business_calendar"}:
        if any(sla[key] is not None for key in ("acknowledgeDueAt", "mitigateDueAt", "acknowledgedOnTime", "mitigatedOnTime")):
            _fail("$.sla", "provisional/blocked policy cannot claim due-time or on-time facts")
    else:
        if parsed_times["acknowledgeDueAt"] is None or parsed_times["mitigateDueAt"] is None:
            _fail("$.sla", "active/assessed SLA requires both due times")
        if severity in {"SEV0", "SEV1"}:
            expected_ack_due = episode_started_at + timedelta(seconds=ack_seconds)
            expected_mitigate_due = episode_started_at + timedelta(seconds=mitigate_seconds)
            if parsed_times["acknowledgeDueAt"] != expected_ack_due or parsed_times["mitigateDueAt"] != expected_mitigate_due:
                _fail("$.sla", "elapsed UTC due times must derive exactly from the current occurrence")
    expected_ack = ack_at.strftime("%Y-%m-%dT%H:%M:%SZ") if ack_at else None
    expected_mitigated = mitigated_at.strftime("%Y-%m-%dT%H:%M:%SZ") if mitigated_at else None
    _constant(sla["acknowledgedAt"], expected_ack, "$.sla.acknowledgedAt")
    _constant(sla["mitigatedAt"], expected_mitigated, "$.sla.mitigatedAt")
    for observed_key, due_key, on_time_key in (
        ("acknowledgedAt", "acknowledgeDueAt", "acknowledgedOnTime"),
        ("mitigatedAt", "mitigateDueAt", "mitigatedOnTime"),
    ):
        observed, due_at = parsed_times[observed_key], parsed_times[due_key]
        expected_on_time = observed <= due_at if observed is not None and due_at is not None else None
        _constant(sla[on_time_key], expected_on_time, f"$.sla.{on_time_key}")
    if calc == "assessed" and (ack_at is None or mitigated_at is None):
        _fail("$.sla.calculationStatus", "assessed SLA requires acknowledgement and mitigation observations")

    _authority(root["authority"])
    _manifest(root["manifest"], {
        "affectedReferenceCount": len(refs), "tagCount": len(tags),
        "containmentReferenceCount": len(containment),
        "resolutionEvidenceReferenceCount": len(evidence_rows), "eventCount": len(events),
    })
    _verify_digest(root)


def work_item_fingerprint(payload: dict[str, Any]) -> str:
    refs = payload.get("subjectRefs")
    if type(refs) is not list:
        _fail("$.subjectRefs", "is required for fingerprinting")
    return _digest("review-work-item-fingerprint-v1", {
        "environment": payload.get("environment"),
        "workClass": payload.get("workClass"), "reasonCode": payload.get("reasonCode"),
        "subjectRefs": sorted(refs, key=canonical_json),
    })


def derive_work_event_id(fingerprint: str, ordinal: int, expected_prior: str | None, event_type: str, occurred_at: str) -> str:
    return "work-event-" + _digest("review-work-event-v1", {
        "fingerprint": fingerprint, "ordinal": ordinal, "expectedPriorEventId": expected_prior,
        "eventType": event_type, "occurredAt": occurred_at,
    })


def validate_review_work_item(payload: dict[str, Any]) -> None:
    _walk(payload)
    root = _object(payload, "$", {
        "schemaVersion", "policyVersion", "availability", "mode", "workItemId",
        "workItemFingerprintSha256", "environment", "workClass", "reasonCode", "ownerRole",
        "assigneeId", "currentState", "publicationBlocking", "subjectRefs",
        "duePolicy", "events", "authority", "manifest",
    })
    _constant(root["schemaVersion"], "1.0.0", "$.schemaVersion")
    _constant(root["policyVersion"], "review-work-item-v1", "$.policyVersion")
    _constant(root["availability"], "operations_record_only", "$.availability")
    _enum(root["mode"], {"synthetic_fixture", "shadow", "production"}, "$.mode")
    _stable(root["environment"], "$.environment")
    work_class = _enum(root["workClass"], _WORK_CLASSES, "$.workClass")
    _reason(root["reasonCode"], "$.reasonCode")
    _stable(root["ownerRole"], "$.ownerRole")
    _stable(root["assigneeId"], "$.assigneeId", True)
    _enum(root["currentState"], _WORK_STATES, "$.currentState")
    if type(root["publicationBlocking"]) is not bool:
        _fail("$.publicationBlocking", "must be boolean")
    if work_class in {"display_conflict", "publication_artifact"} and not root["publicationBlocking"]:
        _fail("$.publicationBlocking", "display/publication work cannot bypass the release block")
    refs = _references(root["subjectRefs"], "$.subjectRefs", 1)
    fingerprint = work_item_fingerprint(root)
    _constant(root["workItemFingerprintSha256"], fingerprint, "$.workItemFingerprintSha256")
    _constant(root["workItemId"], "work-item-" + fingerprint, "$.workItemId")

    due = _object(root["duePolicy"], "$.duePolicy", {
        "policyStatus", "policyRevisionId", "policyDecisionReference", "dueKind",
        "businessCalendarId", "timeZone", "dueAt", "nextReviewAt",
        "calculationStatus", "terminalAt", "onTime",
    })
    policy_status = _enum(due["policyStatus"], {"provisional_unapproved", "approved"}, "$.duePolicy.policyStatus")
    _stable(due["policyRevisionId"], "$.duePolicy.policyRevisionId")
    decision = _stable(due["policyDecisionReference"], "$.duePolicy.policyDecisionReference", True)
    if (policy_status == "approved") != (decision is not None):
        _fail("$.duePolicy.policyDecisionReference", "approved policy requires a decision; provisional forbids one")
    due_kind = _enum(due["dueKind"], {"business_calendar", "immediate_before_expiry", "release_specific", "incident_recorded"}, "$.duePolicy.dueKind")
    business_id = _stable(due["businessCalendarId"], "$.duePolicy.businessCalendarId", True)
    zone = _stable(due["timeZone"], "$.duePolicy.timeZone", True)
    _utc(due["dueAt"], "$.duePolicy.dueAt", True)
    _utc(due["nextReviewAt"], "$.duePolicy.nextReviewAt", True)
    calc = _enum(due["calculationStatus"], {"blocked_owner_policy", "active", "assessed"}, "$.duePolicy.calculationStatus")
    _utc(due["terminalAt"], "$.duePolicy.terminalAt", True)
    if due["onTime"] not in {None, True, False}:
        _fail("$.duePolicy.onTime", "must be null or boolean")
    if calc == "blocked_owner_policy":
        if policy_status != "provisional_unapproved":
            _fail("$.duePolicy.calculationStatus", "blocked owner policy must remain provisional")
        if any(value is not None for value in (business_id, zone, due["dueAt"], due["onTime"])):
            _fail("$.duePolicy", "blocked owner policy cannot claim SLA calculation facts")
    else:
        if policy_status != "approved" or due["dueAt"] is None:
            _fail("$.duePolicy", "active/assessed due calculation requires approved policy and exact dueAt")
        if due_kind == "business_calendar" and (business_id is None or zone is None):
            _fail("$.duePolicy", "active business due policy requires calendar and timezone IDs")

    events = _array(root["events"], "$.events", 1)
    prior_id: str | None = None
    prior_state: str | None = None
    prior_time: datetime | None = None
    last_deferral_review: str | None = None
    for index, raw in enumerate(sorted(events, key=lambda row: _numbered_row_key(row, "eventOrdinal"))):
        path = f"$.events[{index}]"
        event = _object(raw, path, {
            "eventId", "eventOrdinal", "eventType", "expectedPriorEventId", "fromState",
            "toState", "occurredAt", "actorRole", "reasonCode", "decisionReference",
            "nextReviewAt", "safeContext",
        })
        ordinal = _integer(event["eventOrdinal"], f"{path}.eventOrdinal", 1)
        if ordinal != index + 1:
            _fail(f"{path}.eventOrdinal", "must be contiguous")
        _constant(event["expectedPriorEventId"], prior_id, f"{path}.expectedPriorEventId")
        event_type = _enum(event["eventType"], set(_WORK_TRANSITIONS), f"{path}.eventType")
        expected_from, expected_to = _WORK_TRANSITIONS[event_type]
        from_state = event["fromState"]
        if isinstance(expected_from, set):
            if from_state not in expected_from:
                _fail(path, "illegal work-item transition")
        elif from_state != expected_from:
            _fail(path, "illegal work-item transition")
        if from_state != prior_state or event["toState"] != expected_to:
            _fail(path, "stale/branched work-item transition")
        occurred = _utc(event["occurredAt"], f"{path}.occurredAt")
        assert occurred is not None
        if prior_time and occurred < prior_time:
            _fail(path, "events cannot go backwards")
        _stable(event["actorRole"], f"{path}.actorRole")
        _reason(event["reasonCode"], f"{path}.reasonCode")
        event_decision = _stable(event["decisionReference"], f"{path}.decisionReference", True)
        review_at = _utc(event["nextReviewAt"], f"{path}.nextReviewAt", True)
        if event_type in {"RESOLVED", "REJECTED", "BLOCKED"} and event_decision is None:
            _fail(path, "terminal work-item action requires an explicit decision reference")
        if event_type == "DEFERRED" and review_at is None:
            _fail(path, "deferral requires a new review time")
        if event_type not in {"DEFERRED"} and review_at is not None:
            _fail(path, "nextReviewAt belongs only to explicit deferral")
        context = _object(event["safeContext"], f"{path}.safeContext", {"contextCode", "sourceControlledDataIncluded"})
        _reason(context["contextCode"], f"{path}.safeContext.contextCode")
        _constant(context["sourceControlledDataIncluded"], False, f"{path}.safeContext.sourceControlledDataIncluded")
        expected_id = derive_work_event_id(fingerprint, ordinal, prior_id, event_type, event["occurredAt"])
        _constant(event["eventId"], expected_id, f"{path}.eventId")
        last_deferral_review = event["nextReviewAt"] if event_type == "DEFERRED" else None
        prior_id, prior_state, prior_time = event["eventId"], expected_to, occurred
    _constant(root["currentState"], prior_state, "$.currentState")
    if prior_state == "DEFERRED":
        _constant(due["nextReviewAt"], last_deferral_review, "$.duePolicy.nextReviewAt")
    elif due["nextReviewAt"] is not None:
        _fail("$.duePolicy.nextReviewAt", "only the current explicit deferral may set nextReviewAt")
    if prior_state in {"RESOLVED", "REJECTED", "BLOCKED"}:
        _constant(due["terminalAt"], prior_time.strftime("%Y-%m-%dT%H:%M:%SZ"), "$.duePolicy.terminalAt")
        if calc == "active":
            _fail("$.duePolicy.calculationStatus", "terminal work item must be assessed or explicitly blocked")
    elif due["terminalAt"] is not None or calc == "assessed":
        _fail("$.duePolicy", "non-terminal work item cannot claim terminal assessment facts")
    if calc == "assessed":
        terminal_at = _utc(due["terminalAt"], "$.duePolicy.terminalAt")
        due_at = _utc(due["dueAt"], "$.duePolicy.dueAt")
        assert terminal_at and due_at
        _constant(due["onTime"], terminal_at <= due_at, "$.duePolicy.onTime")
    _authority(root["authority"])
    _manifest(root["manifest"], {"subjectReferenceCount": len(refs), "eventCount": len(events)})
    _verify_digest(root)


def payload_digest(payload: dict[str, Any]) -> str:
    _validate_notification_payload(payload)
    return hashlib.sha256(canonical_json(payload).encode()).hexdigest()


def _validate_notification_payload(value: Any) -> dict[str, Any]:
    payload = _object(value, "$.payload", {
        "incidentCode", "severity", "environment", "incidentId", "currentState",
        "runbookId", "nextActionCode", "occurrenceCount", "recoveryState",
    })
    _reason(payload["incidentCode"], "$.payload.incidentCode")
    _enum(payload["severity"], set(_SEVERITY_RANK), "$.payload.severity")
    for key in ("environment", "incidentId", "runbookId"):
        _stable(payload[key], f"$.payload.{key}")
    _enum(payload["currentState"], _INCIDENT_STATES, "$.payload.currentState")
    _reason(payload["nextActionCode"], "$.payload.nextActionCode")
    _integer(payload["occurrenceCount"], "$.payload.occurrenceCount", 1)
    _enum(payload["recoveryState"], {"not_applicable", "recovered", "still_affected"}, "$.payload.recoveryState")
    return payload


def notification_intent_dedupe_key(payload: dict[str, Any]) -> str:
    return _digest("notification-intent-dedupe-v1", {
        "incidentFingerprintSha256": payload.get("incidentFingerprintSha256"),
        "incidentEventId": payload.get("incidentEventId"),
        "notificationKind": payload.get("notificationKind"),
        "routeId": payload.get("route", {}).get("routeId") if type(payload.get("route")) is dict else None,
        "templateId": payload.get("template", {}).get("templateId") if type(payload.get("template")) is dict else None,
        "templateVersion": payload.get("template", {}).get("version") if type(payload.get("template")) is dict else None,
    })


def validate_notification_intent(payload: dict[str, Any]) -> None:
    _walk(payload)
    root = _object(payload, "$", {
        "schemaVersion", "policyVersion", "availability", "mode", "intentId",
        "dedupeKeySha256", "incidentId", "incidentFingerprintSha256", "incidentFamily",
        "incidentCode", "incidentEventId", "incidentEventType", "notificationKind",
        "severity", "route", "template", "payload", "payloadSha256",
        "dispatchEligibility", "recursionDisposition", "outboxAtomicWithIncidentEvent",
        "authority", "manifest",
    })
    _constant(root["schemaVersion"], "1.0.0", "$.schemaVersion")
    _constant(root["policyVersion"], "notification-intent-v1", "$.policyVersion")
    _constant(root["availability"], "operations_record_only", "$.availability")
    mode = _enum(root["mode"], {"synthetic_fixture", "shadow", "production"}, "$.mode")
    _stable(root["incidentId"], "$.incidentId")
    _sha(root["incidentFingerprintSha256"], "$.incidentFingerprintSha256")
    family = _enum(root["incidentFamily"], set(_INCIDENT_CODES), "$.incidentFamily")
    _enum(root["incidentCode"], _INCIDENT_CODES[family], "$.incidentCode")
    _stable(root["incidentEventId"], "$.incidentEventId")
    _enum(root["incidentEventType"], set(_INCIDENT_TRANSITIONS) | {"OCCURRENCE_RECORDED"}, "$.incidentEventType")
    kind = _enum(root["notificationKind"], {"urgent", "transition", "recovery", "digest", "canary"}, "$.notificationKind")
    _enum(root["severity"], set(_SEVERITY_RANK), "$.severity")
    route = _object(root["route"], "$.route", {
        "routeId", "routeType", "external", "authorityStatus", "authorityDecisionReference",
        "recipientSetId", "failureDomain",
    })
    route_id = _stable(route["routeId"], "$.route.routeId")
    route_type = _enum(route["routeType"], {"local_json", "email", "slack", "discord", "github_issue", "pager", "independent_watchdog"}, "$.route.routeType")
    if type(route["external"]) is not bool:
        _fail("$.route.external", "must be boolean")
    route_status = _enum(route["authorityStatus"], {"local_fixture_only", "externally_blocked", "approved_external"}, "$.route.authorityStatus")
    route_decision = _stable(route["authorityDecisionReference"], "$.route.authorityDecisionReference", True)
    _stable(route["recipientSetId"], "$.route.recipientSetId")
    _enum(route["failureDomain"], {"local_fixture", "primary_outbox", "external_watchdog"}, "$.route.failureDomain")
    eligibility = _enum(root["dispatchEligibility"], {"local_only", "blocked_authority", "eligible_external", "suppressed_recursive"}, "$.dispatchEligibility")
    recursion = _enum(root["recursionDisposition"], {"not_recursive", "suppressed_notify_family"}, "$.recursionDisposition")
    if family == "NOTIFY":
        if recursion != "suppressed_notify_family" or eligibility != "suppressed_recursive":
            _fail("$.recursionDisposition", "notification-family incidents must be suppressed to prevent recursive storms")
    elif recursion != "not_recursive":
        _fail("$.recursionDisposition", "non-notification incidents are not recursive")
    if route_type == "local_json":
        if route["external"] or route_status != "local_fixture_only" or route_decision is not None or eligibility not in {"local_only", "suppressed_recursive"}:
            _fail("$.route", "local JSON routes are non-external fixture/local sinks only")
    else:
        if not route["external"]:
            _fail("$.route.external", "external adapter route types must be marked external")
        if route_status == "externally_blocked":
            if route_decision is not None or eligibility not in {"blocked_authority", "suppressed_recursive"}:
                _fail("$.route", "blocked external routes cannot carry an authority decision or eligibility")
        elif route_status == "approved_external":
            if route_decision is None or eligibility != "eligible_external" or mode == "synthetic_fixture":
                _fail("$.route", "approved external route requires real mode, decision, and eligibility")
        else:
            _fail("$.route.authorityStatus", "external adapters cannot use local_fixture_only")
    template = _object(root["template"], "$.template", {"templateId", "version"})
    _stable(template["templateId"], "$.template.templateId")
    _stable(template["version"], "$.template.version")
    _validate_notification_payload(root["payload"])
    for key, expected in (
        ("incidentCode", root["incidentCode"]),
        ("severity", root["severity"]),
        ("incidentId", root["incidentId"]),
    ):
        _constant(root["payload"][key], expected, f"$.payload.{key}")
    resulting_state = {
        "OPENED": "OPEN", "ACKNOWLEDGED": "ACKNOWLEDGED",
        "INVESTIGATION_STARTED": "INVESTIGATING", "MITIGATED": "MITIGATED",
        "RESOLVED": "RESOLVED", "CLOSED": "CLOSED", "REOPENED": "OPEN",
    }.get(root["incidentEventType"])
    if resulting_state is not None:
        _constant(root["payload"]["currentState"], resulting_state, "$.payload.currentState")
    if kind == "recovery":
        if root["incidentEventType"] not in {"RESOLVED", "CLOSED"} or root["payload"]["recoveryState"] != "recovered":
            _fail("$.notificationKind", "recovery intent requires a resolved/closed event and recovered payload state")
    elif root["payload"]["recoveryState"] == "recovered":
        _fail("$.payload.recoveryState", "only a recovery intent may claim recovered state")
    _constant(root["payloadSha256"], payload_digest(root["payload"]), "$.payloadSha256")
    dedupe = notification_intent_dedupe_key(root)
    _constant(root["dedupeKeySha256"], dedupe, "$.dedupeKeySha256")
    _constant(root["intentId"], "notification-intent-" + dedupe, "$.intentId")
    _constant(root["outboxAtomicWithIncidentEvent"], True, "$.outboxAtomicWithIncidentEvent")
    authority = _object(root["authority"], "$.authority", {
        "classification", "dataMinimizationDecisionReference", "recipientAuthorityDecisionReference",
        "retentionDecisionReference", "authenticationDecisionReference", "ownerDecisionReference",
        "canAcknowledgeIncident", "canResolveIncident", "mutatesEvidence",
    })
    _constant(authority["classification"], "notification_intent_only", "$.authority.classification")
    refs = [
        _stable(authority[key], f"$.authority.{key}", True)
        for key in (
            "dataMinimizationDecisionReference", "recipientAuthorityDecisionReference",
            "retentionDecisionReference", "authenticationDecisionReference", "ownerDecisionReference",
        )
    ]
    for key in ("canAcknowledgeIncident", "canResolveIncident", "mutatesEvidence"):
        _constant(authority[key], False, f"$.authority.{key}")
    if route_status == "approved_external":
        if any(ref is None for ref in refs):
            _fail("$.authority", "approved external route requires every privacy/recipient/retention/auth/owner decision")
    elif any(ref is not None for ref in refs):
        _fail("$.authority", "local or blocked routes cannot imply external authority")
    _manifest(root["manifest"], {})
    _verify_digest(root)


def notification_receipt_dedupe_key(payload: dict[str, Any]) -> str:
    binding = payload.get("intentBinding") if type(payload.get("intentBinding")) is dict else {}
    return _digest("notification-receipt-dedupe-v1", {
        "intentId": binding.get("intentId"), "routeId": binding.get("routeId"),
        "adapterId": binding.get("adapterId"), "adapterVersion": binding.get("adapterVersion"),
    })


def validate_notification_receipt(payload: dict[str, Any]) -> None:
    _walk(payload)
    root = _object(payload, "$", {
        "schemaVersion", "policyVersion", "availability", "mode", "receiptId",
        "receiptDedupeKeySha256", "intentBinding", "routeAuthorityStatus", "outcome",
        "attempts", "deadLetter", "recovery", "canary", "effects", "manifest",
    })
    _constant(root["schemaVersion"], "1.0.0", "$.schemaVersion")
    _constant(root["policyVersion"], "notification-receipt-v1", "$.policyVersion")
    _constant(root["availability"], "operations_record_only", "$.availability")
    _enum(root["mode"], {"synthetic_fixture", "shadow", "production"}, "$.mode")
    binding = _object(root["intentBinding"], "$.intentBinding", {
        "intentId", "intentContentSha256", "intentDedupeKeySha256", "payloadSha256",
        "routeId", "adapterId", "adapterVersion",
    })
    for key in ("intentId", "routeId", "adapterId", "adapterVersion"):
        _stable(binding[key], f"$.intentBinding.{key}")
    for key in ("intentContentSha256", "intentDedupeKeySha256", "payloadSha256"):
        _sha(binding[key], f"$.intentBinding.{key}")
    route_status = _enum(root["routeAuthorityStatus"], {"local_fixture_only", "externally_blocked", "approved_external"}, "$.routeAuthorityStatus")
    outcome = _enum(root["outcome"], {"local_fixture_recorded", "blocked_authority", "delivered", "retry_exhausted", "dead_lettered", "suppressed_duplicate", "canary_failed", "recovery_delivered"}, "$.outcome")
    attempts = _array(root["attempts"], "$.attempts", 1)
    prior_end: datetime | None = None
    prior_retry_at: datetime | None = None
    for index, raw in enumerate(sorted(attempts, key=lambda row: _numbered_row_key(row, "attemptNumber"))):
        path = f"$.attempts[{index}]"
        attempt = _object(raw, path, {
            "attemptNumber", "startedAt", "endedAt", "outcome", "causeCode",
            "safeProviderMessageReferenceSha256", "retryAt",
        })
        number = _integer(attempt["attemptNumber"], f"{path}.attemptNumber", 1, 3)
        if number != index + 1:
            _fail(path, "notification attempt numbers must be contiguous")
        started, ended = _utc(attempt["startedAt"], f"{path}.startedAt"), _utc(attempt["endedAt"], f"{path}.endedAt")
        assert started and ended
        if ended < started or (prior_end and started < prior_end):
            _fail(path, "notification attempts must be temporally ordered")
        if prior_retry_at is not None and started < prior_retry_at:
            _fail(f"{path}.startedAt", "retry attempt cannot start before the prior retryAt")
        attempt_outcome = _enum(attempt["outcome"], {"local_recorded", "blocked_authority", "delivered", "failed_transient", "failed_permanent", "suppressed"}, f"{path}.outcome")
        _reason(attempt["causeCode"], f"{path}.causeCode")
        _sha(attempt["safeProviderMessageReferenceSha256"], f"{path}.safeProviderMessageReferenceSha256", True)
        retry_at = _utc(attempt["retryAt"], f"{path}.retryAt", True)
        if attempt_outcome == "failed_transient":
            if number < 3 and retry_at is None:
                _fail(path, "transient failure before final attempt requires retryAt")
            if number == 3 and retry_at is not None:
                _fail(path, "the final transient failure cannot schedule a fourth attempt")
            if retry_at is not None and retry_at < ended:
                _fail(f"{path}.retryAt", "retryAt cannot precede the failed attempt end")
        elif retry_at is not None:
            _fail(path, "only transient failures may carry retryAt")
        prior_end = ended
        prior_retry_at = retry_at
    ordered_attempts = sorted(attempts, key=lambda row: _numbered_row_key(row, "attemptNumber"))
    for index, attempt in enumerate(ordered_attempts[:-1]):
        if attempt["outcome"] != "failed_transient" or attempt["retryAt"] is None:
            _fail(f"$.attempts[{index}]", "only a transient failure with retryAt may precede another attempt")
    last = ordered_attempts[-1]["outcome"]
    expected_last = {
        "local_fixture_recorded": "local_recorded", "blocked_authority": "blocked_authority",
        "delivered": "delivered", "retry_exhausted": "failed_transient",
        "dead_lettered": "failed_permanent", "suppressed_duplicate": "suppressed",
        "canary_failed": "failed_permanent", "recovery_delivered": "delivered",
    }[outcome]
    if last != expected_last:
        _fail("$.outcome", "final receipt outcome contradicts the final attempt")
    if outcome == "retry_exhausted" and len(attempts) != 3:
        _fail("$.outcome", "retry exhaustion requires the exact three-attempt budget")
    if outcome in {"delivered", "recovery_delivered"} and route_status != "approved_external":
        _fail("$.routeAuthorityStatus", "external delivery requires approved route authority")
    if outcome == "local_fixture_recorded" and route_status != "local_fixture_only":
        _fail("$.routeAuthorityStatus", "local receipt requires local fixture authority")
    if outcome == "blocked_authority" and route_status != "externally_blocked":
        _fail("$.routeAuthorityStatus", "blocked receipt requires externally_blocked authority")
    permitted_outcomes = {
        "local_fixture_only": {"local_fixture_recorded", "suppressed_duplicate"},
        "externally_blocked": {"blocked_authority", "suppressed_duplicate"},
        "approved_external": {"delivered", "retry_exhausted", "dead_lettered", "suppressed_duplicate", "canary_failed", "recovery_delivered"},
    }
    if outcome not in permitted_outcomes[route_status]:
        _fail("$.outcome", "receipt outcome is not legal for the bound route authority")
    dead = _object(root["deadLetter"], "$.deadLetter", {"status", "deadLetterReferenceId", "nextActionCode"})
    dead_status = _enum(dead["status"], {"none", "dead_lettered"}, "$.deadLetter.status")
    dead_ref = _stable(dead["deadLetterReferenceId"], "$.deadLetter.deadLetterReferenceId", True)
    _reason(dead["nextActionCode"], "$.deadLetter.nextActionCode")
    if outcome == "dead_lettered":
        if dead_status != "dead_lettered" or dead_ref is None:
            _fail("$.deadLetter", "dead-letter outcome requires its durable reference")
    elif dead_status != "none" or dead_ref is not None:
        _fail("$.deadLetter", "non-dead-letter outcomes cannot claim dead-letter state")
    recovery = _object(root["recovery"], "$.recovery", {"priorReceiptId", "recoveryIntentId", "recoveredAt"})
    recovery_values = (
        _stable(recovery["priorReceiptId"], "$.recovery.priorReceiptId", True),
        _stable(recovery["recoveryIntentId"], "$.recovery.recoveryIntentId", True),
        _utc(recovery["recoveredAt"], "$.recovery.recoveredAt", True),
    )
    if outcome == "recovery_delivered":
        if any(value is None for value in recovery_values):
            _fail("$.recovery", "recovery delivery requires prior receipt, intent, and time")
    elif any(value is not None for value in recovery_values):
        _fail("$.recovery", "recovery fields belong only to recovery delivery")
    canary = _object(root["canary"], "$.canary", {"isCanary", "canaryId", "expectedBy", "observedAt"})
    if type(canary["isCanary"]) is not bool:
        _fail("$.canary.isCanary", "must be boolean")
    canary_id = _stable(canary["canaryId"], "$.canary.canaryId", True)
    expected_by = _utc(canary["expectedBy"], "$.canary.expectedBy", True)
    observed_at = _utc(canary["observedAt"], "$.canary.observedAt", True)
    if canary["isCanary"] != (canary_id is not None and expected_by is not None):
        _fail("$.canary", "canary identity and deadline must be complete")
    if outcome == "canary_failed" and not canary["isCanary"]:
        _fail("$.canary", "canary_failed requires a canary binding")
    if not canary["isCanary"] and observed_at is not None:
        _fail("$.canary.observedAt", "non-canary receipt cannot carry canary observation time")
    effects = _object(root["effects"], "$.effects", {"acknowledgesIncident", "resolvesIncident", "mutatesEvidence"})
    for key in effects:
        _constant(effects[key], False, f"$.effects.{key}")
    dedupe = notification_receipt_dedupe_key(root)
    _constant(root["receiptDedupeKeySha256"], dedupe, "$.receiptDedupeKeySha256")
    _constant(root["receiptId"], "notification-receipt-" + dedupe, "$.receiptId")
    _manifest(root["manifest"], {"attemptCount": len(attempts)})
    _verify_digest(root)


def validate_notification_pair(intent: dict[str, Any], receipt: dict[str, Any]) -> None:
    validate_notification_intent(intent)
    validate_notification_receipt(receipt)
    binding = receipt["intentBinding"]
    expected = {
        "intentId": intent["intentId"], "intentContentSha256": intent["manifest"]["contentSha256"],
        "intentDedupeKeySha256": intent["dedupeKeySha256"], "payloadSha256": intent["payloadSha256"],
        "routeId": intent["route"]["routeId"],
    }
    for key, value in expected.items():
        if binding[key] != value:
            _fail(f"$.intentBinding.{key}", "receipt does not bind the exact intent")
    if receipt["routeAuthorityStatus"] != intent["route"]["authorityStatus"]:
        _fail("$.routeAuthorityStatus", "receipt route authority differs from the intent")
    is_recovery_intent = intent["notificationKind"] == "recovery"
    is_recovery_receipt = receipt["outcome"] == "recovery_delivered"
    if is_recovery_intent != is_recovery_receipt:
        _fail("$.outcome", "recovery notification kind and recovery receipt outcome must agree")
    if is_recovery_intent and receipt["recovery"]["recoveryIntentId"] != intent["intentId"]:
        _fail("$.recovery.recoveryIntentId", "recovery receipt must bind the exact recovery intent")
    is_canary_intent = intent["notificationKind"] == "canary"
    has_observed_canary = receipt["canary"]["isCanary"] and receipt["canary"]["observedAt"] is not None
    if is_canary_intent != has_observed_canary:
        _fail("$.canary", "canary notification kind requires exactly one observed canary receipt")


def validate_incident_notification_binding(incident: dict[str, Any], intent: dict[str, Any]) -> None:
    """Bind an intent to the exact latest event and redacted facts of an incident."""
    validate_ops_incident(incident)
    validate_notification_intent(intent)
    latest = max(incident["events"], key=lambda row: row["eventOrdinal"])
    exact_root_facts = {
        "incidentId": incident["incidentId"],
        "incidentFingerprintSha256": incident["incidentFingerprintSha256"],
        "incidentFamily": incident["family"],
        "incidentCode": incident["incidentCode"],
        "severity": incident["severity"],
        "incidentEventId": latest["eventId"],
        "incidentEventType": latest["eventType"],
    }
    for key, expected in exact_root_facts.items():
        if intent[key] != expected:
            _fail(f"$.{key}", "notification intent does not bind the exact latest incident fact")
    exact_payload_facts = {
        "environment": incident["environment"],
        "incidentId": incident["incidentId"],
        "incidentCode": incident["incidentCode"],
        "severity": incident["severity"],
        "currentState": incident["currentState"],
        "occurrenceCount": incident["occurrenceCount"],
        "runbookId": incident["runbookId"],
        "nextActionCode": incident["nextActionCode"],
    }
    for key, expected in exact_payload_facts.items():
        if intent["payload"][key] != expected:
            _fail(f"$.payload.{key}", "notification payload does not bind the exact incident fact")


__all__ = [
    "IncidentContractError", "canonical_json", "contract_self_digest",
    "incident_fingerprint", "derive_incident_event_id", "validate_ops_incident",
    "work_item_fingerprint", "derive_work_event_id", "validate_review_work_item",
    "payload_digest", "notification_intent_dedupe_key", "validate_notification_intent",
    "notification_receipt_dedupe_key", "validate_notification_receipt",
    "validate_notification_pair", "validate_incident_notification_binding",
]
