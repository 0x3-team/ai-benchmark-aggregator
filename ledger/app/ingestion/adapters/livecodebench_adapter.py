from __future__ import annotations

import json
from typing import Any

import httpx

from app.db.models import SourceSnapshot
from app.ingestion.adapters.base import SourceAdapter
from app.ingestion.extractors.normalize import try_parse_score
from app.schemas.boundary import ClaimValidationInput, OfficialSource, ResultClaimInput, SourceFetchResult


class LiveCodeBenchAdapter(SourceAdapter):
    source_type = "livecodebench_adapter"

    def fetch(self, source: OfficialSource) -> SourceFetchResult:
        from app.config import get_settings
        settings = get_settings()
        url = source.source_url
        if "leaderboard.html" in url:
            url = url.replace("leaderboard.html", "performances_generation.json")
        try:
            with httpx.Client(timeout=settings.http_timeout_seconds, follow_redirects=True) as client:
                resp = client.get(url, headers={"User-Agent": settings.http_user_agent})
                resp.raise_for_status()
                return SourceFetchResult(
                    raw_bytes=resp.content,
                    content_type="application/json",
                    http_status=resp.status_code,
                    final_url=str(resp.url),
                )
        except Exception as exc:
            raise RuntimeError(f"Fetch failed for {source.id}: {exc}") from exc

    def extract_claims(
        self, source: OfficialSource, snapshot: SourceSnapshot, raw_bytes: bytes
    ) -> list[ResultClaimInput]:
        try:
            data = json.loads(raw_bytes.decode("utf-8"))
        except Exception:
            return []

        models_list = data.get("models", [])
        performances = data.get("performances", [])
        date_marks = sorted(data.get("date_marks", []))

        # Use default date filtering to match the webpage's default view
        # React: (dateMarks.length > 12) ? dateMarks[15].value : dateMarks[4].value
        start_date = 0
        end_date = 9999999999999
        if date_marks:
            initial_start_idx = 15 if len(date_marks) > 12 else (4 if len(date_marks) > 4 else 0)
            if initial_start_idx < len(date_marks):
                start_date = date_marks[initial_start_idx]
            end_date = date_marks[-1]

        claims: list[ResultClaimInput] = []

        for i, m_info in enumerate(models_list):
            if not isinstance(m_info, dict):
                continue
            model_repr = m_info.get("model_repr")
            if not model_repr:
                continue

            # Filter performances for this model within the timeframe
            filtered = [
                p for p in performances
                if isinstance(p, dict) and p.get("model") == model_repr and p.get("date", 0) >= start_date and p.get("date", 0) <= end_date
            ]

            if not filtered:
                # Try without date filter just in case
                filtered = [
                    p for p in performances
                    if isinstance(p, dict) and p.get("model") == model_repr
                ]

            if not filtered:
                continue

            pass1_vals = [p.get("pass@1") for p in filtered if p.get("pass@1") is not None]
            if not pass1_vals:
                continue

            avg_pass = sum(pass1_vals) / len(pass1_vals)
            score_raw = f"{avg_pass:.1f}"

            claims.append(
                ResultClaimInput(
                    official_source_id=source.id,
                    source_snapshot_id=snapshot.id,
                    benchmark_id=source.benchmark_id,
                    model_raw=model_repr,
                    benchmark_raw=source.benchmark_id or source.source_name,
                    score_raw=score_raw,
                    metric_raw="Pass@1",
                    score_numeric=try_parse_score(score_raw) if score_raw else None,
                    evidence_location={
                        "type": "aggregated_json",
                        "model_repr": model_repr,
                        "performances_count": len(filtered),
                    },
                    capture_method="livecodebench_adapter_parser",
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
        outcome = "pass" if claim.model_raw and claim.model_raw in text else "uncertain"
        return [
            ClaimValidationInput(
                validation_type="json_path_match",
                outcome=outcome,
                validator="LiveCodeBenchAdapter",
            )
        ]
