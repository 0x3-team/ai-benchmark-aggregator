"""Guarded append-only persistence for Phase 1 operational contracts.

The repositories validate the frozen wire contracts before retaining exact
payloads.  They intentionally expose no source certification, claim review,
claim publication, notification delivery, or frontend release operation.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any, TypeVar

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import models
from app.schemas.continuous_contracts import validate_recheck_attempt_receipt
from app.schemas.coverage_contracts import validate_discovery_candidate
from app.schemas.domain_identity_contracts import (
    canonical_json as canonical_identity_json,
    validate_benchmark_definition_revision,
    validate_benchmark_revision_chain,
    validate_evaluation_subject,
    validate_evaluation_subject_revision_chain,
    validate_identity_decision,
    validate_identity_decision_chain,
)
from app.schemas.incident_contracts import (
    canonical_json as canonical_incident_json,
    validate_incident_notification_binding,
    validate_notification_intent,
    validate_notification_pair,
    validate_notification_receipt,
    validate_ops_incident,
    validate_review_work_item,
)
from app.schemas.operations_contracts import (
    derive_cycle_id,
    derive_job_id,
    derive_job_idempotency_key,
    validate_scheduled_cycle,
    validate_scheduled_cycle_attempts,
    validate_scheduled_job_planner_disposition,
    validate_scheduled_job_attempt,
)
from app.schemas.source_contracts import (
    source_contract_definition_digest,
    source_contract_digest,
    validate_source_check_receipt,
    validate_source_contract,
)


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_ModelT = TypeVar("_ModelT")
_LANE_TARGET = {
    "discovery": "discovery_target",
    "recheck": "source_revision",
    "maintenance": "maintenance_task",
}


class OperationalPersistenceError(ValueError):
    """Raised when durable identity, lineage, or exact-reference checks fail."""


class OperationalReplayConflict(OperationalPersistenceError):
    """Raised when a stable ID is replayed with different immutable content."""


class StaleFencingToken(OperationalPersistenceError):
    """Raised when a worker does not present the exact current lease token."""


def _payload_copy(payload: Mapping[str, Any]) -> dict[str, Any]:
    if type(payload) is not dict:
        raise OperationalPersistenceError("contract payload must be a plain JSON object")
    return deepcopy(payload)


def _utc(value: str | datetime, *, field: str) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise OperationalPersistenceError(f"{field} must be timezone-aware UTC")
        return value.astimezone(timezone.utc)
    if type(value) is not str or _UTC.fullmatch(value) is None:
        raise OperationalPersistenceError(
            f"{field} must be canonical UTC YYYY-MM-DDTHH:MM:SSZ"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise OperationalPersistenceError(f"{field} must be valid UTC") from exc


def _stored_utc(value: datetime) -> datetime:
    """Normalize SQLite's naive DateTime reloads back to recorded UTC."""

    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _clock_utc(clock: Callable[[], datetime], *, field: str) -> datetime:
    """Read one trusted, injected clock sample for a lease mutation."""

    if not callable(clock):
        raise OperationalPersistenceError(f"{field} must be a callable UTC clock")
    value = clock()
    if not isinstance(value, datetime):
        raise OperationalPersistenceError(
            f"{field} must return a timezone-aware UTC datetime"
        )
    return _utc(value, field=field)


def _sha256(value: str, *, field: str) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise OperationalPersistenceError(f"{field} must be a lowercase SHA-256 digest")
    return value


def _exact_existing(
    existing: _ModelT | None,
    *,
    identity: str,
    actual_digest: str,
    expected_digest: str,
) -> _ModelT | None:
    if existing is None:
        return None
    if actual_digest != expected_digest:
        raise OperationalReplayConflict(
            f"stable identity {identity!r} already has different immutable content"
        )
    return existing


def _source_check_reference(payload: Mapping[str, Any]) -> tuple[str | None, str | None]:
    references = [
        reference
        for reference in payload["outputReferences"]
        if reference["referenceType"] == "source_check_receipt"
    ]
    if not references:
        return None, None
    if len(references) != 1:
        raise OperationalPersistenceError(
            "attempt must contain at most one source-check receipt reference"
        )
    return references[0]["referenceId"], references[0]["contentSha256"]


def _canonical_digest(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def append_scheduled_cycle_intent(
    session: Session,
    *,
    environment: str,
    lane: str,
    scheduled_for: str,
    schedule_policy_revision_id: str,
    mode: str,
    job_targets: Sequence[Mapping[str, Any]],
) -> tuple[models.ScheduledCycleIntent, tuple[models.ScheduledJobIntent, ...]]:
    """Persist deterministic schedule-slot and job truth before dispatch.

    This internal persistence record deliberately contains no terminal outcome,
    attempt ID, or output reference.  The frozen ``scheduled-cycle-v1``
    contract is appended later by :func:`append_scheduled_cycle`.
    """

    if mode not in {"synthetic_fixture", "shadow", "production"}:
        raise OperationalPersistenceError("mode is not an allowed scheduler mode")
    if lane not in _LANE_TARGET:
        raise OperationalPersistenceError("lane is not an allowed scheduler lane")
    if type(job_targets) not in {list, tuple}:
        raise OperationalPersistenceError("job_targets must be a finite list or tuple")

    scheduled = _utc(scheduled_for, field="scheduled_for")
    scheduled_text = scheduled.strftime("%Y-%m-%dT%H:%M:%SZ")
    cycle_id = derive_cycle_id(
        environment, lane, scheduled_text, schedule_policy_revision_id
    )
    normalized_jobs: list[dict[str, Any]] = []
    for index, target in enumerate(job_targets):
        if type(target) is not dict or set(target) != {
            "targetType",
            "targetRevisionId",
            "sourceRevisionId",
            "dueDisposition",
            "dispositionReasonCode",
        }:
            raise OperationalPersistenceError(
                f"job_targets[{index}] must contain the exact target and planner-disposition fields"
            )
        target_type = target["targetType"]
        target_revision_id = target["targetRevisionId"]
        source_revision_id = target["sourceRevisionId"]
        due_disposition = target["dueDisposition"]
        disposition_reason_code = target["dispositionReasonCode"]
        try:
            validate_scheduled_job_planner_disposition(
                due_disposition, disposition_reason_code
            )
        except ValueError as exc:
            raise OperationalPersistenceError(str(exc)) from exc
        if target_type != _LANE_TARGET[lane]:
            raise OperationalPersistenceError("job target type must exactly match its lane")
        if target_type == "source_revision":
            if source_revision_id != target_revision_id:
                raise OperationalPersistenceError(
                    "recheck job intent must bind its target source revision"
                )
            revision = session.get(models.OfficialSourceRevision, source_revision_id)
            if revision is None:
                raise OperationalPersistenceError(
                    f"scheduled job source revision {source_revision_id!r} is absent"
                )
        elif source_revision_id is not None:
            raise OperationalPersistenceError(
                "only recheck job intents may bind a source revision"
            )
        job_id = derive_job_id(
            environment,
            lane,
            target_revision_id,
            scheduled_text,
            schedule_policy_revision_id,
        )
        normalized_jobs.append(
            {
                "jobId": job_id,
                "idempotencyKeySha256": derive_job_idempotency_key(
                    environment,
                    lane,
                    target_revision_id,
                    scheduled_text,
                    schedule_policy_revision_id,
                ),
                "targetType": target_type,
                "targetRevisionId": target_revision_id,
                "sourceRevisionId": source_revision_id,
                "dueDisposition": due_disposition,
                "dispositionReasonCode": disposition_reason_code,
            }
        )
    normalized_jobs.sort(key=lambda item: item["jobId"])
    if len({item["jobId"] for item in normalized_jobs}) != len(normalized_jobs):
        raise OperationalPersistenceError("job_targets contain a duplicate logical job")

    cycle_payload = {
        "recordType": "scheduled-cycle-intent-v1",
        "cycleId": cycle_id,
        "environment": environment,
        "lane": lane,
        "scheduledFor": scheduled_text,
        "schedulePolicyRevisionId": schedule_policy_revision_id,
        "mode": mode,
        "jobs": normalized_jobs,
    }
    cycle_digest = _canonical_digest(cycle_payload)
    existing_cycle = session.get(models.ScheduledCycleIntent, cycle_id)
    if existing_cycle is not None:
        _exact_existing(
            existing_cycle,
            identity=cycle_id,
            actual_digest=existing_cycle.intent_sha256,
            expected_digest=cycle_digest,
        )
        rows = tuple(
            session.scalars(
                select(models.ScheduledJobIntent)
                .where(models.ScheduledJobIntent.cycle_id == cycle_id)
                .order_by(models.ScheduledJobIntent.job_id)
            )
        )
        if [row.payload_json for row in rows] != normalized_jobs:
            raise OperationalReplayConflict(
                "scheduled cycle intent exists with a different immutable job set"
            )
        completion = session.get(models.ScheduledCycleIntentCompletion, cycle_id)
        if (
            completion is None
            or completion.intent_sha256 != cycle_digest
            or completion.job_count != len(rows)
        ):
            raise OperationalReplayConflict(
                "scheduled cycle intent is missing its exact completion sentinel"
            )
        return existing_cycle, rows

    cycle = models.ScheduledCycleIntent(
        cycle_id=cycle_id,
        environment=environment,
        lane=lane,
        scheduled_for=scheduled,
        schedule_policy_revision_id=schedule_policy_revision_id,
        mode=mode,
        job_count=len(normalized_jobs),
        intent_sha256=cycle_digest,
        payload_json=cycle_payload,
    )
    session.add(cycle)
    jobs: list[models.ScheduledJobIntent] = []
    for job_payload in normalized_jobs:
        job = models.ScheduledJobIntent(
            job_id=job_payload["jobId"],
            cycle_id=cycle_id,
            environment=environment,
            lane=lane,
            target_type=job_payload["targetType"],
            target_revision_id=job_payload["targetRevisionId"],
            source_revision_id=job_payload["sourceRevisionId"],
            scheduled_for=scheduled,
            schedule_policy_revision_id=schedule_policy_revision_id,
            idempotency_key_sha256=job_payload["idempotencyKeySha256"],
            due_disposition=job_payload["dueDisposition"],
            disposition_reason_code=job_payload["dispositionReasonCode"],
            intent_sha256=_canonical_digest(job_payload),
            payload_json=deepcopy(job_payload),
        )
        jobs.append(job)
        session.add(job)
    try:
        # The deferred cycle->completion FK permits the exact job denominator
        # to exist before the immutable completion sentinel validates it.
        session.flush()
        session.add(
            models.ScheduledCycleIntentCompletion(
                cycle_id=cycle_id,
                intent_sha256=cycle_digest,
                job_count=len(jobs),
            )
        )
        session.flush()
    except IntegrityError as exc:
        raise OperationalReplayConflict(
            "deterministic schedule slot/job is already owned by another immutable intent"
        ) from exc
    return cycle, tuple(jobs)


def append_scheduled_cycle(session: Session, payload: dict[str, Any]) -> models.ScheduledCycle:
    """Append one frozen terminal cycle receipt after its work is durable."""

    document = _payload_copy(payload)
    validate_scheduled_cycle(document)
    cycle_id = document["cycleId"]
    content_sha256 = document["manifest"]["contentSha256"]
    existing_row = session.get(models.ScheduledCycle, cycle_id)
    existing = _exact_existing(
        existing_row,
        identity=cycle_id,
        actual_digest=existing_row.content_sha256 if existing_row is not None else "",
        expected_digest=content_sha256,
    )
    if existing is not None:
        return existing

    scheduled_for = _utc(document["slot"]["scheduledFor"], field="slot.scheduledFor")
    intent = session.get(models.ScheduledCycleIntent, cycle_id)
    if intent is None:
        raise OperationalPersistenceError(
            "terminal cycle cannot precede its durable schedule-slot intent"
        )
    if (
        intent.environment != document["environment"]
        or intent.lane != document["lane"]
        or _stored_utc(intent.scheduled_for) != scheduled_for
        or intent.schedule_policy_revision_id
        != document["schedulePolicyRevisionId"]
        or intent.mode != document["mode"]
    ):
        raise OperationalPersistenceError(
            "terminal cycle does not exactly bind its pre-dispatch slot intent"
        )
    jobs = tuple(
        session.scalars(
            select(models.ScheduledJobIntent)
            .where(models.ScheduledJobIntent.cycle_id == cycle_id)
            .order_by(models.ScheduledJobIntent.job_id)
        )
    )
    terminal_jobs = {item["jobId"]: item for item in document["jobs"]}
    if set(terminal_jobs) != {job.job_id for job in jobs}:
        raise OperationalPersistenceError(
            "terminal cycle job set does not exactly equal its pre-dispatch intents"
        )
    for job in jobs:
        terminal = terminal_jobs[job.job_id]
        for terminal_key, expected in (
            ("targetType", job.target_type),
            ("targetRevisionId", job.target_revision_id),
            ("sourceRevisionId", job.source_revision_id),
            ("idempotencyKeySha256", job.idempotency_key_sha256),
            ("dueDisposition", job.due_disposition),
            ("dispositionReasonCode", job.disposition_reason_code),
        ):
            if terminal[terminal_key] != expected:
                raise OperationalPersistenceError(
                    f"terminal cycle changed job intent field {terminal_key}"
                )
        output = terminal["terminalOutputReference"]
        if output["referenceType"] != "source_check_receipt":
            raise OperationalPersistenceError(
                "terminal output type has no DATA-09 immutable persistence referent"
            )
        output_receipt = session.get(
            models.SourceCheckReceiptRecord, output["referenceId"]
        )
        if (
            output_receipt is None
            or output_receipt.job_id != job.job_id
            or output_receipt.content_sha256 != output["contentSha256"]
        ):
            raise OperationalPersistenceError(
                "terminal output does not re-resolve to the exact persisted source receipt"
            )
    attempts = list(
        session.scalars(
            select(models.ScheduledJobAttempt)
            .where(models.ScheduledJobAttempt.cycle_id == cycle_id)
            .order_by(models.ScheduledJobAttempt.attempt_id)
        )
    )
    validate_scheduled_cycle_attempts(
        document, [attempt.payload_json for attempt in attempts]
    )
    cycle = models.ScheduledCycle(
        cycle_id=cycle_id,
        environment=document["environment"],
        lane=document["lane"],
        scheduled_for=scheduled_for,
        schedule_policy_revision_id=document["schedulePolicyRevisionId"],
        mode=document["mode"],
        content_sha256=content_sha256,
        payload_json=document,
    )
    session.add(cycle)
    try:
        session.flush()
    except IntegrityError as exc:
        raise OperationalReplayConflict(
            "deterministic terminal cycle slot is already owned by another immutable receipt"
        ) from exc
    return cycle


def acquire_job_lease(
    session: Session,
    *,
    job_id: str,
    lease_id: str,
    worker_identity_sha256: str,
    expires_at: str | datetime,
    clock: Callable[[], datetime],
) -> models.ScheduledJobLease:
    """Append one acquisition using a trusted clock and advance one token.

    ``expires_at`` is policy input, but acquisition and initial-heartbeat time
    are sampled only from the injected clock.  A stable lease-ID replay returns
    its stored immutable facts without resampling the clock.
    """

    worker_digest = _sha256(worker_identity_sha256, field="worker_identity_sha256")
    expires = _utc(expires_at, field="expires_at")
    if session.get(models.ScheduledJobIntent, job_id) is None:
        raise OperationalPersistenceError(f"scheduled job {job_id!r} is absent")

    current = session.scalar(
        select(models.ScheduledJobLease)
        .where(models.ScheduledJobLease.job_id == job_id)
        .with_for_update()
    )
    existing_event = session.get(models.ScheduledJobLeaseEvent, lease_id)
    if existing_event is not None:
        if (
            existing_event.job_id != job_id
            or existing_event.worker_identity_sha256 != worker_digest
            or _stored_utc(existing_event.expires_at) != expires
        ):
            raise OperationalReplayConflict(
                f"lease identity {lease_id!r} was replayed with different acquisition facts"
            )
        if current is None or current.current_lease_id != lease_id:
            raise OperationalReplayConflict(
                f"lease identity {lease_id!r} is historical, not the current lease"
            )
        return current

    acquired = _clock_utc(clock, field="clock")
    heartbeat = acquired
    if acquired >= expires:
        raise OperationalPersistenceError(
            "lease requires the trusted acquisition time to precede expires_at"
        )

    if current is None:
        token = 1
        prior_lease_id = None
    else:
        if current.state == "leased" and acquired < _stored_utc(current.expires_at):
            raise OperationalPersistenceError(
                "an unexpired active lease must be released or expire before replacement"
            )
        token = current.fencing_token + 1
        prior_lease_id = current.current_lease_id

    event = models.ScheduledJobLeaseEvent(
        lease_id=lease_id,
        job_id=job_id,
        fencing_token=token,
        prior_lease_id=prior_lease_id,
        worker_identity_sha256=worker_digest,
        acquired_at=acquired,
        expires_at=expires,
        initial_heartbeat_at=heartbeat,
    )
    session.add(event)
    try:
        # Flush the immutable lineage first.  The projection trigger requires
        # its exact event to be durable before the root INSERT or successor
        # UPDATE is evaluated, and the row lock above keeps replacement linear.
        session.flush()
    except IntegrityError as exc:
        raise OperationalReplayConflict(
            "lease acquisition lost a concurrent root/successor race"
        ) from exc
    if current is None:
        current = models.ScheduledJobLease(
            job_id=job_id,
            current_lease_id=lease_id,
            fencing_token=token,
            worker_identity_sha256=worker_digest,
            acquired_at=acquired,
            expires_at=expires,
            last_heartbeat_at=heartbeat,
            state="leased",
        )
        session.add(current)
    else:
        current.current_lease_id = lease_id
        current.fencing_token = token
        current.worker_identity_sha256 = worker_digest
        current.acquired_at = acquired
        current.expires_at = expires
        current.last_heartbeat_at = heartbeat
        current.state = "leased"
    try:
        session.flush()
    except IntegrityError as exc:
        raise OperationalReplayConflict(
            "lease acquisition lost a concurrent root/successor race"
        ) from exc
    return current


def heartbeat_job_lease(
    session: Session,
    *,
    job_id: str,
    lease_id: str,
    fencing_token: int,
    worker_identity_sha256: str,
    clock: Callable[[], datetime],
) -> models.ScheduledJobLease:
    """Advance only the exact current worker's lease using a trusted clock."""

    worker_digest = _sha256(worker_identity_sha256, field="worker_identity_sha256")
    current = session.scalar(
        select(models.ScheduledJobLease)
        .where(models.ScheduledJobLease.job_id == job_id)
        .with_for_update()
    )
    if (
        current is None
        or current.current_lease_id != lease_id
        or current.fencing_token != fencing_token
        or current.worker_identity_sha256 != worker_digest
        or current.state != "leased"
    ):
        raise StaleFencingToken(
            "heartbeat rejected: lease ID/token/worker is not exactly current"
        )
    heartbeat = _clock_utc(clock, field="clock")
    if (
        heartbeat < _stored_utc(current.last_heartbeat_at)
        or heartbeat > _stored_utc(current.expires_at)
    ):
        raise OperationalPersistenceError(
            "heartbeat must be monotonic and no later than lease expiry"
        )
    current.last_heartbeat_at = heartbeat
    session.flush()
    return current


def append_scheduled_job_attempt(
    session: Session,
    payload: dict[str, Any],
    *,
    clock: Callable[[], datetime],
) -> models.ScheduledJobAttempt:
    """Retain an immutable attempt only under a live exact-current lease."""

    document = _payload_copy(payload)
    validate_scheduled_job_attempt(document)
    attempt_id = document["attemptId"]
    content_sha256 = document["manifest"]["contentSha256"]
    existing_row = session.get(models.ScheduledJobAttempt, attempt_id)
    existing = _exact_existing(
        existing_row,
        identity=attempt_id,
        actual_digest=existing_row.content_sha256 if existing_row is not None else "",
        expected_digest=content_sha256,
    )
    if existing is not None:
        return existing

    job = session.get(models.ScheduledJobIntent, document["jobId"])
    if job is None:
        raise OperationalPersistenceError(f"scheduled job {document['jobId']!r} is absent")
    if job.due_disposition == "not_due":
        raise OperationalPersistenceError("a not-due planner intent cannot be dispatched")
    exact_job_bindings = {
        "cycleId": job.cycle_id,
        "environment": job.environment,
        "lane": job.lane,
        "schedulePolicyRevisionId": job.schedule_policy_revision_id,
        "targetType": job.target_type,
        "targetRevisionId": job.target_revision_id,
        "sourceRevisionId": job.source_revision_id,
    }
    for key, expected in exact_job_bindings.items():
        if document[key] != expected:
            raise OperationalPersistenceError(
                f"attempt {key} does not exactly bind its scheduled job"
            )
    if _utc(document["scheduledFor"], field="scheduledFor") != _stored_utc(
        job.scheduled_for
    ):
        raise OperationalPersistenceError(
            "attempt scheduledFor does not exactly bind its scheduled job"
        )

    current = session.scalar(
        select(models.ScheduledJobLease)
        .where(models.ScheduledJobLease.job_id == document["jobId"])
        .with_for_update()
    )
    lease = document["lease"]
    if (
        current is None
        or current.current_lease_id != lease["leaseId"]
        or current.fencing_token != lease["fencingToken"]
    ):
        raise StaleFencingToken(
            "attempt commit rejected: lease ID/token is not exactly current"
        )
    if current.state != "leased":
        raise StaleFencingToken("attempt commit rejected: current lease is already terminal")
    if current.worker_identity_sha256 != document["workerIdentitySha256"]:
        raise StaleFencingToken(
            "attempt commit rejected: worker identity does not own the current lease"
        )
    commit_observed_at = _clock_utc(clock, field="clock")
    if (
        lease["commitDisposition"] == "accepted_current"
        and commit_observed_at > _stored_utc(current.expires_at)
    ):
        raise StaleFencingToken(
            "attempt commit rejected: current lease expired before commit"
        )
    lease_event = session.get(models.ScheduledJobLeaseEvent, lease["leaseId"])
    if (
        lease_event is None
        or lease_event.job_id != job.job_id
        or lease_event.fencing_token != lease["fencingToken"]
        or lease_event.worker_identity_sha256 != document["workerIdentitySha256"]
        or _stored_utc(lease_event.acquired_at)
        != _utc(lease["acquiredAt"], field="lease.acquiredAt")
        or _stored_utc(lease_event.expires_at)
        != _utc(lease["expiresAt"], field="lease.expiresAt")
    ):
        raise OperationalPersistenceError(
            "attempt lease receipt does not exactly bind its acquisition event"
        )
    if lease["priorFencingToken"] is None:
        if lease_event.prior_lease_id is not None:
            raise OperationalPersistenceError("root attempt unexpectedly binds a prior lease")
    else:
        prior_event = session.get(
            models.ScheduledJobLeaseEvent, lease_event.prior_lease_id
        )
        if prior_event is None or prior_event.fencing_token != lease["priorFencingToken"]:
            raise OperationalPersistenceError(
                "attempt does not bind the immutable prior fencing token"
            )
    receipt_heartbeat = _utc(
        lease["lastHeartbeatAt"], field="lease.lastHeartbeatAt"
    )
    if (
        receipt_heartbeat < _stored_utc(current.last_heartbeat_at)
        or receipt_heartbeat > _stored_utc(current.expires_at)
    ):
        raise OperationalPersistenceError(
            "attempt heartbeat regressed or exceeded the current lease expiry"
        )
    attempt_number = document["attemptNumber"]
    prior_attempt = session.scalar(
        select(models.ScheduledJobAttempt).where(
            models.ScheduledJobAttempt.job_id == job.job_id,
            models.ScheduledJobAttempt.attempt_number == attempt_number - 1,
        )
    )
    if attempt_number == 1:
        if prior_attempt is not None or lease["priorFencingToken"] is not None:
            raise OperationalPersistenceError("first attempt cannot bind a predecessor")
    elif (
        prior_attempt is None
        or prior_attempt.fencing_token != lease["priorFencingToken"]
        or current.fencing_token <= prior_attempt.fencing_token
    ):
        raise OperationalPersistenceError(
            "attempt lineage must be contiguous and bind the exact prior fencing token"
        )

    source_receipt_id, source_receipt_sha = _source_check_reference(document)
    row = models.ScheduledJobAttempt(
        attempt_id=attempt_id,
        cycle_id=document["cycleId"],
        job_id=document["jobId"],
        lease_id=lease["leaseId"],
        source_revision_id=document["sourceRevisionId"],
        attempt_number=attempt_number,
        fencing_token=lease["fencingToken"],
        prior_fencing_token=lease["priorFencingToken"],
        worker_identity_sha256=document["workerIdentitySha256"],
        lease_acquired_at=_utc(lease["acquiredAt"], field="lease.acquiredAt"),
        lease_expires_at=_utc(lease["expiresAt"], field="lease.expiresAt"),
        lease_last_heartbeat_at=receipt_heartbeat,
        started_at=_utc(document["timing"]["startedAt"], field="timing.startedAt"),
        ended_at=_utc(document["timing"]["endedAt"], field="timing.endedAt"),
        stage_reached=document["stageReached"],
        outcome=document["outcome"],
        commit_disposition=lease["commitDisposition"],
        source_check_receipt_id=source_receipt_id,
        source_check_receipt_sha256=source_receipt_sha,
        content_sha256=content_sha256,
        payload_json=document,
    )
    session.add(row)
    # Flush while the locked projection still says `leased`; the database
    # trigger independently verifies the exact current owner/event/token.
    session.flush()
    current.last_heartbeat_at = receipt_heartbeat
    current.state = lease["state"]
    session.flush()
    return row


def append_source_attempt_and_receipt(
    session: Session,
    attempt_payload: dict[str, Any],
    receipt_payload: dict[str, Any],
    *,
    source_contract: dict[str, Any] | None = None,
    clock: Callable[[], datetime],
) -> tuple[models.ScheduledJobAttempt, models.SourceCheckReceiptRecord]:
    """Write the exact attempt/receipt pair in one caller-owned transaction."""

    attempt_document = _payload_copy(attempt_payload)
    receipt_document = _payload_copy(receipt_payload)
    validate_scheduled_job_attempt(attempt_document)
    envelope = _resolve_source_contract_envelope(
        session, receipt_document, source_contract=source_contract
    )
    validate_source_check_receipt(receipt_document, source_contract=envelope.payload_json)
    validate_recheck_attempt_receipt(
        attempt_document, receipt_document, source_contract=envelope.payload_json
    )
    attempt = append_scheduled_job_attempt(
        session, attempt_document, clock=clock
    )
    receipt = append_source_check_receipt(
        session, receipt_document, source_contract=envelope.payload_json
    )
    return attempt, receipt


def append_source_contract_envelope(
    session: Session, payload: dict[str, Any]
) -> models.SourceContractEnvelope:
    """Retain validated source-contract bytes without granting authority.

    The envelope is an immutable digest referent for source-check receipts. It
    records what a receipt checked; it neither certifies the source nor makes a
    schedule or publication decision.
    """

    document = _payload_copy(payload)
    validate_source_contract(document)
    contract_revision_id = document["contractRevisionId"]
    content_sha256 = source_contract_digest(document)
    definition_sha256 = source_contract_definition_digest(document)
    if (
        document["manifest"]["contentSha256"] != content_sha256
        or document["manifest"]["definitionSha256"] != definition_sha256
    ):
        raise OperationalPersistenceError(
            "source contract manifest does not re-resolve its immutable bytes"
        )
    existing_row = session.get(models.SourceContractEnvelope, contract_revision_id)
    existing = _exact_existing(
        existing_row,
        identity=contract_revision_id,
        actual_digest=(
            existing_row.contract_digest_sha256 if existing_row is not None else ""
        ),
        expected_digest=content_sha256,
    )
    if existing is not None:
        if existing.payload_json != document:
            raise OperationalReplayConflict(
                "source contract digest replay did not preserve exact immutable bytes"
            )
        return existing

    logical = document["logicalSource"]
    revision = session.get(models.OfficialSourceRevision, logical["sourceRevisionId"])
    if (
        revision is None
        or revision.official_source_id != logical["sourceId"]
        or session.get(models.OfficialSourceRow, logical["sourceId"]) is None
    ):
        raise OperationalPersistenceError(
            "source contract does not bind an exact persisted logical source revision"
        )
    certification = document["certification"]
    decision_id = certification["decisionId"]
    if decision_id is not None:
        decision = session.get(models.SourceRevisionDecision, decision_id)
        decision_evidence = (
            decision.basis_json.get("sourceContractDecisionEvidence")
            if decision is not None and type(decision.basis_json) is dict
            else None
        )
        expected_decision_evidence = {
            "decisionDigestSha256": certification["decisionDigestSha256"],
            "contractDefinitionSha256": definition_sha256,
            "effectiveOn": certification["effectiveOn"],
            "expiresOn": certification["expiresOn"],
        }
        if (
            decision is None
            or decision.source_revision_id != revision.id
            or decision.outcome != certification["decisionOutcome"]
            or decision_evidence != expected_decision_evidence
        ):
            raise OperationalPersistenceError(
                "source contract lacks exact immutable decision evidence for its outcome/digest/definition/window"
            )
    prior_id = document["supersedesContractRevisionId"]
    if prior_id is not None:
        prior = session.get(models.SourceContractEnvelope, prior_id)
        if prior is None or prior.contract_id != document["contractId"]:
            raise OperationalPersistenceError(
                "source contract predecessor is absent or belongs to another contract"
            )

    row = models.SourceContractEnvelope(
        contract_revision_id=contract_revision_id,
        contract_id=document["contractId"],
        supersedes_contract_revision_id=prior_id,
        official_source_id=logical["sourceId"],
        source_revision_id=logical["sourceRevisionId"],
        certification_decision_id=decision_id,
        certification_decision_sha256=certification["decisionDigestSha256"],
        schedule_policy_revision_id=document["schedule"]["schedulePolicyRevisionId"],
        lifecycle_status=document["lifecycleStatus"],
        contract_digest_sha256=content_sha256,
        contract_definition_sha256=definition_sha256,
        payload_json=document,
    )
    session.add(row)
    try:
        session.flush()
    except IntegrityError as exc:
        raise OperationalReplayConflict(
            "source contract revision lost an immutable root/successor race"
        ) from exc
    return row


def _resolve_source_contract_envelope(
    session: Session,
    receipt: Mapping[str, Any],
    *,
    source_contract: dict[str, Any] | None,
) -> models.SourceContractEnvelope:
    identity = receipt.get("identity")
    if type(identity) is not dict or type(identity.get("contractRevisionId")) is not str:
        raise OperationalPersistenceError(
            "source receipt needs a contract revision before persistence"
        )
    if source_contract is not None:
        envelope = append_source_contract_envelope(session, source_contract)
    else:
        envelope = session.get(
            models.SourceContractEnvelope, identity["contractRevisionId"]
        )
        if envelope is None:
            raise OperationalPersistenceError(
                "source receipt has no durable immutable source-contract referent"
            )
    if envelope.contract_revision_id != identity["contractRevisionId"]:
        raise OperationalPersistenceError(
            "supplied source contract revision differs from the receipt"
        )
    return envelope


def append_source_check_receipt(
    session: Session,
    payload: dict[str, Any],
    *,
    source_contract: dict[str, Any] | None = None,
) -> models.SourceCheckReceiptRecord:
    """Retain exact source-check evidence and its accounting-only extraction row."""

    document = _payload_copy(payload)
    envelope = _resolve_source_contract_envelope(
        session, document, source_contract=source_contract
    )
    validate_source_check_receipt(document, source_contract=envelope.payload_json)
    receipt_id = document["receiptId"]
    content_sha256 = document["manifest"]["contentSha256"]
    existing_row = session.get(models.SourceCheckReceiptRecord, receipt_id)
    existing = _exact_existing(
        existing_row,
        identity=receipt_id,
        actual_digest=existing_row.content_sha256 if existing_row is not None else "",
        expected_digest=content_sha256,
    )
    if existing is not None:
        return existing

    identity = document["identity"]
    attempt = session.get(models.ScheduledJobAttempt, identity["attemptId"])
    if attempt is None:
        raise OperationalPersistenceError(
            f"source receipt attempt {identity['attemptId']!r} is absent"
        )
    validate_recheck_attempt_receipt(
        attempt.payload_json, document, source_contract=envelope.payload_json
    )
    if (
        attempt.source_check_receipt_id != receipt_id
        or attempt.source_check_receipt_sha256 != content_sha256
    ):
        raise OperationalPersistenceError(
            "attempt output reference does not exactly bind this source receipt"
        )

    source_revision = session.get(
        models.OfficialSourceRevision, identity["sourceRevisionId"]
    )
    if (
        source_revision is None
        or source_revision.official_source_id != identity["sourceId"]
    ):
        raise OperationalPersistenceError(
            "source receipt revision does not belong to its exact logical source"
        )
    decision_id = identity["certificationDecisionId"]
    execution_started = _utc(
        document["execution"]["startedAt"], field="execution.startedAt"
    )
    if decision_id is not None:
        decision = session.get(models.SourceRevisionDecision, decision_id)
        if (
            decision is None
            or decision.source_revision_id != source_revision.id
        ):
            raise OperationalPersistenceError(
                "source receipt expected decision belongs to another revision"
            )
    certification_check = document["certificationCheck"]
    checked_decision_id = certification_check["checkedDecisionId"]
    if checked_decision_id is not None:
        checked_decision = session.get(
            models.SourceRevisionDecision, checked_decision_id
        )
        effective_successor = session.scalar(
            select(models.SourceRevisionDecision.id)
            .where(
                models.SourceRevisionDecision.supersedes_decision_id
                == checked_decision_id,
                models.SourceRevisionDecision.decided_at <= execution_started,
            )
            .limit(1)
        )
        checked_evidence = (
            checked_decision.basis_json.get("sourceContractDecisionEvidence")
            if checked_decision is not None
            and type(checked_decision.basis_json) is dict
            else None
        )
        expected_outcome = certification_check["outcome"]
        if expected_outcome == "expired":
            expected_outcome = "certified"
        if (
            checked_decision is None
            or checked_decision.source_revision_id != source_revision.id
            or _stored_utc(checked_decision.decided_at) > execution_started
            or effective_successor is not None
            or type(checked_evidence) is not dict
            or checked_evidence.get("decisionDigestSha256")
            != certification_check["checkedDecisionDigestSha256"]
            or checked_evidence.get("contractDefinitionSha256")
            != certification_check["checkedContractDefinitionSha256"]
            or (
                certification_check["outcome"] != "mismatch"
                and checked_decision.outcome != expected_outcome
            )
        ):
            raise OperationalPersistenceError(
                "source receipt does not bind the single effective durable decision evidence at execution start"
            )

    snapshot = document["snapshot"]
    snapshot_id = snapshot["snapshotId"]
    if snapshot_id is not None:
        stored_snapshot = session.get(models.SourceSnapshot, snapshot_id)
        if (
            stored_snapshot is None
            or stored_snapshot.source_revision_id != source_revision.id
            or stored_snapshot.official_source_id != source_revision.official_source_id
            or stored_snapshot.content_hash != snapshot["snapshotContentSha256"]
            or type(stored_snapshot.fetch_metadata) is not dict
            or stored_snapshot.fetch_metadata.get("storageReceiptSha256")
            != snapshot["storageReceiptSha256"]
        ):
            raise OperationalPersistenceError(
                "source receipt snapshot ID/digest/revision binding is not exact"
            )

    conditional = document["conditionalMetadata"]
    previous_snapshot_id = conditional["previousSnapshotId"]
    if previous_snapshot_id is not None:
        previous_snapshot = session.get(models.SourceSnapshot, previous_snapshot_id)
        if (
            previous_snapshot is None
            or previous_snapshot.source_revision_id != source_revision.id
            or previous_snapshot.official_source_id
            != source_revision.official_source_id
            or previous_snapshot.content_hash
            != conditional["previousSnapshotContentSha256"]
            or type(previous_snapshot.fetch_metadata) is not dict
            or previous_snapshot.fetch_metadata.get(
                "storageVerificationReceiptSha256"
            )
            != conditional["previousSnapshotVerificationReceiptSha256"]
        ):
            raise OperationalPersistenceError(
                "304 prior snapshot/content/verification evidence does not re-resolve"
            )

    extraction = document["extraction"]
    row = models.SourceCheckReceiptRecord(
        receipt_id=receipt_id,
        attempt_id=identity["attemptId"],
        job_id=identity["jobId"],
        official_source_id=identity["sourceId"],
        source_revision_id=identity["sourceRevisionId"],
        source_revision_decision_id=decision_id,
        source_revision_decision_sha256=identity[
            "certificationDecisionDigestSha256"
        ],
        checked_source_revision_decision_id=checked_decision_id,
        checked_source_revision_decision_sha256=certification_check[
            "checkedDecisionDigestSha256"
        ],
        certification_check_outcome=certification_check["outcome"],
        contract_id=identity["contractId"],
        contract_revision_id=identity["contractRevisionId"],
        contract_digest_sha256=identity["contractDigestSha256"],
        contract_definition_sha256=identity["contractDefinitionSha256"],
        schedule_policy_revision_id=identity["schedulePolicyRevisionId"],
        scheduled_for=_utc(identity["scheduledSlot"], field="identity.scheduledSlot"),
        fencing_token=identity["fencingToken"],
        snapshot_id=snapshot_id,
        snapshot_content_sha256=snapshot["snapshotContentSha256"],
        snapshot_storage_receipt_sha256=snapshot["storageReceiptSha256"],
        previous_snapshot_id=previous_snapshot_id,
        previous_snapshot_content_sha256=conditional[
            "previousSnapshotContentSha256"
        ],
        previous_snapshot_verification_receipt_sha256=conditional[
            "previousSnapshotVerificationReceiptSha256"
        ],
        batch_receipt_sha256=extraction["batchReceiptSha256"],
        terminal_disposition=document["terminalDisposition"],
        started_at=_utc(document["execution"]["startedAt"], field="execution.startedAt"),
        finished_at=_utc(
            document["execution"]["finishedAt"], field="execution.finishedAt"
        ),
        content_sha256=content_sha256,
        payload_json=document,
    )
    session.add(row)
    session.flush()

    batch_digest = extraction["batchReceiptSha256"]
    if batch_digest is not None:
        batch = models.ExtractionBatch(
            batch_receipt_sha256=batch_digest,
            source_check_receipt_id=receipt_id,
            attempt_id=identity["attemptId"],
            job_id=identity["jobId"],
            source_revision_id=identity["sourceRevisionId"],
            source_revision_decision_id=decision_id,
            snapshot_id=snapshot_id,
            schema_fingerprint_sha256=extraction["schemaFingerprintSha256"],
            source_records_observed=extraction["sourceRecordsObserved"],
            rows_parsed=extraction["rowsParsed"],
            claim_candidates_emitted=extraction["claimCandidatesEmitted"],
            claims_admitted=extraction["claimsAdmitted"],
            records_excluded=extraction["recordsExcluded"],
            records_rejected=extraction["recordsRejected"],
            records_quarantined=extraction["recordsQuarantined"],
            payload_json=deepcopy(extraction),
        )
        session.add(batch)
        session.flush()
    return row


def append_discovery_candidate(
    session: Session, payload: dict[str, Any]
) -> models.DiscoveryCandidate:
    document = _payload_copy(payload)
    validate_discovery_candidate(document)
    candidate_id = document["candidateId"]
    digest = document["manifest"]["contentSha256"]
    existing_row = session.get(models.DiscoveryCandidate, candidate_id)
    existing = _exact_existing(
        existing_row,
        identity=candidate_id,
        actual_digest=existing_row.content_sha256 if existing_row is not None else "",
        expected_digest=digest,
    )
    if existing is not None:
        return existing
    approved_revision = document["approvedSourceRevisionReference"]
    if approved_revision is not None and session.get(
        models.OfficialSourceRevision, approved_revision
    ) is None:
        raise OperationalPersistenceError(
            "approved discovery reference does not resolve to an exact source revision"
        )
    row = models.DiscoveryCandidate(
        candidate_id=candidate_id,
        candidate_fingerprint_sha256=document["candidateFingerprintSha256"],
        candidate_type=document["candidateType"],
        target_revision_id=document["targetRevisionId"],
        state=document["state"],
        state_decision_reference=document["stateDecisionReference"],
        approved_source_revision_id=approved_revision,
        content_sha256=digest,
        payload_json=document,
    )
    session.add(row)
    session.flush()
    return row


def append_benchmark_definition_revision(
    session: Session, payload: dict[str, Any]
) -> models.BenchmarkDefinitionRevision:
    document = _payload_copy(payload)
    validate_benchmark_definition_revision(document)
    revision_id = document["benchmarkDefinitionRevisionId"]
    digest = document["manifest"]["contentSha256"]
    existing_row = session.get(models.BenchmarkDefinitionRevision, revision_id)
    existing = _exact_existing(
        existing_row,
        identity=revision_id,
        actual_digest=existing_row.content_sha256 if existing_row is not None else "",
        expected_digest=digest,
    )
    if existing is not None:
        return existing
    prior = list(
        session.scalars(
            select(models.BenchmarkDefinitionRevision).where(
                models.BenchmarkDefinitionRevision.benchmark_family_id
                == document["benchmarkFamilyId"]
            )
        )
    )
    validate_benchmark_revision_chain([row.payload_json for row in prior] + [document])
    row = models.BenchmarkDefinitionRevision(
        benchmark_definition_revision_id=revision_id,
        benchmark_family_id=document["benchmarkFamilyId"],
        benchmark_edition_id=document["benchmarkEditionId"],
        supersedes_definition_revision_id=document["supersedesDefinitionRevisionId"],
        lifecycle_status=document["lifecycleStatus"],
        decision_reference=document["decisionReference"],
        dimension_fingerprint_sha256=document["manifest"][
            "dimensionFingerprintSha256"
        ],
        content_sha256=digest,
        payload_json=document,
    )
    session.add(row)
    session.flush()
    return row


def append_evaluation_subject_revision(
    session: Session, payload: dict[str, Any]
) -> models.EvaluationSubjectRevision:
    document = _payload_copy(payload)
    validate_evaluation_subject(document)
    revision_id = document["subjectRevisionId"]
    digest = document["manifest"]["contentSha256"]
    existing_row = session.get(models.EvaluationSubjectRevision, revision_id)
    existing = _exact_existing(
        existing_row,
        identity=revision_id,
        actual_digest=existing_row.content_sha256 if existing_row is not None else "",
        expected_digest=digest,
    )
    if existing is not None:
        return existing
    prior = list(
        session.scalars(
            select(models.EvaluationSubjectRevision).where(
                models.EvaluationSubjectRevision.subject_id == document["subjectId"]
            )
        )
    )
    validate_evaluation_subject_revision_chain(
        [row.payload_json for row in prior] + [document]
    )
    model_entity_id = document["displayIdentity"]["modelEntityId"]
    if model_entity_id is not None and session.get(models.ModelEntity, model_entity_id) is None:
        raise OperationalPersistenceError(
            f"evaluation subject model entity {model_entity_id!r} is absent"
        )
    raw_identity_sha256 = hashlib.sha256(
        canonical_identity_json(document["rawSourceIdentity"]).encode("utf-8")
    ).hexdigest()
    row = models.EvaluationSubjectRevision(
        subject_revision_id=revision_id,
        subject_id=document["subjectId"],
        supersedes_subject_revision_id=document["supersedesSubjectRevisionId"],
        subject_type=document["subjectType"],
        lifecycle_status=document["lifecycleStatus"],
        resolution_status=document["resolutionStatus"],
        decision_reference=document["decisionReference"],
        subject_fingerprint_sha256=document["subjectFingerprintSha256"],
        observed_composition_fingerprint_sha256=document[
            "observedCompositionFingerprintSha256"
        ],
        raw_identity_sha256=raw_identity_sha256,
        model_entity_id=model_entity_id,
        content_sha256=digest,
        payload_json=document,
    )
    session.add(row)
    session.flush()
    return row


def append_identity_decision(
    session: Session, payload: dict[str, Any]
) -> models.IdentityDecisionRecord:
    document = _payload_copy(payload)
    validate_identity_decision(document)
    decision_id = document["decisionId"]
    digest = document["manifest"]["contentSha256"]
    existing_row = session.get(models.IdentityDecisionRecord, decision_id)
    existing = _exact_existing(
        existing_row,
        identity=decision_id,
        actual_digest=existing_row.content_sha256 if existing_row is not None else "",
        expected_digest=digest,
    )
    if existing is not None:
        return existing
    candidate = session.get(models.DiscoveryCandidate, document["candidateReference"])
    if candidate is None:
        raise OperationalPersistenceError(
            f"identity candidate {document['candidateReference']!r} is absent"
        )
    evidence_ids = {
        item["evidenceId"] for item in candidate.payload_json["evidenceReferences"]
    }
    if document["observationReference"] not in evidence_ids:
        raise OperationalPersistenceError(
            "identity observation does not resolve inside its exact candidate evidence"
        )
    selected_subject_id = document["selectedSubjectId"]
    if selected_subject_id is not None:
        subject_revisions = list(
            session.scalars(
                select(models.EvaluationSubjectRevision).where(
                    models.EvaluationSubjectRevision.subject_id == selected_subject_id
                )
            )
        )
        superseded_ids = {
            row.supersedes_subject_revision_id
            for row in subject_revisions
            if row.supersedes_subject_revision_id is not None
        }
        leaves = [
            row
            for row in subject_revisions
            if row.subject_revision_id not in superseded_ids
        ]
        if (
            len(leaves) != 1
            or leaves[0].lifecycle_status != "reviewed"
            or leaves[0].resolution_status != "resolved"
            or leaves[0].decision_reference is None
        ):
            raise OperationalPersistenceError(
                "selected identity subject requires one reviewed, resolved live leaf revision"
            )
    prior = list(
        session.scalars(
            select(models.IdentityDecisionRecord).where(
                models.IdentityDecisionRecord.candidate_reference
                == document["candidateReference"]
            )
        )
    )
    validate_identity_decision_chain([row.payload_json for row in prior] + [document])
    row = models.IdentityDecisionRecord(
        decision_id=decision_id,
        candidate_reference=document["candidateReference"],
        observation_reference=document["observationReference"],
        identity_item_fingerprint_sha256=document[
            "identityItemFingerprintSha256"
        ],
        expected_prior_decision_id=document["expectedPriorDecisionId"],
        decision_sequence=document["decisionSequence"],
        decision_status=document["decisionStatus"],
        decided_at=(
            _utc(document["decidedAt"], field="decidedAt")
            if document["decidedAt"] is not None
            else None
        ),
        selected_subject_id=selected_subject_id,
        content_sha256=digest,
        payload_json=document,
    )
    session.add(row)
    session.flush()
    return row


def _outbox_batch_id(intent_ids: Iterable[str]) -> str:
    material = json.dumps(sorted(intent_ids), separators=(",", ":"), ensure_ascii=True)
    return "outbox-" + hashlib.sha256(material.encode("utf-8")).hexdigest()


def append_ops_incident(
    session: Session,
    payload: dict[str, Any],
    *,
    notification_intents: Sequence[dict[str, Any]] = (),
) -> models.OpsIncident:
    """Append a complete incident contract and optional atomic local outbox rows."""

    document = _payload_copy(payload)
    validate_ops_incident(document)
    intents = [_payload_copy(item) for item in notification_intents]
    for intent in intents:
        validate_notification_intent(intent)
        validate_incident_notification_binding(document, intent)

    incident_id = document["incidentId"]
    digest = document["manifest"]["contentSha256"]
    incident = session.get(models.OpsIncident, incident_id)
    if incident is None:
        incident = models.OpsIncident(
            incident_id=incident_id,
            incident_fingerprint_sha256=document["incidentFingerprintSha256"],
            family=document["family"],
            incident_code=document["incidentCode"],
            cause_code=document["causeCode"],
            environment=document["environment"],
            first_contract_sha256=digest,
        )
        session.add(incident)
        session.flush()
    elif (
        incident.incident_fingerprint_sha256 != document["incidentFingerprintSha256"]
        or incident.family != document["family"]
        or incident.incident_code != document["incidentCode"]
        or incident.cause_code != document["causeCode"]
        or incident.environment != document["environment"]
    ):
        raise OperationalReplayConflict(
            "incident stable identity was replayed with different fingerprint material"
        )

    intents_by_event: dict[str, list[dict[str, Any]]] = {}
    for intent in intents:
        intents_by_event.setdefault(intent["incidentEventId"], []).append(intent)

    new_event_ids: set[str] = set()
    for index, event in enumerate(document["events"]):
        event_id = event["eventId"]
        event_intents = intents_by_event.get(event_id, [])
        batch_id = _outbox_batch_id(item["intentId"] for item in event_intents)
        existing_event = session.get(models.OpsIncidentEvent, event_id)
        if existing_event is not None:
            if (
                existing_event.incident_id != incident_id
                or canonical_incident_json(existing_event.event_payload_json)
                != canonical_incident_json(event)
            ):
                raise OperationalReplayConflict(
                    f"incident event {event_id!r} was replayed with different evidence"
                )
            if event_intents or index == len(document["events"]) - 1:
                if (
                    existing_event.outbox_batch_id != batch_id
                    or existing_event.outbox_intent_count != len(event_intents)
                ):
                    raise OperationalReplayConflict(
                        f"incident event {event_id!r} changed its immutable outbox denominator"
                    )
                stored_ids = set(
                    session.scalars(
                        select(models.NotificationOutboxItem.intent_id).where(
                            models.NotificationOutboxItem.incident_event_id
                            == event_id
                        )
                    )
                )
                if stored_ids != {item["intentId"] for item in event_intents}:
                    raise OperationalReplayConflict(
                        f"incident event {event_id!r} changed its immutable outbox denominator"
                    )
            continue
        session.add(
            models.OpsIncidentEvent(
                event_id=event_id,
                incident_id=incident_id,
                event_ordinal=event["eventOrdinal"],
                expected_prior_event_id=event["expectedPriorEventId"],
                event_type=event["eventType"],
                from_state=event["fromState"],
                to_state=event["toState"],
                occurred_at=_utc(event["occurredAt"], field="events.occurredAt"),
                event_payload_json=deepcopy(event),
                contract_content_sha256=(
                    digest if index == len(document["events"]) - 1 else None
                ),
                contract_payload_json=(
                    document if index == len(document["events"]) - 1 else None
                ),
                outbox_batch_id=batch_id,
                outbox_intent_count=len(event_intents),
            )
        )
        new_event_ids.add(event_id)
        session.flush()
        for ordinal, intent in enumerate(
            sorted(event_intents, key=lambda item: item["intentId"])
        ):
            session.add(
                models.NotificationOutboxItem(
                    incident_event_id=event_id,
                    intent_id=intent["intentId"],
                    intent_ordinal=ordinal,
                    outbox_batch_id=batch_id,
                )
            )
        session.flush()

    leaf = session.get(models.OpsIncidentEvent, document["events"][-1]["eventId"])
    assert leaf is not None
    if leaf.contract_content_sha256 != digest:
        raise OperationalReplayConflict(
            "incident contract changed without appending a new immutable event"
        )

    for event_id, event_intents in intents_by_event.items():
        if event_id not in new_event_ids:
            for intent in event_intents:
                existing_intent = session.get(
                    models.NotificationIntentRecord, intent["intentId"]
                )
                if (
                    existing_intent is None
                    or existing_intent.content_sha256
                    != intent["manifest"]["contentSha256"]
                ):
                    raise OperationalPersistenceError(
                        "a new outbox intent must be atomic with its newly appended incident event"
                    )
                continue
        event_row = session.get(models.OpsIncidentEvent, event_id)
        assert event_row is not None
        for intent in event_intents:
            _append_notification_intent(
                session, intent, outbox_batch_id=event_row.outbox_batch_id
            )
    for event_id in new_event_ids:
        event_row = session.get(models.OpsIncidentEvent, event_id)
        assert event_row is not None
        session.add(
            models.NotificationOutboxBatch(
                incident_event_id=event_id,
                outbox_batch_id=event_row.outbox_batch_id,
                intent_count=event_row.outbox_intent_count,
            )
        )
    session.flush()
    return incident


def append_review_work_item(
    session: Session, payload: dict[str, Any]
) -> models.ReviewWorkItem:
    """Append a complete review-work contract without changing any claim state."""

    document = _payload_copy(payload)
    validate_review_work_item(document)
    work_item_id = document["workItemId"]
    digest = document["manifest"]["contentSha256"]
    item = session.get(models.ReviewWorkItem, work_item_id)
    if item is None:
        item = models.ReviewWorkItem(
            work_item_id=work_item_id,
            work_item_fingerprint_sha256=document["workItemFingerprintSha256"],
            environment=document["environment"],
            work_class=document["workClass"],
            reason_code=document["reasonCode"],
            publication_blocking=document["publicationBlocking"],
            first_contract_sha256=digest,
        )
        session.add(item)
        session.flush()
    elif (
        item.work_item_fingerprint_sha256 != document["workItemFingerprintSha256"]
        or item.environment != document["environment"]
        or item.work_class != document["workClass"]
        or item.reason_code != document["reasonCode"]
        or item.publication_blocking != document["publicationBlocking"]
    ):
        raise OperationalReplayConflict(
            "work-item stable identity was replayed with different fingerprint material"
        )

    for index, event in enumerate(document["events"]):
        event_id = event["eventId"]
        existing_event = session.get(models.ReviewWorkItemEvent, event_id)
        if existing_event is not None:
            if (
                existing_event.work_item_id != work_item_id
                or canonical_incident_json(existing_event.event_payload_json)
                != canonical_incident_json(event)
            ):
                raise OperationalReplayConflict(
                    f"work event {event_id!r} was replayed with different evidence"
                )
            continue
        session.add(
            models.ReviewWorkItemEvent(
                event_id=event_id,
                work_item_id=work_item_id,
                event_ordinal=event["eventOrdinal"],
                expected_prior_event_id=event["expectedPriorEventId"],
                event_type=event["eventType"],
                from_state=event["fromState"],
                to_state=event["toState"],
                occurred_at=_utc(event["occurredAt"], field="events.occurredAt"),
                event_payload_json=deepcopy(event),
                contract_content_sha256=(
                    digest if index == len(document["events"]) - 1 else None
                ),
                contract_payload_json=(
                    document if index == len(document["events"]) - 1 else None
                ),
            )
        )
        session.flush()
    leaf = session.get(models.ReviewWorkItemEvent, document["events"][-1]["eventId"])
    assert leaf is not None
    if leaf.contract_content_sha256 != digest:
        raise OperationalReplayConflict(
            "work-item contract changed without appending a new immutable event"
        )
    return item


def _append_notification_intent(
    session: Session,
    payload: dict[str, Any],
    *,
    outbox_batch_id: str,
) -> models.NotificationIntentRecord:
    """Append one already-authorized local outbox row; this function never sends."""

    document = _payload_copy(payload)
    validate_notification_intent(document)
    intent_id = document["intentId"]
    digest = document["manifest"]["contentSha256"]
    existing_row = session.get(models.NotificationIntentRecord, intent_id)
    existing = _exact_existing(
        existing_row,
        identity=intent_id,
        actual_digest=existing_row.content_sha256 if existing_row is not None else "",
        expected_digest=digest,
    )
    if existing is not None:
        if existing.outbox_batch_id != outbox_batch_id:
            raise OperationalReplayConflict("notification intent changed outbox transaction")
        return existing
    event = session.get(models.OpsIncidentEvent, document["incidentEventId"])
    if (
        event is None
        or event.incident_id != document["incidentId"]
        or event.outbox_batch_id != outbox_batch_id
    ):
        raise OperationalPersistenceError(
            "notification intent must bind the exact incident event/outbox batch"
        )
    outbox_item = session.get(
        models.NotificationOutboxItem,
        (document["incidentEventId"], document["intentId"]),
    )
    if outbox_item is None or outbox_item.outbox_batch_id != outbox_batch_id:
        raise OperationalPersistenceError(
            "notification intent is absent from the event's immutable intent denominator"
        )
    row = models.NotificationIntentRecord(
        intent_id=intent_id,
        dedupe_key_sha256=document["dedupeKeySha256"],
        incident_id=document["incidentId"],
        incident_event_id=document["incidentEventId"],
        notification_kind=document["notificationKind"],
        route_id=document["route"]["routeId"],
        dispatch_eligibility=document["dispatchEligibility"],
        outbox_batch_id=outbox_batch_id,
        content_sha256=digest,
        payload_json=document,
    )
    session.add(row)
    session.flush()
    return row


def append_notification_receipt(
    session: Session, payload: dict[str, Any]
) -> models.NotificationReceiptRecord:
    """Append one immutable local/delivery receipt; no provider call is made."""

    document = _payload_copy(payload)
    validate_notification_receipt(document)
    receipt_id = document["receiptId"]
    digest = document["manifest"]["contentSha256"]
    existing_row = session.get(models.NotificationReceiptRecord, receipt_id)
    existing = _exact_existing(
        existing_row,
        identity=receipt_id,
        actual_digest=existing_row.content_sha256 if existing_row is not None else "",
        expected_digest=digest,
    )
    if existing is not None:
        return existing
    intent_id = document["intentBinding"]["intentId"]
    intent = session.get(models.NotificationIntentRecord, intent_id)
    if intent is None:
        raise OperationalPersistenceError(
            f"notification intent {intent_id!r} is absent"
        )
    validate_notification_pair(intent.payload_json, document)
    binding = document["intentBinding"]
    finished_at = max(
        _utc(attempt["endedAt"], field="attempts.endedAt")
        for attempt in document["attempts"]
    )
    prior_id = document["recovery"]["priorReceiptId"]
    if prior_id is not None:
        prior = session.get(models.NotificationReceiptRecord, prior_id)
        recovered_at = _utc(
            document["recovery"]["recoveredAt"], field="recovery.recoveredAt"
        )
        if (
            prior is None
            or prior.receipt_id == receipt_id
            or prior.intent_id == intent_id
            or prior.incident_id != intent.incident_id
            or prior.route_id != binding["routeId"]
            or _stored_utc(prior.finished_at) > recovered_at
            or recovered_at > finished_at
        ):
            raise OperationalPersistenceError(
                "recovery predecessor must be an earlier receipt for another intent on the same incident route"
            )
    row = models.NotificationReceiptRecord(
        receipt_id=receipt_id,
        receipt_dedupe_key_sha256=document["receiptDedupeKeySha256"],
        intent_id=intent_id,
        incident_id=intent.incident_id,
        route_id=binding["routeId"],
        adapter_id=binding["adapterId"],
        adapter_version=binding["adapterVersion"],
        prior_receipt_id=prior_id,
        finished_at=finished_at,
        outcome=document["outcome"],
        content_sha256=digest,
        payload_json=document,
    )
    session.add(row)
    session.flush()
    return row


__all__ = [
    "OperationalPersistenceError",
    "OperationalReplayConflict",
    "StaleFencingToken",
    "acquire_job_lease",
    "append_benchmark_definition_revision",
    "append_discovery_candidate",
    "append_evaluation_subject_revision",
    "append_identity_decision",
    "append_notification_receipt",
    "append_ops_incident",
    "append_review_work_item",
    "append_scheduled_cycle",
    "append_scheduled_cycle_intent",
    "append_scheduled_job_attempt",
    "append_source_contract_envelope",
    "append_source_attempt_and_receipt",
    "append_source_check_receipt",
    "heartbeat_job_lease",
]
