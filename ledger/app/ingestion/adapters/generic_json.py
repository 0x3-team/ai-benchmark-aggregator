from __future__ import annotations

from typing import Any

from app.db.models import SourceSnapshot
from app.ingestion.adapters.base import SourceAdapter
from app.ingestion.json_lexemes import (
    JsonLexemeError,
    canonical_config_json_path,
    decode_json_bytes,
    resolve_json_path,
    source_score_lexeme,
    source_text,
)
from app.schemas.boundary import ClaimValidationInput, OfficialSource, ResultClaimInput


class GenericJSONAdapter(SourceAdapter):
    source_type = "static_json"
    accepted_content_types = frozenset({"application/json", "application/*+json", "text/json"})

    def _rows(self, data: Any, cfg: dict[str, Any]) -> tuple[str, list[Any]] | None:
        records_path = cfg.get("records_path")
        row_path = cfg.get("row_path")
        if records_path is not None and row_path is not None and records_path != row_path:
            return None
        collection_path = canonical_config_json_path(
            records_path if records_path is not None else row_path
        )
        if collection_path is None:
            return None
        rows, error = resolve_json_path(data, collection_path)
        if error or not isinstance(rows, list):
            return None
        return collection_path, rows

    def extract_claims(
        self, source: OfficialSource, snapshot: SourceSnapshot, raw_bytes: bytes
    ) -> list[ResultClaimInput]:
        cfg = source.parser_config or {}
        try:
            data = decode_json_bytes(raw_bytes)
        except JsonLexemeError:
            return []
        rows_with_path = self._rows(data, cfg)
        if rows_with_path is None:
            return []
        collection_path, rows = rows_with_path
        model_field = cfg.get("model_field")
        score_field = cfg.get("score_field")
        if not isinstance(model_field, str) or not model_field or not isinstance(score_field, str) or not score_field:
            return []
        metric_field = cfg.get("metric_field")
        split_field = cfg.get("split_field")
        rank_field = cfg.get("rank_field")
        benchmark_field = cfg.get("benchmark_field")
        optional_fields = {
            "metric_raw": metric_field,
            "split_raw": split_field,
            "rank_raw": rank_field,
            "benchmark_raw": benchmark_field,
        }
        if any(field is not None and (not isinstance(field, str) or not field) for field in optional_fields.values()):
            return []
        claims: list[ResultClaimInput] = []
        for i, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            model_raw = source_text(row.get(model_field))
            score_raw = source_score_lexeme(row.get(score_field))
            if model_raw is None or score_raw is None:
                continue
            benchmark_raw = (
                source_text(row.get(benchmark_field))
                if isinstance(benchmark_field, str)
                else (source.benchmark_id or source.source_name)
            )
            metric_raw = source_text(row.get(metric_field)) if isinstance(metric_field, str) else None
            split_raw = source_text(row.get(split_field)) if isinstance(split_field, str) else None
            rank_raw = source_score_lexeme(row.get(rank_field)) if isinstance(rank_field, str) else None
            if benchmark_raw is None:
                continue
            fields = {"model_raw": model_field, "score_raw": score_field}
            for field_name, source_field in optional_fields.items():
                if isinstance(source_field, str):
                    fields[field_name] = source_field
            claims.append(
                ResultClaimInput(
                    official_source_id=source.id,
                    source_snapshot_id=snapshot.id,
                    benchmark_id=source.benchmark_id,
                    model_raw=model_raw,
                    benchmark_raw=benchmark_raw,
                    score_raw=score_raw,
                    metric_raw=metric_raw,
                    split_raw=split_raw,
                    rank_raw=rank_raw,
                    score_numeric=None,
                    evidence_location={
                        "type": "json_path_v1",
                        "record_path": f"{collection_path}[{i}]",
                        "fields": fields,
                    },
                    capture_method="json_parser",
                    capture_confidence=0.9 if score_raw else 0.2,
                    capture_status="parser_verified" if score_raw else "needs_review",
                    officialness_level=source.officialness_level,
                )
            )
        return claims

    def validate_claim(self, claim: ResultClaimInput, raw_bytes: bytes) -> list[ClaimValidationInput]:
        try:
            data = decode_json_bytes(raw_bytes)
            locator = claim.evidence_location
            if not isinstance(locator, dict) or locator.get("type") != "json_path_v1":
                raise JsonLexemeError("claim has no JSON record locator")
            record, error = resolve_json_path(data, locator.get("record_path"))
            fields = locator.get("fields")
            if error or not isinstance(record, dict) or not isinstance(fields, dict):
                raise JsonLexemeError("claim record cannot resolve")
            model_field = fields.get("model_raw")
            score_field = fields.get("score_raw")
            if not isinstance(model_field, str) or not isinstance(score_field, str):
                raise JsonLexemeError("claim field mapping is invalid")
            outcome = (
                "pass"
                if source_text(record.get(model_field)) == claim.model_raw
                and source_score_lexeme(record.get(score_field)) == claim.score_raw
                else "uncertain"
            )
        except JsonLexemeError:
            outcome = "uncertain"
        return [
            ClaimValidationInput(
                validation_type="json_path_match",
                outcome=outcome,
                validator="GenericJSONAdapter",
            )
        ]
