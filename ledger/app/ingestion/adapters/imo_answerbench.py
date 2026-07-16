from __future__ import annotations

import csv
import io

from app.db.models import SourceSnapshot
from app.ingestion.adapters.base import SourceAdapter
from app.ingestion.extractors.normalize import try_parse_score
from app.schemas.boundary import ClaimValidationInput, OfficialSource, ResultClaimInput


class ImoAnswerBenchAdapter(SourceAdapter):
    source_type = "imo_answerbench"
    accepted_content_types = frozenset(
        {"application/json", "application/*+json", "text/json", "text/csv", "application/csv"}
    )

    def extract_claims(
        self,
        source: OfficialSource,
        snapshot: SourceSnapshot,
        raw_bytes: bytes,
    ) -> list[ResultClaimInput]:
        text = raw_bytes.decode("utf-8", errors="replace")

        # Handle HF datasets-server JSON response (wraps rows in JSON)
        import json
        try:
            payload = json.loads(text)
            # datasets-server returns {"rows": [{"row": {...}}, ...]} or {"rows": [...]}
            rows = payload.get("rows", [])
            if rows and isinstance(rows[0], dict):
                first = rows[0]
                if "row" in first and isinstance(first["row"], dict):
                    # Flatten: each row is {"row": {...}}
                    rows = [r["row"] for r in rows]
            # Convert rows to CSV text for DictReader
            if rows:
                output = io.StringIO()
                writer = csv.DictWriter(output, fieldnames=list(rows[0].keys()))
                writer.writeheader()
                writer.writerows(rows)
                text = output.getvalue()
        except (json.JSONDecodeError, KeyError, IndexError):
            pass  # assume plain CSV

        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames:
            return []

        model_field = source.parser_config.get("model_field", "model")
        score_field = source.parser_config.get("score_field", "correct")

        # Group rows by model and compute mean accuracy
        model_scores: dict[str, list[float]] = {}
        for row in reader:
            model = row.get(model_field)
            if not model:
                continue
            score_val = row.get(score_field)
            if score_val is None or score_val == "":
                continue
            try:
                score_num = float(score_val)
            except (ValueError, TypeError):
                continue
            model_scores.setdefault(model, []).append(score_num)

        claims: list[ResultClaimInput] = []
        for model, scores in model_scores.items():
            if not scores:
                continue
            accuracy = sum(scores) / len(scores)
            score_raw = f"{accuracy:.4f}"
            claims.append(
                ResultClaimInput(
                    official_source_id=source.id,
                    source_snapshot_id=snapshot.id,
                    benchmark_id=source.benchmark_id,
                    model_raw=model,
                    benchmark_raw=source.benchmark_id or source.source_name,
                    score_raw=score_raw,
                    metric_raw="accuracy_over_problems",
                    score_numeric=accuracy,
                    evidence_location={
                        "type": "imo_answerbench_csv",
                        "model": model,
                        "num_problems": len(scores),
                    },
                    capture_method="imo_answerbench_parser",
                    capture_confidence=0.9,
                    capture_status="parser_verified",
                    officialness_level=source.officialness_level,
                )
            )
        return claims

    def validate_claim(
        self, claim: ResultClaimInput, raw_bytes: bytes
    ) -> list[ClaimValidationInput]:
        try:
            text = raw_bytes.decode("utf-8", errors="replace")
        except Exception:
            text = ""
        outcome = "pass" if claim.score_raw and claim.score_raw in text else "uncertain"
        return [
            ClaimValidationInput(
                validation_type="imo_csv_match",
                outcome=outcome,
                validator="ImoAnswerBenchAdapter",
            )
        ]
