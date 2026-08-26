from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
from threading import Barrier

import pytest
from sqlalchemy import create_engine, func, insert, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from app.db import models
from app.db.migrate import initialize_database, inspect_database
from app.db.operational_repositories import (
    OperationalPersistenceError,
    StaleFencingToken,
    acquire_job_lease,
    append_benchmark_definition_revision,
    append_discovery_candidate,
    append_evaluation_subject_revision,
    append_identity_decision,
    append_ops_incident,
    append_review_work_item,
    append_scheduled_cycle_intent,
    append_scheduled_job_attempt,
    heartbeat_job_lease,
)
from app.db.postgresql import render_least_privilege_role_sql
from app.schemas.coverage_contracts import contract_self_digest as coverage_digest
from app.schemas.operations_contracts import contract_self_digest, derive_attempt_id
from postgresql_test_support import skip_or_fail


ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "docs" / "contracts" / "examples"
TARGET_ENV = "TEST_POSTGRESQL_URL"
RESET_ENV = "TEST_POSTGRESQL_ALLOW_RESET"
UTC = timezone.utc
WORKER_ONE = "2" * 64
WORKER_TWO = "3" * 64
WORKER_THREE = "4" * 64
ROLES = {
    "migrator": "data09_test_migrator",
    "ingestion": "data09_test_ingestion",
    "governance": "data09_test_governance",
    "artifact": "data09_test_artifact",
    "audit": "data09_test_audit",
}


def _target_url() -> str:
    database_url = os.environ.get(TARGET_ENV)
    if not database_url:
        skip_or_fail(f"real PostgreSQL proof requires {TARGET_ENV}")
    if os.environ.get(RESET_ENV) != "1":
        pytest.fail(f"{RESET_ENV}=1 is required for destructive disposable-target tests")
    url = make_url(database_url)
    if url.get_backend_name() != "postgresql":
        pytest.fail(f"{TARGET_ENV} must be an explicit PostgreSQL URL")
    name = (url.database or "").lower()
    if not any(marker in name for marker in ("test", "disposable", "phase2b")):
        pytest.fail("refusing target whose database name lacks a disposable marker")
    return database_url


def _engine(database_url: str):
    return create_engine(database_url, future=True, poolclass=NullPool)


def _reset_public_schema(database_url: str) -> None:
    engine = _engine(database_url)
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        connection.exec_driver_sql("DROP SCHEMA IF EXISTS public CASCADE")
        connection.exec_driver_sql("CREATE SCHEMA public")
    engine.dispose()


def _drop_roles(database_url: str) -> None:
    engine = _engine(database_url)
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        for role in reversed(tuple(ROLES.values())):
            if connection.execute(
                text("SELECT 1 FROM pg_roles WHERE rolname = :role"), {"role": role}
            ).scalar_one_or_none():
                connection.exec_driver_sql(f"DROP OWNED BY {role}")
                connection.exec_driver_sql(f"DROP ROLE {role}")
    engine.dispose()


@pytest.fixture()
def postgresql_target() -> str:
    database_url = _target_url()
    _reset_public_schema(database_url)
    _drop_roles(database_url)
    try:
        assert initialize_database(database_url).kind == "current"
        yield database_url
    finally:
        # Drop owned schema objects before the NOLOGIN owner groups.
        _reset_public_schema(database_url)
        _drop_roles(database_url)


def _load(name: str) -> dict:
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


def _clock(value: datetime):  # type: ignore[no-untyped-def]
    return lambda: value


def _append_discovery_intent(session: Session):  # type: ignore[no-untyped-def]
    cycle, jobs = append_scheduled_cycle_intent(
        session,
        environment="pg-data09",
        lane="discovery",
        scheduled_for="2026-07-15T00:00:00Z",
        schedule_policy_revision_id="schedule-policy-data09-v1",
        mode="synthetic_fixture",
        job_targets=[
            {
                "targetType": "discovery_target",
                "targetRevisionId": "discovery-target-data09-v1",
                "sourceRevisionId": None,
                "dueDisposition": "due",
                "dispositionReasonCode": "DUE_BY_SCHEDULE",
            }
        ],
    )
    return cycle, jobs[0]


def _retryable_attempt(
    *,
    cycle: models.ScheduledCycleIntent,
    job: models.ScheduledJobIntent,
    lease: models.ScheduledJobLeaseEvent,
) -> dict:
    payload = _load("scheduled-job-attempt-v1.valid.json")
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


def _assert_permission_denied(engine, role: str, statement: str) -> None:  # type: ignore[no-untyped-def]
    with engine.connect() as connection:
        transaction = connection.begin()
        connection.exec_driver_sql(f"SET LOCAL ROLE {role}")
        with pytest.raises(DBAPIError, match="permission denied"):
            connection.exec_driver_sql(statement)
        transaction.rollback()


def test_postgresql_two_writer_fencing_clock_guard_and_stale_commit(
    postgresql_target: str,
) -> None:
    engine = _engine(postgresql_target)
    acquired = datetime(2026, 7, 15, 0, 0, 10, tzinfo=UTC)
    boundary = datetime(2026, 7, 15, 0, 10, 10, tzinfo=UTC)
    successor_expiry = datetime(2099, 1, 1, 0, 0, 0, tzinfo=UTC)
    try:
        with Session(engine) as session, session.begin():
            cycle, job = _append_discovery_intent(session)
            acquire_job_lease(
                session,
                job_id=job.job_id,
                lease_id="lease-pg-root",
                worker_identity_sha256=WORKER_ONE,
                expires_at=boundary,
                clock=_clock(acquired),
            )
            job_id = job.job_id
            cycle_id = cycle.cycle_id

        with Session(engine) as session, session.begin():
            persisted_cycle = session.get(models.ScheduledCycleIntent, cycle_id)
            persisted_job = session.get(models.ScheduledJobIntent, job_id)
            root = session.get(models.ScheduledJobLeaseEvent, "lease-pg-root")
            assert persisted_cycle is not None and persisted_job is not None and root is not None
            expired_commit = _successful_discovery_attempt(
                cycle=persisted_cycle,
                job=persisted_job,
                lease=root,
            )
            with pytest.raises(IntegrityError, match="exact current worker"):
                with session.begin_nested():
                    append_scheduled_job_attempt(
                        session,
                        expired_commit,
                        clock=_clock(acquired + timedelta(minutes=2)),
                    )
            assert session.get(
                models.ScheduledJobAttempt, expired_commit["attemptId"]
            ) is None
            with pytest.raises(StaleFencingToken, match="expired before commit"):
                append_scheduled_job_attempt(
                    session,
                    expired_commit,
                    clock=_clock(boundary + timedelta(microseconds=1)),
                )
            current = session.get(models.ScheduledJobLease, job_id)
            assert current is not None and current.state == "leased"

        barrier = Barrier(2)

        def contend(lease_id: str, worker: str) -> tuple[str, str]:
            with Session(engine) as session:
                barrier.wait(timeout=10)
                try:
                    row = acquire_job_lease(
                        session,
                        job_id=job_id,
                        lease_id=lease_id,
                        worker_identity_sha256=worker,
                        expires_at=successor_expiry,
                        clock=_clock(boundary),
                    )
                    session.commit()
                    return "committed", row.current_lease_id
                except OperationalPersistenceError:
                    session.rollback()
                    return "rejected", lease_id

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(
                pool.map(
                    lambda args: contend(*args),
                    (("lease-pg-a", WORKER_TWO), ("lease-pg-b", WORKER_THREE)),
                )
            )
        assert [state for state, _ in results].count("committed") == 1
        winner = next(lease for state, lease in results if state == "committed")
        winner_worker = WORKER_TWO if winner == "lease-pg-a" else WORKER_THREE

        with Session(engine) as session, session.begin():
            tokens = list(
                session.execute(
                    select(
                        models.ScheduledJobLeaseEvent.lease_id,
                        models.ScheduledJobLeaseEvent.fencing_token,
                    )
                    .where(models.ScheduledJobLeaseEvent.job_id == job_id)
                    .order_by(models.ScheduledJobLeaseEvent.fencing_token)
                )
            )
            assert tokens == [("lease-pg-root", 1), (winner, 2)]
            with pytest.raises(StaleFencingToken, match="worker"):
                heartbeat_job_lease(
                    session,
                    job_id=job_id,
                    lease_id=winner,
                    fencing_token=2,
                    worker_identity_sha256=WORKER_ONE,
                    clock=_clock(boundary + timedelta(seconds=30)),
                )
            heartbeat_job_lease(
                session,
                job_id=job_id,
                lease_id=winner,
                fencing_token=2,
                worker_identity_sha256=winner_worker,
                clock=_clock(boundary + timedelta(seconds=30)),
            )
            persisted_cycle = session.get(models.ScheduledCycleIntent, cycle_id)
            persisted_job = session.get(models.ScheduledJobIntent, job_id)
            root = session.get(models.ScheduledJobLeaseEvent, "lease-pg-root")
            assert persisted_cycle is not None and persisted_job is not None and root is not None
            with pytest.raises(StaleFencingToken, match="not exactly current"):
                append_scheduled_job_attempt(
                    session,
                    _retryable_attempt(
                        cycle=persisted_cycle,
                        job=persisted_job,
                        lease=root,
                    ),
                    clock=_clock(boundary + timedelta(seconds=30)),
                )

        forged_acquired = successor_expiry + timedelta(seconds=1)
        with Session(engine) as session:
            with pytest.raises(IntegrityError, match="exact monotonic lineage"):
                session.execute(
                    insert(models.ScheduledJobLeaseEvent).values(
                        lease_id="lease-pg-forged",
                        job_id=job_id,
                        fencing_token=3,
                        prior_lease_id=winner,
                        worker_identity_sha256=WORKER_ONE,
                        acquired_at=forged_acquired,
                        expires_at=forged_acquired + timedelta(minutes=10),
                        initial_heartbeat_at=forged_acquired,
                    )
                )
                session.flush()
            session.rollback()

        with Session(engine) as session:
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(models.ScheduledJobLeaseEvent)
                    .where(models.ScheduledJobLeaseEvent.job_id == job_id)
                )
                == 2
            )
        assert inspect_database(postgresql_target).kind == "current"
    finally:
        engine.dispose()


def test_postgresql_operational_catalog_drift_fails_strict_status(
    postgresql_target: str,
) -> None:
    engine = _engine(postgresql_target)
    try:
        assert inspect_database(postgresql_target).kind == "current"
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "ALTER TABLE notification_outbox_items "
                "DROP CONSTRAINT fk_outbox_item_intent"
            )
            connection.exec_driver_sql(
                "ALTER TABLE notification_outbox_items "
                "ADD CONSTRAINT fk_outbox_item_intent "
                "FOREIGN KEY (intent_id) REFERENCES notification_intents(intent_id) "
                "NOT DEFERRABLE"
            )
        changed = inspect_database(postgresql_target)
        assert changed.kind == "invalid"
        assert "deferrability" in (changed.detail or "")
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "ALTER TABLE notification_outbox_items "
                "DROP CONSTRAINT fk_outbox_item_intent"
            )
            connection.exec_driver_sql(
                "ALTER TABLE notification_outbox_items "
                "ADD CONSTRAINT fk_outbox_item_intent "
                "FOREIGN KEY (intent_id) REFERENCES notification_intents(intent_id) "
                "DEFERRABLE INITIALLY DEFERRED"
            )
        assert inspect_database(postgresql_target).kind == "current"

        with engine.begin() as connection:
            internal_trigger_name = connection.execute(
                text(
                    """
                    SELECT trigger_catalog.tgname
                    FROM pg_trigger trigger_catalog
                    JOIN pg_constraint constraint_catalog
                      ON constraint_catalog.oid = trigger_catalog.tgconstraint
                    JOIN pg_class trigger_relation
                      ON trigger_relation.oid = trigger_catalog.tgrelid
                    WHERE constraint_catalog.conname = 'fk_outbox_item_intent'
                      AND trigger_relation.relname = 'notification_outbox_items'
                      AND trigger_catalog.tgisinternal
                    ORDER BY trigger_catalog.tgname
                    LIMIT 1
                    """
                )
            ).scalar_one()
            quoted_trigger_name = connection.dialect.identifier_preparer.quote(
                internal_trigger_name
            )
            connection.exec_driver_sql(
                "ALTER TABLE notification_outbox_items DISABLE TRIGGER "
                f"{quoted_trigger_name}"
            )
        changed = inspect_database(postgresql_target)
        assert changed.kind == "invalid"
        assert "foreign-key enforcement trigger" in (changed.detail or "")
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "ALTER TABLE notification_outbox_items ENABLE TRIGGER "
                f"{quoted_trigger_name}"
            )
        assert inspect_database(postgresql_target).kind == "current"

        with engine.begin() as connection:
            connection.exec_driver_sql(
                "ALTER TABLE scheduled_cycles DISABLE TRIGGER "
                "trg_scheduled_cycles_terminal_insert"
            )
        changed = inspect_database(postgresql_target)
        assert changed.kind == "invalid"
        assert "trigger inventory" in (changed.detail or "")
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "ALTER TABLE scheduled_cycles ENABLE TRIGGER "
                "trg_scheduled_cycles_terminal_insert"
            )
        assert inspect_database(postgresql_target).kind == "current"

        with engine.begin() as connection:
            connection.exec_driver_sql(
                "CREATE INDEX injected_operational_drift "
                "ON scheduled_job_intents (lane)"
            )
        changed = inspect_database(postgresql_target)
        assert changed.kind == "invalid"
        assert "index inventory" in (changed.detail or "")
        with engine.begin() as connection:
            connection.exec_driver_sql("DROP INDEX injected_operational_drift")
        assert inspect_database(postgresql_target).kind == "current"
    finally:
        engine.dispose()


def test_postgresql_operational_roles_enforce_real_write_and_read_boundaries(
    postgresql_target: str,
) -> None:
    engine = _engine(postgresql_target)
    try:
        role_sql = render_least_privilege_role_sql(
            migrator_role=ROLES["migrator"],
            ingestion_role=ROLES["ingestion"],
            governance_role=ROLES["governance"],
            artifact_role=ROLES["artifact"],
            audit_role=ROLES["audit"],
        )
        with engine.begin() as connection:
            connection.exec_driver_sql(role_sql)

        acquired = datetime(2026, 7, 15, 1, 0, 0, tzinfo=UTC)
        with Session(engine) as session:
            session.execute(text(f"SET LOCAL ROLE {ROLES['ingestion']}"))
            _, job = _append_discovery_intent(session)
            acquire_job_lease(
                session,
                job_id=job.job_id,
                lease_id="lease-role-ingestion",
                worker_identity_sha256=WORKER_ONE,
                expires_at=datetime(2099, 1, 1, tzinfo=UTC),
                clock=_clock(acquired),
            )
            heartbeat_job_lease(
                session,
                job_id=job.job_id,
                lease_id="lease-role-ingestion",
                fencing_token=1,
                worker_identity_sha256=WORKER_ONE,
                clock=_clock(acquired + timedelta(seconds=30)),
            )
            candidate = _load("discovery-candidate-v1.valid.json")
            identity = _load("identity-decision-v1.valid.json")
            candidate["candidateId"] = identity["candidateReference"]
            candidate["evidenceReferences"][0]["evidenceId"] = identity[
                "observationReference"
            ]
            candidate["manifest"]["contentSha256"] = "0" * 64
            candidate["manifest"]["contentSha256"] = coverage_digest(candidate)
            append_discovery_candidate(session, candidate)
            append_ops_incident(session, _load("ops-incident-v1.valid.json"))
            session.commit()

        with Session(engine) as session:
            session.execute(text(f"SET LOCAL ROLE {ROLES['governance']}"))
            append_benchmark_definition_revision(
                session, _load("benchmark-definition-revision-v1.valid.json")
            )
            append_evaluation_subject_revision(
                session, _load("evaluation-subject-v1.valid.json")
            )
            append_identity_decision(session, _load("identity-decision-v1.valid.json"))
            append_review_work_item(session, _load("review-work-item-v1.valid.json"))
            session.commit()

        _assert_permission_denied(
            engine,
            ROLES["ingestion"],
            "INSERT INTO benchmark_definition_revisions "
            "(benchmark_definition_revision_id) VALUES ('forbidden')",
        )
        _assert_permission_denied(
            engine,
            ROLES["ingestion"],
            "INSERT INTO identity_decisions (decision_id) VALUES ('forbidden')",
        )
        _assert_permission_denied(
            engine,
            ROLES["ingestion"],
            "INSERT INTO review_work_items (work_item_id) VALUES ('forbidden')",
        )
        _assert_permission_denied(
            engine,
            ROLES["ingestion"],
            "UPDATE scheduled_job_intents SET lane = 'forbidden'",
        )
        with engine.connect() as connection:
            transaction = connection.begin()
            connection.exec_driver_sql(f"SET LOCAL ROLE {ROLES['ingestion']}")
            with pytest.raises(DBAPIError, match="append-only"):
                connection.exec_driver_sql(
                    "UPDATE scheduled_job_intents SET job_id = job_id"
                )
            transaction.rollback()

        for statement in (
            "INSERT INTO scheduled_job_intents (job_id) VALUES ('forbidden')",
            "INSERT INTO source_check_receipts (receipt_id) VALUES ('forbidden')",
            "INSERT INTO notification_outbox_items (incident_event_id, intent_id) "
            "VALUES ('forbidden', 'forbidden')",
            "INSERT INTO result_claims (id) VALUES ('forbidden')",
            "INSERT INTO source_revision_decisions (id) VALUES ('forbidden')",
            "INSERT INTO claim_publication_decisions (id) VALUES ('forbidden')",
        ):
            _assert_permission_denied(engine, ROLES["governance"], statement)

        _assert_permission_denied(
            engine, ROLES["artifact"], "SELECT COUNT(*) FROM ops_incidents"
        )
        with engine.begin() as connection:
            connection.exec_driver_sql(f"SET LOCAL ROLE {ROLES['audit']}")
            assert connection.exec_driver_sql(
                "SELECT COUNT(*) FROM ops_incidents"
            ).scalar_one() == 1
        _assert_permission_denied(
            engine,
            ROLES["audit"],
            "INSERT INTO ops_incidents (incident_id) VALUES ('forbidden')",
        )
        assert inspect_database(postgresql_target).kind == "current"
    finally:
        engine.dispose()
