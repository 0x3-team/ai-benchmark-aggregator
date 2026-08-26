"""Deterministic due planner for discovery targets (DSC-01).

The planner is a pure function of the validated manifest and the explicit
UTC slot: it never consults a wall clock, wake-up delivery facts, local
timezones, or a database.  Every declared target receives exactly one
terminal planner disposition whose reason code is drawn from the
``scheduled-cycle-v1`` allowlists, so the resulting job intents are directly
persistable through the DATA-09 operational repositories.
"""

from __future__ import annotations

from dataclasses import dataclass
import re

from app.scheduling.slots import ScheduleSlot


class DiscoveryPlannerError(ValueError):
    """Raised when a target due policy cannot produce a deterministic plan."""


_DURATION = re.compile(r"^P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?$")

#: Terminal planner disposition for every non-configured target status.
#: Reason codes are exactly the ``scheduled-cycle-v1`` planner allowlist.
_STATUS_DISPOSITION = {
    "draft": ("blocked", "SOURCE_POLICY_BLOCKED"),
    "paused": ("blocked", "OPERATOR_PAUSED"),
    "blocked_terms": ("blocked", "TERMS_POLICY_BLOCKED"),
    "blocked_permission": ("blocked", "TERMS_POLICY_BLOCKED"),
    "retired": ("not_due", "NOT_DUE_BY_POLICY"),
}


@dataclass(frozen=True, slots=True)
class TargetDisposition:
    """One target's frozen planner decision for one deterministic slot."""

    target_revision_id: str
    target_id: str
    due_disposition: str
    disposition_reason_code: str


def parse_cadence_seconds(duration: str) -> int:
    """Convert the contract's bounded ISO-8601 duration to exact seconds."""

    if type(duration) is not str:
        raise DiscoveryPlannerError("duePolicy.cadence must be an ISO-8601 string")
    match = _DURATION.fullmatch(duration)
    if match is None or all(group is None for group in match.groups()):
        raise DiscoveryPlannerError(
            f"duePolicy.cadence {duration!r} is not a supported ISO-8601 duration"
        )
    days, hours, minutes, seconds = (
        int(group) if group is not None else 0 for group in match.groups()
    )
    total = days * 86_400 + hours * 3_600 + minutes * 60 + seconds
    if total < 1:
        raise DiscoveryPlannerError("duePolicy.cadence must be at least one second")
    return total


def plan_dispositions(
    targets: tuple[dict, ...],
    *,
    anchor_utc: str,
    cadence_seconds: int,
    slot: ScheduleSlot,
) -> tuple[TargetDisposition, ...]:
    """Assign every target exactly one terminal planner disposition.

    A configured target is due when the elapsed seconds between the schedule
    anchor and this slot are an exact multiple of the target's due cadence.
    Slot ordinal zero (the anchor itself) is therefore always due, which
    makes the first fixture cycle exercise every configured target.
    """

    if slot.anchor_utc != anchor_utc or slot.cadence_seconds != cadence_seconds:
        raise DiscoveryPlannerError(
            "slot does not bind the manifest's anchored schedule policy"
        )
    elapsed = slot.slot_ordinal * slot.cadence_seconds
    dispositions: list[TargetDisposition] = []
    for target in targets:
        status = target["configurationStatus"]
        if status == "configured":
            target_cadence = parse_cadence_seconds(target["duePolicy"]["cadence"])
            if elapsed % target_cadence == 0:
                due, reason = "due", "DUE_BY_SCHEDULE"
            else:
                due, reason = "not_due", "NOT_DUE_BY_POLICY"
        else:
            try:
                due, reason = _STATUS_DISPOSITION[status]
            except KeyError:
                raise DiscoveryPlannerError(
                    f"target {target['targetRevisionId']!r} has unsupported "
                    f"configurationStatus {status!r}"
                ) from None
        dispositions.append(
            TargetDisposition(
                target_revision_id=target["targetRevisionId"],
                target_id=target["targetId"],
                due_disposition=due,
                disposition_reason_code=reason,
            )
        )
    return tuple(sorted(dispositions, key=lambda item: item.target_revision_id))


__all__ = [
    "DiscoveryPlannerError",
    "TargetDisposition",
    "parse_cadence_seconds",
    "plan_dispositions",
]
