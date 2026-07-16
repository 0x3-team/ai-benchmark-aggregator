from __future__ import annotations

import json

from app.db.models import SourceSnapshot
from app.ingestion.adapters.base import SourceAdapter
from app.ingestion.extractors.normalize import try_parse_score
from app.schemas.boundary import ClaimValidationInput, OfficialSource, ResultClaimInput, SourceFetchResult


class ArtificialAnalysisAPIAdapter(SourceAdapter):
    source_type = "artificial_analysis_api"
    requires_central_fetch = False

    def fetch(self, source: OfficialSource) -> SourceFetchResult:
        # This adapter's only active source was a third-party aggregate that
        # required private authentication and manufactured mock fallback
        # scores. It is retired until a future one-source certification ticket
        # supplies direct, source-reported evidence and fixture coverage.
        raise RuntimeError(
            "Artificial Analysis adapter is retired: third-party aggregate and mock fallback data "
            "cannot produce benchmark result claims."
        )

    def extract_claims(
        self, source: OfficialSource, snapshot: SourceSnapshot, raw_bytes: bytes
    ) -> list[ResultClaimInput]:
        if source.parser_config.get("mode") == "retired":
            return []
        try:
            data = json.loads(raw_bytes.decode("utf-8"))
        except Exception:
            return []

        models_list = data.get("data", [])
        claims: list[ResultClaimInput] = []

        for i, item in enumerate(models_list):
            if not isinstance(item, dict):
                continue
            model_raw = str(item.get("name") or item.get("id") or "")
            evals = item.get("evaluations") or {}
            score_raw = str(evals.get("intelligence_index") or evals.get("quality_index") or "")
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
                    metric_raw="Intelligence Index",
                    score_numeric=try_parse_score(score_raw) if score_raw else None,
                    evidence_location={
                        "type": "json_path",
                        "path": f"$.data[{i}].evaluations.intelligence_index",
                        "model_path": f"$.data[{i}].name",
                    },
                    capture_method="artificial_analysis_api_parser",
                    # Fixture extraction is retained only for offline parser
                    # mechanics. It is a non-certifying candidate, never an
                    # official claim from this retired third-party route.
                    capture_confidence=0.0,
                    capture_status="unreviewed",
                    officialness_level=source.officialness_level,
                )
            )
        return claims

    def validate_claim(self, claim: ResultClaimInput, raw_bytes: bytes) -> list[ClaimValidationInput]:
        return [
            ClaimValidationInput(
                validation_type="retired_third_party_aggregate",
                outcome="fail",
                validator="ArtificialAnalysisAPIAdapter",
                notes="retired third-party aggregate is not official benchmark result evidence",
            )
        ]
