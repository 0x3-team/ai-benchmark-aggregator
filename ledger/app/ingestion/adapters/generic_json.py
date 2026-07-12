from __future__ import annotations

import json
from typing import Any

from app.db.models import SourceSnapshot
from app.ingestion.adapters.base import SourceAdapter
from app.ingestion.extractors.normalize import try_parse_score
from app.schemas.boundary import ClaimValidationInput, OfficialSource, ResultClaimInput, SourceFetchResult


class GenericJSONAdapter(SourceAdapter):
    source_type = "static_json"

    def fetch(self, source: OfficialSource) -> SourceFetchResult:
        import httpx
        from app.config import get_settings

        settings = get_settings()
        with httpx.Client(timeout=settings.http_timeout_seconds, follow_redirects=True) as client:
            resp = client.get(source.source_url, headers={"User-Agent": settings.http_user_agent})
            return SourceFetchResult(
                raw_bytes=resp.content,
                content_type=resp.headers.get("content-type"),
                http_status=resp.status_code,
                etag=resp.headers.get("etag"),
                last_modified_header=resp.headers.get("last-modified"),
                final_url=str(resp.url),
            )

    def _rows(self, data: Any, cfg: dict[str, Any]) -> list[Any]:
        path = cfg.get("records_path") or cfg.get("row_path")
        if not path:
            if isinstance(data, list):
                return data
            return data.get("results") or data.get("leaderboard") or data.get("data") or []
        cur: Any = data
        for part in path.strip("$.").split("."):
            if not part:
                continue
            if isinstance(cur, dict):
                cur = cur.get(part)
            else:
                return []
        return cur if isinstance(cur, list) else []

    def extract_claims(
        self, source: OfficialSource, snapshot: SourceSnapshot, raw_bytes: bytes
    ) -> list[ResultClaimInput]:
        cfg = source.parser_config or {}
        try:
            data = json.loads(raw_bytes.decode("utf-8"))
        except json.JSONDecodeError:
            return []
        model_field = cfg.get("model_field", "model")
        score_field = cfg.get("score_field", "score")
        metric_field = cfg.get("metric_field")
        split_field = cfg.get("split_field")
        rank_field = cfg.get("rank_field")
        benchmark_field = cfg.get("benchmark_field")
        claims: list[ResultClaimInput] = []
        for i, row in enumerate(self._rows(data, cfg)):
            if not isinstance(row, dict):
                continue
            model_raw = str(row.get(model_field, "unknown"))
            score_raw = str(row.get(score_field, ""))
            claims.append(
                ResultClaimInput(
                    official_source_id=source.id,
                    source_snapshot_id=snapshot.id,
                    benchmark_id=source.benchmark_id,
                    model_raw=model_raw,
                    benchmark_raw=str(row.get(benchmark_field)) if benchmark_field and row.get(benchmark_field) else (source.benchmark_id or source.source_name),
                    score_raw=score_raw,
                    metric_raw=str(row.get(metric_field)) if metric_field and row.get(metric_field) is not None else None,
                    split_raw=str(row.get(split_field)) if split_field and row.get(split_field) is not None else None,
                    rank_raw=str(row.get(rank_field)) if rank_field and row.get(rank_field) is not None else None,
                    score_numeric=try_parse_score(score_raw) if score_raw else None,
                    evidence_location={"type": "json_path", "path": f"$.records[{i}].{score_field}", "model_path": f"$.records[{i}].{model_field}"},
                    capture_method="json_parser",
                    capture_confidence=0.9 if score_raw else 0.2,
                    capture_status="parser_verified" if score_raw else "needs_review",
                    officialness_level=source.officialness_level,
                )
            )
        return claims

    def validate_claim(self, claim: ResultClaimInput, raw_bytes: bytes) -> list[ClaimValidationInput]:
        try:
            text = raw_bytes.decode("utf-8")
        except Exception:
            text = ""
        outcome = "pass" if claim.score_raw and claim.score_raw in text else "uncertain"
        return [
            ClaimValidationInput(
                validation_type="json_path_match",
                outcome=outcome,
                validator="GenericJSONAdapter",
            )
        ]
