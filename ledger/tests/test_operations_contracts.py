from __future__ import annotations

import ast
from copy import deepcopy
import json
import math
from pathlib import Path
import sys

import pytest

from app.schemas.operations_contracts import (
    OperationsContractError,
    assert_current_fencing_token,
    canonical_json,
    contract_self_digest,
    derive_attempt_id,
    derive_cycle_id,
    derive_job_id,
    derive_job_idempotency_key,
    scheduled_slot_utc,
    validate_scheduled_cycle,
    validate_scheduled_cycle_attempts,
    validate_scheduled_job_attempt,
)


ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "docs" / "contracts" / "examples"
MODULE = ROOT / "ledger" / "app" / "schemas" / "operations_contracts.py"


def _load(name: str) -> dict:
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


def _cycle() -> dict:
    return _load("scheduled-cycle-v1.valid.json")


def _attempt() -> dict:
    return _load("scheduled-job-attempt-v1.valid.json")


def _resign(payload: dict) -> None:
    payload["manifest"]["contentSha256"] = "0" * 64
    payload["manifest"]["contentSha256"] = contract_self_digest(payload)


def _retryable_attempt() -> dict:
    payload = _attempt()
    payload["stageReached"] = "fetch_started"
    payload["outcome"] = "retryable_failed"
    payload["causeCode"] = "TIMEOUT"
    payload["retry"].update(
        {
            "classification": "transient",
            "retryAt": "2026-07-15T00:03:00Z",
            "backoffSeconds": 60,
            "retryAfterSource": "policy",
        }
    )
    payload["lease"].update(
        {
            "state": "expired",
            "commitPresentedToken": None,
            "commitDisposition": "no_commit",
        }
    )
    payload["outputReferences"] = []
    payload["manifest"]["outputReferenceCount"] = 0
    _resign(payload)
    return payload


def _stale_attempt() -> dict:
    payload = _attempt()
    payload["outcome"] = "stale_fenced"
    payload["causeCode"] = "LEASE_FENCED"
    payload["stageReached"] = "snapshot_committed"
    payload["lease"].update(
        {
            "fencingToken": 2,
            "priorFencingToken": 1,
            "state": "superseded",
            "commitPresentedToken": 1,
            "commitDisposition": "rejected_stale",
        }
    )
    payload["outputReferences"] = []
    payload["manifest"]["outputReferenceCount"] = 0
    _resign(payload)
    return payload


def _exhausted_attempt() -> dict:
    payload = _retryable_attempt()
    payload["attemptNumber"] = 3
    payload["attemptId"] = derive_attempt_id(payload["jobId"], 3)
    payload["outcome"] = "retry_exhausted"
    payload["retry"].update(
        {
            "classification": "none",
            "retryAt": None,
            "backoffSeconds": 0,
            "retryAfterSource": "none",
        }
    )
    _resign(payload)
    return payload


def _append_not_due_job(payload: dict) -> None:
    environment = payload["environment"]
    lane = payload["lane"]
    scheduled = payload["slot"]["scheduledFor"]
    policy = payload["schedulePolicyRevisionId"]
    target = "source-revision-example-v2"
    payload["jobs"].append(
        {
            "jobId": derive_job_id(environment, lane, target, scheduled, policy),
            "idempotencyKeySha256": derive_job_idempotency_key(
                environment, lane, target, scheduled, policy
            ),
            "targetType": "source_revision",
            "targetRevisionId": target,
            "sourceRevisionId": target,
            "dueDisposition": "not_due",
            "dispositionReasonCode": "NOT_DUE_BY_POLICY",
            "attemptReceiptIds": [],
            "attemptCount": 0,
            "terminalDisposition": "not_due",
            "terminalOutputReference": {
                "referenceType": "schedule_disposition_receipt",
                "referenceId": "schedule-disposition-example-v2",
                "contentSha256": "4" * 64,
            },
        }
    )
    payload["counts"].update({"expected": 2, "notDue": 1, "terminal": 2})
    payload["manifest"]["jobCount"] = 2


def test_valid_synthetic_examples_pass_and_are_non_authoritative() -> None:
    cycle = _cycle()
    attempt = _attempt()

    validate_scheduled_cycle(cycle)
    validate_scheduled_job_attempt(attempt)

    assert cycle["mode"] == attempt["mode"] == "synthetic_fixture"
    assert cycle["authority"] == attempt["authority"]
    assert all(value is False for key, value in cycle["authority"].items() if key != "classification")
    assert all(wakeup["authoritative"] is False for wakeup in cycle["wakeups"])


def test_example_self_digests_are_exact() -> None:
    for payload in (_cycle(), _attempt()):
        assert contract_self_digest(payload) == payload["manifest"]["contentSha256"]


def test_canonical_json_is_compact_ascii_sorted_and_rejects_nonfinite() -> None:
    assert canonical_json({"z": "café", "a": 1}) == '{"a":1,"z":"caf\\u00e9"}'
    with pytest.raises(OperationsContractError, match="non-finite"):
        canonical_json({"value": math.nan})


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_contract_digest_rejects_nonfinite_anywhere(value: float) -> None:
    payload = _cycle()
    payload["counts"]["expected"] = value
    with pytest.raises(OperationsContractError, match="non-finite"):
        contract_self_digest(payload)


def test_extreme_slot_and_retry_arithmetic_fail_with_typed_contract_errors() -> None:
    with pytest.raises(OperationsContractError, match="supported UTC range"):
        scheduled_slot_utc("2026-01-01T00:00:00Z", 10**100, 10**100)

    payload = _retryable_attempt()
    payload["retry"]["backoffSeconds"] = 10**100
    payload["retry"]["retryAt"] = "2026-07-15T00:03:00Z"
    _resign(payload)
    with pytest.raises(OperationsContractError, match="retry arithmetic"):
        validate_scheduled_job_attempt(payload)


def test_malformed_mixed_attempt_id_array_fails_typed_not_during_digest_sort() -> None:
    payload = _cycle()
    payload["jobs"][0]["attemptReceiptIds"] = [{"raw": "value"}, "attempt_fabricated"]
    payload["jobs"][0]["attemptCount"] = 2
    _resign(payload)
    with pytest.raises(OperationsContractError, match="stable lowercase"):
        validate_scheduled_cycle(payload)


def test_utc_slot_arithmetic_is_dst_and_local_timezone_independent() -> None:
    # These UTC slots straddle US DST transitions, but remain exact one-hour UTC steps.
    assert scheduled_slot_utc("2026-03-08T00:00:00Z", 3600, 7) == "2026-03-08T07:00:00Z"
    assert scheduled_slot_utc("2026-11-01T00:00:00Z", 3600, 6) == "2026-11-01T06:00:00Z"
    assert scheduled_slot_utc("2026-01-01T00:00:00Z", 43200, 390) == "2026-07-15T00:00:00Z"


@pytest.mark.parametrize(
    "bad_timestamp",
    [
        "2026-07-14T20:00:00-04:00",
        "2026-07-15T00:00:00+00:00",
        "2026-07-15 00:00:00Z",
        "2026-07-15T00:00:00.000Z",
    ],
)
def test_noncanonical_or_local_timestamp_is_rejected(bad_timestamp: str) -> None:
    payload = _cycle()
    payload["slot"]["scheduledFor"] = bad_timestamp
    _resign(payload)
    with pytest.raises(OperationsContractError, match="scheduledFor|canonical UTC"):
        validate_scheduled_cycle(payload)


def test_duplicate_trigger_redelivery_keeps_one_cycle_and_job_identity() -> None:
    payload = _cycle()
    before_cycle = payload["cycleId"]
    before_job = payload["jobs"][0]["jobId"]
    payload["wakeups"].append(
        {
            "wakeupId": "wakeup-example-third-delivery",
            "kind": "queue",
            "observedAt": "2026-07-15T00:00:08Z",
            "opaqueTriggerId": "trigger-example-390",
            "deliveryAttempt": 3,
            "authoritative": False,
        }
    )
    payload["manifest"]["wakeupCount"] = 3
    _resign(payload)

    validate_scheduled_cycle(payload)
    assert payload["cycleId"] == before_cycle
    assert payload["jobs"][0]["jobId"] == before_job
    assert len(payload["jobs"]) == 1


def test_cycle_and_job_identity_exclude_wakeup_and_worker_facts() -> None:
    cycle = _cycle()
    assert cycle["cycleId"] == derive_cycle_id(
        cycle["environment"],
        cycle["lane"],
        cycle["slot"]["scheduledFor"],
        cycle["schedulePolicyRevisionId"],
    )
    job = cycle["jobs"][0]
    assert job["jobId"] == derive_job_id(
        cycle["environment"],
        cycle["lane"],
        job["targetRevisionId"],
        cycle["slot"]["scheduledFor"],
        cycle["schedulePolicyRevisionId"],
    )


def test_cycle_digest_is_deterministic_under_set_like_reordering() -> None:
    payload = _cycle()
    _append_not_due_job(payload)
    _resign(payload)
    validate_scheduled_cycle(payload)
    expected = contract_self_digest(payload)

    payload["jobs"].reverse()
    payload["wakeups"].reverse()
    payload["jobs"][1]["attemptReceiptIds"].reverse()
    assert contract_self_digest(payload) == expected
    validate_scheduled_cycle(payload)


def test_attempt_digest_is_deterministic_under_output_reference_reordering() -> None:
    payload = _attempt()
    expected = contract_self_digest(payload)
    payload["outputReferences"].reverse()
    assert contract_self_digest(payload) == expected
    validate_scheduled_job_attempt(payload)


@pytest.mark.parametrize(
    "field",
    ["expected", "due", "notDue", "blocked", "terminal", "succeeded", "reviewRequired", "failed"],
)
def test_cycle_rejects_every_count_mismatch(field: str) -> None:
    payload = _cycle()
    payload["counts"][field] += 1
    _resign(payload)
    with pytest.raises(OperationsContractError, match=field):
        validate_scheduled_cycle(payload)


def test_cycle_rejects_duplicate_logical_job() -> None:
    payload = _cycle()
    payload["jobs"].append(deepcopy(payload["jobs"][0]))
    payload["counts"].update({"expected": 2, "due": 2, "terminal": 2, "succeeded": 2})
    payload["manifest"]["jobCount"] = 2
    _resign(payload)
    with pytest.raises(OperationsContractError, match="duplicate logical job"):
        validate_scheduled_cycle(payload)


def test_cycle_rejects_attempt_count_receipt_mismatch() -> None:
    payload = _cycle()
    payload["jobs"][0]["attemptCount"] = 2
    _resign(payload)
    with pytest.raises(OperationsContractError, match="attempt receipt count"):
        validate_scheduled_cycle(payload)


def test_cycle_rejects_noncontiguous_or_fabricated_attempt_receipt_ids() -> None:
    payload = _cycle()
    payload["jobs"][0]["attemptReceiptIds"] = ["attempt_fabricated"]
    _resign(payload)
    with pytest.raises(OperationsContractError, match="contiguous derived"):
        validate_scheduled_cycle(payload)


def test_cycle_reconciles_wakeup_manifest_denominator() -> None:
    payload = _cycle()
    payload["manifest"]["wakeupCount"] = 1
    _resign(payload)
    with pytest.raises(OperationsContractError, match="wakeupCount"):
        validate_scheduled_cycle(payload)


def test_cycle_accepts_explicit_not_due_and_balances_it() -> None:
    payload = _cycle()
    _append_not_due_job(payload)
    _resign(payload)
    validate_scheduled_cycle(payload)


def test_not_due_job_cannot_hide_an_attempt() -> None:
    payload = _cycle()
    job = payload["jobs"][0]
    job["dueDisposition"] = "not_due"
    job["dispositionReasonCode"] = "NOT_DUE_BY_POLICY"
    job["terminalDisposition"] = "not_due"
    job["terminalOutputReference"]["referenceType"] = "schedule_disposition_receipt"
    payload["counts"].update({"due": 0, "notDue": 1, "succeeded": 0})
    _resign(payload)
    with pytest.raises(OperationsContractError, match="zero attempts"):
        validate_scheduled_cycle(payload)


def test_blocked_job_requires_one_admission_attempt_and_blocked_terminal() -> None:
    payload = _cycle()
    job = payload["jobs"][0]
    job.update(
        {
            "dueDisposition": "blocked",
            "dispositionReasonCode": "SOURCE_REVISION_UNCERTIFIED",
            "attemptReceiptIds": [],
            "attemptCount": 0,
            "terminalDisposition": "source_uncertified",
        }
    )
    payload["counts"].update({"due": 0, "blocked": 1, "succeeded": 0})
    _resign(payload)
    with pytest.raises(OperationsContractError, match="exactly one admission attempt"):
        validate_scheduled_cycle(payload)

    payload = _cycle()
    job = payload["jobs"][0]
    job.update(
        {
            "dueDisposition": "blocked",
            "dispositionReasonCode": "SOURCE_REVISION_UNCERTIFIED",
            "terminalDisposition": "completed_unchanged",
        }
    )
    payload["counts"].update({"due": 0, "blocked": 1, "succeeded": 0})
    _resign(payload)
    with pytest.raises(OperationsContractError, match="allowlisted blocked reason"):
        validate_scheduled_cycle(payload)


def test_blocked_job_may_bind_one_nonretryable_admission_attempt() -> None:
    payload = _cycle()
    job = payload["jobs"][0]
    job.update(
        {
            "dueDisposition": "blocked",
            "dispositionReasonCode": "SOURCE_REVISION_UNCERTIFIED",
            "terminalDisposition": "source_uncertified",
        }
    )
    payload["counts"].update({"due": 0, "blocked": 1, "succeeded": 0})
    _resign(payload)
    validate_scheduled_cycle(payload)


def test_cycle_rejects_terminal_receipt_type_from_another_lane() -> None:
    payload = _cycle()
    payload["jobs"][0]["terminalOutputReference"]["referenceType"] = "maintenance_receipt"
    _resign(payload)
    with pytest.raises(OperationsContractError, match="requires source_check_receipt"):
        validate_scheduled_cycle(payload)


def test_catch_up_requires_missed_slot_count_and_missed_reconciliation_receipt() -> None:
    payload = _cycle()
    payload["slot"].update({"catchUpDisposition": "catch_up", "missedSlotCount": 1})
    _resign(payload)
    validate_scheduled_cycle(payload)

    payload["slot"]["catchUpDisposition"] = "reconciled_missed"
    _resign(payload)
    with pytest.raises(OperationsContractError, match="missed-dispatch"):
        validate_scheduled_cycle(payload)


def test_completion_window_cannot_cross_next_slot() -> None:
    payload = _cycle()
    payload["slot"]["completionWindowEndsAt"] = "2026-07-15T12:00:01Z"
    _resign(payload)
    with pytest.raises(OperationsContractError, match="next slot"):
        validate_scheduled_cycle(payload)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda p: p["authority"].__setitem__("authorizesCapture", True),
        lambda p: p["authority"].__setitem__("authorizesPublication", True),
        lambda p: p["authority"].__setitem__("frontendLoadable", True),
        lambda p: p["wakeups"][0].__setitem__("authoritative", True),
    ],
)
def test_cycle_rejects_authority_escalation(mutation) -> None:
    payload = _cycle()
    mutation(payload)
    _resign(payload)
    with pytest.raises(OperationsContractError):
        validate_scheduled_cycle(payload)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        ("opaqueTriggerId", "https://source.example/results?token=secret"),
        ("opaqueTriggerId", "secret\nheader"),
        ("wakeupId", "<script>alert(1)</script>"),
    ],
)
def test_cycle_rejects_raw_secret_or_source_controlled_wakeup_payload(path: str, value: str) -> None:
    payload = _cycle()
    payload["wakeups"][0][path] = value
    _resign(payload)
    with pytest.raises(OperationsContractError, match="stable lowercase"):
        validate_scheduled_cycle(payload)


def test_cycle_rejects_unallowlisted_reason_code_that_could_carry_secret_material() -> None:
    payload = _cycle()
    payload["jobs"][0]["dispositionReasonCode"] = "API_KEY_SECRET_MATERIAL"
    _resign(payload)
    with pytest.raises(OperationsContractError, match="allowlisted due reason"):
        validate_scheduled_cycle(payload)


def test_cycle_rejects_mutable_unallowlisted_field_even_when_resigned() -> None:
    payload = _cycle()
    payload["generatedAt"] = "2026-07-15T00:00:00Z"
    _resign(payload)
    with pytest.raises(OperationsContractError, match="unexpected keys"):
        validate_scheduled_cycle(payload)


def test_cycle_rejects_wrong_lane_target_and_source_revision_binding() -> None:
    payload = _cycle()
    payload["jobs"][0]["targetType"] = "discovery_target"
    _resign(payload)
    with pytest.raises(OperationsContractError, match="cycle lane"):
        validate_scheduled_cycle(payload)

    payload = _cycle()
    payload["jobs"][0]["sourceRevisionId"] = "source-revision-other-v1"
    _resign(payload)
    with pytest.raises(OperationsContractError, match="exact target"):
        validate_scheduled_cycle(payload)


@pytest.mark.parametrize(
    ("lane", "target_type", "target", "terminal", "reference_type", "stage"),
    [
        (
            "discovery",
            "discovery_target",
            "discovery-target-example-v1",
            "discovery_changed",
            "discovery_receipt",
            "discovery_accounted",
        ),
        (
            "maintenance",
            "maintenance_task",
            "maintenance-task-example-v1",
            "maintenance_completed",
            "maintenance_receipt",
            "maintenance_completed",
        ),
    ],
)
def test_discovery_and_maintenance_lanes_have_typed_terminal_receipts(
    lane: str,
    target_type: str,
    target: str,
    terminal: str,
    reference_type: str,
    stage: str,
) -> None:
    cycle = _cycle()
    cycle["lane"] = lane
    scheduled = cycle["slot"]["scheduledFor"]
    policy = cycle["schedulePolicyRevisionId"]
    environment = cycle["environment"]
    cycle["cycleId"] = derive_cycle_id(environment, lane, scheduled, policy)
    job = cycle["jobs"][0]
    job["targetType"] = target_type
    job["targetRevisionId"] = target
    job["sourceRevisionId"] = None
    job["jobId"] = derive_job_id(environment, lane, target, scheduled, policy)
    job["idempotencyKeySha256"] = derive_job_idempotency_key(
        environment, lane, target, scheduled, policy
    )
    job["attemptReceiptIds"] = [derive_attempt_id(job["jobId"], 1)]
    job["terminalDisposition"] = terminal
    job["terminalOutputReference"]["referenceType"] = reference_type
    _resign(cycle)
    validate_scheduled_cycle(cycle)

    attempt = _attempt()
    attempt["lane"] = lane
    attempt["targetType"] = target_type
    attempt["targetRevisionId"] = target
    attempt["sourceRevisionId"] = None
    attempt["cycleId"] = cycle["cycleId"]
    attempt["jobId"] = job["jobId"]
    attempt["attemptId"] = job["attemptReceiptIds"][0]
    attempt["stageReached"] = stage
    attempt["outputReferences"] = [
        {
            "referenceType": reference_type,
            "referenceId": f"{reference_type.replace('_', '-')}-example-v1",
            "contentSha256": "5" * 64,
        }
    ]
    attempt["manifest"]["outputReferenceCount"] = 1
    _resign(attempt)
    validate_scheduled_job_attempt(attempt)

def test_retryable_transient_attempt_passes() -> None:
    validate_scheduled_job_attempt(_retryable_attempt())


def test_retry_exhaustion_is_a_distinct_final_transient_outcome() -> None:
    validate_scheduled_job_attempt(_exhausted_attempt())

    payload = _exhausted_attempt()
    payload["attemptNumber"] = 2
    payload["attemptId"] = derive_attempt_id(payload["jobId"], 2)
    _resign(payload)
    with pytest.raises(OperationsContractError, match="final attempt"):
        validate_scheduled_job_attempt(payload)


@pytest.mark.parametrize("cause", ["SCHEMA_DRIFT", "TERMS_UNAPPROVED", "UNSAFE_PEER"])
def test_nonretryable_causes_cannot_be_auto_retried(cause: str) -> None:
    payload = _retryable_attempt()
    payload["causeCode"] = cause
    _resign(payload)
    with pytest.raises(OperationsContractError, match="allowlisted transient"):
        validate_scheduled_job_attempt(payload)


def test_third_attempt_cannot_schedule_a_fourth() -> None:
    payload = _retryable_attempt()
    payload["attemptNumber"] = 3
    payload["attemptId"] = derive_attempt_id(payload["jobId"], 3)
    _resign(payload)
    with pytest.raises(OperationsContractError, match="final attempt"):
        validate_scheduled_job_attempt(payload)


def test_retry_at_must_match_backoff_and_fit_window() -> None:
    payload = _retryable_attempt()
    payload["retry"]["retryAt"] = "2026-07-15T00:04:00Z"
    _resign(payload)
    with pytest.raises(OperationsContractError, match=r"endedAt \+ backoff"):
        validate_scheduled_job_attempt(payload)

    payload = _retryable_attempt()
    payload["retry"]["retryWindowEndsAt"] = payload["retry"]["nextScheduledFor"]
    _resign(payload)
    with pytest.raises(OperationsContractError, match="before the next slot"):
        validate_scheduled_job_attempt(payload)

    payload = _retryable_attempt()
    payload["retry"]["retryWindowEndsAt"] = "2026-07-15T12:00:01Z"
    _resign(payload)
    with pytest.raises(OperationsContractError, match="next slot"):
        validate_scheduled_job_attempt(payload)


def test_success_cannot_carry_retry_fields() -> None:
    payload = _attempt()
    payload["retry"].update(
        {"retryAt": "2026-07-15T00:03:00Z", "backoffSeconds": 60, "retryAfterSource": "policy"}
    )
    _resign(payload)
    with pytest.raises(OperationsContractError, match="null retryAt"):
        validate_scheduled_job_attempt(payload)


def test_successful_recheck_requires_source_check_receipt() -> None:
    payload = _attempt()
    payload["outputReferences"] = [payload["outputReferences"][1]]
    payload["manifest"]["outputReferenceCount"] = 1
    _resign(payload)
    with pytest.raises(OperationsContractError, match="source-check"):
        validate_scheduled_job_attempt(payload)


def test_stale_worker_receipt_is_explicit_and_has_no_outputs() -> None:
    validate_scheduled_job_attempt(_stale_attempt())


def test_stale_worker_cannot_present_current_or_future_token() -> None:
    payload = _stale_attempt()
    payload["lease"]["commitPresentedToken"] = 2
    _resign(payload)
    with pytest.raises(OperationsContractError, match="older presented token"):
        validate_scheduled_job_attempt(payload)


def test_fencing_token_must_be_monotonic_and_bind_prior() -> None:
    payload = _stale_attempt()
    payload["lease"]["priorFencingToken"] = 2
    _resign(payload)
    with pytest.raises(OperationsContractError, match="monotonically"):
        validate_scheduled_job_attempt(payload)

    payload = _attempt()
    payload["lease"]["fencingToken"] = 2
    payload["lease"]["commitPresentedToken"] = 2
    _resign(payload)
    with pytest.raises(OperationsContractError, match="bind its prior"):
        validate_scheduled_job_attempt(payload)


@pytest.mark.parametrize("presented", [1, 3])
def test_fencing_helper_rejects_stale_and_future_commits(presented: int) -> None:
    with pytest.raises(OperationsContractError, match="cannot commit"):
        assert_current_fencing_token(2, presented)
    assert_current_fencing_token(2, 2)


def test_heartbeat_must_remain_inside_lease() -> None:
    payload = _attempt()
    payload["lease"]["lastHeartbeatAt"] = "2026-07-15T00:11:00Z"
    _resign(payload)
    with pytest.raises(OperationsContractError, match="lease interval"):
        validate_scheduled_job_attempt(payload)


def test_accepted_commit_requires_released_current_lease() -> None:
    payload = _attempt()
    payload["lease"]["state"] = "expired"
    _resign(payload)
    with pytest.raises(OperationsContractError, match="released lease"):
        validate_scheduled_job_attempt(payload)


def test_matching_token_cannot_commit_after_lease_expiry() -> None:
    payload = _attempt()
    payload["lease"]["expiresAt"] = "2026-07-15T00:01:30Z"
    payload["lease"]["lastHeartbeatAt"] = "2026-07-15T00:01:00Z"
    _resign(payload)
    with pytest.raises(OperationsContractError, match="expired lease"):
        validate_scheduled_job_attempt(payload)


def test_success_stage_must_be_terminal_for_its_lane() -> None:
    payload = _attempt()
    payload["stageReached"] = "fetch_started"
    _resign(payload)
    with pytest.raises(OperationsContractError, match="terminal success"):
        validate_scheduled_job_attempt(payload)


def test_attempt_rejects_duplicate_output_reference() -> None:
    payload = _attempt()
    payload["outputReferences"].append(deepcopy(payload["outputReferences"][0]))
    payload["manifest"]["outputReferenceCount"] = 3
    _resign(payload)
    with pytest.raises(OperationsContractError, match="duplicate output"):
        validate_scheduled_job_attempt(payload)


@pytest.mark.parametrize("field", ["cycleId", "jobId", "attemptId"])
def test_attempt_rejects_identity_mismatch(field: str) -> None:
    payload = _attempt()
    payload[field] = f"{field.lower()}-wrong"
    _resign(payload)
    with pytest.raises(OperationsContractError, match=field):
        validate_scheduled_job_attempt(payload)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda p: p["authority"].__setitem__("authorizesCapture", True),
        lambda p: p["authority"].__setitem__("authorizesPublication", True),
        lambda p: p["wakeup"].__setitem__("authoritative", True),
    ],
)
def test_attempt_rejects_authority_escalation(mutation) -> None:
    payload = _attempt()
    mutation(payload)
    _resign(payload)
    with pytest.raises(OperationsContractError):
        validate_scheduled_job_attempt(payload)


@pytest.mark.parametrize(
    "unsafe",
    [
        "https://queue.example/message?token=secret",
        "delivery\nauthorization: bearer secret",
        "../../private/object",
        "<script>alert(1)</script>",
    ],
)
def test_attempt_rejects_secret_raw_or_controlled_delivery_payload(unsafe: str) -> None:
    payload = _attempt()
    payload["wakeup"]["opaqueDeliveryId"] = unsafe
    _resign(payload)
    with pytest.raises(OperationsContractError, match="stable lowercase"):
        validate_scheduled_job_attempt(payload)


def test_attempt_rejects_raw_exception_field() -> None:
    payload = _attempt()
    payload["rawException"] = "GET https://source/?token=secret failed"
    _resign(payload)
    with pytest.raises(OperationsContractError, match="unexpected keys"):
        validate_scheduled_job_attempt(payload)


def test_cycle_attempt_cross_validator_reconciles_exact_receipt_denominator() -> None:
    cycle = _cycle()
    attempt = _attempt()
    validate_scheduled_cycle_attempts(cycle, [attempt])

    with pytest.raises(OperationsContractError, match="exactly equal"):
        validate_scheduled_cycle_attempts(cycle, [])

    extra = deepcopy(attempt)
    extra["attemptNumber"] = 2
    extra["attemptId"] = derive_attempt_id(extra["jobId"], 2)
    extra["lease"].update(
        {
            "leaseId": "lease-example-extra",
            "fencingToken": 2,
            "priorFencingToken": 1,
            "commitPresentedToken": 2,
        }
    )
    _resign(extra)
    with pytest.raises(OperationsContractError, match="exactly equal"):
        validate_scheduled_cycle_attempts(cycle, [attempt, extra])


def test_cycle_attempt_cross_validator_rejects_nonmonotonic_fences() -> None:
    cycle = _cycle()
    job = cycle["jobs"][0]
    attempt_one = _retryable_attempt()
    attempt_two = _attempt()
    attempt_two["attemptNumber"] = 2
    attempt_two["attemptId"] = derive_attempt_id(attempt_two["jobId"], 2)
    attempt_two["lease"].update(
        {
            "leaseId": "lease-example-2",
            "fencingToken": 2,
            "priorFencingToken": 1,
            "acquiredAt": "2026-07-15T00:03:05Z",
            "expiresAt": "2026-07-15T00:13:05Z",
            "lastHeartbeatAt": "2026-07-15T00:04:00Z",
            "commitPresentedToken": 2,
        }
    )
    attempt_two["timing"] = {
        "startedAt": "2026-07-15T00:03:10Z",
        "endedAt": "2026-07-15T00:05:00Z",
    }
    _resign(attempt_two)
    job["attemptReceiptIds"] = [attempt_one["attemptId"], attempt_two["attemptId"]]
    job["attemptCount"] = 2
    _resign(cycle)
    validate_scheduled_cycle_attempts(cycle, [attempt_two, attempt_one])

    attempt_two["lease"].update(
        {
            "fencingToken": 1,
            "priorFencingToken": None,
            "commitPresentedToken": 1,
        }
    )
    _resign(attempt_two)
    with pytest.raises(OperationsContractError, match="increase across attempts"):
        validate_scheduled_cycle_attempts(cycle, [attempt_one, attempt_two])


def _two_attempt_chain() -> tuple[dict, dict, dict]:
    cycle = _cycle()
    job = cycle["jobs"][0]
    attempt_one = _retryable_attempt()
    attempt_two = _attempt()
    attempt_two["attemptNumber"] = 2
    attempt_two["attemptId"] = derive_attempt_id(attempt_two["jobId"], 2)
    attempt_two["lease"].update(
        {
            "leaseId": "lease-example-2",
            "fencingToken": 2,
            "priorFencingToken": 1,
            "acquiredAt": "2026-07-15T00:03:05Z",
            "expiresAt": "2026-07-15T00:13:05Z",
            "lastHeartbeatAt": "2026-07-15T00:04:00Z",
            "commitPresentedToken": 2,
        }
    )
    attempt_two["timing"] = {
        "startedAt": "2026-07-15T00:03:10Z",
        "endedAt": "2026-07-15T00:05:00Z",
    }
    _resign(attempt_two)
    job["attemptReceiptIds"] = [attempt_one["attemptId"], attempt_two["attemptId"]]
    job["attemptCount"] = 2
    _resign(cycle)
    return cycle, attempt_one, attempt_two


def test_cycle_attempt_cross_validator_rejects_attempt_after_terminal_outcome() -> None:
    cycle, attempt_one, attempt_two = _two_attempt_chain()
    attempt_one = _attempt()
    _resign(attempt_one)

    with pytest.raises(OperationsContractError, match="only a retryable or stale-fenced"):
        validate_scheduled_cycle_attempts(cycle, [attempt_one, attempt_two])


def test_cycle_attempt_cross_validator_requires_exact_fencing_predecessor() -> None:
    cycle, attempt_one, attempt_two = _two_attempt_chain()
    attempt_two["lease"]["fencingToken"] = 3
    attempt_two["lease"]["priorFencingToken"] = 2
    attempt_two["lease"]["commitPresentedToken"] = 3
    _resign(attempt_two)

    with pytest.raises(OperationsContractError, match="preceding attempt's fencing token"):
        validate_scheduled_cycle_attempts(cycle, [attempt_one, attempt_two])


def test_cycle_attempt_cross_validator_requires_retry_timing_inside_window() -> None:
    cycle, attempt_one, attempt_two = _two_attempt_chain()
    attempt_two["lease"]["acquiredAt"] = "2026-07-15T00:02:50Z"
    attempt_two["timing"]["startedAt"] = "2026-07-15T00:02:55Z"
    _resign(attempt_two)

    with pytest.raises(OperationsContractError, match="inside the preceding retry window"):
        validate_scheduled_cycle_attempts(cycle, [attempt_one, attempt_two])


def test_cycle_attempt_cross_validator_binds_cycle_retry_window_and_next_slot() -> None:
    cycle, attempt_one, attempt_two = _two_attempt_chain()
    attempt_two["retry"]["retryWindowEndsAt"] = "2026-07-15T01:59:59Z"
    _resign(attempt_two)

    with pytest.raises(OperationsContractError, match="equal the cycle completion window"):
        validate_scheduled_cycle_attempts(cycle, [attempt_one, attempt_two])

    attempt_two = _two_attempt_chain()[2]
    attempt_two["retry"]["nextScheduledFor"] = "2026-07-15T13:00:00Z"
    _resign(attempt_two)
    with pytest.raises(OperationsContractError, match="equal the cycle next slot"):
        validate_scheduled_cycle_attempts(cycle, [attempt_one, attempt_two])


def test_cycle_attempt_cross_validator_binds_final_output_digest() -> None:
    cycle, attempt_one, attempt_two = _two_attempt_chain()
    cycle["jobs"][0]["terminalOutputReference"]["contentSha256"] = "2" * 64
    _resign(cycle)

    with pytest.raises(OperationsContractError, match="exactly bind a final-attempt"):
        validate_scheduled_cycle_attempts(cycle, [attempt_one, attempt_two])


def test_manifest_count_and_digest_mismatches_fail() -> None:
    payload = _attempt()
    payload["manifest"]["outputReferenceCount"] = 99
    _resign(payload)
    with pytest.raises(OperationsContractError, match="outputReferenceCount"):
        validate_scheduled_job_attempt(payload)

    payload = _cycle()
    payload["manifest"]["contentSha256"] = "0" * 64
    with pytest.raises(OperationsContractError, match="self-digest mismatch"):
        validate_scheduled_cycle(payload)


def test_validator_module_imports_only_python_standard_library() -> None:
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    imported_roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".")[0])
    assert imported_roots <= sys.stdlib_module_names | {"__future__"}
    assert not ({"sqlalchemy", "requests", "httpx", "yaml", "jsonschema"} & imported_roots)


def test_contract_module_contains_no_network_database_or_filesystem_entrypoints() -> None:
    source = MODULE.read_text(encoding="utf-8")
    for forbidden in ("open(", "sqlite3", "socket", "urlopen", "requests.", "os.environ", "Path("):
        assert forbidden not in source
