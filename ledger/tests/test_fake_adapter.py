from pathlib import Path

import pytest

from app.db.models import SourceSnapshot
from app.ingestion.adapters.fake import FakeSourceAdapter
from app.schemas.boundary import OfficialSource

FIXTURE = Path(__file__).parent / "fixtures" / "fake_source.json"


def test_fake_extract_preserves_raw():
    adapter = FakeSourceAdapter(fixture_path=FIXTURE)
    source = OfficialSource(
        id="fake",
        source_name="fake",
        source_url="file://x",
        source_type="fake",
        officialness_level="O5",
        benchmark_id="hf_official_benchmarks",
        parser_config={"mode": "test_fixture_only"},
    )
    fetch = adapter.fetch(source)
    snap = SourceSnapshot(
        id="11111111-1111-1111-1111-111111111111",
        official_source_id="fake",
        raw_content_uri="mem",
        content_hash="x",
    )
    claims = adapter.extract_claims(source, snap, fetch.raw_bytes)
    assert len(claims) == 2
    assert claims[0].score_raw == "42.50"
    assert claims[0].model_raw == "Fake-Model-1"
    vals = adapter.validate_claim(claims[0], fetch.raw_bytes)
    assert vals[0].outcome == "pass"


def test_fake_adapter_rejects_unscoped_or_retired_sources():
    adapter = FakeSourceAdapter(fixture_path=FIXTURE)
    for mode in ({}, {"mode": "retired"}):
        source = OfficialSource(
            id="fake",
            source_name="fake",
            source_url="file://x",
            source_type="fake",
            officialness_level="O5",
            benchmark_id="hf_official_benchmarks",
            parser_config=mode,
        )
        snap = SourceSnapshot(
            id="11111111-1111-1111-1111-111111111111",
            official_source_id="fake",
            raw_content_uri="mem",
            content_hash="x",
        )

        with pytest.raises(RuntimeError, match="test-fixture only"):
            adapter.fetch(source)
        assert adapter.extract_claims(source, snap, FIXTURE.read_bytes()) == []
