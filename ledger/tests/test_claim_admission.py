from __future__ import annotations

from dataclasses import replace
from datetime import datetime
import json
from uuid import UUID

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.db import models, repositories as repo
from app.db.engine import get_session
from app.ingestion import runner as ingestion_runner
from app.ingestion.adapters.base import SourceAdapter
from app.ingestion.admission import (
    ADMISSION_POLICY_SCHEMA,
    AdmissionVerdict,
    resolve_claim_admission,
    resolve_fetch_admission,
    resolve_source_admission,
)
from app.ingestion.extractors.normalize import compute_claim_fingerprint
from app.ingestion.runner import IngestionBlockedError, run_ingestion
from app.ingestion.safe_fetch import FetchTransportResponse
from app.matching.aliases import resolve_benchmark, resolve_model_entity
from app.runtime.dependencies import (
    RuntimeCapability,
    contained_runtime_dependencies,
)
from app.schemas.boundary import (
    ClaimValidationInput,
    OfficialSource,
    ResultClaimInput,
    SourceFetchResult,
    SourceSnapshotInput,
)


BENCHMARK_RAW = "Admission fixture benchmark"
MODEL_RAW = "Admission Fixture Model"
RAW_BYTES = b'{"records":[{"model":"Admission Fixture Model","score":"001.2300"}]}'


def _governance() -> dict[str, object]:
    return {
        "production_eligible": True,
        "result_kind": "reported_result",
        "direct_source_only": True,
    }


def _source_from_row(row: models.OfficialSourceRow) -> OfficialSource:
    return OfficialSource(
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


def _make_source(
    session,
    *,
    source_id: str = "admission-fixture-source",
    source_url: str | None = None,
) -> tuple[OfficialSource, models.OfficialSourceRevision]:  # type: ignore[no-untyped-def]
    reconciled = repo.reconcile_official_source(
        session,
        {
            "id": source_id,
            "benchmark_id": "hf_official_benchmarks",
            "source_name": "Certified admission fixture",
            "source_url": source_url or f"https://official.example/{source_id}.json",
            "source_type": "api",
            "officialness_level": "O5",
            "machine_readable": True,
            "requires_auth": False,
            "supports_history": False,
            "update_cadence": "manual",
            "parser_name": "certified_fixture_adapter",
            "parser_version": "fixture-v1",
            "parser_config": {"governance": _governance()},
            "status": "active",
            "notes": "LDR-05 fixture only",
        },
    )
    return _source_from_row(reconciled.source), reconciled.revision


def _policy(
    source: OfficialSource,
    revision: models.OfficialSourceRevision,
    *,
    definition_hash: str | None = None,
    numeric: dict[str, object] | None = None,
    locator_types: list[str] | None = None,
    evidence_contracts: dict[str, object] | None = None,
) -> dict[str, object]:
    selected_locator_types = locator_types or ["json_path_v1"]
    contracts: dict[str, object] = {
        "json_path_v1": {
            "record_path_template": "$.records[{row_index}]",
            "fields": {"model_raw": "model", "score_raw": "score"},
        },
        "json_script_path_v1": {
            "script_id": "leaderboard-data",
            "script_type": None,
            "record_path_template": "$[0].results[{row_index}]",
            "fields": {"model_raw": "name", "score_raw": "resolved"},
            "assertions": [{"path": "$[0].name", "equals": "Verified"}],
        },
        "csv_cell_v1": {
            "fields": {"model_raw": "model", "score_raw": "score"},
        },
    }
    return {
        "schema": ADMISSION_POLICY_SCHEMA,
        "definition_hash": definition_hash or revision.definition_hash,
        "source_kind": "official_reported_result",
        "adapter": {
            "parser_name": source.parser_name,
            "parser_version": source.parser_version,
        },
        "approved_source_urls": [source.source_url],
        "approved_final_urls": [source.source_url],
        "locator_types": selected_locator_types,
        "evidence_contracts": evidence_contracts
        or {locator_type: contracts[locator_type] for locator_type in selected_locator_types},
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
        "numeric": numeric or {"lexeme": "decimal", "score_unit": None},
        "fetch": {"max_bytes": 5 * 1024 * 1024},
    }


def _certify(
    session,
    *,
    source: OfficialSource,
    revision: models.OfficialSourceRevision,
    policy: dict[str, object] | None = None,
    supersedes_decision_id: str | None = None,
) -> models.SourceRevisionDecision:  # type: ignore[no-untyped-def]
    if supersedes_decision_id is None:
        supersedes_decision_id = session.scalar(
            select(models.SourceRevisionDecision.id).where(
                models.SourceRevisionDecision.source_revision_id == revision.id
            )
        )
    assert supersedes_decision_id is not None
    decision = models.SourceRevisionDecision(
        source_revision_id=revision.id,
        outcome="certified",
        policy_version=ADMISSION_POLICY_SCHEMA,
        reason_code="fixture_certification",
        basis_json={"source_admission": policy or _policy(source, revision)},
        actor="test",
        supersedes_decision_id=supersedes_decision_id,
    )
    session.add(decision)
    session.flush()
    return decision


def _add_model(session, *, model_id: str, alias: str = MODEL_RAW) -> None:  # type: ignore[no-untyped-def]
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


def _claim(
    source: OfficialSource,
    decision: models.SourceRevisionDecision,
    *,
    model_raw: str = MODEL_RAW,
    score_raw: str = "001.2300",
    score_numeric: float | None = 1.23,
    score_unit: str | None = None,
    metric_raw: str | None = None,
    evidence_location: dict[str, object] | None = None,
) -> ResultClaimInput:
    return ResultClaimInput(
        source_revision_decision_id=UUID(decision.id),
        official_source_id=source.id,
        benchmark_id=source.benchmark_id,
        model_raw=model_raw,
        benchmark_raw=BENCHMARK_RAW,
        score_raw=score_raw,
        metric_raw=metric_raw,
        score_numeric=score_numeric,
        score_unit=score_unit,
        evidence_location=evidence_location
        or {
            "type": "json_path_v1",
            "record_path": "$.records[0]",
            "fields": {"model_raw": "model", "score_raw": "score"},
        },
        capture_method="certified_fixture_adapter",
        capture_confidence=1.0,
        capture_status="unreviewed",
        officialness_level=source.officialness_level,
    )


def _resolve_claim(session, *, source, admission, claim, raw_bytes=RAW_BYTES):  # type: ignore[no-untyped-def]
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
    )


def test_source_admission_requires_certification_policy_and_single_leaf(seeded_db):
    with get_session() as session:
        source, revision = _make_source(session, source_id="uncertified-source")
        denied = resolve_source_admission(session, source=source, source_revision=revision)
        assert denied.verdict.reason_code == "SRC_DECISION_NOT_CERTIFIED"

        bad_source, bad_revision = _make_source(session, source_id="bad-policy-source")
        _certify(
            session,
            source=bad_source,
            revision=bad_revision,
            policy=_policy(bad_source, bad_revision, definition_hash="not-the-revision-hash"),
        )
        bad = resolve_source_admission(session, source=bad_source, source_revision=bad_revision)
        assert bad.verdict.reason_code == "SRC_POLICY_INVALID"

        contract_source, contract_revision = _make_source(session, source_id="bad-evidence-contract-source")
        _certify(
            session,
            source=contract_source,
            revision=contract_revision,
            policy=_policy(
                contract_source,
                contract_revision,
                evidence_contracts={
                    "json_path_v1": {
                        "fields": {"model_raw": "model", "score_raw": "score"},
                    }
                },
            ),
        )
        contract_denied = resolve_source_admission(
            session, source=contract_source, source_revision=contract_revision
        )
        assert contract_denied.verdict.reason_code == "SRC_POLICY_INVALID"

        valid_source, valid_revision = _make_source(session, source_id="valid-policy-source")
        certified = _certify(session, source=valid_source, revision=valid_revision)
        admitted = resolve_source_admission(session, source=valid_source, source_revision=valid_revision)
        assert admitted.verdict == AdmissionVerdict("admit")
        assert admitted.source_revision_decision_id == certified.id

        # The database now prevents the ambiguous state at its write boundary;
        # the resolver therefore retains one deterministic certified leaf.
        with pytest.raises(IntegrityError, match="linear chain"):
            with session.begin_nested():
                _certify(
                    session,
                    source=valid_source,
                    revision=valid_revision,
                    supersedes_decision_id=session.scalar(
                        select(models.SourceRevisionDecision.id)
                        .where(
                            models.SourceRevisionDecision.source_revision_id
                            == valid_revision.id
                        )
                        .where(models.SourceRevisionDecision.id != certified.id)
                    ),
                )
        still_admitted = resolve_source_admission(
            session, source=valid_source, source_revision=valid_revision
        )
        assert still_admitted.source_revision_decision_id == certified.id


def test_fetch_admission_rejects_nonverbatim_mock_and_unapproved_redirect(seeded_db):
    with get_session() as session:
        source, revision = _make_source(session)
        _certify(session, source=source, revision=revision)
        admission = resolve_source_admission(session, source=source, source_revision=revision)
        snapshot = SourceSnapshotInput(official_source_id=source.id, raw_bytes=RAW_BYTES)

        mock = resolve_fetch_admission(
            source_admission=admission,
            source=source,
            fetch_result=SourceFetchResult(
                raw_bytes=RAW_BYTES,
                http_status=200,
                final_url=source.source_url,
                metadata={"verbatim": True, "artifact_count": 1, "mock_used": True},
            ),
            snapshot_input=snapshot,
        )
        assert mock.reason_code == "FETCH_FALLBACK_OR_MOCK"

        nonverbatim = resolve_fetch_admission(
            source_admission=admission,
            source=source,
            fetch_result=SourceFetchResult(
                raw_bytes=RAW_BYTES,
                http_status=200,
                final_url=source.source_url,
                metadata={"verbatim": False, "artifact_count": 1},
            ),
            snapshot_input=snapshot,
        )
        assert nonverbatim.reason_code == "FETCH_NON_VERBATIM_OR_MULTI_ARTIFACT"

        redirect = resolve_fetch_admission(
            source_admission=admission,
            source=source,
            fetch_result=SourceFetchResult(
                raw_bytes=RAW_BYTES,
                http_status=200,
                final_url="https://unapproved.example/redirect.json",
                metadata={"verbatim": True, "artifact_count": 1},
            ),
            snapshot_input=snapshot,
        )
        assert redirect.reason_code == "FETCH_FINAL_URL_NOT_APPROVED"

        altered_snapshot = resolve_fetch_admission(
            source_admission=admission,
            source=source,
            fetch_result=SourceFetchResult(
                raw_bytes=RAW_BYTES,
                http_status=200,
                final_url=source.source_url,
                metadata={"verbatim": True, "artifact_count": 1},
            ),
            snapshot_input=SourceSnapshotInput(
                official_source_id=source.id,
                raw_bytes=b'{"records":[]}',
            ),
        )
        assert altered_snapshot.reason_code == "FETCH_SNAPSHOT_NOT_VERBATIM"

        altered_metadata = resolve_fetch_admission(
            source_admission=admission,
            source=source,
            fetch_result=SourceFetchResult(
                raw_bytes=RAW_BYTES,
                http_status=200,
                final_url=source.source_url,
                metadata={"verbatim": True, "artifact_count": 1},
            ),
            snapshot_input=SourceSnapshotInput(
                official_source_id=source.id,
                raw_bytes=RAW_BYTES,
                http_status=200,
                fetch_metadata={
                    "final_url": "https://tampered.example/result.json",
                    "verbatim": True,
                    "artifact_count": 1,
                },
            ),
        )
        assert altered_metadata.reason_code == "FETCH_SNAPSHOT_METADATA_MISMATCH"


def test_fetch_admission_enforces_the_source_revision_byte_limit(seeded_db):
    raw_bytes = b"1234"
    with get_session() as session:
        source, revision = _make_source(session, source_id="bounded-fetch-source")
        policy = _policy(source, revision)
        policy["fetch"] = {"max_bytes": 3}
        _certify(session, source=source, revision=revision, policy=policy)
        admission = resolve_source_admission(session, source=source, source_revision=revision)

        verdict = resolve_fetch_admission(
            source_admission=admission,
            source=source,
            fetch_result=SourceFetchResult(
                raw_bytes=raw_bytes,
                http_status=200,
                final_url=source.source_url,
                metadata={"verbatim": True, "artifact_count": 1},
            ),
            snapshot_input=SourceSnapshotInput(official_source_id=source.id, raw_bytes=raw_bytes),
        )

        assert verdict.reason_code == "FETCH_BODY_TOO_LARGE"


def test_claim_admission_requires_exact_raw_record_and_preserves_lexemes(seeded_db):
    with get_session() as session:
        source, revision = _make_source(session)
        decision = _certify(session, source=source, revision=revision)
        admission = resolve_source_admission(session, source=source, source_revision=revision)
        _add_model(session, model_id="admission-model")

        claim = _claim(source, decision)
        before = (claim.model_raw, claim.benchmark_raw, claim.score_raw, claim.metric_raw)
        result = _resolve_claim(session, source=source, admission=admission, claim=claim)
        assert result.verdict.disposition == "admit"
        assert result.score_numeric == 1.23
        assert (claim.model_raw, claim.benchmark_raw, claim.score_raw, claim.metric_raw) == before

        mismatched = _claim(source, decision, score_raw="1.2300", score_numeric=1.23)
        assert (
            _resolve_claim(session, source=source, admission=admission, claim=mismatched).verdict.reason_code
            == "EVIDENCE_VALUE_MISMATCH"
        )

        missing = _claim(
            source,
            decision,
            evidence_location={
                "type": "json_path_v1",
                "record_path": "$.records[9]",
                "fields": {"model_raw": "model", "score_raw": "score"},
            },
        )
        assert (
            _resolve_claim(session, source=source, admission=admission, claim=missing).verdict.reason_code
            == "EVIDENCE_NOT_FOUND"
        )

        dimension = _claim(source, decision, metric_raw="accuracy")
        assert (
            _resolve_claim(session, source=source, admission=admission, claim=dimension).verdict.reason_code
            == "DIMENSION_VALUE_MISMATCH"
        )

        # Equality is lexical, not numeric or whitespace-normalized: the raw
        # source cell below is deliberately distinct from the claim's value.
        whitespace_bytes = (
            b'{"records":[{"model":"Admission Fixture Model","score":"001.2300 "}]}'
        )
        whitespace = _claim(source, decision)
        assert (
            _resolve_claim(
                session,
                source=source,
                admission=admission,
                claim=whitespace,
                raw_bytes=whitespace_bytes,
            ).verdict.reason_code
            == "EVIDENCE_VALUE_MISMATCH"
        )


def test_json_evidence_rejects_nonverbatim_types_and_ambiguous_json(seeded_db):
    with get_session() as session:
        source, revision = _make_source(session, source_id="unsafe-json-evidence-source")
        decision = _certify(session, source=source, revision=revision)
        admission = resolve_source_admission(session, source=source, source_revision=revision)
        _add_model(session, model_id="admission-model")

        cases = [
            (
                b'{"records":[{"model":7,"score":1.2300}]}',
                _claim(source, decision, model_raw="7", score_raw="1.2300", score_numeric=None),
                "EVIDENCE_VALUE_NOT_VERBATIM",
            ),
            (
                b'{"records":[{"model":"Admission Fixture Model","score":true}]}',
                _claim(source, decision, score_raw="true", score_numeric=None),
                "EVIDENCE_VALUE_NOT_VERBATIM",
            ),
            (
                b'{"records":[{"model":"Admission Fixture Model","score":null}]}',
                _claim(source, decision, score_raw="null", score_numeric=None),
                "EVIDENCE_VALUE_NOT_VERBATIM",
            ),
            (
                b'{"records":[{"model":"Admission Fixture Model","score":{"value":1}}]}',
                _claim(source, decision, score_raw="1", score_numeric=None),
                "EVIDENCE_VALUE_NOT_VERBATIM",
            ),
            (
                b'{"records":[{"model":"Admission Fixture Model","score":[1]}]}',
                _claim(source, decision, score_raw="1", score_numeric=None),
                "EVIDENCE_VALUE_NOT_VERBATIM",
            ),
            (
                b'{"records":[{"model":"Admission Fixture Model","score":NaN}]}',
                _claim(source, decision, score_raw="NaN", score_numeric=None),
                "EVIDENCE_LOCATOR_INVALID",
            ),
            (
                b'{"records":[{"model":"Admission Fixture Model","score":Infinity}]}',
                _claim(source, decision, score_raw="Infinity", score_numeric=None),
                "EVIDENCE_LOCATOR_INVALID",
            ),
            (
                b'{"records":[{"model":"Admission Fixture Model","score":1,"score":2}]}',
                _claim(source, decision, score_raw="1", score_numeric=None),
                "EVIDENCE_LOCATOR_INVALID",
            ),
        ]
        for raw_bytes, claim, expected_reason in cases:
            assert (
                _resolve_claim(
                    session,
                    source=source,
                    admission=admission,
                    claim=claim,
                    raw_bytes=raw_bytes,
                ).verdict.reason_code
                == expected_reason
            )


def test_claim_admission_binds_each_locator_to_its_revision_contract(seeded_db):
    with get_session() as session:
        source, revision = _make_source(session, source_id="locator-contract-source")
        decision = _certify(session, source=source, revision=revision)
        admission = resolve_source_admission(session, source=source, source_revision=revision)
        _add_model(session, model_id="admission-model")

        locators = [
            {
                "type": "json_path_v1",
                "record_path": "$.other[0]",
                "fields": {"model_raw": "model", "score_raw": "score"},
            },
            {
                "type": "json_path_v1",
                "record_path": "$.records[00]",
                "fields": {"model_raw": "model", "score_raw": "score"},
            },
            {
                "type": "json_path_v1",
                "record_path": "$.records[0]",
                "fields": {"model_raw": "score", "score_raw": "model"},
            },
        ]
        for locator in locators:
            claim = _claim(source, decision, evidence_location=locator)
            assert (
                _resolve_claim(session, source=source, admission=admission, claim=claim).verdict.reason_code
                == "EVIDENCE_LOCATOR_CONTRACT_MISMATCH"
            )


def test_claim_admission_rejects_numeric_underflow_instead_of_coercing_to_zero(seeded_db):
    raw_bytes = b'{"records":[{"model":"Admission Fixture Model","score":1e-10000}]}'
    with get_session() as session:
        source, revision = _make_source(session, source_id="underflow-source")
        decision = _certify(session, source=source, revision=revision)
        admission = resolve_source_admission(session, source=source, source_revision=revision)
        _add_model(session, model_id="admission-model")
        claim = _claim(source, decision, score_raw="1e-10000", score_numeric=None)

        assert (
            _resolve_claim(
                session,
                source=source,
                admission=admission,
                claim=claim,
                raw_bytes=raw_bytes,
            ).verdict.reason_code
            == "SCORE_NOT_REPRESENTABLE"
        )


@pytest.mark.parametrize(
    ("score_raw", "score_numeric"),
    [
        ("1.2300", 1.23),
        ("1e-3", 0.001),
        ("-0", -0.0),
        ("1E+02", 100.0),
    ],
)
def test_json_path_evidence_preserves_numeric_json_lexemes(seeded_db, score_raw, score_numeric):
    raw_bytes = (
        b'{"records":[{"model":"Admission Fixture Model","score":' + score_raw.encode("ascii") + b"}]}"
    )
    with get_session() as session:
        source, revision = _make_source(session)
        decision = _certify(session, source=source, revision=revision)
        admission = resolve_source_admission(session, source=source, source_revision=revision)
        _add_model(session, model_id="admission-model")

        claim = _claim(source, decision, score_raw=score_raw, score_numeric=score_numeric)
        result = _resolve_claim(
            session,
            source=source,
            admission=admission,
            claim=claim,
            raw_bytes=raw_bytes,
        )

        assert result.verdict == AdmissionVerdict("admit")
        assert claim.score_raw == score_raw
        assert result.score_numeric == score_numeric


def test_json_script_path_evidence_re_resolves_exact_embedded_record(seeded_db):
    raw_bytes = b"""<html><body>
<script id="leaderboard-data">[{"name":"Verified","results":[{"name":"Admission Fixture Model","resolved":1.2300}]}]</script>
</body></html>"""
    locator = {
        "type": "json_script_path_v1",
        "script_id": "leaderboard-data",
        "script_type": None,
        "record_path": "$[0].results[0]",
        "fields": {"model_raw": "name", "score_raw": "resolved"},
        "assertions": [{"path": "$[0].name", "equals": "Verified"}],
    }
    with get_session() as session:
        source, revision = _make_source(session, source_id="script-evidence-source")
        decision = _certify(
            session,
            source=source,
            revision=revision,
            policy=_policy(source, revision, locator_types=["json_script_path_v1"]),
        )
        admission = resolve_source_admission(session, source=source, source_revision=revision)
        _add_model(session, model_id="admission-model")
        claim = _claim(
            source,
            decision,
            score_raw="1.2300",
            score_numeric=1.23,
            evidence_location=locator,
        )

        result = _resolve_claim(
            session,
            source=source,
            admission=admission,
            claim=claim,
            raw_bytes=raw_bytes,
        )

        assert result.verdict == AdmissionVerdict("admit")
        assert result.score_numeric == 1.23


@pytest.mark.parametrize(
    ("raw_bytes", "expected_reason"),
    [
        (
            b'<html><body><script id="other">[]</script></body></html>',
            "EVIDENCE_NOT_FOUND",
        ),
        (
            b'<script id="leaderboard-data">[]</script><script id="leaderboard-data">[]</script>',
            "EVIDENCE_SCRIPT_AMBIGUOUS",
        ),
        (
            b'<div id="leaderboard-data"></div><script id="leaderboard-data">[]</script>',
            "EVIDENCE_SCRIPT_AMBIGUOUS",
        ),
        (
            b'<script id="leaderboard-data">not-json</script>',
            "EVIDENCE_LOCATOR_INVALID",
        ),
        (
            b'<script id="leaderboard-data" src="/leaderboard.json">[]</script>',
            "EVIDENCE_LOCATOR_INVALID",
        ),
        (
            b'<script id="leaderboard-data" type="application/json">[]</script>',
            "EVIDENCE_LOCATOR_INVALID",
        ),
        (
            b'<script id="leaderboard-data">[{"name":"Community","results":[]}]</script>',
            "EVIDENCE_ASSERTION_FAILED",
        ),
        (
            b'<script id="leaderboard-data">[{"name":"Verified","name":"Community","results":[]}]</script>',
            "EVIDENCE_LOCATOR_INVALID",
        ),
    ],
)
def test_json_script_path_evidence_fails_closed_for_invalid_script_locations(
    seeded_db, raw_bytes, expected_reason
):
    locator = {
        "type": "json_script_path_v1",
        "script_id": "leaderboard-data",
        "script_type": None,
        "record_path": "$[0].results[0]",
        "fields": {"model_raw": "name", "score_raw": "resolved"},
        "assertions": [{"path": "$[0].name", "equals": "Verified"}],
    }
    with get_session() as session:
        source, revision = _make_source(session, source_id=f"script-{expected_reason.lower()}")
        decision = _certify(
            session,
            source=source,
            revision=revision,
            policy=_policy(source, revision, locator_types=["json_script_path_v1"]),
        )
        admission = resolve_source_admission(session, source=source, source_revision=revision)
        _add_model(session, model_id="admission-model")
        claim = _claim(
            source,
            decision,
            score_raw="1.2300",
            score_numeric=1.23,
            evidence_location=locator,
        )

        result = _resolve_claim(
            session,
            source=source,
            admission=admission,
            claim=claim,
            raw_bytes=raw_bytes,
        )

        assert result.verdict.reason_code == expected_reason


@pytest.mark.parametrize(
    ("score_raw", "expected"),
    [
        ("12widgets", "SCORE_NOT_NUMERIC"),
        ("NaN", "SCORE_NOT_NUMERIC"),
        ("1e10000", "SCORE_NOT_FINITE"),
        ("12%", "SCORE_UNIT_UNDECLARED"),
    ],
)
def test_claim_admission_rejects_nonpublishable_numeric_lexemes(seeded_db, score_raw, expected):
    raw_bytes = json.dumps({"records": [{"model": MODEL_RAW, "score": score_raw}]}).encode("utf-8")
    with get_session() as session:
        source, revision = _make_source(session)
        decision = _certify(session, source=source, revision=revision)
        admission = resolve_source_admission(session, source=source, source_revision=revision)
        _add_model(session, model_id="admission-model")
        claim = _claim(source, decision, score_raw=score_raw, score_numeric=None)
        assert (
            _resolve_claim(
                session,
                source=source,
                admission=admission,
                claim=claim,
                raw_bytes=raw_bytes,
            ).verdict.reason_code
            == expected
        )


def test_ambiguous_model_identity_is_quarantined_without_a_guess(seeded_db):
    with get_session() as session:
        source, revision = _make_source(session)
        decision = _certify(session, source=source, revision=revision)
        admission = resolve_source_admission(session, source=source, source_revision=revision)
        _add_model(session, model_id="admission-model-a")
        _add_model(session, model_id="admission-model-b")

        claim = _claim(source, decision)
        resolution = resolve_model_entity(session, claim.model_raw)
        assert resolution.status == "ambiguous"
        assert resolution.entity_id is None
        result = _resolve_claim(session, source=source, admission=admission, claim=claim)
        assert result.verdict.disposition == "quarantine"
        assert result.verdict.reason_code == "MODEL_AMBIGUOUS"
        assert claim.model_entity_id is None
        assert claim.model_raw == MODEL_RAW


def test_claim_schema_does_not_coerce_raw_source_values():
    with pytest.raises(ValidationError):
        ResultClaimInput(
            official_source_id="source",
            model_raw=123,
            benchmark_raw="benchmark",
            score_raw="1.0",
            evidence_location={},
            capture_method="test",
        )


class CertifiedFixtureAdapter(SourceAdapter):
    source_type = "api"

    def __init__(self, *, claim_score_raw: str = "001.2300", raw_bytes: bytes = RAW_BYTES) -> None:
        self.claim_score_raw = claim_score_raw
        self.raw_bytes = raw_bytes

    def fetch(self, source: OfficialSource) -> SourceFetchResult:
        return SourceFetchResult(
            raw_bytes=self.raw_bytes,
            content_type="application/json",
            http_status=200,
            final_url=source.source_url,
            metadata={"verbatim": True, "artifact_count": 1},
        )

    def extract_claims(self, source, snapshot, raw_bytes):  # type: ignore[no-untyped-def]
        return [
            ResultClaimInput(
                official_source_id=source.id,
                source_snapshot_id=snapshot.id,
                benchmark_id=source.benchmark_id,
                model_raw=MODEL_RAW,
                benchmark_raw=BENCHMARK_RAW,
                score_raw=self.claim_score_raw,
                score_numeric=1.23,
                evidence_location={
                    "type": "json_path_v1",
                    "record_path": "$.records[0]",
                    "fields": {"model_raw": "model", "score_raw": "score"},
                },
                capture_method="certified_fixture_adapter",
                capture_confidence=1.0,
                capture_status="parser_verified",
                officialness_level=source.officialness_level,
            )
        ]

    def validate_claim(self, claim, raw_bytes):  # type: ignore[no-untyped-def]
        return [
            ClaimValidationInput(
                validation_type="fixture_exact_record",
                outcome="pass",
                validator="CertifiedFixtureAdapter",
            )
        ]


class _CertifiedFixtureTransport:
    def __init__(self, raw_bytes: bytes = RAW_BYTES) -> None:
        self.raw_bytes = raw_bytes

    def request(self, *, url: str, headers, timeout_seconds: float) -> FetchTransportResponse:  # type: ignore[no-untyped-def]
        _ = headers, timeout_seconds
        return FetchTransportResponse(
            url=url,
            status_code=200,
            headers={"content-type": "application/json"},
            body=self.raw_bytes,
        )


class _CertifiedFixtureRateLimiter:
    def acquire(self, *, source_id: str, url: str, observed_at: datetime) -> None:
        _ = source_id, url, observed_at


def _certified_fixture_dependencies(raw_bytes: bytes = RAW_BYTES):  # type: ignore[no-untyped-def]
    return replace(
        contained_runtime_dependencies(),
        fetch_transport=_CertifiedFixtureTransport(raw_bytes),
        resolver=lambda _host, _port: ["8.8.8.8"],
        rate_limiter=_CertifiedFixtureRateLimiter(),
        capabilities=frozenset({RuntimeCapability.NETWORK_FETCH}),
    )


def test_runner_refuses_uncertified_revision_before_fetch_or_write(seeded_db, monkeypatch):
    with get_session() as session:
        source, _revision = _make_source(session, source_id="runner-uncertified-source")
        monkeypatch.setattr(
            ingestion_runner,
            "get_adapter",
            lambda *_args, **_kwargs: pytest.fail("uncertified source must not be fetched"),
        )
        with pytest.raises(IngestionBlockedError, match="No production-eligible source"):
            run_ingestion(session, source_id=source.id)
        assert session.scalar(select(func.count()).select_from(models.IngestionRun)) == 0
        assert session.scalar(select(func.count()).select_from(models.SourceSnapshot)) == 0
        assert session.scalar(select(func.count()).select_from(models.ResultClaim)) == 0


def test_runner_refuses_first_rows_preview_before_adapter_fetch_or_snapshot_write(seeded_db, monkeypatch):
    with get_session() as session:
        source, _revision = _make_source(
            session,
            source_id="runner-preview-source",
            source_url="https://datasets-server.huggingface.co/first-rows?dataset=owner/results",
        )
        monkeypatch.setattr(
            ingestion_runner,
            "get_adapter",
            lambda *_args, **_kwargs: pytest.fail("preview source must not reach an adapter"),
        )

        with pytest.raises(IngestionBlockedError, match="No production-eligible source"):
            run_ingestion(session, source_id=source.id)

        assert session.scalar(select(func.count()).select_from(models.IngestionRun)) == 0
        assert session.scalar(select(func.count()).select_from(models.SourceSnapshot)) == 0
        assert session.scalar(select(func.count()).select_from(models.ResultClaim)) == 0


def test_runner_records_exact_admission_and_rejects_mismatched_candidate(seeded_db, monkeypatch):
    with get_session() as session:
        source, revision = _make_source(session, source_id="runner-certified-source")
        decision = _certify(session, source=source, revision=revision)
        _add_model(session, model_id="runner-admission-model")
        monkeypatch.setattr(
            ingestion_runner,
            "get_adapter",
            lambda *_args, **_kwargs: CertifiedFixtureAdapter(),
        )

        summary = run_ingestion(
            session,
            source_id=source.id,
            dependencies=_certified_fixture_dependencies(),
        )
        assert summary.status == "completed"
        assert summary.claims_inserted == 1
        claim = session.scalar(select(models.ResultClaim))
        assert claim is not None
        assert claim.source_revision_decision_id == decision.id
        assert claim.score_raw == "001.2300"
        assert claim.capture_status == "parser_verified"
        validation_types = set(
            session.scalars(
                select(models.ClaimValidation.validation_type).where(
                    models.ClaimValidation.result_claim_id == claim.id
                )
            )
        )
        assert {"fixture_exact_record", "central_claim_admission"}.issubset(validation_types)

    # A fresh source makes its mismatch receipt unambiguous in the run table.
    with get_session() as session:
        source, revision = _make_source(session, source_id="runner-rejected-source")
        _certify(session, source=source, revision=revision)
        _add_model(session, model_id="runner-rejection-model")
        monkeypatch.setattr(
            ingestion_runner,
            "get_adapter",
            lambda *_args, **_kwargs: CertifiedFixtureAdapter(claim_score_raw="1.2300"),
        )

        rejected = run_ingestion(
            session,
            source_id=source.id,
            dependencies=_certified_fixture_dependencies(),
        )
        assert rejected.status == "partial"
        assert rejected.claims_extracted == 1
        assert rejected.claims_inserted == 0
        assert rejected.claims_rejected == 1
        assert rejected.claim_rejections[0]["reason_code"] == "EVIDENCE_VALUE_MISMATCH"
        run = session.scalar(
            select(models.IngestionRun).where(models.IngestionRun.official_source_id == source.id)
        )
        assert run is not None
        assert run.status == "partial"
        assert run.metadata_json["claim_rejections"][0]["reason_code"] == "EVIDENCE_VALUE_MISMATCH"


def _direct_candidate(
    source: OfficialSource,
    decision: models.SourceRevisionDecision,
    snapshot: models.SourceSnapshot,
    *,
    model_raw: str,
) -> ResultClaimInput:
    candidate = _claim(source, decision, model_raw=model_raw)
    candidate.source_snapshot_id = UUID(snapshot.id)
    candidate.claim_fingerprint = compute_claim_fingerprint(candidate)
    return candidate


def test_database_trigger_rejects_direct_unbound_or_uncertified_claim_insert(seeded_db, monkeypatch):
    with get_session() as session:
        source, revision = _make_source(session, source_id="trigger-certified-source")
        decision = _certify(session, source=source, revision=revision)
        _add_model(session, model_id="trigger-admission-model")
        monkeypatch.setattr(
            ingestion_runner,
            "get_adapter",
            lambda *_args, **_kwargs: CertifiedFixtureAdapter(),
        )
        run_ingestion(
            session,
            source_id=source.id,
            dependencies=_certified_fixture_dependencies(),
        )
        snapshot = session.scalar(
            select(models.SourceSnapshot).where(models.SourceSnapshot.official_source_id == source.id)
        )
        assert snapshot is not None

        unbound = _direct_candidate(source, decision, snapshot, model_raw="Direct bypass model")
        unbound.source_revision_decision_id = None
        unbound.claim_fingerprint = compute_claim_fingerprint(unbound)
        with pytest.raises(IntegrityError, match="require.*source decision"):
            with session.begin_nested():
                repo.insert_claim_if_new(session, unbound)

        quarantined_source, quarantined_revision = _make_source(
            session, source_id="trigger-quarantined-source"
        )
        quarantined_decision = session.scalar(
            select(models.SourceRevisionDecision).where(
                models.SourceRevisionDecision.source_revision_id == quarantined_revision.id
            )
        )
        assert quarantined_decision is not None
        quarantined_snapshot = repo.insert_snapshot(
            session,
            official_source_id=quarantined_source.id,
            source_revision_id=quarantined_revision.id,
            raw_content_uri="file:///test-only/quarantined.json",
            content_hash="a" * 64,
            content_type="application/json",
            http_status=200,
            etag=None,
            last_modified_header=None,
            fetch_metadata={},
        )
        uncertified = _direct_candidate(
            quarantined_source,
            quarantined_decision,
            quarantined_snapshot,
            model_raw="Quarantined direct bypass model",
        )
        with pytest.raises(IntegrityError, match="current effective certified"):
            with session.begin_nested():
                repo.insert_claim_if_new(session, uncertified)


def test_database_trigger_rejects_stale_and_prevents_ambiguous_effective_decisions(
    seeded_db,
):
    with get_session() as session:
        ambiguous_source, ambiguous_revision = _make_source(
            session, source_id="trigger-ambiguous-source"
        )
        ambiguous_decision = _certify(
            session, source=ambiguous_source, revision=ambiguous_revision
        )
        # A second child of the original root would make policy ambiguous, so
        # the append-only database boundary rejects the branch itself.
        original_decision = session.scalar(
            select(models.SourceRevisionDecision).where(
                models.SourceRevisionDecision.source_revision_id == ambiguous_revision.id,
                models.SourceRevisionDecision.id != ambiguous_decision.id,
            )
        )
        assert original_decision is not None
        with pytest.raises(IntegrityError, match="linear chain"):
            with session.begin_nested():
                _certify(
                    session,
                    source=ambiguous_source,
                    revision=ambiguous_revision,
                    supersedes_decision_id=original_decision.id,
                )
        assert (
            resolve_source_admission(
                session,
                source=ambiguous_source,
                source_revision=ambiguous_revision,
            ).source_revision_decision_id
            == ambiguous_decision.id
        )

        stale_source, stale_revision = _make_source(session, source_id="trigger-stale-source")
        stale_decision = _certify(session, source=stale_source, revision=stale_revision)
        stale_snapshot = repo.insert_snapshot(
            session,
            official_source_id=stale_source.id,
            source_revision_id=stale_revision.id,
            raw_content_uri="file:///test-only/stale.json",
            content_hash="c" * 64,
            content_type="application/json",
            http_status=200,
            etag=None,
            last_modified_header=None,
            fetch_metadata={},
        )
        # Move the source projection through a normal append-only successor.
        # The old snapshot/decision remain retained evidence, but they cannot
        # be used to create a new claim after the revision is no longer current.
        repo.reconcile_official_source(
            session,
            {
                "id": stale_source.id,
                "benchmark_id": stale_source.benchmark_id,
                "source_name": stale_source.source_name,
                "source_url": stale_source.source_url,
                "source_type": stale_source.source_type,
                "officialness_level": stale_source.officialness_level,
                "machine_readable": stale_source.machine_readable,
                "requires_auth": stale_source.requires_auth,
                "supports_history": stale_source.supports_history,
                "update_cadence": stale_source.update_cadence,
                "parser_name": stale_source.parser_name,
                "parser_version": stale_source.parser_version,
                "parser_config": {"governance": _governance(), "fixture_revision": "two"},
                "status": stale_source.status,
                "notes": stale_source.notes,
            },
        )
        stale = _direct_candidate(
            stale_source,
            stale_decision,
            stale_snapshot,
            model_raw="Stale direct bypass model",
        )
        with pytest.raises(IntegrityError, match="current effective certified"):
            with session.begin_nested():
                repo.insert_claim_if_new(session, stale)
