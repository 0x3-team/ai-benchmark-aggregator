from __future__ import annotations

import io
from pathlib import Path
from uuid import UUID, uuid5

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from app.db import repositories as repo
from app.db.engine import get_session
from app.db.models import OfficialSourceRow, SourceSnapshot
from app.storage.local import LocalSnapshotStorage
from app.ingestion import runner as ingestion_runner
from app.ingestion.admission import (
    AdmissionVerdict,
    ClaimAdmission,
    MatchResolution,
    SourceAdmission,
)
from app.ingestion.adapters.base import SourceAdapter
from app.ingestion.parquet_cells import ParquetCellError, ParquetEvidenceResolver
from app.ingestion.runner import _run_one_source
from app.runtime.dependencies import RuntimeDependencies
from app.schemas.boundary import (
    ClaimValidationInput,
    OfficialSource,
    ResultClaimInput,
    SourceFetchResult,
)


def _parquet_bytes() -> bytes:
    table = pa.table(
        {
            "model": ["M"],
            "score": ["1.0"],
            "rank": [1],
        }
    )
    buffer = io.BytesIO()
    pq.write_table(table, buffer)
    return buffer.getvalue()


class _LifecycleAdapter(SourceAdapter):
    """A fixture adapter that resolves typed ``parquet_cell_v1`` evidence and
    shares the run-scoped resolver across extraction and validation."""

    source_type = "fake"
    uses_parquet_evidence_resolver = True
    requires_central_fetch = False

    def __init__(self, *, fail_extract: bool = False, fail_validate: bool = False) -> None:
        self.fail_extract = fail_extract
        self.fail_validate = fail_validate
        self.shared_resolvers: list[object] = []

    def fetch(self, source: OfficialSource) -> SourceFetchResult:
        return SourceFetchResult(
            raw_bytes=_parquet_bytes(),
            content_type="application/parquet",
            http_status=200,
            metadata={"kind": "parquet_fixture"},
        )

    def extract_claims(
        self, source, snapshot, raw_bytes, *, parquet_resolver=None
    ) -> list[ResultClaimInput]:
        if self.fail_extract:
            raise RuntimeError("injected extraction failure")
        assert parquet_resolver is not None
        self.shared_resolvers.append(parquet_resolver)
        cells, error = parquet_resolver.read(row_group=0, row_index=0)
        assert error is None and cells is not None
        return [
            ResultClaimInput(
                source_snapshot_id=snapshot.id,
                official_source_id=source.id,
                benchmark_id=source.benchmark_id,
                model_raw=cells["model"],
                benchmark_raw=source.benchmark_id or "hf_official_benchmarks",
                score_raw=cells["score"],
                score_numeric=float(cells["score"]),
                evidence_location={"type": "parquet", "row_group": 0, "row_index": 0},
                capture_method="fixture_adapter",
                capture_confidence=1.0,
                capture_status="parser_verified",
                officialness_level=source.officialness_level,
            )
        ]

    def validate_claim(self, claim, raw_bytes, *, parquet_resolver=None):
        assert parquet_resolver is not None
        assert isinstance(parquet_resolver, ParquetEvidenceResolver)
        self.shared_resolvers.append(parquet_resolver)
        if self.fail_validate:
            raise RuntimeError("injected validation failure")
        parquet_resolver.verify(raw_bytes)
        return [
            ClaimValidationInput(
                validation_type="parquet_resolver_share",
                outcome="pass",
                validator="LifecycleAdapter",
            )
        ]


class _RecordingResolver(ParquetEvidenceResolver):
    """Subclass that records open/close events so the runner's resolver
    lifecycle is provable deterministically."""

    created = 0
    closed = 0
    last_instance: "_RecordingResolver | None" = None

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        type(self).created += 1
        type(self).last_instance = self

    def close(self) -> None:
        type(self).closed += 1
        super().close()


@pytest.fixture(autouse=True)
def _reset_recording(monkeypatch):
    """Route the runner's resolver construction through the recorder."""
    _RecordingResolver.created = 0
    _RecordingResolver.closed = 0
    _RecordingResolver.last_instance = None
    monkeypatch.setattr(ingestion_runner, "ParquetEvidenceResolver", _RecordingResolver)
    yield


def _source(official: OfficialSourceRow) -> OfficialSource:
    return OfficialSource(
        id=official.id,
        benchmark_id=official.benchmark_id,
        source_name=official.source_name,
        source_url=official.source_url,
        source_type=official.source_type,
        officialness_level=official.officialness_level,
        parser_name=official.parser_name or "fake",
        parser_config=official.parser_config or {},
    )


def _admission(revision_id: str, decision_id: str | None) -> SourceAdmission:
    return SourceAdmission(
        AdmissionVerdict("admit", "LIFECYCLE_BYPASS"),
        source_revision_id=revision_id,
        source_revision_decision_id=decision_id,
    )


def _claim_admission(*, claim, **_kwargs):
    return ClaimAdmission(
        AdmissionVerdict("admit", "TEST_LIFECYCLE"),
        score_numeric=claim.score_numeric,
        score_unit=claim.score_unit,
    )


_UUID_NS = UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")


def _decision_id(source_id: str) -> str:
    return str(uuid5(_UUID_NS, f"decision-{source_id}"))


def _add_source(session, source_id: str) -> OfficialSourceRow:
    return repo.reconcile_official_source(
        session,
        {
            "id": source_id,
            "benchmark_id": "hf_official_benchmarks",
            "source_name": f"Lifecycle {source_id}",
            "source_url": f"file://{source_id}.parquet",
            "source_type": "fake",
            "officialness_level": "O5",
            "machine_readable": True,
            "requires_auth": False,
            "supports_history": False,
            "update_cadence": "manual",
            "parser_name": "fake",
            "parser_config": {},
            "status": "active",
            "notes": "parquet resolver lifecycle test",
        },
    ).source


@pytest.fixture()
def lifecycle_env(seeded_db, monkeypatch):
    """A directly-scoped ``_run_one_source`` environment.

    ``dry_run=True`` keeps the run free of snapshot storage and database
    writes; the claim and model/benchmark resolutions are stubbed to a known
    pass so the focus stays on the resolver open/close lifecycle.
    """
    monkeypatch.setattr(ingestion_runner, "resolve_claim_admission", _claim_admission)
    monkeypatch.setattr(
        ingestion_runner,
        "resolve_fetch_admission",
        lambda **_kwargs: AdmissionVerdict("admit", "TEST_LIFECYCLE"),
    )
    monkeypatch.setattr(
        ingestion_runner,
        "resolve_model_entity",
        lambda _session, raw: MatchResolution("model-1", "matched"),
    )
    monkeypatch.setattr(
        ingestion_runner,
        "resolve_benchmark",
        lambda _session, raw, benchmark_id=None: MatchResolution(
            benchmark_id or "bench-1", "matched"
        ),
    )
    return RuntimeDependencies()


def _run_one(
    session,
    source_row: OfficialSourceRow,
    adapter: _LifecycleAdapter,
    *,
    decision_id: str | None,
    env: RuntimeDependencies,
    monkeypatch,
    dry_run: bool = True,
    storage=None,
):
    monkeypatch.setattr(
        ingestion_runner, "get_adapter", lambda *_a, **_k: adapter
    )
    revision_id = str(uuid5(_UUID_NS, f"revision-{source_row.id}"))
    return _run_one_source(
        session,
        source=_source(source_row),
        source_revision_id=revision_id,
        source_admission=_admission(revision_id, decision_id),
        dependencies=env,
        storage=storage,
        dry_run=dry_run,
        fixture_path=None,
        fetch_client=None,
    )


def test_parquet_resolver_created_and_closed_on_success(
    lifecycle_env, seeded_db, monkeypatch
) -> None:
    with get_session() as session:
        row = _add_source(session, "lifecycle-ok")
        adapter = _LifecycleAdapter()
        _run_one(
            session,
            row,
            adapter,
            decision_id=_decision_id(row.id),
            env=lifecycle_env,
            monkeypatch=monkeypatch,
        )

    assert _RecordingResolver.created == 1
    assert _RecordingResolver.closed == 1
    # The same shared instance was used for extraction and validation (one
    # open, not one per call).
    assert len(adapter.shared_resolvers) == 2
    assert all(seen is _RecordingResolver.last_instance for seen in adapter.shared_resolvers)
    # The resolver that was closed is the one that was opened (no leak).
    assert _RecordingResolver.last_instance is not None
    assert _RecordingResolver.last_instance._closed is True


def test_parquet_resolver_closed_when_extraction_raises(
    lifecycle_env, seeded_db, monkeypatch
) -> None:
    with get_session() as session:
        row = _add_source(session, "lifecycle-fail-extract")
        adapter = _LifecycleAdapter(fail_extract=True)
        with pytest.raises(RuntimeError, match="injected extraction failure"):
            _run_one(
                session,
                row,
                adapter,
                decision_id=_decision_id(row.id + "-x"),
                env=lifecycle_env,
                monkeypatch=monkeypatch,
            )

    assert _RecordingResolver.created == 1
    assert _RecordingResolver.closed == 1


def test_parquet_resolver_closed_on_missing_decision(
    lifecycle_env, seeded_db, monkeypatch
) -> None:
    """Even when the immutable decision-id guard raises after extraction, the
    opened resolver is closed in ``finally``."""
    with get_session() as session:
        row = _add_source(session, "lifecycle-missing-decision")
        adapter = _LifecycleAdapter()
        with pytest.raises(RuntimeError):
            _run_one(
                session,
                row,
                adapter,
                decision_id=None,  # no decision id => guard raises
                env=lifecycle_env,
                monkeypatch=monkeypatch,
            )

    assert _RecordingResolver.created == 1
    assert _RecordingResolver.closed == 1


def test_parquet_resolver_created_and_closed_on_rejected_admission(
    lifecycle_env, seeded_db, monkeypatch
) -> None:
    """A claim admitted-as-rejected still runs the finally path exactly once."""
    with get_session() as session:
        row = _add_source(session, "lifecycle-rejected")
        adapter = _LifecycleAdapter()

        def _reject(*, claim, **_kwargs):
            return ClaimAdmission(AdmissionVerdict("reject", "TEST_REJECT"))

        monkeypatch.setattr(ingestion_runner, "resolve_claim_admission", _reject)
        _run_one(
            session,
            row,
            adapter,
            decision_id=_decision_id(row.id + "-r"),
            env=lifecycle_env,
            monkeypatch=monkeypatch,
        )

    assert _RecordingResolver.created == 1
    assert _RecordingResolver.closed == 1


def test_parquet_resolver_fails_closed_after_close() -> None:
    resolver = ParquetEvidenceResolver(_parquet_bytes())
    resolver.close()
    with pytest.raises(ParquetCellError):
        resolver.read(row_group=0, row_index=0)
    with pytest.raises(ParquetCellError):
        list(resolver.iter_records())
    with pytest.raises(ParquetCellError):
        resolver.verify(_parquet_bytes())
    # close is idempotent and never raises after the first call.
    resolver.close()
    resolver.close()


def test_parquet_resolver_closed_when_validation_raises(
    lifecycle_env, seeded_db, monkeypatch
) -> None:
    """Defect 6: if adapter.validate_claim raises after a claim passes central
    admission, the run-scoped resolver is still created once and closed once."""
    with get_session() as session:
        row = _add_source(session, "lifecycle-fail-validate")
        adapter = _LifecycleAdapter(fail_validate=True)
        with pytest.raises(RuntimeError, match="injected validation failure"):
            _run_one(
                session,
                row,
                adapter,
                decision_id=_decision_id(row.id + "-v"),
                env=lifecycle_env,
                monkeypatch=monkeypatch,
            )

    assert _RecordingResolver.created == 1
    assert _RecordingResolver.closed == 1


def test_parquet_resolver_closed_when_persistence_insert_raises(
    lifecycle_env, seeded_db, monkeypatch, tmp_path
) -> None:
    """Defect 6: if ``insert_claim_if_new`` raises during persistence (a
    non-dry-run path), the resolver is created once and closed exactly once in
    the ``finally``."""
    storage = LocalSnapshotStorage(tmp_path / "snapshots")

    def _fake_snapshot_insert(
        session,
        *,
        official_source_id,
        source_revision_id,
        raw_content_uri,
        content_hash,
        content_type,
        http_status,
        etag,
        last_modified_header,
        fetch_metadata,
        parser_version=None,
        **_kwargs,
    ):
        # Bypass the DB current-revision gate (an unrelated reconciliation
        # constraint) so the run genuinely reaches the claim-persistence path
        # where the injected insert failure lives.  Fabricated id mirrors the
        # storage receipt the runner already verified.
        return (
            SourceSnapshot(
                id=str(UUID(int=0x11111111111111111111111111111111)),
                official_source_id=official_source_id,
                source_revision_id=source_revision_id,
                raw_content_uri=raw_content_uri,
                content_hash=content_hash,
                content_type=content_type,
                http_status=http_status,
                etag=etag,
                last_modified_header=last_modified_header,
                fetch_metadata=fetch_metadata,
                parser_version=parser_version,
            ),
            True,
        )

    def _raise_insert(*_a, **_k):
        raise RuntimeError("injected persistence insert failure")

    monkeypatch.setattr(
        ingestion_runner.repo, "insert_snapshot_if_new", _fake_snapshot_insert
    )
    monkeypatch.setattr(
        ingestion_runner.repo, "insert_claim_if_new", _raise_insert
    )
    with get_session() as session:
        row = _add_source(session, "lifecycle-persist-raise")
        adapter = _LifecycleAdapter()
        with pytest.raises(RuntimeError, match="injected persistence insert failure"):
            _run_one(
                session,
                row,
                adapter,
                decision_id=_decision_id(row.id + "-p"),
                env=lifecycle_env,
                monkeypatch=monkeypatch,
                dry_run=False,
                storage=storage,
            )

    assert _RecordingResolver.created == 1
    assert _RecordingResolver.closed == 1
