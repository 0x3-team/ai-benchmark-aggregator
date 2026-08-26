from __future__ import annotations

import base64
import csv
from io import StringIO
import hashlib
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import event, func, select
from typer.testing import CliRunner

from app.cli import app
from app.db import repositories as repo
from app.db import models
from app.db.engine import get_session
from app.ingestion.runner import run_ingestion
from app.reporting.identity_review import (
    IDENTITY_REVIEW_CSV_COLUMNS,
    build_identity_review_csv,
)


runner = CliRunner()
FIXTURE = Path(__file__).parent / "fixtures" / "fake_source.json"


def _item(*, model_raw: str = "Model A", model_id: str | None = None, effective: str | None = None, chain_error: str | None = None, status: str = "needs_review"):
    claim = SimpleNamespace(
        id="claim-1",
        official_source_id="source-1",
        source_snapshot_id="snapshot-1",
        source_revision_decision_id="revision-decision-1",
        benchmark_id="benchmark-1",
        model_entity_id=model_id,
        model_raw=model_raw,
        capture_status=status,
    )
    projection = repo.ClaimReviewProjection(
        model_entity_id=effective,
        benchmark_id="benchmark-1",
        metric=None,
        split=None,
        setting=None,
        evaluation_version=None,
        effective_decision_id="decision-1" if effective else None,
        chain_error=chain_error,
    )
    return repo.ReviewQueueItem(claim=claim, projection=projection)


def _page(*items, next_cursor=None, exhausted=True, scanned=None):
    return repo.ReviewQueuePage(
        items=list(items),
        next_cursor=next_cursor,
        exhausted=exhausted,
        scanned=len(items) if scanned is None else scanned,
        projected=len(items),
    )


def _rows(payload: bytes):
    assert payload.endswith(b"\r\n")
    assert b"\n" in payload
    return list(csv.DictReader(StringIO(payload.decode("utf-8", errors="strict"))))


def test_empty_queue_has_header_and_page_record_only():
    payload = build_identity_review_csv(_page())
    lines = payload.splitlines(keepends=True)
    assert len(lines) == 2  # header and page row
    rows = _rows(payload)
    assert list(rows[0]) == list(IDENTITY_REVIEW_CSV_COLUMNS)
    assert rows[0]["record_type"] == "page"
    assert rows[0]["emitted"] == "0"
    assert rows[0]["scanned"] == "0"
    assert rows[0]["exhausted"] == "true"


def test_claim_row_preserves_raw_model_and_excludes_sensitive_fields():
    raw = "=SUM(1,1)\nnaïve\\model\u202e"
    payload = build_identity_review_csv(
        _page(_item(model_raw=raw), next_cursor="v1.cursor", exhausted=False, scanned=7)
    )
    rows = _rows(payload)
    page, claim = rows
    assert page["next_cursor"] == "v1.cursor"
    assert claim["model_raw_b64"] == base64.b64encode(raw.encode()).decode("ascii")
    assert claim["model_raw_sha256"] == hashlib.sha256(raw.encode("utf-8")).hexdigest()
    assert claim["model_raw_display"].startswith("text:=SUM(1,1)\\n")
    assert "model_raw" not in claim
    assert "score_raw" not in claim
    assert "evidence_location" not in claim
    assert claim["queue_reason_codes"] == "MODEL_IDENTITY_UNRESOLVED;CAPTURE_NEEDS_REVIEW"


def test_reason_codes_are_closed_and_reviewed_identity_is_explicit():
    item = _item(model_id=None, effective="model-1", status="parser_verified")
    rows = _rows(build_identity_review_csv(_page(item)))
    assert rows[1]["queue_reason_codes"] == "MODEL_IDENTITY_REVIEWED"

    invalid = _item(chain_error="do not export details")
    rows = _rows(build_identity_review_csv(_page(invalid)))
    assert rows[1]["queue_reason_codes"] == "REVIEW_CHAIN_INVALID;CAPTURE_NEEDS_REVIEW"


def test_serialization_is_deterministic_and_quotes_every_cell():
    page = _page(_item(), next_cursor="next", exhausted=False, scanned=4)
    first = build_identity_review_csv(page)
    assert first == build_identity_review_csv(page)
    assert first.startswith(b'"record_type","claim_id"')
    assert b"\r\n" in first
    assert b"\n" not in first.replace(b"\r\n", b"")


def test_empty_but_unexhausted_page_keeps_cursor_and_metadata():
    payload = build_identity_review_csv(
        _page(next_cursor="v1.opaque-verbatim", exhausted=False, scanned=4)
    )
    rows = _rows(payload)
    assert rows == [
        {
            **{column: "" for column in IDENTITY_REVIEW_CSV_COLUMNS},
            "record_type": "page",
            "next_cursor": "v1.opaque-verbatim",
            "exhausted": "false",
            "scanned": "4",
            "emitted": "0",
        }
    ]


def test_model_raw_fixtures_round_trip_and_display_is_not_a_formula():
    values = (
        "=formula",
        "+formula",
        "-formula",
        "@formula",
        "  =leading-space",
        "unicode ✓ 日本語",
        "c0\x00\x1f",
        "c1\x80\x9f",
        "format\u202e\u200e",
        "back\\slash",
    )
    for raw in values:
        rows = _rows(build_identity_review_csv(_page(_item(model_raw=raw))))
        claim = rows[1]
        assert base64.b64decode(claim["model_raw_b64"]).decode("utf-8") == raw
        assert claim["model_raw_sha256"] == hashlib.sha256(raw.encode("utf-8")).hexdigest()
        assert claim["model_raw_display"].startswith("text:")
        assert "\x00" not in claim["model_raw_display"]
        assert "\x1f" not in claim["model_raw_display"]
        assert "\x80" not in claim["model_raw_display"]
        assert "\x9f" not in claim["model_raw_display"]
        assert "\u202e" not in claim["model_raw_display"]
        assert "\u200e" not in claim["model_raw_display"]
        display = claim["model_raw_display"].lstrip()
        assert not display.startswith(("=", "+", "-", "@"))


def test_fixed_columns_are_only_the_decision_support_contract():
    forbidden_fragments = (
        "score",
        "evidence",
        "url",
        "locator",
        "time",
        "timestamp",
        "snapshot_content",
        "environment",
    )
    assert all(
        not any(fragment in column.lower() for fragment in forbidden_fragments)
        for column in IDENTITY_REVIEW_CSV_COLUMNS
    )
    assert set(IDENTITY_REVIEW_CSV_COLUMNS) == set(_rows(build_identity_review_csv(_page()))[0])


def test_cli_invalid_limit_and_cursor_are_fixed_redacted(tmp_db, monkeypatch):
    def invalid_page(*_args, **_kwargs):
        raise ValueError("private cursor or limit details")

    monkeypatch.setattr(repo, "list_review_queue_page", invalid_page)
    for option, value in (("--limit", "not-a-number"), ("--limit", "0"), ("--limit", "-1"), ("--limit", "10001"), ("--cursor", "v1.private")):
        result = runner.invoke(app, ["review", "export-csv", option, value])
        assert result.exit_code == 2
        assert result.stdout == ""
        assert result.stderr == "Identity review CSV export blocked: invalid limit or cursor.\n"
        assert "private" not in result.output


def test_cli_export_real_db_is_two_selects_and_does_not_mutate(seeded_db, allow_quarantined_fixture_ingestion):
    with get_session() as session:
        run_ingestion(session, source_id="fake_local_fixture", fixture_path=FIXTURE)
        before_claims = session.scalar(select(func.count()).select_from(models.ResultClaim))
        before_decisions = session.scalar(select(func.count()).select_from(models.ClaimReviewDecision))

    from app.db.engine import _engine

    assert _engine is not None
    statements: list[str] = []

    def count_statement(conn, cursor, statement, parameters, context, executemany):  # type: ignore[no-untyped-def]
        statements.append(str(statement))

    event.listen(_engine, "before_cursor_execute", count_statement)
    try:
        result = runner.invoke(app, ["review", "export-csv", "--limit", "10"])
    finally:
        event.remove(_engine, "before_cursor_execute", count_statement)
    assert result.exit_code == 0, result.output
    assert len(statements) == 2
    assert all(statement.lstrip().upper().startswith("SELECT") for statement in statements)
    with get_session() as session:
        assert session.scalar(select(func.count()).select_from(models.ResultClaim)) == before_claims
        assert session.scalar(select(func.count()).select_from(models.ClaimReviewDecision)) == before_decisions


def test_real_repository_and_csv_pagination_has_no_duplicate_or_omitted_claims(
    seeded_db, allow_quarantined_fixture_ingestion
):
    with get_session() as session:
        run_ingestion(session, source_id="fake_local_fixture", fixture_path=FIXTURE)

    seen: list[str] = []
    cursor = None
    while True:
        with get_session() as session:
            page = repo.list_review_queue_page(session, limit=1, cursor=cursor)
            payload = build_identity_review_csv(page)
        rows = _rows(payload)
        page_row = rows[0]
        assert page_row["exhausted"] == ("true" if page.exhausted else "false")
        assert page_row["next_cursor"] == (page.next_cursor or "")
        assert int(page_row["emitted"]) == len(page.items)
        seen.extend(row["claim_id"] for row in rows[1:])
        if page.exhausted:
            assert page.next_cursor is None
            break
        assert page.next_cursor
        cursor = page.next_cursor

    with get_session() as session:
        expected = [item.claim.id for item in repo.list_review_queue_page(session, limit=10).items]
    assert seen == expected
    assert len(seen) == len(set(seen))
