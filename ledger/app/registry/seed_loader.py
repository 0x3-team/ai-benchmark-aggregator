from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models, repositories as repo


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


def _registry_files(path: Path, *_patterns: str) -> list[Path]:
    """Return the *authoritative* registry files for ``path``, never arbitrary siblings.

    The caller names one canonical file (e.g. ``models.yaml``); we expand only
    the *explicit* overlay it enumerates via ``_patterns`` (e.g.
    ``models_frontier.yaml``).  This is deliberately NOT a ``<base>*.yaml``
    glob: an arbitrary or review-only sibling (``models_hf_seed.yaml``,
    ``models_demo.yaml``, …) must never be promoted into authoritative input.
    Review output is a no-overwrite, offline candidate artifact that no longer
    reaches ``ModelEntity``.

    Ordering is an explicit lexicographic sort so the loader never depends on
    filesystem iteration order.  Every file in the returned set is
    authoritative: an ID may be defined in exactly one file, and any duplicate —
    byte-identical or not — is rejected by ``_validate_entity_ids`` before any
    durable write (no "first file wins").  See ``_seed_registry_changes``.
    """
    parent = path.parent
    candidates: set[Path] = {path}
    for pattern in _patterns:
        if pattern:
            candidates.add(parent / pattern)
    files = [f for f in candidates if f.exists()]
    return sorted(files) or [path]


def _validate_entity_ids(files: list[Path], kind: str) -> dict[Path, list[dict[str, Any]]]:
    """Reject a benchmark/model ``id`` defined more than once across seed files.

    Mirrors ``_validated_source_entries``: a duplicated identity is a governance
    error because the loader would otherwise silently seed one definition and
    drop the other. Every duplicate ID is reported with the exact files that
    define it and the loader never picks a "first file wins" definition. This
    runs before any durable registry write so a collision leaves the database
    unchanged. ``kind`` is the YAML key, e.g. ``"models"`` or ``"benchmarks"``.

    Unlike a plain ID scan, this fails *closed* on any malformed collection or
    entry (missing/null/wrong-type ``kind`` list, non-mapping row, blank/missing
    ``id``, malformed aliases) instead of silently skipping it. Each malformed
    row raises a deterministic ``ValueError`` naming the file, kind, and
    0-based index, so a partial or ill-formed registry can never quietly
    reconcile to success. This is the authoritative fail-closed preflight that
    the write loops reuse via the returned per-file ``_strict_entries``
    snapshots: every authoritative file is loaded and strictly validated exactly
    once here, and the same validated entries feed both the duplicate-ID scan
    and the durable writes.
    """
    validated_by_file: dict[Path, list[dict[str, Any]]] = {}
    id_files: dict[str, list[str]] = {}
    for file_path in files:
        document = _load_yaml(file_path)
        entries = _strict_entries(document, kind, file_path)
        validated_by_file[file_path] = entries
        for entry in entries:
            id_files.setdefault(str(entry["id"]), []).append(str(file_path))

    duplicates = {entity_id: file_list for entity_id, file_list in id_files.items() if len(file_list) > 1}
    if duplicates:
        detail = "; ".join(
            f"{entity_id!r} defined by {', '.join(sorted(set(file_list)))}"
            for entity_id, file_list in sorted(duplicates.items())
        )
        raise ValueError(
            f"Registry {kind} IDs must be unique across seed files; duplicates: {detail}"
        )
    return validated_by_file


def _strict_entries(document: Any, kind: str, file_path: Path) -> list[dict[str, Any]]:
    """Fail closed on a malformed ``kind`` collection — no silent omission.

    ``document`` must be a mapping carrying a non-null *list* under ``kind``,
    and every entry must be a mapping with a non-empty stable ``id``.  Aliases,
    when present, must be a list of strings.  This guarantees a partial or
    malformed registry can never quietly reconcile to success.
    """
    if not isinstance(document, dict):
        raise ValueError(f"Registry {kind} document {file_path} must be a mapping.")
    collection = document.get(kind)
    if not isinstance(collection, list):
        raise ValueError(
            f"Registry {kind} collection in {file_path} must be a non-null list; "
            f"got {type(collection).__name__ if collection is not None else 'null'}."
        )
    entries: list[dict[str, Any]] = []
    for idx, entry in enumerate(collection):
        if not isinstance(entry, dict):
            raise ValueError(
                f"Registry {kind} entry #{idx} in {file_path} must be a mapping, "
                f"got {type(entry).__name__}."
            )
        if not entry.get("id") or not str(entry["id"]).strip():
            raise ValueError(
                f"Registry {kind} entry #{idx} in {file_path} must have a non-empty id."
            )
        aliases = entry.get("aliases")
        if aliases is not None:
            if not isinstance(aliases, list) or not all(isinstance(a, str) for a in aliases):
                raise ValueError(
                    f"Registry {kind} entry #{idx} ({entry['id']!r}) in {file_path} has "
                    f"malformed aliases; expected a list of strings."
                )
        entries.append(entry)
    return entries


def _seed_registry_changes(
    session: Session,
    *,
    benchmarks_path: Path,
    models_path: Path,
    benchmark_files: list[Path],
    model_files: list[Path],
    benchmark_entries_by_file: dict[Path, list[dict[str, Any]]],
    model_entries_by_file: dict[Path, list[dict[str, Any]]],
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

    # Preload the target existing Benchmark/ModelEntity rows in one constant
    # SELECT each (the whole table, since ids are the primary key), then apply
    # creates/updates in-memory through the batched upsert seams and flush once
    # per entity group.  This replaces the former per-row ``session.get`` +
    # ``flush`` N+1 (defect #8) while preserving identical public
    # ``upsert_benchmark``/``upsert_model_entity`` semantics for single-row
    # callers.
    existing_benchmarks: dict[str, models.Benchmark] = {
        row.id: row for row in session.scalars(select(models.Benchmark))
    }
    existing_models: dict[str, models.ModelEntity] = {
        row.id: row for row in session.scalars(select(models.ModelEntity))
    }

    # Alias existence is checked in bounded chunks of the whole alias set once
    # below, then only missing rows are inserted.  This keeps the number of
    # alias ``SELECT`` statements O(len/batch) instead of 1/alias, preserving
    # the exact unique ``(entity_type, entity_id, alias_text)`` semantics and
    # idempotency.
    alias_requests: list[repo._AliasSeedRequest] = []

    for benchmark_file in benchmark_files:
        for benchmark in benchmark_entries_by_file[benchmark_file]:
            benchmark_id = str(benchmark["id"])
            aliases = benchmark.get("aliases") or []
            benchmark_data = {key: value for key, value in benchmark.items() if key != "aliases"}
            repo._upsert_benchmark_from_map(session, benchmark_data, existing_benchmarks)
            counts["benchmarks"] += 1
            for alias in aliases:
                alias_requests.append(
                    repo._AliasSeedRequest(
                        entity_type="benchmark",
                        entity_id=benchmark_id,
                        alias_text=alias,
                        is_official_alias=True,
                    )
                )
    session.flush()

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
    for model_file in model_files:
        # Consume the same strict, fail-closed validation as the preflight so a
        # malformed model file can never silently reconcile. The models loop is
        # symmetric with the benchmark loop above: every row was validated up
        # front exactly once and is written, or the whole run raised before any
        # durable write.
        for model in model_entries_by_file[model_file]:
            model_id = str(model["id"])
            aliases = model.get("aliases") or []
            model_data = {key: value for key, value in model.items() if key in allowed_model_fields}
            repo._upsert_model_entity_from_map(session, model_data, existing_models)
            counts["models"] += 1
            for alias in aliases:
                alias_requests.append(
                    repo._AliasSeedRequest(
                        entity_type="model_entity",
                        entity_id=model_id,
                        alias_text=alias,
                        is_official_alias=True,
                    )
                )
    session.flush()

    # ``counts["aliases"]`` preserves its prior public meaning: the number of
    # manifest alias entries *processed*, not the number of new rows inserted.
    # ``add_aliases_bulk`` inserts only the missing rows but the seed count
    # reports the full processed set (idempotent reseed reports every entry
    # again), matching the pre-batching semantics.
    repo.add_aliases_bulk(session, alias_requests)
    counts["aliases"] += len(alias_requests)

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
    # Reject cross-file benchmark/model identity collisions before any durable
    # write so a contradictory registry cannot silently seed a "first file
    # wins" definition and drop the others. Selecting these files (and their
    # deterministic ordering) happens here, once, and is reused by the change
    # loop below. Each authoritative file is loaded and strictly validated
    # exactly once here; the returned per-file entry snapshots are reused for
    # the durable writes so the write loops never re-read or re-parse the files.
    benchmark_files = _registry_files(benchmarks_path, "benchmarks_curated.yaml")
    model_files = _registry_files(models_path, "models_frontier.yaml")
    benchmark_entries_by_file = _validate_entity_ids(benchmark_files, "benchmarks")
    model_entries_by_file = _validate_entity_ids(model_files, "models")
    # Preserve all-or-nothing behavior for the complete seed operation, even
    # when a library caller catches an error and keeps using its outer session.
    with session.begin_nested():
        return _seed_registry_changes(
            session,
            benchmarks_path=benchmarks_path,
            models_path=models_path,
            benchmark_files=benchmark_files,
            model_files=model_files,
            benchmark_entries_by_file=benchmark_entries_by_file,
            model_entries_by_file=model_entries_by_file,
            source_entries=source_entries,
            source_ids=source_ids,
            retire_missing=retire_missing,
        )
