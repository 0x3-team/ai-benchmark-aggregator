from __future__ import annotations

from pathlib import Path

from sqlalchemy import func, select
from typer.testing import CliRunner

from app.cli import app
from app.config import get_settings
from app.db import models, repositories as repo
from app.db.engine import get_session
from app.ingestion.admission import AdmissionVerdict, ClaimAdmission, SourceAdmission
from app.ingestion import runner as ingestion_runner
from app.ingestion.adapters.base import SourceAdapter
from app.ingestion.runner import run_ingestion
from app.schemas.boundary import ClaimValidationInput, ResultClaimInput, SourceFetchResult


FIXTURE = Path(__file__).parent / "fixtures" / "fake_source.json"
cli_runner = CliRunner()


def _count(session, model) -> int:
    return session.scalar(select(func.count()).select_from(model)) or 0


def _evidence_counts(session) -> dict[str, int]:
    return {
        "runs": _count(session, models.IngestionRun),
        "snapshots": _count(session, models.SourceSnapshot),
        "claims": _count(session, models.ResultClaim),
        "validations": _count(session, models.ClaimValidation),
    }


def _add_scripted_source(session, source_id: str) -> models.OfficialSourceRow:
    return repo.reconcile_official_source(
        session,
        {
            "id": source_id,
            "benchmark_id": "hf_official_benchmarks",
            "source_name": f"Scripted {source_id}",
            "source_url": f"file:///{source_id}.json",
            "source_type": "fake",
            "officialness_level": "O5",
            "machine_readable": True,
            "requires_auth": False,
            "supports_history": False,
            "update_cadence": "manual",
            "parser_name": "scripted",
            "parser_version": "test-v1",
            "parser_config": {},
            "status": "active",
            "notes": "LDR-04 transaction fixture",
        },
    ).source


class ScriptedAdapter(SourceAdapter):
    source_type = "fake"

    def __init__(self, *, fail_on_second_validation: set[str] | None = None) -> None:
        self.fail_on_second_validation = fail_on_second_validation or set()
        self.validation_calls: dict[str, int] = {}
        self.fetched: list[str] = []

    def fetch(self, source) -> SourceFetchResult:  # type: ignore[no-untyped-def]
        self.fetched.append(source.id)
        return SourceFetchResult(
            raw_bytes=f"{source.id}: 10.0 20.0".encode("utf-8"),
            content_type="text/plain",
            http_status=200,
        )

    def extract_claims(self, source, snapshot, raw_bytes):  # type: ignore[no-untyped-def]
        claim_count = 2 if source.id in self.fail_on_second_validation else 1
        return [
            ResultClaimInput(
                source_snapshot_id=snapshot.id,
                official_source_id=source.id,
                benchmark_id=source.benchmark_id,
                model_raw=f"Scripted model {index}",
                benchmark_raw=source.benchmark_id or source.source_name,
                score_raw=f"{(index + 1) * 10}.0",
                score_numeric=float((index + 1) * 10),
                evidence_location={"type": "scripted", "index": index},
                capture_method="scripted_adapter",
                capture_confidence=1.0,
                capture_status="parser_verified",
                officialness_level=source.officialness_level,
            )
            for index in range(claim_count)
        ]

    def validate_claim(self, claim, raw_bytes):  # type: ignore[no-untyped-def]
        source_id = claim.official_source_id
        call_count = self.validation_calls.get(source_id, 0) + 1
        self.validation_calls[source_id] = call_count
        if source_id in self.fail_on_second_validation and call_count == 2:
            raise RuntimeError("scripted validation failure after first claim")
        return [
            ClaimValidationInput(
                validation_type="scripted",
                outcome="pass",
                validator="ScriptedAdapter",
            )
        ]


def _install_scripted_runner(
    monkeypatch, source_ids: list[str], adapter: ScriptedAdapter
) -> None:  # type: ignore[no-untyped-def]
    """Install a transaction-only adapter path, never a production admission path."""

    def fixture_source_admission(session, *, source, source_revision):  # type: ignore[no-untyped-def]
        decisions = list(
            session.scalars(
                select(models.SourceRevisionDecision).where(
                    models.SourceRevisionDecision.source_revision_id == source_revision.id
                )
            )
        )
        superseded = {
            decision.supersedes_decision_id
            for decision in decisions
            if decision.supersedes_decision_id is not None
        }
        leaves = [decision for decision in decisions if decision.id not in superseded]
        assert len(leaves) == 1
        decision = leaves[0]
        if decision.outcome != "certified":
            decision = models.SourceRevisionDecision(
                source_revision_id=source_revision.id,
                outcome="certified",
                policy_version="test-scripted-admission-v1",
                reason_code="test_scripted_admission_bypass",
                basis_json={"test_fixture": True},
                actor="pytest",
                supersedes_decision_id=decision.id,
            )
            session.add(decision)
            session.flush()
        return SourceAdmission(
            AdmissionVerdict("admit", "TEST_SCRIPTED_ADMISSION_BYPASS"),
            source_revision_id=source_revision.id,
            source_revision_decision_id=decision.id,
        )

    def fixture_claim_admission(*, claim, **_kwargs):  # type: ignore[no-untyped-def]
        return ClaimAdmission(
            AdmissionVerdict("admit", "TEST_SCRIPTED_ADMISSION_BYPASS"),
            score_numeric=claim.score_numeric,
            score_unit=claim.score_unit,
        )

    monkeypatch.setattr(ingestion_runner, "can_ingest_source", lambda _source: True)
    monkeypatch.setattr(ingestion_runner, "resolve_source_admission", fixture_source_admission)
    monkeypatch.setattr(
        ingestion_runner,
        "resolve_fetch_admission",
        lambda **_kwargs: AdmissionVerdict("admit", "TEST_SCRIPTED_ADMISSION_BYPASS"),
    )
    monkeypatch.setattr(ingestion_runner, "resolve_claim_admission", fixture_claim_admission)
    monkeypatch.setattr(
        ingestion_runner.repo,
        "list_active_sources",
        lambda session, **_kwargs: [
            source for source_id in source_ids if (source := session.get(models.OfficialSourceRow, source_id))
        ],
    )
    monkeypatch.setattr(ingestion_runner, "get_adapter", lambda *_args, **_kwargs: adapter)


def test_dry_run_has_no_database_or_snapshot_storage_writes(
    seeded_db, allow_quarantined_fixture_ingestion
):
    snapshot_root = get_settings().snapshot_local_root
    assert not snapshot_root.exists()

    with get_session() as session:
        before = _evidence_counts(session)
        summary = run_ingestion(
            session,
            source_id="fake_local_fixture",
            fixture_path=FIXTURE,
            dry_run=True,
        )
        after = _evidence_counts(session)

    assert summary.status == "completed"
    assert summary.dry_run_claims
    assert summary.snapshots_created == 0
    assert summary.snapshots_reused == 0
    assert after == before
    assert not snapshot_root.exists()


def test_dry_run_leaves_existing_evidence_and_storage_tree_unchanged(
    seeded_db, allow_quarantined_fixture_ingestion
):
    with get_session() as session:
        run_ingestion(session, source_id="fake_local_fixture", fixture_path=FIXTURE)
        before = _evidence_counts(session)
        snapshot = session.scalar(select(models.SourceSnapshot))
        assert snapshot is not None
        snapshot_root = get_settings().snapshot_local_root
        tree_before = {
            path.relative_to(snapshot_root): path.read_bytes()
            for path in snapshot_root.rglob("*")
            if path.is_file()
        }

        summary = run_ingestion(
            session,
            source_id="fake_local_fixture",
            fixture_path=FIXTURE,
            dry_run=True,
        )
        after = _evidence_counts(session)
        tree_after = {
            path.relative_to(snapshot_root): path.read_bytes()
            for path in snapshot_root.rglob("*")
            if path.is_file()
        }

    assert summary.status == "completed"
    assert summary.dry_run_claims
    assert after == before
    assert tree_after == tree_before


def test_partial_failure_rolls_back_only_the_failed_source(seeded_db, monkeypatch):
    with get_session() as session:
        good = _add_scripted_source(session, "a-good-source")
        failed = _add_scripted_source(session, "z-failed-source")
        adapter = ScriptedAdapter(fail_on_second_validation={failed.id})
        _install_scripted_runner(monkeypatch, [good.id, failed.id], adapter)

        summary = run_ingestion(session)

        assert summary.status == "partial"
        assert summary.sources_checked == 2
        assert summary.sources_succeeded == 1
        assert summary.snapshots_created == 1
        assert summary.claims_inserted == 1
        assert any(failed.id in error for error in summary.errors)
        assert _count(
            session, models.SourceSnapshot
        ) == 1
        assert session.scalar(
            select(func.count())
            .select_from(models.SourceSnapshot)
            .where(models.SourceSnapshot.official_source_id == failed.id)
        ) == 0
        assert session.scalar(
            select(func.count())
            .select_from(models.ResultClaim)
            .where(models.ResultClaim.official_source_id == failed.id)
        ) == 0
        # The successful claim has both its adapter validation and the
        # central admission receipt introduced by LDR-05.
        assert _count(session, models.ClaimValidation) == 2
        run = session.scalar(select(models.IngestionRun))
        assert run is not None
        assert run.status == "partial"
        assert run.finished_at is not None
        assert failed.id in (run.error_message or "")
        assert run.metadata_json["sources_succeeded"] == 1
        assert run.metadata_json["sources_failed"] == 1
        assert any(
            outcome["source_id"] == failed.id and outcome["outcome"] == "failed"
            for outcome in run.metadata_json["source_outcomes"]
        )


def test_all_source_failures_are_failed_not_partial(seeded_db, monkeypatch):
    with get_session() as session:
        first = _add_scripted_source(session, "a-failed-source")
        second = _add_scripted_source(session, "z-failed-source")
        adapter = ScriptedAdapter(fail_on_second_validation={first.id, second.id})
        _install_scripted_runner(monkeypatch, [first.id, second.id], adapter)

        summary = run_ingestion(session, fail_fast=False)

        assert summary.status == "failed"
        assert summary.sources_succeeded == 0
        assert len(summary.errors) == 2
        assert _evidence_counts(session) == {
            "runs": 1,
            "snapshots": 0,
            "claims": 0,
            "validations": 0,
        }
        run = session.scalar(select(models.IngestionRun))
        assert run is not None
        assert run.status == "failed"
        assert len(run.metadata_json["errors"]) == 2


def test_late_failure_preserves_preexisting_snapshot_claim_and_artifact(
    seeded_db, allow_quarantined_fixture_ingestion, monkeypatch
):
    source_id = "fake_local_fixture"
    snapshot_root = get_settings().snapshot_local_root
    with get_session() as session:
        run_ingestion(session, source_id=source_id, fixture_path=FIXTURE)
        before_counts = _evidence_counts(session)
        snapshot = session.scalar(
            select(models.SourceSnapshot).where(models.SourceSnapshot.official_source_id == source_id)
        )
        assert snapshot is not None
        snapshot_id = snapshot.id
        snapshot_record = (snapshot.raw_content_uri, snapshot.content_hash, snapshot.source_revision_id)
        claims_before = [
            (claim.id, claim.model_raw, claim.score_raw, claim.claim_fingerprint)
            for claim in session.scalars(
                select(models.ResultClaim)
                .where(models.ResultClaim.official_source_id == source_id)
                .order_by(models.ResultClaim.id)
            )
        ]
        artifact_bytes_before = {
            path.relative_to(snapshot_root): path.read_bytes()
            for path in snapshot_root.rglob("*")
            if path.is_file()
        }

    adapter = ScriptedAdapter(fail_on_second_validation={source_id})
    _install_scripted_runner(monkeypatch, [source_id], adapter)
    with get_session() as session:
        summary = run_ingestion(session, source_id=source_id)
        assert summary.status == "failed"
        assert summary.claims_inserted == 0
        assert _evidence_counts(session) == {
            **before_counts,
            "runs": before_counts["runs"] + 1,
        }
        snapshot_after = session.get(models.SourceSnapshot, snapshot_id)
        assert snapshot_after is not None
        assert (
            snapshot_after.raw_content_uri,
            snapshot_after.content_hash,
            snapshot_after.source_revision_id,
        ) == snapshot_record
        claims_after = [
            (claim.id, claim.model_raw, claim.score_raw, claim.claim_fingerprint)
            for claim in session.scalars(
                select(models.ResultClaim)
                .where(models.ResultClaim.official_source_id == source_id)
                .order_by(models.ResultClaim.id)
            )
        ]
        assert claims_after == claims_before

    for relative_path, expected_bytes in artifact_bytes_before.items():
        assert (snapshot_root / relative_path).read_bytes() == expected_bytes


def test_successful_retry_adopts_an_unreferenced_content_addressed_artifact(
    seeded_db, monkeypatch
):
    source_id = "a-retry-source"
    snapshot_root = get_settings().snapshot_local_root
    with get_session() as session:
        source = _add_scripted_source(session, source_id)
        failing_adapter = ScriptedAdapter(fail_on_second_validation={source.id})
        _install_scripted_runner(monkeypatch, [source.id], failing_adapter)

        failed_summary = run_ingestion(session, source_id=source.id)
        assert failed_summary.status == "failed"
        assert _evidence_counts(session) == {
            "runs": 1,
            "snapshots": 0,
            "claims": 0,
            "validations": 0,
        }
        files_after_failure = {
            path.relative_to(snapshot_root): path.read_bytes()
            for path in snapshot_root.rglob("*")
            if path.is_file()
        }
        assert files_after_failure

    successful_adapter = ScriptedAdapter()
    monkeypatch.setattr(ingestion_runner, "get_adapter", lambda *_args, **_kwargs: successful_adapter)
    with get_session() as session:
        retry_summary = run_ingestion(session, source_id=source_id)
        files_after_retry = {
            path.relative_to(snapshot_root): path.read_bytes()
            for path in snapshot_root.rglob("*")
            if path.is_file()
        }

    assert retry_summary.status == "completed"
    assert retry_summary.snapshots_created == 1
    assert files_after_retry == files_after_failure


def test_fail_fast_commits_terminal_failure_then_cli_exits_nonzero(seeded_db, monkeypatch):
    with get_session() as session:
        failed = _add_scripted_source(session, "a-failed-source")
        unattempted = _add_scripted_source(session, "z-unattempted-source")
        failed_id = failed.id
        unattempted_id = unattempted.id

    adapter = ScriptedAdapter(fail_on_second_validation={failed_id})
    _install_scripted_runner(monkeypatch, [failed_id, unattempted_id], adapter)

    result = cli_runner.invoke(app, ["ingest", "--all", "--fail-fast"])

    assert result.exit_code == 1
    assert "Ingestion failed." in result.output
    assert adapter.fetched == [failed_id]
    with get_session() as session:
        run = session.scalar(select(models.IngestionRun))
        assert run is not None
        assert run.status == "failed"
        assert run.finished_at is not None
        assert run.metadata_json["stopped_early"] is True
        assert run.metadata_json["sources_attempted"] == 1
        assert run.metadata_json["sources_succeeded"] == 0
        assert _count(session, models.SourceSnapshot) == 0
        assert _count(session, models.ResultClaim) == 0


def test_cli_dry_run_does_not_initialize_a_missing_database(tmp_path: Path, monkeypatch):
    database_path = tmp_path / "missing.db"
    snapshot_root = tmp_path / "missing-snapshots"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    monkeypatch.setenv("SNAPSHOT_LOCAL_ROOT", str(snapshot_root))
    get_settings.cache_clear()
    import app.db.engine as engine

    engine._engine = None
    engine._SessionLocal = None
    try:
        result = cli_runner.invoke(app, ["ingest", "--source", "anything", "--dry-run"])
    finally:
        engine._engine = None
        engine._SessionLocal = None
        get_settings.cache_clear()

    assert result.exit_code == 2
    assert "will not initialize or migrate" in result.output
    assert not database_path.exists()
    assert not snapshot_root.exists()


def test_cli_live_ingest_initializes_a_missing_database_before_it_fails_closed(
    tmp_path: Path, monkeypatch
):
    database_path = tmp_path / "missing.db"
    snapshot_root = tmp_path / "missing-snapshots"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    monkeypatch.setenv("SNAPSHOT_LOCAL_ROOT", str(snapshot_root))
    get_settings.cache_clear()
    import app.db.engine as engine

    engine._engine = None
    engine._SessionLocal = None
    try:
        result = cli_runner.invoke(app, ["ingest", "--source", "anything"])
    finally:
        engine._engine = None
        engine._SessionLocal = None
        get_settings.cache_clear()

    assert result.exit_code == 2
    assert "Ingestion blocked:" in result.output
    assert database_path.exists()
    assert not snapshot_root.exists()
