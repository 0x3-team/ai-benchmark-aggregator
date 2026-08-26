from __future__ import annotations

import pytest

from app.discovery.planner import (
    DiscoveryPlannerError,
    parse_cadence_seconds,
    plan_dispositions,
)
from app.scheduling.slots import slot_for_ordinal
from app.schemas.operations_contracts import (
    validate_scheduled_job_planner_disposition,
)
from discovery_fixtures import build_target

ANCHOR = "2026-01-01T00:00:00Z"
CADENCE = 43_200


def _slot(ordinal: int):
    return slot_for_ordinal(ANCHOR, CADENCE, ordinal)


@pytest.mark.parametrize(
    ("duration", "seconds"),
    [
        ("PT12H", 43_200),
        ("P1D", 86_400),
        ("P30D", 2_592_000),
        ("PT1H30M", 5_400),
        ("PT45S", 45),
        ("P2DT3H", 183_600),
    ],
)
def test_parse_cadence_seconds(duration: str, seconds: int) -> None:
    assert parse_cadence_seconds(duration) == seconds


@pytest.mark.parametrize(
    "bad", ["", "P", "PT", "12H", "PT0S", "P0D", "garbage", None, 43_200]
)
def test_parse_cadence_seconds_rejects_bad_durations(bad) -> None:
    with pytest.raises(DiscoveryPlannerError):
        parse_cadence_seconds(bad)


def test_configured_target_is_due_at_anchor_and_each_cadence_boundary() -> None:
    targets = (build_target("t-alpha-v1", cadence="PT12H"),)
    at_anchor = plan_dispositions(
        targets, anchor_utc=ANCHOR, cadence_seconds=CADENCE, slot=_slot(0)
    )
    assert [(item.due_disposition, item.disposition_reason_code) for item in at_anchor] == [
        ("due", "DUE_BY_SCHEDULE")
    ]
    later = plan_dispositions(
        targets, anchor_utc=ANCHOR, cadence_seconds=CADENCE, slot=_slot(5)
    )
    assert later[0].due_disposition == "due"


def test_daily_target_is_not_due_on_the_midday_slot() -> None:
    targets = (build_target("t-alpha-v1", cadence="P1D"),)
    midday = plan_dispositions(
        targets, anchor_utc=ANCHOR, cadence_seconds=CADENCE, slot=_slot(1)
    )
    assert [(midday[0].due_disposition, midday[0].disposition_reason_code)] == [
        ("not_due", "NOT_DUE_BY_POLICY")
    ]
    next_day = plan_dispositions(
        targets, anchor_utc=ANCHOR, cadence_seconds=CADENCE, slot=_slot(2)
    )
    assert next_day[0].due_disposition == "due"


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("draft", ("blocked", "SOURCE_POLICY_BLOCKED")),
        ("paused", ("blocked", "OPERATOR_PAUSED")),
        ("blocked_terms", ("blocked", "TERMS_POLICY_BLOCKED")),
        ("blocked_permission", ("blocked", "TERMS_POLICY_BLOCKED")),
        ("retired", ("not_due", "NOT_DUE_BY_POLICY")),
    ],
)
def test_non_configured_statuses_map_to_allowlisted_reasons(status, expected) -> None:
    targets = (build_target("t-alpha-v1", status=status),)
    plan = plan_dispositions(
        targets, anchor_utc=ANCHOR, cadence_seconds=CADENCE, slot=_slot(0)
    )
    assert [(plan[0].due_disposition, plan[0].disposition_reason_code)] == [expected]


def test_every_disposition_passes_the_operations_contract_allowlist() -> None:
    statuses = (
        "configured",
        "draft",
        "paused",
        "blocked_terms",
        "blocked_permission",
        "retired",
    )
    targets = tuple(
        build_target(f"t-{status}-v1", status=status) for status in statuses
    )
    plan = plan_dispositions(
        targets, anchor_utc=ANCHOR, cadence_seconds=CADENCE, slot=_slot(0)
    )
    assert len(plan) == len(statuses)
    for disposition in plan:
        validate_scheduled_job_planner_disposition(
            disposition.due_disposition, disposition.disposition_reason_code
        )


def test_slot_outside_the_manifest_policy_is_rejected() -> None:
    targets = (build_target("t-alpha-v1"),)
    foreign_slot = slot_for_ordinal("2026-02-01T00:00:00Z", CADENCE, 0)
    with pytest.raises(DiscoveryPlannerError):
        plan_dispositions(
            targets, anchor_utc=ANCHOR, cadence_seconds=CADENCE, slot=foreign_slot
        )
