"""Focused failing regressions for security-remediation wave A.

Four boundaries, each asserted to FAIL on the current code and pass only
after the narrow fix lands:

  1. Authoritative allowlist: registry globbing must NOT promote review-only
     or arbitrary sibling ``models*.yaml`` / ``benchmarks*.yaml`` files into
     authoritative seeding input.
  2. Strict registry collection/entry validation: wrong-type collections and
     non-mapping / id-less registry entries fail closed before any durable write.
  3. Malformed / id-less / wrong-shaped-alias review candidates produce a
     deterministic CLI error and write no output file.
  4. Aliases with invalid ``entity_type`` or dangling ``entity_id`` cannot be
     inserted (single or bulk) and cannot resolve to a nonexistent identity.

Run with:  uv run pytest -q tests/test_security_remediation_regressions.py
"""

from __future__ import annotations

import subprocess
import sys
from collections import defaultdict
from pathlib import Path

import pytest
import yaml
from sqlalchemy import func, select

from app.db import models, repositories as repo
from app.db.engine import get_session
from app.matching.aliases import resolve_benchmark, resolve_model_entity
from app.registry import seed_loader
from app.registry.seed_loader import seed_registry


LEDGER = Path(__file__).resolve().parents[1]
TOOL = LEDGER / "scripts" / "seed_models_from_hf.py"
FIXTURE = Path(__file__).parent / "fixtures" / "hf_seed_candidates.yaml"


def _run_tool(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(TOOL), *args],
        cwd=str(LEDGER),
        capture_output=True,
        text=True,
    )


def _count_models(session) -> int:
    return session.scalar(select(func.count()).select_from(models.ModelEntity)) or 0


def _count_benchmarks(session) -> int:
    return session.scalar(select(func.count()).select_from(models.Benchmark)) or 0


# ---------------------------------------------------------------------------
# 1. Authoritative allowlist: review-only / arbitrary sibling glob exclusion
# ---------------------------------------------------------------------------

def test_review_only_sibling_model_never_reaches_model_entity(tmp_path, tmp_db):
    """A review-only ``models_hf_seed.yaml`` unique model is excluded by the
    explicit allowlist and must never be inserted as a ModelEntity."""
    benchmarks = tmp_path / "benchmarks.yaml"
    canonical = tmp_path / "models.yaml"
    frontier = tmp_path / "models_frontier.yaml"
    review_only = tmp_path / "models_hf_seed.yaml"
    sources = tmp_path / "sources.yaml"

    benchmarks.write_text("benchmarks: []\n", encoding="utf-8")
    canonical.write_text(
        yaml.safe_dump(
            {
                "models": [
                    {
                        "id": "canonical-model",
                        "canonical_name": "C",
                        "display_name": "Canonical Model",
                        "entity_type": "chat_model",
                        "access_type": "api",
                    }
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    frontier.write_text(
        yaml.safe_dump(
            {
                "models": [
                    {
                        "id": "frontier-model",
                        "canonical_name": "F",
                        "display_name": "Frontier Model",
                        "entity_type": "chat_model",
                        "access_type": "api",
                    }
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    # A review-only candidate with a UNIQUE id that must never be seeded.
    review_only.write_text(
        yaml.safe_dump(
            {
                "models": [
                    {
                        "id": "only-in-review",
                        "canonical_name": "R",
                        "display_name": "Review Only Model",
                        "entity_type": "chat_model",
                        "status": "active",
                    }
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    sources.write_text("sources: []\n", encoding="utf-8")

    with get_session() as session:
        seed_registry(
            session,
            benchmarks_path=benchmarks,
            models_path=canonical,
            sources_path=sources,
        )
        session.expire_all()
        assert _count_models(session) == 2, (
            "only canonical + frontier must be seeded; a review-only sibling "
            "was promoted into ModelEntity"
        )
        assert session.get(models.ModelEntity, "only-in-review") is None


def test_arbitrary_sibling_models_file_is_not_authoritative(tmp_path, tmp_db):
    """A third, arbitrary ``models_whatever.yaml`` sibling is not consumed as
    authoritative input under the allowlist."""
    benchmarks = tmp_path / "benchmarks.yaml"
    canonical = tmp_path / "models.yaml"
    arbitrary = tmp_path / "models_demo.yaml"
    sources = tmp_path / "sources.yaml"
    benchmarks.write_text("benchmarks: []\n", encoding="utf-8")
    canonical.write_text(
        yaml.safe_dump(
            {
                "models": [
                    {
                        "id": "a",
                        "canonical_name": "A",
                        "display_name": "Model A",
                        "entity_type": "chat_model",
                        "access_type": "api",
                    }
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    arbitrary.write_text(
        yaml.safe_dump(
            {
                "models": [
                    {
                        "id": "sneaky",
                        "canonical_name": "S",
                        "display_name": "Sneaky Model",
                        "entity_type": "chat_model",
                        "access_type": "api",
                    }
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    sources.write_text("sources: []\n", encoding="utf-8")
    with get_session() as session:
        seed_registry(
            session,
            benchmarks_path=benchmarks,
            models_path=canonical,
            sources_path=sources,
        )
        session.expire_all()
        assert session.get(models.ModelEntity, "sneaky") is None
        assert _count_models(session) == 1


def test_each_authoritative_registry_file_loaded_exactly_once(tmp_path, tmp_db, monkeypatch):
    """Load-bearing: every selected authoritative benchmark/model YAML file is
    loaded exactly once and the validated snapshot feeds the durable writes.

    The former reload behavior re-read each authoritative file a second time in
    the write loops (``_strict_entries(_load_yaml(...))``), so each selected
    path would be loaded twice. The fix validates every selected file exactly
    once in the preflight and reuses that validated entry snapshot for the
    writes. This test proves both halves: each selected benchmark/model path
    has load count 1, and the seeded IDs are the legitimate control that the
    single validated load actually produced the rows.
    """
    benchmarks = tmp_path / "benchmarks.yaml"
    curated = tmp_path / "benchmarks_curated.yaml"
    models_path = tmp_path / "models.yaml"
    frontier = tmp_path / "models_frontier.yaml"
    sources = tmp_path / "sources.yaml"

    benchmarks.write_text(
        "benchmarks:\n  - id: b1\n    canonical_name: B1\n    display_name: B1\n",
        encoding="utf-8",
    )
    curated.write_text(
        "benchmarks:\n  - id: b2\n    canonical_name: B2\n    display_name: B2\n",
        encoding="utf-8",
    )
    models_path.write_text(
        "models:\n  - id: m1\n    canonical_name: M1\n    display_name: M1\n"
        "    entity_type: chat_model\n    access_type: api\n",
        encoding="utf-8",
    )
    frontier.write_text(
        "models:\n  - id: m2\n    canonical_name: M2\n    display_name: M2\n"
        "    entity_type: chat_model\n    access_type: api\n",
        encoding="utf-8",
    )
    sources.write_text("sources: []\n", encoding="utf-8")

    load_counts: defaultdict[str, int] = defaultdict(int)
    real_load_yaml = seed_loader._load_yaml

    def counting_load_yaml(path: Path):
        load_counts[str(path)] += 1
        return real_load_yaml(path)

    monkeypatch.setattr(seed_loader, "_load_yaml", counting_load_yaml)

    with get_session() as session:
        seed_registry(
            session,
            benchmarks_path=benchmarks,
            models_path=models_path,
            sources_path=sources,
        )
        session.expire_all()
        seeded_benchmarks = set(session.scalars(select(models.Benchmark.id)))
        seeded_models = set(session.scalars(select(models.ModelEntity.id)))

    # Every selected authoritative file is loaded exactly once.
    for path in (benchmarks, curated, models_path, frontier):
        assert load_counts[str(path)] == 1, (
            f"{path.name} was loaded {load_counts[str(path)]} times; "
            "expected exactly one load per authoritative file"
        )
    # The explicitly selected overlays are authoritative; arbitrary siblings
    # never appear as loads (no promotion).
    assert load_counts[str(tmp_path / "models_demo.yaml")] == 0
    assert load_counts[str(tmp_path / "models_hf_seed.yaml")] == 0

    # Legitimate control: the single validated load produced the rows.
    assert seeded_benchmarks == {"b1", "b2"}
    assert seeded_models == {"m1", "m2"}


# ---------------------------------------------------------------------------
# 2. Strict registry collections and entries fail closed before writes
# ---------------------------------------------------------------------------
def test_wrong_type_models_collection_fails_before_write(tmp_path, tmp_db):
    """A non-list ``models`` collection must fail closed, not iterate chars."""
    benchmarks = tmp_path / "benchmarks.yaml"
    models_path = tmp_path / "models.yaml"
    sources = tmp_path / "sources.yaml"
    benchmarks.write_text("benchmarks: []\n", encoding="utf-8")
    models_path.write_text("models: not-a-list\n", encoding="utf-8")
    sources.write_text("sources: []\n", encoding="utf-8")
    with get_session() as session:
        with pytest.raises(ValueError):
            seed_registry(
                session, benchmarks_path=benchmarks, models_path=models_path, sources_path=sources
            )
        session.expire_all()
        assert _count_models(session) == 0


def test_non_mapping_registry_entry_fails_before_write(tmp_path, tmp_db):
    """A non-mapping entry (e.g. a bare string) must fail closed, not be skipped."""
    benchmarks = tmp_path / "benchmarks.yaml"
    models_path = tmp_path / "models.yaml"
    sources = tmp_path / "sources.yaml"
    benchmarks.write_text("benchmarks: []\n", encoding="utf-8")
    models_path.write_text("models:\n  - id: ok\n    canonical_name: Ok\n  - garbage\n", encoding="utf-8")
    sources.write_text("sources: []\n", encoding="utf-8")
    with get_session() as session:
        with pytest.raises(ValueError):
            seed_registry(
                session, benchmarks_path=benchmarks, models_path=models_path, sources_path=sources
            )
        session.expire_all()
        assert _count_models(session) == 0


def test_id_less_registry_entry_fails_closed(tmp_path, tmp_db):
    """A mapping entry without a non-empty id must fail closed."""
    benchmarks = tmp_path / "benchmarks.yaml"
    models_path = tmp_path / "models.yaml"
    sources = tmp_path / "sources.yaml"
    benchmarks.write_text("benchmarks: []\n", encoding="utf-8")
    models_path.write_text(
        "models:\n  - canonical_name: NoId\n    access_type: api\n", encoding="utf-8"
    )
    sources.write_text("sources: []\n", encoding="utf-8")
    with get_session() as session:
        with pytest.raises(ValueError):
            seed_registry(
                session, benchmarks_path=benchmarks, models_path=models_path, sources_path=sources
            )
        session.expire_all()
        assert _count_models(session) == 0


def test_wrong_type_benchmarks_collection_fails_before_write(tmp_path, tmp_db):
    """A non-list ``benchmarks`` collection must fail closed, not iterate chars."""
    benchmarks = tmp_path / "benchmarks.yaml"
    models_path = tmp_path / "models.yaml"
    sources = tmp_path / "sources.yaml"
    benchmarks.write_text("benchmarks: not-a-list\n", encoding="utf-8")
    models_path.write_text("models: []\n", encoding="utf-8")
    sources.write_text("sources: []\n", encoding="utf-8")
    with get_session() as session:
        with pytest.raises(ValueError):
            seed_registry(
                session, benchmarks_path=benchmarks, models_path=models_path, sources_path=sources
            )
        session.expire_all()
        assert _count_benchmarks(session) == 0
        assert _count_models(session) == 0


def test_id_less_benchmark_entry_fails_closed(tmp_path, tmp_db):
    """A mapping benchmark entry without a non-empty id must fail closed."""
    benchmarks = tmp_path / "benchmarks.yaml"
    models_path = tmp_path / "models.yaml"
    sources = tmp_path / "sources.yaml"
    benchmarks.write_text("benchmarks:\n  - canonical_name: NoId\n", encoding="utf-8")
    models_path.write_text("models: []\n", encoding="utf-8")
    sources.write_text("sources: []\n", encoding="utf-8")
    with get_session() as session:
        with pytest.raises(ValueError):
            seed_registry(
                session, benchmarks_path=benchmarks, models_path=models_path, sources_path=sources
            )
        session.expire_all()
        assert _count_benchmarks(session) == 0
        assert _count_models(session) == 0


def test_malformed_model_overlay_leaves_both_entity_tables_unchanged(tmp_path, tmp_db):
    """A valid canonical model file is fully written only if the explicit
    ``models_frontier.yaml`` overlay is also valid; a malformed overlay must fail
    atomically and leave both ``ModelEntity`` and ``Benchmark`` tables unchanged
    even when the caller catches the error and continues using its session."""
    benchmarks = tmp_path / "benchmarks.yaml"
    models_path = tmp_path / "models.yaml"
    frontier = tmp_path / "models_frontier.yaml"
    sources = tmp_path / "sources.yaml"
    benchmarks.write_text(
        "benchmarks:\n  - id: b1\n    canonical_name: B1\n    access_type: api\n",
        encoding="utf-8",
    )
    models_path.write_text(
        "models:\n  - id: m1\n    canonical_name: M1\n    access_type: api\n", encoding="utf-8"
    )
    # Malformed overlay: an entry without an id.
    frontier.write_text(
        "models:\n  - id: m2\n    canonical_name: M2\n    access_type: api\n"
        "  - canonical_name: NoId\n    access_type: api\n",
        encoding="utf-8",
    )
    sources.write_text("sources: []\n", encoding="utf-8")

    with get_session() as session:
        with pytest.raises(ValueError):
            seed_registry(
                session, benchmarks_path=benchmarks, models_path=models_path, sources_path=sources
            )
        session.flush()  # a caller catching the error may still flush/commit later
        session.expire_all()
        # All-or-nothing: nothing from the canonical file may have been written.
        assert _count_models(session) == 0
        assert _count_benchmarks(session) == 0


def test_malformed_benchmark_overlay_leaves_both_entity_tables_unchanged(tmp_path, tmp_db):
    """A malformed ``benchmarks_curated.yaml`` overlay must fail atomically and
    leave both entity tables unchanged even when the caller catches the error
    and later commits."""
    benchmarks = tmp_path / "benchmarks.yaml"
    curated = tmp_path / "benchmarks_curated.yaml"
    models_path = tmp_path / "models.yaml"
    sources = tmp_path / "sources.yaml"
    benchmarks.write_text(
        "benchmarks:\n  - id: b1\n    canonical_name: B1\n    access_type: api\n"
        "  - id: b2\n    canonical_name: B2\n",
        encoding="utf-8",
    )
    models_path.write_text(
        "models:\n  - id: m1\n    canonical_name: M1\n    access_type: api\n", encoding="utf-8"
    )
    # Malformed curated overlay: wrong-shaped aliases on a valid-id row.
    curated.write_text(
        "benchmarks:\n  - id: b3\n    canonical_name: B3\n    aliases: not-a-list\n",
        encoding="utf-8",
    )
    sources.write_text("sources: []\n", encoding="utf-8")

    with get_session() as session:
        with pytest.raises(ValueError):
            seed_registry(
                session, benchmarks_path=benchmarks, models_path=models_path, sources_path=sources
            )
        session.flush()
        session.expire_all()
        assert _count_benchmarks(session) == 0
        assert _count_models(session) == 0


# ---------------------------------------------------------------------------
# 3. Malformed review candidates and fail with no output + deterministic error
# ---------------------------------------------------------------------------
def test_review_non_mapping_candidate_fails_closed(tmp_path):
    out = tmp_path / "out.yaml"
    bad = tmp_path / "in.yaml"
    bad.write_text("models:\n  - id: ok\n    canonical_name: Ok\n  - [not, a, dict]\n", encoding="utf-8")
    proc = _run_tool("--input", str(bad), "--output", str(out), "--registry-dir", str(tmp_path))
    assert proc.returncode != 0, "malformed candidate must exit non-zero"
    assert not out.exists(), "no output file may be written when a candidate is malformed"


def test_review_id_less_candidate_fails_closed_and_writes_nothing(tmp_path):
    out = tmp_path / "out.yaml"
    bad = tmp_path / "in.yaml"
    bad.write_text("models:\n  - canonical_name: No-id\n  - id: valid2\n    canonical_name: V2\n", encoding="utf-8")
    proc = _run_tool("--input", str(bad), "--output", str(out), "--registry-dir", str(tmp_path))
    assert proc.returncode != 0
    assert "id" in proc.stdout + proc.stderr, "error should identify the failed candidate"
    assert not out.exists()


def test_review_wrong_shape_aliases_fails_closed(tmp_path):
    out = tmp_path / "out.yaml"
    bad = tmp_path / "in.yaml"
    # aliases as a string would be char-split under list(...) — must be rejected.
    bad.write_text("models:\n  - id: m1\n    canonical_name: M1\n    aliases: not-a-list\n", encoding="utf-8")
    proc = _run_tool("--input", str(bad), "--output", str(out), "--registry-dir", str(tmp_path))
    assert proc.returncode != 0, "wrong-shaped aliases must be rejected"
    assert not out.exists()


def test_review_valid_candidates_still_write(tmp_path):
    """Regression guard: a fully-valid review input still produces the review file."""
    out = tmp_path / "out.yaml"
    proc = _run_tool("--input", str(FIXTURE), "--output", str(out), "--registry-dir", str(tmp_path))
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert out.exists()


# ---------------------------------------------------------------------------
# 4. Invalid / dangling alias targets cannot insert or resolve
# ---------------------------------------------------------------------------
def test_alias_invalid_entity_type_rejected(tmp_db):
    with get_session() as session:
        with pytest.raises(ValueError):
            repo.add_alias(
                session,
                entity_type="evil",
                entity_id="some-id",
                alias_text="poison",
            )
        assert _count_aliases(session) == 0


def _count_aliases(session) -> int:
    return session.scalar(select(func.count()).select_from(models.Alias)) or 0


def test_alias_dangling_entity_id_rejected(tmp_db):
    with get_session() as session:
        with pytest.raises(ValueError):
            repo.add_alias(
                session,
                entity_type="model_entity",
                entity_id="does-not-exist",
                alias_text="poison",
            )
        assert _count_aliases(session) == 0


def test_alias_bulk_dangling_target_rejected(tmp_db):
    with get_session() as session:
        with pytest.raises(ValueError):
            repo.add_aliases_bulk(
                session,
                [
                    repo._AliasSeedRequest(
                        entity_type="model_entity", entity_id="no-such-model", alias_text="x"
                    )
                ],
            )
        assert _count_aliases(session) == 0


def test_legacy_dangling_alias_cannot_resolve_to_nonexistent_identity(tmp_db):
    """A poisoned/already-present dangling Alias row (from a legacy/direct
    writer) must not resolve to a nonexistent official identity."""
    with get_session() as session:
        session.add(
            models.Alias(
                entity_type="model_entity",
                entity_id="ghost-entity",
                alias_text="poison-label",
                is_official_alias=False,
                alias_source="legacy",
            )
        )
        session.flush()
        result = resolve_model_entity(session, "poison-label")
        assert result.status == "unmatched", (
            "a dangling alias must not produce a matched identity pointing at a "
            "nonexistent entity"
        )
        assert result.entity_id is None