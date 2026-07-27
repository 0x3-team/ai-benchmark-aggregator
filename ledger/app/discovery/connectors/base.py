"""Connector seam for fixture-only discovery cycles.

DSC-01 defines the connector boundary; DSC-02 adds the bounded connector
families (Git repository metadata, Hugging Face dataset metadata, official
JSON/file manifests, structured-page locators, manually governed roots).
Every connector consumes fixture bytes from the fixture root only: it
performs no network, clock, database, or environment access, enforces the
target's declared budgets at the boundary, and emits quarantined
``discovery-candidate-v1`` payloads as its only output.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping, Protocol, runtime_checkable

from app.discovery.candidates import CandidateAssemblyError, assemble_candidate
from app.scheduling.slots import ScheduleSlot


class ConnectorError(ValueError):
    """A connector could not produce a bounded observation; fail closed."""

    def __init__(self, reason_code: str, detail: str = "") -> None:
        super().__init__(f"{reason_code}: {detail}" if detail else reason_code)
        self.reason_code = reason_code


@dataclass(frozen=True, slots=True)
class ConnectorObservation:
    """One bounded observation for one target at one slot."""

    candidates: tuple[dict[str, Any], ...]
    review_required: bool


@runtime_checkable
class DiscoveryConnector(Protocol):
    """The DSC-01 connector contract consumed by the discovery controller."""

    connector_id: str

    def observe(
        self,
        *,
        target: Mapping[str, Any],
        fixture_root: Path,
        slot: ScheduleSlot,
    ) -> ConnectorObservation: ...


class StaticFixtureConnector:
    """Deterministic connector that replays checked-in observation specs.

    Observation specs live in ``connectors/static.json`` under the fixture
    root, keyed by target revision ID.  A configured, due target with no
    recorded observation is a fixture authoring gap and fails closed rather
    than being silently skipped.
    """

    connector_id = "static-fixture"

    def observe(
        self,
        *,
        target: Mapping[str, Any],
        fixture_root: Path,
        slot: ScheduleSlot,
    ) -> ConnectorObservation:
        _ = slot  # Slot identity participates in receipts, never in replay truth.
        revision_id = target["targetRevisionId"]
        path = Path(fixture_root) / "connectors" / "static.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ConnectorError("STATIC_FIXTURE_UNREADABLE", type(exc).__name__) from exc
        if type(payload) is not dict or set(payload) != {"targets"}:
            raise ConnectorError("STATIC_FIXTURE_MALFORMED", "top level must be {'targets'}")
        entries = payload["targets"]
        if type(entries) is not dict:
            raise ConnectorError("STATIC_FIXTURE_MALFORMED", "'targets' must be an object")
        entry = entries.get(revision_id)
        if entry is None:
            raise ConnectorError("MISSING_FIXTURE_OBSERVATION", revision_id)
        if type(entry) is not dict or set(entry) != {"candidates", "reviewRequired"}:
            raise ConnectorError(
                "STATIC_FIXTURE_MALFORMED",
                f"{revision_id}: entry must contain exactly 'candidates' and 'reviewRequired'",
            )
        if type(entry["reviewRequired"]) is not bool:
            raise ConnectorError("STATIC_FIXTURE_MALFORMED", "'reviewRequired' must be a boolean")
        specs = entry["candidates"]
        if type(specs) is not list:
            raise ConnectorError("STATIC_FIXTURE_MALFORMED", "'candidates' must be an array")
        try:
            candidates = tuple(
                assemble_candidate(revision_id, spec) for spec in specs
            )
        except CandidateAssemblyError as exc:
            raise ConnectorError("CANDIDATE_ASSEMBLY_REJECTED", str(exc)) from exc
        return ConnectorObservation(
            candidates=candidates,
            review_required=entry["reviewRequired"],
        )


__all__ = [
    "ConnectorError",
    "ConnectorObservation",
    "DiscoveryConnector",
    "StaticFixtureConnector",
]
