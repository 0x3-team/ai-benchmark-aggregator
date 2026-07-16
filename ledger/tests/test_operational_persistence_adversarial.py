from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from collections.abc import Callable
from typing import Any

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import models
from app.db import operational_repositories as operational
from app.db import repositories
from app.schemas.coverage_contracts import (
    contract_self_digest as coverage_self_digest,
    discovery_candidate_fingerprint,
)
from app.schemas.domain_identity_contracts import (
    contract_self_digest as identity_self_digest,
    evaluation_subject_fingerprint,
    evaluation_subject_observed_composition_fingerprint,
    identity_decision_item_fingerprint,
    raw_identity_label_sha256,
)
from app.schemas.incident_contracts import (
    contract_self_digest as incident_self_digest,
    derive_incident_event_id,
    notification_intent_dedupe_key,
    notification_receipt_dedupe_key,
    payload_digest,
)
from app.schemas.operations_contracts import (
    contract_self_digest as operations_self_digest,
    derive_attempt_id,
    derive_cycle_id,
    derive_job_id,
    derive_job_idempotency_key,
    validate_scheduled_cycle,
    validate_scheduled_job_attempt,
)
from app.schemas.source_contracts import (
    derive_source_check_receipt_id,
    source_check_receipt_digest,
    source_contract_definition_digest,
    source_contract_digest,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
LEDGER_ROOT = REPOSITORY_ROOT / "ledger"
EXAMPLES = REPOSITORY_ROOT / "docs" / "contracts" / "examples"

SOURCE_ID = "operational-fixture-source"
SOURCE_URL = "https://results.example.com/releases/example-v1/results.json"
ENVIRONMENT = "shadow-eu"
SOURCE_SLOT = "2026-12-01T00:00:00Z"
SOURCE_NEXT_SLOT = "2026-12-01T12:00:00Z"
SOURCE_WINDOW_END = "2026-12-01T02:00:00Z"
SOURCE_POLICY_ID = "example-schedule-policy-r1"
WORKER_A = "2" * 64
WORKER_B = "6" * 64


def _load(name: str) -> dict[str, Any]:
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


def _clock(value: str) -> Callable[[], datetime]:
    instant = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=timezone.utc
    )
    return lambda: instant


def _alembic_config(database_url: str) -> Config:
    config = Config(str(LEDGER_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(LEDGER_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url)
    config.attributes["database_url"] = database_url
    return config


@pytest.fixture()
def sqlite_engine(tmp_path: Path) -> Engine:
    """A new versioned database for every adversarial case.

    This deliberately does not use the configured ledger URL and cannot open
    the quarantined legacy database.
    """

    database_path = tmp_path / "operational-adversarial.db"
    database_url = f"sqlite:///{database_path}"
    command.upgrade(_alembic_config(database_url), "head")
    engine = create_engine(database_url, future=True)

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record) -> None:  # type: ignore[no-untyped-def]
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    try:
        yield engine
    finally:
        engine.dispose()


def _resign_operations(payload: dict[str, Any]) -> dict[str, Any]:
    payload["manifest"]["contentSha256"] = "0" * 64
    payload["manifest"]["contentSha256"] = operations_self_digest(payload)
    return payload


def _resign_incident(payload: dict[str, Any]) -> dict[str, Any]:
    payload["manifest"]["contentSha256"] = "0" * 64
    payload["manifest"]["contentSha256"] = incident_self_digest(payload)
    return payload


def _resign_source_contract(payload: dict[str, Any]) -> dict[str, Any]:
    definition_digest = source_contract_definition_digest(payload)
    payload["manifest"]["definitionSha256"] = definition_digest
    if payload["certification"]["decisionOutcome"] != "not_assessed":
        payload["certification"][
            "decidedContractDefinitionSha256"
        ] = definition_digest
    payload["manifest"]["contentSha256"] = source_contract_digest(payload)
    return payload


def _resign_source_receipt(payload: dict[str, Any]) -> dict[str, Any]:
    payload["manifest"]["contentSha256"] = "0" * 64
    payload["manifest"]["contentSha256"] = source_check_receipt_digest(payload)
    return payload


def _resign_candidate(payload: dict[str, Any]) -> dict[str, Any]:
    payload["candidateFingerprintSha256"] = discovery_candidate_fingerprint(payload)
    payload["manifest"]["contentSha256"] = coverage_self_digest(payload)
    return payload


def _resign_subject(payload: dict[str, Any]) -> dict[str, Any]:
    payload["subjectFingerprintSha256"] = evaluation_subject_fingerprint(payload)
    payload["observedCompositionFingerprintSha256"] = (
        evaluation_subject_observed_composition_fingerprint(payload)
    )
    payload["manifest"]["contentSha256"] = identity_self_digest(payload)
    return payload


def _resign_identity_decision(payload: dict[str, Any]) -> dict[str, Any]:
    payload["rawObservation"]["rawLabelSha256"] = raw_identity_label_sha256(
        payload["rawObservation"]["modelRaw"]
    )
    payload["identityItemFingerprintSha256"] = identity_decision_item_fingerprint(
        payload
    )
    payload["manifest"]["contentSha256"] = identity_self_digest(payload)
    return payload


def _seed_source(session: Session) -> tuple[models.OfficialSourceRevision, models.SourceRevisionDecision]:
    repositories.upsert_benchmark(
        session,
        {
            "id": "operational-fixture-benchmark",
            "canonical_name": "operational-fixture-benchmark",
            "display_name": "Operational fixture benchmark",
        },
    )
    reconciliation = repositories.reconcile_official_source(
        session,
        {
            "id": SOURCE_ID,
            "benchmark_id": "operational-fixture-benchmark",
            "source_name": "Synthetic operational acceptance source",
            "source_url": SOURCE_URL,
            "source_type": "api",
            "officialness_level": "O1",
            "machine_readable": True,
            "requires_auth": False,
            "supports_history": True,
            "update_cadence": "PT12H",
            "parser_name": "synthetic-json-v1",
            "parser_version": "1",
            "parser_config": {},
            "status": "active",
            "notes": "Disposable synthetic fixture only.",
        },
    )
    quarantine = session.scalar(
        select(models.SourceRevisionDecision).where(
            models.SourceRevisionDecision.source_revision_id
            == reconciliation.revision.id
        )
    )
    assert quarantine is not None
    return reconciliation.revision, quarantine


def _approved_contract(
    revision: models.OfficialSourceRevision,
    *,
    decision_id: str,
) -> dict[str, Any]:
    contract = _load("source-contract-v2.valid.json")
    contract["logicalSource"].update(
        {
            "sourceId": SOURCE_ID,
            "sourceRevisionId": revision.id,
        }
    )
    contract["lifecycleStatus"] = "approved"
    contract["reasonCode"] = "EXTERNAL_CERTIFICATION_BOUND"
    contract["authority"]["approvalStatus"] = "external_certification_bound"
    contract["authority"]["captureEligible"] = True
    contract["certification"] = {
        "decisionId": decision_id,
        "decisionDigestSha256": "c" * 64,
        "decisionOutcome": "certified",
        "decidedSourceRevisionId": revision.id,
        "decidedContractDefinitionSha256": None,
        "effectiveOn": "2026-07-01",
        "expiresOn": "2026-12-31",
    }
    contract["termsReuse"] = {
        "status": "reviewed_permitted",
        "decisionReference": "synthetic-reuse-decision-r1",
        "evidenceDate": "2026-06-15",
        "effectiveOn": "2026-07-01",
        "reviewDueOn": "2026-12-31",
        "expiresOn": "2026-12-31",
        "reuseScope": "Synthetic fixture persistence verification only.",
        "correctionRoute": "https://governance.example.com/corrections",
    }
    contract["implementationBinding"]["status"] = "wired_peer_verified"
    contract["implementationBinding"]["connectedPeerProof"] = "implemented_verified"
    contract["schedule"]["enabled"] = True
    return _resign_source_contract(contract)


def _append_synthetic_certification(
    session: Session,
    *,
    revision: models.OfficialSourceRevision,
    quarantine: models.SourceRevisionDecision,
    contract: dict[str, Any],
    decision_evidence_override: dict[str, Any] | None = None,
) -> models.SourceRevisionDecision:
    evidence = {
        "decisionDigestSha256": contract["certification"][
            "decisionDigestSha256"
        ],
        "contractDefinitionSha256": contract["manifest"]["definitionSha256"],
        "effectiveOn": contract["certification"]["effectiveOn"],
        "expiresOn": contract["certification"]["expiresOn"],
    }
    if decision_evidence_override:
        evidence.update(decision_evidence_override)
    decision = models.SourceRevisionDecision(
        id=contract["certification"]["decisionId"],
        source_revision_id=revision.id,
        outcome="certified",
        policy_version="synthetic-source-contract-certification-v1",
        reason_code="SYNTHETIC_CONTRACT_FIXTURE_ONLY",
        basis_json={"sourceContractDecisionEvidence": evidence},
        actor="pytest-synthetic-fixture",
        supersedes_decision_id=quarantine.id,
        decided_at=datetime(2026, 7, 16, tzinfo=timezone.utc),
    )
    session.add(decision)
    session.flush()
    return decision


def _persist_snapshot(
    session: Session,
    *,
    revision: models.OfficialSourceRevision,
    snapshot_id: str,
    content_sha256: str,
    storage_receipt_sha256: str,
    verification_receipt_sha256: str,
) -> models.SourceSnapshot:
    snapshot = models.SourceSnapshot(
        id=snapshot_id,
        official_source_id=SOURCE_ID,
        source_revision_id=revision.id,
        raw_content_uri=f"file:///synthetic/{snapshot_id}.json",
        content_hash=content_sha256,
        content_type="application/json",
        http_status=200,
        fetch_metadata={
            "storageReceiptSha256": storage_receipt_sha256,
            "storageVerificationReceiptSha256": verification_receipt_sha256,
        },
        parser_version="synthetic-v1",
    )
    session.add(snapshot)
    session.flush()
    return snapshot


def _append_recheck_intent_and_lease(
    session: Session,
    *,
    revision_id: str,
    mode: str = "shadow",
) -> tuple[models.ScheduledCycleIntent, models.ScheduledJobIntent]:
    cycle, jobs = operational.append_scheduled_cycle_intent(
        session,
        environment=ENVIRONMENT,
        lane="recheck",
        scheduled_for=SOURCE_SLOT,
        schedule_policy_revision_id=SOURCE_POLICY_ID,
        mode=mode,
        job_targets=[
            {
                "targetType": "source_revision",
                "targetRevisionId": revision_id,
                "sourceRevisionId": revision_id,
                "dueDisposition": "due",
                "dispositionReasonCode": "DUE_BY_SCHEDULE",
            }
        ],
    )
    job = jobs[0]
    operational.acquire_job_lease(
        session,
        job_id=job.job_id,
        lease_id="source-lease-r1",
        worker_identity_sha256=WORKER_A,
        expires_at="2099-01-01T00:00:00Z",
        clock=_clock("2026-12-01T00:00:10Z"),
    )
    return cycle, job


def _source_receipt(
    contract: dict[str, Any],
    *,
    job_id: str,
    attempt_id: str,
    disposition: str,
    snapshot_id: str,
) -> dict[str, Any]:
    receipt = _load("source-check-receipt-v1.valid.json")
    certification = contract["certification"]
    receipt["availability"] = "operational_receipt_only"
    receipt["identity"].update(
        {
            "sourceId": SOURCE_ID,
            "sourceRevisionId": contract["logicalSource"]["sourceRevisionId"],
            "contractId": contract["contractId"],
            "contractRevisionId": contract["contractRevisionId"],
            "contractDigestSha256": contract["manifest"]["contentSha256"],
            "contractDefinitionSha256": contract["manifest"]["definitionSha256"],
            "certificationDecisionId": certification["decisionId"],
            "certificationDecisionDigestSha256": certification[
                "decisionDigestSha256"
            ],
            "schedulePolicyRevisionId": SOURCE_POLICY_ID,
            "scheduledSlot": SOURCE_SLOT,
            "jobId": job_id,
            "attemptId": attempt_id,
            "attemptNumber": 1,
            "fencingToken": 1,
            "expectedFencingToken": 1,
        }
    )
    receipt["receiptId"] = derive_source_check_receipt_id(attempt_id)
    receipt["certificationCheck"] = {
        "outcome": "certified",
        "checkedDecisionId": certification["decisionId"],
        "checkedDecisionDigestSha256": certification["decisionDigestSha256"],
        "checkedSourceRevisionId": contract["logicalSource"]["sourceRevisionId"],
        "checkedContractDigestSha256": contract["manifest"]["contentSha256"],
        "checkedContractDefinitionSha256": contract["manifest"][
            "definitionSha256"
        ],
        "checkedBeforeFetch": True,
        "checkedBeforeClaimWrite": True,
        "effectiveForAttempt": True,
    }
    receipt["request"] = {
        "disposition": "completed",
        "method": "GET",
        "requestedUrl": SOURCE_URL,
        "finalUrl": SOURCE_URL,
        "lastApprovedUrl": SOURCE_URL,
        "redirectCount": 0,
        "statusCode": 200 if disposition == "completed_changed" else 304,
        "conditionalRequestUsed": disposition == "completed_unchanged",
        "responseBodyReceived": disposition == "completed_changed",
        "failureStage": None,
        "failureCode": None,
    }
    receipt["networkEvidence"] = {
        "dnsPolicyStatus": "passed",
        "connectedPeerStatus": "passed",
        "tlsStatus": "passed",
        "connectedPeerAddressClass": "public",
        "finalHost": "results.example.com",
    }
    receipt["terminalDisposition"] = disposition
    receipt["reasonCode"] = (
        "SOURCE_CHANGED_AND_ACCOUNTED"
        if disposition == "completed_changed"
        else "SOURCE_NOT_MODIFIED"
    )
    receipt["incidentReferences"] = []
    receipt["manifest"]["incidentReferenceCount"] = 0
    receipt["execution"] = {
        "startedAt": "2026-12-01T00:00:15Z",
        "finishedAt": "2026-12-01T00:02:00Z",
        "durationMs": 105000,
    }
    if disposition == "completed_changed":
        receipt["response"] = {
            "contentChanged": True,
            "bytesReceived": 256,
            "contentSha256": "d" * 64,
            "mimeType": "application/json",
            "retryClassification": "none",
            "retryAfterSeconds": None,
        }
        receipt["conditionalMetadata"] = {
            "previousSnapshotId": None,
            "previousSnapshotContentSha256": None,
            "previousSnapshotVerificationReceiptSha256": None,
            "etagRequestSha256": None,
            "lastModifiedRequestSha256": None,
            "etagResponseSha256": "1" * 64,
            "lastModifiedResponseSha256": None,
        }
        receipt["snapshot"] = {
            "snapshotId": snapshot_id,
            "snapshotContentSha256": "d" * 64,
            "storageReceiptSha256": "e" * 64,
            "status": "committed_reverified",
            "immutable": True,
            "readBackVerified": True,
            "committedBeforeExtraction": True,
        }
        receipt["extraction"] = {
            "disposition": "accounted",
            "sourceRecordsObserved": 2,
            "rowsParsed": 2,
            "claimCandidatesEmitted": 2,
            "claimsAdmitted": 2,
            "recordsExcluded": 0,
            "recordsRejected": 0,
            "recordsQuarantined": 0,
            "evidenceLocatorCoverageCount": 2,
            "duplicateLocatorCount": 0,
            "unexplainedRecordCount": 0,
            "schemaFingerprintSha256": contract["drift"][
                "approvedSchemaSha256"
            ],
            "batchReceiptSha256": "f" * 64,
            "dimensionsObserved": contract["extraction"][
                "allowedDisplayDimensions"
            ].copy(),
        }
    else:
        receipt["response"] = {
            "contentChanged": False,
            "bytesReceived": 0,
            "contentSha256": None,
            "mimeType": None,
            "retryClassification": "none",
            "retryAfterSeconds": None,
        }
        receipt["conditionalMetadata"] = {
            "previousSnapshotId": snapshot_id,
            "previousSnapshotContentSha256": "3" * 64,
            "previousSnapshotVerificationReceiptSha256": "4" * 64,
            "etagRequestSha256": "2" * 64,
            "lastModifiedRequestSha256": None,
            "etagResponseSha256": None,
            "lastModifiedResponseSha256": None,
        }
        receipt["snapshot"] = {
            "snapshotId": None,
            "snapshotContentSha256": None,
            "storageReceiptSha256": None,
            "status": "not_created",
            "immutable": False,
            "readBackVerified": False,
            "committedBeforeExtraction": False,
        }
        receipt["extraction"] = {
            "disposition": "not_run",
            "sourceRecordsObserved": 0,
            "rowsParsed": 0,
            "claimCandidatesEmitted": 0,
            "claimsAdmitted": 0,
            "recordsExcluded": 0,
            "recordsRejected": 0,
            "recordsQuarantined": 0,
            "evidenceLocatorCoverageCount": 0,
            "duplicateLocatorCount": 0,
            "unexplainedRecordCount": 0,
            "schemaFingerprintSha256": None,
            "batchReceiptSha256": None,
            "dimensionsObserved": [],
        }
    return _resign_source_receipt(receipt)


def _source_attempt(
    *,
    revision_id: str,
    job_id: str,
    receipt: dict[str, Any],
    disposition: str,
) -> dict[str, Any]:
    attempt = _load("scheduled-job-attempt-v1.valid.json")
    attempt_id = receipt["identity"]["attemptId"]
    attempt.update(
        {
            "mode": "shadow",
            "attemptId": attempt_id,
            "cycleId": derive_cycle_id(
                ENVIRONMENT, "recheck", SOURCE_SLOT, SOURCE_POLICY_ID
            ),
            "jobId": job_id,
            "environment": ENVIRONMENT,
            "lane": "recheck",
            "schedulePolicyRevisionId": SOURCE_POLICY_ID,
            "scheduledFor": SOURCE_SLOT,
            "targetType": "source_revision",
            "targetRevisionId": revision_id,
            "sourceRevisionId": revision_id,
            "attemptNumber": 1,
            "workerIdentitySha256": WORKER_A,
            "stageReached": (
                "claims_admitted"
                if disposition == "completed_changed"
                else "not_modified"
            ),
            "outcome": "succeeded",
            "causeCode": "ATTEMPT_COMPLETED",
        }
    )
    attempt["lease"] = {
        "leaseId": "source-lease-r1",
        "fencingToken": 1,
        "priorFencingToken": None,
        "acquiredAt": "2026-12-01T00:00:10Z",
        "expiresAt": "2099-01-01T00:00:00Z",
        "lastHeartbeatAt": "2026-12-01T00:02:00Z",
        "state": "released",
        "commitPresentedToken": 1,
        "commitDisposition": "accepted_current",
    }
    attempt["timing"] = {
        "startedAt": "2026-12-01T00:00:15Z",
        "endedAt": "2026-12-01T00:02:00Z",
    }
    attempt["retry"].update(
        {
            "classification": "none",
            "retryAt": None,
            "backoffSeconds": 0,
            "retryAfterSource": "none",
            "retryWindowEndsAt": SOURCE_WINDOW_END,
            "nextScheduledFor": SOURCE_NEXT_SLOT,
        }
    )
    snapshot = receipt["snapshot"]
    conditional = receipt["conditionalMetadata"]
    snapshot_id = snapshot["snapshotId"] or conditional["previousSnapshotId"]
    snapshot_digest = (
        snapshot["snapshotContentSha256"]
        or conditional["previousSnapshotContentSha256"]
    )
    attempt["outputReferences"] = [
        {
            "referenceType": "source_check_receipt",
            "referenceId": receipt["receiptId"],
            "contentSha256": receipt["manifest"]["contentSha256"],
        },
        {
            "referenceType": "source_snapshot",
            "referenceId": snapshot_id,
            "contentSha256": snapshot_digest,
        },
    ]
    attempt["manifest"]["outputReferenceCount"] = len(
        attempt["outputReferences"]
    )
    return _resign_operations(attempt)


def _source_pair(
    contract: dict[str, Any],
    *,
    revision_id: str,
    job_id: str,
    disposition: str,
    snapshot_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    attempt_id = derive_attempt_id(job_id, 1)
    receipt = _source_receipt(
        contract,
        job_id=job_id,
        attempt_id=attempt_id,
        disposition=disposition,
        snapshot_id=snapshot_id,
    )
    return (
        _source_attempt(
            revision_id=revision_id,
            job_id=job_id,
            receipt=receipt,
            disposition=disposition,
        ),
        receipt,
    )


def _source_cycle(
    *,
    revision_id: str,
    attempt: dict[str, Any],
    receipt: dict[str, Any],
) -> dict[str, Any]:
    cycle = _load("scheduled-cycle-v1.valid.json")
    cycle.update(
        {
            "mode": "shadow",
            "cycleId": derive_cycle_id(
                ENVIRONMENT, "recheck", SOURCE_SLOT, SOURCE_POLICY_ID
            ),
            "environment": ENVIRONMENT,
            "lane": "recheck",
            "schedulePolicyRevisionId": SOURCE_POLICY_ID,
        }
    )
    cycle["slot"] = {
        "anchorUtc": "2026-01-01T00:00:00Z",
        "cadenceSeconds": 43200,
        "slotOrdinal": 668,
        "scheduledFor": SOURCE_SLOT,
        "nextScheduledFor": SOURCE_NEXT_SLOT,
        "completionWindowEndsAt": SOURCE_WINDOW_END,
        "catchUpDisposition": "scheduled",
        "missedSlotCount": 0,
    }
    cycle["wakeups"][0]["observedAt"] = "2026-12-01T00:00:01Z"
    cycle["wakeups"][1]["observedAt"] = "2026-12-01T00:00:05Z"
    cycle["jobs"] = [
        {
            "jobId": attempt["jobId"],
            "idempotencyKeySha256": derive_job_idempotency_key(
                ENVIRONMENT,
                "recheck",
                revision_id,
                SOURCE_SLOT,
                SOURCE_POLICY_ID,
            ),
            "targetType": "source_revision",
            "targetRevisionId": revision_id,
            "sourceRevisionId": revision_id,
            "dueDisposition": "due",
            "dispositionReasonCode": "DUE_BY_SCHEDULE",
            "attemptReceiptIds": [attempt["attemptId"]],
            "attemptCount": 1,
            "terminalDisposition": receipt["terminalDisposition"],
            "terminalOutputReference": {
                "referenceType": "source_check_receipt",
                "referenceId": receipt["receiptId"],
                "contentSha256": receipt["manifest"]["contentSha256"],
            },
        }
    ]
    cycle["counts"] = {
        "expected": 1,
        "due": 1,
        "notDue": 0,
        "blocked": 0,
        "terminal": 1,
        "succeeded": 1,
        "reviewRequired": 0,
        "failed": 0,
    }
    cycle["manifest"]["jobCount"] = 1
    cycle["manifest"]["wakeupCount"] = len(cycle["wakeups"])
    return _resign_operations(cycle)


def _raw_insert_terminal_cycle(session: Session, cycle: dict[str, Any]) -> None:
    session.execute(
        text(
            """
            INSERT INTO scheduled_cycles (
                cycle_id, environment, lane, scheduled_for,
                schedule_policy_revision_id, mode, content_sha256, payload_json
            ) VALUES (
                :cycle_id, :environment, :lane, :scheduled_for,
                :schedule_policy_revision_id, :mode, :content_sha256, :payload_json
            )
            """
        ),
        {
            "cycle_id": cycle["cycleId"],
            "environment": cycle["environment"],
            "lane": cycle["lane"],
            "scheduled_for": cycle["slot"]["scheduledFor"].replace("T", " ").replace(
                "Z", ".000000"
            ),
            "schedule_policy_revision_id": cycle["schedulePolicyRevisionId"],
            "mode": cycle["mode"],
            "content_sha256": cycle["manifest"]["contentSha256"],
            "payload_json": json.dumps(
                cycle, sort_keys=True, separators=(",", ":"), ensure_ascii=True
            ),
        },
    )


def _incident_prefix(event_count: int, *, mode: str = "synthetic_fixture") -> dict[str, Any]:
    incident = _load("ops-incident-v1.valid.json")
    incident["events"] = incident["events"][:event_count]
    incident["currentState"] = incident["events"][-1]["toState"]
    incident["manifest"]["eventCount"] = event_count
    incident["mode"] = mode
    if event_count == 1:
        incident["sla"]["acknowledgedAt"] = None
    return _resign_incident(incident)


def _append_incident_event(
    incident: dict[str, Any],
    *,
    event_type: str,
    to_state: str,
    occurred_at: str,
    resolution_ref: dict[str, Any] | None = None,
) -> dict[str, Any]:
    prior = max(incident["events"], key=lambda item: item["eventOrdinal"])
    event = {
        "eventId": "placeholder",
        "eventOrdinal": prior["eventOrdinal"] + 1,
        "eventType": event_type,
        "expectedPriorEventId": prior["eventId"],
        "fromState": prior["toState"],
        "toState": to_state,
        "occurredAt": occurred_at,
        "actorRole": "operations-owner",
        "reasonCode": f"{event_type}_BY_FIXTURE",
        "acknowledgementEvidenceRef": None,
        "resolutionEvidenceRef": deepcopy(resolution_ref),
        "safeContext": {
            "contextCode": "SYNTHETIC_FIXTURE_ONLY",
            "sourceControlledDataIncluded": False,
        },
    }
    event["eventId"] = derive_incident_event_id(
        incident["incidentFingerprintSha256"],
        event["eventOrdinal"],
        event["expectedPriorEventId"],
        event_type,
        occurred_at,
    )
    incident["events"].append(event)
    incident["currentState"] = to_state
    incident["manifest"]["eventCount"] = len(incident["events"])
    if event_type in {"OPENED", "OCCURRENCE_RECORDED", "REOPENED"}:
        incident["occurrenceCount"] += 1
        incident["lastOccurredAt"] = occurred_at
    return _resign_incident(incident)


def _bind_intent(
    incident: dict[str, Any],
    *,
    external: bool = False,
    recovery: bool = False,
    route_id: str = "local-json-fixture-v1",
) -> dict[str, Any]:
    intent = _load("notification-intent-v1.valid.json")
    latest = max(incident["events"], key=lambda item: item["eventOrdinal"])
    intent.update(
        {
            "mode": incident["mode"],
            "incidentId": incident["incidentId"],
            "incidentFingerprintSha256": incident["incidentFingerprintSha256"],
            "incidentFamily": incident["family"],
            "incidentCode": incident["incidentCode"],
            "incidentEventId": latest["eventId"],
            "incidentEventType": latest["eventType"],
            "severity": incident["severity"],
            "notificationKind": "recovery" if recovery else "transition",
        }
    )
    intent["payload"].update(
        {
            "environment": incident["environment"],
            "incidentId": incident["incidentId"],
            "incidentCode": incident["incidentCode"],
            "severity": incident["severity"],
            "currentState": incident["currentState"],
            "occurrenceCount": incident["occurrenceCount"],
            "runbookId": incident["runbookId"],
            "nextActionCode": incident["nextActionCode"],
            "recoveryState": "recovered" if recovery else "not_applicable",
        }
    )
    if external:
        intent["route"].update(
            {
                "routeId": route_id,
                "routeType": "email",
                "external": True,
                "authorityStatus": "approved_external",
                "authorityDecisionReference": "synthetic-route-decision-v1",
                "failureDomain": "primary_outbox",
            }
        )
        intent["dispatchEligibility"] = "eligible_external"
        for key in (
            "dataMinimizationDecisionReference",
            "recipientAuthorityDecisionReference",
            "retentionDecisionReference",
            "authenticationDecisionReference",
            "ownerDecisionReference",
        ):
            intent["authority"][key] = f"synthetic-{key.lower()}"
    intent["payloadSha256"] = payload_digest(intent["payload"])
    dedupe = notification_intent_dedupe_key(intent)
    intent["dedupeKeySha256"] = dedupe
    intent["intentId"] = "notification-intent-" + dedupe
    return _resign_incident(intent)


def _rebind_notification_receipt(
    receipt: dict[str, Any], intent: dict[str, Any]
) -> dict[str, Any]:
    receipt["intentBinding"].update(
        {
            "intentId": intent["intentId"],
            "intentContentSha256": intent["manifest"]["contentSha256"],
            "intentDedupeKeySha256": intent["dedupeKeySha256"],
            "payloadSha256": intent["payloadSha256"],
            "routeId": intent["route"]["routeId"],
        }
    )
    dedupe = notification_receipt_dedupe_key(receipt)
    receipt["receiptDedupeKeySha256"] = dedupe
    receipt["receiptId"] = "notification-receipt-" + dedupe
    return _resign_incident(receipt)


def _dead_letter_receipt(intent: dict[str, Any]) -> dict[str, Any]:
    receipt = _load("notification-receipt-v1.valid.json")
    receipt.update(
        {
            "mode": "shadow",
            "routeAuthorityStatus": "approved_external",
            "outcome": "dead_lettered",
        }
    )
    receipt["attempts"][0].update(
        {
            "outcome": "failed_permanent",
            "causeCode": "PERMANENT_SYNTHETIC_FAILURE",
        }
    )
    receipt["deadLetter"] = {
        "status": "dead_lettered",
        "deadLetterReferenceId": "synthetic-dead-letter-v1",
        "nextActionCode": "REVIEW_DEAD_LETTER",
    }
    return _rebind_notification_receipt(receipt, intent)


def _recovery_receipt(
    intent: dict[str, Any],
    *,
    prior_receipt_id: str,
    recovered_at: str,
    finished_at: str,
) -> dict[str, Any]:
    receipt = _load("notification-receipt-v1.valid.json")
    receipt.update(
        {
            "mode": "shadow",
            "routeAuthorityStatus": "approved_external",
            "outcome": "recovery_delivered",
        }
    )
    receipt["attempts"][0].update(
        {
            "startedAt": finished_at,
            "endedAt": finished_at,
            "outcome": "delivered",
            "causeCode": "DELIVERY_CONFIRMED",
        }
    )
    receipt["recovery"] = {
        "priorReceiptId": prior_receipt_id,
        "recoveryIntentId": intent["intentId"],
        "recoveredAt": recovered_at,
    }
    return _rebind_notification_receipt(receipt, intent)


def _identity_candidate() -> dict[str, Any]:
    candidate = _load("discovery-candidate-v1.valid.json")
    candidate["candidateId"] = "candidate-example-submission-v1"
    candidate["evidenceReferences"][0][
        "evidenceId"
    ] = "example-submission-observation"
    return _resign_candidate(candidate)


def _reviewed_subject_child(parent: dict[str, Any], revision_id: str) -> dict[str, Any]:
    subject = deepcopy(parent)
    subject["subjectRevisionId"] = revision_id
    subject["supersedesSubjectRevisionId"] = parent["subjectRevisionId"]
    subject["lifecycleStatus"] = "reviewed"
    subject["decisionReference"] = "synthetic-subject-review-v1"
    subject["reasonCode"] = "TYPE_IDENTITY_REVIEWED"
    subject["resolutionStatus"] = "resolved"
    subject["authority"]["reviewStatus"] = "identity_reviewed"
    subject["displayIdentity"]["modelEntityId"] = subject["subjectId"]
    subject["displayIdentity"]["displayName"] = "Reviewed opaque fixture"
    return _resign_subject(subject)


def _effective_identity_decision(
    *,
    decision_id: str,
    selected_subject_id: str,
    expected_prior_decision_id: str | None = None,
    sequence: int = 1,
) -> dict[str, Any]:
    decision = _load("identity-decision-v1.valid.json")
    decision.update(
        {
            "decisionId": decision_id,
            "candidateReference": "candidate-example-submission-v1",
            "observationReference": "example-submission-observation",
            "expectedPriorDecisionId": expected_prior_decision_id,
            "decisionSequence": sequence,
            "decisionStatus": "effective",
            "decidedAt": f"2026-07-15T12:00:0{sequence - 1}Z",
            "governanceDecisionReference": f"{decision_id}-governance",
            "outcome": "resolved",
            "selectedSubjectId": selected_subject_id,
            "reasonCode": "ITEMIZED_IDENTITY_REVIEW_COMPLETE",
        }
    )
    decision["actor"] = {
        "actorId": "identity-reviewer",
        "actorType": "human",
        "role": "model-registry-steward",
        "authorityReference": "identity-review-charter-v1",
    }
    decision["authority"].update(
        {
            "approvalStatus": "identity_reviewed",
            "actorAuthorityVerified": True,
            "permitsIdentityReadProjection": True,
        }
    )
    decision["aliasProposal"]["proposedAction"] = "add_scoped_alias"
    decision["effects"]["identityReadProjectionEffect"] = "set_selected_subject"
    return _resign_identity_decision(decision)


def test_cycle_intent_completion_rejects_underfill_and_late_job_add(
    sqlite_engine: Engine,
) -> None:
    with Session(sqlite_engine) as session, session.begin():
        cycle, jobs = operational.append_scheduled_cycle_intent(
            session,
            environment="fixture-shadow",
            lane="maintenance",
            scheduled_for="2026-07-15T00:00:00Z",
            schedule_policy_revision_id="maintenance-policy-r1",
            mode="synthetic_fixture",
            job_targets=[
                {
                    "targetType": "maintenance_task",
                    "targetRevisionId": "maintenance-task-r1",
                    "sourceRevisionId": None,
                    "dueDisposition": "due",
                    "dispositionReasonCode": "DUE_BY_SCHEDULE",
                }
            ],
        )
        assert cycle.job_count == len(jobs) == 1

        before_jobs = session.scalar(
            text(
                "SELECT COUNT(*) FROM scheduled_job_intents WHERE cycle_id = :cycle_id"
            ),
            {"cycle_id": cycle.cycle_id},
        )
        assert before_jobs == 1
        with pytest.raises(IntegrityError):
            with session.begin_nested():
                session.execute(
                    text(
                        """
                        INSERT INTO scheduled_job_intents (
                            job_id, cycle_id, environment, lane, target_type,
                            target_revision_id, source_revision_id, scheduled_for,
                            schedule_policy_revision_id, idempotency_key_sha256,
                            due_disposition, disposition_reason_code, intent_sha256,
                            payload_json
                        )
                        SELECT
                            'late-job', cycle_id, environment, lane, target_type,
                            target_revision_id, source_revision_id, scheduled_for,
                            schedule_policy_revision_id, :idempotency,
                            due_disposition, disposition_reason_code, :intent_sha,
                            payload_json
                        FROM scheduled_job_intents WHERE job_id = :job_id
                        """
                    ),
                    {
                        "idempotency": "7" * 64,
                        "intent_sha": "8" * 64,
                        "job_id": jobs[0].job_id,
                    },
                )
        assert session.scalar(
            text(
                "SELECT COUNT(*) FROM scheduled_job_intents WHERE cycle_id = :cycle_id"
            ),
            {"cycle_id": cycle.cycle_id},
        ) == 1

        underfilled_cycle_id = derive_cycle_id(
            "fixture-shadow",
            "maintenance",
            "2026-07-15T12:00:00Z",
            "maintenance-policy-r1",
        )
        underfilled_payload = {
            "recordType": "scheduled-cycle-intent-v1",
            "cycleId": underfilled_cycle_id,
            "environment": "fixture-shadow",
            "lane": "maintenance",
            "scheduledFor": "2026-07-15T12:00:00Z",
            "schedulePolicyRevisionId": "maintenance-policy-r1",
            "mode": "synthetic_fixture",
            "jobs": [
                {
                    "jobId": "missing-job",
                    "idempotencyKeySha256": "9" * 64,
                    "targetType": "maintenance_task",
                    "targetRevisionId": "missing-maintenance-task",
                    "sourceRevisionId": None,
                    "dueDisposition": "due",
                    "dispositionReasonCode": "DUE_BY_SCHEDULE",
                }
            ],
        }
        underfilled_sha = hashlib.sha256(
            json.dumps(
                underfilled_payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ).encode("utf-8")
        ).hexdigest()
        with pytest.raises(IntegrityError):
            with session.begin_nested():
                session.execute(
                    text(
                        """
                        INSERT INTO scheduled_cycle_intents (
                            cycle_id, environment, lane, scheduled_for,
                            schedule_policy_revision_id, mode, job_count,
                            intent_sha256, payload_json
                        ) VALUES (
                            :cycle_id, 'fixture-shadow', 'maintenance',
                            '2026-07-15 12:00:00.000000',
                            'maintenance-policy-r1', 'synthetic_fixture', 1,
                            :intent_sha256, :payload_json
                        )
                        """
                    ),
                    {
                        "cycle_id": underfilled_cycle_id,
                        "intent_sha256": underfilled_sha,
                        "payload_json": json.dumps(
                            underfilled_payload,
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                    },
                )
                session.execute(
                    text(
                        """
                        INSERT INTO scheduled_cycle_intent_completions (
                            cycle_id, intent_sha256, job_count
                        ) VALUES (:cycle_id, :intent_sha256, 1)
                        """
                    ),
                    {
                        "cycle_id": underfilled_cycle_id,
                        "intent_sha256": underfilled_sha,
                    },
                )
        assert session.get(models.ScheduledCycleIntent, underfilled_cycle_id) is None


def test_terminal_cycle_binds_exact_attempt_denominator_and_final_output(
    sqlite_engine: Engine,
) -> None:
    with Session(sqlite_engine) as session, session.begin():
        revision, quarantine = _seed_source(session)
        contract = _approved_contract(
            revision, decision_id="10000000-0000-0000-0000-000000000001"
        )
        _append_synthetic_certification(
            session,
            revision=revision,
            quarantine=quarantine,
            contract=contract,
        )
        _persist_snapshot(
            session,
            revision=revision,
            snapshot_id="source-snapshot-current-v1",
            content_sha256="d" * 64,
            storage_receipt_sha256="e" * 64,
            verification_receipt_sha256="a" * 64,
        )
        _cycle_intent, job = _append_recheck_intent_and_lease(
            session, revision_id=revision.id
        )
        attempt, receipt = _source_pair(
            contract,
            revision_id=revision.id,
            job_id=job.job_id,
            disposition="completed_changed",
            snapshot_id="source-snapshot-current-v1",
        )
        operational.append_source_attempt_and_receipt(
            session,
            attempt,
            receipt,
            source_contract=contract,
            clock=_clock("2026-12-01T00:02:00Z"),
        )
        cycle = _source_cycle(
            revision_id=revision.id, attempt=attempt, receipt=receipt
        )
        validate_scheduled_cycle(cycle)

        wrong_attempt = deepcopy(cycle)
        wrong_attempt["jobs"][0]["attemptReceiptIds"] = ["fabricated-attempt"]
        _resign_operations(wrong_attempt)
        with pytest.raises(IntegrityError):
            with session.begin_nested():
                _raw_insert_terminal_cycle(session, wrong_attempt)

        wrong_output = deepcopy(cycle)
        wrong_output["jobs"][0]["terminalOutputReference"][
            "contentSha256"
        ] = "0" * 64
        _resign_operations(wrong_output)
        with pytest.raises(IntegrityError):
            with session.begin_nested():
                _raw_insert_terminal_cycle(session, wrong_output)

        terminal = operational.append_scheduled_cycle(session, cycle)
        assert terminal.cycle_id == cycle["cycleId"]
        assert terminal.payload_json["jobs"][0]["attemptReceiptIds"] == [
            attempt["attemptId"]
        ]
        assert terminal.payload_json["jobs"][0][
            "terminalOutputReference"
        ] == {
            "referenceType": "source_check_receipt",
            "referenceId": receipt["receiptId"],
            "contentSha256": receipt["manifest"]["contentSha256"],
        }


def test_source_contract_requires_exact_durable_certification_evidence(
    sqlite_engine: Engine,
) -> None:
    with Session(sqlite_engine) as session, session.begin():
        revision, quarantine = _seed_source(session)
        contract = _approved_contract(
            revision, decision_id="20000000-0000-0000-0000-000000000001"
        )
        _append_synthetic_certification(
            session,
            revision=revision,
            quarantine=quarantine,
            contract=contract,
            decision_evidence_override={"decisionDigestSha256": "0" * 64},
        )

        with pytest.raises(
            operational.OperationalPersistenceError,
            match="exact immutable decision evidence",
        ):
            operational.append_source_contract_envelope(session, contract)
        assert session.get(
            models.SourceContractEnvelope, contract["contractRevisionId"]
        ) is None


@pytest.mark.parametrize(
    ("disposition", "stored_storage", "stored_verification", "message"),
    [
        (
            "completed_changed",
            "0" * 64,
            "a" * 64,
            "snapshot ID/digest/revision binding",
        ),
        (
            "completed_unchanged",
            "b" * 64,
            "0" * 64,
            "304 prior snapshot/content/verification evidence",
        ),
    ],
    ids=["new-snapshot-storage-receipt", "304-prior-verification-receipt"],
)
def test_source_receipt_rejects_nonresolving_snapshot_provenance(
    sqlite_engine: Engine,
    disposition: str,
    stored_storage: str,
    stored_verification: str,
    message: str,
) -> None:
    with Session(sqlite_engine) as session, session.begin():
        revision, quarantine = _seed_source(session)
        contract = _approved_contract(
            revision, decision_id="30000000-0000-0000-0000-000000000001"
        )
        _append_synthetic_certification(
            session,
            revision=revision,
            quarantine=quarantine,
            contract=contract,
        )
        content = "d" * 64 if disposition == "completed_changed" else "3" * 64
        _persist_snapshot(
            session,
            revision=revision,
            snapshot_id="source-snapshot-provenance-v1",
            content_sha256=content,
            storage_receipt_sha256=stored_storage,
            verification_receipt_sha256=stored_verification,
        )
        _cycle_intent, job = _append_recheck_intent_and_lease(
            session, revision_id=revision.id
        )
        attempt, receipt = _source_pair(
            contract,
            revision_id=revision.id,
            job_id=job.job_id,
            disposition=disposition,
            snapshot_id="source-snapshot-provenance-v1",
        )
        with pytest.raises(operational.OperationalPersistenceError, match=message):
            with session.begin_nested():
                operational.append_source_attempt_and_receipt(
                    session,
                    attempt,
                    receipt,
                    source_contract=contract,
                    clock=_clock("2026-12-01T00:02:00Z"),
                )
        assert session.get(models.ScheduledJobAttempt, attempt["attemptId"]) is None
        assert session.get(models.SourceCheckReceiptRecord, receipt["receiptId"]) is None


def test_304_receipt_persists_exact_contract_decision_and_prior_snapshot(
    sqlite_engine: Engine,
) -> None:
    with Session(sqlite_engine) as session, session.begin():
        revision, quarantine = _seed_source(session)
        contract = _approved_contract(
            revision, decision_id="40000000-0000-0000-0000-000000000001"
        )
        decision = _append_synthetic_certification(
            session,
            revision=revision,
            quarantine=quarantine,
            contract=contract,
        )
        snapshot = _persist_snapshot(
            session,
            revision=revision,
            snapshot_id="source-snapshot-prior-v1",
            content_sha256="3" * 64,
            storage_receipt_sha256="b" * 64,
            verification_receipt_sha256="4" * 64,
        )
        _cycle_intent, job = _append_recheck_intent_and_lease(
            session, revision_id=revision.id
        )
        attempt, receipt = _source_pair(
            contract,
            revision_id=revision.id,
            job_id=job.job_id,
            disposition="completed_unchanged",
            snapshot_id=snapshot.id,
        )
        _attempt_row, receipt_row = operational.append_source_attempt_and_receipt(
            session,
            attempt,
            receipt,
            source_contract=contract,
            clock=_clock("2026-12-01T00:02:00Z"),
        )

        assert receipt_row.checked_source_revision_decision_id == decision.id
        assert (
            receipt_row.checked_source_revision_decision_sha256
            == contract["certification"]["decisionDigestSha256"]
        )
        assert receipt_row.contract_digest_sha256 == contract["manifest"][
            "contentSha256"
        ]
        assert receipt_row.contract_definition_sha256 == contract["manifest"][
            "definitionSha256"
        ]
        assert receipt_row.snapshot_id is None
        assert receipt_row.previous_snapshot_id == snapshot.id
        assert receipt_row.previous_snapshot_content_sha256 == "3" * 64
        assert (
            receipt_row.previous_snapshot_verification_receipt_sha256 == "4" * 64
        )


def test_lease_timing_worker_heartbeat_takeover_and_stale_fencing(
    sqlite_engine: Engine,
) -> None:
    with Session(sqlite_engine) as session, session.begin():
        cycle, jobs = operational.append_scheduled_cycle_intent(
            session,
            environment="fixture-shadow",
            lane="maintenance",
            scheduled_for="2026-07-15T00:00:00Z",
            schedule_policy_revision_id="maintenance-policy-r1",
            mode="synthetic_fixture",
            job_targets=[
                {
                    "targetType": "maintenance_task",
                    "targetRevisionId": "maintenance-task-r1",
                    "sourceRevisionId": None,
                    "dueDisposition": "due",
                    "dispositionReasonCode": "DUE_BY_SCHEDULE",
                }
            ],
        )
        job = jobs[0]

        with pytest.raises(
            operational.OperationalPersistenceError, match="precede expires_at"
        ):
            operational.acquire_job_lease(
                session,
                job_id=job.job_id,
                lease_id="invalid-lease",
                worker_identity_sha256=WORKER_A,
                expires_at="2026-07-15T00:00:10Z",
                clock=_clock("2026-07-15T00:00:10Z"),
            )

        first = operational.acquire_job_lease(
            session,
            job_id=job.job_id,
            lease_id="lease-worker-a",
            worker_identity_sha256=WORKER_A,
            expires_at="2026-07-15T00:10:10Z",
            clock=_clock("2026-07-15T00:00:10Z"),
        )
        assert (first.fencing_token, first.worker_identity_sha256) == (1, WORKER_A)
        operational.heartbeat_job_lease(
            session,
            job_id=job.job_id,
            lease_id="lease-worker-a",
            fencing_token=1,
            worker_identity_sha256=WORKER_A,
            clock=_clock("2026-07-15T00:05:00Z"),
        )
        with pytest.raises(operational.StaleFencingToken, match="worker"):
            operational.heartbeat_job_lease(
                session,
                job_id=job.job_id,
                lease_id="lease-worker-a",
                fencing_token=1,
                worker_identity_sha256=WORKER_B,
                clock=_clock("2026-07-15T00:05:01Z"),
            )
        with pytest.raises(
            operational.OperationalPersistenceError, match="monotonic"
        ):
            operational.heartbeat_job_lease(
                session,
                job_id=job.job_id,
                lease_id="lease-worker-a",
                fencing_token=1,
                worker_identity_sha256=WORKER_A,
                clock=_clock("2026-07-15T00:04:59Z"),
            )
        with pytest.raises(
            operational.OperationalPersistenceError, match="lease expiry"
        ):
            operational.heartbeat_job_lease(
                session,
                job_id=job.job_id,
                lease_id="lease-worker-a",
                fencing_token=1,
                worker_identity_sha256=WORKER_A,
                clock=_clock("2026-07-15T00:10:11Z"),
            )
        with pytest.raises(
            operational.OperationalPersistenceError, match="unexpired active lease"
        ):
            operational.acquire_job_lease(
                session,
                job_id=job.job_id,
                lease_id="premature-takeover",
                worker_identity_sha256=WORKER_B,
                expires_at="2026-07-15T00:20:09Z",
                clock=_clock("2026-07-15T00:10:09Z"),
            )

        second = operational.acquire_job_lease(
            session,
            job_id=job.job_id,
            lease_id="lease-worker-b",
            worker_identity_sha256=WORKER_B,
            expires_at="2026-07-15T00:20:10Z",
            clock=_clock("2026-07-15T00:10:10Z"),
        )
        assert (
            second.fencing_token,
            second.worker_identity_sha256,
            second.current_lease_id,
        ) == (2, WORKER_B, "lease-worker-b")
        with pytest.raises(operational.StaleFencingToken):
            operational.heartbeat_job_lease(
                session,
                job_id=job.job_id,
                lease_id="lease-worker-a",
                fencing_token=1,
                worker_identity_sha256=WORKER_A,
                clock=_clock("2026-07-15T00:10:10Z"),
            )

        stale = _load("scheduled-job-attempt-v1.valid.json")
        stale.update(
            {
                "cycleId": cycle.cycle_id,
                "jobId": job.job_id,
                "attemptId": derive_attempt_id(job.job_id, 1),
                "environment": job.environment,
                "lane": job.lane,
                "schedulePolicyRevisionId": job.schedule_policy_revision_id,
                "scheduledFor": "2026-07-15T00:00:00Z",
                "targetType": job.target_type,
                "targetRevisionId": job.target_revision_id,
                "sourceRevisionId": None,
                "workerIdentitySha256": WORKER_A,
                "stageReached": "maintenance_completed",
            }
        )
        stale["lease"] = {
            "leaseId": "lease-worker-a",
            "fencingToken": 1,
            "priorFencingToken": None,
            "acquiredAt": "2026-07-15T00:00:10Z",
            "expiresAt": "2026-07-15T00:10:10Z",
            "lastHeartbeatAt": "2026-07-15T00:05:00Z",
            "state": "released",
            "commitPresentedToken": 1,
            "commitDisposition": "accepted_current",
        }
        stale["timing"] = {
            "startedAt": "2026-07-15T00:00:15Z",
            "endedAt": "2026-07-15T00:05:00Z",
        }
        stale["outputReferences"] = [
            {
                "referenceType": "maintenance_receipt",
                "referenceId": "maintenance-receipt-stale",
                "contentSha256": "5" * 64,
            }
        ]
        stale["manifest"]["outputReferenceCount"] = 1
        _resign_operations(stale)
        validate_scheduled_job_attempt(stale)
        with pytest.raises(operational.StaleFencingToken):
            operational.append_scheduled_job_attempt(
                session, stale, clock=_clock("2026-07-15T00:11:00Z")
            )

        wrong_worker = deepcopy(stale)
        wrong_worker["attemptNumber"] = 2
        wrong_worker["attemptId"] = derive_attempt_id(job.job_id, 2)
        wrong_worker["lease"].update(
            {
                "leaseId": "lease-worker-b",
                "fencingToken": 2,
                "priorFencingToken": 1,
                "acquiredAt": "2026-07-15T00:10:10Z",
                "expiresAt": "2026-07-15T00:20:10Z",
                "lastHeartbeatAt": "2026-07-15T00:11:00Z",
                "commitPresentedToken": 2,
            }
        )
        wrong_worker["timing"] = {
            "startedAt": "2026-07-15T00:10:15Z",
            "endedAt": "2026-07-15T00:11:00Z",
        }
        _resign_operations(wrong_worker)
        validate_scheduled_job_attempt(wrong_worker)
        with pytest.raises(operational.StaleFencingToken, match="worker identity"):
            operational.append_scheduled_job_attempt(
                session, wrong_worker, clock=_clock("2026-07-15T00:11:00Z")
            )
        assert session.scalar(
            text("SELECT COUNT(*) FROM scheduled_job_attempts")
        ) == 0


def test_incremental_incident_outbox_is_per_event_and_zero_batch_is_closed(
    sqlite_engine: Engine,
) -> None:
    with Session(sqlite_engine) as session, session.begin():
        first = _incident_prefix(1)
        first_intent = _bind_intent(first)
        operational.append_ops_incident(
            session, first, notification_intents=[first_intent]
        )

        second = _incident_prefix(2)
        second_intent = _bind_intent(second)
        operational.append_ops_incident(
            session, second, notification_intents=[second_intent]
        )

        third = _incident_prefix(3)
        operational.append_ops_incident(session, third, notification_intents=[])

        events = list(
            session.scalars(
                select(models.OpsIncidentEvent)
                .where(models.OpsIncidentEvent.incident_id == third["incidentId"])
                .order_by(models.OpsIncidentEvent.event_ordinal)
            )
        )
        assert [event.outbox_intent_count for event in events] == [1, 1, 0]
        assert session.scalar(text("SELECT COUNT(*) FROM notification_intents")) == 2
        assert session.scalar(
            text("SELECT COUNT(*) FROM notification_outbox_batches")
        ) == 3
        zero_batch = session.get(models.NotificationOutboxBatch, events[-1].event_id)
        assert zero_batch is not None and zero_batch.intent_count == 0

        late_intent = _bind_intent(third)
        with pytest.raises(operational.OperationalReplayConflict):
            with session.begin_nested():
                operational.append_ops_incident(
                    session, third, notification_intents=[late_intent]
                )
        with pytest.raises(IntegrityError):
            with session.begin_nested():
                session.execute(
                    text(
                        """
                        INSERT INTO notification_outbox_items (
                            incident_event_id, intent_id, intent_ordinal,
                            outbox_batch_id
                        ) VALUES (:event_id, 'late-intent', 0, :batch_id)
                        """
                    ),
                    {
                        "event_id": events[-1].event_id,
                        "batch_id": events[-1].outbox_batch_id,
                    },
                )
        assert session.scalar(text("SELECT COUNT(*) FROM notification_intents")) == 2


def test_recovery_receipt_crosses_intents_on_same_incident_route_without_branch(
    sqlite_engine: Engine,
) -> None:
    with Session(sqlite_engine) as session, session.begin():
        active = _incident_prefix(3, mode="shadow")
        first_intent = _bind_intent(
            active,
            external=True,
            route_id="synthetic-email-route-v1",
        )
        operational.append_ops_incident(
            session, active, notification_intents=[first_intent]
        )
        failed = _dead_letter_receipt(first_intent)
        failed_row = operational.append_notification_receipt(session, failed)

        resolved = deepcopy(active)
        _append_incident_event(
            resolved,
            event_type="MITIGATED",
            to_state="MITIGATED",
            occurred_at="2026-07-15T00:20:00Z",
        )
        evidence = {
            "evidenceId": "resolution-evidence-fixture-v1",
            "contentSha256": "b" * 64,
        }
        resolved["resolutionEvidenceRefs"] = [evidence]
        resolved["manifest"]["resolutionEvidenceReferenceCount"] = 1
        _append_incident_event(
            resolved,
            event_type="RESOLVED",
            to_state="RESOLVED",
            occurred_at="2026-07-15T00:30:00Z",
            resolution_ref=evidence,
        )
        resolved["sla"]["mitigatedAt"] = "2026-07-15T00:20:00Z"
        _resign_incident(resolved)
        recovery_intent = _bind_intent(
            resolved,
            external=True,
            recovery=True,
            route_id="synthetic-email-route-v1",
        )
        operational.append_ops_incident(
            session, resolved, notification_intents=[recovery_intent]
        )
        recovered = _recovery_receipt(
            recovery_intent,
            prior_receipt_id=failed_row.receipt_id,
            recovered_at="2026-07-15T00:31:00Z",
            finished_at="2026-07-15T00:31:01Z",
        )
        recovered_row = operational.append_notification_receipt(session, recovered)
        assert recovered_row.incident_id == failed_row.incident_id == active["incidentId"]
        assert recovered_row.route_id == failed_row.route_id == "synthetic-email-route-v1"
        assert recovered_row.intent_id != failed_row.intent_id
        assert recovered_row.prior_receipt_id == failed_row.receipt_id

        closed = deepcopy(resolved)
        _append_incident_event(
            closed,
            event_type="CLOSED",
            to_state="CLOSED",
            occurred_at="2026-07-15T00:40:00Z",
        )
        second_recovery_intent = _bind_intent(
            closed,
            external=True,
            recovery=True,
            route_id="synthetic-email-route-v1",
        )
        operational.append_ops_incident(
            session, closed, notification_intents=[second_recovery_intent]
        )
        branched = _recovery_receipt(
            second_recovery_intent,
            prior_receipt_id=failed_row.receipt_id,
            recovered_at="2026-07-15T00:41:00Z",
            finished_at="2026-07-15T00:41:01Z",
        )
        with pytest.raises(IntegrityError):
            with session.begin_nested():
                operational.append_notification_receipt(session, branched)
        assert session.scalar(text("SELECT COUNT(*) FROM notification_receipts")) == 2


@pytest.mark.parametrize("aggregate", ["incident", "work"])
def test_incident_and_work_roots_and_state_chains_reject_direct_sql_branches(
    sqlite_engine: Engine,
    aggregate: str,
) -> None:
    with Session(sqlite_engine) as session, session.begin():
        if aggregate == "incident":
            payload = _incident_prefix(3)
            operational.append_ops_incident(session, payload)
            table = "ops_incident_events"
            aggregate_column = "incident_id"
            aggregate_id = payload["incidentId"]
            leaf = payload["events"][-1]
        else:
            payload = _load("review-work-item-v1.valid.json")
            operational.append_review_work_item(session, payload)
            table = "review_work_item_events"
            aggregate_column = "work_item_id"
            aggregate_id = payload["workItemId"]
            leaf = payload["events"][-1]

        with pytest.raises(IntegrityError):
            with session.begin_nested():
                session.execute(
                    text(
                        f"""
                        INSERT INTO {table} (
                            event_id, {aggregate_column}, event_ordinal,
                            expected_prior_event_id, event_type, from_state,
                            to_state, occurred_at, event_payload_json,
                            contract_content_sha256, contract_payload_json
                            {', outbox_batch_id, outbox_intent_count' if aggregate == 'incident' else ''}
                        ) VALUES (
                            'duplicate-root', :aggregate_id, 1, NULL,
                            'OPENED', NULL, 'OPEN',
                            '2026-07-15 00:00:00.000000', '{{}}', NULL, NULL
                            {", 'duplicate-root-batch', 0" if aggregate == 'incident' else ''}
                        )
                        """
                    ),
                    {"aggregate_id": aggregate_id},
                )

        next_ordinal = leaf["eventOrdinal"] + 1
        with pytest.raises(IntegrityError):
            with session.begin_nested():
                session.execute(
                    text(
                        f"""
                        INSERT INTO {table} (
                            event_id, {aggregate_column}, event_ordinal,
                            expected_prior_event_id, event_type, from_state,
                            to_state, occurred_at, event_payload_json,
                            contract_content_sha256, contract_payload_json
                            {', outbox_batch_id, outbox_intent_count' if aggregate == 'incident' else ''}
                        ) VALUES (
                            'wrong-state-successor', :aggregate_id, :ordinal,
                            :prior, 'STATE_CHANGE', 'WRONG_STATE', 'OPEN',
                            '2026-07-15 03:00:00.000000', '{{}}', NULL, NULL
                            {", 'wrong-state-batch', 0" if aggregate == 'incident' else ''}
                        )
                        """
                    ),
                    {
                        "aggregate_id": aggregate_id,
                        "ordinal": next_ordinal,
                        "prior": leaf["eventId"],
                    },
                )
        assert session.scalar(
            text(f"SELECT COUNT(*) FROM {table} WHERE {aggregate_column} = :id"),
            {"id": aggregate_id},
        ) == len(payload["events"])


def test_identity_decision_selects_only_reviewed_resolved_current_leaf(
    sqlite_engine: Engine,
) -> None:
    with Session(sqlite_engine) as session, session.begin():
        operational.append_discovery_candidate(session, _identity_candidate())
        draft = _load("evaluation-subject-v1.valid.json")
        operational.append_evaluation_subject_revision(session, draft)
        decision = _effective_identity_decision(
            decision_id="identity-effective-r1",
            selected_subject_id=draft["subjectId"],
        )
        with pytest.raises(
            operational.OperationalPersistenceError,
            match="reviewed, resolved live leaf",
        ):
            operational.append_identity_decision(session, decision)

        session.add(
            models.ModelEntity(
                id=draft["subjectId"],
                canonical_name=draft["subjectId"],
                display_name="Reviewed opaque fixture",
                entity_type="opaque_submission",
            )
        )
        session.flush()
        reviewed = _reviewed_subject_child(
            draft, "example-submission-subject-revision-v2"
        )
        operational.append_evaluation_subject_revision(session, reviewed)
        stored = operational.append_identity_decision(session, decision)
        assert stored.selected_subject_id == draft["subjectId"]

        superseded = deepcopy(reviewed)
        superseded["subjectRevisionId"] = "example-submission-subject-revision-v3"
        superseded["supersedesSubjectRevisionId"] = reviewed["subjectRevisionId"]
        superseded["lifecycleStatus"] = "superseded"
        superseded["decisionReference"] = "synthetic-subject-supersession-v1"
        _resign_subject(superseded)
        operational.append_evaluation_subject_revision(session, superseded)
        successor_decision = _effective_identity_decision(
            decision_id="identity-effective-r2",
            selected_subject_id=draft["subjectId"],
            expected_prior_decision_id=decision["decisionId"],
            sequence=2,
        )
        with pytest.raises(
            operational.OperationalPersistenceError,
            match="reviewed, resolved live leaf",
        ):
            operational.append_identity_decision(session, successor_decision)
        assert session.get(
            models.IdentityDecisionRecord, successor_decision["decisionId"]
        ) is None


@pytest.mark.parametrize(
    (
        "lane",
        "target_type",
        "target_id",
        "due_disposition",
        "reason_code",
        "terminal_disposition",
        "reference_type",
        "success_stage",
    ),
    [
        (
            "discovery",
            "discovery_target",
            "discovery-target-r1",
            "due",
            "DUE_BY_SCHEDULE",
            "discovery_changed",
            "discovery_receipt",
            "discovery_accounted",
        ),
        (
            "maintenance",
            "maintenance_task",
            "maintenance-task-r1",
            "due",
            "DUE_BY_SCHEDULE",
            "maintenance_completed",
            "maintenance_receipt",
            "maintenance_completed",
        ),
        (
            "maintenance",
            "maintenance_task",
            "maintenance-task-not-due-r1",
            "not_due",
            "MAINTENANCE_NOT_DUE",
            "not_due",
            "schedule_disposition_receipt",
            None,
        ),
    ],
    ids=["discovery", "maintenance", "schedule-disposition"],
)
def test_unimplemented_terminal_referents_fail_closed_explicitly(
    sqlite_engine: Engine,
    lane: str,
    target_type: str,
    target_id: str,
    due_disposition: str,
    reason_code: str,
    terminal_disposition: str,
    reference_type: str,
    success_stage: str | None,
) -> None:
    scheduled_for = "2026-07-15T00:00:00Z"
    policy_id = "unsupported-output-policy-r1"
    with Session(sqlite_engine) as session, session.begin():
        cycle_intent, jobs = operational.append_scheduled_cycle_intent(
            session,
            environment="fixture-shadow",
            lane=lane,
            scheduled_for=scheduled_for,
            schedule_policy_revision_id=policy_id,
            mode="synthetic_fixture",
            job_targets=[
                {
                    "targetType": target_type,
                    "targetRevisionId": target_id,
                    "sourceRevisionId": None,
                    "dueDisposition": due_disposition,
                    "dispositionReasonCode": reason_code,
                }
            ],
        )
        job = jobs[0]
        output_reference = {
            "referenceType": reference_type,
            "referenceId": f"{reference_type.replace('_', '-')}-r1",
            "contentSha256": "5" * 64,
        }
        attempt_ids: list[str] = []
        if success_stage is not None:
            operational.acquire_job_lease(
                session,
                job_id=job.job_id,
                lease_id=f"{lane}-lease-r1",
                worker_identity_sha256=WORKER_A,
                expires_at="2099-01-01T00:00:00Z",
                clock=_clock("2026-07-15T00:00:10Z"),
            )
            attempt = _load("scheduled-job-attempt-v1.valid.json")
            attempt_id = derive_attempt_id(job.job_id, 1)
            attempt.update(
                {
                    "attemptId": attempt_id,
                    "cycleId": cycle_intent.cycle_id,
                    "jobId": job.job_id,
                    "environment": job.environment,
                    "lane": lane,
                    "schedulePolicyRevisionId": policy_id,
                    "scheduledFor": scheduled_for,
                    "targetType": target_type,
                    "targetRevisionId": target_id,
                    "sourceRevisionId": None,
                    "workerIdentitySha256": WORKER_A,
                    "stageReached": success_stage,
                }
            )
            attempt["lease"].update(
                {
                    "leaseId": f"{lane}-lease-r1",
                    "fencingToken": 1,
                    "priorFencingToken": None,
                    "acquiredAt": "2026-07-15T00:00:10Z",
                    "expiresAt": "2099-01-01T00:00:00Z",
                    "lastHeartbeatAt": "2026-07-15T00:02:00Z",
                    "state": "released",
                    "commitPresentedToken": 1,
                    "commitDisposition": "accepted_current",
                }
            )
            attempt["outputReferences"] = [deepcopy(output_reference)]
            attempt["manifest"]["outputReferenceCount"] = 1
            _resign_operations(attempt)
            validate_scheduled_job_attempt(attempt)
            operational.append_scheduled_job_attempt(
                session, attempt, clock=_clock("2026-07-15T00:02:00Z")
            )
            attempt_ids = [attempt_id]

        cycle = _load("scheduled-cycle-v1.valid.json")
        cycle.update(
            {
                "cycleId": cycle_intent.cycle_id,
                "environment": "fixture-shadow",
                "lane": lane,
                "schedulePolicyRevisionId": policy_id,
            }
        )
        job_payload = {
            "jobId": job.job_id,
            "idempotencyKeySha256": job.idempotency_key_sha256,
            "targetType": target_type,
            "targetRevisionId": target_id,
            "sourceRevisionId": None,
            "dueDisposition": due_disposition,
            "dispositionReasonCode": reason_code,
            "attemptReceiptIds": attempt_ids,
            "attemptCount": len(attempt_ids),
            "terminalDisposition": terminal_disposition,
            "terminalOutputReference": output_reference,
        }
        cycle["jobs"] = [job_payload]
        cycle["counts"] = {
            "expected": 1,
            "due": 1 if due_disposition == "due" else 0,
            "notDue": 1 if due_disposition == "not_due" else 0,
            "blocked": 0,
            "terminal": 1,
            "succeeded": 1 if due_disposition == "due" else 0,
            "reviewRequired": 0,
            "failed": 0,
        }
        cycle["manifest"]["jobCount"] = 1
        _resign_operations(cycle)
        validate_scheduled_cycle(cycle)

        with pytest.raises(
            operational.OperationalPersistenceError,
            match="no DATA-09 immutable persistence referent",
        ):
            operational.append_scheduled_cycle(session, cycle)
        with pytest.raises(IntegrityError):
            with session.begin_nested():
                _raw_insert_terminal_cycle(session, cycle)
        assert session.get(models.ScheduledCycle, cycle["cycleId"]) is None
