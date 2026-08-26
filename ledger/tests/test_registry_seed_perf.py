"""Statement-counter tests for bounded registry seeding.

Registry seeding must not degrade to a per-row N+1: the number of ``SELECT``
statements for benchmarks/models/aliases stays constant (bounded) as the seed
definition grows, aliases do not hit SQLite/PostgreSQL parameter-limit failures
on a bounded-but-large alias set, and reseeding stays idempotent with prior
count semantics.  Acceptance is statement/parameter counts, never wall-clock.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from app.db import models
from app.db.engine import get_session
from app.registry.seed_loader import seed_registry


class StatementCounter:
    """Count statements executed on an engine between construct/detach."""

    def __init__(self, session: Session) -> None:
        self.statements: list[str] = []
        self._engine = session.bind
        event.listen(self._engine, "before_cursor_execute", self._on_execute)

    def _on_execute(self, conn, cursor, statement, parameters, context, executemany):  # type: ignore[no-untyped-def]
        self.statements.append(str(statement))

    @property
    def count(self) -> int:
        return len(self.statements)

    def selects(self) -> int:
        return sum(1 for s in self.statements if s.lstrip().upper().startswith("SELECT"))

    def detach(self) -> None:
        event.remove(self._engine, "before_cursor_execute", self._on_execute)


def _write_registry(
    tmp_path: Path,
    *,
    n_benchmarks: int,
    n_models: int,
    alias_texts: list[str],
) -> tuple[Path, Path, Path]:
    benchmarks = tmp_path / "benchmarks.yaml"
    models_path = tmp_path / "models.yaml"
    sources = tmp_path / "sources.yaml"
    benchmarks.write_text(
        yaml.safe_dump(
            {
                "benchmarks": [
                    {
                        "id": f"b{i}",
                        "canonical_name": f"b{i}",
                        "display_name": f"B{i}",
                        "aliases": (
                            [f"b-{i}-{a}" for a in alias_texts] if i == 0 else []
                        ),
                    }
                    for i in range(n_benchmarks)
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    models_path.write_text(
        yaml.safe_dump(
            {
                "models": [
                    {
                        "id": f"m{i}",
                        "canonical_name": f"M{i}",
                        "display_name": f"Model i",
                        "entity_type": "chat_model",
                        "access_type": "api",
                        "aliases": (
                            [f"m-alias-{a}" for a in alias_texts] if i == 0 else []
                        ),
                    }
                    for i in range(n_models)
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    sources.write_text("sources: []\n", encoding="utf-8")
    return benchmarks, models_path, sources


def _count_selects(fn) -> int:  # type: ignore[no-untyped-def]
    with get_session() as session:
        counter = StatementCounter(session)
        try:
            fn(session)
        finally:
            counter.detach()
        return counter.selects()


def test_benchmark_model_select_is_constant_as_seed_grows(tmp_path: Path, tmp_db):
    """Benchmark + model upsert preloads stay a constant number of SELECTs.

    A 5/3 seed and a 200/100 seed must emit the *same* bounded SELECT count for
    the benchmark/model preload (one SELECT per entity type, plus the alias
    existence lookup) — proving the preload is not a per-row N+1.
    """
    small = _write_registry(tmp_path, n_benchmarks=5, n_models=3, alias_texts=["a"])
    with get_session() as session:
        seed_registry(
            session,
            benchmarks_path=small[0],
            models_path=small[1],
            sources_path=small[2],
        )

    big = _write_registry(tmp_path, n_benchmarks=200, n_models=100, alias_texts=["a"])

    def reseed(session: Session) -> None:  # type: ignore[no-untyped-def]
        seed_registry(
            session,
            benchmarks_path=big[0],
            models_path=big[1],
            sources_path=big[2],
        )

    n_select = _count_selects(reseed)
    # Exactly 3 SELECTs: 1 Benchmark preload + 1 ModelEntity preload + 1 alias
    # lookup (sources: [] so no source reconcile SELECTs).  Both the small 5/3
    # seed and the large 200/100 seed must emit this same constant count; we
    # assert the exact 3 (measured), so a regression back to per-row get/insert
    # (~300+ SELECTs) fails loudly instead of drifting under a loose bound.
    assert n_select == 3, f"got {n_select} SELECTs (expected constant sub-linear preload)"


def test_large_alias_set_does_not_exceed_parameter_limit(tmp_path: Path, tmp_db):
    """A bounded-but-large alias set does not hit SQLite IN parameter limit."""
    # 3_000 aliases on one entity -> one lookup IN of 3,000 would exceed SQLite's
    # 999-parameter cap if not batched; chunked lookup must stay under it and
    # insert all rows.
    alias_texts = [f"alias-{i}" for i in range(3_000)]
    paths = _write_registry(tmp_path, n_benchmarks=1, n_models=0, alias_texts=alias_texts)
    with get_session() as session:
        counts = seed_registry(
            session,
            benchmarks_path=paths[0],
            models_path=paths[1],
            sources_path=paths[2],
        )
        alias_total = session.scalar(select(func.count()).select_from(models.Alias))
        assert alias_total == 3_000
        # seed count semantics: aliases = manifest entries processed.
        assert counts["aliases"] == 3_000
        assert counts["benchmarks"] == 1


def test_reseed_is_idempotent_and_count_semantics_preserved(tmp_path: Path, tmp_db):
    from sqlalchemy import func

    paths = _write_registry(tmp_path, n_benchmarks=3, n_models=2, alias_texts=["x", "y"])
    with get_session() as session:
        first = seed_registry(
            session,
            benchmarks_path=paths[0],
            models_path=paths[1],
            sources_path=paths[2],
        )
        bench_rows = session.scalar(
            select(func.count()).select_from(models.Benchmark)
        )
    assert bench_rows == 3
    assert first["aliases"] == 4  # 2 benchmark aliases + 2 model aliases
    # Idempotent reseed: same processed counts, no additional rows.
    with get_session() as session:
        second = seed_registry(
            session,
            benchmarks_path=paths[0],
            models_path=paths[1],
            sources_path=paths[2],
        )
        bench_rows = session.scalar(
            select(func.count()).select_from(models.Benchmark)
        )
        model_rows = session.scalar(
            select(func.count()).select_from(models.ModelEntity)
        )
        alias_rows = session.scalar(
            select(func.count()).select_from(models.Alias)
        )
    assert second["aliases"] == 4
    assert bench_rows == 3
    assert model_rows == 2
    assert alias_rows == 4