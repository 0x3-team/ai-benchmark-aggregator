from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat

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
    _backup_sqlite as _production_backup_sqlite,
    DatabaseMigrationError,
    head_revision,
    initialize_database,
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


def _predict_backup_path(source: Path, backup_dir: Path) -> Path:
    """Derive the deterministic pre-migration backup filename for a source."""
    return (
        backup_dir.expanduser().resolve()
        / f"{source.stem}.pre-migration.{_sha256(source)[:16]}.db"
    )


def test_migration_refuses_backup_write_when_a_dangling_symlink_is_planted(tmp_path: Path):
    """A dangling symlink at a predictable backup name must never redirect it."""
    source = tmp_path / "legacy-source.db"
    candidate = tmp_path / "legacy-copy.db"
    _create_legacy_database(source)
    _backup_sqlite(source, candidate)

    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    planned = _predict_backup_path(candidate, backup_dir)
    attacker_target = tmp_path / "attacker-owned.sqlite3"
    planned.symlink_to(attacker_target)
    source_sha = _sha256(source)

    with pytest.raises(DatabaseMigrationError):
        migrate_legacy_copy(_url(candidate), backup_dir=backup_dir)

    assert Path(planned).is_symlink()
    assert not attacker_target.exists()
    # The source copy must be byte-identical before and after the refused backup;
    # the defender never writes through the planted symlink to the attacker target.
    assert _sha256(source) == source_sha
    assert not attacker_target.exists()


def test_backup_destination_symlink_is_refused_and_attacker_is_never_written(
    tmp_path: Path,
):
    """A planted final-destination symlink is refused without touching the attacker.

    Non-vacuous deterministic adversarial test: the attacker evidence (the
    ``attacker_target`` the planted destination symlink points at) is created up
    front as a sentinel and is never deleted.  The backup is run once against a
    ``final.db`` that is a symlink to that target.  Whichever branch the
    production path takes — refusal at the pre-check or refusal at the
    descriptor-relative no-replace publish — the assertion that the attacker
    target was never opened or written is checked on the surviving evidence
    (never on a deleted file).
    """
    import os

    from app.db.migrate import _backup_sqlite as production_backup

    source = tmp_path / "legacy-source.db"
    _create_legacy_database(source)
    source_sha = _sha256(source)

    # Attacker evidence is established up front and persists for the whole test.
    attacker_target = tmp_path / "attacker-owned.sqlite3"
    attacker_target.write_bytes(b"attacker-owned sentinel; must never change")
    attacker_sentinel = attacker_target.read_bytes()

    dest = tmp_path / "final.db"
    os.symlink(attacker_target, dest)  # final path is a planted symlink to attacker
    assert dest.is_symlink()

    with pytest.raises(DatabaseMigrationError):
        production_backup(source, dest)

    # Very soft zero-assert: the symlink must survive, and the attacker target
    # must still hold exactly its sentinel — proving publication never wrote
    # through the symlink and never replaced the symlink.
    assert dest.is_symlink()
    assert attacker_target.read_bytes() == attacker_sentinel
    assert _sha256(source) == source_sha


def test_bounded_replace_uses_one_held_directory_for_both_operands(
    tmp_path: Path, monkeypatch
):
    """Both the source and destination resolve inside the same held no-follow dir.

    ``migrate_legacy_copy`` finalizes by renaming a *staged sibling* over the
    database path, so ``_bounded_replace`` must insist both operands share one
    lexical parent and drive the rename from a single ``O_NOFOLLOW`` descriptor
    used as both ``src_dir_fd`` and ``dst_dir_fd``.  That is what makes a real
    directory swap between opens unable to redirect the result: there is no
    second open to be diverted.  This test proves the single-fd property by
    recording the descriptor arguments ``os.replace`` is invoked with.
    """
    import os

    from app.db.migrate import _bounded_replace

    parent = tmp_path / "parent"
    parent.mkdir()
    src = parent / "staged.db"
    src.write_bytes(b"stage-bytes")
    dst = parent / "final.db"

    calls: list[tuple] = []
    real_replace = os.replace

    def recording_replace(src_name, dst_name, *, src_dir_fd, dst_dir_fd):
        calls.append((src_name, dst_name, src_dir_fd, dst_dir_fd))
        real_replace(src_name, dst_name, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd)

    monkeypatch.setattr("app.db.migrate.os.replace", recording_replace)
    _bounded_replace(src, dst)

    assert dst.read_bytes() == b"stage-bytes"
    assert not src.exists()
    # Exactly one replace call, and both operand fds are the same held descriptor.
    assert len(calls) == 1
    src_name, dst_name, src_fd, dst_fd = calls[0]
    assert src_fd == dst_fd
    assert src_name == "staged.db"
    assert dst_name == "final.db"


def test_bounded_replace_requires_a_shared_parent(tmp_path: Path):
    """Different lexical parents must be refused outright."""
    from app.db.migrate import _bounded_replace

    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    (a / "staged.db").write_bytes(b"x")
    with pytest.raises(DatabaseMigrationError, match="share the same parent"):
        _bounded_replace(a / "staged.db", b / "final.db")


def test_bounded_replace_refuses_a_shared_parent_that_is_a_symlink(tmp_path: Path):
    """A symlink planted at the shared parent redirects nothing; it is refused.

    Because both operands resolve inside one held no-follow directory, the only
    parent-name attack left open is swapping the shared parent name to a
    symlink.  The ``O_NOFOLLOW`` open refuses that, leaving the attacker
    directory untouched.  The attacker evidence is created up front and never
    deleted.
    """
    import os

    from app.db.migrate import _bounded_replace

    attacker_dir = tmp_path / "attacker-dir"
    attacker_dir.mkdir()
    attacker_dir.joinpath("sentinel.txt").write_text("attacker-owned")
    parent = tmp_path / "parent"
    os.symlink(attacker_dir, parent, target_is_directory=True)  # shared parent is symlink
    src = parent / "staged.db"  # both under the symlink-named parent
    dst = parent / "final.db"

    with pytest.raises(DatabaseMigrationError, match="must be a regular non-symlink"):
        _bounded_replace(src, dst)

    assert [p.name for p in attacker_dir.iterdir()] == ["sentinel.txt"]
    assert (attacker_dir / "sentinel.txt").read_text() == "attacker-owned"


def test_bounded_replace_finalizes_into_the_selected_parent(tmp_path: Path):
    """The shared-parent replace finalizes normally on the success path."""
    from app.db.migrate import _bounded_replace

    parent = tmp_path / "parent"
    parent.mkdir()
    src = parent / "staged.db"
    src.write_bytes(b"stage-bytes")
    dest = parent / "final.db"
    _bounded_replace(src, dest)
    assert dest.read_bytes() == b"stage-bytes"
    assert not src.exists()


def test_migrate_fails_closed_when_the_source_drifts_after_admission(
    tmp_path: Path, monkeypatch
):
    """A source content drift after admission must abort before any replacement.

    ``migrate_legacy_copy`` admits the source by snapshotting it once through a
    single pinned descriptor (``_admit_and_snapshot``), binding ``input_sha256``
    to those exact bytes.  If the *live* source drifts after that snapshot, the
    final pre-replacement identity re-check must fail closed: we never replace a
    database that has drifted away from the admitted source.  We inject a content
    drift (in-place append, so dev/ino stay constant while the hash changes) at
    the admission seam and assert no replacement is produced.
    """
    from app.db.migrate import _admit_and_snapshot, migrate_legacy_copy

    candidate = tmp_path / "legacy-copy.db"
    _create_legacy_database(candidate)

    real_admit = _admit_and_snapshot
    drift = {"applied": False}

    def drifting_admit(source, *, expected_identity=None):
        identity, snapshot, staging = real_admit(
            source, expected_identity=expected_identity
        )
        if not drift["applied"]:
            # On the migration's FIRST admission, append trailing bytes to the
            # LIVE source so the final identity re-check sees drifted content.
            drift["applied"] = True
            with open(source, "ab") as stream:
                stream.write(b"\0" * 4096)
                stream.flush()
        return identity, snapshot, staging

    monkeypatch.setattr(
        "app.db.migrate._admit_and_snapshot", drifting_admit
    )

    with pytest.raises(DatabaseMigrationError, match="drifted|changed"):
        migrate_legacy_copy(_url(candidate), backup_dir=tmp_path / "backups")

    assert drift["applied"]
    # No staged replacement survived, and the live source was not overwritten.
    assert list(tmp_path.glob(".*.migrating-*")) == []


def test_migrate_fails_closed_when_the_source_inode_is_replaced_after_admission(
    tmp_path: Path, monkeypatch
):
    """An inode replacement after admission fails closed before replacement.

    We plant a different, still-valid legacy database in the live source path at
    the admission seam, so the final pre-replacement identity check observes the
    foreign inode and aborts — never replacing with a database built from a
    source the operator did not admit.
    """
    from app.db.migrate import _admit_and_snapshot, migrate_legacy_copy

    candidate = tmp_path / "legacy-copy.db"
    _create_legacy_database(candidate)

    # A different, valid legacy database with a distinguishable row, so it is a
    # distinct inode AND distinct content from the admitted source.
    impostor = tmp_path / "impostor.db"
    _create_legacy_database(impostor)
    import sqlite3 as _s
    with _s.connect(impostor) as c:
        c.execute("UPDATE result_claims SET score_raw='99' WHERE id='claim-1'")
        c.commit()
    assert os.stat(impostor).st_ino != os.stat(candidate).st_ino

    real_admit = _admit_and_snapshot
    swapped = {"done": False}

    def switching_admit(source, *, expected_identity=None):
        identity, snapshot, staging = real_admit(
            source, expected_identity=expected_identity
        )
        if not swapped["done"]:
            # On the migration's FIRST admission, replace the live source path
            # with the impostor so the final identity check sees a foreign inode.
            swapped["done"] = True
            os.replace(str(impostor), str(candidate))
        return identity, snapshot, staging

    monkeypatch.setattr("app.db.migrate._admit_and_snapshot", switching_admit)

    with pytest.raises(DatabaseMigrationError, match="drifted|changed"):
        migrate_legacy_copy(_url(candidate), backup_dir=tmp_path / "backups")

    assert swapped["done"]
    assert list(tmp_path.glob(".*.migrating-*")) == []


def test_backup_and_staged_copies_are_bound_to_the_admitted_snapshot(
    tmp_path: Path,
):
    """Criterion 1/2: backup bytes equal the admitted bytes, never a live-path swap.

    Deterministic swap-and-keep: after the source is admitted and snapshotted,
    the *live source path* is replaced with an attacker-controlled database and
    kept swapped.  The pre-migration backup must still be produced from the
    immutable admitted snapshot (proving it never re-opens the live path), so its
    bytes carry the admitted legacy claim, not the attacker's rewritten value.  A
    post-admission source swap therefore cannot change what is backed up or later
    staged.
    """
    from app.db.migrate import (
        _backup_sqlite as _production_backup_sqlite,
        _immutable_source_snapshot,
        _source_identity,
        DatabaseMigrationError,
    )

    candidate = tmp_path / "legacy-copy.db"
    _create_legacy_database(candidate)
    admitted = _source_identity(candidate)

    attacker = tmp_path / "attacker.db"
    _create_legacy_database(attacker)
    with sqlite3.connect(attacker) as c:
        c.execute("UPDATE result_claims SET score_raw='99' WHERE id='claim-1'")
        c.commit()
    attacker_bytes = attacker.read_bytes()

    # Snapshot the admitted bytes once, under the admitted identity.
    snapshot, admit_staging = _immutable_source_snapshot(
        candidate, expected_identity=admitted
    )
    try:
        assert snapshot.read_bytes() == candidate.read_bytes()
        admitted_sha = _sha256(snapshot)

        # Deterministic post-admission swap: replace the LIVE source path with
        # the attacker DB and keep it swapped.
        os.replace(str(attacker), str(candidate))
        assert _sha256(candidate) != admitted_sha  # live path is now the attacker

        # The backup is produced from the immutable snapshot, never the live
        # path, so it must preserve the admitted claim (77.0), not the attacker's
        # (99.0), and must not be the attacker bytes.
        backup = tmp_path / "pre-migration-admitted.db"
        _production_backup_sqlite(snapshot, backup)
        with sqlite3.connect(backup) as b:
            score = b.execute(
                "SELECT score_raw FROM result_claims WHERE id='claim-1'"
            ).fetchone()[0]
        assert score == "77.0"
        assert backup.read_bytes() != attacker_bytes

        # Re-admitting the (now-swapped) live path under the admitted identity
        # must fail closed: it is the attacker, which no longer matches.
        with pytest.raises(DatabaseMigrationError):
            _immutable_source_snapshot(candidate, expected_identity=admitted)
    finally:
        import shutil

        shutil.rmtree(admit_staging, ignore_errors=True)


def test_backup_staging_is_cleaned_up_after_refusal(tmp_path: Path):
    """A refused or failed backup must not leak a staging directory in the final dir."""
    import os

    source = tmp_path / "legacy-source.db"
    _create_legacy_database(source)

    def _staging_dirs() -> list[str]:
        return sorted(
            name for name in os.listdir(tmp_path) if name.startswith(".ledger-backup-")
        )

    # Refusal path: destination already exists -> must not leak staging.
    dest = tmp_path / "final.db"
    dest.write_bytes(b"operator-owned sentinel; do not overwrite")
    assert _staging_dirs() == []
    with pytest.raises(DatabaseMigrationError):
        _production_backup_sqlite(source, dest)
    assert dest.read_bytes() == b"operator-owned sentinel; do not overwrite"
    assert _staging_dirs() == []

    # Clean destination on the same parent: success publishes and removes staging.
    clean = tmp_path / "clean.db"
    _production_backup_sqlite(source, clean)
    assert clean.is_file()
    assert _staging_dirs() == []


def test_migration_backup_refuses_pre_existing_regular_destination(tmp_path: Path):
    """A pre-existing regular file at the backup name is refused unchanged."""
    source = tmp_path / "legacy-source.db"
    candidate = tmp_path / "legacy-copy.db"
    _create_legacy_database(source)
    _backup_sqlite(source, candidate)

    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    planned = _predict_backup_path(candidate, backup_dir)
    planned.write_bytes(b"operator-owned sentinel; do not overwrite")
    sentinel = planned.read_bytes()

    with pytest.raises(DatabaseMigrationError):
        migrate_legacy_copy(_url(candidate), backup_dir=backup_dir)
    assert planned.read_bytes() == sentinel


def test_copy_database_upgrade_preserves_legacy_evidence_and_quarantines_it(tmp_path: Path):
    source = tmp_path / "legacy-source.db"
    candidate = tmp_path / "legacy-copy.db"
    _create_legacy_database(source)
    _backup_sqlite(source, candidate)
    source_sha = _sha256(source)
    before_counts = _legacy_counts(candidate)
    candidate_at_admission_hash = _sha256(candidate)

    receipt = migrate_legacy_copy(_url(candidate), backup_dir=tmp_path / "backups")

    # output_sha256 must describe the post-migration database bytes actually
    # installed at the candidate path — not the input.  For this known migration
    # the bytes are known to change, so the inequality is a legitimate test
    # expectation here (it is not a runtime contract in production).
    assert Path(receipt.backup_path).is_file()
    assert receipt.input_sha256 == candidate_at_admission_hash
    assert receipt.output_sha256 == _sha256(candidate)
    assert receipt.output_sha256 != receipt.input_sha256
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


def test_copy_upgrade_projects_exact_textual_false_as_false(tmp_path: Path):
    """Finding 11 regression: literal ``'false'`` must be false, not True.

    ``bool(value)`` corrupts the immutable source-revision identity because
    ``bool("false") is True``.  A legacy source carrying the canonical text
    ``'false'`` (with or without surrounding whitespace) must project to the
    integer 0 in both the column and the definition hash, never to a truthy
    value.
    """
    source = tmp_path / "legacy-text-false.db"
    candidate = tmp_path / "legacy-copy.db"
    _create_legacy_database(source)
    with sqlite3.connect(source) as connection:
        connection.execute(
            "UPDATE official_sources SET "
            "machine_readable = 'false', requires_auth = ' true ', supports_history = 'FALSE' "
            "WHERE id = 's1'"
        )
        connection.commit()
    _backup_sqlite(source, candidate)
    source_sha = _sha256(source)

    migrate_legacy_copy(_url(candidate), backup_dir=tmp_path / "backups")

    assert _sha256(source) == source_sha
    with sqlite3.connect(candidate) as connection:
        assert connection.execute(
            "SELECT machine_readable, requires_auth, supports_history "
            "FROM official_source_revisions WHERE official_source_id = 's1'"
        ).fetchone() == (0, 1, 0)


def test_strict_legacy_boolean_rejects_ambiguous_lexemes_without_mutating_source(tmp_path: Path):
    """Finding 11 regression: ambiguous legacy values abort the staged copy.

    ``yes``/``no``/``on``/``off``/``not-sure``, non-canonical numbers, and null
    must be rejected by the strict legacy-boolean parser.  The rejection aborts
    the staged copy migration; the operator's source and the candidate copy are
    left byte-identical.
    """
    for lexeme in ("yes", "no", "on", "off", "not-sure", "2", "-1"):
        stem = "".join(ch if ch not in "/-. " else "_" for ch in lexeme)
        source = tmp_path / f"source-{stem}.db"
        candidate = tmp_path / f"copy-{stem}.db"
        _create_legacy_database(source)
        with sqlite3.connect(source) as connection:
            connection.execute(
                "UPDATE official_sources SET machine_readable = ? WHERE id = 's1'",
                (lexeme,),
            )
            connection.commit()
        _backup_sqlite(source, candidate)
        source_sha = _sha256(source)
        candidate_sha = _sha256(candidate)

        with pytest.raises(ValueError, match="machine_readable|strict"):
            migrate_legacy_copy(_url(candidate), backup_dir=tmp_path / "backups")

        assert _sha256(source) == source_sha
        assert _sha256(candidate) == candidate_sha


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
    candidate_at_admission_hash = _sha256(candidate)

    assert inspect_database(_url(candidate)).kind == "versioned_but_not_head"
    receipt = migrate_legacy_copy(_url(candidate), backup_dir=tmp_path / "backups")

    assert _sha256(source) == source_sha
    assert receipt.input_sha256 == candidate_at_admission_hash
    assert receipt.output_sha256 == _sha256(candidate)
    assert receipt.output_sha256 != receipt.input_sha256
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
    # The real model tree carries cross-file duplicate model IDs that the loader
    # now rejects before any write. This test exercises idempotent reseeding of
    # a legacy-copied database (evidence preservation), not the live model
    # manifest, so a collision-free copy of the base model file is used.
    models_path = tmp_path / "models.yaml"
    models_path.write_text((registry / "models.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    try:
        with get_session() as session:
            seed_registry(
                session,
                benchmarks_path=registry / "benchmarks.yaml",
                models_path=models_path,
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
    with pytest.raises(DatabaseMigrationError, match="could not be completed safely"):
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


def test_initialize_fresh_sqlite_creates_only_the_selected_missing_parent(tmp_path: Path):
    selected_parent = tmp_path / "selected-parent"
    database_path = selected_parent / "ledger.db"

    assert initialize_database(_url(database_path)).kind == "current"

    assert selected_parent.is_dir()
    assert sorted(path.name for path in tmp_path.iterdir()) == ["selected-parent"]
    assert database_path.is_file()


def test_initialize_sqlite_refuses_a_missing_parent_below_a_symlink(tmp_path: Path):
    """A missing parent reachable only through a symlink ancestor is refused.

    ``init-db`` must never "fix" a database path by walking through a symlinked
    ancestor into a directory the operator did not truly select; the grandparent
    (the traversal base for the one created parent) is a symlink here, so no
    parent directory is created at all.
    """
    import os
    import stat

    real_target = tmp_path / "real-target"
    real_target.mkdir()
    link_ancestor = tmp_path / "link-ancestor"
    os.symlink(real_target, link_ancestor)
    # database path is real_target/child/ledger.db via the symlinked ancestor.
    database_path = link_ancestor / "child" / "ledger.db"

    with pytest.raises(DatabaseMigrationError):
        initialize_database(_url(database_path))

    # The attacker-visible real target must be untouched and no child created
    # anywhere.
    assert sorted(path.name for path in real_target.iterdir()) == []
    assert not (real_target / "child").exists()
    assert not (link_ancestor / "child").exists()


def test_initialize_sqlite_refuses_two_level_missing_parent(tmp_path: Path):
    """init-db creates at most one selected parent and refuses a deeper gap."""
    database_path = tmp_path / "a" / "b" / "ledger.db"

    with pytest.raises(DatabaseMigrationError):
        initialize_database(_url(database_path))

    assert not (tmp_path / "a").exists()
    assert not database_path.exists()


def test_initialize_sqlite_refuses_an_existing_parent_reached_through_a_symlink_ancestor(
    tmp_path: Path,
):
    """An already-existing parent reached through any symlink ancestor is refused.

    The fail-closed component walk must reject the path even when the immediate
    parent *already exists* — because an ancestor component is a symlink into a
    directory the operator did not select.  Previously only a *missing* parent
    below a symlink was refused; this closes the existing-parent case with the
    same no-follow walk and proves no database file or external directory is
    mutated.
    """
    real_target = tmp_path / "real-target"
    real_target.mkdir()
    link_ancestor = tmp_path / "link-ancestor"
    os.symlink(real_target, link_ancestor)
    # The immediate parent exists *and* holds a pre-existing file; only the
    # symlink ancestor makes the path unacceptable.
    existing_parent = link_ancestor / "existing-parent"
    existing_parent.mkdir()
    preexisting = existing_parent / "pre-existing.sqlite3"
    preexisting.write_bytes(b"operator-owned sentinel; never touch")

    with pytest.raises(DatabaseMigrationError):
        initialize_database(_url(existing_parent / "ledger.db"))

    # Nothing was ever written through the symlink: no new database, and the
    # pre-existing sentinel in the symlink-reached directory is untouched.
    assert not (real_target / "existing-parent" / "ledger.db").exists()
    assert preexisting.read_bytes() == b"operator-owned sentinel; never touch"
    # The only directory created under the symlink target is the pre-existing one
    # we planted for the test (nothing extra was written through the symlink).
    assert sorted(path.name for path in real_target.iterdir()) == ["existing-parent"]
    assert sorted(path.name for path in (real_target / "existing-parent").iterdir()) == [
        "pre-existing.sqlite3"
    ]


def test_initialize_sqlite_accepts_an_existing_parent_with_real_ancestors(
    tmp_path: Path,
):
    """A normal existing parent with no symlink ancestors is accepted."""
    parent = tmp_path / "good-parent"
    parent.mkdir()
    assert initialize_database(_url(parent / "ledger.db")).kind == "current"
    assert (parent / "ledger.db").is_file()


def test_initialize_sqlite_handles_a_relative_sqlite_path_without_rejecting_it(
    tmp_path: Path, monkeypatch
):
    """A supported relative parent path is validated, not blanket-rejected.

    The component walk must not rely on a resolve-equality shortcut that would
    reject every relative path.  With the working directory rooted at a real,
    symlink-free tmp location, an existing relative parent is accepted.
    """
    top = tmp_path / "rel"
    top.mkdir()
    parent = top / "rparent"
    parent.mkdir()
    monkeypatch.chdir(top)
    # sqlite:///rparent/ledger.db -- relative database path anchored at cwd.
    assert initialize_database("sqlite:///rparent/ledger.db").kind == "current"
    assert (parent / "ledger.db").is_file()


def test_sqlite_parent_walk_does_not_leak_directory_descriptors(tmp_path: Path):
    """The component walk must not leak any directory fd across exits.

    ``_ensure_sqlite_missing_parent`` holds exactly one directory descriptor per
    step of the descent and closes every descriptor it opens on all exit paths
    (existing parent, single-parent creation, and refusal).  This proves the
    bound: the open-fd count over a long loop is unchanged, so no walk leaks.
    Only callable where an fd count is observable (``/dev/fd`` on darwin/linux).
    """
    import os

    from app.db.migrate import _ensure_sqlite_missing_parent

    fd_dir = "/dev/fd"
    if not os.path.isdir(fd_dir):
        return  # not observable here; the walk logic still runs elsewhere

    base = tmp_path / "leakbase"

    import shutil

    def run_all() -> None:
        # Recreate the base so each iteration exercises creation from scratch.
        shutil.rmtree(base, ignore_errors=True)
        base.mkdir()
        # Existing multi-component parent.
        (base / "a" / "b" / "c").mkdir(parents=True)
        _ensure_sqlite_missing_parent(f"sqlite:///{base}/a/b/c/db.sqlite3")
        # Single-parent creation.
        _ensure_sqlite_missing_parent(f"sqlite:///{base}/single/db.sqlite3")
        # Refusal (two-level gap).
        try:
            _ensure_sqlite_missing_parent(f"sqlite:///{base}/x/y/z/db.sqlite3")
        except DatabaseMigrationError:
            pass

    before = len(os.listdir(fd_dir))
    for _ in range(150):
        run_all()
    after = len(os.listdir(fd_dir))
    assert after == before, f"directory fd leaked across walks: {before} -> {after}"


def test_full_migrate_swap_and_restore_never_smuggles_attacker_bytes(
    tmp_path: Path, monkeypatch
):
    """Deterministic full-flow swap/read/restore on migrate_legacy_copy.

    The admitted source (score 77.0) is snapshotted through a single pinned
    descriptor via ``_admit_and_snapshot``.  We then deterministically attack
    EVERY byte-producing backup/staged read at the
    ``_open_admitted_source_connection`` seam: before the read opens, the live
    candidate is overwritten in place (same dev/ino) with an attacker database
    (score 99.0), and the attacker bytes STAY in that same live inode for the
    *entire* ``source_connection.backup(destination_connection)`` read window.
    The original admitted bytes are restored only after backup completes,
    before the final live-path identity re-check.  Production reads every
    backup and staged byte from the immutable snapshot, never the live path, so
    the migrated result and the retained verified backup must both carry the
    admitted value 77.0 and must never contain the attacker's 99.0.

    An exact counter asserts both byte-producing reads (backup + staged) were
    each attacked and each restored (and no extra attack that could mask a
    missed route), keeping the seam non-vacuous: a vulnerable live-path route
    captures the attacker bytes for the whole read window and would surface
    99.0.  This matches the delayed-restore correction from the independent
    mutation review.
    """
    from app.db.migrate import (
        _open_admitted_source_connection,
        migrate_legacy_copy,
    )
    import app.db.migrate as _migrate

    candidate = tmp_path / "legacy-copy.db"
    _create_legacy_database(candidate)
    original_bytes = candidate.read_bytes()
    original_inode = os.stat(candidate).st_ino

    attacker = tmp_path / "attacker.db"
    _create_legacy_database(attacker)
    with sqlite3.connect(attacker) as c:
        c.execute("UPDATE result_claims SET score_raw='99' WHERE id='claim-1'")
        c.commit()
    attacker_bytes = attacker.read_bytes()
    assert attacker_bytes != original_bytes

    real_seam = _open_admitted_source_connection
    # Exact counters: 2 byte-producing reads (backup then staged), each swapped
    # and restored exactly once.  Anything else means a route was not attacked.
    calls = {"seams": 0, "swaps": 0, "restores": 0}

    class _RestoringConnection:
        """Delegate to the real connection but restore the live candidate on exit."""

        def __init__(self, real, restore):
            self._real = real
            self._restore = restore

        def __enter__(self):
            self._real.__enter__()
            return self

        def __exit__(self, *exc):
            # Restore only after the ``with`` body (the backup read window) has
            # fully completed.  This is the fix that makes the seam non-vacuous.
            try:
                return self._real.__exit__(*exc)
            finally:
                self._restore()

        def backup(self, dest):
            return self._real.backup(dest)

        def __getattr__(self, name):
            return getattr(self._real, name)

    def attacking_seam(path):
        # Swap the attacker bytes into the live candidate in place (same inode)
        # and LEAVE them there for the entire backup read window.
        calls["seams"] += 1
        with open(candidate, "r+b") as fh:
            fh.write(attacker_bytes)
            fh.truncate(len(attacker_bytes))
            fh.flush()
            os.fsync(fh.fileno())
        calls["swaps"] += 1

        def restore():
            with open(candidate, "r+b") as fh:
                fh.write(original_bytes)
                fh.truncate(len(original_bytes))
                fh.flush()
                os.fsync(fh.fileno())
            calls["restores"] += 1

        # Open whatever path production asked to read.  If it asks for the
        # immutable snapshot, the backup gets the 77.0 snapshot (defense).  If a
        # mutation routes it back to the live candidate, the backup reads the
        # attacker bytes still in the inode (99.0), the load-bearing defect.
        return _RestoringConnection(real_seam(path), restore)

    monkeypatch.setattr(_migrate, "_open_admitted_source_connection", attacking_seam)
    # The admitted live inode is the source the migration will validate against;
    # the swap/restore must not have replaced it (the attacker in-place rewrite
    # keeps it constant).  Note the final candidate inode legitimately differs
    # after the atomic ``_bounded_replace`` publishes the newly migrated staged
    # file, so this equality is checked here, before the migration.
    assert os.stat(candidate).st_ino == original_inode

    receipt = migrate_legacy_copy(_url(candidate), backup_dir=tmp_path / "backups")

    # Exact counter: exactly two byte-producing reads (backup + staged) were
    # each attacked and each restored.
    assert calls["seams"] == 2, calls
    assert calls["swaps"] == 2, calls
    assert calls["restores"] == 2, calls
    # Migrated result carries the admitted claim, never the attacker's.
    with sqlite3.connect(candidate) as c:
        score = c.execute(
            "SELECT score_raw FROM result_claims WHERE id='claim-1'"
        ).fetchone()[0]
    assert score == "77.0"
    # The retained verified backup also carries the admitted claim, never the
    # attacker's, and is not the attacker database.
    backup = Path(receipt.backup_path)
    assert backup.is_file()
    with sqlite3.connect(backup) as c:
        backup_score = c.execute(
            "SELECT score_raw FROM result_claims WHERE id='claim-1'"
        ).fetchone()[0]
    assert backup_score == "77.0"
    assert backup.read_bytes() != attacker_bytes
