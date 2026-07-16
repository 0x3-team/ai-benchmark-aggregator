from __future__ import annotations

import json
from typing import Any

from app.db.models import SourceSnapshot
from app.ingestion.adapters.base import SourceAdapter
from app.ingestion.extractors.normalize import try_parse_score
from app.schemas.boundary import (
    ClaimValidationInput,
    OfficialSource,
    ResultClaimInput,
)


class HFBenchmarkAPIAdapter(SourceAdapter):
    source_type = "hf_benchmark_api"
    accepted_content_types = frozenset({"application/json", "application/*+json", "text/json"})

    def fetch(self, source: OfficialSource):  # type: ignore[no-untyped-def]
        mode = source.parser_config.get("mode", "discovery")
        if mode == "discovery":
            # Dataset discovery is useful catalogue metadata, but it is never
            # an official model-result feed. Refuse before any network request
            # so this retired route cannot be revived by a direct adapter call.
            raise RuntimeError(
                "HF benchmark discovery mode is retired: dataset metadata cannot produce result claims."
            )
        # A source revision must name the actual endpoint. URL construction or
        # token attachment in an adapter would evade the immutable allowlist.
        return super().fetch(source)

    def extract_claims(
        self,
        source: OfficialSource,
        snapshot: SourceSnapshot,
        raw_bytes: bytes,
    ) -> list[ResultClaimInput]:
        data = json.loads(raw_bytes.decode("utf-8"))
        mode = source.parser_config.get("mode", "discovery")
        if mode == "discovery":
            # Existing raw discovery snapshots may still be retained as
            # evidence, but extraction must never reinterpret a dataset name
            # as a model or fabricate a pseudo-score such as "n/a".
            return []

        # leaderboard mode
        rows = data if isinstance(data, list) else data.get("leaderboard") or data.get("entries") or []
        claims = []
        for i, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            model_raw = str(row.get("model_id") or row.get("model") or row.get("fullname") or "unknown")
            value = row.get("value")
            if value is None:
                value = row.get("score")
            score_raw = str(value) if value is not None else ""
            rank_raw = str(row["rank"]) if row.get("rank") is not None else None
            claims.append(
                ResultClaimInput(
                    official_source_id=source.id,
                    source_snapshot_id=snapshot.id,
                    benchmark_id=source.benchmark_id,
                    model_raw=model_raw,
                    benchmark_raw=source.parser_config.get("dataset_id") or source.benchmark_id or source.source_name,
                    score_raw=score_raw,
                    metric_raw=str(row.get("metric")) if row.get("metric") is not None else None,
                    rank_raw=rank_raw,
                    score_numeric=try_parse_score(score_raw) if score_raw else None,
                    evidence_location={
                        "type": "json_path",
                        "path": f"$[{i}].value",
                        "model_path": f"$[{i}].model_id",
                        "rank_path": f"$[{i}].rank",
                    },
                    capture_method="hf_api",
                    capture_confidence=0.95,
                    capture_status="parser_verified" if score_raw else "needs_review",
                    officialness_level=source.officialness_level,
                    evidence_text=json.dumps(
                        {k: row.get(k) for k in ("source", "filename", "pull_request", "notes", "verified") if k in row}
                    )
                    or None,
                )
            )
        return claims

    def validate_claim(self, claim: ResultClaimInput, raw_bytes: bytes) -> list[ClaimValidationInput]:
        if claim.score_raw == "n/a":
            return [
                ClaimValidationInput(
                    validation_type="retired_discovery_metadata",
                    outcome="fail",
                    validator="HFBenchmarkAPIAdapter",
                    notes="dataset discovery metadata is not a benchmark result claim",
                )
            ]
        try:
            data = json.loads(raw_bytes.decode("utf-8"))
        except json.JSONDecodeError:
            return [
                ClaimValidationInput(
                    validation_type="json_path_match",
                    outcome="fail",
                    validator="HFBenchmarkAPIAdapter",
                    notes="invalid json",
                )
            ]
        rows = data if isinstance(data, list) else data.get("leaderboard") or data.get("entries") or []
        for row in rows:
            if not isinstance(row, dict):
                continue
            model = str(row.get("model_id") or row.get("model") or row.get("fullname") or "")
            value = row.get("value")
            if value is None:
                value = row.get("score")
            if model == claim.model_raw and str(value) == claim.score_raw:
                return [
                    ClaimValidationInput(
                        validation_type="json_path_match",
                        outcome="pass",
                        validator="HFBenchmarkAPIAdapter",
                    )
                ]
        return [
            ClaimValidationInput(
                validation_type="json_path_match",
                outcome="uncertain",
                validator="HFBenchmarkAPIAdapter",
            )
        ]
