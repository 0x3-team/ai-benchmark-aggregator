from pathlib import Path

from app.db.engine import get_session
from app.db import repositories as repo
from app.ingestion.runner import run_ingestion

FIXTURE = Path(__file__).parent / "fixtures" / "fake_source.json"


def test_review_queue_and_map_model(seeded_db):
    with get_session() as session:
        run_ingestion(session, source_id="fake_local_fixture", fixture_path=FIXTURE)
        queue = repo.list_review_queue(session)
        # Unknown-Model-X should be unmatched
        unmatched = [c for c in queue if c.model_raw == "Unknown-Model-X"]
        assert unmatched
        claim = unmatched[0]
        original_raw = claim.model_raw
        mapped = repo.map_claim_model(session, claim.id, "fake_model_1")
        assert mapped is not None
        assert mapped.model_raw == original_raw
        assert mapped.model_entity_id == "fake_model_1"
        verified = repo.mark_human_verified(session, claim.id)
        assert verified is not None
        assert verified.capture_status == "human_verified"
