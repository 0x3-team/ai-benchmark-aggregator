import json

from typer.testing import CliRunner

from app.cli import app
from app.export.official_json import OfficialPublicationDisabledError, export_official_json


runner = CliRunner()


def test_cli_rejects_quarantined_ingestion_before_reporting_success(seeded_db):
    result = runner.invoke(app, ["ingest", "--source", "fake_local_fixture", "--dry-run"])
    assert result.exit_code == 2
    assert "Ingestion blocked:" in result.output
    assert "Ingestion complete." not in result.output


def test_cli_disables_bulk_review_and_export_without_opening_ledger(tmp_db):
    review = runner.invoke(app, ["review", "auto-verify-matched"])
    export = runner.invoke(app, ["export-official-json"])
    assert review.exit_code == 2
    assert "disabled during Official-mode containment" in review.output
    assert export.exit_code == 2
    assert "Official export is disabled during containment" in export.output


def test_export_module_has_no_programmatic_bypass(tmp_db):
    from app.db.engine import get_session

    with get_session() as session:
        try:
            export_official_json(session, tmp_db)  # type: ignore[arg-type]
        except OfficialPublicationDisabledError as exc:
            assert "disabled" in str(exc)
        else:
            raise AssertionError("legacy exporter unexpectedly wrote an Official artifact")


def test_cli_exposes_read_only_migration_status_and_refuses_current_db_rehearsal(tmp_db, tmp_path):
    status = runner.invoke(app, ["db", "status"])
    preflight = runner.invoke(app, ["db", "preflight"])
    migrate = runner.invoke(app, ["db", "migrate", "--backup-dir", str(tmp_path / "backups")])

    assert status.exit_code == 0
    assert json.loads(status.output)["kind"] == "current"
    assert preflight.exit_code == 0
    assert json.loads(preflight.output)["integrity_ok"] is True
    assert migrate.exit_code == 2
    assert "Only an exact, integrity-clean legacy baseline" in migrate.output


def test_legacy_inventory_refuses_a_missing_database_without_creating_it(tmp_path, monkeypatch):
    missing = tmp_path / "missing-ledger.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{missing}")
    from app.config import get_settings
    import app.db.engine as engine_module

    get_settings.cache_clear()
    engine_module._engine = None
    engine_module._SessionLocal = None
    try:
        result = runner.invoke(app, ["reports", "legacy-inventory"])
        assert result.exit_code == 2
        assert "Legacy inventory blocked:" in result.output
        assert not missing.exists()
    finally:
        get_settings.cache_clear()
        engine_module._engine = None
        engine_module._SessionLocal = None


def test_postgresql_upgrade_cli_requires_exact_revision_and_redacts_locator(monkeypatch):
    from app.config import get_settings
    from app.db.migrate import DatabaseStatus
    import app.cli as cli_module

    secret_url = (
        "postgresql+psycopg://operator:do-not-print@db.example/ledger"
        "?sslkey=private.pem&provider_token=hidden"
    )
    monkeypatch.setenv("DATABASE_URL", secret_url)
    get_settings.cache_clear()
    observed: dict[str, str] = {}

    def fake_upgrade(database_url: str, *, expected_revision: str) -> DatabaseStatus:
        observed["database_url"] = database_url
        observed["expected_revision"] = expected_revision
        return DatabaseStatus(
            kind="current",
            database_url="postgresql+psycopg://operator@db.example/ledger",
            path=None,
            revision="0009_postgresql_guardrails",
            tables=("alembic_version",),
            integrity_ok=True,
            foreign_key_violations=0,
        )

    monkeypatch.setattr(cli_module, "upgrade_postgresql_database", fake_upgrade)
    try:
        result = runner.invoke(
            app,
            [
                "db",
                "upgrade-postgresql",
                "--expected-revision",
                "0008_claim_publication_chain_guards",
            ],
        )
    finally:
        get_settings.cache_clear()

    assert result.exit_code == 0
    assert observed == {
        "database_url": secret_url,
        "expected_revision": "0008_claim_publication_chain_guards",
    }
    payload = json.loads(result.output)
    assert payload["kind"] == "current"
    assert "do-not-print" not in result.output
    assert "private.pem" not in result.output
    assert "provider_token" not in result.output


def test_postgresql_unavailable_preflight_is_nonzero_and_redacted(monkeypatch):
    from app.config import get_settings
    from app.db.migrate import DatabaseStatus
    import app.cli as cli_module

    secret_url = (
        "postgresql+psycopg://operator:do-not-print@127.0.0.1:1/ledger"
        "?connect_timeout=1&provider_token=hidden"
    )
    monkeypatch.setenv("DATABASE_URL", secret_url)
    get_settings.cache_clear()

    def fake_inspect(database_url: str) -> DatabaseStatus:
        assert database_url == secret_url
        return DatabaseStatus(
            kind="unavailable",
            database_url="postgresql+psycopg://operator@127.0.0.1:1/ledger",
            path=None,
            revision=None,
            tables=(),
            integrity_ok=False,
            foreign_key_violations=0,
            detail="PostgreSQL inspection failed closed (OperationalError).",
        )

    monkeypatch.setattr(cli_module, "inspect_database", fake_inspect)
    try:
        result = runner.invoke(app, ["db", "preflight"])
    finally:
        get_settings.cache_clear()

    assert result.exit_code == 2
    payload = json.loads(result.output)
    assert payload["kind"] == "unavailable"
    assert payload["integrity_ok"] is False
    assert "do-not-print" not in result.output
    assert "provider_token" not in result.output
