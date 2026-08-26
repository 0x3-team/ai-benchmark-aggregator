from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timezone
import inspect
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from app.config import Settings
from app.db import models, repositories as repo
from app.db.engine import get_session
from app.ingestion.admission import (
    AdmissionVerdict,
    ClaimAdmission,
    SourceAdmission,
)
from app.ingestion import runner as ingestion_runner
from app.ingestion.adapters.base import SourceAdapter
from app.ingestion import safe_fetch
from app.ingestion.safe_fetch import (
    DisabledNetworkTransport,
    FetchPlan,
    FetchTransportResponse,
    SafeFetchClient,
    SafeFetchError,
    SafeFetchSettings,
)
from app.runtime.dependencies import (
    LocalSnapshotStorageFactory,
    NoOpIncidentService,
    NoOpRateLimiter,
    NoOpSchedulerRepository,
    RuntimeCapability,
    RuntimeDependencies,
    RuntimeDependencyError,
    UTCClock,
    contained_runtime_dependencies,
    validate_runtime_dependencies,
)
from app.schemas.boundary import OfficialSource
from app.storage.base import (
    SnapshotStorageIntegrityError,
    SnapshotStorageProtocolError,
    StorageObjectAddress,
    StorageObjectKind,
    StorageReadResult,
    StorageSecurityPosture,
    StorageStoreReceipt,
    StorageVerificationReceipt,
    compute_content_hash,
)
from app.storage.local import LocalSnapshotStorage


URL = "https://official.example/results.json"
REDIRECT_URL = "https://official.example/current.json"
FIXTURE = Path(__file__).parent / "fixtures" / "fake_source.json"


def _plan(**changes: object) -> FetchPlan:
    plan = FetchPlan(
        source_id="runtime-fixture",
        source_revision_id="revision-1",
        source_revision_decision_id="decision-1",
        request_url=URL,
        approved_urls=frozenset({URL, REDIRECT_URL}),
        accepted_content_types=frozenset({"application/json"}),
        timeout_seconds=7.0,
    )
    return replace(plan, **changes)


class RecordingClock:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def now(self) -> datetime:
        self.events.append("clock")
        return datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)


class RecordingRateLimiter:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.urls: list[str] = []

    def acquire(self, *, source_id: str, url: str, observed_at: datetime) -> None:
        assert source_id == "runtime-fixture"
        assert observed_at == datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)
        self.events.append("limit")
        self.urls.append(url)


class ScriptedTransport:
    def __init__(
        self,
        events: list[str],
        responses: dict[str, FetchTransportResponse] | None = None,
    ) -> None:
        self.events = events
        self.responses = responses or {
            URL: FetchTransportResponse(
                url=URL,
                status_code=200,
                headers={"content-type": "application/json"},
                body=b'{"leaderboard":[]}',
            )
        }
        self.calls: list[tuple[str, dict[str, str], float]] = []

    def request(
        self,
        *,
        url: str,
        headers,
        timeout_seconds: float,
        resolved_addresses: tuple[str, ...],
        max_bytes: int,
    ) -> FetchTransportResponse:  # type: ignore[no-untyped-def]
        _ = resolved_addresses, max_bytes
        self.events.append("transport")
        self.calls.append((url, dict(headers), timeout_seconds))
        return self.responses[url]


class ExplodingScheduler:
    def acquire_source_state(self, *, source_id: str, observed_at: datetime) -> None:
        raise AssertionError("dry-run acquired scheduler state")


class ExplodingIncidentService:
    def open_incident(
        self,
        *,
        source_id: str,
        reason_code: str,
        detail: str,
        observed_at: datetime,
    ) -> None:
        raise AssertionError("dry-run opened an incident")


class ExplodingRateLimiter:
    def acquire(self, *, source_id: str, url: str, observed_at: datetime) -> None:
        raise AssertionError("dry-run consumed rate-limit state")


class AdminBearingStorage:
    security_posture = StorageSecurityPosture.application_only()

    def store_snapshot(self, *, raw_bytes: bytes, object_kind=StorageObjectKind.SNAPSHOT):  # type: ignore[no-untyped-def]
        raise AssertionError("not reached")

    def read_snapshot(self, *, uri: str, content_sha256: str):  # type: ignore[no-untyped-def]
        raise AssertionError("not reached")

    def verify_snapshot(self, *, uri: str, content_sha256: str):  # type: ignore[no-untyped-def]
        raise AssertionError("not reached")

    def inventory_orphans(self, *, referenced_uris, object_kind=StorageObjectKind.SNAPSHOT):  # type: ignore[no-untyped-def]
        raise AssertionError("not reached")

    def delete_expired(self, *, prefix: str, authorization_receipt_id: str) -> None:
        raise AssertionError("admin capability must be rejected")


class InMemoryReceiptStorage:
    security_posture = StorageSecurityPosture.application_only()

    def __init__(self) -> None:
        self.bodies: dict[str, bytes] = {}
        self.store_calls = 0
        self.verify_calls = 0

    @staticmethod
    def _address(digest: str) -> StorageObjectAddress:
        return StorageObjectAddress(
            provider="fixture",
            object_kind=StorageObjectKind.SNAPSHOT,
            uri=f"fixture://snapshots/{digest}",
            key=f"snapshots/{digest}",
            content_sha256=digest,
        )

    def store_snapshot(
        self,
        *,
        raw_bytes: bytes,
        object_kind: StorageObjectKind = StorageObjectKind.SNAPSHOT,
    ) -> StorageStoreReceipt:
        assert object_kind is StorageObjectKind.SNAPSHOT
        self.store_calls += 1
        digest = compute_content_hash(raw_bytes)
        outcome = "reused" if digest in self.bodies else "created"
        self.bodies.setdefault(digest, raw_bytes)
        verification = self.verify_snapshot(
            uri=self._address(digest).uri,
            content_sha256=digest,
        )
        return StorageStoreReceipt.create(
            outcome=outcome,
            verification=verification,
            write_precondition="if_none_match_wildcard",
        )

    def read_snapshot(self, *, uri: str, content_sha256: str) -> StorageReadResult:
        verification = self.verify_snapshot(uri=uri, content_sha256=content_sha256)
        return StorageReadResult.create(
            raw_bytes=self.bodies[content_sha256],
            verification=verification,
        )

    def verify_snapshot(
        self,
        *,
        uri: str,
        content_sha256: str,
    ) -> StorageVerificationReceipt:
        self.verify_calls += 1
        address = self._address(content_sha256)
        assert uri == address.uri
        raw_bytes = self.bodies[content_sha256]
        return StorageVerificationReceipt.create(
            address=address,
            expected_sha256=content_sha256,
            observed_sha256=compute_content_hash(raw_bytes),
            byte_length=len(raw_bytes),
            metadata={"content-sha256": content_sha256},
        )

    def inventory_orphans(
        self,
        *,
        referenced_uris,
        object_kind: StorageObjectKind = StorageObjectKind.SNAPSHOT,
    ):  # type: ignore[no-untyped-def]
        raise AssertionError("ingestion must not inventory orphans")


def _install_mock_admitted_central_source(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[OfficialSource, SourceAdmission]:
    source = OfficialSource(
        id="runtime-fixture",
        benchmark_id="hf_official_benchmarks",
        source_name="Runtime fixture",
        source_url=URL,
        source_type="static_json",
        officialness_level="O5",
        machine_readable=True,
        parser_name="generic_json",
        status="active",
    )
    admission = SourceAdmission(
        AdmissionVerdict("admit"),
        source_revision_id="revision-1",
        source_revision_decision_id="decision-1",
        policy={
            "approved_source_urls": [URL],
            "approved_final_urls": [URL],
            "fetch": {"max_bytes": 1024},
        },
    )
    monkeypatch.setattr(
        ingestion_runner.repo,
        "list_active_sources",
        lambda *_args, **_kwargs: [object()],
    )
    monkeypatch.setattr(ingestion_runner, "_row_to_source", lambda _row: source)
    monkeypatch.setattr(ingestion_runner, "can_ingest_source", lambda _source: True)
    monkeypatch.setattr(
        ingestion_runner.repo,
        "get_current_source_revision",
        lambda *_args, **_kwargs: SimpleNamespace(id="revision-1"),
    )
    monkeypatch.setattr(
        ingestion_runner,
        "resolve_source_admission",
        lambda *_args, **_kwargs: admission,
    )
    monkeypatch.setattr(
        ingestion_runner.repo,
        "create_ingestion_run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("contained path created a run row")
        ),
    )
    return source, admission


def test_ingestion_runner_has_no_implicit_runtime_construction() -> None:
    source = inspect.getsource(ingestion_runner.run_ingestion)

    assert "get_settings()" not in source
    assert "LocalSnapshotStorage(" not in source
    assert "SafeFetchClient()" not in source


def test_safe_fetch_never_reads_process_settings() -> None:
    source = inspect.getsource(safe_fetch)

    assert "get_settings" not in source


def test_adapter_base_does_not_retain_a_fetch_client() -> None:
    source = inspect.getsource(SourceAdapter)

    assert "bind_fetch_plan" not in SourceAdapter.__dict__
    assert "SafeFetchClient" not in source


def test_contained_composition_is_frozen_disabled_lazy_and_fresh(tmp_path: Path) -> None:
    root = tmp_path / "snapshots"
    settings = Settings(
        _env_file=None,
        SNAPSHOT_LOCAL_ROOT=root,
        HTTP_TIMEOUT_SECONDS=11,
        HTTP_USER_AGENT="runtime-test/1",
    )

    first = contained_runtime_dependencies(settings)
    second = contained_runtime_dependencies(settings)

    assert isinstance(first.fetch_transport, DisabledNetworkTransport)
    assert type(first.storage_factory) is LocalSnapshotStorageFactory
    assert isinstance(first.clock, UTCClock)
    assert isinstance(first.scheduler_repository, NoOpSchedulerRepository)
    assert isinstance(first.incident_service, NoOpIncidentService)
    assert isinstance(first.rate_limiter, NoOpRateLimiter)
    assert first.capabilities == frozenset()
    assert first.fetch_settings == SafeFetchSettings(
        timeout_seconds=11,
        user_agent="runtime-test/1",
    )
    assert not root.exists()
    assert first is not second
    assert first.clock is not second.clock
    assert first.rate_limiter is not second.rate_limiter
    assert first.storage_factory is not second.storage_factory

    with pytest.raises(FrozenInstanceError):
        first.ingestion_fail_fast = True  # type: ignore[misc]

    storage = first.create_snapshot_storage()
    assert type(storage) is LocalSnapshotStorage
    assert root.exists()


def test_environment_cannot_grant_runtime_capability(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RUNTIME_CAPABILITIES", "network_fetch,external_snapshot_storage")
    monkeypatch.setenv("FETCH_TRANSPORT", "live")

    dependencies = contained_runtime_dependencies(Settings(_env_file=None))

    assert dependencies.capabilities == frozenset()
    assert isinstance(dependencies.fetch_transport, DisabledNetworkTransport)


def test_active_transport_requires_explicit_capability_and_nondefault_limiter() -> None:
    events: list[str] = []
    transport = ScriptedTransport(events)
    base = RuntimeDependencies()

    with pytest.raises(RuntimeDependencyError, match="NETWORK_FETCH"):
        replace(
            base,
            fetch_transport=transport,
            rate_limiter=RecordingRateLimiter(events),
        )
    with pytest.raises(RuntimeDependencyError, match="rate limiter"):
        replace(
            base,
            fetch_transport=transport,
            capabilities=frozenset({RuntimeCapability.NETWORK_FETCH}),
        )

    authorized = replace(
        base,
        fetch_transport=transport,
        rate_limiter=RecordingRateLimiter(events),
        capabilities=frozenset({RuntimeCapability.NETWORK_FETCH}),
    )
    assert authorized.fetch_transport is transport


def test_unauthorized_external_factory_is_rejected_before_invocation() -> None:
    calls: list[str] = []

    def exploding_factory():  # type: ignore[no-untyped-def]
        calls.append("factory")
        raise AssertionError("unauthorized factory was invoked")

    dependencies = replace(RuntimeDependencies(), storage_factory=exploding_factory)

    with pytest.raises(RuntimeDependencyError, match="before invocation"):
        dependencies.create_snapshot_storage()
    assert calls == []


def test_admin_bearing_storage_product_is_rejected() -> None:
    calls: list[str] = []

    def factory() -> AdminBearingStorage:
        calls.append("factory")
        return AdminBearingStorage()

    dependencies = replace(
        RuntimeDependencies(),
        storage_factory=factory,
        capabilities=frozenset({RuntimeCapability.EXTERNAL_SNAPSHOT_STORAGE}),
    )

    with pytest.raises(RuntimeDependencyError, match="admin/delete"):
        dependencies.create_snapshot_storage()
    assert calls == ["factory"]


def test_forged_or_duck_typed_dependency_bundles_are_rejected() -> None:
    with pytest.raises(RuntimeDependencyError, match="explicit frozenset"):
        RuntimeDependencies(capabilities=set())  # type: ignore[arg-type]
    with pytest.raises(RuntimeDependencyError, match="exact RuntimeDependencies"):
        validate_runtime_dependencies(SimpleNamespace(fetch_transport=DisabledNetworkTransport()))

    forged = object.__new__(RuntimeDependencies)
    with pytest.raises(RuntimeDependencyError, match="malformed"):
        validate_runtime_dependencies(forged)


def test_disabled_fetch_fails_before_clock_limiter_dns_or_transport() -> None:
    events: list[str] = []

    def resolver(_host: str, _port: int) -> list[str]:
        events.append("resolver")
        raise AssertionError("disabled client resolved DNS")

    client = SafeFetchClient(
        transport=DisabledNetworkTransport(),
        resolver=resolver,
        clock=RecordingClock(events),
        rate_limiter=ExplodingRateLimiter(),
    )

    with pytest.raises(SafeFetchError) as raised:
        client.fetch(_plan())

    assert raised.value.code == "FETCH_TRANSPORT_UNAVAILABLE"
    assert events == []


def test_rate_limiter_precedes_every_transport_request_deterministically() -> None:
    events: list[str] = []
    limiter = RecordingRateLimiter(events)
    transport = ScriptedTransport(
        events,
        {
            URL: FetchTransportResponse(
                url=URL,
                status_code=302,
                headers={"location": REDIRECT_URL},
                body=b"",
            ),
            REDIRECT_URL: FetchTransportResponse(
                url=REDIRECT_URL,
                status_code=200,
                headers={"content-type": "application/json"},
                body=b'{"leaderboard":[]}',
            ),
        },
    )

    def resolver(_host: str, _port: int) -> list[str]:
        events.append("resolver")
        return ["8.8.8.8"]

    client = SafeFetchClient(
        transport=transport,
        resolver=resolver,
        settings=SafeFetchSettings(timeout_seconds=7, user_agent="injected-agent/1"),
        clock=RecordingClock(events),
        rate_limiter=limiter,
    )

    result = client.fetch(_plan())

    assert result.raw_bytes == b'{"leaderboard":[]}'
    assert events == [
        "clock",
        "limit",
        "resolver",
        "transport",
        "clock",
        "limit",
        "resolver",
        "transport",
    ]
    assert limiter.urls == [URL, REDIRECT_URL]
    assert [call[0] for call in transport.calls] == [URL, REDIRECT_URL]
    assert all(call[1]["User-Agent"] == "injected-agent/1" for call in transport.calls)
    assert all(call[2] == 7.0 for call in transport.calls)


def test_injected_timeout_rejects_plan_substitution_before_runtime_side_effects() -> None:
    events: list[str] = []
    client = SafeFetchClient(
        transport=ScriptedTransport(events),
        resolver=lambda _host, _port: ["8.8.8.8"],
        settings=SafeFetchSettings(timeout_seconds=7),
        clock=RecordingClock(events),
        rate_limiter=RecordingRateLimiter(events),
    )

    with pytest.raises(SafeFetchError) as raised:
        client.fetch(_plan(timeout_seconds=8))

    assert raised.value.code == "FETCH_TIMEOUT_POLICY_MISMATCH"
    assert events == []


def test_store_and_verification_receipts_reject_type_digest_and_key_substitution() -> None:
    raw_bytes = b"canonical runtime receipt"
    digest = compute_content_hash(raw_bytes)
    address = StorageObjectAddress(
        provider="fixture",
        object_kind=StorageObjectKind.SNAPSHOT,
        uri=f"fixture://snapshots/{digest}",
        key=f"snapshots/{digest}",
        content_sha256=digest,
    )
    verification = StorageVerificationReceipt.create(
        address=address,
        expected_sha256=digest,
        observed_sha256=digest,
        byte_length=len(raw_bytes),
        metadata={"content-sha256": digest},
    )
    store = StorageStoreReceipt.create(
        outcome="created",
        verification=verification,
        write_precondition="if_none_match_wildcard",
    )

    assert ingestion_runner._require_store_receipt(
        store,
        content_hash=digest,
        byte_length=len(raw_bytes),
    ) is store
    with pytest.raises(SnapshotStorageProtocolError, match="noncanonical store receipt"):
        ingestion_runner._require_store_receipt(
            SimpleNamespace(address=address, byte_length=len(raw_bytes)),
            content_hash=digest,
            byte_length=len(raw_bytes),
        )
    with pytest.raises(SnapshotStorageIntegrityError, match="substituted"):
        ingestion_runner._require_store_receipt(
            store,
            content_hash=compute_content_hash(b"different"),
            byte_length=len(raw_bytes),
        )

    substituted_address = StorageObjectAddress(
        provider="fixture",
        object_kind=StorageObjectKind.SNAPSHOT,
        uri=address.uri,
        key=f"other/{digest}",
        content_sha256=digest,
    )
    substituted_verification = StorageVerificationReceipt.create(
        address=substituted_address,
        expected_sha256=digest,
        observed_sha256=digest,
        byte_length=len(raw_bytes),
        metadata={"content-sha256": digest},
    )
    with pytest.raises(SnapshotStorageIntegrityError, match="address or key"):
        ingestion_runner._require_verification_receipt(
            substituted_verification,
            uri=address.uri,
            content_hash=digest,
            byte_length=len(raw_bytes),
            expected_address=address,
        )


def test_dry_run_calls_no_runtime_side_effect_dependencies(
    seeded_db,
    allow_quarantined_fixture_ingestion,
) -> None:
    calls: list[str] = []

    def storage_factory():  # type: ignore[no-untyped-def]
        calls.append("storage")
        raise AssertionError("dry-run constructed storage")

    def resolver(_host: str, _port: int) -> list[str]:
        calls.append("resolver")
        raise AssertionError("dry-run resolved DNS")

    dependencies = replace(
        contained_runtime_dependencies(),
        storage_factory=storage_factory,
        resolver=resolver,
        scheduler_repository=ExplodingScheduler(),
        incident_service=ExplodingIncidentService(),
        rate_limiter=ExplodingRateLimiter(),
        capabilities=frozenset(
            {
                RuntimeCapability.EXTERNAL_SNAPSHOT_STORAGE,
                RuntimeCapability.SCHEDULER_STATE,
                RuntimeCapability.INCIDENT_OPENING,
            }
        ),
    )

    with get_session() as session:
        before = {
            model: session.scalar(select(func.count()).select_from(model)) or 0
            for model in (
                models.IngestionRun,
                models.SourceSnapshot,
                models.ResultClaim,
                models.ClaimValidation,
            )
        }
        summary = ingestion_runner.run_ingestion(
            session,
            source_id="fake_local_fixture",
            fixture_path=FIXTURE,
            dry_run=True,
            dependencies=dependencies,
        )
        repeated = ingestion_runner.run_ingestion(
            session,
            source_id="fake_local_fixture",
            fixture_path=FIXTURE,
            dry_run=True,
            dependencies=dependencies,
        )
        after = {
            model: session.scalar(select(func.count()).select_from(model)) or 0
            for model in before
        }

    assert summary.dry_run_claims
    assert repeated.dry_run_claims == summary.dry_run_claims
    assert after == before
    assert calls == []


def test_default_central_fetch_fails_before_dns_storage_or_run_row(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_mock_admitted_central_source(monkeypatch)
    events: list[str] = []

    def resolver(_host: str, _port: int) -> list[str]:
        events.append("resolver")
        raise AssertionError("disabled runtime resolved DNS")

    root = tmp_path / "snapshots"
    dependencies = replace(
        RuntimeDependencies(),
        resolver=resolver,
        storage_factory=LocalSnapshotStorageFactory(root),
    )

    with pytest.raises(SafeFetchError) as raised:
        ingestion_runner.run_ingestion(SimpleNamespace(), dependencies=dependencies)  # type: ignore[arg-type]

    assert raised.value.code == "FETCH_TRANSPORT_UNAVAILABLE"
    assert events == []
    assert not root.exists()


def test_dry_run_rejects_even_authorized_transport_without_any_runtime_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_mock_admitted_central_source(monkeypatch)
    events: list[str] = []
    transport = ScriptedTransport(events)

    def resolver(_host: str, _port: int) -> list[str]:
        events.append("resolver")
        return ["8.8.8.8"]

    def storage_factory():  # type: ignore[no-untyped-def]
        events.append("storage")
        raise AssertionError("dry-run invoked storage factory")

    dependencies = RuntimeDependencies(
        fetch_transport=transport,
        resolver=resolver,
        storage_factory=storage_factory,
        clock=RecordingClock(events),
        scheduler_repository=NoOpSchedulerRepository(),
        incident_service=NoOpIncidentService(),
        rate_limiter=RecordingRateLimiter(events),
        capabilities=frozenset(
            {
                RuntimeCapability.NETWORK_FETCH,
                RuntimeCapability.EXTERNAL_SNAPSHOT_STORAGE,
            }
        ),
    )

    with pytest.raises(SafeFetchError) as raised:
        ingestion_runner.run_ingestion(
            SimpleNamespace(),  # type: ignore[arg-type]
            dry_run=True,
            dependencies=dependencies,
        )

    assert raised.value.code == "FETCH_DRY_RUN_FORBIDDEN"
    assert events == []


def test_explicit_fixture_transport_storage_and_limiter_use_runner_owned_path(
    seeded_db,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with get_session() as session:
        source = repo.reconcile_official_source(
            session,
            {
                "id": "runtime-fixture",
                "benchmark_id": "hf_official_benchmarks",
                "source_name": "CFG-01 admitted transport fixture",
                "source_url": URL,
                "source_type": "static_json",
                "officialness_level": "O5",
                "machine_readable": True,
                "requires_auth": False,
                "supports_history": False,
                "update_cadence": "manual",
                "parser_name": "generic_json",
                "parser_version": "cfg-01-test-v1",
                "parser_config": {
                    "records_path": "$.leaderboard",
                    "model_field": "model",
                    "score_field": "score",
                },
                "status": "active",
                "notes": "Disposable admitted runtime fixture only.",
            },
        ).source
        revision = repo.get_current_source_revision(session, source.id)
        previous = session.scalar(
            select(models.SourceRevisionDecision).where(
                models.SourceRevisionDecision.source_revision_id == revision.id
            )
        )
        assert previous is not None
        certified = models.SourceRevisionDecision(
            source_revision_id=revision.id,
            outcome="certified",
            policy_version="cfg-01-test-v1",
            reason_code="test_fixture_only",
            basis_json={"fixture": True},
            actor="pytest",
            supersedes_decision_id=previous.id,
        )
        session.add(certified)
        session.flush()
        source_id = source.id
        revision_id = revision.id
        decision_id = certified.id

    admission = SourceAdmission(
        AdmissionVerdict("admit", "TEST_FIXTURE_ONLY"),
        source_revision_id=revision_id,
        source_revision_decision_id=decision_id,
        policy={
            "approved_source_urls": [URL],
            "approved_final_urls": [URL],
            "fetch": {"max_bytes": 1024},
        },
    )
    monkeypatch.setattr(
        ingestion_runner,
        "can_ingest_source",
        lambda candidate: candidate.id == source_id,
    )
    monkeypatch.setattr(
        ingestion_runner,
        "resolve_source_admission",
        lambda *_args, **_kwargs: admission,
    )
    monkeypatch.setattr(
        ingestion_runner,
        "resolve_fetch_admission",
        lambda **_kwargs: AdmissionVerdict("admit", "TEST_FIXTURE_ONLY"),
    )
    monkeypatch.setattr(
        ingestion_runner,
        "resolve_claim_admission",
        lambda **_kwargs: ClaimAdmission(
            AdmissionVerdict("admit", "TEST_FIXTURE_ONLY"),
            score_numeric=1.25,
        ),
    )

    events: list[str] = []
    transport = ScriptedTransport(
        events,
        {
            URL: FetchTransportResponse(
                url=URL,
                status_code=200,
                headers={"content-type": "application/json"},
                body=b'{"leaderboard":[{"model":"Runtime Model","score":1.25}]}',
            )
        },
    )
    limiter = RecordingRateLimiter(events)
    storage = InMemoryReceiptStorage()
    factory_calls: list[str] = []

    def storage_factory() -> InMemoryReceiptStorage:
        factory_calls.append("factory")
        return storage

    dependencies = RuntimeDependencies(
        fetch_transport=transport,
        resolver=lambda _host, _port: ["8.8.8.8"],
        storage_factory=storage_factory,
        clock=RecordingClock(events),
        scheduler_repository=NoOpSchedulerRepository(),
        incident_service=NoOpIncidentService(),
        rate_limiter=limiter,
        fetch_settings=SafeFetchSettings(user_agent="cfg-01-fixture/1"),
        capabilities=frozenset(
            {
                RuntimeCapability.NETWORK_FETCH,
                RuntimeCapability.EXTERNAL_SNAPSHOT_STORAGE,
            }
        ),
    )

    with get_session() as session:
        summary = ingestion_runner.run_ingestion(
            session,
            source_id=source_id,
            dependencies=dependencies,
        )
        snapshot = session.scalar(
            select(models.SourceSnapshot).where(
                models.SourceSnapshot.official_source_id == source_id
            )
        )
        snapshot_identity = (
            (snapshot.raw_content_uri, snapshot.content_hash)
            if snapshot is not None
            else None
        )

    assert summary.status == "completed"
    assert summary.snapshots_created == 1
    assert summary.claims_inserted == 1
    assert factory_calls == ["factory"]
    assert storage.store_calls == 1
    assert storage.verify_calls == 2
    assert limiter.urls == [URL]
    assert [call[0] for call in transport.calls] == [URL]
    assert snapshot_identity is not None
    assert snapshot_identity[0] == f"fixture://snapshots/{snapshot_identity[1]}"
