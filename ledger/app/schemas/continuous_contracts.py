"""Pure cross-document checks for continuous collection receipts.

Individual wire validators prove the internal consistency of one scheduling or
source-check document.  This module closes the composition boundary: a recheck
attempt may account for a source-check receipt only when the immutable
identities, schedule slot, source revision, fencing token, execution interval,
terminal semantics, and exact output digest agree.

The validator is deliberately side-effect free and standard-library-only.  It
does not resolve a database reference, read a clock, fetch a source, commit an
output, or confer certification/publication authority.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .operations_contracts import (
    OperationsContractError,
    validate_scheduled_cycle_attempts,
    validate_scheduled_job_attempt,
)
from .source_contracts import (
    SourceContractError,
    validate_source_check_receipt,
)


class ContinuousContractError(ValueError):
    """Raised when independently valid continuous-operation records disagree."""


_OUTCOMES_BY_SOURCE_TERMINAL = {
    "completed_unchanged": {"succeeded"},
    "completed_changed": {"succeeded"},
    "completed_with_review": {"succeeded"},
    "identity_review_required": {"succeeded"},
    "policy_blocked": {"blocked"},
    "terms_quarantined": {"blocked"},
    "operator_paused": {"blocked"},
    "retryable_failed": {"retryable_failed", "retry_exhausted"},
    "attempted_policy_failed": {"nonretryable_failed"},
    "schema_quarantined": {"nonretryable_failed"},
    "snapshot_integrity_failed": {"nonretryable_failed"},
    "extraction_incomplete": {"nonretryable_failed"},
    "display_conflict": {"nonretryable_failed"},
}

_STAGES_BY_SOURCE_TERMINAL = {
    "completed_unchanged": {"not_modified"},
    "completed_changed": {"claims_admitted"},
    "completed_with_review": {"extraction_accounted", "claims_admitted"},
    "identity_review_required": {"extraction_accounted", "claims_admitted"},
    "policy_blocked": {"leased", "revision_admitted"},
    "terms_quarantined": {"leased", "revision_admitted"},
    "operator_paused": {"leased", "revision_admitted"},
    "retryable_failed": {"fetch_started", "bytes_received"},
    "attempted_policy_failed": {"fetch_started", "bytes_received"},
    "schema_quarantined": {"schema_checked"},
    "snapshot_integrity_failed": {"bytes_received"},
    "extraction_incomplete": {"extraction_accounted"},
    "display_conflict": {"extraction_accounted", "claims_admitted"},
}

_FIXED_CAUSE_BY_SOURCE_TERMINAL = {
    "terms_quarantined": "TERMS_UNAPPROVED",
    "operator_paused": "OPERATOR_PAUSED",
    "schema_quarantined": "SCHEMA_DRIFT",
    "snapshot_integrity_failed": "DIGEST_MISMATCH",
    "extraction_incomplete": "EVIDENCE_DRIFT",
    "display_conflict": "DISPLAY_CONFLICT",
}

_CERTIFICATION_FAILURES = {"missing", "expired", "mismatch", "quarantined", "revoked"}
_CERTIFIED_POLICY_BLOCK_CAUSES = {
    "CONTRACT_MISMATCH",
    "PRIVACY_VIOLATION",
    "SECURITY_VIOLATION",
    "UNSAFE_URL",
}

_CYCLE_TERMINAL_BY_SOURCE_TERMINAL = {
    "completed_unchanged": "completed_unchanged",
    "completed_changed": "completed_changed",
    "completed_with_review": "completed_with_review",
    "identity_review_required": "identity_review_required",
    "terms_quarantined": "terms_quarantined",
    "operator_paused": "operator_paused",
    "retryable_failed": "retry_exhausted",
    "attempted_policy_failed": "attempted_policy_failed",
    "schema_quarantined": "schema_quarantined",
    "snapshot_integrity_failed": "snapshot_integrity_failed",
    "extraction_incomplete": "extraction_incomplete",
    "display_conflict": "display_conflict",
}


def _fail(path: str, message: str) -> None:
    raise ContinuousContractError(f"{path}: {message}")


def _utc(value: str) -> datetime:
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except (TypeError, ValueError):  # defensive; document validators run first
        _fail("$", "nested validators accepted a non-canonical UTC timestamp")


def _validate_terminal_semantics(
    attempt: dict[str, Any], receipt: dict[str, Any]
) -> None:
    terminal = receipt["terminalDisposition"]
    outcome = attempt["outcome"]
    if outcome not in _OUTCOMES_BY_SOURCE_TERMINAL[terminal]:
        _fail(
            "$.outcome",
            f"{outcome!r} contradicts source terminal {terminal!r}",
        )

    stage = attempt["stageReached"]
    if stage not in _STAGES_BY_SOURCE_TERMINAL[terminal]:
        _fail(
            "$.stageReached",
            f"{stage!r} contradicts source terminal {terminal!r}",
        )

    cause = attempt["causeCode"]
    if terminal in {
        "completed_unchanged",
        "completed_changed",
        "completed_with_review",
        "identity_review_required",
    }:
        if cause != "ATTEMPT_COMPLETED":
            _fail("$.causeCode", "completed/review source checks require ATTEMPT_COMPLETED")
    elif terminal == "policy_blocked":
        certification = receipt["certificationCheck"]["outcome"]
        allowed = (
            {"CERTIFICATION_INVALID"}
            if certification in _CERTIFICATION_FAILURES
            else _CERTIFIED_POLICY_BLOCK_CAUSES
        )
        if cause not in allowed:
            _fail(
                "$.causeCode",
                "policy-block cause does not match the recorded certification state",
            )
    elif terminal in _FIXED_CAUSE_BY_SOURCE_TERMINAL:
        expected = _FIXED_CAUSE_BY_SOURCE_TERMINAL[terminal]
        if cause != expected:
            _fail("$.causeCode", f"{terminal} requires exact cause {expected}")
    elif terminal in {"retryable_failed", "attempted_policy_failed"}:
        failure_code = receipt["request"]["failureCode"]
        if failure_code is None or cause != failure_code:
            _fail(
                "$.causeCode",
                "attempt cause must preserve the exact typed source request failure code",
            )

    if outcome == "retry_exhausted" and attempt["attemptNumber"] != attempt["maxAttempts"]:
        _fail("$.attemptNumber", "retry exhaustion must be the final bounded attempt")


def _validate_output_bindings(
    attempt: dict[str, Any], receipt: dict[str, Any]
) -> None:
    references = attempt["outputReferences"]
    source_references = [
        reference
        for reference in references
        if reference["referenceType"] == "source_check_receipt"
    ]
    if len(source_references) != 1:
        _fail(
            "$.attempt.outputReferences",
            "one recheck attempt must bind exactly one source-check receipt",
        )
    expected_source_reference = {
        "referenceType": "source_check_receipt",
        "referenceId": receipt["receiptId"],
        "contentSha256": receipt["manifest"]["contentSha256"],
    }
    if source_references[0] != expected_source_reference:
        _fail(
            "$.attempt.outputReferences",
            "source-check output ID and digest must exactly match the bound receipt",
        )

    snapshot = receipt["snapshot"]
    conditional = receipt["conditionalMetadata"]
    expected_snapshot_reference: dict[str, str] | None = None
    if snapshot["snapshotId"] is not None:
        expected_snapshot_reference = {
            "referenceType": "source_snapshot",
            "referenceId": snapshot["snapshotId"],
            "contentSha256": snapshot["snapshotContentSha256"],
        }
    elif receipt["terminalDisposition"] == "completed_unchanged":
        expected_snapshot_reference = {
            "referenceType": "source_snapshot",
            "referenceId": conditional["previousSnapshotId"],
            "contentSha256": conditional["previousSnapshotContentSha256"],
        }
    snapshot_references = [
        reference
        for reference in references
        if reference["referenceType"] == "source_snapshot"
    ]
    expected_snapshot_references = (
        [] if expected_snapshot_reference is None else [expected_snapshot_reference]
    )
    if snapshot_references != expected_snapshot_references:
        _fail(
            "$.attempt.outputReferences",
            "snapshot output must exactly match the new or reused receipt snapshot",
        )

    incident_reference_ids = {
        reference["referenceId"]
        for reference in references
        if reference["referenceType"] == "incident"
    }
    if incident_reference_ids != set(receipt["incidentReferences"]):
        _fail(
            "$.attempt.outputReferences",
            "incident output IDs must exactly equal the source receipt incident denominator",
        )


def _expected_cycle_terminal(receipt: dict[str, Any]) -> str:
    terminal = receipt["terminalDisposition"]
    if terminal != "policy_blocked":
        return _CYCLE_TERMINAL_BY_SOURCE_TERMINAL[terminal]
    certification = receipt["certificationCheck"]["outcome"]
    if certification == "expired":
        return "source_expired"
    if certification in {"missing", "mismatch", "quarantined", "revoked"}:
        return "source_uncertified"
    return "policy_blocked"


def validate_recheck_attempt_receipt(
    attempt: dict[str, Any],
    receipt: dict[str, Any],
    *,
    source_contract: dict[str, Any] | None = None,
) -> None:
    """Validate the exact composition of one recheck attempt and check receipt.

    ``source_contract`` may be omitted only for synthetic evidence. Operational
    composition must supply the exact immutable source contract revision; the
    validator still does not prove durable lookup or decision authority.
    """

    try:
        validate_scheduled_job_attempt(attempt)
    except OperationsContractError as exc:
        _fail("$.attempt", f"invalid scheduled attempt: {exc}")
    try:
        validate_source_check_receipt(receipt, source_contract=source_contract)
    except SourceContractError as exc:
        _fail("$.sourceCheckReceipt", f"invalid source-check receipt: {exc}")

    if attempt["lane"] != "recheck" or attempt["targetType"] != "source_revision":
        _fail("$.attempt.lane", "only a source-revision recheck may bind a source-check receipt")

    identity = receipt["identity"]
    exact_bindings = {
        "sourceRevisionId": (
            attempt["sourceRevisionId"],
            identity["sourceRevisionId"],
        ),
        "schedulePolicyRevisionId": (
            attempt["schedulePolicyRevisionId"],
            identity["schedulePolicyRevisionId"],
        ),
        "scheduledSlot": (attempt["scheduledFor"], identity["scheduledSlot"]),
        "jobId": (attempt["jobId"], identity["jobId"]),
        "attemptId": (attempt["attemptId"], identity["attemptId"]),
        "attemptNumber": (attempt["attemptNumber"], identity["attemptNumber"]),
        "fencingToken": (
            attempt["lease"]["fencingToken"],
            identity["fencingToken"],
        ),
        "expectedFencingToken": (
            attempt["lease"]["fencingToken"],
            identity["expectedFencingToken"],
        ),
    }
    for field, (expected, observed) in exact_bindings.items():
        if type(observed) is not type(expected) or observed != expected:
            _fail(
                f"$.sourceCheckReceipt.identity.{field}",
                "does not exactly bind the scheduled recheck attempt",
            )

    synthetic_attempt = attempt["mode"] == "synthetic_fixture"
    synthetic_receipt = receipt["availability"] == "synthetic_evidence_only"
    if synthetic_attempt != synthetic_receipt:
        _fail(
            "$.sourceCheckReceipt.availability",
            "synthetic and operational records cannot be composed across modes",
        )
    if not synthetic_receipt and source_contract is None:
        _fail(
            "$.sourceContract",
            "operational source-check composition requires the exact source contract",
        )

    _validate_output_bindings(attempt, receipt)

    attempt_started = _utc(attempt["timing"]["startedAt"])
    attempt_ended = _utc(attempt["timing"]["endedAt"])
    check_started = _utc(receipt["execution"]["startedAt"])
    check_finished = _utc(receipt["execution"]["finishedAt"])
    if check_started < attempt_started or check_finished > attempt_ended:
        _fail(
            "$.sourceCheckReceipt.execution",
            "source-check execution must be contained by its scheduled attempt interval",
        )

    if attempt["outcome"] in {"succeeded", "blocked", "nonretryable_failed"}:
        if attempt["lease"]["commitDisposition"] != "accepted_current":
            _fail(
                "$.attempt.lease.commitDisposition",
                "a terminal source-check receipt requires a current fenced commit",
            )

    _validate_terminal_semantics(attempt, receipt)


def validate_recheck_cycle_receipts(
    cycle: dict[str, Any],
    attempts: list[dict[str, Any]],
    receipts: list[dict[str, Any]],
    *,
    source_contracts_by_revision: dict[str, dict[str, Any]] | None = None,
) -> None:
    """Reconcile every recheck attempt, receipt, and terminal cycle reference.

    The supplied arrays are exact denominators. Missing, extra, duplicate, or
    digest-conflicting receipts fail; no row is selected by insertion order.
    Operational receipts additionally require one exact source contract for
    each used source revision.
    """

    try:
        validate_scheduled_cycle_attempts(cycle, attempts)
    except OperationsContractError as exc:
        _fail("$.cycle", f"invalid scheduled cycle/attempt composition: {exc}")
    if cycle["lane"] != "recheck":
        _fail("$.cycle.lane", "only a recheck cycle may bind source-check receipts")
    if type(receipts) is not list:
        _fail("$.receipts", "must be an exact array of source-check receipts")
    contracts = source_contracts_by_revision or {}
    if type(contracts) is not dict:
        _fail("$.sourceContractsByRevision", "must be an object keyed by source revision")

    expected_receipt_keys: list[tuple[str, str]] = []
    attempts_by_id: dict[str, dict[str, Any]] = {}
    for index, attempt in enumerate(attempts):
        attempts_by_id[attempt["attemptId"]] = attempt
        source_refs = [
            reference
            for reference in attempt["outputReferences"]
            if reference["referenceType"] == "source_check_receipt"
        ]
        if len(source_refs) != 1:
            _fail(
                f"$.attempts[{index}].outputReferences",
                "each recheck attempt must expose exactly one source-check receipt",
            )
        expected_receipt_keys.append(
            (source_refs[0]["referenceId"], source_refs[0]["contentSha256"])
        )
    if len(expected_receipt_keys) != len(set(expected_receipt_keys)):
        _fail("$.attempts", "multiple attempts cannot claim the same receipt ID/digest")

    receipts_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    receipt_ids: set[str] = set()
    for index, receipt in enumerate(receipts):
        if type(receipt) is not dict or type(receipt.get("manifest")) is not dict:
            _fail(f"$.receipts[{index}]", "must be a source-check receipt object")
        receipt_id = receipt.get("receiptId")
        content_digest = receipt["manifest"].get("contentSha256")
        if type(receipt_id) is not str or type(content_digest) is not str:
            _fail(f"$.receipts[{index}]", "must expose a receipt ID and content digest")
        if receipt_id in receipt_ids:
            _fail(f"$.receipts[{index}].receiptId", "duplicate/conflicting receipt ID")
        receipt_ids.add(receipt_id)
        receipts_by_key[(receipt_id, content_digest)] = receipt
    if set(receipts_by_key) != set(expected_receipt_keys):
        _fail(
            "$.receipts",
            "supplied receipts must exactly equal every attempt output ID/digest",
        )

    receipt_by_attempt_id: dict[str, dict[str, Any]] = {}
    used_source_revisions: set[str] = set()
    for attempt, receipt_key in zip(attempts, expected_receipt_keys, strict=True):
        receipt = receipts_by_key[receipt_key]
        source_revision = attempt["sourceRevisionId"]
        source_contract = contracts.get(source_revision)
        validate_recheck_attempt_receipt(
            attempt,
            receipt,
            source_contract=source_contract,
        )
        receipt_by_attempt_id[attempt["attemptId"]] = receipt
        if source_contract is not None:
            used_source_revisions.add(source_revision)
    if set(contracts) != used_source_revisions:
        _fail(
            "$.sourceContractsByRevision",
            "contract mapping must contain exactly the source revisions used by receipts",
        )

    for job in cycle["jobs"]:
        if not job["attemptReceiptIds"]:
            continue
        final_attempt = max(
            (attempts_by_id[attempt_id] for attempt_id in job["attemptReceiptIds"]),
            key=lambda row: row["attemptNumber"],
        )
        final_receipt = receipt_by_attempt_id[final_attempt["attemptId"]]
        expected_terminal = _expected_cycle_terminal(final_receipt)
        if job["terminalDisposition"] != expected_terminal:
            _fail(
                "$.cycle.jobs",
                "job terminal disposition contradicts its final source-check receipt",
            )


__all__ = [
    "ContinuousContractError",
    "validate_recheck_attempt_receipt",
    "validate_recheck_cycle_receipts",
]
