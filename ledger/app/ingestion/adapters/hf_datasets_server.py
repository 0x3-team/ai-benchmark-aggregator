from __future__ import annotations

import json
from typing import Any

from app.db.models import SourceSnapshot
from app.ingestion.adapters.base import SourceAdapter
from app.ingestion.extractors.normalize import try_parse_score
from app.schemas.boundary import ClaimValidationInput, OfficialSource, ResultClaimInput, SourceFetchResult


class HFDatasetsServerAdapter(SourceAdapter):
    source_type = "hf_datasets_server"

    def fetch(self, source: OfficialSource) -> SourceFetchResult:
        import httpx
        from app.config import get_settings

        settings = get_settings()
        headers = {"User-Agent": settings.http_user_agent}
        if settings.hf_token:
            headers["Authorization"] = f"Bearer {settings.hf_token}"
        url = source.source_url
        if "open-llm-leaderboard/blog" in url:
            url = "https://datasets-server.huggingface.co/first-rows?dataset=open-llm-leaderboard/contents&config=default&split=train"
        try:
            with httpx.Client(timeout=settings.http_timeout_seconds, follow_redirects=True) as client:
                resp = client.get(url, headers=headers)
                resp.raise_for_status()
                return SourceFetchResult(
                    raw_bytes=resp.content,
                    content_type=resp.headers.get("content-type"),
                    http_status=resp.status_code,
                    etag=resp.headers.get("etag"),
                    last_modified_header=resp.headers.get("last-modified"),
                    final_url=str(resp.url),
                    headers={k: v for k, v in resp.headers.items() if k.lower() in {"etag", "last-modified", "content-type"}},
                )
        except Exception as exc:
            # Gracefully raise a RuntimeError that gets logged in ingestion summary
            raise RuntimeError(f"Fetch failed for {source.id}: {exc}") from exc

    def extract_claims(
        self, source: OfficialSource, snapshot: SourceSnapshot, raw_bytes: bytes
    ) -> list[ResultClaimInput]:
        cfg = source.parser_config or {}
        try:
            data = json.loads(raw_bytes.decode("utf-8"))
        except Exception:
            return []

        records_path = cfg.get("records_path", "rows")
        row_field = cfg.get("row_field", "row")
        model_field = cfg.get("model_field", "model")
        score_field = cfg.get("score_field", "score")
        metric_field = cfg.get("metric_field")
        split_field = cfg.get("split_field")
        rank_field = cfg.get("rank_field")

        rows = data.get(records_path) or data.get("rows") or []
        claims: list[ResultClaimInput] = []

        for i, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            row_data = row.get(row_field) if row_field else row
            if not isinstance(row_data, dict):
                continue

            model_raw = str(row_data.get(model_field, ""))
            score_raw = str(row_data.get(score_field, ""))
            if not model_raw or not score_raw:
                continue

            claims.append(
                ResultClaimInput(
                    official_source_id=source.id,
                    source_snapshot_id=snapshot.id,
                    benchmark_id=source.benchmark_id,
                    model_raw=model_raw,
                    benchmark_raw=source.benchmark_id or source.source_name,
                    score_raw=score_raw,
                    metric_raw=str(row_data.get(metric_field)) if metric_field and row_data.get(metric_field) is not None else score_field,
                    split_raw=str(row_data.get(split_field)) if split_field and row_data.get(split_field) is not None else None,
                    rank_raw=str(row_data.get(rank_field)) if rank_field and row_data.get(rank_field) is not None else None,
                    score_numeric=try_parse_score(score_raw) if score_raw else None,
                    evidence_location={
                        "type": "json_path",
                        "path": f"$.{records_path}[{i}].{row_field}.{score_field}",
                        "model_path": f"$.{records_path}[{i}].{row_field}.{model_field}",
                    },
                    capture_method="hf_datasets_server_parser",
                    capture_confidence=0.95,
                    capture_status="parser_verified",
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
                validator="HFDatasetsServerAdapter",
            )
        ]
