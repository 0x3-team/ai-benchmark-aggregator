from __future__ import annotations

import csv
import io

from app.db.models import SourceSnapshot
from app.ingestion.adapters.base import SourceAdapter
from app.ingestion.extractors.normalize import try_parse_score
from app.schemas.boundary import ClaimValidationInput, OfficialSource, ResultClaimInput


class GenericCSVAdapter(SourceAdapter):
    source_type = "static_csv"
    accepted_content_types = frozenset({"text/csv", "application/csv"})

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
            model_raw = str(row.get(model_col, "unknown"))
            score_raw = str(row.get(score_col, ""))
            claims.append(
                ResultClaimInput(
                    official_source_id=source.id,
                    source_snapshot_id=snapshot.id,
                    benchmark_id=source.benchmark_id,
                    model_raw=model_raw,
                    benchmark_raw=source.benchmark_id or source.source_name,
                    score_raw=score_raw,
                    metric_raw=str(row.get(metric_col)) if metric_col and row.get(metric_col) is not None else None,
                    score_numeric=try_parse_score(score_raw) if score_raw else None,
                    evidence_location={
                        "type": "csv_cell",
                        "row_index": i,
                        "column_name": score_col,
                        "model_column": model_col,
                    },
                    capture_method="csv_parser",
                    capture_confidence=0.9 if score_raw else 0.2,
                    capture_status="parser_verified" if score_raw else "needs_review",
                    officialness_level=source.officialness_level,
                )
            )
        return claims

    def validate_claim(self, claim: ResultClaimInput, raw_bytes: bytes) -> list[ClaimValidationInput]:
        text = raw_bytes.decode("utf-8", errors="replace")
        outcome = "pass" if claim.score_raw and claim.score_raw in text else "uncertain"
        return [
            ClaimValidationInput(
                validation_type="row_column_match",
                outcome=outcome,
                validator="GenericCSVAdapter",
            )
        ]
