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


class HFDatasetsServerAdapter(SourceAdapter):
    source_type = "hf_datasets_server"
    accepted_content_types = frozenset({"application/json", "application/*+json", "text/json"})

    def extract_claims(
        self, source: OfficialSource, snapshot: SourceSnapshot, raw_bytes: bytes
    ) -> list[ResultClaimInput]:
        cfg = source.parser_config or {}
        try:
            data = decode_json_bytes(raw_bytes)
        except JsonLexemeError:
            return []

        records_path = canonical_config_json_path(cfg.get("records_path"))
        row_field = cfg.get("row_field")
        model_field = cfg.get("model_field")
        score_field = cfg.get("score_field")
        if (
            records_path is None
            or row_field is not None
            and (not isinstance(row_field, str) or not row_field)
            or not isinstance(model_field, str)
            or not model_field
            or not isinstance(score_field, str)
            or not score_field
        ):
            return []
        metric_field = cfg.get("metric_field")
        split_field = cfg.get("split_field")
        rank_field = cfg.get("rank_field")
        optional_fields = {
            "metric_raw": metric_field,
            "split_raw": split_field,
            "rank_raw": rank_field,
        }
        if any(field is not None and (not isinstance(field, str) or not field) for field in optional_fields.values()):
            return []
        rows, rows_error = resolve_json_path(data, records_path)
        if rows_error or not isinstance(rows, list):
            return []
        claims: list[ResultClaimInput] = []

        for i, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            row_data = row.get(row_field) if row_field else row
            if not isinstance(row_data, dict):
                continue

            model_raw = source_text(row_data.get(model_field))
            score_raw = source_score_lexeme(row_data.get(score_field))
            if model_raw is None or score_raw is None:
                continue
            metric_raw = source_text(row_data.get(metric_field)) if isinstance(metric_field, str) else None
            split_raw = source_text(row_data.get(split_field)) if isinstance(split_field, str) else None
            rank_raw = source_score_lexeme(row_data.get(rank_field)) if isinstance(rank_field, str) else None
            record_path = f"{records_path}[{i}]" + (f".{row_field}" if row_field else "")
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
                    benchmark_raw=source.benchmark_id or source.source_name,
                    score_raw=score_raw,
                    metric_raw=metric_raw,
                    split_raw=split_raw,
                    rank_raw=rank_raw,
                    score_numeric=None,
                    evidence_location={
                        "type": "json_path_v1",
                        "record_path": record_path,
                        "fields": fields,
                    },
                    capture_method="hf_datasets_server_parser",
                    capture_confidence=0.95,
                    capture_status="parser_verified",
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
                validator="HFDatasetsServerAdapter",
            )
        ]
