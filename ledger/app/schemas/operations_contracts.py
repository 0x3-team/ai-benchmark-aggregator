"""Pure semantic contracts for deterministic scheduler receipts.

The schemas in ``docs/contracts`` describe the JSON wire shape.  This module
enforces identities and cross-field invariants that JSON Schema cannot express:
UTC slot arithmetic, idempotent cycle/job identities, complete disposition
accounting, bounded retry policy, and monotonic lease fencing.

The implementation is deliberately standard-library-only and side-effect-free.
It performs no file, database, network, clock, environment, or provider access.
Wake-up facts are supporting observations only and never participate in logical
cycle or job identity.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import re
from typing import Any


class OperationsContractError(ValueError):
    """Raised when an operations contract is malformed or contradictory."""


_STABLE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_REASON_CODE = re.compile(r"^[A-Z][A-Z0-9_]{2,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_UTC_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_ALGORITHM = "sha256-canonical-operations-json-v1"

_AUTHORITY_KEYS = {
    "classification",
    "certifiesSources",
    "authorizesCapture",
    "authorizesPublication",
    "frontendLoadable",
    "wakeupAuthoritative",
}
_CYCLE_KEYS = {
    "schemaVersion",
    "policyVersion",
    "availability",
    "mode",
    "cycleId",
    "environment",
    "lane",
    "schedulePolicyRevisionId",
    "slot",
    "wakeups",
    "state",
    "jobs",
    "counts",
    "authority",
    "manifest",
}
_ATTEMPT_KEYS = {
    "schemaVersion",
    "policyVersion",
    "availability",
    "mode",
    "attemptId",
    "cycleId",
    "jobId",
    "environment",
    "lane",
    "schedulePolicyRevisionId",
    "scheduledFor",
    "targetType",
    "targetRevisionId",
    "sourceRevisionId",
    "attemptNumber",
    "maxAttempts",
    "workerIdentitySha256",
    "wakeup",
    "lease",
    "timing",
    "stageReached",
    "outcome",
    "causeCode",
    "retry",
    "outputReferences",
    "authority",
    "manifest",
}

_LANES = {"discovery", "recheck", "maintenance"}
_TARGET_TYPES = {"discovery_target", "source_revision", "maintenance_task"}
_LANE_TARGET = {
    "discovery": "discovery_target",
    "recheck": "source_revision",
    "maintenance": "maintenance_task",
}
_WAKEUP_KINDS = {
    "cloudflare_cron",
    "cloudflare_workflow",
    "queue",
    "reconciler",
    "manual_fixture",
}
_TERMINAL_DISPOSITIONS = {
    "not_due",
    "completed_unchanged",
    "completed_changed",
    "completed_with_review",
    "attempted_policy_failed",
    "discovery_unchanged",
    "discovery_changed",
    "maintenance_completed",
    "identity_review_required",
    "retry_exhausted",
    "dispatch_missed",
    "policy_blocked",
    "terms_quarantined",
    "operator_paused",
    "source_uncertified",
    "source_expired",
    "snapshot_integrity_failed",
    "schema_quarantined",
    "extraction_incomplete",
    "display_conflict",
}
_SUCCESS_DISPOSITIONS = {
    "completed_unchanged",
    "completed_changed",
    "discovery_unchanged",
    "discovery_changed",
    "maintenance_completed",
}
_REVIEW_DISPOSITIONS = {"completed_with_review", "identity_review_required"}
_FAILED_DISPOSITIONS = {
    "attempted_policy_failed",
    "retry_exhausted",
    "dispatch_missed",
    "snapshot_integrity_failed",
    "schema_quarantined",
    "extraction_incomplete",
    "display_conflict",
}
_BLOCKED_DISPOSITIONS = {
    "policy_blocked",
    "terms_quarantined",
    "operator_paused",
    "source_uncertified",
    "source_expired",
}
_DUE_REASON_CODES = {"DUE_BY_SCHEDULE", "CATCH_UP_DUE", "RECONCILED_DUE", "DISPATCH_MISSED"}
_NOT_DUE_REASON_CODES = {"NOT_DUE_BY_POLICY", "MAINTENANCE_NOT_DUE"}
_BLOCKED_REASON_TO_TERMINAL = {
    "SOURCE_POLICY_BLOCKED": "policy_blocked",
    "TERMS_POLICY_BLOCKED": "terms_quarantined",
    "OPERATOR_PAUSED": "operator_paused",
    "SOURCE_REVISION_UNCERTIFIED": "source_uncertified",
    "SOURCE_REVISION_EXPIRED": "source_expired",
}
_TRANSIENT_CAUSES = {
    "BODY_TIMEOUT",
    "BODY_TRUNCATED",
    "CONNECT_FAILED",
    "CONNECT_TIMEOUT",
    "TIMEOUT",
    "CONNECTION_RESET",
    "DNS_RESOLUTION_FAILED",
    "HTTP_429",
    "HTTP_5XX",
    "REQUEST_TIMEOUT",
    "OBJECT_STORE_UNAVAILABLE",
    "DATABASE_SERIALIZATION",
    "DATABASE_DEADLOCK",
}
_NON_RETRYABLE_CAUSES = {
    "BODY_SIZE_EXCEEDED",
    "CONNECTED_PEER_PROOF_MISSING",
    "CONNECTED_PEER_UNSAFE",
    "CONTENT_LENGTH_EXCEEDED",
    "TERMS_UNAPPROVED",
    "CERTIFICATION_INVALID",
    "DNS_POLICY_FAILED",
    "DNS_REBIND_DETECTED",
    "UNSAFE_URL",
    "UNSAFE_DNS",
    "UNSAFE_PEER",
    "UNSAFE_REDIRECT",
    "MIME_UNAPPROVED",
    "MIME_MISMATCH",
    "REDIRECT_LIMIT_EXCEEDED",
    "REDIRECT_UNAPPROVED",
    "SIZE_LIMIT_EXCEEDED",
    "TLS_FAILED",
    "CONTRACT_MISMATCH",
    "SCHEMA_DRIFT",
    "EVIDENCE_DRIFT",
    "NONFINITE_SCORE",
    "IDENTITY_AMBIGUOUS",
    "DISPLAY_CONFLICT",
    "DIGEST_MISMATCH",
    "OBJECT_MISSING",
    "SECURITY_VIOLATION",
    "PRIVACY_VIOLATION",
    "OPERATOR_PAUSED",
}


def _fail(path: str, message: str) -> None:
    raise OperationsContractError(f"{path}: {message}")


def _walk_json(value: Any, path: str = "$") -> None:
    if value is None or type(value) in (str, bool, int):
        return
    if type(value) is float:
        if not math.isfinite(value):
            _fail(path, "non-finite numbers are forbidden")
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
    _fail(path, f"unsupported JSON type {type(value).__name__}")


def _normalized_for_digest(payload: dict[str, Any]) -> dict[str, Any]:
    material = deepcopy(payload)
    policy = material.get("policyVersion")
    manifest = material.get("manifest")
    if type(manifest) is not dict or "contentSha256" not in manifest:
        _fail("$.manifest.contentSha256", "is required for self-digesting")
    manifest["contentSha256"] = None
    if policy == "scheduled-cycle-v1":
        jobs = material.get("jobs")
        wakeups = material.get("wakeups")
        if type(jobs) is list:
            for job in jobs:
                if type(job) is dict and type(job.get("attemptReceiptIds")) is list:
                    job["attemptReceiptIds"] = sorted(
                        job["attemptReceiptIds"], key=canonical_json
                    )
            material["jobs"] = sorted(
                jobs,
                key=lambda item: canonical_json(
                    item.get("jobId") if type(item) is dict else item
                ),
            )
        if type(wakeups) is list:
            material["wakeups"] = sorted(
                wakeups,
                key=lambda item: canonical_json(
                    item.get("wakeupId") if type(item) is dict else item
                ),
            )
    elif policy == "scheduled-job-attempt-v1":
        references = material.get("outputReferences")
        if type(references) is list:
            material["outputReferences"] = sorted(
                references,
                key=canonical_json,
            )
    return material


def canonical_json(value: Any) -> str:
    """Return compact deterministic JSON without performing any I/O."""

    _walk_json(value)
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def contract_self_digest(payload: dict[str, Any]) -> str:
    """Digest a scheduling contract after contract-defined set normalization."""

    if type(payload) is not dict:
        _fail("$", "contract must be an object")
    return hashlib.sha256(
        canonical_json(_normalized_for_digest(payload)).encode("utf-8")
    ).hexdigest()


def _identity_digest(kind: str, fields: dict[str, Any]) -> str:
    return hashlib.sha256(
        canonical_json({"identityKind": kind, **fields}).encode("utf-8")
    ).hexdigest()


def derive_cycle_id(
    environment: str,
    lane: str,
    scheduled_for: str,
    schedule_policy_revision_id: str,
) -> str:
    """Derive identity without trigger, Queue, worker, or local-time facts."""

    _stable_id(environment, "environment")
    _enum(lane, _LANES, "lane")
    _utc(scheduled_for, "scheduledFor")
    _stable_id(schedule_policy_revision_id, "schedulePolicyRevisionId")
    return "cycle_" + _identity_digest(
        "schedule-cycle-v1",
        {
            "environment": environment,
            "lane": lane,
            "scheduledFor": scheduled_for,
            "schedulePolicyRevisionId": schedule_policy_revision_id,
        },
    )


def derive_job_id(
    environment: str,
    lane: str,
    target_revision_id: str,
    scheduled_for: str,
    schedule_policy_revision_id: str,
) -> str:
    """Derive the unique logical job identity required by SCH-01."""

    _stable_id(environment, "environment")
    _enum(lane, _LANES, "lane")
    _stable_id(target_revision_id, "targetRevisionId")
    _utc(scheduled_for, "scheduledFor")
    _stable_id(schedule_policy_revision_id, "schedulePolicyRevisionId")
    return "job_" + _identity_digest(
        "schedule-job-v1",
        {
            "environment": environment,
            "lane": lane,
            "targetRevisionId": target_revision_id,
            "scheduledFor": scheduled_for,
            "schedulePolicyRevisionId": schedule_policy_revision_id,
        },
    )


def derive_job_idempotency_key(
    environment: str,
    lane: str,
    target_revision_id: str,
    scheduled_for: str,
    schedule_policy_revision_id: str,
) -> str:
    return derive_job_id(
        environment,
        lane,
        target_revision_id,
        scheduled_for,
        schedule_policy_revision_id,
    ).removeprefix("job_")


def derive_attempt_id(job_id: str, attempt_number: int) -> str:
    _stable_id(job_id, "jobId")
    _integer(attempt_number, "attemptNumber", minimum=1, maximum=3)
    return "attempt_" + _identity_digest(
        "schedule-attempt-v1",
        {"jobId": job_id, "attemptNumber": attempt_number},
    )


def scheduled_slot_utc(anchor_utc: str, cadence_seconds: int, slot_ordinal: int) -> str:
    """Calculate a UTC slot without consulting local timezone or DST state."""

    anchor = _utc(anchor_utc, "anchorUtc")
    cadence = _integer(cadence_seconds, "cadenceSeconds", minimum=1)
    ordinal = _integer(slot_ordinal, "slotOrdinal", minimum=0)
    try:
        result = anchor + timedelta(seconds=cadence * ordinal)
    except OverflowError:
        _fail("slotOrdinal", "slot arithmetic exceeds the supported UTC range")
    return _format_utc(result)


def assert_current_fencing_token(current_fencing_token: int, presented_fencing_token: int) -> None:
    """Fail closed unless the commit presents the exact current monotonic token."""

    current = _integer(current_fencing_token, "currentFencingToken", minimum=1)
    presented = _integer(presented_fencing_token, "presentedFencingToken", minimum=1)
    if presented != current:
        _fail("presentedFencingToken", "stale or future fencing token cannot commit")


def validate_scheduled_job_planner_disposition(
    due_disposition: str, disposition_reason_code: str
) -> None:
    """Validate the frozen SCH-01 planner decision before dispatch."""

    due = _enum(
        due_disposition,
        {"due", "not_due", "blocked"},
        "dueDisposition",
    )
    reason = _reason(disposition_reason_code, "dispositionReasonCode")
    allowed = {
        "due": _DUE_REASON_CODES,
        "not_due": _NOT_DUE_REASON_CODES,
        "blocked": set(_BLOCKED_REASON_TO_TERMINAL),
    }[due]
    if reason not in allowed:
        _fail(
            "dispositionReasonCode",
            f"is not an allowlisted {due} planner reason",
        )


def _object(value: Any, path: str, keys: set[str]) -> dict[str, Any]:
    if type(value) is not dict:
        _fail(path, "must be an object")
    present = set(value)
    if present != keys:
        missing = sorted(keys - present)
        extra = sorted(present - keys)
        parts = []
        if missing:
            parts.append(f"missing keys {missing}")
        if extra:
            parts.append(f"unexpected keys {extra}")
        _fail(path, "; ".join(parts))
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


def _stable_id(value: Any, path: str, nullable: bool = False) -> str | None:
    if nullable and value is None:
        return None
    if type(value) is not str or _STABLE_ID.fullmatch(value) is None:
        _fail(path, "must be a stable lowercase identifier")
    return value


def _reason(value: Any, path: str) -> str:
    if type(value) is not str or _REASON_CODE.fullmatch(value) is None:
        _fail(path, "must be an uppercase reason code")
    return value


def _sha256(value: Any, path: str, nullable: bool = False) -> str | None:
    if nullable and value is None:
        return None
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        _fail(path, "must be a lowercase SHA-256 digest")
    return value


def _integer(
    value: Any,
    path: str,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    if type(value) is not int:
        _fail(path, "must be an integer")
    if minimum is not None and value < minimum:
        _fail(path, f"must be at least {minimum}")
    if maximum is not None and value > maximum:
        _fail(path, f"must be at most {maximum}")
    return value


def _utc(value: Any, path: str, nullable: bool = False) -> datetime | None:
    if nullable and value is None:
        return None
    if type(value) is not str or _UTC_TIMESTAMP.fullmatch(value) is None:
        _fail(path, "must be canonical UTC YYYY-MM-DDTHH:MM:SSZ")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        _fail(path, "must be a valid UTC timestamp")
    return parsed


def _format_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _authority(value: Any, path: str = "$.authority") -> None:
    authority = _object(value, path, _AUTHORITY_KEYS)
    _constant(authority["classification"], "schedule_receipt_only", f"{path}.classification")
    for key in (
        "certifiesSources",
        "authorizesCapture",
        "authorizesPublication",
        "frontendLoadable",
        "wakeupAuthoritative",
    ):
        _constant(authority[key], False, f"{path}.{key}")


def _manifest(value: Any, path: str, count_key: str, count: int) -> None:
    manifest = _object(value, path, {"algorithm", "contentSha256", count_key})
    _constant(manifest["algorithm"], _ALGORITHM, f"{path}.algorithm")
    _sha256(manifest["contentSha256"], f"{path}.contentSha256")
    _constant(manifest[count_key], count, f"{path}.{count_key}")


def _verify_digest(payload: dict[str, Any]) -> None:
    declared = payload["manifest"]["contentSha256"]
    actual = contract_self_digest(payload)
    if declared != actual:
        _fail(
            "$.manifest.contentSha256",
            f"self-digest mismatch (declared {declared}, computed {actual})",
        )


def _validate_output_reference(value: Any, path: str) -> dict[str, Any]:
    ref = _object(value, path, {"referenceType", "referenceId", "contentSha256"})
    _enum(
        ref["referenceType"],
        {
            "source_check_receipt",
            "discovery_receipt",
            "maintenance_receipt",
            "schedule_disposition_receipt",
            "source_snapshot",
            "discovery_observation",
            "quarantine_receipt",
            "incident",
        },
        f"{path}.referenceType",
    )
    _stable_id(ref["referenceId"], f"{path}.referenceId")
    _sha256(ref["contentSha256"], f"{path}.contentSha256")
    return ref


def validate_scheduled_cycle(payload: dict[str, Any]) -> None:
    """Validate a terminal scheduled-cycle receipt without side effects."""

    _walk_json(payload)
    root = _object(payload, "$", _CYCLE_KEYS)
    _constant(root["schemaVersion"], "1.0.0", "$.schemaVersion")
    _constant(root["policyVersion"], "scheduled-cycle-v1", "$.policyVersion")
    _constant(root["availability"], "operations_record_only", "$.availability")
    _enum(root["mode"], {"synthetic_fixture", "shadow", "production"}, "$.mode")
    environment = _stable_id(root["environment"], "$.environment")
    lane = _enum(root["lane"], _LANES, "$.lane")
    policy_id = _stable_id(root["schedulePolicyRevisionId"], "$.schedulePolicyRevisionId")
    _constant(root["state"], "terminal", "$.state")
    _authority(root["authority"])

    slot = _object(
        root["slot"],
        "$.slot",
        {
            "anchorUtc",
            "cadenceSeconds",
            "slotOrdinal",
            "scheduledFor",
            "nextScheduledFor",
            "completionWindowEndsAt",
            "catchUpDisposition",
            "missedSlotCount",
        },
    )
    cadence = _integer(slot["cadenceSeconds"], "$.slot.cadenceSeconds", minimum=1)
    ordinal = _integer(slot["slotOrdinal"], "$.slot.slotOrdinal", minimum=0)
    scheduled_for = scheduled_slot_utc(slot["anchorUtc"], cadence, ordinal)
    _constant(slot["scheduledFor"], scheduled_for, "$.slot.scheduledFor")
    next_scheduled = scheduled_slot_utc(slot["anchorUtc"], cadence, ordinal + 1)
    _constant(slot["nextScheduledFor"], next_scheduled, "$.slot.nextScheduledFor")
    completion = _utc(slot["completionWindowEndsAt"], "$.slot.completionWindowEndsAt")
    scheduled_dt = _utc(scheduled_for, "$.slot.scheduledFor")
    next_dt = _utc(next_scheduled, "$.slot.nextScheduledFor")
    assert completion is not None and scheduled_dt is not None and next_dt is not None
    if not scheduled_dt < completion <= next_dt:
        _fail("$.slot.completionWindowEndsAt", "must be after the slot and no later than the next slot")
    catch_up = _enum(
        slot["catchUpDisposition"],
        {"scheduled", "catch_up", "reconciled_missed"},
        "$.slot.catchUpDisposition",
    )
    missed = _integer(slot["missedSlotCount"], "$.slot.missedSlotCount", minimum=0)
    if (catch_up == "scheduled") != (missed == 0):
        _fail("$.slot.missedSlotCount", "scheduled slots require zero misses; catch-up slots require at least one")

    expected_cycle_id = derive_cycle_id(environment, lane, scheduled_for, policy_id)
    _constant(root["cycleId"], expected_cycle_id, "$.cycleId")

    wakeups = _array(root["wakeups"], "$.wakeups", minimum=1)
    wakeup_ids: set[str] = set()
    for index, raw in enumerate(wakeups):
        path = f"$.wakeups[{index}]"
        wakeup = _object(
            raw,
            path,
            {
                "wakeupId",
                "kind",
                "observedAt",
                "opaqueTriggerId",
                "deliveryAttempt",
                "authoritative",
            },
        )
        wakeup_id = _stable_id(wakeup["wakeupId"], f"{path}.wakeupId")
        if wakeup_id in wakeup_ids:
            _fail(f"{path}.wakeupId", "duplicate wake-up fact")
        wakeup_ids.add(wakeup_id)
        _enum(wakeup["kind"], _WAKEUP_KINDS, f"{path}.kind")
        _utc(wakeup["observedAt"], f"{path}.observedAt")
        _stable_id(wakeup["opaqueTriggerId"], f"{path}.opaqueTriggerId")
        _integer(wakeup["deliveryAttempt"], f"{path}.deliveryAttempt", minimum=1)
        _constant(wakeup["authoritative"], False, f"{path}.authoritative")

    jobs = _array(root["jobs"], "$.jobs")
    job_ids: set[str] = set()
    logical_keys: set[tuple[str, str, str, str, str]] = set()
    dispositions: list[tuple[str, str]] = []
    for index, raw in enumerate(jobs):
        path = f"$.jobs[{index}]"
        job = _object(
            raw,
            path,
            {
                "jobId",
                "idempotencyKeySha256",
                "targetType",
                "targetRevisionId",
                "sourceRevisionId",
                "dueDisposition",
                "dispositionReasonCode",
                "attemptReceiptIds",
                "attemptCount",
                "terminalDisposition",
                "terminalOutputReference",
            },
        )
        target_type = _enum(job["targetType"], _TARGET_TYPES, f"{path}.targetType")
        if target_type != _LANE_TARGET[lane]:
            _fail(f"{path}.targetType", "must match the cycle lane")
        target_revision = _stable_id(job["targetRevisionId"], f"{path}.targetRevisionId")
        source_revision = _stable_id(
            job["sourceRevisionId"], f"{path}.sourceRevisionId", nullable=True
        )
        if target_type == "source_revision":
            if source_revision != target_revision:
                _fail(f"{path}.sourceRevisionId", "recheck jobs must bind the exact target source revision")
        elif source_revision is not None:
            _fail(f"{path}.sourceRevisionId", "only recheck jobs may bind a source revision")
        expected_job_id = derive_job_id(
            environment, lane, target_revision, scheduled_for, policy_id
        )
        _constant(job["jobId"], expected_job_id, f"{path}.jobId")
        _constant(
            job["idempotencyKeySha256"],
            derive_job_idempotency_key(
                environment, lane, target_revision, scheduled_for, policy_id
            ),
            f"{path}.idempotencyKeySha256",
        )
        if expected_job_id in job_ids:
            _fail(f"{path}.jobId", "duplicate logical job")
        job_ids.add(expected_job_id)
        logical_key = (environment, lane, target_revision, scheduled_for, policy_id)
        if logical_key in logical_keys:
            _fail(f"{path}.targetRevisionId", "duplicate logical job tuple")
        logical_keys.add(logical_key)

        due = _enum(job["dueDisposition"], {"due", "not_due", "blocked"}, f"{path}.dueDisposition")
        reason_code = _reason(job["dispositionReasonCode"], f"{path}.dispositionReasonCode")
        terminal = _enum(job["terminalDisposition"], _TERMINAL_DISPOSITIONS, f"{path}.terminalDisposition")
        attempt_ids = _array(job["attemptReceiptIds"], f"{path}.attemptReceiptIds")
        validated_attempt_ids: list[str] = []
        for attempt_index, attempt_id in enumerate(attempt_ids):
            validated = _stable_id(
                attempt_id, f"{path}.attemptReceiptIds[{attempt_index}]"
            )
            assert validated is not None
            validated_attempt_ids.append(validated)
        if len(validated_attempt_ids) != len(set(validated_attempt_ids)):
            _fail(f"{path}.attemptReceiptIds", "duplicate attempt receipt ID")
        attempts = _integer(job["attemptCount"], f"{path}.attemptCount", minimum=0, maximum=3)
        if attempts != len(attempt_ids):
            _fail(f"{path}.attemptCount", "must equal the attempt receipt count")
        expected_attempt_ids = {
            derive_attempt_id(expected_job_id, number) for number in range(1, attempts + 1)
        }
        if set(validated_attempt_ids) != expected_attempt_ids:
            _fail(
                f"{path}.attemptReceiptIds",
                "must be the complete contiguous derived attempt-ID set",
            )
        output = _validate_output_reference(job["terminalOutputReference"], f"{path}.terminalOutputReference")

        if due == "not_due":
            if reason_code not in _NOT_DUE_REASON_CODES:
                _fail(f"{path}.dispositionReasonCode", "is not an allowlisted not-due reason")
            if attempts != 0 or terminal != "not_due":
                _fail(path, "not-due jobs require zero attempts and terminal not_due")
            if output["referenceType"] != "schedule_disposition_receipt":
                _fail(f"{path}.terminalOutputReference", "not-due jobs require a schedule disposition receipt")
        elif due == "blocked":
            expected_blocked_terminal = _BLOCKED_REASON_TO_TERMINAL.get(reason_code)
            if expected_blocked_terminal != terminal:
                _fail(
                    f"{path}.dispositionReasonCode",
                    "must be an allowlisted blocked reason matching terminalDisposition",
                )
            if attempts != 1 or terminal not in _BLOCKED_DISPOSITIONS:
                _fail(
                    path,
                    "blocked jobs require exactly one admission attempt and a blocked terminal disposition",
                )
        else:
            if reason_code not in _DUE_REASON_CODES:
                _fail(f"{path}.dispositionReasonCode", "is not an allowlisted due reason")
            if terminal == "dispatch_missed" and reason_code != "DISPATCH_MISSED":
                _fail(f"{path}.dispositionReasonCode", "missed dispatch requires DISPATCH_MISSED")
            if terminal in _BLOCKED_DISPOSITIONS or terminal == "not_due":
                _fail(path, "due jobs cannot use not-due or pre-execution blocked dispositions")
            if terminal == "dispatch_missed":
                if attempts != 0:
                    _fail(path, "a missed dispatch cannot have attempts")
            elif attempts < 1:
                _fail(path, "an executed due job requires at least one attempt receipt")
        expected_reference_type = {
            "discovery": "discovery_receipt",
            "recheck": "source_check_receipt",
            "maintenance": "maintenance_receipt",
        }[lane]
        if terminal in {"not_due", "dispatch_missed"}:
            expected_reference_type = "schedule_disposition_receipt"
        if output["referenceType"] != expected_reference_type:
            _fail(
                f"{path}.terminalOutputReference.referenceType",
                f"{lane}/{terminal} requires {expected_reference_type}",
            )
        dispositions.append((due, terminal))

    if catch_up == "reconciled_missed" and not any(
        terminal == "dispatch_missed" for _due, terminal in dispositions
    ):
        _fail("$.slot.catchUpDisposition", "reconciled_missed requires an explicit missed-dispatch job")

    counts = _object(
        root["counts"],
        "$.counts",
        {
            "expected",
            "due",
            "notDue",
            "blocked",
            "terminal",
            "succeeded",
            "reviewRequired",
            "failed",
        },
    )
    expected_counts = {
        "expected": len(jobs),
        "due": sum(due == "due" for due, _terminal in dispositions),
        "notDue": sum(due == "not_due" for due, _terminal in dispositions),
        "blocked": sum(due == "blocked" for due, _terminal in dispositions),
        "terminal": len(jobs),
        "succeeded": sum(terminal in _SUCCESS_DISPOSITIONS for _due, terminal in dispositions),
        "reviewRequired": sum(terminal in _REVIEW_DISPOSITIONS for _due, terminal in dispositions),
        "failed": sum(terminal in _FAILED_DISPOSITIONS for _due, terminal in dispositions),
    }
    for key, expected in expected_counts.items():
        _constant(counts[key], expected, f"$.counts.{key}")
    if counts["expected"] != counts["due"] + counts["notDue"] + counts["blocked"]:
        _fail("$.counts", "expected must balance due + notDue + blocked")
    if counts["due"] != counts["succeeded"] + counts["reviewRequired"] + counts["failed"]:
        _fail("$.counts", "due must balance succeeded + reviewRequired + failed")

    manifest = _object(
        root["manifest"],
        "$.manifest",
        {"algorithm", "contentSha256", "jobCount", "wakeupCount"},
    )
    _constant(manifest["algorithm"], _ALGORITHM, "$.manifest.algorithm")
    _sha256(manifest["contentSha256"], "$.manifest.contentSha256")
    _constant(manifest["jobCount"], len(jobs), "$.manifest.jobCount")
    _constant(manifest["wakeupCount"], len(wakeups), "$.manifest.wakeupCount")
    _verify_digest(root)


def validate_scheduled_job_attempt(payload: dict[str, Any]) -> None:
    """Validate one immutable attempt/fencing receipt without side effects."""

    _walk_json(payload)
    root = _object(payload, "$", _ATTEMPT_KEYS)
    _constant(root["schemaVersion"], "1.0.0", "$.schemaVersion")
    _constant(root["policyVersion"], "scheduled-job-attempt-v1", "$.policyVersion")
    _constant(root["availability"], "operations_record_only", "$.availability")
    _enum(root["mode"], {"synthetic_fixture", "shadow", "production"}, "$.mode")
    environment = _stable_id(root["environment"], "$.environment")
    lane = _enum(root["lane"], _LANES, "$.lane")
    policy_id = _stable_id(root["schedulePolicyRevisionId"], "$.schedulePolicyRevisionId")
    scheduled_for = root["scheduledFor"]
    _utc(scheduled_for, "$.scheduledFor")
    target_type = _enum(root["targetType"], _TARGET_TYPES, "$.targetType")
    if target_type != _LANE_TARGET[lane]:
        _fail("$.targetType", "must match the attempt lane")
    target_revision = _stable_id(root["targetRevisionId"], "$.targetRevisionId")
    source_revision = _stable_id(root["sourceRevisionId"], "$.sourceRevisionId", nullable=True)
    if target_type == "source_revision":
        if source_revision != target_revision:
            _fail("$.sourceRevisionId", "recheck attempts must bind the exact target source revision")
    elif source_revision is not None:
        _fail("$.sourceRevisionId", "only recheck attempts may bind a source revision")
    expected_cycle = derive_cycle_id(environment, lane, scheduled_for, policy_id)
    expected_job = derive_job_id(environment, lane, target_revision, scheduled_for, policy_id)
    _constant(root["cycleId"], expected_cycle, "$.cycleId")
    _constant(root["jobId"], expected_job, "$.jobId")
    attempt_number = _integer(root["attemptNumber"], "$.attemptNumber", minimum=1, maximum=3)
    _constant(root["maxAttempts"], 3, "$.maxAttempts")
    _constant(root["attemptId"], derive_attempt_id(expected_job, attempt_number), "$.attemptId")
    _sha256(root["workerIdentitySha256"], "$.workerIdentitySha256")
    _authority(root["authority"])

    wakeup = _object(
        root["wakeup"],
        "$.wakeup",
        {"kind", "opaqueDeliveryId", "deliveryAttempt", "authoritative"},
    )
    _enum(wakeup["kind"], _WAKEUP_KINDS, "$.wakeup.kind")
    _stable_id(wakeup["opaqueDeliveryId"], "$.wakeup.opaqueDeliveryId")
    _integer(wakeup["deliveryAttempt"], "$.wakeup.deliveryAttempt", minimum=1)
    _constant(wakeup["authoritative"], False, "$.wakeup.authoritative")

    lease = _object(
        root["lease"],
        "$.lease",
        {
            "leaseId",
            "fencingToken",
            "priorFencingToken",
            "acquiredAt",
            "expiresAt",
            "lastHeartbeatAt",
            "state",
            "commitPresentedToken",
            "commitDisposition",
        },
    )
    _stable_id(lease["leaseId"], "$.lease.leaseId")
    token = _integer(lease["fencingToken"], "$.lease.fencingToken", minimum=1)
    prior = lease["priorFencingToken"]
    if prior is not None:
        prior = _integer(prior, "$.lease.priorFencingToken", minimum=1)
        if token <= prior:
            _fail("$.lease.fencingToken", "must increase monotonically beyond priorFencingToken")
    elif token != 1:
        _fail("$.lease.priorFencingToken", "a token above one must bind its prior token")
    acquired = _utc(lease["acquiredAt"], "$.lease.acquiredAt")
    expires = _utc(lease["expiresAt"], "$.lease.expiresAt")
    heartbeat = _utc(lease["lastHeartbeatAt"], "$.lease.lastHeartbeatAt")
    assert acquired is not None and expires is not None and heartbeat is not None
    if not acquired <= heartbeat <= expires or acquired >= expires:
        _fail("$.lease", "heartbeat must fall inside a positive lease interval")
    lease_state = _enum(lease["state"], {"released", "expired", "superseded"}, "$.lease.state")
    commit_disposition = _enum(
        lease["commitDisposition"],
        {"accepted_current", "rejected_stale", "no_commit"},
        "$.lease.commitDisposition",
    )
    presented = lease["commitPresentedToken"]
    if commit_disposition == "accepted_current":
        presented = _integer(presented, "$.lease.commitPresentedToken", minimum=1)
        assert_current_fencing_token(token, presented)
        if lease_state != "released":
            _fail("$.lease.state", "accepted commits require a released lease receipt")
    elif commit_disposition == "rejected_stale":
        presented = _integer(presented, "$.lease.commitPresentedToken", minimum=1)
        if presented >= token or lease_state != "superseded":
            _fail("$.lease", "stale rejection requires an older presented token and superseded lease")
    elif presented is not None:
        _fail("$.lease.commitPresentedToken", "no_commit requires a null presented token")

    timing = _object(root["timing"], "$.timing", {"startedAt", "endedAt"})
    started = _utc(timing["startedAt"], "$.timing.startedAt")
    ended = _utc(timing["endedAt"], "$.timing.endedAt")
    assert started is not None and ended is not None
    if ended < started or started < acquired:
        _fail("$.timing", "attempt timing must be ordered after lease acquisition")
    if commit_disposition == "accepted_current" and ended > expires:
        _fail(
            "$.lease.expiresAt",
            "an expired lease cannot accept a current-token commit",
        )

    _enum(
        root["stageReached"],
        {
            "leased",
            "revision_admitted",
            "fetch_started",
            "not_modified",
            "bytes_received",
            "snapshot_committed",
            "schema_checked",
            "extraction_accounted",
            "claims_admitted",
            "discovery_accounted",
            "maintenance_completed",
        },
        "$.stageReached",
    )
    outcome = _enum(
        root["outcome"],
        {
            "succeeded",
            "retryable_failed",
            "retry_exhausted",
            "nonretryable_failed",
            "blocked",
            "stale_fenced",
        },
        "$.outcome",
    )
    cause = _reason(root["causeCode"], "$.causeCode")
    retry = _object(
        root["retry"],
        "$.retry",
        {
            "classification",
            "retryAt",
            "backoffSeconds",
            "retryAfterSource",
            "retryWindowEndsAt",
            "nextScheduledFor",
        },
    )
    classification = _enum(
        retry["classification"], {"none", "transient", "non_retryable"}, "$.retry.classification"
    )
    retry_window_end = _utc(retry["retryWindowEndsAt"], "$.retry.retryWindowEndsAt")
    next_scheduled = _utc(retry["nextScheduledFor"], "$.retry.nextScheduledFor")
    assert retry_window_end is not None and next_scheduled is not None
    if retry_window_end >= next_scheduled:
        _fail("$.retry.retryWindowEndsAt", "retry window must end before the next slot")

    if outcome == "retryable_failed":
        if classification != "transient" or cause not in _TRANSIENT_CAUSES:
            _fail("$.retry", "retryable outcomes require an allowlisted transient cause")
        if attempt_number >= root["maxAttempts"]:
            _fail("$.attemptNumber", "the final attempt cannot schedule another retry")
        retry_at = _utc(retry["retryAt"], "$.retry.retryAt")
        backoff = _integer(retry["backoffSeconds"], "$.retry.backoffSeconds", minimum=1)
        _enum(retry["retryAfterSource"], {"policy", "safe_retry_after"}, "$.retry.retryAfterSource")
        assert retry_at is not None
        try:
            expected_retry_at = ended + timedelta(seconds=backoff)
        except OverflowError:
            _fail("$.retry.backoffSeconds", "retry arithmetic exceeds the supported UTC range")
        if retry_at != expected_retry_at or retry_at > retry_window_end:
            _fail("$.retry.retryAt", "must equal endedAt + backoff and remain inside the retry window")
        if commit_disposition != "no_commit":
            _fail("$.lease.commitDisposition", "retryable failures cannot commit outputs")
    else:
        if retry["retryAt"] is not None or retry["backoffSeconds"] != 0:
            _fail("$.retry", "non-retried outcomes require null retryAt and zero backoff")
        _constant(retry["retryAfterSource"], "none", "$.retry.retryAfterSource")
        expected_class = (
            "none"
            if outcome in {"succeeded", "stale_fenced", "retry_exhausted"}
            else "non_retryable"
        )
        if classification != expected_class:
            _fail("$.retry.classification", f"{outcome} requires {expected_class}")
        if outcome in {"blocked", "nonretryable_failed"} and cause not in _NON_RETRYABLE_CAUSES:
            _fail("$.causeCode", "blocked/nonretryable outcomes require a non-retryable cause")

    if outcome == "succeeded":
        _constant(cause, "ATTEMPT_COMPLETED", "$.causeCode")
        if commit_disposition != "accepted_current":
            _fail("$.lease.commitDisposition", "successful attempts require a current fenced commit")
        if ended > expires:
            _fail("$.lease.expiresAt", "an expired lease cannot commit even with an old matching token")
        permitted_success_stages = {
            "recheck": {"not_modified", "extraction_accounted", "claims_admitted"},
            "discovery": {"discovery_accounted"},
            "maintenance": {"maintenance_completed"},
        }[lane]
        if root["stageReached"] not in permitted_success_stages:
            _fail("$.stageReached", "does not represent a terminal success for this lane")
    elif outcome == "stale_fenced":
        _constant(cause, "LEASE_FENCED", "$.causeCode")
        if commit_disposition != "rejected_stale":
            _fail("$.lease.commitDisposition", "stale attempts must record rejected_stale")
    elif outcome == "retry_exhausted":
        if cause not in _TRANSIENT_CAUSES or attempt_number != root["maxAttempts"]:
            _fail(
                "$.outcome",
                "retry_exhausted requires an allowlisted transient cause on the final attempt",
            )
        if commit_disposition != "no_commit":
            _fail("$.lease.commitDisposition", "retry exhaustion cannot commit worker outputs")

    references = _array(root["outputReferences"], "$.outputReferences")
    seen_refs: set[tuple[str, str]] = set()
    for index, raw in enumerate(references):
        ref = _validate_output_reference(raw, f"$.outputReferences[{index}]")
        key = (ref["referenceType"], ref["referenceId"])
        if key in seen_refs:
            _fail(f"$.outputReferences[{index}]", "duplicate output reference")
        seen_refs.add(key)
    if outcome == "stale_fenced" and references:
        _fail("$.outputReferences", "a fenced stale worker cannot commit output references")
    if outcome == "succeeded" and lane == "recheck" and not any(
        ref["referenceType"] == "source_check_receipt" for ref in references
    ):
        _fail("$.outputReferences", "successful recheck requires a source-check receipt reference")
    if outcome == "succeeded" and lane == "discovery" and not any(
        ref["referenceType"] == "discovery_receipt" for ref in references
    ):
        _fail("$.outputReferences", "successful discovery requires a discovery receipt reference")
    if outcome == "succeeded" and lane == "maintenance" and not any(
        ref["referenceType"] == "maintenance_receipt" for ref in references
    ):
        _fail("$.outputReferences", "successful maintenance requires a maintenance receipt reference")

    _manifest(root["manifest"], "$.manifest", "outputReferenceCount", len(references))
    _verify_digest(root)


def validate_scheduled_cycle_attempts(
    cycle: dict[str, Any], attempts: list[dict[str, Any]]
) -> None:
    """Cross-check a cycle's attempt denominator against immutable receipts."""

    validate_scheduled_cycle(cycle)
    attempt_rows = _array(attempts, "attempts")
    by_id: dict[str, dict[str, Any]] = {}
    for index, attempt in enumerate(attempt_rows):
        validate_scheduled_job_attempt(attempt)
        attempt_id = attempt["attemptId"]
        if attempt_id in by_id:
            _fail(f"attempts[{index}].attemptId", "duplicate attempt receipt")
        if attempt["cycleId"] != cycle["cycleId"]:
            _fail(f"attempts[{index}].cycleId", "attempt belongs to a different cycle")
        by_id[attempt_id] = attempt

    listed_ids = {
        attempt_id
        for job in cycle["jobs"]
        for attempt_id in job["attemptReceiptIds"]
    }
    if set(by_id) != listed_ids:
        _fail("attempts", "actual attempt receipts must exactly equal the cycle denominator")

    for job in cycle["jobs"]:
        job_attempts = sorted(
            (by_id[attempt_id] for attempt_id in job["attemptReceiptIds"]),
            key=lambda attempt: attempt["attemptNumber"],
        )
        if any(attempt["jobId"] != job["jobId"] for attempt in job_attempts):
            _fail("attempts", "attempt receipt is bound to the wrong logical job")
        expected_numbers = list(range(1, len(job_attempts) + 1))
        if [attempt["attemptNumber"] for attempt in job_attempts] != expected_numbers:
            _fail("attempts", "attempt numbers must be contiguous from one")
        for attempt in job_attempts:
            exact_bindings = {
                "mode": cycle["mode"],
                "environment": cycle["environment"],
                "lane": cycle["lane"],
                "schedulePolicyRevisionId": cycle["schedulePolicyRevisionId"],
                "scheduledFor": cycle["slot"]["scheduledFor"],
                "targetType": job["targetType"],
                "targetRevisionId": job["targetRevisionId"],
                "sourceRevisionId": job["sourceRevisionId"],
            }
            for field, expected in exact_bindings.items():
                if attempt[field] != expected:
                    _fail(
                        "attempts",
                        f"attempt {field} must exactly bind its cycle job",
                    )
            if attempt["retry"]["retryWindowEndsAt"] != cycle["slot"]["completionWindowEndsAt"]:
                _fail(
                    "attempts",
                    "attempt retry window must equal the cycle completion window",
                )
            if attempt["retry"]["nextScheduledFor"] != cycle["slot"]["nextScheduledFor"]:
                _fail(
                    "attempts",
                    "attempt next scheduled time must equal the cycle next slot",
                )
        tokens = [attempt["lease"]["fencingToken"] for attempt in job_attempts]
        if any(current <= prior for prior, current in zip(tokens, tokens[1:])):
            _fail("attempts", "fencing tokens must increase across attempts")
        for prior_attempt, current_attempt in zip(job_attempts, job_attempts[1:]):
            if current_attempt["lease"]["priorFencingToken"] != prior_attempt["lease"]["fencingToken"]:
                _fail(
                    "attempts",
                    "each replacement lease must bind the preceding attempt's fencing token",
                )
            if prior_attempt["outcome"] not in {"retryable_failed", "stale_fenced"}:
                _fail(
                    "attempts",
                    "only a retryable or stale-fenced attempt may precede another attempt",
                )
            if prior_attempt["outcome"] == "retryable_failed":
                retry_at = _utc(prior_attempt["retry"]["retryAt"], "attempts.retryAt")
                retry_window_end = _utc(
                    prior_attempt["retry"]["retryWindowEndsAt"],
                    "attempts.retryWindowEndsAt",
                )
                next_acquired = _utc(
                    current_attempt["lease"]["acquiredAt"],
                    "attempts.lease.acquiredAt",
                )
                assert retry_at is not None and retry_window_end is not None and next_acquired is not None
                if not retry_at <= next_acquired <= retry_window_end:
                    _fail(
                        "attempts",
                        "a retry lease must be acquired inside the preceding retry window",
                    )

        terminal = job["terminalDisposition"]
        if not job_attempts:
            continue
        last_outcome = job_attempts[-1]["outcome"]
        terminal_reference = job["terminalOutputReference"]
        terminal_reference_key = (
            terminal_reference["referenceType"],
            terminal_reference["referenceId"],
            terminal_reference["contentSha256"],
        )
        final_reference_keys = {
            (reference["referenceType"], reference["referenceId"], reference["contentSha256"])
            for reference in job_attempts[-1]["outputReferences"]
        }
        if terminal_reference_key not in final_reference_keys:
            _fail(
                "attempts",
                "cycle terminal output must exactly bind a final-attempt output reference",
            )
        if terminal in _SUCCESS_DISPOSITIONS | _REVIEW_DISPOSITIONS:
            if last_outcome != "succeeded":
                _fail("attempts", "successful/review terminal job requires a successful final attempt")
        elif terminal == "retry_exhausted":
            if last_outcome != "retry_exhausted":
                _fail("attempts", "retry_exhausted job requires a retry_exhausted final attempt")
        elif terminal in _BLOCKED_DISPOSITIONS:
            if last_outcome != "blocked":
                _fail("attempts", "blocked terminal job requires a blocked admission attempt")
        elif terminal in _FAILED_DISPOSITIONS and last_outcome != "nonretryable_failed":
            _fail("attempts", "failed terminal job requires a current non-retryable final attempt")


__all__ = [
    "OperationsContractError",
    "assert_current_fencing_token",
    "canonical_json",
    "contract_self_digest",
    "derive_attempt_id",
    "derive_cycle_id",
    "derive_job_id",
    "derive_job_idempotency_key",
    "scheduled_slot_utc",
    "validate_scheduled_cycle",
    "validate_scheduled_cycle_attempts",
    "validate_scheduled_job_planner_disposition",
    "validate_scheduled_job_attempt",
]
