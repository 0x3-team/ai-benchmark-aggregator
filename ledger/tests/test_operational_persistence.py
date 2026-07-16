from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, event, func, insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import models
from app.db.operational_repositories import (
    OperationalPersistenceError,
    StaleFencingToken,
    acquire_job_lease,
    append_scheduled_cycle_intent,
    append_scheduled_job_attempt,
    heartbeat_job_lease,
)
from app.schemas.operations_contracts import (
    contract_self_digest,
    derive_attempt_id,
)


ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "docs" / "contracts" / "examples"
UTC = timezone.utc
WORKER_ONE = "2" * 64
WORKER_TWO = "3" * 64


def _alembic_config(database_url: str) -> Config:
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url)
    config.attributes["database_url"] = database_url
    return config


@pytest.fixture()
def operational_engine(tmp_path: Path):
    database_url = f"sqlite:///{tmp_path / 'operational.db'}"
    command.upgrade(_alembic_config(database_url), "head")
    engine = create_engine(database_url, future=True)

    @event.listens_for(engine, "connect")
    def _foreign_keys(dbapi_connection, _connection_record) -> None:  # type: ignore[no-untyped-def]
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    yield engine
    engine.dispose()


def _append_discovery_intent(
    session: Session,
    *,
    target: str = "discovery-target-example-v1",
    scheduled_for: str = "2026-07-15T00:00:00Z",
) -> tuple[models.ScheduledCycleIntent, models.ScheduledJobIntent]:
    cycle, jobs = append_scheduled_cycle_intent(
        session,
        environment="shadow-eu",
        lane="discovery",
        scheduled_for=scheduled_for,
        schedule_policy_revision_id="schedule-policy-example-v1",
        mode="synthetic_fixture",
        job_targets=[
            {
                "targetType": "discovery_target",
                "targetRevisionId": target,
                "sourceRevisionId": None,
                "dueDisposition": "due",
                "dispositionReasonCode": "DUE_BY_SCHEDULE",
            }
        ],
    )
    return cycle, jobs[0]


def _clock(value: datetime):  # type: ignore[no-untyped-def]
    return lambda: value


def _retryable_attempt(
    *,
    cycle: models.ScheduledCycleIntent,
    job: models.ScheduledJobIntent,
    lease: models.ScheduledJobLeaseEvent,
) -> dict:
    payload = json.loads(
        (EXAMPLES / "scheduled-job-attempt-v1.valid.json").read_text(
            encoding="utf-8"
        )
    )
    payload.update(
        {
            "attemptId": derive_attempt_id(job.job_id, 1),
            "cycleId": cycle.cycle_id,
            "jobId": job.job_id,
            "environment": job.environment,
            "lane": job.lane,
            "schedulePolicyRevisionId": job.schedule_policy_revision_id,
            "scheduledFor": "2026-07-15T00:00:00Z",
            "targetType": job.target_type,
            "targetRevisionId": job.target_revision_id,
            "sourceRevisionId": None,
            "workerIdentitySha256": lease.worker_identity_sha256,
            "stageReached": "fetch_started",
            "outcome": "retryable_failed",
            "causeCode": "TIMEOUT",
        }
    )
    payload["lease"] = {
        "leaseId": lease.lease_id,
        "fencingToken": lease.fencing_token,
        "priorFencingToken": None,
        "acquiredAt": "2026-07-15T00:00:10Z",
        "expiresAt": "2026-07-15T00:10:10Z",
        "lastHeartbeatAt": "2026-07-15T00:01:00Z",
        "state": "expired",
        "commitPresentedToken": None,
        "commitDisposition": "no_commit",
    }
    payload["retry"].update(
        {
            "classification": "transient",
            "retryAt": "2026-07-15T00:03:00Z",
            "backoffSeconds": 60,
            "retryAfterSource": "policy",
        }
    )
    payload["outputReferences"] = []
    payload["manifest"]["outputReferenceCount"] = 0
    payload["manifest"]["contentSha256"] = "0" * 64
    payload["manifest"]["contentSha256"] = contract_self_digest(payload)
    return payload


def _successful_discovery_attempt(
    *,
    cycle: models.ScheduledCycleIntent,
    job: models.ScheduledJobIntent,
    lease: models.ScheduledJobLeaseEvent,
) -> dict:
    payload = _retryable_attempt(cycle=cycle, job=job, lease=lease)
    payload.update(
        {
            "stageReached": "discovery_accounted",
            "outcome": "succeeded",
            "causeCode": "ATTEMPT_COMPLETED",
        }
    )
    payload["lease"].update(
        {
            "state": "released",
            "commitPresentedToken": lease.fencing_token,
            "commitDisposition": "accepted_current",
        }
    )
    payload["retry"].update(
        {
            "classification": "none",
            "retryAt": None,
            "backoffSeconds": 0,
            "retryAfterSource": "none",
        }
    )
    payload["outputReferences"] = [
        {
            "referenceType": "discovery_receipt",
            "referenceId": "discovery-receipt-expired-clock",
            "contentSha256": "5" * 64,
        }
    ]
    payload["manifest"]["outputReferenceCount"] = 1
    payload["manifest"]["contentSha256"] = "0" * 64
    payload["manifest"]["contentSha256"] = contract_self_digest(payload)
    return payload


def test_operational_migration_surface_and_cycle_intent_replay(
    operational_engine,
) -> None:
    with Session(operational_engine) as session, session.begin():
        cycle, job = _append_discovery_intent(session)
        cycle_id = cycle.cycle_id
        job_id = job.job_id

    with Session(operational_engine) as session, session.begin():
        replayed_cycle, replayed_job = _append_discovery_intent(session)
        assert replayed_cycle.cycle_id == cycle_id
        assert replayed_job.job_id == job_id
        assert session.scalar(select(func.count()).select_from(models.ScheduledCycleIntent)) == 1
        assert session.scalar(select(func.count()).select_from(models.ScheduledJobIntent)) == 1
        assert (
            session.scalar(
                select(func.count()).select_from(
                    models.ScheduledCycleIntentCompletion
                )
            )
            == 1
        )
        assert session.scalar(select(func.count()).select_from(models.ResultClaim)) == 0
        assert (
            session.scalar(select(func.count()).select_from(models.SourceRevisionDecision))
            == 0
        )
        assert (
            session.scalar(select(func.count()).select_from(models.ClaimPublicationDecision))
            == 0
        )


def test_injected_clock_takeover_boundary_worker_heartbeat_and_stale_commit(
    operational_engine,
) -> None:
    acquired = datetime(2026, 7, 15, 0, 0, 10, tzinfo=UTC)
    expiry = datetime(2026, 7, 15, 0, 10, 10, tzinfo=UTC)
    with Session(operational_engine) as session, session.begin():
        cycle, job = _append_discovery_intent(session)
        current = acquire_job_lease(
            session,
            job_id=job.job_id,
            lease_id="lease-example-1",
            worker_identity_sha256=WORKER_ONE,
            expires_at=expiry,
            clock=_clock(acquired),
        )
        assert current.acquired_at == acquired
        assert current.last_heartbeat_at == acquired

    with Session(operational_engine) as session, session.begin():
        job = session.scalar(select(models.ScheduledJobIntent))
        assert job is not None
        persisted_cycle = session.get(models.ScheduledCycleIntent, job.cycle_id)
        assert persisted_cycle is not None
        with pytest.raises(OperationalPersistenceError, match="unexpired"):
            acquire_job_lease(
                session,
                job_id=job.job_id,
                lease_id="lease-example-2",
                worker_identity_sha256=WORKER_TWO,
                expires_at=expiry + timedelta(minutes=10),
                clock=_clock(expiry - timedelta(microseconds=1)),
            )

        current = acquire_job_lease(
            session,
            job_id=job.job_id,
            lease_id="lease-example-2",
            worker_identity_sha256=WORKER_TWO,
            expires_at=expiry + timedelta(minutes=10),
            clock=_clock(expiry),
        )
        assert current.fencing_token == 2
        assert current.acquired_at == expiry

        with pytest.raises(StaleFencingToken, match="worker"):
            heartbeat_job_lease(
                session,
                job_id=job.job_id,
                lease_id="lease-example-2",
                fencing_token=2,
                worker_identity_sha256=WORKER_ONE,
                clock=_clock(expiry + timedelta(seconds=30)),
            )
        heartbeat_job_lease(
            session,
            job_id=job.job_id,
            lease_id="lease-example-2",
            fencing_token=2,
            worker_identity_sha256=WORKER_TWO,
            clock=_clock(expiry + timedelta(seconds=30)),
        )

        root = session.get(models.ScheduledJobLeaseEvent, "lease-example-1")
        assert root is not None
        stale_attempt = _retryable_attempt(
            cycle=persisted_cycle, job=job, lease=root
        )
        with pytest.raises(StaleFencingToken, match="not exactly current"):
            append_scheduled_job_attempt(
                session,
                stale_attempt,
                clock=_clock(datetime(2026, 7, 15, 0, 10, 10, tzinfo=UTC)),
            )

        replay = acquire_job_lease(
            session,
            job_id=job.job_id,
            lease_id="lease-example-2",
            worker_identity_sha256=WORKER_TWO,
            expires_at=expiry + timedelta(minutes=10),
            clock=lambda: (_ for _ in ()).throw(AssertionError("clock resampled")),
        )
        assert replay.fencing_token == 2


def test_sqlite_expired_accepted_commit_rejects_forged_application_clock(
    operational_engine,
) -> None:
    acquired = datetime(2026, 7, 15, 0, 0, 10, tzinfo=UTC)
    expiry = datetime(2026, 7, 15, 0, 10, 10, tzinfo=UTC)
    with Session(operational_engine) as session, session.begin():
        cycle, job = _append_discovery_intent(
            session, target="discovery-target-expired-commit"
        )
        acquire_job_lease(
            session,
            job_id=job.job_id,
            lease_id="lease-expired-commit",
            worker_identity_sha256=WORKER_ONE,
            expires_at=expiry,
            clock=_clock(acquired),
        )
        lease = session.get(models.ScheduledJobLeaseEvent, "lease-expired-commit")
        assert lease is not None
        attempt = _successful_discovery_attempt(
            cycle=cycle, job=job, lease=lease
        )

        # A forged in-window application clock is insufficient: SQLite's own
        # clock independently rejects an accepted commit after real expiry.
        with pytest.raises(IntegrityError, match="exact current worker"):
            with session.begin_nested():
                append_scheduled_job_attempt(
                    session,
                    attempt,
                    clock=_clock(acquired + timedelta(minutes=2)),
                )
        assert session.get(models.ScheduledJobAttempt, attempt["attemptId"]) is None

        # The supported repository path also rejects a trusted post-expiry
        # sample before attempting the insert.
        with pytest.raises(StaleFencingToken, match="expired before commit"):
            append_scheduled_job_attempt(
                session,
                attempt,
                clock=_clock(expiry + timedelta(microseconds=1)),
            )
        current = session.get(models.ScheduledJobLease, job.job_id)
        assert current is not None and current.state == "leased"


def test_sqlite_direct_sql_rejects_forged_future_takeover(
    operational_engine,
) -> None:
    now = datetime.now(UTC)
    expiry = now + timedelta(minutes=10)
    with Session(operational_engine) as session, session.begin():
        _, job = _append_discovery_intent(
            session,
            target="discovery-target-live-clock",
            scheduled_for="2026-07-15T01:00:00Z",
        )
        acquire_job_lease(
            session,
            job_id=job.job_id,
            lease_id="lease-live-clock-1",
            worker_identity_sha256=WORKER_ONE,
            expires_at=expiry,
            clock=_clock(now),
        )
        job_id = job.job_id

    forged_acquired = expiry + timedelta(seconds=1)
    with Session(operational_engine) as session:
        with pytest.raises(IntegrityError, match="exact monotonic lineage"):
            session.execute(
                insert(models.ScheduledJobLeaseEvent).values(
                    lease_id="lease-live-clock-forged",
                    job_id=job_id,
                    fencing_token=2,
                    prior_lease_id="lease-live-clock-1",
                    worker_identity_sha256=WORKER_TWO,
                    acquired_at=forged_acquired,
                    expires_at=forged_acquired + timedelta(minutes=10),
                    initial_heartbeat_at=forged_acquired,
                )
            )
            session.flush()


def test_immutable_operational_rows_reject_mutation(operational_engine) -> None:
    with Session(operational_engine) as session, session.begin():
        cycle, _ = _append_discovery_intent(session)
        cycle_id = cycle.cycle_id

    with Session(operational_engine) as session:
        cycle = session.get(models.ScheduledCycleIntent, cycle_id)
        assert cycle is not None
        changed = deepcopy(cycle.payload_json)
        changed["environment"] = "substituted"
        cycle.payload_json = changed
        with pytest.raises(IntegrityError, match="append-only"):
            session.flush()
