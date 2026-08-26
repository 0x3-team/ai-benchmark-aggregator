from __future__ import annotations

import io
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
import yaml

from app.db.models import SourceSnapshot
from app.db.engine import get_session
from app.ingestion.adapters import ADAPTERS, get_adapter
from app.ingestion.adapters.lmarena_leaderboard_parquet import (
    ARTIFACT_PATH,
    ARTIFACT_URL,
    DATASET_CONFIG,
    DATASET_ID,
    DATASET_REVISION,
    DATASET_SPLIT,
    LMArenaLeaderboardBatchError,
    LMArenaLeaderboardParquetAdapter,
)
from app.ingestion.parquet_cells import read_parquet_record
from app.ingestion.policy import source_admission_reason
from app.matching.aliases import resolve_model_entity
from app.schemas.boundary import OfficialSource


SNAPSHOT = SourceSnapshot(
    id="33333333-3333-3333-3333-333333333333",
    official_source_id="lmarena-first-party-fixture",
    raw_content_uri="memory://lmarena-first-party.parquet",
    content_hash="c" * 64,
)
REGISTRY = Path(__file__).resolve().parents[1] / "app" / "registry" / "official_sources.yaml"
SOURCE_SCHEMA = pa.schema(
    [
        pa.field("model_name", pa.string()),
        pa.field("rating", pa.float64()),
        pa.field("rating_lower", pa.float64()),
        pa.field("rating_upper", pa.float64()),
        pa.field("variance", pa.float64()),
        pa.field("vote_count", pa.int64()),
        pa.field("rank", pa.int64()),
        pa.field("category", pa.string()),
        pa.field("leaderboard_publish_date", pa.string()),
    ]
)


def _row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "model_name": "Unregistered Arena Fixture Model",
        "rating": 1264.25,
        "rating_lower": 1249.5,
        "rating_upper": 1278.75,
        "variance": 54.125,
        "vote_count": 4096,
        "rank": 7,
        "category": "Overall",
        "leaderboard_publish_date": "2026-08-03",
    }
    row.update(overrides)
    return row


def _parquet(
    rows: list[dict[str, object]],
    *,
    schema: pa.Schema = SOURCE_SCHEMA,
    row_group_size: int | None = None,
) -> bytes:
    table = pa.Table.from_pylist(rows, schema=schema)
    buffer = io.BytesIO()
    pq.write_table(table, buffer, row_group_size=row_group_size)
    return buffer.getvalue()


def _source(**config_overrides: object) -> OfficialSource:
    return OfficialSource(
        id="lmarena-first-party-fixture",
        benchmark_id="chatbot_arena",
        source_name="LMArena first-party fixture",
        source_url=ARTIFACT_URL,
        source_type="lmarena_leaderboard_parquet",
        officialness_level="O5",
        machine_readable=True,
        parser_name="lmarena_leaderboard_parquet",
        parser_version="fixture-candidate-v1",
        status="inactive",
        parser_config={
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
            "field_map": {
                "model_raw": "model_name",
                "score_raw": "rating",
                "split_raw": "category",
                "evaluation_version_raw": "leaderboard_publish_date",
                "rank_raw": "rank",
            },
            "omitted_context_fields": [
                "rating_lower",
                "rating_upper",
                "variance",
                "vote_count",
            ],
            **config_overrides,
        },
    )


def test_extracts_source_shaped_rating_and_every_supported_dimension() -> None:
    raw = _parquet([_row(rating=1264.0)], row_group_size=1)

    claims = LMArenaLeaderboardParquetAdapter().extract_claims(_source(), SNAPSHOT, raw)

    assert len(claims) == 1
    claim = claims[0]
    assert claim.model_raw == "Unregistered Arena Fixture Model"
    assert claim.score_raw == "1264.0"
    assert claim.score_numeric == 1264.0
    assert claim.benchmark_raw == "chatbot_arena"
    assert claim.metric_raw == "Arena Score"
    assert claim.split_raw == "Overall"
    assert claim.setting_raw == "text_style_control"
    assert claim.evaluation_version_raw == "2026-08-03"
    assert claim.rank_raw == "7"
    assert claim.capture_confidence == 0.0
    assert claim.evidence_location == {
        "type": "parquet_cell_v1",
        "row_group": 0,
        "row_index": 0,
        "fields": {
            "model_raw": "model_name",
            "score_raw": "rating",
            "split_raw": "category",
            "evaluation_version_raw": "leaderboard_publish_date",
            "rank_raw": "rank",
        },
    }
    assert set(claim.evidence_location["fields"].values()).isdisjoint(
        {"rating_lower", "rating_upper", "variance", "vote_count"}
    )
    assert not hasattr(claim, "vote_count")
    assert not hasattr(claim, "rating_lower")


def test_complete_accounting_replay_and_typed_evidence_across_row_groups() -> None:
    raw = _parquet(
        [
            _row(model_name="Model A", rating=1300.125, rank=1),
            _row(
                model_name="Model B",
                rating=1288.5,
                rank=2,
                category="Creative Writing",
            ),
        ],
        row_group_size=1,
    )
    adapter = LMArenaLeaderboardParquetAdapter()

    first = adapter.extract_claims(_source(), SNAPSHOT, raw)
    replay = adapter.extract_claims(_source(), SNAPSHOT, raw)

    assert first == replay
    assert len(first) == 2
    assert [claim.evidence_location["row_group"] for claim in first] == [0, 1]
    for claim in first:
        locator = claim.evidence_location
        record, error = read_parquet_record(
            raw,
            row_group=locator["row_group"],
            row_index=locator["row_index"],
        )
        assert error is None
        assert record is not None
        for claim_field, parquet_field in locator["fields"].items():
            assert record[parquet_field] == getattr(claim, claim_field)
        assert adapter.validate_claim(claim, raw)[0].outcome == "pass"

    altered = first[0].model_copy(update={"evaluation_version_raw": "2026-08-04"})
    assert adapter.validate_claim(altered, raw)[0].outcome == "uncertain"


@pytest.mark.parametrize(
    ("overrides", "reason_code"),
    [
        ({"model_name": None}, "PARQUET_COLUMN_MISSING"),
        ({"rating": None}, "PARQUET_COLUMN_MISSING"),
        ({"category": None}, "PARQUET_COLUMN_MISSING"),
        ({"leaderboard_publish_date": None}, "PARQUET_COLUMN_MISSING"),
        ({"rank": None}, "PARQUET_COLUMN_MISSING"),
        ({"model_name": ""}, "MODEL_VALUE_MISSING"),
        ({"category": ""}, "CATEGORY_VALUE_MISSING"),
        ({"leaderboard_publish_date": ""}, "PUBLISH_DATE_VALUE_MISSING"),
        ({"rating": float("nan")}, "SCORE_NOT_FINITE"),
        ({"rating": float("inf")}, "SCORE_NOT_FINITE"),
    ],
)
def test_null_empty_and_nonfinite_required_cells_stop_the_batch(
    overrides: dict[str, object], reason_code: str
) -> None:
    with pytest.raises(LMArenaLeaderboardBatchError) as raised:
        LMArenaLeaderboardParquetAdapter().extract_claims(
            _source(), SNAPSHOT, _parquet([_row(**overrides)])
        )

    assert raised.value.reason_code == reason_code


def test_duplicate_model_category_publish_date_stops_complete_accounting() -> None:
    raw = _parquet([_row(rating=1264.25), _row(rating=1265.75, rank=8)])

    with pytest.raises(LMArenaLeaderboardBatchError) as raised:
        LMArenaLeaderboardParquetAdapter().extract_claims(_source(), SNAPSHOT, raw)

    assert raised.value.reason_code == "DUPLICATE_MODEL_CATEGORY_DATE"


def test_same_model_in_distinct_category_or_publish_date_is_not_a_duplicate() -> None:
    raw = _parquet(
        [
            _row(category="Overall", leaderboard_publish_date="2026-08-03"),
            _row(category="Overall", leaderboard_publish_date="2026-08-10"),
            _row(category="Creative Writing", leaderboard_publish_date="2026-08-03"),
        ]
    )

    claims = LMArenaLeaderboardParquetAdapter().extract_claims(_source(), SNAPSHOT, raw)

    assert len(claims) == 3


@pytest.mark.parametrize(
    ("raw", "reason_code"),
    [
        (_parquet([]), "PARQUET_EMPTY"),
        (b"not parquet", "PARQUET_UNREADABLE"),
    ],
)
def test_empty_or_unreadable_artifact_stops_the_batch(raw: bytes, reason_code: str) -> None:
    with pytest.raises(LMArenaLeaderboardBatchError) as raised:
        LMArenaLeaderboardParquetAdapter().extract_claims(_source(), SNAPSHOT, raw)

    assert raised.value.reason_code == reason_code


def test_malformed_schema_does_not_substitute_a_similar_column() -> None:
    malformed_schema = pa.schema(
        [
            field
            for field in SOURCE_SCHEMA
            if field.name != "leaderboard_publish_date"
        ]
        + [pa.field("publish_date", pa.string())]
    )
    malformed_row = _row()
    malformed_row["publish_date"] = malformed_row.pop("leaderboard_publish_date")

    with pytest.raises(LMArenaLeaderboardBatchError) as raised:
        LMArenaLeaderboardParquetAdapter().extract_claims(
            _source(), SNAPSHOT, _parquet([malformed_row], schema=malformed_schema)
        )

    assert raised.value.reason_code == "PARQUET_COLUMN_MISSING"


def test_malformed_numeric_schema_is_not_coerced() -> None:
    malformed_schema = pa.schema(
        [pa.field("rating", pa.string()) if field.name == "rating" else field for field in SOURCE_SCHEMA]
    )

    with pytest.raises(LMArenaLeaderboardBatchError) as raised:
        LMArenaLeaderboardParquetAdapter().extract_claims(
            _source(),
            SNAPSHOT,
            _parquet([_row(rating="not-a-rating")], schema=malformed_schema),
        )

    assert raised.value.reason_code == "SCORE_NOT_NUMERIC"


def test_parquet_metadata_resource_ceiling_is_enforced_before_extraction() -> None:
    oversized_schema = pa.schema(
        list(SOURCE_SCHEMA)
        + [pa.field(f"unexpected_{index}", pa.string()) for index in range(24)]
    )
    oversized_row = _row()
    oversized_row.update({f"unexpected_{index}": "x" for index in range(24)})

    with pytest.raises(LMArenaLeaderboardBatchError) as raised:
        LMArenaLeaderboardParquetAdapter().extract_claims(
            _source(), SNAPSHOT, _parquet([oversized_row], schema=oversized_schema)
        )

    assert raised.value.reason_code == "PARQUET_UNREADABLE"


def test_adapter_is_bounded_to_exact_candidate_revision_config_and_split() -> None:
    raw = _parquet([_row()])
    adapter = LMArenaLeaderboardParquetAdapter()

    for override in (
        {"dataset_revision": "0" * 40},
        {"config": "overall"},
        {"split": "train"},
        {"field_map": {"model_raw": "model_name", "score_raw": "rating_lower"}},
    ):
        with pytest.raises(LMArenaLeaderboardBatchError) as raised:
            adapter.extract_claims(_source(**override), SNAPSHOT, raw)
        assert raised.value.reason_code == "CONFIG_INVALID"


def test_active_source_is_refused_even_with_exact_candidate_config() -> None:
    source = _source().model_copy(update={"status": "active"})

    with pytest.raises(LMArenaLeaderboardBatchError) as raised:
        LMArenaLeaderboardParquetAdapter().extract_claims(
            source, SNAPSHOT, _parquet([_row()])
        )

    assert raised.value.reason_code == "CONFIG_INVALID"


def test_unregistered_model_identity_remains_unresolved(tmp_db) -> None:
    claim = LMArenaLeaderboardParquetAdapter().extract_claims(
        _source(), SNAPSHOT, _parquet([_row()])
    )[0]

    with get_session() as session:
        resolution = resolve_model_entity(session, claim.model_raw)

    assert resolution.status == "unmatched"
    assert resolution.entity_id is None
    assert claim.model_entity_id is None
    assert claim.model_raw == "Unregistered Arena Fixture Model"


def test_registered_candidate_is_inactive_not_certified_and_first_party_only() -> None:
    document = yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))
    sources = {row["id"]: OfficialSource(**row) for row in document["sources"]}
    candidate = sources["lmarena_first_party_leaderboard_candidate"]
    retired = sources["lmsys_arena_leaderboard"]

    assert candidate.source_url == ARTIFACT_URL
    assert candidate.status == "inactive"
    assert candidate.parser_config["mode"] == "candidate"
    assert candidate.parser_config["certification_status"] == "not_certified"
    assert candidate.parser_config["dataset_revision"] == DATASET_REVISION
    assert "CC BY 4.0" in (candidate.notes or "")
    assert "no live fetch" in (candidate.notes or "")
    assert source_admission_reason(candidate) == "source is not active"
    assert "arena.ai" not in candidate.source_url
    assert retired.status == "inactive"
    assert retired.parser_name == "lmsys_arena_api"


def test_adapter_is_concrete_registered_and_does_not_revive_lmsys() -> None:
    assert ADAPTERS["lmarena_leaderboard_parquet"] is LMArenaLeaderboardParquetAdapter
    assert type(get_adapter("lmarena_leaderboard_parquet")) is LMArenaLeaderboardParquetAdapter
    assert ADAPTERS["lmsys_arena_api"] is not LMArenaLeaderboardParquetAdapter
