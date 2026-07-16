from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.db import models
from app.db.engine import get_session
from app.ingestion.runner import IngestionBlockedError, run_ingestion


FIXTURE = Path(__file__).parent / "fixtures" / "fake_source.json"


def _count(session, model) -> int:
    return session.scalar(select(func.count()).select_from(model)) or 0


def test_quarantined_source_is_rejected_before_any_ledger_write(seeded_db):
    with get_session() as session:
        before = {
            "runs": _count(session, models.IngestionRun),
            "snapshots": _count(session, models.SourceSnapshot),
            "claims": _count(session, models.ResultClaim),
        }
        with pytest.raises(IngestionBlockedError, match="No production-eligible source"):
            run_ingestion(session, source_id="fake_local_fixture", fixture_path=FIXTURE)
        after = {
            "runs": _count(session, models.IngestionRun),
            "snapshots": _count(session, models.SourceSnapshot),
            "claims": _count(session, models.ResultClaim),
        }
    assert after == before


def test_default_all_sources_is_blocked_before_fetch_or_write(seeded_db):
    with get_session() as session:
        with pytest.raises(IngestionBlockedError, match="all active sources"):
            run_ingestion(session)
        assert _count(session, models.IngestionRun) == 0
        assert _count(session, models.SourceSnapshot) == 0
        assert _count(session, models.ResultClaim) == 0
