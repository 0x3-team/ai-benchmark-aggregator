from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from sqlalchemy.orm import Session

from app.db import repositories as repo


def _load_yaml(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as stream:
        return yaml.safe_load(stream) or {}


def _validated_source_entries(source_document: Any) -> tuple[list[dict[str, Any]], set[str]]:
    if not isinstance(source_document, dict):
        raise ValueError("Registry source document must be a mapping with a sources list.")
    if "sources" not in source_document or source_document["sources"] is None:
        raise ValueError("Registry source document must include a non-null sources list.")
    source_entries = source_document["sources"]
    if not isinstance(source_entries, list):
        raise ValueError("Registry source document sources must be a list.")

    source_ids: set[str] = set()
    duplicate_source_ids: set[str] = set()
    validated_entries: list[dict[str, Any]] = []
    for source in source_entries:
        if not isinstance(source, dict) or not source.get("id"):
            raise ValueError("Each registry source must be a mapping with a stable id.")
        source_id = str(source["id"])
        if source_id in source_ids:
            duplicate_source_ids.add(source_id)
        source_ids.add(source_id)
        validated_entries.append(source)
    if duplicate_source_ids:
        raise ValueError(
            "Registry source IDs must be unique; duplicate IDs would rewrite source history: "
            + ", ".join(sorted(duplicate_source_ids))
        )
    return validated_entries, source_ids


def _registry_files(path: Path, pattern: str) -> list[Path]:
    files = sorted(path.parent.glob(pattern)) if path.parent.exists() else []
    return files or [path]


def _seed_registry_changes(
    session: Session,
    *,
    benchmarks_path: Path,
    models_path: Path,
    source_entries: list[dict[str, Any]],
    source_ids: set[str],
    retire_missing: bool,
) -> dict[str, int]:
    counts = {
        "benchmarks": 0,
        "models": 0,
        "aliases": 0,
        "sources": 0,
        "source_revisions": 0,
        "sources_retired": 0,
    }

    seen_benchmark_ids: set[str] = set()
    for benchmark_file in _registry_files(benchmarks_path, "benchmarks*.yaml"):
        benchmark_document = _load_yaml(benchmark_file)
        if not isinstance(benchmark_document, dict):
            raise ValueError("Benchmark registry document must be a mapping.")
        for benchmark in benchmark_document.get("benchmarks") or []:
            if not isinstance(benchmark, dict) or "id" not in benchmark:
                continue
            benchmark_id = str(benchmark["id"])
            if benchmark_id in seen_benchmark_ids:
                continue
            seen_benchmark_ids.add(benchmark_id)
            aliases = benchmark.get("aliases") or []
            benchmark_data = {key: value for key, value in benchmark.items() if key != "aliases"}
            repo.upsert_benchmark(session, benchmark_data)
            counts["benchmarks"] += 1
            for alias in aliases:
                repo.add_alias(
                    session,
                    entity_type="benchmark",
                    entity_id=benchmark_id,
                    alias_text=alias,
                    is_official_alias=True,
                )
                counts["aliases"] += 1

    allowed_model_fields = {
        "id",
        "canonical_name",
        "display_name",
        "entity_type",
        "provider",
        "developer",
        "model_family",
        "access_type",
        "official_model_url",
        "official_docs_url",
        "official_card_url",
        "official_repo_url",
        "official_hf_repo",
        "api_model_id",
        "api_version",
        "status",
        "context_window",
        "modalities",
        "license",
    }
    seen_model_ids: set[str] = set()
    for model_file in _registry_files(models_path, "models*.yaml"):
        model_document = _load_yaml(model_file)
        if not isinstance(model_document, dict):
            raise ValueError("Model registry document must be a mapping.")
        for model in model_document.get("models") or []:
            if not isinstance(model, dict) or "id" not in model:
                continue
            model_id = str(model["id"])
            if model_id in seen_model_ids:
                continue
            seen_model_ids.add(model_id)
            aliases = model.get("aliases") or []
            model_data = {key: value for key, value in model.items() if key in allowed_model_fields}
            repo.upsert_model_entity(session, model_data)
            counts["models"] += 1
            for alias in aliases:
                repo.add_alias(
                    session,
                    entity_type="model_entity",
                    entity_id=model_id,
                    alias_text=alias,
                    is_official_alias=True,
                )
                counts["aliases"] += 1

    for source in source_entries:
        result = repo.reconcile_official_source(session, source, registry_managed=True)
        counts["sources"] += 1
        if result.revision_created:
            counts["source_revisions"] += 1
    if retire_missing:
        retirements = repo.retire_registry_sources_not_in(session, source_ids=source_ids)
        counts["sources_retired"] = len(retirements)
        counts["source_revisions"] += len(retirements)
    return counts


def seed_registry(
    session: Session,
    *,
    benchmarks_path: Path,
    models_path: Path,
    sources_path: Path,
    retire_missing: bool = False,
) -> dict[str, int]:
    """Reconcile a validated complete or partial registry without deleting evidence.

    A CLI caller uses ``retire_missing=True`` only after supplying a complete
    reviewed manifest. Programmatic callers default to no retirement so a
    deliberately partial manifest cannot mass-retire existing sources.
    """
    source_entries, source_ids = _validated_source_entries(_load_yaml(sources_path))
    # Preserve all-or-nothing behavior for the complete seed operation, even
    # when a library caller catches an error and keeps using its outer session.
    with session.begin_nested():
        return _seed_registry_changes(
            session,
            benchmarks_path=benchmarks_path,
            models_path=models_path,
            source_entries=source_entries,
            source_ids=source_ids,
            retire_missing=retire_missing,
        )
