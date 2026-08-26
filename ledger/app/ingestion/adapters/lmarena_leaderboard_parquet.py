"""LMArena first-party leaderboard Parquet adapter candidate.

This fixture-only adapter is bounded to one immutable
``lmarena-ai/leaderboard-dataset`` artifact: the ``text_style_control``
configuration's publisher-generated ``latest`` split. It emits the reported
``rating`` only; confidence bounds, variance, and vote count remain omitted
because the current claim boundary has no typed fields for them. ``rank`` is
retained as non-score context through the existing ``rank_raw`` field.

Every source row must produce exactly one claim. Missing evidence cells,
duplicate model/category/publication-date identities, unreadable Parquet, or an
empty artifact stop the complete batch before any claim escapes.
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
from app.schemas.boundary import ClaimValidationInput, OfficialSource, ResultClaimInput


DATASET_ID = "lmarena-ai/leaderboard-dataset"
DATASET_REVISION = "952c8f01f0c60d7762daab67639afec1722e6c2b"
DATASET_CONFIG = "text_style_control"
DATASET_SPLIT = "latest"
ARTIFACT_PATH = "text_style_control/latest-00000-of-00001.parquet"
ARTIFACT_URL = (
    "https://huggingface.co/datasets/lmarena-ai/leaderboard-dataset/resolve/"
    f"{DATASET_REVISION}/{ARTIFACT_PATH}"
)


class LMArenaLeaderboardBatchError(ValueError):
    """The candidate artifact cannot be completely accounted."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


class LMArenaLeaderboardParquetAdapter(SourceAdapter):
    """Parse only the pinned first-party LMArena leaderboard candidate."""

    source_type = "lmarena_leaderboard_parquet"
    accepted_content_types = frozenset(
        {
            "application/parquet",
            "application/vnd.apache.parquet",
            "application/octet-stream",
        }
    )
    uses_parquet_evidence_resolver = True
    _DECIMAL_RE = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?\Z")
    _FIELD_MAP = {
        "model_raw": "model_name",
        "score_raw": "rating",
        "split_raw": "category",
        "evaluation_version_raw": "leaderboard_publish_date",
        "rank_raw": "rank",
    }
    _OMITTED_CONTEXT_FIELDS = (
        "rating_lower",
        "rating_upper",
        "variance",
        "vote_count",
    )

    @classmethod
    def _config(cls, source: OfficialSource) -> dict[str, Any] | None:
        config = source.parser_config or {}
        expected = {
            "mode": "candidate",
            "certification_status": "not_certified",
            "dataset_id": DATASET_ID,
            "dataset_revision": DATASET_REVISION,
            "config": DATASET_CONFIG,
            "split": DATASET_SPLIT,
            "artifact_path": ARTIFACT_PATH,
            "benchmark_raw": "chatbot_arena",
            "metric_raw": "Arena Score",
            "setting_raw": DATASET_CONFIG,
            "field_map": cls._FIELD_MAP,
            "omitted_context_fields": list(cls._OMITTED_CONTEXT_FIELDS),
        }
        if (
            source.status != "inactive"
            or source.source_url != ARTIFACT_URL
            or source.benchmark_id != "chatbot_arena"
        ):
            return None
        if any(config.get(key) != value for key, value in expected.items()):
            return None
        return expected

    @classmethod
    def _strict_numeric(cls, score_raw: str) -> float:
        try:
            decimal = Decimal(score_raw)
        except (InvalidOperation, ValueError):
            raise LMArenaLeaderboardBatchError("SCORE_NOT_NUMERIC") from None
        if not decimal.is_finite():
            raise LMArenaLeaderboardBatchError("SCORE_NOT_FINITE")
        if not cls._DECIMAL_RE.fullmatch(score_raw):
            raise LMArenaLeaderboardBatchError("SCORE_NOT_NUMERIC")
        score_numeric = float(decimal)
        if not math.isfinite(score_numeric):
            raise LMArenaLeaderboardBatchError("SCORE_NOT_FINITE")
        if decimal != 0 and score_numeric == 0.0:
            raise LMArenaLeaderboardBatchError("SCORE_NOT_REPRESENTABLE")
        return score_numeric

    def extract_claims(
        self,
        source: OfficialSource,
        snapshot: SourceSnapshot,
        raw_bytes: bytes,
        parquet_resolver: ParquetEvidenceResolver | None = None,
    ) -> list[ResultClaimInput]:
        config = self._config(source)
        if config is None:
            raise LMArenaLeaderboardBatchError("CONFIG_INVALID")

        claims: list[ResultClaimInput] = []
        seen_identities: set[tuple[str, str, str]] = set()
        record_count = 0
        required_fields = set(self._FIELD_MAP.values())

        try:
            if parquet_resolver is not None:
                parquet_resolver.verify(raw_bytes)
                records = parquet_resolver.iter_records()
            else:
                records = iter_parquet_records(raw_bytes)

            for row_group, row_index, record in records:
                record_count += 1
                if any(field not in record for field in required_fields):
                    raise LMArenaLeaderboardBatchError("PARQUET_COLUMN_MISSING")

                model_raw = record[self._FIELD_MAP["model_raw"]]
                score_raw = record[self._FIELD_MAP["score_raw"]]
                category_raw = record[self._FIELD_MAP["split_raw"]]
                publish_date_raw = record[self._FIELD_MAP["evaluation_version_raw"]]
                rank_raw = record[self._FIELD_MAP["rank_raw"]]
                if not model_raw:
                    raise LMArenaLeaderboardBatchError("MODEL_VALUE_MISSING")
                if not category_raw:
                    raise LMArenaLeaderboardBatchError("CATEGORY_VALUE_MISSING")
                if not publish_date_raw:
                    raise LMArenaLeaderboardBatchError("PUBLISH_DATE_VALUE_MISSING")

                identity = (model_raw, category_raw, publish_date_raw)
                if identity in seen_identities:
                    raise LMArenaLeaderboardBatchError("DUPLICATE_MODEL_CATEGORY_DATE")
                seen_identities.add(identity)

                claims.append(
                    ResultClaimInput(
                        official_source_id=source.id,
                        source_snapshot_id=snapshot.id,
                        benchmark_id=source.benchmark_id,
                        model_raw=model_raw,
                        benchmark_raw=config["benchmark_raw"],
                        score_raw=score_raw,
                        metric_raw=config["metric_raw"],
                        split_raw=category_raw,
                        setting_raw=config["setting_raw"],
                        evaluation_version_raw=publish_date_raw,
                        rank_raw=rank_raw,
                        score_numeric=self._strict_numeric(score_raw),
                        evidence_location={
                            "type": "parquet_cell_v1",
                            "row_group": row_group,
                            "row_index": row_index,
                            "fields": dict(self._FIELD_MAP),
                        },
                        capture_method="lmarena_leaderboard_parquet_parser",
                        capture_confidence=0.0,
                        capture_status="unreviewed",
                        officialness_level=source.officialness_level,
                    )
                )
        except ParquetCellError:
            raise LMArenaLeaderboardBatchError("PARQUET_UNREADABLE") from None

        if record_count == 0:
            raise LMArenaLeaderboardBatchError("PARQUET_EMPTY")
        if len(claims) != record_count:
            raise LMArenaLeaderboardBatchError("INCOMPLETE_ACCOUNTING")
        return claims

    def validate_claim(
        self,
        claim: ResultClaimInput,
        raw_bytes: bytes,
        parquet_resolver: ParquetEvidenceResolver | None = None,
    ) -> list[ClaimValidationInput]:
        outcome = "uncertain"
        locator = claim.evidence_location
        if isinstance(locator, dict) and locator.get("type") == "parquet_cell_v1":
            record, error = read_parquet_record(
                raw_bytes,
                row_group=locator.get("row_group"),
                row_index=locator.get("row_index"),
                resolver=parquet_resolver,
            )
            fields = locator.get("fields")
            expected = {
                "model_raw": claim.model_raw,
                "score_raw": claim.score_raw,
                "split_raw": claim.split_raw,
                "evaluation_version_raw": claim.evaluation_version_raw,
                "rank_raw": claim.rank_raw,
            }
            if (
                error is None
                and record is not None
                and fields == self._FIELD_MAP
                and all(record.get(fields[name]) == value for name, value in expected.items())
            ):
                outcome = "pass"

        return [
            ClaimValidationInput(
                validation_type="parquet_cell_match",
                outcome=outcome,
                validator="LMArenaLeaderboardParquetAdapter",
            )
        ]


__all__ = [
    "ARTIFACT_PATH",
    "ARTIFACT_URL",
    "DATASET_CONFIG",
    "DATASET_ID",
    "DATASET_REVISION",
    "DATASET_SPLIT",
    "LMArenaLeaderboardBatchError",
    "LMArenaLeaderboardParquetAdapter",
]
