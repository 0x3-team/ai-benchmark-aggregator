from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models


def _normalize_alias_key(s: str) -> str:
    # Lazy import to avoid a circular import (ingestion -> matching -> ingestion).
    from app.ingestion.extractors.normalize import normalize_alias_key

    return normalize_alias_key(s)


@dataclass(frozen=True)
class MatchResolution:
    """A priority-aware identity resolution that never picks a collision."""

    entity_id: str | None
    status: str

    @property
    def is_match(self) -> bool:
        return self.status == "matched" and self.entity_id is not None


def _resolution(entity_ids: set[str]) -> MatchResolution:
    if len(entity_ids) == 1:
        return MatchResolution(next(iter(entity_ids)), "matched")
    if len(entity_ids) > 1:
        return MatchResolution(None, "ambiguous")
    return MatchResolution(None, "unmatched")


def _resolve_aliases(session: Session, *, entity_type: str, raw: str) -> MatchResolution:
    exact_aliases = list(
        session.scalars(
            select(models.Alias).where(
                models.Alias.entity_type == entity_type,
                models.Alias.alias_text == raw,
            )
        )
    )
    if exact_aliases:
        return _resolution({alias.entity_id for alias in exact_aliases})

    aliases = list(session.scalars(select(models.Alias).where(models.Alias.entity_type == entity_type)))
    lower = raw.lower()
    case_insensitive = {alias.entity_id for alias in aliases if alias.alias_text.lower() == lower}
    if case_insensitive:
        return _resolution(case_insensitive)

    key = _normalize_alias_key(raw)
    normalized = {alias.entity_id for alias in aliases if _normalize_alias_key(alias.alias_text) == key}
    if normalized:
        return _resolution(normalized)
    return MatchResolution(None, "unmatched")


def resolve_model_entity(session: Session, model_raw: str) -> MatchResolution:
    """Resolve a model at the first matching priority and fail closed on ties."""
    if not model_raw:
        return MatchResolution(None, "unmatched")

    aliases = _resolve_aliases(session, entity_type="model_entity", raw=model_raw)
    if aliases.status != "unmatched":
        return aliases

    entity = session.get(models.ModelEntity, model_raw)
    if entity:
        return MatchResolution(entity.id, "matched")

    entities = list(session.scalars(select(models.ModelEntity)))
    lower = model_raw.lower()
    direct_text = {
        entity.id
        for entity in entities
        if entity.canonical_name.lower() == lower or entity.display_name.lower() == lower
    }
    if direct_text:
        return _resolution(direct_text)

    key = _normalize_alias_key(model_raw)
    normalized = {
        entity.id
        for entity in entities
        if _normalize_alias_key(entity.canonical_name) == key
        or _normalize_alias_key(entity.display_name) == key
    }
    return _resolution(normalized)


def match_model_entity(session: Session, model_raw: str) -> str | None:
    """Compatibility API: return an entity only when the match is unique."""
    return resolve_model_entity(session, model_raw).entity_id


def resolve_benchmark(
    session: Session, benchmark_raw: str, source_benchmark_id: str | None
) -> MatchResolution:
    """Resolve a benchmark at the first matching priority and fail closed on ties."""
    if source_benchmark_id:
        benchmark = session.get(models.Benchmark, source_benchmark_id)
        if benchmark:
            return MatchResolution(benchmark.id, "matched")
    if not benchmark_raw:
        return MatchResolution(None, "unmatched")

    aliases = _resolve_aliases(session, entity_type="benchmark", raw=benchmark_raw)
    if aliases.status != "unmatched":
        return aliases

    benchmark = session.get(models.Benchmark, benchmark_raw)
    if benchmark:
        return MatchResolution(benchmark.id, "matched")

    benchmarks = list(session.scalars(select(models.Benchmark)))
    lower = benchmark_raw.lower()
    direct_text = {
        benchmark.id
        for benchmark in benchmarks
        if benchmark.canonical_name.lower() == lower or benchmark.display_name.lower() == lower
    }
    if direct_text:
        return _resolution(direct_text)

    key = _normalize_alias_key(benchmark_raw)
    normalized = {
        benchmark.id
        for benchmark in benchmarks
        if _normalize_alias_key(benchmark.canonical_name) == key
        or _normalize_alias_key(benchmark.display_name) == key
    }
    return _resolution(normalized)


def match_benchmark(session: Session, benchmark_raw: str, source_benchmark_id: str | None) -> str | None:
    """Compatibility API: return a benchmark only when the match is unique."""
    return resolve_benchmark(session, benchmark_raw, source_benchmark_id).entity_id
