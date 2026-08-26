from __future__ import annotations

import pytest

from app.scheduling.slots import (
    ScheduleSlotError,
    TWICE_DAILY_CADENCE_SECONDS,
    slot_at,
    slot_for_ordinal,
)
from app.schemas.operations_contracts import derive_cycle_id

ANCHOR = "2026-01-01T00:00:00Z"


def test_slot_for_ordinal_zero_is_the_anchor() -> None:
    slot = slot_for_ordinal(ANCHOR, TWICE_DAILY_CADENCE_SECONDS, 0)
    assert slot.scheduled_for == ANCHOR
    assert slot.next_scheduled_for == "2026-01-01T12:00:00Z"
    assert slot.completion_window_ends_at == "2026-01-01T12:00:00Z"
    assert slot.slot_ordinal == 0


def test_slot_calculus_is_pure_utc_without_dst() -> None:
    slot = slot_for_ordinal("2026-03-28T00:00:00Z", TWICE_DAILY_CADENCE_SECONDS, 3)
    # DST transitions inside this window cannot shift the anchored UTC grid.
    assert slot.scheduled_for == "2026-03-29T12:00:00Z"
    assert slot.next_scheduled_for == "2026-03-30T00:00:00Z"


def test_cycle_id_matches_operations_contract_identity() -> None:
    slot = slot_for_ordinal(ANCHOR, TWICE_DAILY_CADENCE_SECONDS, 2)
    assert slot.cycle_id(
        "fixture-local", "discovery", "fixture-policy-v1"
    ) == derive_cycle_id(
        "fixture-local", "discovery", "2026-01-02T00:00:00Z", "fixture-policy-v1"
    )


def test_slot_document_is_a_frozen_terminal_receipt_slot() -> None:
    slot = slot_for_ordinal(ANCHOR, TWICE_DAILY_CADENCE_SECONDS, 1)
    assert slot.slot_document() == {
        "anchorUtc": ANCHOR,
        "cadenceSeconds": TWICE_DAILY_CADENCE_SECONDS,
        "slotOrdinal": 1,
        "scheduledFor": "2026-01-01T12:00:00Z",
        "nextScheduledFor": "2026-01-02T00:00:00Z",
        "completionWindowEndsAt": "2026-01-02T00:00:00Z",
        "catchUpDisposition": "scheduled",
        "missedSlotCount": 0,
    }


def test_slot_at_floors_to_the_most_recent_slot() -> None:
    slot = slot_at(ANCHOR, TWICE_DAILY_CADENCE_SECONDS, "2026-01-02T17:59:59Z")
    assert slot.slot_ordinal == 3
    assert slot.scheduled_for == "2026-01-02T12:00:00Z"


def test_slot_at_exact_boundary_returns_that_slot() -> None:
    slot = slot_at(ANCHOR, TWICE_DAILY_CADENCE_SECONDS, "2026-01-02T12:00:00Z")
    assert slot.slot_ordinal == 3


@pytest.mark.parametrize("ordinal", [-1, -100])
def test_negative_ordinals_are_rejected(ordinal: int) -> None:
    with pytest.raises(ScheduleSlotError):
        slot_for_ordinal(ANCHOR, TWICE_DAILY_CADENCE_SECONDS, ordinal)


@pytest.mark.parametrize("cadence", [0, -1, "43200", 43_200.5])
def test_non_positive_or_non_integer_cadence_is_rejected(cadence) -> None:
    with pytest.raises(ScheduleSlotError):
        slot_for_ordinal(ANCHOR, cadence, 0)


@pytest.mark.parametrize(
    "bad", ["2026-01-01 00:00:00", "2026-01-01T00:00:00+00:00", 0, None]
)
def test_malformed_utc_strings_are_rejected(bad) -> None:
    with pytest.raises(ScheduleSlotError):
        slot_for_ordinal(bad, TWICE_DAILY_CADENCE_SECONDS, 0)


def test_instant_before_anchor_is_rejected() -> None:
    with pytest.raises(ScheduleSlotError):
        slot_at(ANCHOR, TWICE_DAILY_CADENCE_SECONDS, "2025-12-31T23:59:59Z")
