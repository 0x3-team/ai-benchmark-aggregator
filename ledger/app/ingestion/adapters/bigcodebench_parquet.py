"""BigCodeBench results Parquet adapter (fixture-first certification prep, B2).

One revision-pinned Parquet artifact carries every result row.  ``complete``
and ``instruct`` are distinct source-reported metric dimensions: each row
yields exactly one claim per declared dimension column — never an average,
never a row-order selection, never a substitute column.  Model identity is
preserved exactly as reported; central admission alone decides whether an
unresolved identity is quarantined for review.

Complete-artifact accounting is fail-closed: an unreadable file, a zero-row
collapse, a duplicated model/metric identity, or a row that cannot render
every declared column quarantines the whole batch before any claim exists.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
import math
import re
from typing import Any

from app.db.models import SourceSnapshot
from app.ingestion.adapters.base import SourceAdapter
from app.ingestion.parquet_cells import (
    ParquetCellError,
    ParquetEvidenceResolver,
    iter_parquet_records,
    read_parquet_record,
)
from app.schemas.boundary import (
    ClaimValidationInput,
    OfficialSource,
    ResultClaimInput,
)


class BigCodeBenchBatchError(ValueError):
    """The artifact cannot be completely accounted; the batch is quarantined."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


class BigCodeBenchParquetAdapter(SourceAdapter):
    """Parse the revision-pinned BigCodeBench results Parquet artifact."""

    source_type = "bigcodebench_parquet"
    accepted_content_types = frozenset(
        {
            "application/parquet",
            "application/vnd.apache.parquet",
            "application/octet-stream",
        }
    )
    _DECIMAL_RE = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?\Z")
    # Resolves typed ``parquet_cell_v1`` evidence against the snapshot bytes.
    # It can reuse a run-scoped shared resolver so extraction, admission, and
    # validation do not each open/decode the snapshot independently.
    uses_parquet_evidence_resolver = True

    def _config(self, source: OfficialSource) -> dict[str, Any] | None:
        cfg = source.parser_config or {}
        model_field = cfg.get("model_field", "model")
        dimension_fields = cfg.get("dimension_fields")
        constants = {
            name: cfg.get(name)
            for name in ("split_raw", "setting_raw", "evaluation_version_raw")
        }
        if not isinstance(model_field, str) or not model_field:
            return None
        if (
            not isinstance(dimension_fields, dict)
            or not dimension_fields
            or any(
                not isinstance(metric, str)
                or not metric
                or not isinstance(column, str)
                or not column
                for metric, column in dimension_fields.items()
            )
        ):
            return None
        # Two dimensions may never share one column; that would silently
        # substitute one source-reported dimension for another.
        if len(set(dimension_fields.values())) != len(dimension_fields):
            return None
        if any(value is not None and not isinstance(value, str) for value in constants.values()):
            return None
        return {
            "model_field": model_field,
            "dimension_fields": dict(sorted(dimension_fields.items())),
            **constants,
        }

    @staticmethod
    def _strict_numeric(score_raw: str) -> float:
        """Return a finite numeric score without changing its raw lexeme."""

        try:
            decimal = Decimal(score_raw)
        except (InvalidOperation, ValueError):
            raise BigCodeBenchBatchError("SCORE_NOT_NUMERIC") from None
        if not decimal.is_finite():
            raise BigCodeBenchBatchError("SCORE_NOT_FINITE")
        if not BigCodeBenchParquetAdapter._DECIMAL_RE.fullmatch(score_raw):
            raise BigCodeBenchBatchError("SCORE_NOT_NUMERIC")
        score_numeric = float(decimal)
        if not math.isfinite(score_numeric):
            raise BigCodeBenchBatchError("SCORE_NOT_FINITE")
        if decimal != 0 and score_numeric == 0.0:
            raise BigCodeBenchBatchError("SCORE_NOT_REPRESENTABLE")
        return score_numeric

    def extract_claims(
        self,
        source: OfficialSource,
        snapshot: SourceSnapshot,
        raw_bytes: bytes,
        parquet_resolver: ParquetEvidenceResolver | None = None,
    ) -> list[ResultClaimInput]:
        """Extract a complete, one-row-per-dimension claim batch.

        When ``parquet_resolver`` is supplied, extraction reuses the shared
        ``ParquetEvidenceResolver`` opened once by the runner so the snapshot
        is decoded a single time across extraction, admission, and validation;
        otherwise a single-shot resolver is built and released here.  A supplied
        resolver is first verified against ``raw_bytes`` and fails closed on
        mismatch.

        This method intentionally builds claims only in a local list.  Any
        accounting error raises before a partial list can escape to the
        runner, so a malformed artifact quarantined as one unit.
        """

        config = self._config(source)
        if config is None:
            raise BigCodeBenchBatchError("CONFIG_INVALID")

        model_field = config["model_field"]
        dimension_fields: dict[str, str] = config["dimension_fields"]
        required_fields = {model_field, *dimension_fields.values()}
        claims: list[ResultClaimInput] = []
        seen_model_dimensions: set[tuple[str, str]] = set()
        record_count = 0

        # Stream the resolver iterator (always a one-shot iterator over the
        # snapshot) rather than materialising a full ``records`` list.  The
        # shared resolver's ``iter_records`` is consumed exactly once here;
        # when no shared resolver is supplied a single-shot resolver is built
        # and released inside ``iter_parquet_records``.  ``record_count`` is
        # the sole source of truth for complete accounting, so a duplicate
        # materialised list cannot diverge from what was consumed.
        try:
            if parquet_resolver is not None:
                parquet_resolver.verify(raw_bytes)
                records_iter = parquet_resolver.iter_records()
            else:
                records_iter = iter_parquet_records(raw_bytes)
            for row_group, row_index, record in records_iter:
                record_count += 1
                if any(field not in record for field in required_fields):
                    raise BigCodeBenchBatchError("PARQUET_COLUMN_MISSING")

                model_raw = record[model_field]
                if not model_raw:
                    raise BigCodeBenchBatchError("MODEL_VALUE_MISSING")

                for metric_raw, score_field in dimension_fields.items():
                    score_raw = record[score_field]
                    score_numeric = self._strict_numeric(score_raw)
                    identity = (model_raw, metric_raw)
                    if identity in seen_model_dimensions:
                        raise BigCodeBenchBatchError("DUPLICATE_MODEL_DIMENSION")
                    seen_model_dimensions.add(identity)

                    claims.append(
                        ResultClaimInput(
                            official_source_id=source.id,
                            source_snapshot_id=snapshot.id,
                            benchmark_id=source.benchmark_id,
                            model_raw=model_raw,
                            benchmark_raw=source.benchmark_id or source.source_name,
                            score_raw=score_raw,
                            metric_raw=metric_raw,
                            split_raw=config["split_raw"],
                            setting_raw=config["setting_raw"],
                            evaluation_version_raw=config["evaluation_version_raw"],
                            score_numeric=score_numeric,
                            evidence_location={
                                "type": "parquet_cell_v1",
                                "row_group": row_group,
                                "row_index": row_index,
                                "fields": {
                                    "model_raw": model_field,
                                    "score_raw": score_field,
                                },
                            },
                            capture_method="bigcodebench_parquet_parser",
                            capture_confidence=0.9,
                            capture_status="parser_verified",
                            officialness_level=source.officialness_level,
                        )
                    )
        except ParquetCellError:
            raise BigCodeBenchBatchError("PARQUET_UNREADABLE") from None
        if record_count == 0:
            raise BigCodeBenchBatchError("PARQUET_EMPTY")
        expected_claim_count = record_count * len(dimension_fields)
        if len(claims) != expected_claim_count:
            raise BigCodeBenchBatchError("INCOMPLETE_ACCOUNTING")
        return claims

    def validate_claim(
        self,
        claim: ResultClaimInput,
        raw_bytes: bytes,
        parquet_resolver: ParquetEvidenceResolver | None = None,
    ) -> list[ClaimValidationInput]:
        """Re-resolve and compare the exact model/score cells in the snapshot."""

        locator = claim.evidence_location
        outcome = "uncertain"
        if isinstance(locator, dict) and locator.get("type") == "parquet_cell_v1":
            record, error = read_parquet_record(
                raw_bytes,
                row_group=locator.get("row_group"),
                row_index=locator.get("row_index"),
                resolver=parquet_resolver,
            )
            fields = locator.get("fields")
            if error is None and record is not None and isinstance(fields, dict):
                model_field = fields.get("model_raw")
                score_field = fields.get("score_raw")
                if (
                    isinstance(model_field, str)
                    and isinstance(score_field, str)
                    and record.get(model_field) == claim.model_raw
                    and record.get(score_field) == claim.score_raw
                ):
                    outcome = "pass"

        return [
            ClaimValidationInput(
                validation_type="parquet_cell_match",
                outcome=outcome,
                validator="BigCodeBenchParquetAdapter",
            )
        ]
