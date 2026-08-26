"""F16A: SQLite 0012 ingestion-run finalization-once hardening.

The ingestion runner inserts a ``running`` row (``finished_at`` null) and
finalizes it exactly once into a terminal status.  0011 installed that guard on
PostgreSQL only.  This suite proves the forward-only SQLite 0012 revision
applies the same rule by upgrading a disposable database to 0011,
inserting a running run, upgrading to 0012, permitting exactly one
running/null -> terminal/non-null finalization, and rejecting every later
mutation (second finalization, identity rewrite, missing finished_at, invalid
terminal status, pre-finalization counter update).
"""

from __future__ import annotations

import hashlib
from pathlib import Path
import sqlite3

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.backup.errors import RecoveryIntegrityError
from app.backup import sqlite_driver
from app.backup.sqlite_driver import SQLiteBackupRestoreDriver
from app.db import models, repositories as repo


def _url(path: Path) -> str:
    return f"sqlite:///{path}"


def _session(path: Path) -> Session:
    return Session(create_engine(_url(path)))


def _alembic_config(database_url: str) -> Config:
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url)
    config.attributes["database_url"] = database_url
    return config


def _upgrade(path: Path, revision: str) -> None:
    command.upgrade(_alembic_config(_url(path)), revision)


def _make_disposable_0011(path: Path) -> None:
    """Migrate a fresh SQLite database to 0011 (the pre-0012 head)."""
    _upgrade(path, "0011_ingestion_run_hardening")


def _upgrade_head(path: Path) -> None:
    """Migrate a fresh SQLite database to the current chain head."""
    _upgrade(path, "head")


def _insert_running_run(engine, *, run_id: str = "run-running") -> None:
    with engine.begin() as connection:
        connection.exec_driver_sql(
            """
            INSERT INTO ingestion_runs (
                id, run_type, status, sources_checked, claims_inserted
            ) VALUES (?, 'source', 'running', 0, 0)
            """,
            (run_id,),
        )


def test_sqlite_0012_finalizes_a_running_run_once_and_rejects_repeat_mutation(
    tmp_path: Path,
):
    path = tmp_path / "history.db"
    _make_disposable_0011(path)
    engine = create_engine(_url(path))
    _insert_running_run(engine, run_id="run-first")

    _upgrade(path, "0012_sqlite_ingestion_run_hardening")

    # Exactly one running/null -> completed/non-null finalization is allowed.
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "UPDATE ingestion_runs SET status = 'completed', finished_at = '2026-08-12 10:00:00', "
            "claims_inserted = 3 WHERE id = 'run-first'"
        )

    # A second finalization/status/counter update on the now-terminal row is
    # rejected with the stable identity/history error.
    with engine.begin() as connection:
        with pytest.raises(IntegrityError, match="identity/history is immutable"):
            connection.exec_driver_sql(
                "UPDATE ingestion_runs SET status = 'failed', claims_inserted = 4 WHERE id = 'run-first'"
            )

    # The first finalization survives intact.
    with engine.connect() as connection:
        row = connection.exec_driver_sql(
            "SELECT id, status, finished_at, claims_inserted FROM ingestion_runs WHERE id = 'run-first'"
        ).one()
    assert row == ("run-first", "completed", "2026-08-12 10:00:00", 3)


def test_sqlite_0012_rejects_pre_finalization_counter_update(tmp_path: Path):
    """A running row must reach its terminal finalization before any counters may move."""
    path = tmp_path / "history.db"
    _make_disposable_0011(path)
    engine = create_engine(_url(path))
    _insert_running_run(engine, run_id="run-precount")

    _upgrade(path, "0012_sqlite_ingestion_run_hardening")

    with engine.begin() as connection:
        with pytest.raises(IntegrityError, match="identity/history is immutable"):
            connection.exec_driver_sql(
                "UPDATE ingestion_runs SET claims_inserted = 1 WHERE id = 'run-precount'"
            )

    with engine.connect() as connection:
        row = connection.exec_driver_sql(
            "SELECT status, finished_at, claims_inserted FROM ingestion_runs WHERE id = 'run-precount'"
        ).one()
    assert row == ("running", None, 0)


@pytest.mark.parametrize(
    "column,new_value",
    [
        ("id", "'run-rewritten'"),
        ("started_at", "'2025-01-01 00:00:00'"),
        ("run_type", "'manual'"),
        ("official_source_id", "'other-source'"),
    ],
)
def test_sqlite_0012_rejects_identity_rewrite(tmp_path: Path, column: str, new_value: str):
    path = tmp_path / "history.db"
    _make_disposable_0011(path)
    engine = create_engine(_url(path))
    _insert_running_run(engine, run_id="run-identity")

    _upgrade(path, "0012_sqlite_ingestion_run_hardening")

    with engine.begin() as connection:
        with pytest.raises(IntegrityError, match="identity/history is immutable"):
            connection.exec_driver_sql(
                f"UPDATE ingestion_runs SET status = 'completed', finished_at = '2026-08-12 12:00:00', "
                f"{column} = {new_value} WHERE id = 'run-identity'"
            )

    # The rejected rewrite is in its own transaction; the running row is untouched.
    with engine.connect() as connection:
        row = connection.exec_driver_sql(
            "SELECT id, status, finished_at, run_type FROM ingestion_runs WHERE id = 'run-identity'"
        ).one()
    assert row == ("run-identity", "running", None, "source")


def test_sqlite_0012_rejects_missing_finished_at_on_finalize(tmp_path: Path):
    path = tmp_path / "history.db"
    _make_disposable_0011(path)
    engine = create_engine(_url(path))
    _insert_running_run(engine, run_id="run-nofinish")

    _upgrade(path, "0012_sqlite_ingestion_run_hardening")

    with engine.begin() as connection:
        with pytest.raises(IntegrityError, match="identity/history is immutable"):
            connection.exec_driver_sql(
                "UPDATE ingestion_runs SET status = 'completed' WHERE id = 'run-nofinish'"
            )


def test_sqlite_0012_rejects_invalid_terminal_status(tmp_path: Path):
    path = tmp_path / "history.db"
    _make_disposable_0011(path)
    engine = create_engine(_url(path))
    _insert_running_run(engine, run_id="run-badstatus")

    _upgrade(path, "0012_sqlite_ingestion_run_hardening")

    for invalid_status in ("running", "paused", "canceled"):
        with engine.begin() as connection:
            with pytest.raises(IntegrityError, match="identity/history is immutable"):
                connection.exec_driver_sql(
                    "UPDATE ingestion_runs SET status = ?, finished_at = '2026-08-12 13:00:00' "
                    "WHERE id = 'run-badstatus'",
                    (invalid_status,),
                )

    # Each rejected write was its own transaction; the row is still running/null.
    with engine.connect() as connection:
        row = connection.exec_driver_sql(
            "SELECT status, finished_at FROM ingestion_runs WHERE id = 'run-badstatus'"
        ).one()
    assert row == ("running", None)


def test_sqlite_0012_fresh_trigger_present_and_enforcing(tmp_path: Path):
    path = tmp_path / "history.db"
    _make_disposable_0011(path)
    engine = create_engine(_url(path))
    _insert_running_run(engine, run_id="run-trigger")

    # 0011 keeps SQLite unchanged, so no guard exists before 0012.
    with engine.connect() as connection:
        before = connection.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type = 'trigger' AND name = "
            "'trg_ingestion_runs_finalize_once'"
        ).fetchone()
    assert before is None

    _upgrade(path, "0012_sqlite_ingestion_run_hardening")

    # The 0012 trigger exists and redirects a terminal rewrite.
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "UPDATE ingestion_runs SET status = 'partial', finished_at = '2026-08-12 14:00:00' "
            "WHERE id = 'run-trigger'"
        )
        with pytest.raises(IntegrityError, match="identity/history is immutable"):
            connection.exec_driver_sql(
                "UPDATE ingestion_runs SET status = 'failed', run_type = 'manual', "
                "finished_at = '2026-08-12 14:05:00' WHERE id = 'run-trigger'"
            )


def test_sqlite_fresh_empty_upgrade_to_head_installs_finalize_once_trigger(
    tmp_path: Path,
):
    """A brand-new database upgraded to head gets the 0012 SQLite guard."""
    path = tmp_path / "fresh.db"
    _upgrade_head(path)
    engine = create_engine(_url(path))
    _insert_running_run(engine, run_id="run-fresh")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "UPDATE ingestion_runs SET status = 'completed', finished_at = '2026-08-12 16:00:00' "
            "WHERE id = 'run-fresh'"
        )
        with pytest.raises(IntegrityError, match="identity/history is immutable"):
            connection.exec_driver_sql(
                "UPDATE ingestion_runs SET status = 'failed' WHERE id = 'run-fresh'"
            )


def test_sqlite_0011_baseline_is_vulnerable_but_0012_closes_them(tmp_path: Path):
    """A direct counter/metadata mutation succeeds on 0011 and fails on 0012.

    This proves the regression guard actually closes a hole: the same
    ``claims_inserted`` mutation on a running row succeeds before 0012 (running
    rows are mutable on 0011 SQLite) and is rejected after 0012.
    """
    path = tmp_path / "history.db"
    _make_disposable_0011(path)
    engine = create_engine(_url(path))
    _insert_running_run(engine, run_id="run-baseline")

    # On 0011, SQLite has no guard: a running row's counter can move directly.
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "UPDATE ingestion_runs SET claims_inserted = 1 WHERE id = 'run-baseline'"
        )
    with engine.connect() as connection:
        assert connection.exec_driver_sql(
            "SELECT claims_inserted FROM ingestion_runs WHERE id = 'run-baseline'"
        ).scalar_one() == 1

    # Upgrade to 0012; the same-class mutation is now rejected.
    _upgrade(path, "0012_sqlite_ingestion_run_hardening")
    with engine.begin() as connection:
        with pytest.raises(IntegrityError, match="identity/history is immutable"):
            connection.exec_driver_sql(
                "UPDATE ingestion_runs SET claims_inserted = 2 WHERE id = 'run-baseline'"
            )


def test_sqlite_0012_allows_partial_and_failed_terminal_statuses(tmp_path: Path):
    for terminal in ("partial", "failed"):
        path = tmp_path / f"history-{terminal}.db"
        _make_disposable_0011(path)
        engine = create_engine(_url(path))
        run_id = f"run-{terminal}"
        _insert_running_run(engine, run_id=run_id)

        _upgrade(path, "0012_sqlite_ingestion_run_hardening")

        with engine.begin() as connection:
            connection.exec_driver_sql(
                "UPDATE ingestion_runs SET status = ?, finished_at = '2026-08-12 15:00:00' "
                "WHERE id = ?",
                (terminal, run_id),
            )
        with engine.connect() as connection:
            row = connection.exec_driver_sql(
                "SELECT id, status, finished_at FROM ingestion_runs WHERE id = ?",
                (run_id,),
            ).one()
        assert row == (run_id, terminal, "2026-08-12 15:00:00")


# --- F16B: repository finish_ingestion_run guard ---------------------------------


def test_repo_finish_valid_finalization_persists_counters_and_metadata(tmp_path: Path):
    path = tmp_path / "repo.db"
    _upgrade_head(path)
    with _session(path) as session:
        run = repo.create_ingestion_run(session, run_type="source")
        run_id = run.id
        # F16B: the repository enforces finalize-once with a stable ValueError,
        # independent of the DDL-only 0012 SQLite trigger.
        repo.finish_ingestion_run(
            session,
            run,
            status="completed",
            error_message=None,
            counters={
                "sources_checked": 1,
                "snapshots_created": 2,
                "snapshots_reused": 3,
                "claims_extracted": 4,
                "claims_inserted": 5,
                "claims_unchanged": 6,
                "claims_needing_review": 7,
            },
            metadata={"source_outcomes": []},
        )
        session.commit()
        assert run.status == "completed"
        assert run.finished_at is not None
        assert run.sources_checked == 1
        assert run.claims_inserted == 5
        assert run.metadata_json == {"source_outcomes": []}

    # Persisted state matches the session state.
    with _session(path) as session:
        row = session.get(models.IngestionRun, run_id)
        assert row is not None
        assert row.status == "completed"
        assert (row.sources_checked, row.snapshots_created, row.claims_inserted) == (1, 2, 5)
        assert row.metadata_json == {"source_outcomes": []}


def test_repo_repeated_finalization_rejected_keeps_first_terminal_history(tmp_path):
    path = tmp_path / "repo.db"
    _upgrade_head(path)
    with _session(path) as session:
        run = repo.create_ingestion_run(session, run_type="source")
        run_id = run.id
        repo.finish_ingestion_run(
            session, run, status="completed", counters={"claims_inserted": 5}
        )
        session.commit()
        with pytest.raises(ValueError, match="identity/history is immutable"):
            repo.finish_ingestion_run(
                session, run, status="failed", counters={"claims_inserted": 99}
            )
        # The first terminal history is unchanged after the rejected repeat.
        session.expire_all()
        row = session.get(models.IngestionRun, run_id)
        assert row.status == "completed"
        assert row.claims_inserted == 5
        assert row.finished_at is not None


def test_repo_invalid_status_rejected_before_row_mutation(tmp_path):
    path = tmp_path / "repo.db"
    _upgrade_head(path)
    with _session(path) as session:
        run = repo.create_ingestion_run(session, run_type="source")
        run_id = run.id
        session.commit()  # persist the running row before testing a rejection
    with _session(path) as session:
        run = session.get(models.IngestionRun, run_id)
        assert run.status == "running"
        with pytest.raises(ValueError, match="terminal status"):
            repo.finish_ingestion_run(session, run, status="paused")
        session.rollback()
    with _session(path) as session:
        row = session.get(models.IngestionRun, run_id)
        assert row.status == "running"
        assert row.finished_at is None


@pytest.mark.parametrize("counter", ["unknown_counter", "sources_checked_x", "metadata"])
def test_finish_unknown_counter_rejected_before_row_mutation(tmp_path, counter):
    path = tmp_path / "repo.db"
    _upgrade_head(path)
    with _session(path) as session:
        run = repo.create_ingestion_run(session, run_type="source")
        run_id = run.id
        session.commit()  # persist the running row before testing a rejection
    with _session(path) as session:
        run = session.get(models.IngestionRun, run_id)
        with pytest.raises(ValueError, match="unknown ingestion run counter"):
            repo.finish_ingestion_run(
                session, run, status="completed", counters={counter: 1}
            )
        session.rollback()
    with _session(path) as session:
        row = session.get(models.IngestionRun, run_id)
        assert row.status == "running"
        assert row.finished_at is None


@pytest.mark.parametrize("bad_value", [True, 1.5, "3", -1])
def test_finish_rejects_bool_float_string_and_negative_before_row_mutation(
    tmp_path, bad_value
):
    path = tmp_path / "repo.db"
    _upgrade_head(path)
    with _session(path) as session:
        run = repo.create_ingestion_run(session, run_type="source")
        run_id = run.id
        session.commit()  # persist the running row before testing a rejection
    with _session(path) as session:
        run = session.get(models.IngestionRun, run_id)
        with pytest.raises(ValueError, match="non-negative integer"):
            repo.finish_ingestion_run(
                session, run, status="completed", counters={"claims_inserted": bad_value}
            )
        session.rollback()
    with _session(path) as session:
        row = session.get(models.IngestionRun, run_id)
        assert row.status == "running"
        assert row.finished_at is None


def test_finish_accepts_empty_counters(tmp_path):
    path = tmp_path / "repo.db"
    _upgrade_head(path)
    with _session(path) as session:
        run = repo.create_ingestion_run(session, run_type="source")
        repo.finish_ingestion_run(
            session, run, status="failed", counters={}, metadata={"errors": ["x"]}
        )
        session.commit()
        assert run.status == "failed"
        assert run.sources_checked == 0
    with _session(path) as session:
        row = session.get(models.IngestionRun, run.id)
        assert row.status == "failed"
        assert row.finished_at is not None


# --- F16C2: real-path SQLite backup artifact inspection -----------------------


def _file_sha256(path: Path) -> str:
    """Return the exact SHA-256 of the on-disk source database file."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def test_sqlite_head_artifact_inspects_with_unchanged_durable_source(tmp_path: Path):
    """Upgrade a fresh DB to head, back it up for real, and inspect the artifact.

    The typed artifact retains its identity and the durable source still carries
    exactly the reviewed 0012 schema (revision, schema SHA, finalize-once trigger).
    No mocks on the backup/inspection path.
    """
    path = tmp_path / "source.db"
    _upgrade_head(path)

    # Snapshot the durable source before backup/inspection so immutability can
    # be proven against a before value rather than asserted tautologically.
    source_sha = _file_sha256(path)

    driver = SQLiteBackupRestoreDriver()
    artifact = driver.create_backup(path)

    # The typed artifact identity survives intact after inspect. The reviewed
    # head schema has exactly two allowed raw-SQL hashes (Alembic 1.18.5 batch
    # reflection order of the two semantically identical FKs on
    # official_source_revisions), so either is accepted.
    result = driver.inspect_artifact(artifact)
    assert result.schema_revision == "0012_sqlite_ingestion_run_hardening"
    assert (
        result.schema_sha256
        in sqlite_driver._HEAD_SCHEMA_SHA256_ALLOWLIST
    )
    assert result.artifact is artifact
    assert result.artifact.raw_bytes == artifact.raw_bytes
    assert result.artifact.source_database_identity_sha256 == artifact.source_database_identity_sha256

    # The durable source is unchanged by inspection and still at head with its
    # required finalize-once trigger.
    assert _file_sha256(path) == source_sha
    with sqlite3.connect(path) as connection:
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchall()
        trigger = connection.execute(
            "SELECT name FROM sqlite_schema WHERE type='trigger' AND "
            "name='trg_ingestion_runs_finalize_once'"
        ).fetchone()
    assert revision == [("0012_sqlite_ingestion_run_hardening",)]
    assert trigger is not None


def test_sqlite_artifact_with_dropped_trigger_fails_inspection_without_mutating_source(
    tmp_path: Path,
):
    """Inspection rejects a backup whose durable source lost the finalize trigger.

    Validation must raise the stable RecoveryIntegrityError without ever
    mutating (or repairing) the on-disk source file, revision, or trigger set.
    """
    path = tmp_path / "source.db"
    _upgrade_head(path)

    # Deliberately drop the required trigger and commit it to the source file.
    with sqlite3.connect(path) as connection:
        connection.execute("DROP TRIGGER trg_ingestion_runs_finalize_once")
        connection.commit()
    mutated_sha = _file_sha256(path)

    driver = SQLiteBackupRestoreDriver()
    artifact = driver.create_backup(path)
    with pytest.raises(RecoveryIntegrityError, match="missing required integrity triggers"):
        driver.inspect_artifact(artifact)

    # Inspection never repaired or mutated the durable source.
    assert _file_sha256(path) == mutated_sha
    with sqlite3.connect(path) as connection:
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchall()
        trigger = connection.execute(
            "SELECT name FROM sqlite_schema WHERE type='trigger' AND "
            "name='trg_ingestion_runs_finalize_once'"
        ).fetchone()
    assert revision == [("0012_sqlite_ingestion_run_hardening",)]
    assert trigger is None


def test_production_schema_allowlist_is_exactly_the_two_reviewed_hashes():
    """The production allowlist is locked to exactly the two reviewed hashes.

    This is the security-policy lock: both raw-SQL variants of the measured
    head schema are the only accepted fingerprints. If the allowlist is ever
    broadened beyond those two (or one is dropped), this test fails and the
    reviewed-hash set must be re-audited before it can change.
    """
    _REVIEWED_HEAD_SCHEMA_HASHES = frozenset(
        {
            "db670c153790c9805f6af46c7f462b2ddd13a49f5a4d7e3294637c646aa068e4",
            "4602bd3a302274e46180d93839f6cafeaa7863e7b2523c2a76fd4ac7b195e7c9",
        }
    )
    assert (
        sqlite_driver._HEAD_SCHEMA_SHA256_ALLOWLIST
        == _REVIEWED_HEAD_SCHEMA_HASHES
    )