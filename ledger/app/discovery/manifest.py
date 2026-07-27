"""Fixture-root manifest loading for the deterministic discovery controller.

A discovery fixture root is the complete versioned input to one DSC-01 run::

    fixture-root/
        manifest.json           discovery-run-manifest-v1 run parameters
        coverage-universe.json  coverage-universe-v1 payload
        targets/*.json          discovery-target-v1 payloads
        connectors/             connector-specific fixture bytes (DSC-02)

The loader is fail-closed: every payload passes the COV-02 semantic
validators, cross-references resolve exactly, and every configured universe
benchmark is covered by at least one declared target so denominators are
never silently incomplete.  Loading performs no network, clock, database, or
environment access and reads nothing outside the fixture root.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
import stat
from typing import Any

from app.schemas.coverage_contracts import (
    CoverageContractError,
    validate_coverage_universe,
    validate_discovery_target,
)
from app.schemas.operations_contracts import (
    OperationsContractError,
    scheduled_slot_utc,
)


class DiscoveryManifestError(ValueError):
    """Raised when a discovery fixture manifest is incomplete or contradictory."""


MANIFEST_POLICY_VERSION = "discovery-run-manifest-v1"
DISCOVERY_LANE = "discovery"
FIXTURE_MODE = "synthetic_fixture"

_MANIFEST_KEYS = {
    "schemaVersion",
    "policyVersion",
    "environment",
    "lane",
    "schedulePolicyRevisionId",
    "anchorUtc",
    "cadenceSeconds",
    "mode",
}
_STABLE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")


@dataclass(frozen=True, slots=True)
class DiscoveryManifest:
    """One fully validated, deterministic discovery run input."""

    environment: str
    lane: str
    schedule_policy_revision_id: str
    anchor_utc: str
    cadence_seconds: int
    mode: str
    universe: dict[str, Any]
    targets: tuple[dict[str, Any], ...]

    @property
    def configured_benchmark_ids(self) -> frozenset[str]:
        return frozenset(
            benchmark["benchmarkId"]
            for benchmark in self.universe["benchmarks"]
            if benchmark["coverageStatus"] == "configured"
        )


def _fail(message: str) -> None:
    raise DiscoveryManifestError(message)


def _stable_id(value: Any, field: str) -> str:
    if type(value) is not str or _STABLE_ID.fullmatch(value) is None:
        _fail(f"manifest.json: {field} must be a stable lowercase identifier")
    return value


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        _fail(f"{label}: cannot read {path.name}: {exc.strerror or exc}")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        _fail(f"{label}: {path.name} is not valid JSON: {exc}")
    if type(payload) is not dict:
        _fail(f"{label}: {path.name} top level must be a JSON object")
    return payload


def _load_run_parameters(root: Path) -> tuple[str, str, str, str, int, str]:
    payload = _read_json(root / "manifest.json", "run manifest")
    keys = set(payload)
    if keys != _MANIFEST_KEYS:
        missing = sorted(_MANIFEST_KEYS - keys)
        extra = sorted(keys - _MANIFEST_KEYS)
        parts = []
        if missing:
            parts.append(f"missing keys {missing}")
        if extra:
            parts.append(f"unexpected keys {extra}")
        _fail(f"manifest.json: {'; '.join(parts)}")
    if payload["schemaVersion"] != "1.0.0":
        _fail("manifest.json: schemaVersion must be '1.0.0'")
    if payload["policyVersion"] != MANIFEST_POLICY_VERSION:
        _fail(f"manifest.json: policyVersion must be {MANIFEST_POLICY_VERSION!r}")
    environment = _stable_id(payload["environment"], "environment")
    lane = _stable_id(payload["lane"], "lane")
    if lane != DISCOVERY_LANE:
        _fail("manifest.json: DSC-01 runs only the discovery lane")
    policy_revision = _stable_id(
        payload["schedulePolicyRevisionId"], "schedulePolicyRevisionId"
    )
    mode = payload["mode"]
    if mode != FIXTURE_MODE:
        _fail(
            f"manifest.json: mode must be {FIXTURE_MODE!r}; "
            "live scheduler modes are outside the fixture-only boundary"
        )
    cadence = payload["cadenceSeconds"]
    if type(cadence) is not int or cadence < 1:
        _fail("manifest.json: cadenceSeconds must be a positive integer")
    anchor = payload["anchorUtc"]
    try:
        canonical_anchor = scheduled_slot_utc(anchor, cadence, 0)
    except (OperationsContractError, ValueError) as exc:
        _fail(f"manifest.json: anchorUtc is not canonical UTC: {exc}")
    if canonical_anchor != anchor:
        _fail("manifest.json: anchorUtc must be canonical UTC YYYY-MM-DDTHH:MM:SSZ")
    return environment, lane, policy_revision, anchor, cadence, mode


def load_manifest(fixture_root: Path) -> DiscoveryManifest:
    """Load and fully validate one discovery fixture root, fail closed."""

    root = Path(fixture_root)
    try:
        metadata = root.lstat()
    except OSError:
        _fail("fixture root must be an existing directory")
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        _fail("fixture root must be a regular directory, not a link or file")

    environment, lane, policy_revision, anchor, cadence, mode = _load_run_parameters(root)

    universe = _read_json(root / "coverage-universe.json", "coverage universe")
    try:
        validate_coverage_universe(universe)
    except CoverageContractError as exc:
        _fail(f"coverage-universe.json failed semantic validation: {exc}")

    targets_dir = root / "targets"
    try:
        targets_metadata = targets_dir.lstat()
    except OSError:
        _fail("targets/ directory is required for an explicit target denominator")
    if stat.S_ISLNK(targets_metadata.st_mode) or not stat.S_ISDIR(targets_metadata.st_mode):
        _fail("targets/ must be a regular directory")

    targets: list[dict[str, Any]] = []
    for path in sorted(targets_dir.glob("*.json")):
        payload = _read_json(path, "discovery target")
        try:
            validate_discovery_target(payload)
        except CoverageContractError as exc:
            _fail(f"targets/{path.name} failed semantic validation: {exc}")
        targets.append(payload)

    seen_revisions: set[str] = set()
    seen_target_ids: set[str] = set()
    for target in targets:
        revision_id = target["targetRevisionId"]
        target_id = target["targetId"]
        if revision_id in seen_revisions:
            _fail(f"duplicate targetRevisionId {revision_id!r} across targets/")
        if target_id in seen_target_ids:
            _fail(f"duplicate targetId {target_id!r} across targets/")
        seen_revisions.add(revision_id)
        seen_target_ids.add(target_id)

    universe_benchmark_ids = {
        benchmark["benchmarkId"] for benchmark in universe["benchmarks"]
    }
    covered: set[str] = set()
    for target in targets:
        for benchmark_id in target["affectedBenchmarkIds"]:
            if benchmark_id not in universe_benchmark_ids:
                _fail(
                    f"target {target['targetRevisionId']!r} affects unknown "
                    f"universe benchmark {benchmark_id!r}"
                )
            covered.add(benchmark_id)

    configured = {
        benchmark["benchmarkId"]
        for benchmark in universe["benchmarks"]
        if benchmark["coverageStatus"] == "configured"
    }
    uncovered = sorted(configured - covered)
    if uncovered:
        _fail(
            f"configured universe benchmarks have no discovery target: {uncovered}; "
            "uncovered denominators must be explicit universe omissions"
        )

    return DiscoveryManifest(
        environment=environment,
        lane=lane,
        schedule_policy_revision_id=policy_revision,
        anchor_utc=anchor,
        cadence_seconds=cadence,
        mode=mode,
        universe=universe,
        targets=tuple(sorted(targets, key=lambda item: item["targetRevisionId"])),
    )


__all__ = [
    "DISCOVERY_LANE",
    "FIXTURE_MODE",
    "MANIFEST_POLICY_VERSION",
    "DiscoveryManifest",
    "DiscoveryManifestError",
    "load_manifest",
]
