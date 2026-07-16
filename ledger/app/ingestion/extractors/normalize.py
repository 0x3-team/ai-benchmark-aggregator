from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from app.schemas.boundary import ResultClaimInput


def compute_claim_fingerprint(claim: ResultClaimInput) -> str:
    payload = {
        "official_source_id": str(claim.official_source_id),
        "source_snapshot_id": str(claim.source_snapshot_id) if claim.source_snapshot_id else None,
        "source_revision_decision_id": (
            str(claim.source_revision_decision_id) if claim.source_revision_decision_id else None
        ),
        "model_raw": claim.model_raw,
        "benchmark_raw": claim.benchmark_raw,
        "score_raw": claim.score_raw,
        "metric_raw": claim.metric_raw,
        "split_raw": claim.split_raw,
        "setting_raw": claim.setting_raw,
        "evaluation_version_raw": claim.evaluation_version_raw,
        "rank_raw": claim.rank_raw,
        "date_raw": claim.date_raw,
        "score_unit": claim.score_unit,
        "evidence_location": claim.evidence_location,
    }
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def try_parse_score(score_raw: str) -> float | None:
    if score_raw is None:
        return None
    text = str(score_raw).strip().replace("%", "").replace(",", "")
    m = re.search(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", text)
    if not m:
        return None
    try:
        return float(m.group(0))
    except ValueError:
        return None


def normalize_alias_key(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.lower())
