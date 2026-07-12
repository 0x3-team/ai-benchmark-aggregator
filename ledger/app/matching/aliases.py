from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models


def _normalize_alias_key(s: str) -> str:
    # Lazy import to avoid a circular import (ingestion -> matching -> ingestion).
    from app.ingestion.extractors.normalize import normalize_alias_key

    return normalize_alias_key(s)


def match_model_entity(session: Session, model_raw: str) -> str | None:
    if not model_raw:
        return None
    # exact
    row = session.scalar(
        select(models.Alias).where(
            models.Alias.entity_type == "model_entity",
            models.Alias.alias_text == model_raw,
        )
    )
    if row:
        return row.entity_id
    # case-insensitive
    aliases = session.scalars(
        select(models.Alias).where(models.Alias.entity_type == "model_entity")
    ).all()
    lower = model_raw.lower()
    for a in aliases:
        if a.alias_text.lower() == lower:
            return a.entity_id
    key = _normalize_alias_key(model_raw)
    for a in aliases:
        if _normalize_alias_key(a.alias_text) == key:
            return a.entity_id
    # direct id / canonical match
    ent = session.get(models.ModelEntity, model_raw)
    if ent:
        return ent.id
    for ent in session.scalars(select(models.ModelEntity)).all():
        if ent.canonical_name.lower() == lower or ent.display_name.lower() == lower:
            return ent.id
        if _normalize_alias_key(ent.canonical_name) == key:
            return ent.id
    return None


def match_benchmark(session: Session, benchmark_raw: str, source_benchmark_id: str | None) -> str | None:
    if source_benchmark_id:
        b = session.get(models.Benchmark, source_benchmark_id)
        if b:
            return b.id
    if not benchmark_raw:
        return None

    # 1. Exact alias match
    row = session.scalar(
        select(models.Alias).where(
            models.Alias.entity_type == "benchmark",
            models.Alias.alias_text == benchmark_raw,
        )
    )
    if row:
        return row.entity_id

    # 2. Case-insensitive and normalized alias match
    aliases = session.scalars(
        select(models.Alias).where(models.Alias.entity_type == "benchmark")
    ).all()
    lower = benchmark_raw.lower()
    for a in aliases:
        if a.alias_text.lower() == lower:
            return a.entity_id

    key = _normalize_alias_key(benchmark_raw)
    for a in aliases:
        if _normalize_alias_key(a.alias_text) == key:
            return a.entity_id

    # 3. Direct ID match
    b = session.get(models.Benchmark, benchmark_raw)
    if b:
        return b.id

    # 4. Case-insensitive and normalized canonical/display match
    for b in session.scalars(select(models.Benchmark)).all():
        if b.canonical_name.lower() == lower or b.display_name.lower() == lower:
            return b.id
        if _normalize_alias_key(b.canonical_name) == key or _normalize_alias_key(b.display_name) == key:
            return b.id

    return None
