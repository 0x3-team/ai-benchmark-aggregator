"""Read-only discovery status projection for operators (DSC-01).

The projection reads durable scheduler/discovery rows only and renders a
deterministic report in canonical-style JSON or Markdown.  It never writes,
never certifies, and never treats candidate reconnaissance as coverage,
capture, or publication truth.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models


def _utc_text(value: Any) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def build_discovery_status(session: Session) -> dict[str, Any]:
    """Project discovery cycle intents and quarantined candidates, read-only."""

    intents = list(
        session.scalars(
            select(models.ScheduledCycleIntent)
            .where(models.ScheduledCycleIntent.lane == "discovery")
            .order_by(
                models.ScheduledCycleIntent.scheduled_for,
                models.ScheduledCycleIntent.cycle_id,
            )
        )
    )
    candidates = list(
        session.scalars(
            select(models.DiscoveryCandidate).order_by(
                models.DiscoveryCandidate.candidate_id
            )
        )
    )

    cycles: list[dict[str, Any]] = []
    for intent in intents:
        jobs = intent.payload_json.get("jobs", [])
        dispositions = {"due": 0, "not_due": 0, "blocked": 0}
        for job in jobs:
            disposition = job.get("dueDisposition")
            if disposition in dispositions:
                dispositions[disposition] += 1
        cycles.append(
            {
                "cycleId": intent.cycle_id,
                "environment": intent.environment,
                "scheduledFor": _utc_text(intent.scheduled_for),
                "schedulePolicyRevisionId": intent.schedule_policy_revision_id,
                "mode": intent.mode,
                "jobCount": intent.job_count,
                "dueCount": dispositions["due"],
                "notDueCount": dispositions["not_due"],
                "blockedCount": dispositions["blocked"],
            }
        )

    by_state: dict[str, int] = {}
    by_target: dict[str, int] = {}
    for candidate in candidates:
        by_state[candidate.state] = by_state.get(candidate.state, 0) + 1
        by_target[candidate.target_revision_id] = (
            by_target.get(candidate.target_revision_id, 0) + 1
        )

    return {
        "schemaVersion": "1.0.0",
        "policyVersion": "discovery-status-report-v1",
        "availability": "report_only",
        "cycles": cycles,
        "candidates": {
            "total": len(candidates),
            "byState": {key: by_state[key] for key in sorted(by_state)},
            "byTargetRevisionId": {key: by_target[key] for key in sorted(by_target)},
        },
        "authority": {
            "classification": "candidate_reconnaissance_only",
            "certifiesSources": False,
            "authorizesCapture": False,
            "authorizesPublication": False,
            "frontendLoadable": False,
        },
    }


def render_status_markdown(document: dict[str, Any]) -> str:
    """Render the status projection as a deterministic Markdown report."""

    lines = [
        "# Discovery status (report only)",
        "",
        "Candidate reconnaissance only; certifies no sources, authorizes no capture or publication.",
        "",
        "## Cycles",
        "",
        "| Cycle | Scheduled (UTC) | Mode | Jobs | Due | Not due | Blocked |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for cycle in document["cycles"]:
        lines.append(
            f"| `{cycle['cycleId']}` | {cycle['scheduledFor']} | {cycle['mode']} "
            f"| {cycle['jobCount']} | {cycle['dueCount']} | {cycle['notDueCount']} "
            f"| {cycle['blockedCount']} |"
        )
    if not document["cycles"]:
        lines.append("| — | — | — | 0 | 0 | 0 | 0 |")
    candidates = document["candidates"]
    lines += [
        "",
        "## Quarantined candidates",
        "",
        f"- Total: {candidates['total']}",
    ]
    for state, count in candidates["byState"].items():
        lines.append(f"- State `{state}`: {count}")
    for target, count in candidates["byTargetRevisionId"].items():
        lines.append(f"- Target `{target}`: {count}")
    lines.append("")
    return "\n".join(lines)


__all__ = ["build_discovery_status", "render_status_markdown"]
