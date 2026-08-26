"""AGC-Bench CSV candidate adapter, bounded to inactive local fixtures.

The candidate accepts one source-reported score cell per CSV row.  It never
calculates a z-score, composite, rank, average, or other derived result.  The
two supported row shapes retain their reported dimensions directly:

* ``model_dataset_scores`` binds the dataset cell as ``benchmark_raw``.
* ``headline_leaderboard`` binds its explicitly reported benchmark and metric
  cells, including a source-reported composite label when present.

This is deliberately a fixture-only parsing seam.  It cannot fetch, is only
enabled for inactive ``fixture_only`` sources, and its returned inputs remain
unreviewed candidates until a separate source-revision decision exists.
"""

from __future__ import annotations

import csv
from decimal import Decimal, InvalidOperation
import io
import math
import re
from typing import Any

from app.db.models import SourceSnapshot
from app.ingestion.adapters.base import SourceAdapter
from app.schemas.boundary import (
    ClaimValidationInput,
    OfficialSource,
    ResultClaimInput,
    SourceFetchResult,
)


class AGCBenchBatchError(ValueError):
    """The bounded local CSV fixture cannot be completely accounted for."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


class AGCBenchAdapter(SourceAdapter):
    """Parse direct AGC-Bench CSV cells without deriving benchmark results."""

    source_type = "agc_bench"
    requires_central_fetch = False
    accepted_content_types = frozenset({"text/csv", "application/csv"})

    _DECIMAL_RE = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?\Z")
    _MAX_FIXTURE_BYTES = 1 * 1024 * 1024
    _MAX_FIXTURE_ROWS = 10_000
    _RECORD_KINDS = frozenset({"model_dataset_scores", "headline_leaderboard"})

    def fetch(self, source: OfficialSource) -> SourceFetchResult:
        _ = source
        raise RuntimeError(
            "AGC-Bench adapter is fixture-only and cannot fetch or capture an Official source."
        )

    @staticmethod
    def _nonempty_string(value: object) -> str | None:
        return value if isinstance(value, str) and value else None

    def _config(self, source: OfficialSource) -> dict[str, Any] | None:
        config = source.parser_config or {}
        if source.status != "inactive" or config.get("mode") != "fixture_only":
            return None

        record_kind = config.get("record_kind")
        model_field = self._nonempty_string(config.get("model_field"))
        score_field = self._nonempty_string(config.get("score_field"))
        benchmark_field = self._nonempty_string(config.get("benchmark_field"))
        metric_field = self._nonempty_string(config.get("metric_field"))
        max_bytes = config.get("max_bytes")
        max_rows = config.get("max_rows")
        if (
            record_kind not in self._RECORD_KINDS
            or not model_field
            or not score_field
            or not benchmark_field
            or not metric_field
            or type(max_bytes) is not int
            or not 0 < max_bytes <= self._MAX_FIXTURE_BYTES
            or type(max_rows) is not int
            or not 0 < max_rows <= self._MAX_FIXTURE_ROWS
        ):
            return None
        if len({model_field, score_field, benchmark_field, metric_field}) != 4:
            return None
        return {
            "record_kind": record_kind,
            "model_field": model_field,
            "score_field": score_field,
            "benchmark_field": benchmark_field,
            "metric_field": metric_field,
            "max_bytes": max_bytes,
            "max_rows": max_rows,
        }

    @staticmethod
    def _read_rows(raw_bytes: bytes, config: dict[str, Any]) -> tuple[list[str], list[list[str]]]:
        if len(raw_bytes) > config["max_bytes"]:
            raise AGCBenchBatchError("CSV_MAX_BYTES_EXCEEDED")
        try:
            text = raw_bytes.decode("utf-8")
        except UnicodeDecodeError:
            raise AGCBenchBatchError("CSV_NOT_UTF8") from None

        try:
            reader = csv.reader(io.StringIO(text, newline=""), strict=True)
            headers = next(reader, None)
            if not headers or any(not header for header in headers) or len(set(headers)) != len(headers):
                raise AGCBenchBatchError("CSV_SCHEMA_INVALID")
            required = {
                config["model_field"],
                config["score_field"],
                config["benchmark_field"],
                config["metric_field"],
            }
            if not required.issubset(headers):
                raise AGCBenchBatchError("CSV_SCHEMA_INVALID")

            rows: list[list[str]] = []
            for row in reader:
                if len(row) != len(headers):
                    raise AGCBenchBatchError("CSV_ROW_WIDTH_INVALID")
                rows.append(row)
                if len(rows) > config["max_rows"]:
                    raise AGCBenchBatchError("CSV_MAX_ROWS_EXCEEDED")
        except csv.Error:
            raise AGCBenchBatchError("CSV_MALFORMED") from None

        if not rows:
            raise AGCBenchBatchError("CSV_EMPTY")
        return headers, rows

    @classmethod
    def _strict_numeric(cls, score_raw: str) -> float:
        if score_raw.casefold() in {"nan", "+nan", "-nan", "inf", "+inf", "-inf", "infinity", "+infinity", "-infinity"}:
            raise AGCBenchBatchError("SCORE_NOT_FINITE")
        if not cls._DECIMAL_RE.fullmatch(score_raw):
            raise AGCBenchBatchError("SCORE_NOT_NUMERIC")
        try:
            decimal = Decimal(score_raw)
        except InvalidOperation:
            raise AGCBenchBatchError("SCORE_NOT_NUMERIC") from None
        if not decimal.is_finite():
            raise AGCBenchBatchError("SCORE_NOT_FINITE")
        numeric = float(decimal)
        if not math.isfinite(numeric):
            raise AGCBenchBatchError("SCORE_NOT_FINITE")
        if decimal != 0 and numeric == 0.0:
            raise AGCBenchBatchError("SCORE_NOT_REPRESENTABLE")
        return numeric

    def extract_claims(
        self,
        source: OfficialSource,
        snapshot: SourceSnapshot,
        raw_bytes: bytes,
    ) -> list[ResultClaimInput]:
        config = self._config(source)
        if config is None:
            return []

        headers, rows = self._read_rows(raw_bytes, config)
        columns = {header: index for index, header in enumerate(headers)}
        claims: list[ResultClaimInput] = []
        identities: set[tuple[str, str, str]] = set()

        for row_index, row in enumerate(rows):
            model_raw = row[columns[config["model_field"]]]
            benchmark_raw = row[columns[config["benchmark_field"]]]
            metric_raw = row[columns[config["metric_field"]]]
            score_raw = row[columns[config["score_field"]]]
            if not model_raw or not benchmark_raw or not metric_raw:
                raise AGCBenchBatchError("RAW_DIMENSION_MISSING")
            if not score_raw:
                raise AGCBenchBatchError("SCORE_VALUE_MISSING")
            score_numeric = self._strict_numeric(score_raw)
            identity = (model_raw, benchmark_raw, metric_raw)
            if identity in identities:
                raise AGCBenchBatchError("DUPLICATE_MODEL_DIMENSION")
            identities.add(identity)

            claims.append(
                ResultClaimInput(
                    official_source_id=source.id,
                    source_snapshot_id=snapshot.id,
                    benchmark_id=source.benchmark_id,
                    model_raw=model_raw,
                    benchmark_raw=benchmark_raw,
                    score_raw=score_raw,
                    metric_raw=metric_raw,
                    score_numeric=score_numeric,
                    evidence_location={
                        "type": "csv_cell_v1",
                        "row_index": row_index,
                        "fields": {
                            "model_raw": config["model_field"],
                            "benchmark_raw": config["benchmark_field"],
                            "metric_raw": config["metric_field"],
                            "score_raw": config["score_field"],
                        },
                    },
                    capture_method=f"agc_bench_{config['record_kind']}_fixture_parser",
                    capture_confidence=0.0,
                    capture_status="unreviewed",
                    officialness_level=source.officialness_level,
                )
            )

        if len(claims) != len(rows):
            raise AGCBenchBatchError("INCOMPLETE_ACCOUNTING")
        return claims

    def validate_claim(self, claim: ResultClaimInput, raw_bytes: bytes) -> list[ClaimValidationInput]:
        locator = claim.evidence_location
        outcome = "uncertain"
        if isinstance(locator, dict) and locator.get("type") == "csv_cell_v1":
            row_index = locator.get("row_index")
            fields = locator.get("fields")
            if type(row_index) is int and row_index >= 0 and isinstance(fields, dict):
                expected_fields = {
                    "model_raw": claim.model_raw,
                    "benchmark_raw": claim.benchmark_raw,
                    "metric_raw": claim.metric_raw,
                    "score_raw": claim.score_raw,
                }
                if (
                    len(raw_bytes) <= self._MAX_FIXTURE_BYTES
                    and all(isinstance(fields.get(name), str) for name in expected_fields)
                ):
                    try:
                        reader = csv.reader(
                            io.StringIO(raw_bytes.decode("utf-8"), newline=""), strict=True
                        )
                        headers = next(reader, None)
                        if (
                            headers
                            and len(set(headers)) == len(headers)
                            and all(fields[name] in headers for name in expected_fields)
                        ):
                            columns = {header: index for index, header in enumerate(headers)}
                            for current_index, row in enumerate(reader):
                                if (
                                    current_index >= self._MAX_FIXTURE_ROWS
                                    or len(row) != len(headers)
                                ):
                                    break
                                if current_index == row_index:
                                    if all(
                                        row[columns[fields[name]]] == value
                                        for name, value in expected_fields.items()
                                    ):
                                        outcome = "pass"
                                    break
                    except (csv.Error, UnicodeDecodeError):
                        pass
        return [
            ClaimValidationInput(
                validation_type="csv_cell_match",
                outcome=outcome,
                validator="AGCBenchAdapter",
                notes="fixture-only evidence replay; not a source-certification decision",
            )
        ]
