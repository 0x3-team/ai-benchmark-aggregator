from __future__ import annotations

import builtins
import json
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import func, select

from app.db import models, repositories as repo
from app.db.engine import get_session
from app.ingestion import runner as ingestion_runner
from app.ingestion.adapters import taubench_s3 as taubench_module
from app.ingestion.adapters.taubench_s3 import TauBenchS3Adapter
from app.ingestion.extractors.normalize import compute_claim_fingerprint
from app.ingestion.runner import IngestionBlockedError, run_ingestion
from app.schemas.boundary import OfficialSource, ResultClaimInput


RAW = json.dumps(
    {
        "model": "model-a",
        "results": {
            "domain-a": {"pass_1": 80, "pass_2": 60},
            "domain-b": {"pass_1": 90},
        },
    }
).encode("utf-8")


def _count(session, model) -> int:  # type: ignore[no-untyped-def]
    return session.scalar(select(func.count()).select_from(model)) or 0


def _source(*, status: str, notes: str | None, parser_config: dict[str, object]) -> dict[str, object]:
    return {
        "id": "taubench-transition-fixture",
        "benchmark_id": "tau_bench",
        "source_name": "TauBench transition fixture",
        "source_url": "https://example.invalid/taubench",
        "source_type": "taubench_s3",
        "officialness_level": "O1",
        "machine_readable": True,
        "requires_auth": False,
        "supports_history": False,
        "update_cadence": "monthly",
        "parser_name": "taubench_s3",
        "parser_config": parser_config,
        "status": status,
        "notes": notes,
    }


def _fixture_source(*, mode: str | None = None) -> OfficialSource:
    parser_config = {} if mode is None else {"mode": mode}
    return OfficialSource(
        id="taubench-fixture",
        source_name="TauBench fixture",
        source_url="https://example.invalid/taubench",
        source_type="taubench_s3",
        officialness_level="O1",
        benchmark_id="tau_bench",
        parser_name="taubench_s3",
        parser_config=parser_config,
    )


def test_taubench_derived_fixture_is_non_certifying_and_fetch_is_retired(seeded_db, monkeypatch):
    snapshot = models.SourceSnapshot(
        id="77777777-7777-7777-7777-777777777777",
        official_source_id="taubench-fixture",
        raw_content_uri="mem",
        content_hash="fixture",
    )
    adapter = TauBenchS3Adapter()
    with get_session() as session:
        before = {
            "runs": _count(session, models.IngestionRun),
            "snapshots": _count(session, models.SourceSnapshot),
            "claims": _count(session, models.ResultClaim),
        }
    claims = adapter.extract_claims(_fixture_source(), snapshot, RAW)

    assert len(claims) == 1
    assert claims[0].model_raw == "model-a"
    assert claims[0].score_raw == "76.6667"
    assert claims[0].evidence_location["type"] == "derived_analytics"
    assert claims[0].capture_status == "unreviewed"
    assert claims[0].capture_confidence == 0.0
    assert adapter.validate_claim(claims[0], RAW)[0].outcome == "fail"
    assert adapter.extract_claims(_fixture_source(mode="retired"), snapshot, RAW) == []
    with get_session() as session:
        assert {
            "runs": _count(session, models.IngestionRun),
            "snapshots": _count(session, models.SourceSnapshot),
            "claims": _count(session, models.ResultClaim),
        } == before

    assert "sierra-tau-bench-public" not in Path(taubench_module.__file__).read_text(encoding="utf-8")
    original_import = builtins.__import__

    def deny_network_dependencies(name, *args, **kwargs):  # type: ignore[no-untyped-def]
        if name in {"httpx", "app.config"}:
            pytest.fail(f"retired TauBench fetch imported {name}")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", deny_network_dependencies)
    with pytest.raises(RuntimeError, match="adapter is retired"):
        adapter.fetch(_fixture_source(mode="retired"))


def test_retiring_taubench_appends_a_revision_and_preserves_historical_evidence(seeded_db):
    active = _source(status="active", notes=None, parser_config={})
    retired = _source(
        status="inactive",
        notes="Retired LDR-06: aggregated submission metrics are not official result evidence.",
        parser_config={
            "mode": "retired",
            "retirement_reason": "aggregated submission metrics are not Official claim evidence",
        },
    )
    with get_session() as session:
        initial = repo.reconcile_official_source(session, active, registry_managed=True)
        snapshot = repo.insert_snapshot(
            session,
            official_source_id=initial.source.id,
            source_revision_id=initial.revision.id,
            raw_content_uri="file:///test-only/taubench.json",
            content_hash="a" * 64,
            content_type="application/x-ndjson",
            http_status=200,
            etag=None,
            last_modified_header=None,
            fetch_metadata={"fixture": True},
        )
        initial_decision = session.scalar(
            select(models.SourceRevisionDecision).where(
                models.SourceRevisionDecision.source_revision_id == initial.revision.id
            )
        )
        assert initial_decision is not None
        # Retirement retains a historical derived record for LDR-09 reporting;
        # it never deletes or rewrites raw evidence.
        historical_decision = models.SourceRevisionDecision(
            source_revision_id=initial.revision.id,
            outcome="certified",
            policy_version="test-historical-claim-v1",
            reason_code="test_historical_claim",
            basis_json={"fixture": True},
            actor="pytest",
            supersedes_decision_id=initial_decision.id,
        )
        session.add(historical_decision)
        session.flush()
        historical_claim = ResultClaimInput(
            source_snapshot_id=UUID(snapshot.id),
            source_revision_decision_id=UUID(historical_decision.id),
            official_source_id=initial.source.id,
            benchmark_id=initial.source.benchmark_id,
            model_raw="model-a",
            benchmark_raw="tau_bench",
            score_raw="76.6667",
            evidence_location={"type": "derived_analytics", "record_path": "$.results"},
            capture_method="legacy_taubench_derived",
            capture_confidence=0.9,
            capture_status="parser_verified",
            officialness_level=initial.source.officialness_level,
        )
        historical_claim.claim_fingerprint = compute_claim_fingerprint(historical_claim)
        claim_row, inserted = repo.insert_claim_if_new(session, historical_claim)
        assert inserted is True

        result = repo.reconcile_official_source(session, retired, registry_managed=True)
        decision = session.scalar(
            select(models.SourceRevisionDecision).where(
                models.SourceRevisionDecision.source_revision_id == result.revision.id
            )
        )

        assert result.disposition == "revised"
        assert result.revision.revision_ordinal == initial.revision.revision_ordinal + 1
        assert result.revision.supersedes_revision_id == initial.revision.id
        assert result.source.current_revision_id == result.revision.id
        assert result.source.status == "inactive"
        assert result.revision.status == "inactive"
        assert result.revision.parser_config["mode"] == "retired"
        assert snapshot.source_revision_id == initial.revision.id
        preserved_claim = session.get(models.ResultClaim, claim_row.id)
        assert preserved_claim is not None
        assert (
            preserved_claim.source_snapshot_id,
            preserved_claim.model_raw,
            preserved_claim.score_raw,
            preserved_claim.capture_method,
            preserved_claim.capture_confidence,
            preserved_claim.capture_status,
            preserved_claim.evidence_location,
        ) == (
            snapshot.id,
            "model-a",
            "76.6667",
            "legacy_taubench_derived",
            0.9,
            "parser_verified",
            {"type": "derived_analytics", "record_path": "$.results"},
        )
        assert decision is not None
        assert (decision.outcome, decision.reason_code) == ("quarantined", "registry_definition_changed")


def test_retired_taubench_source_never_dispatches_or_writes(seeded_db, monkeypatch):
    with get_session() as session:
        before = {
            "runs": _count(session, models.IngestionRun),
            "snapshots": _count(session, models.SourceSnapshot),
            "claims": _count(session, models.ResultClaim),
        }
        monkeypatch.setattr(
            ingestion_runner,
            "get_adapter",
            lambda *_args, **_kwargs: pytest.fail("inactive TauBench route must not dispatch an adapter"),
        )

        with pytest.raises(IngestionBlockedError, match="No production-eligible source"):
            run_ingestion(session, source_id="tau_bench_s3", dry_run=True)

        assert {
            "runs": _count(session, models.IngestionRun),
            "snapshots": _count(session, models.SourceSnapshot),
            "claims": _count(session, models.ResultClaim),
        } == before
