from __future__ import annotations

import json

from app.db.models import SourceSnapshot
from app.ingestion.adapters.base import SourceAdapter
from app.ingestion.extractors.normalize import try_parse_score
from app.schemas.boundary import ClaimValidationInput, OfficialSource, ResultClaimInput, SourceFetchResult


class LiveCodeBenchAdapter(SourceAdapter):
    source_type = "livecodebench_adapter"
    requires_central_fetch = False

    def fetch(self, source: OfficialSource) -> SourceFetchResult:
        # The old path fetched generated performance records and then chose a
        # date window and calculated an average. That is derived analytics,
        # not one verbatim source-reported result record, so it cannot produce
        # Official claims until a future source-specific certification ticket.
        raise RuntimeError(
            "LiveCodeBench adapter is retired: date-window aggregates cannot produce "
            "Official benchmark result claims."
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
                        "type": "derived_analytics",
                        "model_repr": model_repr,
                        "performances_count": len(filtered),
                    },
                    capture_method="livecodebench_derived_analytics",
                    # Offline fixture parsing can exercise aggregation
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
                validator="LiveCodeBenchAdapter",
                notes="retired date-window aggregate is not source-reported benchmark evidence",
            )
        ]
