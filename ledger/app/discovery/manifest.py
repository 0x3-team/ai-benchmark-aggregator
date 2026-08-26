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
import os
from pathlib import Path
import re
import stat
from typing import Any

from app.discovery.fixture_io import (
    FixtureBudget,
    FixtureInputError,
    read_json_object_at,
)
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

# Single fixture payload, decoded in isolation.
MAX_FIXTURE_JSON_BYTES = 8 * 1024 * 1024
MAX_FIXTURE_JSON_DEPTH = 64
MAX_FIXTURE_JSON_NODES = 100_000
# Entire fixture root (manifest + universe + targets) shared across one load.
MAX_FIXTURE_MANIFEST_BYTES = 32 * 1024 * 1024
MAX_FIXTURE_MANIFEST_NODES = 500_000
# targets/ directory shape: total entries and JSON leaves, both bounded first.
MAX_TARGET_DIRECTORY_ENTRIES = 512
MAX_TARGET_JSON_FILES = 512

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


def _require_descriptor_nofollow(root: Path) -> int:
    """Open the fixture root as a no-follow directory descriptor.

    ``Path.exists()``/``lstat()`` are pure time-of-check probes: a symlink can
    be swapped in afterwards, and every later ``Path.read_text()`` would follow
    it. ``os.open`` with ``O_NOFOLLOW | O_DIRECTORY`` commits to the exact
    directory inode at hand and returns a descriptor, so subsequent fixture
    reads are anchored here instead of to whatever the path later names.
    """

    if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
        raise DiscoveryManifestError(
            "discovery fixture loading requires no-follow directory-descriptor support."
        )
    try:
        metadata = root.lstat()
    except OSError:
        _fail("fixture root must be an existing directory")
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        _fail("fixture root must be a regular directory, not a link or file")
    try:
        return os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError:
        _fail("fixture root directory could not be opened safely")


def _open_no_follow_directory(parent_fd: int, name: str, label: str) -> int:
    """Open one fixture subdirectory by its root-relative name, no-follow.

    ``O_NOFOLLOW | O_DIRECTORY`` on an ``O_CLOEXEC`` child makes it impossible
    for a planted symlink to redirect the open to an attacker-chosen directory,
    and the resulting descriptor is valid even if the parent walk races a path
    swap.  The opened descriptor must still be a real directory, never a link.
    """

    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    try:
        descriptor = os.open(name, flags | os.O_CLOEXEC, dir_fd=parent_fd)
    except OSError:
        _fail(f"{label} directory is required and must not be a symbolic link")
    return descriptor


def _read_json(
    parent_fd: int, name: str, label: str, budget: FixtureBudget
) -> dict[str, Any]:
    """Read and parse one fixture payload relative to ``parent_fd``, bounded.

    Delegates to the shared :func:`read_json_object_at` helper so every per-file
    byte/depth/node cap and the shared :class:`FixtureBudget` are enforced during
    the read, and maps a :class:`FixtureInputError` to this module's stable
    :class:`DiscoveryManifestError` carrying only ``label``/``name`` and the
    stable ``reason_code`` — never raw decode/OS details.
    """

    try:
        return read_json_object_at(
            parent_fd,
            name,
            max_bytes=MAX_FIXTURE_JSON_BYTES,
            max_depth=MAX_FIXTURE_JSON_DEPTH,
            max_nodes=MAX_FIXTURE_JSON_NODES,
            budget=budget,
        )
    except FixtureInputError as exc:
        _fail(f"{label}: cannot read {name} ({exc.reason_code})")


def _load_run_parameters(
    root_fd: int, budget: FixtureBudget
) -> tuple[str, str, str, str, int, str]:
    payload = _read_json(root_fd, "manifest.json", "run manifest", budget)
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
    root_fd = _require_descriptor_nofollow(root)
    try:
        return _load_manifest_from_root(root_fd)
    finally:
        os.close(root_fd)


def _load_targets_from_directory(
    targets_fd: int, budget: FixtureBudget
) -> list[dict[str, Any]]:
    """Load every ``*.json`` payload in a no-follow ``targets/`` descriptor.

    The full directory is scanned exactly once under a closed
    ``with os.scandir(targets_fd)`` iterator: every entry (including ignored
    non-JSON names and subdirectories) counts toward
    ``MAX_TARGET_DIRECTORY_ENTRIES``, every ``.json`` leaf counts toward
    ``MAX_TARGET_JSON_FILES``, and only then are the collected JSON names sorted
    deterministically and decoded through the bounded shared-helper read.  The
    bounded name pass therefore runs entirely before any payload is read, so a
    malformed overflow JSON is never decoded once the entry caps are exceeded.
    Leaf regularity is enforced per-file inside :func:`read_json_object_at`
    (``stat.S_ISREG``); no ``entry.is_file`` probe is made here.
    """

    json_names: list[str] = []
    total_entries = 0
    try:
        with os.scandir(targets_fd) as scan:
            for entry in scan:
                total_entries += 1
                if total_entries > MAX_TARGET_DIRECTORY_ENTRIES:
                    _fail(
                        "targets/: directory has more than "
                        f"{MAX_TARGET_DIRECTORY_ENTRIES} entries"
                    )
                if entry.name.endswith(".json"):
                    json_names.append(entry.name)
                    if len(json_names) > MAX_TARGET_JSON_FILES:
                        _fail(
                            "targets/: more than "
                            f"{MAX_TARGET_JSON_FILES} JSON payload files"
                        )
    except OSError:
        # Redact raw OS details; keep the descriptor context in the error.
        _fail("targets/: directory scan failed")

    targets: list[dict[str, Any]] = []
    for name in sorted(json_names):
        payload = _read_json(targets_fd, name, "discovery target", budget)
        try:
            validate_discovery_target(payload)
        except CoverageContractError as exc:
            _fail(f"targets/{name} failed semantic validation: {exc}")
        targets.append(payload)
    return targets


def _load_manifest_from_root(root_fd: int) -> DiscoveryManifest:
    """Validate a fixture root opened as one no-follow descriptor."""

    budget = FixtureBudget(
        max_bytes=MAX_FIXTURE_MANIFEST_BYTES,
        max_nodes=MAX_FIXTURE_MANIFEST_NODES,
    )

    environment, lane, policy_revision, anchor, cadence, mode = _load_run_parameters(
        root_fd, budget
    )

    universe = _read_json(root_fd, "coverage-universe.json", "coverage universe", budget)
    try:
        validate_coverage_universe(universe)
    except CoverageContractError as exc:
        _fail(f"coverage-universe.json failed semantic validation: {exc}")

    targets_fd = _open_no_follow_directory(root_fd, "targets", "targets/")
    try:
        targets = _load_targets_from_directory(targets_fd, budget)
    finally:
        os.close(targets_fd)

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
    "MAX_FIXTURE_JSON_BYTES",
    "MAX_FIXTURE_JSON_DEPTH",
    "MAX_FIXTURE_JSON_NODES",
    "MAX_FIXTURE_MANIFEST_BYTES",
    "MAX_FIXTURE_MANIFEST_NODES",
    "MAX_TARGET_DIRECTORY_ENTRIES",
    "MAX_TARGET_JSON_FILES",
    "DiscoveryManifest",
    "DiscoveryManifestError",
    "load_manifest",
]
