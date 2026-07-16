from __future__ import annotations

import json

from app.db.models import SourceSnapshot
from app.ingestion.adapters.base import SourceAdapter
from app.ingestion.extractors.normalize import try_parse_score
from app.schemas.boundary import ClaimValidationInput, OfficialSource, ResultClaimInput, SourceFetchResult


class LMSYSArenaAPIAdapter(SourceAdapter):
    source_type = "lmsys_arena_api"
    requires_central_fetch = False

    def fetch(self, source: OfficialSource) -> SourceFetchResult:
        # The former production route retried an LM Arena URL through an
        # unrelated third-party endpoint. It cannot establish that an
        # Official claim was directly reported by its declared source, so it
        # remains retired until a future one-source certification ticket
        # supplies typed direct evidence and fixture coverage.
        raise RuntimeError(
            "LMSYS Arena adapter is retired: a third-party fallback route cannot produce "
            "official benchmark result claims."
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

        models_list = data.get("models", [])
        claims: list[ResultClaimInput] = []

        for i, item in enumerate(models_list):
            if not isinstance(item, dict):
                continue
            # LMSYS fields: rank, model, score (Elo), vendor/org
            model_raw = str(item.get("model", ""))
            score_raw = str(item.get("score", ""))
            if not model_raw or not score_raw:
                continue

            rank_raw = str(item.get("rank")) if item.get("rank") is not None else None

            claims.append(
                ResultClaimInput(
                    official_source_id=source.id,
                    source_snapshot_id=snapshot.id,
                    benchmark_id=source.benchmark_id,
                    model_raw=model_raw,
                    benchmark_raw=source.benchmark_id or source.source_name,
                    score_raw=score_raw,
                    metric_raw="Elo",
                    rank_raw=rank_raw,
                    score_numeric=try_parse_score(score_raw) if score_raw else None,
                    evidence_location={
                        "type": "json_path",
                        "path": f"$.models[{i}].score",
                        "model_path": f"$.models[{i}].model",
                        "rank_path": f"$.models[{i}].rank",
                    },
                    capture_method="lmsys_arena_api_parser",
                    # Fixture parsing is retained only for offline parser
                    # mechanics. It is a non-certifying candidate, never an
                    # Official claim from this retired fallback route.
                    capture_confidence=0.0,
                    capture_status="unreviewed",
                    officialness_level=source.officialness_level,
                )
            )
        return claims

    def validate_claim(self, claim: ResultClaimInput, raw_bytes: bytes) -> list[ClaimValidationInput]:
        return [
            ClaimValidationInput(
                validation_type="retired_fallback_route",
                outcome="fail",
                validator="LMSYSArenaAPIAdapter",
                notes="retired fallback route is not official benchmark result evidence",
            )
        ]
