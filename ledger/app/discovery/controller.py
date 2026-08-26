"""DSC-01 discovery controller: deterministic cycles over fixture manifests.

One cycle binds a validated manifest to one explicit UTC slot.  The
controller freezes every target's planner disposition as pre-dispatch job
truth through the DATA-09 operational repositories, runs the connector seam
for due targets against fixture bytes, persists quarantined candidates
idempotently, and returns a receipt whose denominator accounting must
balance exactly.  It writes operational scheduler/discovery rows only —
never ``SourceSnapshot``/``ResultClaim`` rows, source decisions, or any
certification/publication fact.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models
from app.db.operational_repositories import (
    append_discovery_candidate,
    append_scheduled_cycle_intent,
)
from app.discovery.connectors.base import (
    ConnectorError,
    DiscoveryConnector,
    StaticFixtureConnector,
)
from app.discovery.manifest import DiscoveryManifest
from app.discovery.planner import plan_dispositions
from app.runtime.dependencies import (
    RuntimeCapability,
    RuntimeDependencies,
    validate_runtime_dependencies,
)
from app.scheduling.slots import ScheduleSlot


class DiscoveryControllerError(ValueError):
    """Raised when a discovery cycle cannot complete with balanced accounting."""


_RUN_OUTCOMES = {
    "not_due",
    "blocked",
    "unchanged",
    "changed",
    "review_required",
    "failed",
}

# Hard ceiling on quarantined candidates persisted across a single discovery
# cycle.  The controller fails the whole cycle (and the caller rolls back the
# transaction) before any disputed candidate is written, so a runaway or
# malicious observation can never flood the operational tables.
MAX_CANDIDATES_PER_CYCLE = 10_000


@dataclass(frozen=True, slots=True)
class TargetRunRecord:
    """One target's terminal cycle outcome for the receipt."""

    target_revision_id: str
    target_id: str
    due_disposition: str
    disposition_reason_code: str
    run_outcome: str
    candidate_ids: tuple[str, ...]
    new_candidate_ids: tuple[str, ...]
    failure_reason_code: str | None


@dataclass(frozen=True, slots=True)
class CycleRunReport:
    """One deterministic cycle receipt with balanced denominators."""

    cycle_id: str
    environment: str
    lane: str
    schedule_policy_revision_id: str
    mode: str
    slot: ScheduleSlot
    records: tuple[TargetRunRecord, ...]
    counts: Mapping[str, int]

    def to_document(self) -> dict[str, Any]:
        return {
            "schemaVersion": "1.0.0",
            "policyVersion": "discovery-run-receipt-v1",
            "availability": "candidate_only",
            "cycleId": self.cycle_id,
            "environment": self.environment,
            "lane": self.lane,
            "schedulePolicyRevisionId": self.schedule_policy_revision_id,
            "mode": self.mode,
            "slot": self.slot.slot_document(),
            "counts": dict(self.counts),
            "targets": [
                {
                    "targetRevisionId": record.target_revision_id,
                    "targetId": record.target_id,
                    "dueDisposition": record.due_disposition,
                    "dispositionReasonCode": record.disposition_reason_code,
                    "runOutcome": record.run_outcome,
                    "candidateIds": list(record.candidate_ids),
                    "newCandidateIds": list(record.new_candidate_ids),
                    "failureReasonCode": record.failure_reason_code,
                }
                for record in self.records
            ],
            "authority": {
                "classification": "candidate_reconnaissance_only",
                "certifiesSources": False,
                "authorizesCapture": False,
                "authorizesPublication": False,
                "frontendLoadable": False,
            },
        }


def build_fixture_connectors(
    dependencies: RuntimeDependencies,
) -> dict[str, DiscoveryConnector]:
    """Build the fixture connector registry from the inert composition root.

    The runtime bundle is revalidated exactly, and any network-fetch
    capability fails closed: fixture discovery never holds live authority.
    """

    bundle = validate_runtime_dependencies(dependencies)
    if RuntimeCapability.NETWORK_FETCH in bundle.capabilities:
        raise DiscoveryControllerError(
            "fixture discovery cannot run with network fetch authority"
        )
    return {"static-fixture": StaticFixtureConnector()}


def _candidate_fingerprint_exists(session: Session, fingerprint: str) -> bool:
    return (
        session.scalar(
            select(models.DiscoveryCandidate.candidate_id).where(
                models.DiscoveryCandidate.candidate_fingerprint_sha256 == fingerprint
            )
        )
        is not None
    )


def run_discovery_cycle(
    session: Session,
    *,
    manifest: DiscoveryManifest,
    slot: ScheduleSlot,
    connectors: Mapping[str, DiscoveryConnector],
    fixture_root: Path,
) -> CycleRunReport:
    """Run one deterministic discovery cycle inside the caller's transaction.

    Replaying the same manifest at the same slot re-derives the identical
    cycle intent and re-appends the identical candidates, so a repeat run is
    a byte-exact no-op: no duplicate intents, observations, or candidates.
    """

    dispositions = plan_dispositions(
        manifest.targets,
        anchor_utc=manifest.anchor_utc,
        cadence_seconds=manifest.cadence_seconds,
        slot=slot,
    )
    job_targets = [
        {
            "targetType": "discovery_target",
            "targetRevisionId": disposition.target_revision_id,
            "sourceRevisionId": None,
            "dueDisposition": disposition.due_disposition,
            "dispositionReasonCode": disposition.disposition_reason_code,
        }
        for disposition in dispositions
    ]
    intent, _jobs = append_scheduled_cycle_intent(
        session,
        environment=manifest.environment,
        lane=manifest.lane,
        scheduled_for=slot.scheduled_for,
        schedule_policy_revision_id=manifest.schedule_policy_revision_id,
        mode=manifest.mode,
        job_targets=job_targets,
    )

    targets_by_revision = {target["targetRevisionId"]: target for target in manifest.targets}
    records: list[TargetRunRecord] = []
    candidate_total = 0
    for disposition in dispositions:
        target = targets_by_revision[disposition.target_revision_id]
        base = {
            "target_revision_id": disposition.target_revision_id,
            "target_id": disposition.target_id,
            "due_disposition": disposition.due_disposition,
            "disposition_reason_code": disposition.disposition_reason_code,
        }
        if disposition.due_disposition != "due":
            records.append(
                TargetRunRecord(
                    **base,
                    run_outcome=disposition.due_disposition,
                    candidate_ids=(),
                    new_candidate_ids=(),
                    failure_reason_code=None,
                )
            )
            continue

        connector = connectors.get(target["connector"]["connectorId"])
        failure: str | None = None
        observation = None
        if connector is None:
            failure = "CONNECTOR_UNKNOWN"
        else:
            try:
                observation = connector.observe(
                    target=target, fixture_root=Path(fixture_root), slot=slot
                )
            except ConnectorError as exc:
                failure = exc.reason_code
            except Exception:
                failure = "CONNECTOR_INTERNAL_ERROR"
        if failure is not None:
            records.append(
                TargetRunRecord(
                    **base,
                    run_outcome="failed",
                    candidate_ids=(),
                    new_candidate_ids=(),
                    failure_reason_code=failure,
                )
            )
            continue

        assert observation is not None
        proposed = candidate_total + len(observation.candidates)
        if proposed > MAX_CANDIDATES_PER_CYCLE:
            raise DiscoveryControllerError(
                f"candidate count {proposed} exceeds per-cycle cap "
                f"{MAX_CANDIDATES_PER_CYCLE}"
            )
        candidate_total = proposed
        candidate_ids: list[str] = []
        new_candidate_ids: list[str] = []
        for payload in observation.candidates:
            replayed = _candidate_fingerprint_exists(
                session, payload["candidateFingerprintSha256"]
            )
            row = append_discovery_candidate(session, payload)
            candidate_ids.append(row.candidate_id)
            if not replayed:
                new_candidate_ids.append(row.candidate_id)
        if observation.review_required:
            outcome = "review_required"
        elif new_candidate_ids:
            outcome = "changed"
        else:
            outcome = "unchanged"
        records.append(
            TargetRunRecord(
                **base,
                run_outcome=outcome,
                candidate_ids=tuple(candidate_ids),
                new_candidate_ids=tuple(new_candidate_ids),
                failure_reason_code=None,
            )
        )

    outcome_counts = {outcome: 0 for outcome in _RUN_OUTCOMES}
    for record in records:
        outcome_counts[record.run_outcome] += 1
    due = outcome_counts["unchanged"] + outcome_counts["changed"] + outcome_counts["review_required"] + outcome_counts["failed"]
    counts = {
        "expectedTargetCount": len(records),
        "dueCount": due,
        "notDueCount": outcome_counts["not_due"],
        "blockedCount": outcome_counts["blocked"],
        "checkedCount": outcome_counts["unchanged"] + outcome_counts["changed"] + outcome_counts["review_required"],
        "failedCount": outcome_counts["failed"],
        "unchangedCount": outcome_counts["unchanged"],
        "changedCount": outcome_counts["changed"],
        "reviewRequiredCount": outcome_counts["review_required"],
        "newCandidateCount": sum(len(record.new_candidate_ids) for record in records),
        "replayedCandidateCount": sum(
            len(record.candidate_ids) - len(record.new_candidate_ids) for record in records
        ),
    }
    balanced = (
        counts["expectedTargetCount"]
        == counts["dueCount"] + counts["notDueCount"] + counts["blockedCount"]
        and counts["dueCount"] == counts["checkedCount"] + counts["failedCount"]
        and counts["checkedCount"]
        == counts["unchangedCount"] + counts["changedCount"] + counts["reviewRequiredCount"]
    )
    if not balanced:
        raise DiscoveryControllerError("denominator accounting does not balance")

    return CycleRunReport(
        cycle_id=intent.cycle_id,
        environment=manifest.environment,
        lane=manifest.lane,
        schedule_policy_revision_id=manifest.schedule_policy_revision_id,
        mode=manifest.mode,
        slot=slot,
        records=tuple(records),
        counts=counts,
    )


__all__ = [
    "CycleRunReport",
    "DiscoveryControllerError",
    "MAX_CANDIDATES_PER_CYCLE",
    "TargetRunRecord",
    "build_fixture_connectors",
    "run_discovery_cycle",
]
