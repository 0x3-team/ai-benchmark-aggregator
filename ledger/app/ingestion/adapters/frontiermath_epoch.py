from __future__ import annotations

import csv
import io

import httpx

from app.db.models import SourceSnapshot
from app.ingestion.adapters.base import SourceAdapter
from app.ingestion.extractors.normalize import try_parse_score
from app.schemas.boundary import ClaimValidationInput, OfficialSource, ResultClaimInput, SourceFetchResult


class FrontierMathEpochAdapter(SourceAdapter):
    source_type = "frontiermath_epoch"

    def fetch(self, source: OfficialSource) -> SourceFetchResult:
        from app.config import get_settings

        settings = get_settings()
        try:
            with httpx.Client(timeout=settings.http_timeout_seconds, follow_redirects=True) as client:
                resp = client.get(source.source_url, headers={"User-Agent": settings.http_user_agent})
                resp.raise_for_status()
                return SourceFetchResult(
                    raw_bytes=resp.content,
                    content_type=resp.headers.get("content-type", "text/csv"),
                    http_status=resp.status_code,
                    final_url=str(resp.url),
                )
        except Exception as exc:
            raise RuntimeError(f"Fetch failed for {source.id}: {exc}") from exc

    def extract_claims(
        self, source: OfficialSource, snapshot: SourceSnapshot, raw_bytes: bytes
    ) -> list[ResultClaimInput]:
        cfg = source.parser_config or {}
        model_col = cfg.get("model_field", "model")
        score_col = cfg.get("score_field", "score")
        metric_col = cfg.get("metric_field")

        text = raw_bytes.decode("utf-8", errors="replace")
        reader = csv.DictReader(io.StringIO(text))
        claims: list[ResultClaimInput] = []

        for i, row in enumerate(reader):
            model_raw = str(row.get(model_col, "")).strip()
            if not model_raw:
                continue
            score_raw = str(row.get(score_col, "")).strip()
            if not score_raw:
                continue

            claims.append(
                ResultClaimInput(
                    official_source_id=source.id,
                    source_snapshot_id=snapshot.id,
                    benchmark_id=source.benchmark_id,
                    model_raw=model_raw,
                    benchmark_raw=source.benchmark_id or source.source_name,
                    score_raw=score_raw,
                    metric_raw=metric_col if metric_col else score_col,
                    score_numeric=try_parse_score(score_raw),
                    evidence_location={
                        "type": "csv_cell",
                        "row_index": i,
                        "column_name": score_col,
                        "model_column": model_col,
                    },
                    capture_method="frontiermath_epoch_parser",
                    capture_confidence=0.9,
                    capture_status="parser_verified",
                    officialness_level=source.officialness_level,
                )
            )
        return claims

    def validate_claim(self, claim: ResultClaimInput, raw_bytes: bytes) -> list[ClaimValidationInput]:
        try:
            text = raw_bytes.decode("utf-8", errors="replace")
        except Exception:
            text = ""
        if claim.score_raw and claim.score_raw in text:
            outcome = "pass"
        else:
            outcome = "uncertain"
        return [
            ClaimValidationInput(
                validation_type="fm_csv_match",
                outcome=outcome,
                validator="FrontierMathEpochAdapter",
            )
        ]
