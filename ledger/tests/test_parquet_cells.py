from __future__ import annotations

from decimal import Decimal
import importlib
import io

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from app.ingestion.parquet_cells import (
    MAX_PARQUET_BATCH_SIZE,
    MAX_PARQUET_CELLS,
    MAX_PARQUET_COLUMNS,
    MAX_PARQUET_DECOMPRESSED_BYTES,
    MAX_PARQUET_ROW_GROUPS,
    MAX_PARQUET_ROWS,
    ParquetCellError,
    ParquetEvidenceResolver,
    ParquetMetadataLimitError,
    _enforce_metadata_limits,
    _metadata_limit_reason,
    _range_bounded,
    _require_nonnegative_int,
    iter_parquet_records,
    parquet_row_group_rows,
    read_parquet_record,
    render_cell_lexeme,
)


def _write(table: pa.Table, *, row_group_size: int | None = None) -> bytes:
    buffer = io.BytesIO()
    pq.write_table(table, buffer, row_group_size=row_group_size)
    return buffer.getvalue()


def _rich_table() -> pa.Table:
    schema = pa.schema(
        [
            pa.field("model", pa.string()),
            pa.field("score_f", pa.float64()),
            pa.field("score_s", pa.string()),
            pa.field("score_d", pa.decimal128(10, 2)),
            pa.field("rank", pa.int64()),
            pa.field("note", pa.string()),
            pa.field("flag", pa.bool_()),
            pa.field("tags", pa.list_(pa.string())),
            pa.field("stamp", pa.timestamp("us")),
        ]
    )
    rows = [
        (
            "Model A",
            0.875,
            "001.2300",
            Decimal("87.50"),
            1,
            "first",
            True,
            ["x"],
            1_700_000_000_000_000,
        ),
        ("Model B", 1.5, "1.5", Decimal("99.00"), 2, None, False, ["y"], None),
    ]
    columns = [pa.array([row[i] for row in rows], type=schema[i].type) for i in range(len(schema))]
    return pa.Table.from_arrays(columns, schema=schema)


def test_render_cell_lexeme_preserves_raw_lexemes_exactly() -> None:
    assert render_cell_lexeme("verbatim") == "verbatim"
    assert render_cell_lexeme(42) == "42"
    assert render_cell_lexeme(-7) == "-7"
    assert render_cell_lexeme(0.875) == "0.875"
    assert render_cell_lexeme(1.5) == "1.5"
    assert render_cell_lexeme(Decimal("87.50")) == "87.50"
    assert render_cell_lexeme(Decimal("0.010")) == "0.010"


def test_render_cell_lexeme_rejects_unsupported_values_without_coercion() -> None:
    assert render_cell_lexeme(None) is None
    assert render_cell_lexeme(True) is None
    assert render_cell_lexeme(b"bytes") is None
    assert render_cell_lexeme(["nested"]) is None


def test_render_cell_lexeme_renders_nonfinite_floats_for_admission_rejection() -> None:
    assert render_cell_lexeme(float("nan")) == "nan"
    assert render_cell_lexeme(float("inf")) == "inf"
    assert render_cell_lexeme(float("-inf")) == "-inf"


def test_read_parquet_record_resolves_exact_cells_across_row_groups() -> None:
    raw = _write(_rich_table(), row_group_size=1)
    first, error = read_parquet_record(raw, row_group=0, row_index=0)
    assert error is None
    assert first is not None
    assert first["model"] == "Model A"
    assert first["score_f"] == "0.875"
    assert first["score_s"] == "001.2300"
    assert first["score_d"] == "87.50"
    assert first["rank"] == "1"
    assert first["note"] == "first"
    # Null, boolean, nested, and temporal cells never enter the record.
    assert "flag" not in first
    assert "tags" not in first
    assert "stamp" not in first

    second, error = read_parquet_record(raw, row_group=1, row_index=0)
    assert error is None
    assert second is not None
    assert second["model"] == "Model B"
    assert second["score_f"] == "1.5"
    assert "note" not in second  # null stays absent


def test_read_parquet_record_bounds_and_shape_fail_closed() -> None:
    raw = _write(_rich_table(), row_group_size=1)
    _, error = read_parquet_record(raw, row_group=2, row_index=0)
    assert error == "EVIDENCE_NOT_FOUND"
    _, error = read_parquet_record(raw, row_group=0, row_index=1)
    assert error == "EVIDENCE_NOT_FOUND"
    _, error = read_parquet_record(raw, row_group=-1, row_index=0)
    assert error == "EVIDENCE_LOCATOR_INVALID"
    _, error = read_parquet_record(raw, row_group=0, row_index="0")
    assert error == "EVIDENCE_LOCATOR_INVALID"
    _, error = read_parquet_record(raw, row_group=True, row_index=0)
    assert error == "EVIDENCE_LOCATOR_INVALID"
    _, error = read_parquet_record(b"not a parquet file", row_group=0, row_index=0)
    assert error == "EVIDENCE_LOCATOR_INVALID"


def test_parquet_row_group_rows_reports_exact_denominators() -> None:
    raw = _write(_rich_table(), row_group_size=1)
    counts, error = parquet_row_group_rows(raw)
    assert error is None
    assert counts == (1, 1)
    counts, error = parquet_row_group_rows(b"garbage")
    assert counts is None
    assert error == "EVIDENCE_LOCATOR_INVALID"


def test_parquet_row_group_rows_is_metadata_only_no_row_decode(monkeypatch) -> None:
    """Row-group denominators must be read from the footer, never by decoding rows.

    If ``parquet_row_group_rows`` ever decoded row data, it would call
    ``ParquetFile.read_row_group`` (the entry point that materializes a
    ``pyarrow.Table``); we wire that call to fail loudly, so a correct
    metadata-only path still succeeds while a decode-based path errors out.
    (``to_pylist`` lives on the returned ``Table`` and cannot be reached
    without first calling ``read_row_group``.)
    """
    raw = _write(_rich_table(), row_group_size=1)

    def _no_row_read(*_args, **_kwargs):  # pragma: no cover - must not run
        raise AssertionError("parquet_row_group_rows must not decode row data")

    monkeypatch.setattr(pq.ParquetFile, "read_row_group", _no_row_read)
    counts, error = parquet_row_group_rows(raw)
    assert error is None
    assert counts == (1, 1)


def test_iter_parquet_records_accounts_for_every_row() -> None:
    raw = _write(_rich_table(), row_group_size=1)
    rows = list(iter_parquet_records(raw))
    assert [(group, index) for group, index, _ in rows] == [(0, 0), (1, 0)]
    assert rows[0][2]["model"] == "Model A"
    assert rows[1][2]["model"] == "Model B"


def test_iter_parquet_records_fails_closed_on_malformed_bytes() -> None:
    with pytest.raises(ParquetCellError):
        list(iter_parquet_records(b"definitely not parquet"))


# --- Claim-admission integration through the exact source-revision policy ---

from uuid import UUID  # noqa: E402

from app.db import models, repositories as repo  # noqa: E402
from app.db.engine import get_session  # noqa: E402
from app.ingestion.admission import (  # noqa: E402
    ADMISSION_POLICY_SCHEMA,
    resolve_claim_admission,
    resolve_source_admission,
)
from app.matching.aliases import resolve_benchmark, resolve_model_entity  # noqa: E402
from app.schemas.boundary import OfficialSource, ResultClaimInput  # noqa: E402

BENCHMARK_RAW = "Parquet admission fixture benchmark"
MODEL_RAW = "Model A"


def _parquet_source(session, *, source_id: str = "parquet-fixture-source"):
    reconciled = repo.reconcile_official_source(
        session,
        {
            "id": source_id,
            "benchmark_id": "hf_official_benchmarks",
            "source_name": "Certified parquet admission fixture",
            "source_url": f"https://official.example/{source_id}.parquet",
            "source_type": "api",
            "officialness_level": "O5",
            "machine_readable": True,
            "requires_auth": False,
            "supports_history": False,
            "update_cadence": "manual",
            "parser_name": "parquet_fixture_adapter",
            "parser_version": "fixture-v1",
            "parser_config": {
                "governance": {
                    "production_eligible": True,
                    "result_kind": "reported_result",
                    "direct_source_only": True,
                }
            },
            "status": "active",
            "notes": "B1 parquet fixture only",
        },
    )
    row = reconciled.source
    source = OfficialSource(
        id=row.id,
        benchmark_id=row.benchmark_id,
        source_name=row.source_name,
        source_url=row.source_url,
        source_type=row.source_type,
        officialness_level=row.officialness_level,
        machine_readable=row.machine_readable,
        requires_auth=row.requires_auth,
        supports_history=row.supports_history,
        update_cadence=row.update_cadence,
        parser_name=row.parser_name,
        parser_version=row.parser_version,
        parser_config=row.parser_config or {},
        status=row.status,
        notes=row.notes,
    )
    return source, reconciled.revision


def _parquet_policy(source, revision, *, fields=None, evidence_contracts=None):
    selected_fields = fields or {"model_raw": "model", "score_raw": "score_f"}
    return {
        "schema": ADMISSION_POLICY_SCHEMA,
        "definition_hash": revision.definition_hash,
        "source_kind": "official_reported_result",
        "adapter": {
            "parser_name": source.parser_name,
            "parser_version": source.parser_version,
        },
        "approved_source_urls": [source.source_url],
        "approved_final_urls": [source.source_url],
        "locator_types": ["parquet_cell_v1"],
        "evidence_contracts": evidence_contracts
        or {"parquet_cell_v1": {"fields": selected_fields}},
        "dimensions": {
            "benchmark_raw": {
                "mode": "revision_constant",
                "value": BENCHMARK_RAW,
                "allowed_values": [BENCHMARK_RAW],
            },
            "metric_raw": {"mode": "revision_constant", "value": None, "allowed_values": [None]},
            "split_raw": {"mode": "revision_constant", "value": None, "allowed_values": [None]},
            "setting_raw": {"mode": "revision_constant", "value": None, "allowed_values": [None]},
            "evaluation_version_raw": {
                "mode": "revision_constant",
                "value": None,
                "allowed_values": [None],
            },
        },
        "numeric": {"lexeme": "decimal", "score_unit": None},
        "fetch": {"max_bytes": 5 * 1024 * 1024},
    }


def _certify(session, *, source, revision, policy):
    from sqlalchemy import select as _select

    supersedes = session.scalar(
        _select(models.SourceRevisionDecision.id).where(
            models.SourceRevisionDecision.source_revision_id == revision.id
        )
    )
    decision = models.SourceRevisionDecision(
        source_revision_id=revision.id,
        outcome="certified",
        policy_version=ADMISSION_POLICY_SCHEMA,
        reason_code="fixture_certification",
        basis_json={"source_admission": policy},
        actor="test",
        supersedes_decision_id=supersedes,
    )
    session.add(decision)
    session.flush()
    return decision


def _add_model(session, *, model_id: str = "model-a", alias: str = MODEL_RAW) -> None:
    session.add(
        models.ModelEntity(
            id=model_id,
            canonical_name=model_id,
            display_name=model_id,
            entity_type="model",
        )
    )
    session.add(
        models.Alias(
            entity_type="model_entity",
            entity_id=model_id,
            alias_text=alias,
            alias_source="test",
            is_official_alias=True,
        )
    )
    session.flush()


def _parquet_claim(source, decision, *, score_raw, score_numeric, row_group=0, row_index=0, fields=None):
    return ResultClaimInput(
        source_revision_decision_id=UUID(decision.id),
        official_source_id=source.id,
        benchmark_id=source.benchmark_id,
        model_raw=MODEL_RAW,
        benchmark_raw=BENCHMARK_RAW,
        score_raw=score_raw,
        metric_raw=None,
        score_numeric=score_numeric,
        score_unit=None,
        evidence_location={
            "type": "parquet_cell_v1",
            "row_group": row_group,
            "row_index": row_index,
            "fields": fields or {"model_raw": "model", "score_raw": "score_f"},
        },
        capture_method="parquet_fixture_adapter",
        capture_confidence=1.0,
        capture_status="unreviewed",
        officialness_level=source.officialness_level,
    )


def _admitted_setup(session):
    source, revision = _parquet_source(session)
    policy = _parquet_policy(source, revision)
    decision = _certify(session, source=source, revision=revision, policy=policy)
    admission = resolve_source_admission(session, source=source, source_revision=revision)
    assert admission.verdict.disposition == "admit"
    _add_model(session)
    return source, decision, admission


def _resolve(session, *, source, admission, claim, raw_bytes, parquet_resolver=None):
    model_match = resolve_model_entity(session, claim.model_raw)
    benchmark_match = resolve_benchmark(session, claim.benchmark_raw, source.benchmark_id)
    claim.model_entity_id = model_match.entity_id
    claim.benchmark_id = benchmark_match.entity_id
    return resolve_claim_admission(
        source_admission=admission,
        source=source,
        claim=claim,
        raw_bytes=raw_bytes,
        model_match=model_match,
        benchmark_match=benchmark_match,
        parquet_resolver=parquet_resolver,
    )


def test_parquet_claim_admission_admits_exact_reresolution(seeded_db) -> None:
    raw = _write(_rich_table(), row_group_size=1)
    with get_session() as session:
        source, decision, admission = _admitted_setup(session)
        claim = _parquet_claim(source, decision, score_raw="0.875", score_numeric=0.875)
        result = _resolve(session, source=source, admission=admission, claim=claim, raw_bytes=raw)
        assert result.verdict.disposition == "admit", result.verdict
        assert result.score_numeric == 0.875


def test_parquet_claim_admission_preserves_string_lexeme_verbatim(seeded_db) -> None:
    raw = _write(_rich_table(), row_group_size=1)
    with get_session() as session:
        source, revision = _parquet_source(session, source_id="parquet-string-source")
        policy = _parquet_policy(
            source, revision, fields={"model_raw": "model", "score_raw": "score_s"}
        )
        decision = _certify(session, source=source, revision=revision, policy=policy)
        admission = resolve_source_admission(session, source=source, source_revision=revision)
        _add_model(session)
        claim = _parquet_claim(
            source,
            decision,
            score_raw="001.2300",
            score_numeric=1.23,
            fields={"model_raw": "model", "score_raw": "score_s"},
        )
        result = _resolve(session, source=source, admission=admission, claim=claim, raw_bytes=raw)
        assert result.verdict.disposition == "admit", result.verdict


def test_parquet_claim_admission_rejects_drifted_values(seeded_db) -> None:
    raw = _write(_rich_table(), row_group_size=1)
    with get_session() as session:
        source, decision, admission = _admitted_setup(session)
        claim = _parquet_claim(source, decision, score_raw="0.876", score_numeric=0.876)
        result = _resolve(session, source=source, admission=admission, claim=claim, raw_bytes=raw)
        assert result.verdict.disposition == "reject"
        assert result.verdict.reason_code == "EVIDENCE_VALUE_MISMATCH"


def test_parquet_claim_admission_rejects_locator_shape_drift(seeded_db) -> None:
    raw = _write(_rich_table(), row_group_size=1)
    with get_session() as session:
        source, decision, admission = _admitted_setup(session)
        claim = _parquet_claim(source, decision, score_raw="0.875", score_numeric=0.875)
        del claim.evidence_location["row_group"]
        result = _resolve(session, source=source, admission=admission, claim=claim, raw_bytes=raw)
        assert result.verdict.reason_code == "EVIDENCE_LOCATOR_CONTRACT_MISMATCH"


def test_parquet_claim_admission_rejects_missing_record(seeded_db) -> None:
    raw = _write(_rich_table(), row_group_size=1)
    with get_session() as session:
        source, decision, admission = _admitted_setup(session)
        claim = _parquet_claim(
            source, decision, score_raw="0.875", score_numeric=0.875, row_group=0, row_index=9
        )
        result = _resolve(session, source=source, admission=admission, claim=claim, raw_bytes=raw)
        assert result.verdict.reason_code == "EVIDENCE_NOT_FOUND"


def test_parquet_claim_admission_rejects_nonfinite_score_without_coercion(seeded_db) -> None:
    table = pa.table({"model": [MODEL_RAW], "score_f": [float("nan")]})
    raw = _write(table)
    with get_session() as session:
        source, decision, admission = _admitted_setup(session)
        claim = _parquet_claim(source, decision, score_raw="nan", score_numeric=None)
        result = _resolve(session, source=source, admission=admission, claim=claim, raw_bytes=raw)
        assert result.verdict.reason_code == "SCORE_NOT_NUMERIC"


def test_parquet_claim_admission_rejects_unsupported_column_reference(seeded_db) -> None:
    raw = _write(_rich_table(), row_group_size=1)
    with get_session() as session:
        source, revision = _parquet_source(session, source_id="parquet-bool-source")
        flag_fields = {"model_raw": "model", "score_raw": "flag"}
        policy = _parquet_policy(source, revision, fields=flag_fields)
        decision = _certify(session, source=source, revision=revision, policy=policy)
        admission = resolve_source_admission(session, source=source, source_revision=revision)
        assert admission.verdict.disposition == "admit"
        _add_model(session)
        claim = _parquet_claim(
            source,
            decision,
            score_raw="true",
            score_numeric=None,
            fields=flag_fields,
        )
        result = _resolve(session, source=source, admission=admission, claim=claim, raw_bytes=raw)
        assert result.verdict.reason_code == "EVIDENCE_VALUE_NOT_VERBATIM"


def test_parquet_claim_admission_fails_closed_on_mismatched_resolver(seeded_db) -> None:
    raw = _write(_rich_table(), row_group_size=1)
    # A genuinely different snapshot (different content -> different digest).
    other = _write(
        pa.table({"model": ["Drift"], "score_f": [0.999]}), row_group_size=1
    )
    with get_session() as session:
        source, decision, admission = _admitted_setup(session)
        claim = _parquet_claim(source, decision, score_raw="0.875", score_numeric=0.875)
        # A resolver bound to a DIFFERENT snapshot must fail closed at admission,
        # never silently resolve the claim against the wrong bytes.
        mismatched = ParquetEvidenceResolver(other)
        result = _resolve(
            session,
            source=source,
            admission=admission,
            claim=claim,
            raw_bytes=raw,
            parquet_resolver=mismatched,
        )
        assert result.verdict.reason_code == "EVIDENCE_SNAPSHOT_MISMATCH"
        mismatched.close()


def test_parquet_claim_admission_reuses_same_snapshot_resolver(seeded_db) -> None:
    raw = _write(_rich_table(), row_group_size=1)
    with get_session() as session:
        source, decision, admission = _admitted_setup(session)
        claim = _parquet_claim(source, decision, score_raw="0.875", score_numeric=0.875)
        resolver = ParquetEvidenceResolver(raw)
        result = _resolve(
            session,
            source=source,
            admission=admission,
            claim=claim,
            raw_bytes=raw,
            parquet_resolver=resolver,
        )
        assert result.verdict.disposition == "admit", result.verdict
        resolver.close()


def test_source_admission_rejects_malformed_parquet_evidence_contract(seeded_db) -> None:
    with get_session() as session:
        source, revision = _parquet_source(session, source_id="parquet-bad-contract")
        policy = _parquet_policy(
            source,
            revision,
            evidence_contracts={
                "parquet_cell_v1": {
                    "fields": {"model_raw": "model", "score_raw": "score_f"},
                    "row_group": 0,
                }
            },
        )
        _certify(session, source=source, revision=revision, policy=policy)
        denied = resolve_source_admission(session, source=source, source_revision=revision)
        assert denied.verdict.disposition == "reject"
        assert denied.verdict.reason_code == "SRC_POLICY_INVALID"


# --- Metadata-derived resource caps (hostile footer, no allocation) ----------


def test_metadata_limit_reason_is_pure_and_numeric() -> None:
    """The cardinality checker is a pure helper, so hostile grids are tested
    as plain integers without constructing any Parquet object at all (no
    allocation of the claimed table)."""
    # At the exact caps: accepted.
    assert _metadata_limit_reason(
        row_groups=MAX_PARQUET_ROW_GROUPS,
        columns=MAX_PARQUET_COLUMNS,
        rows=MAX_PARQUET_ROWS,
        cells=MAX_PARQUET_CELLS,
        decompressed_bytes=MAX_PARQUET_DECOMPRESSED_BYTES,
    ) is None
    # Each dimension just above its cap maps to a stable reason token.
    assert _metadata_limit_reason(
        row_groups=MAX_PARQUET_ROW_GROUPS + 1, columns=1, rows=1, cells=1, decompressed_bytes=1
    ) == "row_groups"
    assert _metadata_limit_reason(
        row_groups=1, columns=MAX_PARQUET_COLUMNS + 1, rows=1, cells=1, decompressed_bytes=1
    ) == "columns"
    assert _metadata_limit_reason(
        row_groups=1, columns=1, rows=MAX_PARQUET_ROWS + 1, cells=1, decompressed_bytes=1
    ) == "rows"
    # Cell-count cap keyed on the rows*columns product.
    assert _metadata_limit_reason(
        row_groups=1, columns=1, rows=1, cells=MAX_PARQUET_CELLS + 1, decompressed_bytes=1
    ) == "cells"
    assert _metadata_limit_reason(
        row_groups=1, columns=1, rows=1, cells=1,
        decompressed_bytes=MAX_PARQUET_DECOMPRESSED_BYTES + 1,
    ) == "decompressed_size"


def test_metadata_limit_error_is_stable_typed_parquet_error() -> None:
    err = ParquetMetadataLimitError("cells")
    assert isinstance(err, ParquetCellError)
    assert isinstance(err, ValueError)
    assert err.reason == "cells"
    assert "cells" in str(err)


def test_metadata_limit_error_carries_full_stable_token_set() -> None:
    """The stable token set is both the base cap tokens and the strict
    ``metadata_*`` prefix families.  The docstring and the locator error
    contract must agree with this exact set."""
    base_tokens = {
        "row_groups",
        "columns",
        "rows",
        "cells",
        "decompressed_size",
    }
    strict_tokens = {
        "metadata_row_groups",
        "metadata_columns",
        "metadata_rows",
        "metadata_decompressed_size",
    }
    for token in sorted(base_tokens | strict_tokens):
        err = ParquetMetadataLimitError(token)
        assert isinstance(err, ParquetCellError)
        assert err.reason == token
        assert token in str(err)


def test_require_nonnegative_int_fails_closed_on_invalid() -> None:
    """Ill-typed or negative metadata denominators are never coerced."""
    assert _require_nonnegative_int(0, "rows") == 0
    assert _require_nonnegative_int(5, "rows") == 5
    for bad in (-1, -100, 1.5, "5", None, True):
        with pytest.raises(ParquetMetadataLimitError) as raised:
            _require_nonnegative_int(bad, "rows")
        assert raised.value.reason == "metadata_rows"


def test_range_bounded_scalar_cap_gate_before_row_access(monkeypatch) -> None:
    """A hostile ``num_row_groups`` is rejected by the scalar row-group cap
    *before* any row-group access or any iteration over the count.

    The load-bearing seam: if the implementation ever fell through to touch a
    row group (``metadata.row_group``) or to iterate a ``range`` over the
    hostile count before rejecting, this test fails loudly.
    """
    imported = importlib.import_module("app.ingestion.parquet_cells")
    raw = _write(_rich_table(), row_group_size=1)
    touched = {"row_group_access": 0, "range_iterations": 0, "close": 0}

    class _FakeColumn:
        def __init__(self):
            self.total_uncompressed_size = 100

    class _FakeRowGroup:
        num_columns = 1

        def column(self, _i):
            return _FakeColumn()

    class _FakeMetadata:
        num_columns = 1

        def row_group(self, _i):
            touched["row_group_access"] += 1
            raise AssertionError("hostile row-group count must not access a row group")

    class _FakeFile:
        num_row_groups = MAX_PARQUET_ROW_GROUPS + 1  # over the scalar cap

        @property
        def metadata(self):
            return _FakeMetadata()

        def close(self, force=False):
            touched["close"] += 1

    real_run = imported._range_bounded

    def _counting_range(count):
        touched["range_iterations"] += 1
        return real_run(count)

    monkeypatch.setattr(imported, "_range_bounded", _counting_range)
    monkeypatch.setattr(imported, "_open", lambda _b: _FakeFile())

    with pytest.raises(ParquetMetadataLimitError) as raised:
        imported.ParquetEvidenceResolver(raw)  # type: ignore[no-untyped-call]
    assert raised.value.reason == "row_groups"
    # The scalar cap rejected the claim before any row-group access or any
    # iteration over the hostile count, and the handle was force-closed.
    assert touched["row_group_access"] == 0
    assert touched["range_iterations"] == 0
    assert touched["close"] == 1


def test_bounded_footer_is_accepted_and_binding_preserved() -> None:
    """A normal (legal) footer clears the caps and still decodes exactly."""
    raw = _write(_rich_table(), row_group_size=1)
    resolver = ParquetEvidenceResolver(raw)
    assert resolver.row_group_rows == (1, 1)
    record, error = resolver.read(row_group=0, row_index=0)
    assert error is None
    assert record is not None and record["model"] == "Model A"
    resolver.close()


def test_real_snapshot_metadata_counts_as_expected() -> None:
    """Sum-of-uncompressed-sizes stays under the cap for current fixtures and
    the metadata-only row-group denominator matches expectations."""
    raw = _write(_rich_table(), row_group_size=1)
    parquet_file = pq.ParquetFile(io.BytesIO(raw))
    try:
        # Must not raise on a legal, bounded artifact.
        _enforce_metadata_limits(parquet_file)
    finally:
        parquet_file.close()


def test_focused_fixture_fits_under_final_caps_with_headroom() -> None:
    """The 10k-row x 3-column fixture (30,000 cells) has ~10x row and >16x cell
    headroom against the final safety ceilings.

    ``MAX_PARQUET_ROWS`` = 100,000 is exactly 10x the 10k fixture rows and
    ``MAX_PARQUET_CELLS`` = 500,000 is 500,000/30,000 ~= 16.7x the fixture
    cells.  These ceilings are safety ceilings, not heap guarantees: the
    decoded Python amplification (dicts + ResultClaimInput + duplicate-set
    entries) is what bounds heap, not the encoded Parquet size.
    """
    # 10k rows x 3 columns = 30,000 cells, all well under the final caps.
    assert 10_000 <= MAX_PARQUET_ROWS
    assert 3 <= MAX_PARQUET_COLUMNS
    assert 30_000 <= MAX_PARQUET_CELLS
    # ~10x row headroom and >16x cell headroom over the current fixture.
    assert MAX_PARQUET_ROWS >= 10_000 * 10
    assert MAX_PARQUET_CELLS >= 30_000 * 10
    # The caps are deliberately conservative safety ceilings (well bounded),
    # and the fixture remains the compatibility evidence.
    assert MAX_PARQUET_ROWS <= 1_000_000
    assert MAX_PARQUET_CELLS <= 4_000_000




def _fake_file2(row_groups, columns, *, groups=None, touch_row_raises=False):
    """Instrumented fake ParquetFile metadata for strict/cap tests."""
    holder = {"closed": 0, "force": None, "decode": 0, "iter": 0,
              "groups": list(groups or []), "raises": touch_row_raises}

    class _Meta:
        num_columns = columns

        def row_group(self, i):
            if holder["raises"]:
                raise AssertionError("row-group accessed before scalar-cap rejection")
            return holder["groups"][i]

    class _Fake:
        @property
        def num_row_groups(self):
            return row_groups

        @property
        def metadata(self):
            return _Meta()

        def close(self, force=False):
            holder["closed"] += 1
            holder["force"] = force

        def iter_batches(self, *a, **k):
            holder["iter"] += 1
            raise AssertionError("must not decode")

        def read_row_group(self, *a, **k):
            holder["decode"] += 1
            raise AssertionError("must not decode")

    _Fake.holder = holder
    return _Fake()


def _rg2(num_rows, num_columns, uncompressed):
    class _Column:
        total_uncompressed_size = uncompressed

    group = type("RG", (), {})()
    group.num_rows = num_rows
    group.num_columns = num_columns
    group.column = lambda _i: _Column()
    return group


def test_row_groups_cap_checked_before_row_access(monkeypatch) -> None:
    imported = importlib.import_module("app.ingestion.parquet_cells")
    raw = _write(_rich_table(), row_group_size=1)
    Fake = _fake_file2(MAX_PARQUET_ROW_GROUPS + 1, 1, touch_row_raises=True)
    monkeypatch.setattr(imported, "_open", lambda _b: Fake)
    with pytest.raises(ParquetMetadataLimitError) as raised:
        imported.ParquetEvidenceResolver(raw)  # type: ignore[no-untyped-call]
    assert raised.value.reason == "row_groups"
    assert Fake.holder["decode"] == 0 and Fake.holder["iter"] == 0
    assert Fake.holder["closed"] == 1 and Fake.holder["force"] is True


def test_columns_cap_checked_before_any_decode(monkeypatch) -> None:
    imported = importlib.import_module("app.ingestion.parquet_cells")
    raw = _write(_rich_table(), row_group_size=1)
    Fake = _fake_file2(1, MAX_PARQUET_COLUMNS + 1, touch_row_raises=True)
    monkeypatch.setattr(imported, "_open", lambda _b: Fake)
    with pytest.raises(ParquetMetadataLimitError) as raised:
        imported.ParquetEvidenceResolver(raw)  # type: ignore[no-untyped-call]
    assert raised.value.reason == "columns"
    assert Fake.holder["decode"] == 0 and Fake.holder["iter"] == 0
    assert Fake.holder["closed"] == 1


def test_inconsistent_group_column_count_fails_closed(monkeypatch) -> None:
    imported = importlib.import_module("app.ingestion.parquet_cells")
    Fake = _fake_file2(1, 2, groups=[_rg2(1, 99, 10)])
    with pytest.raises(ParquetMetadataLimitError) as raised:
        imported._enforce_metadata_limits(Fake)
    assert raised.value.reason == "columns"


def test_negative_group_rows_fail_closed(monkeypatch) -> None:
    imported = importlib.import_module("app.ingestion.parquet_cells")
    Fake = _fake_file2(1, 2, groups=[_rg2(-5, 2, 10)])
    with pytest.raises(ParquetMetadataLimitError) as raised:
        imported._enforce_metadata_limits(Fake)
    assert raised.value.reason == "metadata_rows"


def test_negative_uncompressed_size_fails_closed(monkeypatch) -> None:
    imported = importlib.import_module("app.ingestion.parquet_cells")
    Fake = _fake_file2(1, 1, groups=[_rg2(1, 1, -50)])
    with pytest.raises(ParquetMetadataLimitError) as raised:
        imported._enforce_metadata_limits(Fake)
    assert raised.value.reason == "metadata_decompressed_size"


def test_group_rows_must_be_int(monkeypatch) -> None:
    imported = importlib.import_module("app.ingestion.parquet_cells")
    Fake = _fake_file2(1, 2, groups=[_rg2("five", 2, 10)])
    with pytest.raises(ParquetMetadataLimitError) as raised:
        imported._enforce_metadata_limits(Fake)
    assert raised.value.reason == "metadata_rows"
