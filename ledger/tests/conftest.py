from __future__ import annotations

from pathlib import Path

import pytest

from app.config import get_settings
from app.db.engine import get_session, init_db
from app.registry.seed_loader import seed_registry


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
def seeded_db(tmp_db):
    """Seed registry and close session so tests can open their own."""
    reg = Path(__file__).resolve().parents[1] / "app" / "registry"
    with get_session() as session:
        seed_registry(
            session,
            benchmarks_path=reg / "benchmarks.yaml",
            models_path=reg / "models.yaml",
            sources_path=reg / "official_sources.yaml",
        )
    yield tmp_db
