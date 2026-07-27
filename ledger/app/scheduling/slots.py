"""Deterministic UTC slot calculus for scheduled discovery cycles (DSC-01).

The calculus is pure UTC arithmetic anchored to an explicit instant with an
explicit cadence, so slot identity never consults local timezones, DST rules,
wall clocks, or trigger delivery facts.  Slot identities are exactly the
``scheduled-cycle-v1`` identities from ``app.schemas.operations_contracts``,
which makes them reusable later by the recheck lane (RCK-01).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from app.schemas.operations_contracts import (
    OperationsContractError,
    derive_cycle_id,
    scheduled_slot_utc,
)


class ScheduleSlotError(ValueError):
    """Raised when a slot request is outside the deterministic calculus."""


#: Twice-daily cadence: two slots per UTC day, DST-independent by definition.
TWICE_DAILY_CADENCE_SECONDS = 43_200


@dataclass(frozen=True, slots=True)
class ScheduleSlot:
    """One immutable deterministic slot in an anchored UTC cadence."""

    anchor_utc: str
    cadence_seconds: int
    slot_ordinal: int
    scheduled_for: str
    next_scheduled_for: str
    completion_window_ends_at: str

    def cycle_id(self, environment: str, lane: str, schedule_policy_revision_id: str) -> str:
        """Derive the canonical scheduled-cycle-v1 identity for this slot."""

        return derive_cycle_id(
            environment, lane, self.scheduled_for, schedule_policy_revision_id
        )

    def slot_document(self) -> dict[str, object]:
        """Return the frozen ``$.slot`` object for a terminal cycle receipt."""

        return {
            "anchorUtc": self.anchor_utc,
            "cadenceSeconds": self.cadence_seconds,
            "slotOrdinal": self.slot_ordinal,
            "scheduledFor": self.scheduled_for,
            "nextScheduledFor": self.next_scheduled_for,
            "completionWindowEndsAt": self.completion_window_ends_at,
            "catchUpDisposition": "scheduled",
            "missedSlotCount": 0,
        }


def _parse_utc(value: str, field: str) -> datetime:
    if type(value) is not str:
        raise ScheduleSlotError(f"{field} must be a canonical UTC string")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise ScheduleSlotError(
            f"{field} must be canonical UTC YYYY-MM-DDTHH:MM:SSZ"
        ) from exc


def slot_for_ordinal(anchor_utc: str, cadence_seconds: int, slot_ordinal: int) -> ScheduleSlot:
    """Materialize the immutable slot at one explicit cadence ordinal."""

    if type(cadence_seconds) is not int or cadence_seconds < 1:
        raise ScheduleSlotError("cadence_seconds must be a positive integer")
    if type(slot_ordinal) is not int or slot_ordinal < 0:
        raise ScheduleSlotError("slot_ordinal must be a non-negative integer")
    try:
        scheduled_for = scheduled_slot_utc(anchor_utc, cadence_seconds, slot_ordinal)
        next_scheduled_for = scheduled_slot_utc(anchor_utc, cadence_seconds, slot_ordinal + 1)
    except OperationsContractError as exc:
        raise ScheduleSlotError(str(exc)) from exc
    return ScheduleSlot(
        anchor_utc=anchor_utc,
        cadence_seconds=cadence_seconds,
        slot_ordinal=slot_ordinal,
        scheduled_for=scheduled_for,
        next_scheduled_for=next_scheduled_for,
        # The completion window ends exactly at the next slot; the operations
        # contract requires scheduledFor < window end <= nextScheduledFor.
        completion_window_ends_at=next_scheduled_for,
    )


def slot_at(anchor_utc: str, cadence_seconds: int, instant_utc: str) -> ScheduleSlot:
    """Return the most recent slot at or before an explicit UTC instant."""

    anchor = _parse_utc(anchor_utc, "anchor_utc")
    instant = _parse_utc(instant_utc, "instant_utc")
    if instant < anchor:
        raise ScheduleSlotError("instant_utc precedes the schedule anchor")
    if type(cadence_seconds) is not int or cadence_seconds < 1:
        raise ScheduleSlotError("cadence_seconds must be a positive integer")
    elapsed = int((instant - anchor).total_seconds())
    return slot_for_ordinal(anchor_utc, cadence_seconds, elapsed // cadence_seconds)


__all__ = [
    "ScheduleSlot",
    "ScheduleSlotError",
    "TWICE_DAILY_CADENCE_SECONDS",
    "slot_at",
    "slot_for_ordinal",
]
