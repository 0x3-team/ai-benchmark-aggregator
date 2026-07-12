from __future__ import annotations

import json
from typing import Any

from bs4 import BeautifulSoup
import httpx

from app.db.models import SourceSnapshot
from app.ingestion.adapters.base import SourceAdapter
from app.ingestion.extractors.normalize import try_parse_score
from app.schemas.boundary import ClaimValidationInput, OfficialSource, ResultClaimInput, SourceFetchResult


class SWEBenchAdapter(SourceAdapter):
    source_type = "swe_bench_adapter"

    def fetch(self, source: OfficialSource) -> SourceFetchResult:
        from app.config import get_settings
        settings = get_settings()
        try:
            with httpx.Client(timeout=settings.http_timeout_seconds, follow_redirects=True) as client:
                resp = client.get(source.source_url, headers={"User-Agent": settings.http_user_agent})
                resp.raise_for_status()
                return SourceFetchResult(
                    raw_bytes=resp.content,
                    content_type=resp.headers.get("content-type", "text/html"),
                    http_status=resp.status_code,
                    final_url=str(resp.url),
                )
        except Exception as exc:
            raise RuntimeError(f"Fetch failed for {source.id}: {exc}") from exc

    def extract_claims(
        self, source: OfficialSource, snapshot: SourceSnapshot, raw_bytes: bytes
    ) -> list[ResultClaimInput]:
        soup = BeautifulSoup(raw_bytes, "lxml")
        script_tag = soup.find("script", id="leaderboard-data")
        if not script_tag:
            return []

        try:
            data = json.loads(script_tag.text)
        except Exception:
            return []

        category_name = source.parser_config.get("category", "Verified")
        category_data = None
        for cat in data:
            if isinstance(cat, dict) and cat.get("name") == category_name:
                category_data = cat
                break

        if not category_data:
            return []

        results = category_data.get("results", [])
        claims: list[ResultClaimInput] = []

        for i, row in enumerate(results):
            if not isinstance(row, dict):
                continue
            model_raw = str(row.get("name", ""))
            score_raw = str(row.get("resolved", ""))
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
                    metric_raw="% Resolved",
                    score_numeric=try_parse_score(score_raw) if score_raw else None,
                    evidence_location={
                        "type": "json_script_path",
                        "script_id": "leaderboard-data",
                        "category": category_name,
                        "row_index": i,
                    },
                    capture_method="swe_bench_adapter_parser",
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
                validator="SWEBenchAdapter",
            )
        ]
