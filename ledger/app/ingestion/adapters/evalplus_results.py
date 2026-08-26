"""Fixture-only parser for one EvalPlus EvalPerf brief-result file.

The candidate source stores one model's source-reported summary and evaluation
configuration in each ``*_evalperf_results.brief.json`` file. This adapter only
reads explicitly configured, top-level scalar summary fields. It never opens,
profiles, selects, or aggregates per-task records or model outputs.

One invocation accounts for exactly one brief file and every configured summary
score in that file. It is deliberately not a directory or manifest adapter:
the source's multi-file result coverage has no immutable manifest, denominator,
or atomic multi-file snapshot contract yet. The adapter is fixture-only and
cannot acquire data or authorize a source for ingestion.
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
    decode_json_bytes,
    resolve_json_path,
    source_score_lexeme,
    source_text,
)
from app.schemas.boundary import (
    ClaimValidationInput,
    OfficialSource,
    ResultClaimInput,
    SourceFetchResult,
)


class EvalPlusResultsBatchError(ValueError):
    """A single brief-result fixture is not safe for complete extraction."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


class EvalPlusResultsAdapter(SourceAdapter):
    """Parse one configured EvalPlus EvalPerf summary fixture, never a result tree."""

    source_type = "evalplus_results"
    requires_central_fetch = False
    accepted_content_types = frozenset({"application/json", "application/*+json", "text/json"})
    MAX_FIXTURE_BYTES = 256 * 1024
    _DECIMAL_RE = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?\Z")
    _CONFIGURATION_CLAIM_FIELDS = frozenset(
        {"split_raw", "setting_raw", "evaluation_version_raw"}
    )

    def fetch(self, source: OfficialSource) -> SourceFetchResult:
        _ = source
        raise RuntimeError(
            "EvalPlus results adapter is fixture-only and cannot fetch an Official benchmark source."
        )

    def _config(self, source: OfficialSource) -> dict[str, Any] | None:
        cfg = source.parser_config or {}
        if cfg.get("mode") != "test_fixture_only" or source.status != "inactive":
            return None

        model_field = cfg.get("model_field")
        score_fields = cfg.get("score_fields")
        configuration_fields = cfg.get("configuration_fields")
        benchmark_raw = cfg.get("benchmark_raw", source.benchmark_id or source.source_name)
        if (
            not isinstance(model_field, str)
            or not model_field
            or not isinstance(score_fields, dict)
            or not score_fields
            or not isinstance(configuration_fields, dict)
            or not configuration_fields
            or not isinstance(benchmark_raw, str)
            or not benchmark_raw
        ):
            return None
        if any(
            not isinstance(metric_raw, str)
            or not metric_raw
            or not isinstance(field, str)
            or not field
            or metric_raw != field
            for metric_raw, field in score_fields.items()
        ):
            return None
        if any(
            claim_field not in self._CONFIGURATION_CLAIM_FIELDS
            or not isinstance(source_field, str)
            or not source_field
            for claim_field, source_field in configuration_fields.items()
        ):
            return None

        score_field_values = list(score_fields.values())
        configuration_field_values = list(configuration_fields.values())
        if (
            len(set(score_field_values)) != len(score_field_values)
            or len(set(configuration_field_values)) != len(configuration_field_values)
            or model_field in score_fields.values()
            or model_field in configuration_fields.values()
            or set(score_fields.values()).intersection(configuration_fields.values())
        ):
            return None
        return {
            "model_field": model_field,
            "score_fields": dict(score_fields),
            "configuration_fields": dict(configuration_fields),
            "benchmark_raw": benchmark_raw,
        }

    @classmethod
    def _strict_score(cls, score_raw: str) -> float:
        try:
            decimal = Decimal(score_raw)
        except (InvalidOperation, ValueError):
            raise EvalPlusResultsBatchError("SCORE_NOT_NUMERIC") from None
        if not decimal.is_finite():
            raise EvalPlusResultsBatchError("SCORE_NOT_FINITE")
        if not cls._DECIMAL_RE.fullmatch(score_raw):
            raise EvalPlusResultsBatchError("SCORE_NOT_NUMERIC")
        numeric_value = float(decimal)
        if not math.isfinite(numeric_value):
            raise EvalPlusResultsBatchError("SCORE_NOT_FINITE")
        if decimal != 0 and numeric_value == 0.0:
            raise EvalPlusResultsBatchError("SCORE_NOT_REPRESENTABLE")
        return numeric_value

    def extract_claims(
        self, source: OfficialSource, snapshot: SourceSnapshot, raw_bytes: bytes
    ) -> list[ResultClaimInput]:
        """Extract one complete batch of configured top-level summary scores."""

        if (source.parser_config or {}).get("mode") != "test_fixture_only":
            return []
        config = self._config(source)
        if config is None:
            raise EvalPlusResultsBatchError("CONFIG_INVALID")
        if len(raw_bytes) > self.MAX_FIXTURE_BYTES:
            raise EvalPlusResultsBatchError("RESULT_FILE_TOO_LARGE")
        try:
            document = decode_json_bytes(raw_bytes)
        except JsonLexemeError:
            raise EvalPlusResultsBatchError("JSON_INVALID") from None
        if not isinstance(document, dict):
            raise EvalPlusResultsBatchError("SUMMARY_ROOT_INVALID")

        model_raw = source_text(document.get(config["model_field"]))
        if not model_raw:
            raise EvalPlusResultsBatchError("MODEL_VALUE_MISSING")

        configuration_values: dict[str, str] = {}
        for claim_field, source_field in config["configuration_fields"].items():
            value = source_text(document.get(source_field))
            if value is None:
                raise EvalPlusResultsBatchError("CONFIGURATION_VALUE_MISSING")
            configuration_values[claim_field] = value

        fields: dict[str, str] = {"model_raw": config["model_field"]}
        fields.update(config["configuration_fields"])
        claims: list[ResultClaimInput] = []
        seen_score_fields: set[str] = set()
        for metric_raw, score_field in config["score_fields"].items():
            if score_field in seen_score_fields:
                raise EvalPlusResultsBatchError("DUPLICATE_SCORE_FIELD")
            seen_score_fields.add(score_field)
            score_raw = source_score_lexeme(document.get(score_field))
            if score_raw is None:
                raise EvalPlusResultsBatchError("SCORE_VALUE_MISSING")
            score_numeric = self._strict_score(score_raw)
            claims.append(
                ResultClaimInput(
                    official_source_id=source.id,
                    source_snapshot_id=snapshot.id,
                    benchmark_id=source.benchmark_id,
                    model_raw=model_raw,
                    benchmark_raw=config["benchmark_raw"],
                    score_raw=score_raw,
                    metric_raw=metric_raw,
                    split_raw=configuration_values.get("split_raw"),
                    setting_raw=configuration_values.get("setting_raw"),
                    evaluation_version_raw=configuration_values.get("evaluation_version_raw"),
                    score_numeric=score_numeric,
                    evidence_location={
                        "type": "json_path_v1",
                        "record_path": "$",
                        "fields": {**fields, "score_raw": score_field},
                    },
                    capture_method="evalplus_results_fixture_parser",
                    capture_confidence=0.0,
                    capture_status="needs_review",
                    officialness_level=source.officialness_level,
                )
            )
        if len(claims) != len(config["score_fields"]):
            raise EvalPlusResultsBatchError("INCOMPLETE_SINGLE_FILE_ACCOUNTING")
        return claims

    def validate_claim(self, claim: ResultClaimInput, raw_bytes: bytes) -> list[ClaimValidationInput]:
        """Re-resolve the exact top-level summary and configuration fields."""

        outcome = "uncertain"
        try:
            document = decode_json_bytes(raw_bytes)
            locator = claim.evidence_location
            if not isinstance(locator, dict) or locator.get("type") != "json_path_v1":
                raise JsonLexemeError("claim has no JSON summary locator")
            record, error = resolve_json_path(document, locator.get("record_path"))
            fields = locator.get("fields")
            if error or not isinstance(record, dict) or not isinstance(fields, dict):
                raise JsonLexemeError("claim summary cannot resolve")
            model_field = fields.get("model_raw")
            score_field = fields.get("score_raw")
            if (
                isinstance(model_field, str)
                and isinstance(score_field, str)
                and score_field == claim.metric_raw
                and source_text(record.get(model_field)) == claim.model_raw
                and source_score_lexeme(record.get(score_field)) == claim.score_raw
                and all(
                    isinstance(claim_field, str)
                    and isinstance(source_field, str)
                    and claim_field in self._CONFIGURATION_CLAIM_FIELDS
                    and source_text(record.get(source_field)) == getattr(claim, claim_field)
                    for claim_field, source_field in fields.items()
                    if claim_field in self._CONFIGURATION_CLAIM_FIELDS
                )
            ):
                outcome = "pass"
        except JsonLexemeError:
            pass
        return [
            ClaimValidationInput(
                validation_type="evalplus_summary_json_path_match",
                outcome=outcome,
                validator="EvalPlusResultsAdapter",
            )
        ]
