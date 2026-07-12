from pathlib import Path

from app.db.engine import get_session
from app.db import models, repositories as repo
from app.ingestion.runner import run_ingestion
from sqlalchemy import select

FIXTURE = Path(__file__).parent / "fixtures" / "fake_source.json"


def test_claims_have_required_evidence_fields(seeded_db):
    with get_session() as session:
        run_ingestion(session, source_id="fake_local_fixture", fixture_path=FIXTURE)
        claims = repo.list_claims(session, limit=100)
        assert claims
        for c in claims:
            assert c.official_source_id
            assert c.source_snapshot_id
            assert c.model_raw
            assert c.benchmark_raw
            assert c.score_raw
            assert c.evidence_location
            assert c.capture_method
            assert c.claim_fingerprint
            vals = session.scalars(
                select(models.ClaimValidation).where(models.ClaimValidation.result_claim_id == c.id)
            ).all()
            assert vals, "validation record required"
