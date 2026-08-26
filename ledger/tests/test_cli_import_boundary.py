from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
from contextlib import nullcontext

from typer.testing import CliRunner

from app.cli import app


runner = CliRunner()


def test_cli_import_and_help_work_in_a_fresh_process() -> None:
    ledger_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ledger_root)

    imported = subprocess.run(
        [sys.executable, "-c", "import app.cli"],
        cwd=ledger_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    helped = subprocess.run(
        [str(ledger_root / ".venv" / "bin" / "benchmark-ledger"), "--help"],
        cwd=ledger_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert imported.returncode == 0, imported.stderr
    assert helped.returncode == 0, helped.stderr
    assert "Official benchmark result capture ledger" in helped.stdout


def test_non_dry_ingest_refuses_missing_database_without_initializing_it(
    tmp_path: Path, monkeypatch
) -> None:
    database_path = tmp_path / "missing.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")

    from app.config import get_settings
    import app.db.engine as engine

    get_settings.cache_clear()
    engine._engine = None
    engine._SessionLocal = None
    try:
        result = runner.invoke(app, ["ingest", "--source", "anything"])
    finally:
        get_settings.cache_clear()
        engine._engine = None
        engine._SessionLocal = None

    assert result.exit_code == 2
    assert "existing, integrity-clean current ledger database is required" in result.output
    assert not database_path.exists()


def test_expected_safe_fetch_failure_has_stable_redacted_exit(monkeypatch) -> None:
    import app.cli as cli_module
    from app.db.migrate import DatabaseStatus
    from app.ingestion.safe_fetch import SafeFetchError

    monkeypatch.setattr(
        cli_module,
        "inspect_database",
        lambda _url: DatabaseStatus(
            kind="current",
            database_url="sqlite:///redacted.db",
            path="/tmp/redacted.db",
            revision="0010_operational_persistence",
            tables=("alembic_version",),
            integrity_ok=True,
            foreign_key_violations=0,
        ),
    )
    monkeypatch.setattr(cli_module, "get_session", lambda: nullcontext(object()))
    monkeypatch.setattr(
        cli_module,
        "run_ingestion",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            SafeFetchError(
                "FETCH_TRANSPORT_UNAVAILABLE",
                "provider response contained https://operator:secret@example.invalid/token",
            )
        ),
    )
    monkeypatch.setattr(
        cli_module,
        "init_db",
        lambda: (_ for _ in ()).throw(AssertionError("ingest must not initialize a database")),
    )

    result = runner.invoke(app, ["ingest", "--source", "source-id"])

    assert result.exit_code == 2
    assert "FETCH_TRANSPORT_UNAVAILABLE" in result.output
    assert "provider response" not in result.output
    assert "operator:secret" not in result.output
