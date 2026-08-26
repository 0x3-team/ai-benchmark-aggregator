"""F14 regression: CLI terminal output must never carry raw control bytes or
control/format code points from durable values (claims, review, ingestion).

Adversarial values across model_raw, benchmark_raw, score_raw, evidence, and
chain_error must render as visible escapes; printable Unicode stays readable;
literal backslashes render exactly as ``\\``; identifiers and status strings
are sanitized at the same sinks; and no injected output line can appear.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from app import cli as cli_module
from app.cli import _terminal_render, app
from app.db import models
from app.db import repositories as repo
from app.ingestion.runner import IngestionSummary


runner = CliRunner()


def _claim(
    *,
    claim_id: str = "c1",
    model_raw: str,
    benchmark_raw: str,
    score_raw: str,
    evidence: dict | None = None,
    model_entity_id: str | None = None,
    benchmark_id: str | None = None,
    capture_status: str = "unreviewed",
    chain_error: str | None = None,
) -> tuple[models.ResultClaim, repo.ClaimReviewProjection]:
    claim = models.ResultClaim(
        id=claim_id,
        source_snapshot_id="snap-1",
        source_revision_decision_id=None,
        official_source_id="src-1",
        benchmark_id=benchmark_id,
        model_entity_id=model_entity_id,
        model_raw=model_raw,
        benchmark_raw=benchmark_raw,
        score_raw=score_raw,
        metric_raw=None,
        split_raw=None,
        setting_raw=None,
        evaluation_version_raw=None,
        rank_raw=None,
        date_raw=None,
        score_numeric=None,
        score_unit=None,
        evidence_text=None,
        evidence_location=evidence if evidence is not None else {},
        capture_method="fixture",
        capture_confidence=0.0,
        capture_status=capture_status,
        scientific_status="unknown",
        officialness_level="O5",
        claim_fingerprint="f" * 64,
    )
    projection = repo.ClaimReviewProjection(
        model_entity_id=model_entity_id,
        benchmark_id=benchmark_id,
        metric=None,
        split=None,
        setting=None,
        evaluation_version=None,
        effective_decision_id=None,
        chain_error=chain_error,
    )
    return claim, projection


@pytest.fixture()
def db(tmp_path: Path, monkeypatch):
    """A current disposable SQLite ledger so inspect_database passes."""
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("SNAPSHOT_LOCAL_ROOT", str(tmp_path / "snapshots"))
    from app.config import get_settings

    get_settings.cache_clear()
    import app.db.engine as engine

    engine._engine = None
    engine._SessionLocal = None
    try:
        engine.init_db()
        yield db_path
    finally:
        engine._engine = None
        engine._SessionLocal = None
        get_settings.cache_clear()


def _adversarial_values() -> dict[str, str]:
    return {
        "ansi_csi": "\x1b[31m",
        "osc_bel": "\x1b]0;evil-title\x07",
        "carriage_return": "\r",
        "embedded_newline": "\n",
        "backspace": "\b",
        "literal_backslash": "C:\\temp\\file",
        "c1_csi": "\x9b",
        "bidi": "\u202e",
    }


# ---------------------------------------------------------------------------
# Direct helper edge cases (exact, deterministic)
# ---------------------------------------------------------------------------


def test_terminal_render_helper_full_edge_cases():
    """Exact, deterministic renderer behavior across every documented class."""
    # Short visible escapes for LF/CR/TAB/BS/FF.
    assert _terminal_render("a\nb") == "a\\nb"
    assert _terminal_render("a\rb") == "a\\rb"
    assert _terminal_render("a\tb") == "a\\tb"
    assert _terminal_render("a\bb") == "a\\bb"
    assert _terminal_render("a\fb") == "a\\fb"
    # Literal backslash -> double backslash (two chars), exactly once.
    assert _terminal_render("a\\b") == "a\\\\b"
    assert _terminal_render("C:\\temp\\file") == "C:\\\\temp\\\\file"
    # ESC/BEL/DEL/C1 -> \xNN lowercase.
    assert _terminal_render("\x1b[31m") == "\\x1b[31m"
    assert _terminal_render("\x07") == "\\x07"
    assert _terminal_render("\x7f") == "\\x7f"
    assert _terminal_render("\x9b") == "\\x9b"
    # BMP format/control -> \uNNNN lowercase (bidi U+202E, LRM U+200E).
    assert _terminal_render("\u202e") == "\\u202e"
    assert _terminal_render("\u200e") == "\\u200e"
    # Astral Cf -> \UNNNNNNNN lowercase (U+E0001 LANGUAGE TAG).
    assert _terminal_render("\U000e0001") == "\\U000e0001"
    # Printable Unicode preserved exactly (incl. accented, symbol, emoji, CJK).
    assert _terminal_render("héllo ✓") == "héllo ✓"
    assert _terminal_render("😀") == "😀"
    assert _terminal_render("日本語") == "日本語"
    # str() of a non-string value is accepted.  The dict repr already shows
    # the C1 byte as the two-character sequence \x9b, whose backslash the
    # renderer then escapes to \\x9b — visible and unambiguous.
    assert _terminal_render({"path": "a\x9bb"}) == "{'path': 'a\\\\x9bb'}"


# ---------------------------------------------------------------------------
# Real Typer command sinks
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("sink", ["list", "show"])
def test_claims_terminal_output_never_leaks_control_bytes(db, monkeypatch, sink):
    values = _adversarial_values()
    model_raw = f"m{values['ansi_csi']}x"
    benchmark_raw = f"b{values['osc_bel']}y"
    score_raw = f"s{values['c1_csi']}z"
    claim, projection = _claim(
        claim_id="c1\x9b",
        model_raw=model_raw,
        benchmark_raw=benchmark_raw,
        score_raw=score_raw,
        evidence={"path": values["literal_backslash"] + values["bidi"]},
        capture_status="needs\u202ereview",
        chain_error=f"err{values['embedded_newline']}injected-line",
    )
    if sink == "list":
        monkeypatch.setattr(repo, "list_claims", lambda session, benchmark_id=None, limit=50: [claim])
        result = runner.invoke(app, ["claims", "list"])
    else:
        monkeypatch.setattr(repo, "get_claim", lambda session, claim_id: claim)
        monkeypatch.setattr(
            repo, "get_claim_review_projection", lambda session, c: projection
        )
        result = runner.invoke(app, ["claims", "show", "c1"])

    assert result.exit_code == 0, result.output
    out = result.output
    for token in (
        "\x1b[31m",
        "\x1b]0;evil-title\x07",
        "\r",
        "\x9b",
        "\u202e",
    ):
        assert token not in out, f"raw control token {token!r} leaked in {sink}"
    # Visible escapes present (identifiers/status too).
    assert "\\x1b" in out
    assert "\\x9b" in out  # from claim_id c1\x9b
    assert "\\u202e" in out  # from capture_status needs\u202ereview
    if sink == "show":
        # Evidence is only printed by show; it carries the bidi + backslash.
        # The embedded newline renders as a visible \\n escape, so the
        # adversarial text never starts a new terminal line.
        assert "\n" + "injected-line" not in out
        assert "\\n" in out
    # Printable Unicode stays readable.
    assert "x" in out and "y" in out and "z" in out


def test_review_show_delegation_sanitizes_values(db, monkeypatch):
    values = _adversarial_values()
    claim, projection = _claim(
        model_raw=f"m{values['ansi_csi']}",
        benchmark_raw=f"b{values['osc_bel']}",
        score_raw=f"s{values['carriage_return']}",
        evidence={"k": values["backspace"]},
        chain_error=f"chain{values['bidi']}err",
    )
    monkeypatch.setattr(repo, "get_claim", lambda session, claim_id: claim)
    monkeypatch.setattr(
        repo, "get_claim_review_projection", lambda session, c: projection
    )
    result = runner.invoke(app, ["review", "show", "c1"])
    assert result.exit_code == 0, result.output
    out = result.output
    for token in ("\x1b[", "\x07", "\r", "\b", "\u202e"):
        assert token not in out, f"raw control token {token!r} leaked in review show"
    assert "\\x1b" in out and "\\u202e" in out


def test_review_queue_single_pass_reason_rendering(db, monkeypatch):
    """The chain-error reason is rendered exactly once (no double-escape)."""
    values = _adversarial_values()
    claim, projection = _claim(
        model_raw=f"m{values['ansi_csi']}",
        benchmark_raw=f"b{values['bidi']}",
        score_raw=f"s{values['c1_csi']}",
        evidence={"path": values["literal_backslash"]},
        capture_status="needs_review",
        chain_error=f"chain{values['embedded_newline']}injected",
    )
    item = repo.ReviewQueueItem(claim=claim, projection=projection)
    page = repo.ReviewQueuePage(items=[item], next_cursor=None, exhausted=True, scanned=1)
    monkeypatch.setattr(repo, "list_review_queue_page", lambda session, limit=50, cursor=None: page)
    result = runner.invoke(app, ["review", "queue"])
    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    out = result.output
    for token in ("\x1b[", "\x07", "\x9b", "\u202e"):
        assert token not in out, f"raw control token {token!r} leaked in review queue"
    # The embedded newline in chain_error renders as a visible \\n escape, so
    # "injected" never starts a new terminal line.
    assert "\n" + "injected" not in out
    assert "\\x1b" in out and "\\u202e" in out and "\\x9b" in out
    # Single-pass: the exact reason line renders with one backslash in the \n
    # escape; a double render would show \\n (two backslashes) instead.
    assert any(
        "Reason: review chain invalid: chain\\ninjected" in line for line in lines
    )
    assert not any(
        "Reason: review chain invalid: chain\\\\ninjected" in line for line in lines
    )


def test_review_export_csv_is_safe_and_invalid_requests_are_redacted(db, monkeypatch):
    claim, projection = _claim(
        model_raw="=SUM(1,1)\nmodel\u202e",
        benchmark_raw="benchmark",
        score_raw="1",
        capture_status="needs_review",
        chain_error="secret cursor details",
    )
    page = repo.ReviewQueuePage(
        items=[repo.ReviewQueueItem(claim=claim, projection=projection)],
        next_cursor="v1.safe-cursor",
        exhausted=False,
        scanned=1,
    )
    monkeypatch.setattr(
        repo,
        "list_review_queue_page",
        lambda session, limit=50, cursor=None: page,
    )
    result = runner.invoke(app, ["review", "export-csv", "--limit", "1"])
    assert result.exit_code == 0, result.output
    assert result.stdout_bytes.endswith(b"\r\n")
    assert b"\r\n" in result.stdout_bytes
    assert result.stdout.startswith('"record_type"')
    assert "text:=SUM(1,1)\\nmodel\\u202e" in result.stdout
    assert "secret cursor details" not in result.stdout
    assert "score_raw" not in result.stdout
    for token in ("\x1b", "\u202e", "\r"):
        assert token not in result.stdout

    def invalid_page(*_args, **_kwargs):
        raise ValueError("v1.private-cursor")

    monkeypatch.setattr(repo, "list_review_queue_page", invalid_page)
    invalid = runner.invoke(app, ["review", "export-csv", "--cursor", "v1.private-cursor"])
    assert invalid.exit_code == 2
    assert invalid.stdout == ""
    assert "v1.private-cursor" not in invalid.output
    assert "Identity review CSV export blocked: invalid limit or cursor." in invalid.output


def test_ingest_dry_run_sample_and_summary_error_are_sanitized(db, monkeypatch):
    values = _adversarial_values()
    summary = IngestionSummary(
        sources_checked=1,
        status="completed",
        errors=[f"boom{values['osc_bel']}error"],
        dry_run_claims=[
            {
                "model_raw": f"m{values['ansi_csi']}",
                "score_raw": f"s{values['bidi']}",
                # Exact: "needs" + U+009B + "review".
                "capture_status": "needs\x9breview",
            }
        ],
    )
    monkeypatch.setattr(cli_module, "run_ingestion", lambda session, **kwargs: summary)
    result = runner.invoke(
        app, ["ingest", "--source", "fake_local_fixture", "--dry-run"]
    )
    assert result.exit_code == 0, result.output
    out = result.output
    for token in ("\x1b[", "\x07", "\u202e", "\x9b"):
        assert token not in out, f"raw control token {token!r} leaked in ingest dry-run"
    assert "\\x1b" in out and "\\u202e" in out
    assert "\\x07" in out
    # Exact visible escape for the dry-run capture_status.
    assert "needs\\x9breview" in out


def test_literal_backslash_renders_exactly_in_claims_show(db, monkeypatch):
    values = _adversarial_values()
    claim, projection = _claim(
        model_raw=f"m{values['literal_backslash']}",
        benchmark_raw="plain",
        score_raw="1.0",
        evidence={"path": "a\\b"},
        chain_error=None,
    )
    monkeypatch.setattr(repo, "get_claim", lambda session, claim_id: claim)
    monkeypatch.setattr(
        repo, "get_claim_review_projection", lambda session, c: projection
    )
    result = runner.invoke(app, ["claims", "show", "c1"])
    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    # Exact: C:\temp\file renders as C:\\temp\\file (each \ -> \\, once).
    assert "model_raw: mC:\\\\temp\\\\file" in lines
    # Exact raw-single-backslash line absent.
    assert "model_raw: mC:\\temp\\file" not in lines


def test_identifier_and_status_controls_are_sanitized(db, monkeypatch):
    values = _adversarial_values()
    claim, projection = _claim(
        claim_id="evil\x1b-id",
        model_raw="m",
        benchmark_raw="b",
        score_raw="1.0",
        evidence={"k": "v"},
        model_entity_id="ent\x9b",
        benchmark_id="bench\u202e",
        capture_status="needs\u200ereview",
    )
    monkeypatch.setattr(repo, "get_claim", lambda session, claim_id: claim)
    monkeypatch.setattr(
        repo, "get_claim_review_projection", lambda session, c: projection
    )
    result = runner.invoke(app, ["claims", "show", "c1"])
    assert result.exit_code == 0, result.output
    out = result.output
    for token in ("\x1b", "\x9b", "\u202e", "\u200e"):
        assert token not in out, f"raw control token {token!r} leaked in identifiers"
    assert "\\x1b" in out and "\\x9b" in out
    assert "\\u202e" in out and "\\u200e" in out
