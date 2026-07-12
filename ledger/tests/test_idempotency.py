from pathlib import Path

from app.db.engine import get_session
from app.db import repositories as repo
from app.ingestion.runner import run_ingestion


FIXTURE = Path(__file__).parent / "fixtures" / "fake_source.json"


def test_duplicate_ingest_no_new_claims(seeded_db):
    with get_session() as session:
        s1 = run_ingestion(session, source_id="fake_local_fixture", fixture_path=FIXTURE)
        assert s1.claims_inserted >= 1
        s2 = run_ingestion(session, source_id="fake_local_fixture", fixture_path=FIXTURE)
        assert s2.snapshots_reused >= 1
        assert s2.claims_inserted == 0
        assert s2.claims_unchanged >= 1


def test_claim_fingerprint_unique_constraint(seeded_db):
    with get_session() as session:
        run_ingestion(session, source_id="fake_local_fixture", fixture_path=FIXTURE)
        claims = repo.list_claims(session, limit=100)
        fps = [c.claim_fingerprint for c in claims]
        assert len(fps) == len(set(fps))
