from __future__ import annotations

import json

from app.db.models import SourceSnapshot
from app.ingestion.adapters.base import SourceAdapter
from app.schemas.boundary import ClaimValidationInput, OfficialSource, ResultClaimInput, SourceFetchResult


class LiveBenchAdapter(SourceAdapter):
    source_type = "livebench_adapter"
    requires_central_fetch = False

    def fetch(self, source: OfficialSource) -> SourceFetchResult:
        # The old path assembled a homepage, JavaScript bundle, CSV, and
        # categories JSON, then calculated a score. That is derived analytics,
        # not one verbatim source-reported result record, so it cannot produce
        # Official claims until a future source-specific certification ticket.
        raise RuntimeError(
            "LiveBench adapter is retired: assembled artifacts and derived aggregates "
            "cannot produce Official benchmark result claims."
        )

    def extract_claims(
        self, source: OfficialSource, snapshot: SourceSnapshot, raw_bytes: bytes
    ) -> list[ResultClaimInput]:
        import csv
        from io import StringIO
        from app.ingestion.extractors.normalize import try_parse_score

        if source.parser_config.get("mode") == "retired":
            return []
        try:
            payload = json.loads(raw_bytes.decode("utf-8"))
        except Exception:
            return []

        csv_text = payload.get("csv", "")
        categories = payload.get("categories", {})
        if not csv_text or not categories:
            return []

        # Read CSV rows
        f = StringIO(csv_text.strip())
        reader = csv.DictReader(f)
        claims: list[ResultClaimInput] = []

        for row in reader:
            model_raw = row.get("model")
            if not model_raw:
                continue

            # Compute category averages
            cat_averages = []
            for cat_name, tasks in categories.items():
                task_scores = []
                for t in tasks:
                    val = row.get(t)
                    if val is not None and val != "" and val != "-":
                        try:
                            task_scores.append(float(val))
                        except ValueError:
                            pass
                if task_scores:
                    cat_avg = sum(task_scores) / len(task_scores)
                    cat_averages.append(cat_avg)

            if not cat_averages:
                continue

            # Compute overall score (average of category averages)
            overall_score = sum(cat_averages) / len(cat_averages)
            score_raw = f"{overall_score:.2f}"

            claims.append(
                ResultClaimInput(
                    official_source_id=source.id,
                    source_snapshot_id=snapshot.id,
                    benchmark_id=source.benchmark_id,
                    model_raw=model_raw,
                    benchmark_raw=source.benchmark_id or source.source_name,
                    score_raw=score_raw,
                    metric_raw="overall",
                    score_numeric=try_parse_score(score_raw),
                    evidence_location={
                        "type": "derived_analytics",
                        "model": model_raw,
                        "version": payload.get("version"),
                        "categories_computed": len(cat_averages),
                    },
                    capture_method="livebench_derived_analytics",
                    # Offline fixture parsing can exercise the aggregation
                    # mechanics, but the calculated value is never a
                    # source-reported Official claim.
                    capture_confidence=0.0,
                    capture_status="unreviewed",
                    officialness_level=source.officialness_level,
                )
            )
        return claims

    def validate_claim(self, claim: ResultClaimInput, raw_bytes: bytes) -> list[ClaimValidationInput]:
        return [
            ClaimValidationInput(
                validation_type="derived_aggregate",
                outcome="fail",
                validator="LiveBenchAdapter",
                notes="retired derived aggregate is not source-reported benchmark evidence",
            )
        ]
