from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models


def export_official_json(session: Session, out_path: Path) -> dict[str, Any]:
    """Export verified-ish claims for dashboard official mode."""
    # Load frontier IDs to mark them featured
    frontier_ids = set()
    frontier_path = Path(__file__).parent.parent / "registry" / "models_frontier.yaml"
    if frontier_path.exists():
        import yaml
        try:
            with frontier_path.open("r", encoding="utf-8") as f:
                frontier_data = yaml.safe_load(f) or {}
                for m in frontier_data.get("models") or []:
                    if "id" in m:
                        frontier_ids.add(m["id"])
        except Exception:
            pass

    claims = list(
        session.scalars(
            select(models.ResultClaim).where(
                models.ResultClaim.capture_status.in_(
                    ["parser_verified", "double_verified", "human_verified", "needs_review"]
                )
            )
        )
    )
    models_map: dict[str, dict[str, Any]] = {}
    benches_map: dict[str, dict[str, Any]] = {}
    scores: list[dict[str, Any]] = []

    # First add all registered ModelEntities in the DB
    for ent in session.scalars(select(models.ModelEntity)).all():
        models_map[ent.id] = {
            "id": ent.id,
            "name": ent.display_name,
            "vendor": ent.provider or "unknown",
            "family": ent.model_family or "unknown",
            "raw_name": ent.canonical_name,
            "featured": ent.id in frontier_ids,
        }

    for c in claims:
        mid = c.model_entity_id or f"raw::{c.model_raw}"
        bid = c.benchmark_id or f"raw::{c.benchmark_raw}"
        if mid not in models_map:
            ent = session.get(models.ModelEntity, c.model_entity_id) if c.model_entity_id else None
            models_map[mid] = {
                "id": mid,
                "name": ent.display_name if ent else c.model_raw,
                "vendor": ent.provider if ent else "unknown",
                "family": ent.model_family if ent else "unknown",
                "raw_name": c.model_raw,
                "featured": mid in frontier_ids,
            }
        if bid not in benches_map:
            b = session.get(models.Benchmark, c.benchmark_id) if c.benchmark_id else None
            benches_map[bid] = {
                "id": bid,
                "name": b.display_name if b else c.benchmark_raw,
                "fullName": b.canonical_name if b else c.benchmark_raw,
                "category": (b.benchmark_family if b else "unknown") or "unknown",
                "higherIsBetter": True,
                "scaleMax": 100,
                "primaryMetric": b.primary_metric if b else c.metric_raw,
            }
        scores.append(
            {
                "modelId": mid,
                "benchmarkId": bid,
                "value": c.score_numeric,
                "scoreRaw": c.score_raw,
                "date": c.date_raw,
                "captureStatus": c.capture_status,
                "officialSourceId": c.official_source_id,
                "sourceSnapshotId": c.source_snapshot_id,
                "evidenceLocation": c.evidence_location,
                "claimId": c.id,
            }
        )

    payload = {
        "schemaVersion": "0.1.0",
        "trustLevel": "official_claims",
        "models": list(models_map.values()),
        "benchmarks": list(benches_map.values()),
        "scores": scores,
        "note": "Values are source-backed claims, not independently recalculated scores.",
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload
