"""One explicit, live-disabled dependency boundary for ingestion.

The ordinary composition is intentionally useful only for contained local
fixtures: it has immutable settings, a fresh local storage factory, and no
network, scheduler, incident, or notification authority.  Supplying a
protocol-shaped object is not authority.  Any future side-effecting adapter
must also receive the corresponding code-level capability grant.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import inspect
from pathlib import Path
from typing import Protocol, runtime_checkable

from app.config import Settings, get_settings
from app.ingestion.safe_fetch import (
    DisabledNetworkTransport,
    FetchTransport,
    Resolver,
    SafeFetchClient,
    SafeFetchError,
    SafeFetchSettings,
    _rate_limiter_accepts_deadline,
    system_resolver,
)
from app.storage.base import (
    SnapshotStorageRunner,
    StorageSecurityPosture,
)
from app.storage.local import LocalSnapshotStorage


class RuntimeDependencyError(ValueError):
    """A supplied runtime bundle could grant ambiguous or unsafe authority."""


class RuntimeCapability(str, Enum):
    """Code-level grants; process environment values never create these."""

    NETWORK_FETCH = "network_fetch"
    EXTERNAL_SNAPSHOT_STORAGE = "external_snapshot_storage"
    SCHEDULER_STATE = "scheduler_state"
    INCIDENT_OPENING = "incident_opening"


@runtime_checkable
class Clock(Protocol):
    def now(self) -> datetime: ...


@runtime_checkable
class SchedulerRepository(Protocol):
    """Future scheduler seam; CFG-01 never acquires durable scheduler state."""

    def acquire_source_state(self, *, source_id: str, observed_at: datetime) -> None: ...


@runtime_checkable
class IncidentService(Protocol):
    """Future incident seam; CFG-01 never opens or persists an incident."""

    def open_incident(
        self,
        *,
        source_id: str,
        reason_code: str,
        detail: str,
        observed_at: datetime,
    ) -> None: ...


@runtime_checkable
class RateLimiter(Protocol):
    """Synchronous admission immediately before each transport request."""

    def acquire(
        self,
        *,
        source_id: str,
        url: str,
        observed_at: datetime,
        timeout_seconds: float,
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class UTCClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class NoOpSchedulerRepository:
    def acquire_source_state(self, *, source_id: str, observed_at: datetime) -> None:
        _ = source_id, observed_at


@dataclass(frozen=True, slots=True)
class NoOpIncidentService:
    def open_incident(
        self,
        *,
        source_id: str,
        reason_code: str,
        detail: str,
        observed_at: datetime,
    ) -> None:
        _ = source_id, reason_code, detail, observed_at


@dataclass(frozen=True, slots=True)
class NoOpRateLimiter:
    def acquire(
        self,
        *,
        source_id: str,
        url: str,
        observed_at: datetime,
        timeout_seconds: float,
    ) -> None:
        _ = source_id, url, observed_at, timeout_seconds


StorageFactory = Callable[[], SnapshotStorageRunner]


@dataclass(frozen=True, slots=True)
class LocalSnapshotStorageFactory:
    """Canonical no-network local factory, safe to admit before invocation."""

    root: Path

    def __post_init__(self) -> None:
        if not isinstance(self.root, Path):
            raise RuntimeDependencyError("Local snapshot storage root must be a pathlib.Path.")

    def __call__(self) -> SnapshotStorageRunner:
        return LocalSnapshotStorage(self.root)


def _default_local_storage_factory_value() -> LocalSnapshotStorageFactory:
    return LocalSnapshotStorageFactory(Path("./data/snapshots"))


_FORBIDDEN_STORAGE_CAPABILITIES = frozenset(
    {
        "configure_retention",
        "delete",
        "delete_expired",
        "delete_object",
        "overwrite",
        "put_retention_policy",
        "set_lifecycle",
    }
)
_MISSING = object()


def validate_snapshot_storage_runner(storage: object) -> SnapshotStorageRunner:
    """Reject admin/delete-bearing or weakly-postured storage products."""

    if not isinstance(storage, SnapshotStorageRunner):
        raise RuntimeDependencyError(
            "Snapshot storage factory must return a SnapshotStorageRunner implementation."
        )
    storage_type = type(storage)
    exposed = sorted(
        name
        for name in _FORBIDDEN_STORAGE_CAPABILITIES
        if inspect.getattr_static(storage_type, name, _MISSING) is not _MISSING
        or inspect.getattr_static(storage, name, _MISSING) is not _MISSING
    )
    if exposed:
        raise RuntimeDependencyError(
            "Runner snapshot storage exposes forbidden admin/delete capability: "
            + ", ".join(exposed)
        )
    posture = inspect.getattr_static(storage_type, "security_posture", _MISSING)
    if type(posture) is not StorageSecurityPosture or posture != StorageSecurityPosture.application_only():
        raise RuntimeDependencyError(
            "Runner snapshot storage must declare the canonical application-only security posture."
        )
    return storage


@dataclass(frozen=True, slots=True)
class RuntimeDependencies:
    """Frozen composition root passed as one value into ingestion."""

    fetch_transport: FetchTransport = field(default_factory=DisabledNetworkTransport)
    resolver: Resolver = system_resolver
    storage_factory: StorageFactory | None = field(
        default_factory=_default_local_storage_factory_value
    )
    clock: Clock = field(default_factory=UTCClock)
    scheduler_repository: SchedulerRepository = field(default_factory=NoOpSchedulerRepository)
    incident_service: IncidentService = field(default_factory=NoOpIncidentService)
    rate_limiter: RateLimiter = field(default_factory=NoOpRateLimiter)
    fetch_settings: SafeFetchSettings = field(default_factory=SafeFetchSettings)
    ingestion_fail_fast: bool = False
    capabilities: frozenset[RuntimeCapability] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        if type(self.capabilities) is not frozenset or any(
            type(capability) is not RuntimeCapability for capability in self.capabilities
        ):
            raise RuntimeDependencyError(
                "capabilities must be an explicit frozenset of RuntimeCapability values."
            )
        if not isinstance(self.fetch_transport, DisabledNetworkTransport):
            if RuntimeCapability.NETWORK_FETCH not in self.capabilities:
                raise RuntimeDependencyError(
                    "A non-disabled fetch transport requires explicit NETWORK_FETCH capability."
                )
        if (
            type(self.scheduler_repository) is not NoOpSchedulerRepository
            and RuntimeCapability.SCHEDULER_STATE not in self.capabilities
        ):
            raise RuntimeDependencyError(
                "A scheduler repository requires explicit SCHEDULER_STATE capability."
            )
        if (
            type(self.incident_service) is not NoOpIncidentService
            and RuntimeCapability.INCIDENT_OPENING not in self.capabilities
        ):
            raise RuntimeDependencyError(
                "An incident service requires explicit INCIDENT_OPENING capability."
            )
        if not isinstance(self.fetch_transport, FetchTransport):
            raise RuntimeDependencyError("fetch_transport must implement FetchTransport.")
        if not callable(self.resolver):
            raise RuntimeDependencyError("resolver must be callable.")
        if self.storage_factory is not None and not callable(self.storage_factory):
            raise RuntimeDependencyError("storage_factory must be callable or None.")
        for dependency, protocol, label in (
            (self.clock, Clock, "clock"),
            (self.scheduler_repository, SchedulerRepository, "scheduler_repository"),
            (self.incident_service, IncidentService, "incident_service"),
            (self.rate_limiter, RateLimiter, "rate_limiter"),
        ):
            if not isinstance(dependency, protocol):
                raise RuntimeDependencyError(f"{label} does not implement its runtime protocol.")
        if not _rate_limiter_accepts_deadline(self.rate_limiter):
            raise RuntimeDependencyError(
                "rate_limiter must accept the complete deadline-aware contract."
            )
        if (
            not isinstance(self.fetch_transport, DisabledNetworkTransport)
            and type(self.rate_limiter) is NoOpRateLimiter
        ):
            raise RuntimeDependencyError(
                "A non-disabled fetch transport requires an explicitly injected rate limiter."
            )
        if type(self.fetch_settings) is not SafeFetchSettings:
            raise RuntimeDependencyError(
                "fetch_settings must be a canonical frozen SafeFetchSettings value."
            )
        if type(self.ingestion_fail_fast) is not bool:
            raise RuntimeDependencyError("ingestion_fail_fast must be a boolean.")

    def require_network_fetch(self) -> None:
        """Fail before DNS, limiter, transport, storage, or run-row effects."""

        if isinstance(self.fetch_transport, DisabledNetworkTransport):
            raise SafeFetchError(
                "FETCH_TRANSPORT_UNAVAILABLE",
                "a runner-specific peer-pinning transport and egress policy are required",
            )
        if RuntimeCapability.NETWORK_FETCH not in self.capabilities:
            # Defensive revalidation for a forged instance created outside the
            # dataclass initializer.
            raise RuntimeDependencyError(
                "Network fetch authority is absent from the runtime capability set."
            )

    def create_fetch_client(self) -> SafeFetchClient:
        return SafeFetchClient(
            transport=self.fetch_transport,
            resolver=self.resolver,
            settings=self.fetch_settings,
            clock=self.clock,
            rate_limiter=self.rate_limiter,
        )

    def create_snapshot_storage(self) -> SnapshotStorageRunner:
        if self.storage_factory is None:
            raise RuntimeDependencyError("Persistent ingestion requires a snapshot storage factory.")
        is_local_factory = type(self.storage_factory) is LocalSnapshotStorageFactory
        if (
            not is_local_factory
            and RuntimeCapability.EXTERNAL_SNAPSHOT_STORAGE not in self.capabilities
        ):
            raise RuntimeDependencyError(
                "Non-local snapshot storage factory requires explicit "
                "EXTERNAL_SNAPSHOT_STORAGE capability before invocation."
            )
        storage = validate_snapshot_storage_runner(self.storage_factory())
        if (
            is_local_factory
            and type(storage) is not LocalSnapshotStorage
        ):
            raise RuntimeDependencyError(
                "Canonical local snapshot storage factory returned a substituted product."
            )
        return storage


def validate_runtime_dependencies(dependencies: object) -> RuntimeDependencies:
    """Revalidate the exact bundle so forged/duck-typed substitutes fail closed."""

    if type(dependencies) is not RuntimeDependencies:
        raise RuntimeDependencyError(
            "Ingestion dependencies must be an exact RuntimeDependencies bundle."
        )
    try:
        dependencies.__post_init__()
    except RuntimeDependencyError:
        raise
    except Exception as exc:
        raise RuntimeDependencyError("Runtime dependency bundle is malformed.") from exc
    return dependencies


def contained_runtime_dependencies(settings: Settings | None = None) -> RuntimeDependencies:
    """Build the sole ordinary/local composition; it can never enable live I/O."""

    selected = get_settings() if settings is None else settings
    if not isinstance(selected, Settings):
        raise RuntimeDependencyError("Contained runtime settings must be a Settings instance.")
    snapshot_root = Path(selected.snapshot_local_root)

    return RuntimeDependencies(
        fetch_transport=DisabledNetworkTransport(),
        resolver=system_resolver,
        storage_factory=LocalSnapshotStorageFactory(snapshot_root),
        clock=UTCClock(),
        scheduler_repository=NoOpSchedulerRepository(),
        incident_service=NoOpIncidentService(),
        rate_limiter=NoOpRateLimiter(),
        fetch_settings=SafeFetchSettings(
            timeout_seconds=float(selected.http_timeout_seconds),
            user_agent=selected.http_user_agent,
        ),
        ingestion_fail_fast=selected.ingestion_fail_fast,
        capabilities=frozenset(),
    )
