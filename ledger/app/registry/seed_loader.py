from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.db import repositories as repo
from app.db import models


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def seed_registry(
    session: Session,
    *,
    benchmarks_path: Path,
    models_path: Path,
    sources_path: Path,
) -> dict[str, int]:
    counts = {"benchmarks": 0, "models": 0, "aliases": 0, "sources": 0}
    
    # Find all benchmarks files matching benchmarks*.yaml in the same directory
    benchmarks_files = sorted(list(benchmarks_path.parent.glob("benchmarks*.yaml"))) if benchmarks_path.parent.exists() else [benchmarks_path]
    if not benchmarks_files:
        benchmarks_files = [benchmarks_path]

    seen_benchmark_ids = set()
    for b_file in benchmarks_files:
        bdoc = _load_yaml(b_file)
        for b in bdoc.get("benchmarks") or []:
            if not isinstance(b, dict) or "id" not in b:
                continue
            b_id = b["id"]
            if b_id in seen_benchmark_ids:
                continue
            seen_benchmark_ids.add(b_id)

            aliases = b.pop("aliases", []) if isinstance(b, dict) else []
            repo.upsert_benchmark(session, b)
            counts["benchmarks"] += 1
            for alias in aliases or []:
                repo.add_alias(session, entity_type="benchmark", entity_id=b["id"], alias_text=alias, is_official_alias=True)
                counts["aliases"] += 1

    # Find all models files matching models*.yaml in the same directory
    models_files = sorted(list(models_path.parent.glob("models*.yaml"))) if models_path.parent.exists() else [models_path]
    if not models_files:
        models_files = [models_path]

    seen_model_ids = set()
    for m_file in models_files:
        mdoc = _load_yaml(m_file)
        for m in mdoc.get("models") or []:
            if not isinstance(m, dict) or "id" not in m:
                continue
            model_id = m["id"]
            if model_id in seen_model_ids:
                continue
            seen_model_ids.add(model_id)

            aliases = m.pop("aliases", []) if isinstance(m, dict) else []
            # only keep model entity fields
            allowed = {
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
            data = {k: v for k, v in m.items() if k in allowed}
            repo.upsert_model_entity(session, data)
            counts["models"] += 1
            for alias in aliases or []:
                repo.add_alias(
                    session,
                    entity_type="model_entity",
                    entity_id=data["id"],
                    alias_text=alias,
                    is_official_alias=True,
                )
                counts["aliases"] += 1

    sdoc = _load_yaml(sources_path)
    # Source registry is the single source of truth for official_sources.
    # Clear all source-derived rows (and their dependents) so re-seeding is
    # idempotent and never collides on (benchmark_id, source_url) with a stale
    # row carried under a different id. FK checks are suspended for the clear
    # because the dependency chain (claims <- validations/review) is wide.
    session.execute(text("PRAGMA foreign_keys=OFF"))
    session.query(models.IngestionRun).delete()
    session.query(models.ResultClaim).delete()
    session.query(models.SourceSnapshot).delete()
    session.query(models.OfficialSourceRow).delete()
    session.execute(text("PRAGMA foreign_keys=ON"))
    session.flush()
    for s in sdoc.get("sources") or []:
        repo.upsert_official_source(session, s)
        counts["sources"] += 1
    return counts
