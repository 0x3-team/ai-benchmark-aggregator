from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from sqlalchemy import func, select

from app.db import models, repositories as repo
from app.db.engine import get_session
from app.ingestion.runner import run_ingestion
from app.registry.seed_loader import seed_registry


FIXTURE = Path(__file__).parent / "fixtures" / "fake_source.json"


def _count(session, model) -> int:
    return session.scalar(select(func.count()).select_from(model)) or 0


def _source_count(session, source_id: str) -> int:
    return (
        session.scalar(
            select(func.count())
            .select_from(models.OfficialSourceRevision)
            .where(models.OfficialSourceRevision.official_source_id == source_id)
        )
        or 0
    )


def _source_payload(
    source_id: str,
    *,
    source_url: str,
    parser_config: dict[str, object] | None = None,
    status: str = "active",
    notes: str | None = "fixture source",
) -> dict[str, object]:
    return {
        "id": source_id,
        "benchmark_id": "b1",
        "source_name": "Fixture source",
        "source_url": source_url,
        "source_type": "api",
        "officialness_level": "O5",
        "machine_readable": True,
        "requires_auth": False,
        "supports_history": True,
        "update_cadence": "daily",
        "parser_name": "fixture_parser",
        "parser_version": "v1",
        "parser_config": parser_config or {"nested": {"a": 1, "b": 2}},
        "status": status,
        "notes": notes,
    }


def _write_registry(tmp_path: Path, source_entries: list[dict[str, object]]) -> tuple[Path, Path, Path]:
    benchmarks = tmp_path / "benchmarks.yaml"
    models_path = tmp_path / "models.yaml"
    sources = tmp_path / "sources.yaml"
    benchmarks.write_text(
        yaml.safe_dump(
            {
                "benchmarks": [
                    {
                        "id": "b1",
                        "canonical_name": "fixture-benchmark",
                        "display_name": "Fixture benchmark",
                    }
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    models_path.write_text("models: []\n", encoding="utf-8")
    sources.write_text(yaml.safe_dump({"sources": source_entries}, sort_keys=False), encoding="utf-8")
    return benchmarks, models_path, sources


def _seed_manifest(
    session,
    paths: tuple[Path, Path, Path],
    *,
    retire_missing: bool = True,
) -> dict[str, int]:
    benchmarks, models_path, sources = paths
    return seed_registry(
        session,
        benchmarks_path=benchmarks,
        models_path=models_path,
        sources_path=sources,
        retire_missing=retire_missing,
    )


def test_reseed_preserves_claim_snapshot_and_run_history(
    seeded_db, allow_quarantined_fixture_ingestion
):
    registry = Path(__file__).resolve().parents[1] / "app" / "registry"
    with get_session() as session:
        run_ingestion(session, source_id="fake_local_fixture", fixture_path=FIXTURE)
        before = {
            "runs": _count(session, models.IngestionRun),
            "snapshots": _count(session, models.SourceSnapshot),
            "claims": _count(session, models.ResultClaim),
        }
        snapshot_uri = session.scalar(select(models.SourceSnapshot.raw_content_uri))
        seed_registry(
            session,
            benchmarks_path=registry / "benchmarks.yaml",
            models_path=registry / "models.yaml",
            sources_path=registry / "official_sources.yaml",
        )
        after = {
            "runs": _count(session, models.IngestionRun),
            "snapshots": _count(session, models.SourceSnapshot),
            "claims": _count(session, models.ResultClaim),
        }
        assert session.scalar(select(models.SourceSnapshot.raw_content_uri)) == snapshot_uri
    assert after == before


def test_source_identity_collision_fails_without_remapping_history(seeded_db):
    with get_session() as session:
        original = session.get(models.OfficialSourceRow, "fake_local_fixture")
        assert original is not None
        before = _count(session, models.OfficialSourceRow)
        with pytest.raises(ValueError, match="Refusing to remap an existing logical source identity"):
            repo.upsert_official_source(
                session,
                {
                    "id": "replacement-source-id",
                    "benchmark_id": original.benchmark_id,
                    "source_name": "renamed fixture",
                    "source_url": original.source_url,
                    "source_type": original.source_type,
                    "officialness_level": original.officialness_level,
                    "machine_readable": original.machine_readable,
                    "requires_auth": original.requires_auth,
                    "supports_history": original.supports_history,
                    "status": original.status,
                },
            )
        assert _count(session, models.OfficialSourceRow) == before
        assert session.get(models.OfficialSourceRow, "fake_local_fixture") is not None


def test_changed_source_definition_appends_a_successor_without_rewriting_evidence(
    seeded_db, allow_quarantined_fixture_ingestion
):
    with get_session() as session:
        run_ingestion(session, source_id="fake_local_fixture", fixture_path=FIXTURE)
        source = session.get(models.OfficialSourceRow, "fake_local_fixture")
        assert source is not None
        before_revision = repo.get_current_source_revision(session, source.id)
        snapshot = session.scalar(
            select(models.SourceSnapshot).where(models.SourceSnapshot.official_source_id == source.id)
        )
        assert snapshot is not None
        result = repo.reconcile_official_source(
            session,
            {"id": source.id, "source_url": "file:///changed-fixture.json"},
            registry_managed=True,
        )

        assert result.disposition == "revised"
        assert result.revision_created
        assert result.revision.revision_ordinal == before_revision.revision_ordinal + 1
        assert result.revision.supersedes_revision_id == before_revision.id
        assert result.revision.source_url == "file:///changed-fixture.json"
        assert before_revision.source_url != result.revision.source_url
        assert source.current_revision_id == result.revision.id
        assert snapshot.source_revision_id == before_revision.id
        decision = session.scalar(
            select(models.SourceRevisionDecision)
            .where(models.SourceRevisionDecision.source_revision_id == result.revision.id)
            .order_by(models.SourceRevisionDecision.decided_at.desc())
        )
        assert decision is not None
        assert (decision.outcome, decision.reason_code) == ("quarantined", "registry_definition_changed")


def test_complete_manifest_reconciles_idempotent_changes_retirement_and_reintroduction(tmp_db, tmp_path: Path):
    v1 = _source_payload("source-a", source_url="https://official.example/v1.json")
    paths = _write_registry(tmp_path, [v1])

    with get_session() as session:
        initial = _seed_manifest(session, paths)
        source = session.get(models.OfficialSourceRow, "source-a")
        assert source is not None
        revision_one = repo.get_current_source_revision(session, source.id)
        assert initial["source_revisions"] == 1
        assert source.registry_managed is True
        snapshot = repo.insert_snapshot(
            session,
            official_source_id=source.id,
            source_revision_id=revision_one.id,
            raw_content_uri="file:///snapshots/source-a-v1.json",
            content_hash="a" * 64,
            content_type="application/json",
            http_status=200,
            etag=None,
            last_modified_header=None,
            fetch_metadata={"fixture": True},
            parser_version="v1",
        )

        # Canonical definition hashing makes a semantically identical nested
        # parser config a no-op even when YAML key order differs.
        v1_reordered = _source_payload(
            "source-a",
            source_url="https://official.example/v1.json",
            parser_config={"nested": {"b": 2, "a": 1}},
        )
        _write_registry(tmp_path, [v1_reordered])
        unchanged = _seed_manifest(session, paths)
        assert unchanged["source_revisions"] == 0
        assert _source_count(session, source.id) == 1

        v2 = _source_payload(
            "source-a",
            source_url="https://official.example/v2.json",
            parser_config={"nested": {"a": 1, "b": 3}},
            notes="parser configuration revised",
        )
        _write_registry(tmp_path, [v2])
        changed = _seed_manifest(session, paths)
        revision_two = repo.get_current_source_revision(session, source.id)
        assert changed["source_revisions"] == 1
        assert revision_two.revision_ordinal == 2
        assert revision_two.supersedes_revision_id == revision_one.id
        assert snapshot.source_revision_id == revision_one.id
        assert revision_one.parser_config == {"nested": {"a": 1, "b": 2}}

        manual = repo.reconcile_official_source(
            session,
            _source_payload("manual-source", source_url="https://official.example/manual.json"),
            registry_managed=False,
        )
        assert manual.source.registry_managed is False

        _write_registry(tmp_path, [])
        retired = _seed_manifest(session, paths)
        revision_three = repo.get_current_source_revision(session, source.id)
        assert retired["sources_retired"] == 1
        assert revision_three.revision_ordinal == 3
        assert revision_three.supersedes_revision_id == revision_two.id
        assert revision_three.status == "retired"
        assert source.current_revision_id == revision_three.id
        assert {row.id for row in repo.list_active_sources(session)} == {"manual-source"}
        retirement_decision = session.scalar(
            select(models.SourceRevisionDecision).where(
                models.SourceRevisionDecision.source_revision_id == revision_three.id
            )
        )
        assert retirement_decision is not None
        assert (retirement_decision.outcome, retirement_decision.reason_code) == (
            "revoked",
            "removed_from_registry",
        )

        repeated_retirement = _seed_manifest(session, paths)
        assert repeated_retirement["sources_retired"] == 0
        assert _source_count(session, source.id) == 3
        assert repo.get_current_source_revision(session, "manual-source").status == "active"

        _write_registry(tmp_path, [v1])
        reintroduced = _seed_manifest(session, paths)
        revision_four = repo.get_current_source_revision(session, source.id)
        assert reintroduced["source_revisions"] == 1
        assert revision_four.revision_ordinal == 4
        assert revision_four.supersedes_revision_id == revision_three.id
        assert revision_four.definition_hash == revision_one.definition_hash
        reintroduction_decision = session.scalar(
            select(models.SourceRevisionDecision).where(
                models.SourceRevisionDecision.source_revision_id == revision_four.id
            )
        )
        assert reintroduction_decision is not None
        assert (reintroduction_decision.outcome, reintroduction_decision.reason_code) == (
            "quarantined",
            "source_reintroduced",
        )

        repeated_reintroduction = _seed_manifest(session, paths)
        assert repeated_reintroduction["source_revisions"] == 0
        assert _source_count(session, source.id) == 4


def test_reverting_to_a_noncurrent_historical_definition_appends_a_new_successor(tmp_db, tmp_path: Path):
    v1 = _source_payload("source-a", source_url="https://official.example/v1.json")
    v2 = _source_payload(
        "source-a",
        source_url="https://official.example/v2.json",
        parser_config={"nested": {"a": 1, "b": 3}},
    )
    paths = _write_registry(tmp_path, [v1])
    with get_session() as session:
        _seed_manifest(session, paths)
        revision_one = repo.get_current_source_revision(session, "source-a")
        _write_registry(tmp_path, [v2])
        _seed_manifest(session, paths)
        revision_two = repo.get_current_source_revision(session, "source-a")
        _write_registry(tmp_path, [v1])
        reverted = _seed_manifest(session, paths)
        revision_three = repo.get_current_source_revision(session, "source-a")

        assert reverted["source_revisions"] == 1
        assert revision_three.revision_ordinal == 3
        assert revision_three.supersedes_revision_id == revision_two.id
        assert revision_three.definition_hash == revision_one.definition_hash


def test_library_partial_manifest_does_not_retire_managed_sources_without_opt_in(tmp_db, tmp_path: Path):
    source_a = _source_payload("source-a", source_url="https://official.example/a.json")
    source_b = _source_payload("source-b", source_url="https://official.example/b.json")
    paths = _write_registry(tmp_path, [source_a, source_b])
    with get_session() as session:
        _seed_manifest(session, paths)
        before_revision = repo.get_current_source_revision(session, "source-b")
        _write_registry(tmp_path, [source_a])
        partial = _seed_manifest(session, paths, retire_missing=False)
        source_b_row = session.get(models.OfficialSourceRow, "source-b")

        assert partial["sources_retired"] == 0
        assert source_b_row is not None
        assert source_b_row.status == "active"
        assert source_b_row.current_revision_id == before_revision.id
        assert _source_count(session, "source-b") == 1


def test_late_manifest_conflict_rolls_back_earlier_source_transitions(tmp_db, tmp_path: Path):
    source_a = _source_payload("source-a", source_url="https://official.example/a.json")
    source_b = _source_payload("source-b", source_url="https://official.example/b.json")
    paths = _write_registry(tmp_path, [source_a, source_b])
    with get_session() as session:
        _seed_manifest(session, paths)
        before_a = repo.get_current_source_revision(session, "source-a")
        before_b = repo.get_current_source_revision(session, "source-b")
        conflicting_a = _source_payload("source-a", source_url="https://official.example/a-v2.json")
        conflicting_b = _source_payload("source-b", source_url="https://official.example/a-v2.json")
        _write_registry(tmp_path, [conflicting_a, conflicting_b])

        with pytest.raises(ValueError, match="Refusing to remap an existing logical source identity"):
            _seed_manifest(session, paths)

        session.expire_all()
        after_a = repo.get_current_source_revision(session, "source-a")
        after_b = repo.get_current_source_revision(session, "source-b")
        assert (after_a.id, after_a.source_url, _source_count(session, "source-a")) == (
            before_a.id,
            "https://official.example/a.json",
            1,
        )
        assert (after_b.id, after_b.source_url, _source_count(session, "source-b")) == (
            before_b.id,
            "https://official.example/b.json",
            1,
        )


def test_malformed_source_document_cannot_retire_managed_sources(tmp_db, tmp_path: Path):
    paths = _write_registry(
        tmp_path,
        [_source_payload("source-a", source_url="https://official.example/v1.json")],
    )
    with get_session() as session:
        _seed_manifest(session, paths)
        source = session.get(models.OfficialSourceRow, "source-a")
        assert source is not None
        before_revision_id = source.current_revision_id
        before_count = _source_count(session, source.id)
        paths[2].write_text("sources: null\n", encoding="utf-8")
        with pytest.raises(ValueError, match="non-null sources list"):
            _seed_manifest(session, paths)
        session.expire_all()
        source = session.get(models.OfficialSourceRow, "source-a")
        assert source is not None
        assert source.current_revision_id == before_revision_id
        assert source.status == "active"
        assert _source_count(session, source.id) == before_count


def test_duplicate_source_manifest_is_rejected_before_any_registry_write(tmp_db, tmp_path: Path):
    benchmarks = tmp_path / "benchmarks.yaml"
    models_path = tmp_path / "models.yaml"
    sources = tmp_path / "sources.yaml"
    benchmarks.write_text("benchmarks: []\n", encoding="utf-8")
    models_path.write_text("models: []\n", encoding="utf-8")
    sources.write_text("sources:\n  - id: duplicate\n  - id: duplicate\n", encoding="utf-8")
    with get_session() as session:
        with pytest.raises(ValueError, match="Registry source IDs must be unique"):
            seed_registry(
                session,
                benchmarks_path=benchmarks,
                models_path=models_path,
                sources_path=sources,
                retire_missing=True,
            )
        assert _count(session, models.OfficialSourceRow) == 0
