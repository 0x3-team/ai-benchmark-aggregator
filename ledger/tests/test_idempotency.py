from pathlib import Path

from sqlalchemy import func, select

from app.db.engine import get_session
from app.db import repositories as repo
from app.db import models
from app.ingestion.runner import run_ingestion


FIXTURE = Path(__file__).parent / "fixtures" / "fake_source.json"


def test_duplicate_ingest_no_new_claims(seeded_db, allow_quarantined_fixture_ingestion):
    with get_session() as session:
        s1 = run_ingestion(session, source_id="fake_local_fixture", fixture_path=FIXTURE)
        assert s1.claims_inserted >= 1
        s2 = run_ingestion(session, source_id="fake_local_fixture", fixture_path=FIXTURE)
        assert s2.snapshots_reused >= 1
        assert s2.claims_inserted == 0
        assert s2.claims_unchanged >= 1


def test_claim_fingerprint_unique_constraint(seeded_db, allow_quarantined_fixture_ingestion):
    with get_session() as session:
        run_ingestion(session, source_id="fake_local_fixture", fixture_path=FIXTURE)
        claims = repo.list_claims(session, limit=100)
        fps = [c.claim_fingerprint for c in claims]
        assert len(fps) == len(set(fps))


def test_reingestion_verifies_existing_snapshot_bytes_before_reuse(
    seeded_db, allow_quarantined_fixture_ingestion
):
    with get_session() as session:
        run_ingestion(session, source_id="fake_local_fixture", fixture_path=FIXTURE)
        snapshot = session.scalar(
            select(models.SourceSnapshot).where(
                models.SourceSnapshot.official_source_id == "fake_local_fixture"
            )
        )
        assert snapshot is not None
        snapshot_uri = snapshot.raw_content_uri
        snapshot_hash = snapshot.content_hash
        snapshot_count = session.scalar(select(func.count()).select_from(models.SourceSnapshot))
        claim_count = session.scalar(select(func.count()).select_from(models.ResultClaim))
        Path(snapshot_uri).write_bytes(b"tampered on disk")

        summary = run_ingestion(
            session, source_id="fake_local_fixture", fixture_path=FIXTURE, fail_fast=False
        )

        assert summary.snapshots_reused == 0
        assert any("not expected digest" in error for error in summary.errors)
        assert session.scalar(select(func.count()).select_from(models.SourceSnapshot)) == snapshot_count
        assert session.scalar(select(func.count()).select_from(models.ResultClaim)) == claim_count
        unchanged = session.scalar(select(models.SourceSnapshot).where(models.SourceSnapshot.id == snapshot.id))
        assert unchanged is not None
        assert unchanged.raw_content_uri == snapshot_uri
        assert unchanged.content_hash == snapshot_hash
        assert Path(snapshot_uri).read_bytes() == b"tampered on disk"
