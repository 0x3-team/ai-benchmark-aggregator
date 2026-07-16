from __future__ import annotations

import ast
from copy import deepcopy
import json
from pathlib import Path
from typing import Callable

import pytest

from app.schemas.continuous_contracts import (
    ContinuousContractError,
    validate_recheck_attempt_receipt,
    validate_recheck_cycle_receipts,
)
from app.schemas.operations_contracts import (
    OperationsContractError,
    contract_self_digest,
    derive_attempt_id,
    derive_cycle_id,
    derive_job_id,
    derive_job_idempotency_key,
    validate_scheduled_cycle_attempts,
    validate_scheduled_job_attempt,
)
from app.schemas.source_contracts import (
    derive_source_check_receipt_id,
    source_check_receipt_digest,
    validate_source_check_receipt,
)


ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "docs" / "contracts" / "examples"
MODULE = ROOT / "ledger" / "app" / "schemas" / "continuous_contracts.py"


def _load(name: str) -> dict:
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


def _resign_attempt(payload: dict) -> None:
    payload["manifest"]["contentSha256"] = "0" * 64
    payload["manifest"]["contentSha256"] = contract_self_digest(payload)


def _resign_receipt(payload: dict) -> None:
    payload["manifest"]["contentSha256"] = "0" * 64
    payload["manifest"]["contentSha256"] = source_check_receipt_digest(payload)


def _blocked_pair() -> tuple[dict, dict]:
    attempt = _load("scheduled-job-attempt-v1.valid.json")
    receipt = _load("source-check-receipt-v1.valid.json")

    source_revision = receipt["identity"]["sourceRevisionId"]
    schedule_policy = receipt["identity"]["schedulePolicyRevisionId"]
    scheduled_for = receipt["identity"]["scheduledSlot"]
    job_id = derive_job_id(
        attempt["environment"],
        "recheck",
        source_revision,
        scheduled_for,
        schedule_policy,
    )
    attempt_id = derive_attempt_id(job_id, 1)

    attempt.update(
        {
            "cycleId": derive_cycle_id(
                attempt["environment"], "recheck", scheduled_for, schedule_policy
            ),
            "jobId": job_id,
            "attemptId": attempt_id,
            "schedulePolicyRevisionId": schedule_policy,
            "scheduledFor": scheduled_for,
            "targetRevisionId": source_revision,
            "sourceRevisionId": source_revision,
            "stageReached": "revision_admitted",
            "outcome": "blocked",
            "causeCode": "CERTIFICATION_INVALID",
        }
    )
    attempt["retry"].update(
        {
            "classification": "non_retryable",
            "retryAt": None,
            "backoffSeconds": 0,
            "retryAfterSource": "none",
        }
    )
    receipt["identity"].update(
        {
            "jobId": job_id,
            "attemptId": attempt_id,
            "attemptNumber": 1,
            "fencingToken": attempt["lease"]["fencingToken"],
            "expectedFencingToken": attempt["lease"]["fencingToken"],
        }
    )
    receipt["receiptId"] = derive_source_check_receipt_id(attempt_id)
    receipt["execution"] = {
        "startedAt": "2026-07-15T00:00:15Z",
        "finishedAt": "2026-07-15T00:00:16Z",
        "durationMs": 1000,
    }
    _resign_receipt(receipt)
    attempt["outputReferences"] = [
        {
            "referenceType": "source_check_receipt",
            "referenceId": receipt["receiptId"],
            "contentSha256": receipt["manifest"]["contentSha256"],
        },
        {
            "referenceType": "incident",
            "referenceId": receipt["incidentReferences"][0],
            "contentSha256": "a" * 64,
        },
    ]
    attempt["manifest"]["outputReferenceCount"] = len(attempt["outputReferences"])
    _resign_attempt(attempt)
    return attempt, receipt


def _blocked_cycle_triplet() -> tuple[dict, dict, dict]:
    attempt, receipt = _blocked_pair()
    cycle = _load("scheduled-cycle-v1.valid.json")
    source_revision = attempt["sourceRevisionId"]
    scheduled_for = attempt["scheduledFor"]
    policy = attempt["schedulePolicyRevisionId"]
    cycle.update(
        {
            "cycleId": derive_cycle_id(
                cycle["environment"], "recheck", scheduled_for, policy
            ),
            "schedulePolicyRevisionId": policy,
        }
    )
    job = cycle["jobs"][0]
    job.update(
        {
            "jobId": attempt["jobId"],
            "idempotencyKeySha256": derive_job_idempotency_key(
                cycle["environment"],
                "recheck",
                source_revision,
                scheduled_for,
                policy,
            ),
            "targetRevisionId": source_revision,
            "sourceRevisionId": source_revision,
            "dueDisposition": "blocked",
            "dispositionReasonCode": "SOURCE_REVISION_UNCERTIFIED",
            "attemptReceiptIds": [attempt["attemptId"]],
            "attemptCount": 1,
            "terminalDisposition": "source_uncertified",
            "terminalOutputReference": deepcopy(attempt["outputReferences"][0]),
        }
    )
    cycle["counts"].update(
        {
            "due": 0,
            "notDue": 0,
            "blocked": 1,
            "succeeded": 0,
            "reviewRequired": 0,
            "failed": 0,
        }
    )
    cycle["manifest"]["contentSha256"] = "0" * 64
    cycle["manifest"]["contentSha256"] = contract_self_digest(cycle)
    return cycle, attempt, receipt


def test_compatible_synthetic_blocked_pair_is_exactly_bound_and_non_authoritative() -> None:
    attempt, receipt = _blocked_pair()

    validate_scheduled_job_attempt(attempt)
    validate_source_check_receipt(receipt)
    validate_recheck_attempt_receipt(attempt, receipt)

    assert attempt["mode"] == "synthetic_fixture"
    assert receipt["availability"] == "synthetic_evidence_only"
    assert attempt["authority"]["authorizesCapture"] is False
    assert receipt["authority"]["authorizesCapture"] is False


@pytest.mark.parametrize(
    "mutate",
    [
        lambda receipt: receipt["identity"].update(
            {
                "sourceRevisionId": "different-source-revision",
            }
        )
        or receipt["certificationCheck"].update(
            {"checkedSourceRevisionId": "different-source-revision"}
        ),
        lambda receipt: receipt["identity"].update(
            {"schedulePolicyRevisionId": "different-schedule-policy"}
        ),
        lambda receipt: receipt["identity"].update(
            {"scheduledSlot": "2026-07-14T23:59:59Z"}
        ),
        lambda receipt: receipt["identity"].update({"jobId": "different-job"}),
        lambda receipt: receipt["identity"].update({"attemptId": "different-attempt"})
        or receipt.update(
            {"receiptId": derive_source_check_receipt_id("different-attempt")}
        ),
        lambda receipt: receipt["identity"].update({"attemptNumber": 2}),
        lambda receipt: receipt["identity"].update(
            {"fencingToken": 2, "expectedFencingToken": 2}
        ),
    ],
    ids=[
        "source-revision",
        "schedule-policy",
        "slot",
        "job",
        "attempt",
        "attempt-number",
        "fencing-token",
    ],
)
def test_independently_valid_receipt_identity_substitution_fails_composition(
    mutate: Callable[[dict], object],
) -> None:
    attempt, receipt = _blocked_pair()
    mutate(receipt)
    _resign_receipt(receipt)
    validate_source_check_receipt(receipt)

    with pytest.raises(ContinuousContractError, match="does not exactly bind"):
        validate_recheck_attempt_receipt(attempt, receipt)


@pytest.mark.parametrize("field", ["referenceId", "contentSha256"])
def test_output_reference_requires_exact_receipt_id_and_digest(field: str) -> None:
    attempt, receipt = _blocked_pair()
    attempt["outputReferences"][0][field] = (
        "substituted-receipt" if field == "referenceId" else "f" * 64
    )
    _resign_attempt(attempt)
    validate_scheduled_job_attempt(attempt)

    with pytest.raises(ContinuousContractError, match="ID and digest"):
        validate_recheck_attempt_receipt(attempt, receipt)


def test_second_source_receipt_reference_is_rejected_even_when_attempt_is_valid() -> None:
    attempt, receipt = _blocked_pair()
    attempt["outputReferences"].append(
        {
            "referenceType": "source_check_receipt",
            "referenceId": "second-source-check-receipt",
            "contentSha256": "e" * 64,
        }
    )
    attempt["manifest"]["outputReferenceCount"] = len(attempt["outputReferences"])
    _resign_attempt(attempt)
    validate_scheduled_job_attempt(attempt)

    with pytest.raises(ContinuousContractError, match="exactly one"):
        validate_recheck_attempt_receipt(attempt, receipt)


def test_snapshot_and_incident_output_denominators_are_exact() -> None:
    attempt, receipt = _blocked_pair()
    attempt["outputReferences"] = [
        reference
        for reference in attempt["outputReferences"]
        if reference["referenceType"] != "incident"
    ]
    attempt["manifest"]["outputReferenceCount"] = len(attempt["outputReferences"])
    _resign_attempt(attempt)
    validate_scheduled_job_attempt(attempt)
    with pytest.raises(ContinuousContractError, match="incident output IDs"):
        validate_recheck_attempt_receipt(attempt, receipt)

    attempt, receipt = _blocked_pair()
    attempt["outputReferences"].append(
        {
            "referenceType": "source_snapshot",
            "referenceId": "substituted-source-snapshot",
            "contentSha256": "b" * 64,
        }
    )
    attempt["manifest"]["outputReferenceCount"] = len(attempt["outputReferences"])
    _resign_attempt(attempt)
    validate_scheduled_job_attempt(attempt)
    with pytest.raises(ContinuousContractError, match="snapshot output"):
        validate_recheck_attempt_receipt(attempt, receipt)


def test_production_mode_cannot_promote_a_synthetic_source_receipt() -> None:
    attempt, receipt = _blocked_pair()
    attempt["mode"] = "shadow"
    _resign_attempt(attempt)
    validate_scheduled_job_attempt(attempt)

    with pytest.raises(ContinuousContractError, match="across modes"):
        validate_recheck_attempt_receipt(attempt, receipt)


def test_operational_receipt_cannot_omit_exact_source_contract_resolution() -> None:
    attempt, receipt = _blocked_pair()
    attempt["mode"] = "shadow"
    receipt["availability"] = "operational_receipt_only"
    _resign_receipt(receipt)
    attempt["outputReferences"][0]["contentSha256"] = receipt["manifest"]["contentSha256"]
    _resign_attempt(attempt)
    validate_scheduled_job_attempt(attempt)
    validate_source_check_receipt(receipt)

    with pytest.raises(ContinuousContractError, match="exact source contract"):
        validate_recheck_attempt_receipt(attempt, receipt)


def test_source_execution_must_be_contained_by_attempt_timing() -> None:
    attempt, receipt = _blocked_pair()
    receipt["execution"] = {
        "startedAt": "2026-07-15T00:00:05Z",
        "finishedAt": "2026-07-15T00:00:06Z",
        "durationMs": 1000,
    }
    _resign_receipt(receipt)
    attempt["outputReferences"][0]["contentSha256"] = receipt["manifest"]["contentSha256"]
    _resign_attempt(attempt)
    validate_source_check_receipt(receipt)

    with pytest.raises(ContinuousContractError, match="contained"):
        validate_recheck_attempt_receipt(attempt, receipt)


def test_source_terminal_must_match_attempt_outcome_stage_and_cause() -> None:
    for field, value, pattern in (
        ("outcome", "nonretryable_failed", "contradicts source terminal"),
        ("stageReached", "fetch_started", "contradicts source terminal"),
        ("causeCode", "CONTRACT_MISMATCH", "certification state"),
    ):
        attempt, receipt = _blocked_pair()
        attempt[field] = value
        _resign_attempt(attempt)
        validate_scheduled_job_attempt(attempt)
        with pytest.raises(ContinuousContractError, match=pattern):
            validate_recheck_attempt_receipt(attempt, receipt)


def test_nested_tampering_is_reported_as_a_composition_error() -> None:
    attempt, receipt = _blocked_pair()
    attempt["manifest"]["contentSha256"] = "0" * 64

    with pytest.raises(ContinuousContractError, match="invalid scheduled attempt"):
        validate_recheck_attempt_receipt(attempt, receipt)


def test_current_token_commit_after_lease_expiry_is_rejected_for_blocked_output() -> None:
    attempt, _receipt = _blocked_pair()
    attempt["timing"]["endedAt"] = "2026-07-15T00:10:11Z"
    _resign_attempt(attempt)

    with pytest.raises(OperationsContractError, match="expired lease"):
        validate_scheduled_job_attempt(attempt)


def test_cycle_reconciles_every_attempt_receipt_without_order_selection() -> None:
    cycle, attempt, receipt = _blocked_cycle_triplet()

    validate_scheduled_cycle_attempts(cycle, [attempt])
    validate_recheck_cycle_receipts(cycle, [attempt], [receipt])

    with pytest.raises(ContinuousContractError, match="exactly equal every attempt"):
        validate_recheck_cycle_receipts(cycle, [attempt], [])

    extra = deepcopy(receipt)
    extra["identity"]["attemptId"] = "unlisted-attempt"
    extra["receiptId"] = derive_source_check_receipt_id("unlisted-attempt")
    _resign_receipt(extra)
    with pytest.raises(ContinuousContractError, match="exactly equal every attempt"):
        validate_recheck_cycle_receipts(cycle, [attempt], [extra, receipt])

    validate_recheck_cycle_receipts(cycle, [attempt], list(reversed([receipt])))


def test_cycle_terminal_and_mode_must_match_final_source_receipt() -> None:
    cycle, attempt, receipt = _blocked_cycle_triplet()
    cycle["jobs"][0].update(
        {
            "dispositionReasonCode": "SOURCE_REVISION_EXPIRED",
            "terminalDisposition": "source_expired",
        }
    )
    cycle["manifest"]["contentSha256"] = "0" * 64
    cycle["manifest"]["contentSha256"] = contract_self_digest(cycle)
    validate_scheduled_cycle_attempts(cycle, [attempt])
    with pytest.raises(ContinuousContractError, match="contradicts its final"):
        validate_recheck_cycle_receipts(cycle, [attempt], [receipt])

    cycle, attempt, _receipt = _blocked_cycle_triplet()
    cycle["mode"] = "shadow"
    cycle["manifest"]["contentSha256"] = "0" * 64
    cycle["manifest"]["contentSha256"] = contract_self_digest(cycle)
    with pytest.raises(OperationsContractError, match="mode"):
        validate_scheduled_cycle_attempts(cycle, [attempt])


def test_cross_validator_imports_no_runtime_io_or_persistence_modules() -> None:
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.split(".")[0])

    assert imports.isdisjoint(
        {
            "requests",
            "httpx",
            "urllib",
            "socket",
            "subprocess",
            "sqlalchemy",
            "app.db",
            "app.ingestion",
            "app.storage",
        }
    )


def test_composition_validation_is_pure_and_does_not_mutate_inputs() -> None:
    attempt, receipt = _blocked_pair()
    original_attempt = deepcopy(attempt)
    original_receipt = deepcopy(receipt)

    validate_recheck_attempt_receipt(attempt, receipt)

    assert attempt == original_attempt
    assert receipt == original_receipt
