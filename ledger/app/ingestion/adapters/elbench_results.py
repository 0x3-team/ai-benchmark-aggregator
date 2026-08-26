"""Bounded fixture-only ELBench aggregate leaderboard adapter.

This candidate parser accepts only the reviewed aggregate-board shape in an
explicit inactive fixture mode. It emits each source-reported module and both
explicitly labelled overall fields directly; it never derives a score, rank,
bootstrap interval, or per-sample result.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
import math
import re
from typing import Any

from app.db.models import SourceSnapshot
from app.ingestion.adapters.base import SourceAdapter
from app.ingestion.json_lexemes import (
    JsonLexemeError,
    JsonNumberLexeme,
    decode_json_bytes,
    resolve_json_path,
    source_score_lexeme,
    source_text,
)
from app.schemas.boundary import ClaimValidationInput, OfficialSource, ResultClaimInput


class ElBenchResultsBatchError(ValueError):
    """The bounded aggregate artifact cannot be completely accounted for."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


class ElBenchResultsAdapter(SourceAdapter):
    """Parse the ELBench aggregate board in inactive fixture-candidate mode."""

    source_type = "elbench_results"
    accepted_content_types = frozenset(
        {"application/json", "application/*+json", "text/json", "text/plain"}
    )

    _MAX_ARTIFACT_BYTES = 4_096
    _MAX_ROW_COUNT = 9
    _DECIMAL_RE = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?\Z")
    _ROOT_FIELDS = frozenset({"rows", "old_rank", "new_rank"})
    _ROW_FIELDS = frozenset({"model", "gen", "saf", "bas", "high", "ovr_old", "ovr_new"})
    _SCORE_FIELDS = (
        ("gen", "General Capability"),
        ("saf", "Safety & Trustworthiness"),
        ("bas", "Basic Education"),
        ("high", "High-Level Educational Cultivation"),
        ("ovr_old", "Historical Overall (source-reported)"),
        ("ovr_new", "Corrected Overall"),
    )

    @classmethod
    def _config(cls, source: OfficialSource) -> int | None:
        config = source.parser_config or {}
        expected_row_count = config.get("expected_row_count")
        if (
            source.status != "inactive"
            or set(config) != {"mode", "expected_row_count"}
            or config.get("mode") != "fixture_candidate_only"
            or type(expected_row_count) is not int
            or not 1 <= expected_row_count <= cls._MAX_ROW_COUNT
        ):
            return None
        return expected_row_count

    @classmethod
    def _strict_numeric(cls, value: object) -> tuple[str, float]:
        score_raw = source_score_lexeme(value)
        if score_raw is None:
            raise ElBenchResultsBatchError("SCORE_NOT_NUMERIC")
        try:
            decimal = Decimal(score_raw)
        except (InvalidOperation, ValueError):
            raise ElBenchResultsBatchError("SCORE_NOT_NUMERIC") from None
        if not decimal.is_finite():
            raise ElBenchResultsBatchError("SCORE_NOT_FINITE")
        if not cls._DECIMAL_RE.fullmatch(score_raw):
            raise ElBenchResultsBatchError("SCORE_NOT_NUMERIC")
        score_numeric = float(decimal)
        if not math.isfinite(score_numeric):
            raise ElBenchResultsBatchError("SCORE_NOT_FINITE")
        if decimal != 0 and score_numeric == 0.0:
            raise ElBenchResultsBatchError("SCORE_NOT_REPRESENTABLE")
        return score_raw, score_numeric

    @staticmethod
    def _rank_maps_are_context_only(
        old_rank: object, new_rank: object, model_names: set[str]
    ) -> bool:
        if not isinstance(old_rank, dict) or not isinstance(new_rank, dict):
            return False
        if set(old_rank) != model_names or set(new_rank) != model_names:
            return False
        for rank_map in (old_rank, new_rank):
            ranks: set[int] = set()
            for rank in rank_map.values():
                if not isinstance(rank, JsonNumberLexeme) or not rank.isdigit() or int(rank) < 1:
                    return False
                ranks.add(int(rank))
            if ranks != set(range(1, len(model_names) + 1)):
                return False
        return True

    def extract_claims(
        self, source: OfficialSource, snapshot: SourceSnapshot, raw_bytes: bytes
    ) -> list[ResultClaimInput]:
        expected_row_count = self._config(source)
        if expected_row_count is None:
            return []
        if len(raw_bytes) > self._MAX_ARTIFACT_BYTES:
            raise ElBenchResultsBatchError("ARTIFACT_BYTES_EXCEEDED")
        try:
            data = decode_json_bytes(raw_bytes)
        except JsonLexemeError:
            raise ElBenchResultsBatchError("JSON_MALFORMED") from None
        if not isinstance(data, dict) or set(data) != self._ROOT_FIELDS:
            raise ElBenchResultsBatchError("ROOT_SHAPE_INVALID")
        rows = data["rows"]
        if not isinstance(rows, list):
            raise ElBenchResultsBatchError("ROWS_INVALID")
        if len(rows) > self._MAX_ROW_COUNT:
            raise ElBenchResultsBatchError("ROW_LIMIT_EXCEEDED")
        if len(rows) != expected_row_count:
            raise ElBenchResultsBatchError("ROW_COUNT_UNEXPECTED")

        model_names: set[str] = set()
        claims: list[ResultClaimInput] = []
        for row_index, row in enumerate(rows):
            if not isinstance(row, dict) or set(row) != self._ROW_FIELDS:
                raise ElBenchResultsBatchError("ROW_SHAPE_INVALID")
            model_raw = source_text(row["model"])
            if model_raw is None or not model_raw:
                raise ElBenchResultsBatchError("MODEL_VALUE_INVALID")
            if model_raw in model_names:
                raise ElBenchResultsBatchError("DUPLICATE_MODEL")
            model_names.add(model_raw)
            for score_field, metric_raw in self._SCORE_FIELDS:
                score_raw, score_numeric = self._strict_numeric(row[score_field])
                claims.append(
                    ResultClaimInput(
                        official_source_id=source.id,
                        source_snapshot_id=snapshot.id,
                        benchmark_id=source.benchmark_id,
                        model_raw=model_raw,
                        benchmark_raw=source.benchmark_id or source.source_name,
                        score_raw=score_raw,
                        metric_raw=metric_raw,
                        score_numeric=score_numeric,
                        evidence_location={
                            "type": "json_path_v1",
                            "record_path": f"$.rows[{row_index}]",
                            "fields": {"model_raw": "model", "score_raw": score_field},
                        },
                        capture_method="elbench_results_fixture_candidate_parser",
                        capture_confidence=0.0,
                        capture_status="unreviewed",
                        officialness_level=source.officialness_level,
                    )
                )
        if not self._rank_maps_are_context_only(data["old_rank"], data["new_rank"], model_names):
            raise ElBenchResultsBatchError("RANK_CONTEXT_INVALID")
        if len(claims) != len(rows) * len(self._SCORE_FIELDS):
            raise ElBenchResultsBatchError("INCOMPLETE_ACCOUNTING")
        return claims

    def validate_claim(self, claim: ResultClaimInput, raw_bytes: bytes) -> list[ClaimValidationInput]:
        outcome = "uncertain"
        locator = claim.evidence_location
        if isinstance(locator, dict) and locator.get("type") == "json_path_v1":
            fields = locator.get("fields")
            score_field = fields.get("score_raw") if isinstance(fields, dict) else None
            expected_metric = dict(self._SCORE_FIELDS).get(score_field)
            try:
                data = decode_json_bytes(raw_bytes)
            except JsonLexemeError:
                data = None
            if data is not None and expected_metric == claim.metric_raw:
                record, error = resolve_json_path(data, locator.get("record_path"))
                if (
                    error is None
                    and isinstance(record, dict)
                    and fields == {"model_raw": "model", "score_raw": score_field}
                    and source_text(record.get("model")) == claim.model_raw
                    and source_score_lexeme(record.get(score_field)) == claim.score_raw
                ):
                    outcome = "pass"
        return [
            ClaimValidationInput(
                validation_type="json_path_match",
                outcome=outcome,
                validator="ElBenchResultsAdapter",
            )
        ]
