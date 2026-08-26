"""F17 regression: review map-model must bind the persisted actor to the actual
invoking OS principal and must never accept caller-controlled provenance.

The former CLI accepted an arbitrary ``--actor`` string and persisted it as the
ClaimReviewDecision actor — a caller-controlled audit-provenance forgery.  The
fixed CLI resolves the trusted principal lazily (so the CLI stays importable
without ``pwd``) as the canonical ``posix:euid=<decimal>;name=<name>`` value,
failing closed before any DB session or write when the principal cannot be
resolved or fails strict validation.  ``--actor`` is removed from the CLI.
"""

from __future__ import annotations

import os
import pwd

import pytest
from sqlalchemy import func, select
from typer.testing import CliRunner

from app import cli as cli_module
from app.cli import _os_principal, app
from app.db import models
from app.db.engine import get_session
from app.ingestion.runner import run_ingestion


FIXTURE = __import__("pathlib").Path(__file__).parent / "fixtures" / "fake_source.json"
runner = CliRunner()


def _unknown_claim(session):  # type: ignore[no-untyped-def]
    claim = session.scalar(
        select(models.ResultClaim).where(models.ResultClaim.model_raw == "Unknown-Model-X")
    )
    assert claim is not None
    return claim


def _mapping_count(session, claim_id: str) -> int:
    return session.scalar(
        select(func.count()).select_from(models.ClaimReviewDecision).where(
            models.ClaimReviewDecision.result_claim_id == claim_id
        )
    ) or 0


def _expected_canonical_actor() -> str:
    euid = os.geteuid()
    name = pwd.getpwuid(euid).pw_name
    return f"posix:euid={euid};name={name}"


# ---------------------------------------------------------------------------
# Direct production-helper tests (fail closed on every failure mode)
# ---------------------------------------------------------------------------


def test_helper_missing_geteuid_fails_closed(monkeypatch):
    monkeypatch.delattr(cli_module.os, "geteuid", raising=False)
    with pytest.raises(LookupError, match="no trusted local principal"):
        _os_principal()


def test_helper_missing_pwd_module_fails_closed(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def _no_pwd(name, *args, **kwargs):
        if name == "pwd":
            raise ImportError("no pwd")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _no_pwd)
    with pytest.raises(LookupError, match="no trusted local principal"):
        _os_principal()


def test_helper_passwd_lookup_failure_fails_closed(monkeypatch):
    def _no_entry(uid):
        raise KeyError(uid)

    monkeypatch.setattr(pwd, "getpwuid", _no_entry)
    with pytest.raises(LookupError, match="no passwd entry"):
        _os_principal()


def test_helper_uid_mismatch_fails_closed(monkeypatch):
    euid = os.geteuid()

    class _Mismatched:  # type: ignore[no-untyped-def]
        pw_uid = euid + 1
        pw_name = "someone-else"

    monkeypatch.setattr(pwd, "getpwuid", lambda uid: _Mismatched())
    with pytest.raises(LookupError, match="uid mismatch"):
        _os_principal()


def test_helper_blank_or_control_name_fails_closed(monkeypatch):
    euid = os.geteuid()

    class _Blank:  # type: ignore[no-untyped-def]
        pw_uid = euid
        pw_name = ""

    class _Control:  # type: ignore[no-untyped-def]
        pw_uid = euid
        pw_name = "evil\x1bname"

    monkeypatch.setattr(pwd, "getpwuid", lambda uid: _Blank())
    with pytest.raises(LookupError, match="empty"):
        _os_principal()
    monkeypatch.setattr(pwd, "getpwuid", lambda uid: _Control())
    with pytest.raises(LookupError, match="control or format"):
        _os_principal()


def test_helper_overlong_value_fails_closed(monkeypatch):
    euid = os.geteuid()

    class _Overlong:  # type: ignore[no-untyped-def]
        pw_uid = euid
        pw_name = "n" * 200

    monkeypatch.setattr(pwd, "getpwuid", lambda uid: _Overlong())
    with pytest.raises(LookupError, match="exceeds the persisted actor field bound"):
        _os_principal()


def test_helper_success_returns_canonical_euid_and_name():
    actor = _os_principal()
    assert actor == _expected_canonical_actor()
    assert actor.startswith("posix:euid=")
    assert ";name=" in actor


# ---------------------------------------------------------------------------
# CLI boundary tests
# ---------------------------------------------------------------------------


def test_cli_rejects_caller_supplied_actor_before_any_row(
    seeded_db, allow_quarantined_fixture_ingestion
):
    """F17: --actor is no longer a CLI option; the invocation must fail and no
    decision row may be written."""
    with get_session() as session:
        run_ingestion(session, source_id="fake_local_fixture", fixture_path=FIXTURE)
        claim = _unknown_claim(session)
        claim_id = claim.id

    result = runner.invoke(
        app,
        ["review", "map-model", claim_id, "fake_model_1", "--actor", "operator"],
    )
    assert result.exit_code == 2
    assert "No such option" in result.output
    with get_session() as session:
        assert _mapping_count(session, claim_id) == 0


def test_cli_writes_os_bound_actor_even_with_forged_identity_env(
    seeded_db, allow_quarantined_fixture_ingestion
):
    """F17: a legitimate command writes the OS principal even when common
    identity environment variables are forged."""
    with get_session() as session:
        run_ingestion(session, source_id="fake_local_fixture", fixture_path=FIXTURE)
        claim = _unknown_claim(session)
        claim_id = claim.id

    expected_actor = _expected_canonical_actor()
    result = runner.invoke(
        app,
        ["review", "map-model", claim_id, "fake_model_1"],
        env={"USER": "forged-user", "LOGNAME": "forged-logname"},
    )
    assert result.exit_code == 0, result.output
    assert "Recorded manual model mapping" in result.output
    with get_session() as session:
        decisions = list(
            session.scalars(
                select(models.ClaimReviewDecision).where(
                    models.ClaimReviewDecision.result_claim_id == claim_id
                )
            )
        )
        assert len(decisions) == 1
        assert decisions[0].actor == expected_actor
        assert decisions[0].actor != "forged-user"
        assert decisions[0].actor != "forged-logname"
        assert decisions[0].model_entity_id == "fake_model_1"


def test_cli_fails_closed_when_trusted_principal_unresolvable_writes_zero_rows(
    seeded_db, allow_quarantined_fixture_ingestion, monkeypatch
):
    """F17: if the trusted principal cannot be resolved, the command exits 2
    and writes zero decision rows."""
    with get_session() as session:
        run_ingestion(session, source_id="fake_local_fixture", fixture_path=FIXTURE)
        claim = _unknown_claim(session)
        claim_id = claim.id

    def _no_principal() -> str:
        raise LookupError("no trusted principal")

    monkeypatch.setattr(cli_module, "_os_principal", _no_principal)
    result = runner.invoke(
        app,
        ["review", "map-model", claim_id, "fake_model_1"],
        env={"USER": "forged-user", "LOGNAME": "forged-logname"},
    )
    assert result.exit_code == 2
    assert "Review mapping blocked" in result.output
    assert "principal" in result.output.lower()
    with get_session() as session:
        assert _mapping_count(session, claim_id) == 0
