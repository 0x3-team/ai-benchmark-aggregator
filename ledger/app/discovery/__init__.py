"""Fixture-only discovery engine (DSC-01).

The discovery lane plans twice-daily deterministic cycles over versioned
Coverage Universe/target manifests, records every target's terminal
planner disposition, runs bounded connectors against fixture bytes, and
persists quarantined ``discovery-candidate-v1`` proposals idempotently.
It holds no certification, capture, publication, or network authority.
"""

from app.discovery.controller import (
    CycleRunReport,
    DiscoveryControllerError,
    TargetRunRecord,
    build_fixture_connectors,
    run_discovery_cycle,
)
from app.discovery.manifest import (
    DiscoveryManifest,
    DiscoveryManifestError,
    load_manifest,
)
from app.discovery.planner import (
    DiscoveryPlannerError,
    TargetDisposition,
    parse_cadence_seconds,
    plan_dispositions,
)
from app.discovery.reporting import build_discovery_status, render_status_markdown

__all__ = [
    "CycleRunReport",
    "DiscoveryControllerError",
    "DiscoveryManifest",
    "DiscoveryManifestError",
    "DiscoveryPlannerError",
    "TargetDisposition",
    "TargetRunRecord",
    "build_discovery_status",
    "build_fixture_connectors",
    "load_manifest",
    "parse_cadence_seconds",
    "plan_dispositions",
    "render_status_markdown",
    "run_discovery_cycle",
]
