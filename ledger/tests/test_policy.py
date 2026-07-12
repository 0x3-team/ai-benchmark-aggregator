from app.ingestion.policy import can_ingest_source
from app.schemas.boundary import OfficialSource


def test_policy_rejects_o0():
    s = OfficialSource(
        id="x",
        source_name="blog",
        source_url="https://example.com",
        source_type="html_table",
        officialness_level="O0",
        status="active",
    )
    assert can_ingest_source(s) is False


def test_policy_accepts_o5():
    s = OfficialSource(
        id="x",
        source_name="api",
        source_url="https://example.com",
        source_type="hf_benchmark_api",
        officialness_level="O5",
        status="active",
    )
    assert can_ingest_source(s) is True
