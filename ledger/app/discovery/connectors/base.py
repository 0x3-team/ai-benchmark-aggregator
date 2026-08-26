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
import os
from pathlib import Path
import stat
from typing import Any, Mapping, Protocol, runtime_checkable

from app.discovery.candidates import CandidateAssemblyError, assemble_candidate
from app.discovery.fixture_io import FixtureInputError, read_json_object_at
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


# Bounded loading budget for the single ``connectors/static.json`` leaf.
MAX_STATIC_FIXTURE_BYTES = 8 * 1024 * 1024
MAX_STATIC_JSON_DEPTH = 64
MAX_STATIC_JSON_NODES = 100_000
# ``targets`` object shape caps, enforced for the whole file before assembly.
MAX_STATIC_TARGET_ENTRIES = 512
MAX_STATIC_CANDIDATES_PER_TARGET = 1_000
MAX_STATIC_CANDIDATE_SPECS = 10_000

_TARGET_ENTRY_KEYS = frozenset({"candidates", "reviewRequired"})


def _fail(reason_code: str, detail: str) -> ConnectorError:
    """Build a stable redacted :class:`ConnectorError` carrying only the code."""
    return ConnectorError(reason_code, detail)


def _supports_dir_descriptors() -> bool:
    return hasattr(os, "O_NOFOLLOW") and hasattr(os, "O_DIRECTORY")


def _require_descriptor(path: Path) -> int:
    """Open the fixture root as a no-follow ``O_DIRECTORY`` descriptor.

    ``lstat`` rejects a symlink or non-directory up front, and the subsequent
    ``os.open`` with ``O_NOFOLLOW | O_DIRECTORY`` commits to the exact
    directory inode at hand, so every later read is anchored there instead of
    to whatever the path later names.
    """

    if not _supports_dir_descriptors():
        raise _fail(
            "STATIC_FIXTURE_UNREADABLE",
            "no-follow directory-descriptor support is required",
        )
    try:
        metadata = path.lstat()
    except OSError:
        raise _fail("STATIC_FIXTURE_UNREADABLE", "fixture root must exist")
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise _fail(
            "STATIC_FIXTURE_UNREADABLE",
            "fixture root must be a directory, not a link or file",
        )
    try:
        return os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError:
        raise _fail("STATIC_FIXTURE_UNREADABLE", "fixture root could not be opened")


def _open_connectors(root_fd: int) -> int:
    """Open the ``connectors`` subdirectory relative to the root, no-follow."""

    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    flags |= getattr(os, "O_CLOEXEC", 0)
    try:
        return os.open("connectors", flags, dir_fd=root_fd)
    except OSError:
        raise _fail("STATIC_FIXTURE_UNREADABLE", "connectors/ must not be a symlink")


def _read_static(connectors_fd: int) -> dict[str, Any]:
    """Read ``static.json`` relative to the ``connectors`` descriptor, bounded.

    Maps any :class:`FixtureInputError` to a stable redacted
    :class:`ConnectorError` carrying only the stable ``reason_code`` — never
    raw OS/JSON/decoder text.
    """

    try:
        return read_json_object_at(
            connectors_fd,
            "static.json",
            max_bytes=MAX_STATIC_FIXTURE_BYTES,
            max_depth=MAX_STATIC_JSON_DEPTH,
            max_nodes=MAX_STATIC_JSON_NODES,
        )
    except FixtureInputError as exc:
        raise _fail("STATIC_FIXTURE_UNREADABLE", exc.reason_code)


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

        root = Path(fixture_root)
        root_fd = _require_descriptor(root)
        connectors_fd = None
        try:
            connectors_fd = _open_connectors(root_fd)
            payload = _read_static(connectors_fd)
        finally:
            if connectors_fd is not None:
                try:
                    os.close(connectors_fd)
                except OSError:
                    pass
            try:
                os.close(root_fd)
            except OSError:
                pass

        if type(payload) is not dict or set(payload) != {"targets"}:
            raise _fail("STATIC_FIXTURE_MALFORMED", "top level must be {'targets'}")
        entries = payload["targets"]
        if type(entries) is not dict:
            raise _fail("STATIC_FIXTURE_MALFORMED", "'targets' must be an object")

        # Whole-file validation/count pass runs for the entire file before any
        # assembly: every target entry is shape-validated and every candidate
        # count is accumulated, fail fast, against all three caps.
        if len(entries) > MAX_STATIC_TARGET_ENTRIES:
            raise _fail(
                "STATIC_FIXTURE_TOO_MANY_TARGETS",
                f"more than {MAX_STATIC_TARGET_ENTRIES} target entries",
            )
        total_specs = 0
        for rev, entry in entries.items():
            if type(entry) is not dict or set(entry) != _TARGET_ENTRY_KEYS:
                raise _fail(
                    "STATIC_FIXTURE_MALFORMED",
                    f"{rev}: entry must contain exactly 'candidates' and 'reviewRequired'",
                )
            if type(entry["reviewRequired"]) is not bool:
                raise _fail(
                    "STATIC_FIXTURE_MALFORMED",
                    f"{rev}: 'reviewRequired' must be a boolean",
                )
            specs = entry["candidates"]
            if type(specs) is not list:
                raise _fail(
                    "STATIC_FIXTURE_MALFORMED",
                    f"{rev}: 'candidates' must be an array",
                )
            if len(specs) > MAX_STATIC_CANDIDATES_PER_TARGET:
                raise _fail(
                    "STATIC_FIXTURE_TOO_MANY_CANDIDATES",
                    f"{rev}: more than {MAX_STATIC_CANDIDATES_PER_TARGET} candidates",
                )
            total_specs += len(specs)
            if total_specs > MAX_STATIC_CANDIDATE_SPECS:
                raise _fail(
                    "STATIC_FIXTURE_TOO_MANY_CANDIDATES",
                    f"more than {MAX_STATIC_CANDIDATE_SPECS} candidate specs in total",
                )

        entry = entries.get(revision_id)
        if entry is None:
            raise ConnectorError("MISSING_FIXTURE_OBSERVATION", revision_id)
        try:
            candidates = tuple(
                assemble_candidate(revision_id, spec) for spec in entry["candidates"]
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
    "MAX_STATIC_FIXTURE_BYTES",
    "MAX_STATIC_JSON_DEPTH",
    "MAX_STATIC_JSON_NODES",
    "MAX_STATIC_TARGET_ENTRIES",
    "MAX_STATIC_CANDIDATES_PER_TARGET",
    "MAX_STATIC_CANDIDATE_SPECS",
]
