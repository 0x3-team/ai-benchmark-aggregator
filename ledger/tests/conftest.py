from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.db import models, repositories as repo
from app.db.engine import get_session, init_db
from app.ingestion.admission import AdmissionVerdict, ClaimAdmission, SourceAdmission
from app.registry.seed_loader import seed_registry


@pytest.fixture()
def allow_quarantined_fixture_ingestion(seeded_db, monkeypatch: pytest.MonkeyPatch):
    """Opt legacy fake-fixture tests into a narrowly scoped runner bypass.

    The canonical fake registry route is retired and remains forbidden in
    production. These historical persistence tests exercise
    snapshot/idempotency mechanics, not source certification or exact-evidence
    admission, so they append a temporary active *test-fixture-only* successor
    in their disposable database and replace all three LDR-05 admission
    stages. The provenance trigger remains exercised; real LDR-05 tests never
    use this fixture and production cannot invoke this path.
    """

    with get_session() as session:
        repo.reconcile_official_source(
            session,
            {
                "id": "fake_local_fixture",
                "benchmark_id": "hf_official_benchmarks",
                "source_name": "Temporary pytest fake fixture source",
                "source_url": "file://fake",
                "source_type": "fake",
                "officialness_level": "O5",
                "machine_readable": True,
                "requires_auth": False,
                "supports_history": False,
                "update_cadence": "manual",
                "parser_name": "fake",
                "parser_config": {"mode": "test_fixture_only"},
                "status": "active",
                "notes": "Temporary pytest fixture bypass; never a production source.",
            },
        )

    def fixture_source_admission(session, *, source, source_revision):  # type: ignore[no-untyped-def]
        decisions = list(
            session.scalars(
                select(models.SourceRevisionDecision).where(
                    models.SourceRevisionDecision.source_revision_id == source_revision.id
                )
            )
        )
        superseded = {
            decision.supersedes_decision_id
            for decision in decisions
            if decision.supersedes_decision_id is not None
        }
        leaves = [decision for decision in decisions if decision.id not in superseded]
        assert len(leaves) == 1, "fixture source must have one effective decision"
        decision = leaves[0]
        if decision.outcome != "certified":
            # The runner's three resolver stages remain monkeypatched below;
            # this synthetic successor exists only to satisfy the migration
            # guard for persistence mechanics in a disposable test database.
            decision = models.SourceRevisionDecision(
                source_revision_id=source_revision.id,
                outcome="certified",
                policy_version="test-fixture-admission-v1",
                reason_code="test_fixture_admission_bypass",
                basis_json={"test_fixture": True},
                actor="pytest",
                supersedes_decision_id=decision.id,
            )
            session.add(decision)
            session.flush()
        return SourceAdmission(
            AdmissionVerdict("admit", "TEST_FIXTURE_ADMISSION_BYPASS"),
            source_revision_id=source_revision.id,
            source_revision_decision_id=decision.id,
        )

    def fixture_claim_admission(*, claim, **_kwargs):  # type: ignore[no-untyped-def]
        return ClaimAdmission(
            AdmissionVerdict("admit", "TEST_FIXTURE_ADMISSION_BYPASS"),
            score_numeric=claim.score_numeric,
            score_unit=claim.score_unit,
        )

    monkeypatch.setattr("app.ingestion.runner.can_ingest_source", lambda source: source.source_type == "fake")
    monkeypatch.setattr("app.ingestion.runner.resolve_source_admission", fixture_source_admission)
    monkeypatch.setattr(
        "app.ingestion.runner.resolve_fetch_admission",
        lambda **_kwargs: AdmissionVerdict("admit", "TEST_FIXTURE_ADMISSION_BYPASS"),
    )
    monkeypatch.setattr("app.ingestion.runner.resolve_claim_admission", fixture_claim_admission)


@pytest.fixture()
def tmp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db_path = tmp_path / "test.db"
    snap = tmp_path / "snapshots"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("SNAPSHOT_LOCAL_ROOT", str(snap))
    get_settings.cache_clear()
    import app.db.engine as eng

    eng._engine = None
    eng._SessionLocal = None
    # timeout helps avoid intermittent locks
    eng.get_engine()
    if eng._engine is not None:
        eng._engine = eng.create_engine if False else eng._engine  # keep
    init_db()
    # recreate engine with timeout
    eng._engine = None
    eng._SessionLocal = None
    from sqlalchemy import create_engine, event
    from sqlalchemy.orm import sessionmaker
    from app.db.models import Base

    url = f"sqlite:///{db_path}"
    engine = create_engine(url, future=True, connect_args={"check_same_thread": False, "timeout": 30})

    @event.listens_for(engine, "connect")
    def _fk(dbapi_connection, connection_record):  # type: ignore[no-untyped-def]
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    eng._engine = engine
    eng._SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    Base.metadata.create_all(bind=engine)
    yield str(db_path)
    get_settings.cache_clear()
    eng._engine = None
    eng._SessionLocal = None


@pytest.fixture()
def seeded_db(tmp_db, tmp_path: Path):
    """Seed registry and close session so tests can open their own.

    The real ``app/registry`` tree carries cross-file model-ID collisions between
    ``models.yaml``, ``models_frontier.yaml`` and ``models_hf_seed.yaml`` that the
    loader now rejects before any durable write. The seeded test database does not
    need those frontier/HF-seed model rows (assertions fabricate their own
    entities), so we seed a collision-free, disposable model manifest in a temp
    directory and keep the real curated benchmarks + official sources.
    """
    reg = Path(__file__).resolve().parents[1] / "app" / "registry"
    # Seed only the base model manifest. The loader expands the ``models*.yaml``
    # glob to the real tree, which would bring in cross-file duplicate IDs
    # (models_frontier.yaml / models_hf_seed.yaml) that now fail closed. A
    # collision-free copy of the base file supplies the entities tests need
    # (e.g. the ``fake_model_1`` review-queue helper) while staying monolithic.
    models_path = tmp_path / "models.yaml"
    models_path.write_text((reg / "models.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    with get_session() as session:
        seed_registry(
            session,
            benchmarks_path=reg / "benchmarks.yaml",
            models_path=models_path,
            sources_path=reg / "official_sources.yaml",
        )
    yield tmp_db
