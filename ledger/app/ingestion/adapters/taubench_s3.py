from __future__ import annotations

import json

from app.db.models import SourceSnapshot
from app.ingestion.adapters.base import SourceAdapter
from app.schemas.boundary import (
    ClaimValidationInput,
    OfficialSource,
    ResultClaimInput,
    SourceFetchResult,
)

class TauBenchS3Adapter(SourceAdapter):
    source_type = "taubench_s3"
    requires_central_fetch = False

    def fetch(self, source: OfficialSource) -> SourceFetchResult:
        # The old path listed S3 submissions and calculated a mean pass rate.
        # That is derived analytics, not one verbatim source-reported result
        # record, so it cannot produce Official claims until a future
        # source-specific certification ticket.
        raise RuntimeError(
            "TauBench adapter is retired: aggregated submission metrics cannot produce "
            "Official benchmark result claims."
        )

    def extract_claims(
        self,
        source: OfficialSource,
        snapshot: SourceSnapshot,
        raw_bytes: bytes,
    ) -> list[ResultClaimInput]:
        if source.parser_config.get("mode") == "retired":
            return []
        claims_by_model: dict[str, list[float]] = {}  # model_raw -> [pass_rate, ...]

        for line in raw_bytes.split(b"\n"):
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line.decode("utf-8"))
            except json.JSONDecodeError:
                continue

            model = data.get("model") or data.get("model_name") or data.get("model_id")
            if not model:
                continue

            model = str(model)
            results = data.get("results", {})
            if not isinstance(results, dict):
                continue

            for domain, domain_results in results.items():
                if not isinstance(domain_results, dict):
                    continue
                for metric_name, metric_value in domain_results.items():
                    if isinstance(metric_name, str) and metric_name.startswith("pass_"):
                        try:
                            val = float(metric_value)
                            claims_by_model.setdefault(model, []).append(val)
                        except (TypeError, ValueError):
                            continue

        claims: list[ResultClaimInput] = []
        for model_raw, pass_values in claims_by_model.items():
            if not pass_values:
                continue
            mean = sum(pass_values) / len(pass_values)
            claims.append(
                ResultClaimInput(
                    official_source_id=source.id,
                    source_snapshot_id=snapshot.id,
                    benchmark_id=source.benchmark_id,
                    model_raw=model_raw,
                    benchmark_raw=source.benchmark_id or source.source_name,
                    score_raw=f"{mean:.4f}",
                    metric_raw="mean_pass_rate",
                    score_numeric=mean,
                    evidence_location={
                        "type": "derived_analytics",
                        "model": model_raw,
                    },
                    capture_method="taubench_derived_analytics",
                    # Offline fixture parsing can exercise aggregation
                    # mechanics, but the calculated value is never a
                    # source-reported Official claim.
                    capture_confidence=0.0,
                    capture_status="unreviewed",
                    officialness_level=source.officialness_level,
                )
            )
        return claims

    def validate_claim(
        self, claim: ResultClaimInput, raw_bytes: bytes
    ) -> list[ClaimValidationInput]:
        return [
            ClaimValidationInput(
                validation_type="derived_aggregate",
                outcome="fail",
                validator="TauBenchS3Adapter",
                notes="retired aggregate is not source-reported benchmark evidence",
            )
        ]
