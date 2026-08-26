from __future__ import annotations

import hashlib
import json
from pathlib import Path

from typer.testing import CliRunner

from app.cli import app
from app.reporting.coverage_census import coverage_census_digest


runner = CliRunner()
REGISTRY_DIR = Path(__file__).resolve().parents[1] / "app" / "registry"
UNIVERSE = REGISTRY_DIR / "coverage_universe.yaml"


def _coverage_args(database_url: str, output_format: str = "json") -> list[str]:
    return [
        "coverage",
        "status",
        "--format",
        output_format,
        "--registry-dir",
        str(REGISTRY_DIR),
        "--universe",
        str(UNIVERSE),
        "--database-url",
        database_url,
    ]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sidecars(path: Path) -> set[str]:
    return {
        candidate.name
        for suffix in ("-wal", "-shm", "-journal")
        if (candidate := Path(f"{path}{suffix}")).exists()
    }


def test_coverage_cli_emits_complete_blocked_json_without_creating_missing_db(tmp_path):
    missing = tmp_path / "missing-ledger.db"

    result = runner.invoke(app, _coverage_args(f"sqlite:///{missing}"))

    assert result.exit_code == 1, result.output
    payload = json.loads(result.stdout)
    assert payload["availability"] == "report_only"
    assert payload["readiness"] == "blocked"
    assert payload["manifest"]["contentSha256"] == coverage_census_digest(payload)
    assert {
        "benchmarkRowCount": 42,
        "benchmarkUniqueIdCount": 42,
        "sourceRowCount": 53,
        "sourceUniqueIdCount": 53,
        "modelRowCount": 1186,
        "modelUniqueIdCount": 1186,
    }.items() <= payload["manifest"]["denominators"].items()
    assert payload["universe"]["approvalStatus"] == "draft_unapproved"
    assert payload["universe"]["effectiveOn"] is None
    assert payload["universe"]["decisionReference"] is None
    assert payload["legacyDatabase"]["status"] == "absent"
    assert payload["legacyDatabase"]["kind"] == "absent"
    assert {"LEGACY_DATABASE_ABSENT", "UNIVERSE_REVISION_UNAPPROVED"} <= {
        issue["reasonCode"] for issue in payload["issues"]
    }
    assert all(
        not Path(row["relativePath"]).is_absolute()
        and ".." not in Path(row["relativePath"]).parts
        for row in payload["inputs"]
    )
    assert not missing.exists()
    assert list(tmp_path.iterdir()) == []


def test_coverage_cli_keeps_current_database_bytes_metadata_schema_and_sidecars_unchanged(tmp_db):
    database = Path(tmp_db)
    before = (
        _sha256(database),
        database.stat().st_size,
        database.stat().st_mtime_ns,
        database.stat().st_ino,
        database.stat().st_mode,
        _sidecars(database),
    )

    result = runner.invoke(app, _coverage_args(f"sqlite:///{database}"))

    assert result.exit_code == 1, result.output
    payload = json.loads(result.stdout)
    assert payload["legacyDatabase"]["status"] == "current_read_only"
    assert payload["legacyDatabase"]["kind"] == "versioned"
    assert payload["legacyDatabase"]["integrityOk"] is True
    assert payload["legacyDatabase"]["foreignKeyViolationCount"] == 0
    assert payload["legacyDatabase"]["contentSha256"] == before[0]
    assert (
        _sha256(database),
        database.stat().st_size,
        database.stat().st_mtime_ns,
        database.stat().st_ino,
        database.stat().st_mode,
        _sidecars(database),
    ) == before


def test_coverage_cli_markdown_is_the_same_blocked_report_and_includes_digest(tmp_path):
    missing = tmp_path / "missing-ledger.db"
    database_url = f"sqlite:///{missing}"

    json_result = runner.invoke(app, _coverage_args(database_url, "json"))
    markdown_result = runner.invoke(app, _coverage_args(database_url, "markdown"))

    assert json_result.exit_code == markdown_result.exit_code == 1
    payload = json.loads(json_result.stdout)
    assert payload["manifest"]["contentSha256"] in markdown_result.stdout
    assert "blocked" in markdown_result.stdout.lower()
    assert "not certification" in markdown_result.stdout.lower()
    assert not missing.exists()


def test_coverage_cli_rejects_unknown_format_before_database_access(tmp_path):
    missing = tmp_path / "must-not-exist.db"

    result = runner.invoke(app, _coverage_args(f"sqlite:///{missing}", "yaml"))

    assert result.exit_code == 2
    assert "--format must be either 'json' or 'markdown'" in result.output
    assert not missing.exists()


def test_coverage_cli_reports_unsupported_database_without_echoing_credentials():
    secret_url = "postgresql://coverage-user:do-not-print@example.invalid/ledger"

    result = runner.invoke(app, _coverage_args(secret_url))

    assert result.exit_code == 1, result.output
    payload = json.loads(result.stdout)
    assert payload["legacyDatabase"]["kind"] == "unsupported_url"
    assert payload["legacyDatabase"]["status"] == "unavailable"
    assert "do-not-print" not in result.output
    assert "coverage-user" not in result.output
    assert secret_url not in result.output
