from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from app.cli import app
from app.db import models, repositories as repo
from app.db.engine import get_session, init_db
from app.db.migrate import (
    DatabaseMigrationError,
    head_revision,
    inspect_database,
    migrate_legacy_copy,
)
from app.registry.seed_loader import seed_registry
from app.reporting.legacy_inventory import (
    build_legacy_inventory_report,
    canonical_legacy_inventory_json,
)


def _url(path: Path) -> str:
    return f"sqlite:///{path}"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _alembic_config(database_url: str) -> Config:
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url)
    config.attributes["database_url"] = database_url
    return config


def _backup_sqlite(source: Path, destination: Path) -> None:
    with sqlite3.connect(source) as source_connection, sqlite3.connect(destination) as destination_connection:
        source_connection.backup(destination_connection)


def _create_legacy_database(path: Path) -> None:
    """Create a pre-Alembic fixture with every evidence-bearing relation populated."""
    database_url = _url(path)
    command.upgrade(_alembic_config(database_url), "0001_legacy_schema")
    with sqlite3.connect(path) as connection:
        connection.execute("DROP TABLE alembic_version")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            "INSERT INTO benchmarks (id, canonical_name, display_name) VALUES ('b1', 'bench', 'Bench')"
        )
        connection.execute(
            "INSERT INTO model_entities (id, canonical_name, display_name, entity_type) "
            "VALUES ('m1', 'model', 'Model', 'model')"
        )
        connection.execute(
            """
            INSERT INTO official_sources (
                id, benchmark_id, source_name, source_url, source_type,
                officialness_level, machine_readable, requires_auth, supports_history,
                parser_config, status
            ) VALUES (
                's1', 'b1', 'Legacy source', 'https://official.example/results.json', 'api',
                'O5', 1, 0, 1, '{"adapter":"legacy"}', 'active'
            )
            """
        )
        connection.execute(
            """
            INSERT INTO source_snapshots (
                id, official_source_id, raw_content_uri, content_hash, content_type,
                fetch_metadata, parser_version
            ) VALUES (
                'snap-1', 's1', 'file:///snapshots/legacy.json',
                'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
                'application/json', '{"etag":"legacy"}', 'legacy-v1'
            )
            """
        )
        for claim_id, model_raw, score_raw, fingerprint in (
            ("claim-1", "Model Raw One", "77.0", "f" * 64),
            ("claim-2", "Model Raw Two", "78.0", "e" * 64),
        ):
            connection.execute(
                """
                INSERT INTO result_claims (
                    id, source_snapshot_id, official_source_id, benchmark_id,
                    model_entity_id, model_raw, benchmark_raw, score_raw, metric_raw,
                    score_numeric, score_unit, evidence_text, evidence_location,
                    capture_method, capture_confidence, capture_status,
                    scientific_status, officialness_level, claim_fingerprint
                ) VALUES (
                    ?, 'snap-1', 's1', 'b1', 'm1', ?, 'Bench Raw', ?, 'accuracy',
                    ?, 'percent', 'verbatim evidence', '{"row":1}', 'legacy_parser',
                    0.9, 'human_verified', 'unknown', 'O5', ?
                )
                """,
                (claim_id, model_raw, score_raw, float(score_raw), fingerprint),
            )
        connection.execute(
            """
            INSERT INTO claim_validations (id, result_claim_id, validation_type, outcome, validator, notes)
            VALUES ('validation-1', 'claim-1', 'legacy', 'pass', 'legacy-validator', 'retained')
            """
        )
        connection.execute(
            """
            INSERT INTO claim_relationships (id, claim_id, related_claim_id, relationship_type, notes)
            VALUES ('relationship-1', 'claim-1', 'claim-2', 'same_source', 'retained')
            """
        )
        connection.execute(
            """
            INSERT INTO ingestion_runs (id, run_type, status, official_source_id, sources_checked, claims_inserted)
            VALUES ('run-1', 'source', 'completed', 's1', 1, 2)
            """
        )
        connection.commit()


def _legacy_counts(path: Path) -> dict[str, int]:
    with sqlite3.connect(path) as connection:
        return {
            table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in (
                "official_sources",
                "source_snapshots",
                "result_claims",
                "claim_validations",
                "claim_relationships",
                "ingestion_runs",
            )
        }


def _create_versioned_0003_database(path: Path) -> None:
    _create_legacy_database(path)
    config = _alembic_config(_url(path))
    command.stamp(config, "0001_legacy_schema")
    command.upgrade(config, "0003_snapshot_revision_identity")


def _revision_definition(
    *,
    source_name: str,
    source_url: str,
    parser_config: dict[str, object] | None = None,
    status: str = "active",
) -> dict[str, object]:
    return {
        "benchmark_id": "b1",
        "source_name": source_name,
        "source_url": source_url,
        "source_type": "api",
        "officialness_level": "O5",
        "machine_readable": True,
        "requires_auth": False,
        "supports_history": True,
        "update_cadence": None,
        "parser_name": None,
        "parser_version": None,
        "parser_config": parser_config or {},
        "status": status,
        "notes": None,
    }


def _insert_source_revision(
    connection,
    *,
    revision_id: str,
    source_id: str,
    revision_ordinal: int,
    definition: dict[str, object],
    supersedes_revision_id: str | None,
    projection: dict[str, object] | None = None,
) -> None:
    definition_json = json.dumps(definition, sort_keys=True, separators=(",", ":"))
    projection = projection or definition
    connection.execute(
        text(
            """
            INSERT INTO official_source_revisions (
                id, official_source_id, revision_ordinal, definition_hash,
                definition_json, source_name, source_url, source_type,
                officialness_level, machine_readable, requires_auth,
                supports_history, update_cadence, parser_name, parser_version,
                parser_config, status, notes, origin, supersedes_revision_id
            ) VALUES (
                :id, :official_source_id, :revision_ordinal, :definition_hash,
                :definition_json, :source_name, :source_url, :source_type,
                :officialness_level, :machine_readable, :requires_auth,
                :supports_history, :update_cadence, :parser_name, :parser_version,
                :parser_config, :status, :notes, 'test', :supersedes_revision_id
            )
            """
        ),
        {
            "id": revision_id,
            "official_source_id": source_id,
            "revision_ordinal": revision_ordinal,
            "definition_hash": hashlib.sha256(definition_json.encode("utf-8")).hexdigest(),
            "definition_json": definition_json,
            "source_name": projection["source_name"],
            "source_url": projection["source_url"],
            "source_type": projection["source_type"],
            "officialness_level": projection["officialness_level"],
            "machine_readable": projection["machine_readable"],
            "requires_auth": projection["requires_auth"],
            "supports_history": projection["supports_history"],
            "update_cadence": projection["update_cadence"],
            "parser_name": projection["parser_name"],
            "parser_version": projection["parser_version"],
            "parser_config": json.dumps(projection["parser_config"], sort_keys=True, separators=(",", ":")),
            "status": projection["status"],
            "notes": projection["notes"],
            "supersedes_revision_id": supersedes_revision_id,
        },
    )


def _insert_source_decision(connection, *, decision_id: str, revision_id: str, outcome: str) -> None:
    connection.execute(
        text(
            """
            INSERT INTO source_revision_decisions (
                id, source_revision_id, outcome, policy_version, reason_code, basis_json, actor
            ) VALUES (:id, :source_revision_id, :outcome, 'test-v1', 'test_transition', '{}', 'test')
            """
        ),
        {"id": decision_id, "source_revision_id": revision_id, "outcome": outcome},
    )


def test_copy_database_upgrade_preserves_legacy_evidence_and_quarantines_it(tmp_path: Path):
    source = tmp_path / "legacy-source.db"
    candidate = tmp_path / "legacy-copy.db"
    _create_legacy_database(source)
    _backup_sqlite(source, candidate)
    source_sha = _sha256(source)
    before_counts = _legacy_counts(candidate)

    receipt = migrate_legacy_copy(_url(candidate), backup_dir=tmp_path / "backups")

    assert _sha256(source) == source_sha
    assert Path(receipt.backup_path).is_file()
    assert _legacy_counts(Path(receipt.backup_path)) == before_counts
    with sqlite3.connect(receipt.backup_path) as connection:
        assert connection.execute(
            "SELECT score_raw, evidence_location FROM result_claims WHERE id = 'claim-1'"
        ).fetchone() == ("77.0", '{"row":1}')
    assert receipt.from_revision == "0001_legacy_schema"
    assert receipt.to_revision == head_revision()
    status = inspect_database(_url(candidate))
    assert status.kind == "current"
    assert status.integrity_ok
    assert status.foreign_key_violations == 0
    assert _legacy_counts(candidate) == before_counts

    engine = create_engine(_url(candidate))
    with engine.connect() as connection:
        raw = connection.execute(
            text(
                "SELECT model_raw, benchmark_raw, score_raw, evidence_location, capture_status, "
                "source_revision_decision_id, evaluation_version_raw "
                "FROM result_claims WHERE id = 'claim-1'"
            )
        ).one()
        assert raw == (
            "Model Raw One",
            "Bench Raw",
            "77.0",
            '{"row":1}',
            "human_verified",
            None,
            None,
        )
        assert connection.execute(text("SELECT source_revision_id FROM source_snapshots WHERE id = 'snap-1'")).scalar_one()
        assert connection.execute(text("SELECT current_revision_id FROM official_sources WHERE id = 's1'")).scalar_one()
        assert connection.execute(
            text("SELECT outcome, reason_code FROM source_revision_decisions")
        ).one() == ("quarantined", "legacy_unassessed")
        assert connection.execute(
            text("SELECT COUNT(*) FROM claim_review_decisions WHERE outcome = 'needs_review' AND reason_code = 'legacy_unassessed'")
        ).scalar_one() == 2
        assert connection.execute(
            text("SELECT COUNT(*) FROM claim_publication_decisions WHERE outcome = 'quarantined' AND reason_code = 'legacy_unassessed'")
        ).scalar_one() == 2
        assert connection.execute(text("PRAGMA integrity_check")).scalar_one() == "ok"
        assert connection.execute(text("SELECT COUNT(*) FROM pragma_foreign_key_check")).scalar_one() == 0


def test_legacy_inventory_explains_migrated_unassessed_claims_without_rewriting_them(tmp_path: Path):
    source = tmp_path / "legacy-source.db"
    candidate = tmp_path / "legacy-copy.db"
    _create_legacy_database(source)
    _backup_sqlite(source, candidate)
    migrate_legacy_copy(_url(candidate), backup_dir=tmp_path / "backups")
    engine = create_engine(_url(candidate))
    with engine.connect() as connection:
        before = connection.execute(
            text(
                "SELECT COUNT(*), group_concat(score_raw, ',') FROM result_claims ORDER BY id"
            )
        ).one()

    with Session(engine) as session:
        first = build_legacy_inventory_report(session)
        second = build_legacy_inventory_report(session)

    assert canonical_legacy_inventory_json(first) == canonical_legacy_inventory_json(second)
    assert first["availability"] == "report_only"
    assert first["manifest"] == {
        **first["manifest"],
        "claimCount": 2,
        "snapshotCount": 1,
        "candidateClaimCount": 0,
        "excludedClaimCount": 2,
        "conflictedClaimCount": 0,
        "conflictCellCount": 0,
    }
    assert first["summary"]["explicitQuarantineDecisionCount"] == 2
    assert {row["omissionReasonCode"] for row in first["claims"]} == {"SOURCE_DECISION_MISSING"}
    assert all(
        {"LEGACY_UNASSESSED", "PUBLICATION_QUARANTINED"} <= set(row["observedRiskSignals"])
        for row in first["claims"]
    )
    assert [row["raw"]["score"] for row in first["claims"]] == ["77.0", "78.0"]

    with engine.connect() as connection:
        after = connection.execute(
            text(
                "SELECT COUNT(*), group_concat(score_raw, ',') FROM result_claims ORDER BY id"
            )
        ).one()
    assert after == before


def test_copy_database_upgrade_accepts_a_known_0003_revision_without_mutating_its_source(tmp_path: Path):
    source = tmp_path / "v0003-source.db"
    candidate = tmp_path / "v0003-copy.db"
    _create_versioned_0003_database(source)
    _backup_sqlite(source, candidate)
    source_sha = _sha256(source)
    before_counts = _legacy_counts(candidate)

    assert inspect_database(_url(candidate)).kind == "versioned_but_not_head"
    receipt = migrate_legacy_copy(_url(candidate), backup_dir=tmp_path / "backups")

    assert _sha256(source) == source_sha
    assert receipt.from_revision == "0003_snapshot_revision_identity"
    assert receipt.to_revision == head_revision()
    assert _legacy_counts(candidate) == before_counts
    assert inspect_database(_url(candidate)).kind == "current"
    with sqlite3.connect(candidate) as connection:
        assert connection.execute(
            "SELECT registry_managed FROM official_sources WHERE id = 's1'"
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT score_raw, evidence_location, source_revision_decision_id, evaluation_version_raw "
            "FROM result_claims WHERE id = 'claim-1'"
        ).fetchone() == ("77.0", '{"row":1}', None, None)
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert connection.execute("SELECT COUNT(*) FROM pragma_foreign_key_check").fetchone() == (0,)


def test_cli_preflight_accepts_a_known_0003_copy(tmp_path: Path, monkeypatch):
    candidate = tmp_path / "v0003-copy.db"
    _create_versioned_0003_database(candidate)
    monkeypatch.setenv("DATABASE_URL", _url(candidate))
    from app.config import get_settings

    get_settings.cache_clear()
    try:
        result = CliRunner().invoke(app, ["db", "preflight"])
        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["kind"] == "versioned_but_not_head"
        assert payload["revision"] == "0003_snapshot_revision_identity"
        assert payload["integrity_ok"] is True
    finally:
        get_settings.cache_clear()


def test_reseed_after_copy_upgrade_preserves_legacy_claim_snapshot_and_run_history(tmp_path: Path, monkeypatch):
    source = tmp_path / "legacy-source.db"
    candidate = tmp_path / "legacy-copy.db"
    _create_legacy_database(source)
    _backup_sqlite(source, candidate)
    migrate_legacy_copy(_url(candidate), backup_dir=tmp_path / "backups")
    before_counts = _legacy_counts(candidate)
    monkeypatch.setenv("DATABASE_URL", _url(candidate))
    from app.config import get_settings

    get_settings.cache_clear()
    import app.db.engine as engine_module

    engine_module._engine = None
    engine_module._SessionLocal = None
    registry = Path(__file__).resolve().parents[1] / "app" / "registry"
    try:
        with get_session() as session:
            seed_registry(
                session,
                benchmarks_path=registry / "benchmarks.yaml",
                models_path=registry / "models.yaml",
                sources_path=registry / "official_sources.yaml",
            )
        after_counts = _legacy_counts(candidate)
        for evidence_table in (
            "source_snapshots",
            "result_claims",
            "claim_validations",
            "claim_relationships",
            "ingestion_runs",
        ):
            assert after_counts[evidence_table] == before_counts[evidence_table]
        with sqlite3.connect(candidate) as connection:
            assert connection.execute("SELECT COUNT(*) FROM official_sources WHERE id = 's1'").fetchone()[0] == 1
        assert inspect_database(_url(candidate)).kind == "current"
    finally:
        engine_module._engine = None
        engine_module._SessionLocal = None
        get_settings.cache_clear()


def test_preflight_rejects_foreign_key_broken_legacy_database_without_writing(tmp_path: Path):
    candidate = tmp_path / "broken.db"
    _create_legacy_database(candidate)
    with sqlite3.connect(candidate) as connection:
        connection.execute("PRAGMA foreign_keys=OFF")
        connection.execute(
            "INSERT INTO claim_validations (id, result_claim_id, validation_type, outcome) "
            "VALUES ('orphan', 'missing-claim', 'legacy', 'pass')"
        )
        connection.commit()
    before_sha = _sha256(candidate)
    status = inspect_database(_url(candidate))
    assert status.kind == "invalid"
    assert status.foreign_key_violations == 1
    with pytest.raises(DatabaseMigrationError, match="legacy baseline"):
        migrate_legacy_copy(_url(candidate), backup_dir=tmp_path / "backups")
    assert _sha256(candidate) == before_sha


def test_preflight_rejects_unmodelled_legacy_trigger_without_writing(tmp_path: Path):
    candidate = tmp_path / "unexpected-trigger.db"
    _create_legacy_database(candidate)
    with sqlite3.connect(candidate) as connection:
        connection.execute(
            """
            CREATE TRIGGER unexpected_legacy_trigger
            AFTER INSERT ON official_sources
            BEGIN
                SELECT 1;
            END
            """
        )
        connection.commit()
    before_sha = _sha256(candidate)
    status = inspect_database(_url(candidate))
    assert status.kind == "unsupported"
    with pytest.raises(DatabaseMigrationError, match="legacy baseline"):
        migrate_legacy_copy(_url(candidate), backup_dir=tmp_path / "backups")
    assert _sha256(candidate) == before_sha


def test_staged_failure_leaves_the_legacy_copy_unchanged(tmp_path: Path, monkeypatch):
    candidate = tmp_path / "legacy-copy.db"
    _create_legacy_database(candidate)
    before_sha = _sha256(candidate)

    def fail_upgrade(*args, **kwargs):
        raise RuntimeError("injected migration failure")

    monkeypatch.setattr("app.db.migrate.command.upgrade", fail_upgrade)
    with pytest.raises(RuntimeError, match="injected migration failure"):
        migrate_legacy_copy(_url(candidate), backup_dir=tmp_path / "backups")
    assert _sha256(candidate) == before_sha
    assert inspect_database(_url(candidate)).kind == "legacy_unversioned"
    assert list(tmp_path.glob(".*.migrating-*")) == []
    assert list((tmp_path / "backups").glob("*.db"))


def test_atomic_replace_failure_leaves_the_legacy_copy_unchanged(tmp_path: Path, monkeypatch):
    candidate = tmp_path / "legacy-copy.db"
    _create_legacy_database(candidate)
    before_sha = _sha256(candidate)

    def fail_replace(*args, **kwargs):
        raise OSError("injected atomic replace failure")

    monkeypatch.setattr("app.db.migrate.os.replace", fail_replace)
    with pytest.raises(OSError, match="injected atomic replace failure"):
        migrate_legacy_copy(_url(candidate), backup_dir=tmp_path / "backups")
    assert _sha256(candidate) == before_sha
    assert inspect_database(_url(candidate)).kind == "legacy_unversioned"
    assert list(tmp_path.glob(".*.migrating-*")) == []
    assert list((tmp_path / "backups").glob("*.db"))


def test_downgrade_refuses_and_append_only_triggers_preserve_raw_evidence(tmp_path: Path):
    candidate = tmp_path / "legacy-copy.db"
    _create_legacy_database(candidate)
    migrate_legacy_copy(_url(candidate), backup_dir=tmp_path / "backups")
    before_sha = _sha256(candidate)
    with pytest.raises(RuntimeError, match="recovery-only"):
        command.downgrade(_alembic_config(_url(candidate)), "0002_governance_history")
    assert _sha256(candidate) == before_sha

    engine = create_engine(_url(candidate))
    with engine.begin() as connection:
        with pytest.raises(IntegrityError, match="benchmarks identity is immutable"):
            connection.execute(text("UPDATE benchmarks SET id = 'rewritten' WHERE id = 'b1'"))
        with pytest.raises(IntegrityError, match="model_entities identity is immutable"):
            connection.execute(text("UPDATE model_entities SET id = 'rewritten' WHERE id = 'm1'"))
        with pytest.raises(IntegrityError, match="immutable"):
            connection.execute(text("UPDATE result_claims SET score_raw = '999' WHERE id = 'claim-1'"))
        with pytest.raises(IntegrityError, match="identity and creation time"):
            connection.execute(
                text("UPDATE result_claims SET id = 'claim-rewritten' WHERE id = 'claim-1'")
            )
        with pytest.raises(IntegrityError, match="identity and creation time"):
            connection.execute(
                text(
                    "UPDATE result_claims SET created_at = '2099-01-01 00:00:00' "
                    "WHERE id = 'claim-1'"
                )
            )
        with pytest.raises(IntegrityError, match="append a claim review decision"):
            connection.execute(
                text("UPDATE result_claims SET model_entity_id = NULL WHERE id = 'claim-1'")
            )
        with pytest.raises(IntegrityError, match="append a claim review decision"):
            connection.execute(
                text("UPDATE result_claims SET capture_status = 'parser_verified' WHERE id = 'claim-1'")
            )
        with pytest.raises(IntegrityError, match="append-only"):
            connection.execute(text("DELETE FROM source_snapshots WHERE id = 'snap-1'"))
        with pytest.raises(IntegrityError, match="append-only"):
            connection.execute(text("UPDATE source_revision_decisions SET outcome = 'certified'"))
        with pytest.raises(IntegrityError, match="append-only"):
            connection.execute(text("DELETE FROM claim_validations WHERE id = 'validation-1'"))
        with pytest.raises(IntegrityError, match="retained evidence"):
            connection.execute(text("DELETE FROM ingestion_runs WHERE id = 'run-1'"))
        review_id = connection.execute(
            text("SELECT id FROM claim_review_decisions WHERE result_claim_id = 'claim-1'")
        ).scalar_one()
        other_publication_id = connection.execute(
            text("SELECT id FROM claim_publication_decisions WHERE result_claim_id = 'claim-2'")
        ).scalar_one()
        with pytest.raises(IntegrityError, match="linear chain"):
            connection.execute(
                text(
                    """
                    INSERT INTO claim_publication_decisions (
                        id, result_claim_id, claim_review_decision_id, outcome,
                        policy_version, reason_code, basis_json
                    ) VALUES (
                        'publication-second-root', 'claim-1', :review_id, 'quarantined',
                        'test-v1', 'second_root', '{}'
                    )
                    """
                ),
                {"review_id": review_id},
            )
        with pytest.raises(IntegrityError, match="same claim"):
            connection.execute(
                text(
                    """
                    INSERT INTO claim_publication_decisions (
                        id, result_claim_id, claim_review_decision_id, outcome,
                        policy_version, reason_code, basis_json, supersedes_decision_id
                    ) VALUES (
                        'publication-foreign-parent', 'claim-1', :review_id, 'quarantined',
                        'test-v1', 'foreign_parent', '{}', :other_publication_id
                    )
                    """
                ),
                {"review_id": review_id, "other_publication_id": other_publication_id},
            )

    with Session(engine) as session:
        source_revision_id = session.execute(
            text("SELECT id FROM official_source_revisions WHERE official_source_id = 's1'")
        ).scalar_one()
        review_id = session.execute(
            text("SELECT id FROM claim_review_decisions WHERE result_claim_id = 'claim-1'")
        ).scalar_one()
        with pytest.raises(ValueError, match="Source certification is unavailable"):
            repo.append_source_revision_decision(
                session,
                source_revision_id=source_revision_id,
                outcome="certified",
                policy_version="test-v1",
                reason_code="attempted_promotion",
            )
        with pytest.raises(ValueError, match="Official publication approval is unavailable"):
            repo.append_claim_publication_decision(
                session,
                result_claim_id="claim-1",
                claim_review_decision_id=review_id,
                outcome="approved",
                policy_version="test-v1",
                reason_code="attempted_promotion",
            )


def test_source_revision_and_snapshot_links_must_match_the_logical_source(tmp_path: Path):
    candidate = tmp_path / "legacy-copy.db"
    _create_legacy_database(candidate)
    migrate_legacy_copy(_url(candidate), backup_dir=tmp_path / "backups")
    engine = create_engine(_url(candidate))
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO official_sources (
                    id, benchmark_id, source_name, source_url, source_type,
                    officialness_level, machine_readable, requires_auth,
                    supports_history, parser_config, status
                ) VALUES (
                    's2', 'b1', 'Other source', 'https://official.example/other.json', 'api',
                    'O5', 1, 0, 1, '{}', 'active'
                )
                """
            )
        )
        _insert_source_revision(
            connection,
            revision_id="revision-s2",
            source_id="s2",
            revision_ordinal=1,
            definition=_revision_definition(
                source_name="Other source",
                source_url="https://official.example/other.json",
            ),
            supersedes_revision_id=None,
        )
        foreign_parent = connection.execute(
            text(
                "SELECT decision.id FROM source_revision_decisions decision "
                "JOIN official_source_revisions revision "
                "ON revision.id = decision.source_revision_id "
                "WHERE revision.official_source_id = 's1'"
            )
        ).scalar_one()
        with pytest.raises(IntegrityError, match="same source revision"):
            connection.execute(
                text(
                    """
                    INSERT INTO source_revision_decisions (
                        id, source_revision_id, outcome, policy_version, reason_code,
                        basis_json, supersedes_decision_id
                    ) VALUES (
                        'decision-wrong-revision', 'revision-s2', 'quarantined',
                        'test-v1', 'foreign_parent', '{}', :foreign_parent
                    )
                    """
                ),
                {"foreign_parent": foreign_parent},
            )
    with engine.begin() as connection:
        with pytest.raises(
            IntegrityError,
            match="current_revision_id must belong|logical source definition is immutable",
        ):
            connection.execute(text("UPDATE official_sources SET current_revision_id = 'revision-s2' WHERE id = 's1'"))
        with pytest.raises(IntegrityError, match="logical source definition is immutable"):
            connection.execute(
                text("UPDATE official_sources SET source_url = 'https://changed.example/results.json' WHERE id = 's1'")
            )
    with engine.begin() as connection:
        with pytest.raises(IntegrityError, match="snapshot source revision must belong"):
            connection.execute(
                text(
                    """
                    INSERT INTO source_snapshots (
                        id, official_source_id, source_revision_id, raw_content_uri,
                        content_hash, fetch_metadata
                    ) VALUES (
                        'snap-wrong', 's1', 'revision-s2', 'file:///snapshots/wrong.json',
                        'cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc', '{}'
                    )
                    """
                )
            )


def test_source_projection_requires_a_valid_successor_and_governance_decision(tmp_path: Path):
    candidate = tmp_path / "legacy-copy.db"
    _create_legacy_database(candidate)
    migrate_legacy_copy(_url(candidate), backup_dir=tmp_path / "backups")
    engine = create_engine(_url(candidate))

    with engine.connect() as connection:
        revision_one = connection.execute(
            text("SELECT current_revision_id FROM official_sources WHERE id = 's1'")
        ).scalar_one()

    definition_two = _revision_definition(
        source_name="Legacy source",
        source_url="https://official.example/results-v2.json",
        parser_config={"adapter": "legacy"},
    )
    with engine.begin() as connection:
        _insert_source_revision(
            connection,
            revision_id="revision-two",
            source_id="s1",
            revision_ordinal=2,
            definition=definition_two,
            supersedes_revision_id=revision_one,
        )
        mismatched_definition = _revision_definition(
            source_name="Legacy source",
            source_url="https://official.example/definition-only.json",
            parser_config={"adapter": "legacy"},
        )
        with pytest.raises(IntegrityError, match="definition must match"):
            _insert_source_revision(
                connection,
                revision_id="revision-mismatched",
                source_id="s1",
                revision_ordinal=3,
                definition=mismatched_definition,
                projection=definition_two,
                supersedes_revision_id=revision_one,
            )

    with engine.begin() as connection:
        with pytest.raises(IntegrityError, match="logical source definition is immutable"):
            connection.execute(
                text(
                    "UPDATE official_sources SET source_url = :source_url, current_revision_id = 'revision-two' "
                    "WHERE id = 's1'"
                ),
                {"source_url": definition_two["source_url"]},
            )

    with engine.begin() as connection:
        _insert_source_decision(
            connection,
            decision_id="decision-two",
            revision_id="revision-two",
            outcome="quarantined",
        )
        connection.execute(
            text(
                "UPDATE official_sources SET source_url = :source_url, current_revision_id = 'revision-two' "
                "WHERE id = 's1'"
            ),
            {"source_url": definition_two["source_url"]},
        )
        with pytest.raises(IntegrityError, match="source_snapshots is append-only"):
            connection.execute(
                text(
                    "UPDATE source_snapshots SET source_revision_id = 'revision-two' "
                    "WHERE id = 'snap-1'"
                )
            )

    with engine.begin() as connection:
        with pytest.raises(IntegrityError, match="logical source definition is immutable"):
            connection.execute(
                text(
                    "UPDATE official_sources SET source_url = 'https://official.example/results.json', "
                    "current_revision_id = :revision_one WHERE id = 's1'"
                ),
                {"revision_one": revision_one},
            )

    low_ordinal_definition = _revision_definition(
        source_name="Legacy source",
        source_url="https://official.example/lower-ordinal.json",
        parser_config={"adapter": "legacy"},
    )
    with engine.begin() as connection:
        _insert_source_revision(
            connection,
            revision_id="revision-low",
            source_id="s1",
            revision_ordinal=0,
            definition=low_ordinal_definition,
            supersedes_revision_id="revision-two",
        )
        _insert_source_decision(
            connection,
            decision_id="decision-low",
            revision_id="revision-low",
            outcome="quarantined",
        )
        with pytest.raises(IntegrityError, match="logical source definition is immutable"):
            connection.execute(
                text(
                    "UPDATE official_sources SET source_url = :source_url, current_revision_id = 'revision-low' "
                    "WHERE id = 's1'"
                ),
                {"source_url": low_ordinal_definition["source_url"]},
            )

    retired_definition = _revision_definition(
        source_name="Legacy source",
        source_url="https://official.example/results-v2.json",
        parser_config={"adapter": "legacy"},
        status="retired",
    )
    with engine.begin() as connection:
        _insert_source_revision(
            connection,
            revision_id="revision-retired",
            source_id="s1",
            revision_ordinal=3,
            definition=retired_definition,
            supersedes_revision_id="revision-two",
        )
        with pytest.raises(IntegrityError, match="logical source definition is immutable"):
            connection.execute(
                text(
                    "UPDATE official_sources SET status = 'retired', current_revision_id = 'revision-retired' "
                    "WHERE id = 's1'"
                )
            )
        _insert_source_decision(
            connection,
            decision_id="decision-retired",
            revision_id="revision-retired",
            outcome="revoked",
        )
        connection.execute(
            text(
                "UPDATE official_sources SET status = 'retired', current_revision_id = 'revision-retired' "
                "WHERE id = 's1'"
            )
        )


def test_init_db_refuses_a_populated_unversioned_ledger(tmp_path: Path):
    candidate = tmp_path / "legacy.db"
    _create_legacy_database(candidate)
    before_sha = _sha256(candidate)
    with pytest.raises(DatabaseMigrationError, match="init-db only initializes an empty database"):
        init_db(_url(candidate))
    assert _sha256(candidate) == before_sha
