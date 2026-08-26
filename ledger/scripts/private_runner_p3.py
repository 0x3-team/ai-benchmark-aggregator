"""Fail-closed P3 private-runner candidate.

This module deliberately contains the exact live dependency composition that a
future H4 lease-fenced recheck executor must receive. It has no default live
entrypoint: H4 does not yet bind a scheduled job attempt, source receipt, and
terminal cycle to ingestion, so running it now would create an unaccounted
claim path and make a DATA-10 checkpoint semantically invalid.
"""

from __future__ import annotations

import os
from pathlib import Path
import stat
import subprocess
import sys

from app.db.migrate import DatabaseMigrationError, initialize_database, inspect_database
from app.ingestion.live_transport import PinnedHTTPSFetchTransport
from app.ingestion.runner import run_ingestion
from app.runtime.dependencies import (
    RateLimiter,
    RuntimeCapability,
    RuntimeDependencies,
)


class PrivateRunnerBlockedError(RuntimeError):
    """Raised before the candidate can contact the database or a source."""


class DenyAllP3RateLimiter:
    """Inert-only limiter that rejects before any transport request."""

    def acquire(self, *, source_id: str, url: str, observed_at: object) -> None:
        _ = source_id, url, observed_at
        raise PrivateRunnerBlockedError(
            "H4_BLOCKED: inert private-runner composition refuses every fetch request."
        )


def pinned_network_dependencies(*, rate_limiter: RateLimiter) -> RuntimeDependencies:
    """Compose the only permitted future live-fetch dependency bundle.

    Calling this function itself performs no request. The explicit capability
    means a future H4 executor cannot accidentally substitute the ordinary
    disabled transport when it receives this bundle.
    """

    return RuntimeDependencies(
        fetch_transport=PinnedHTTPSFetchTransport(),
        rate_limiter=rate_limiter,
        capabilities=frozenset({RuntimeCapability.NETWORK_FETCH}),
    )


def verify_fresh_or_current_database(database_url: str) -> None:
    """Initialize only an empty database, then require an integrity-clean head.

    This intentionally does not call either legacy-copy migration or the
    PostgreSQL in-place upgrade path. H4 may use this only for a fresh target
    or a database that is already at the exact supported head.
    """

    try:
        status = inspect_database(database_url)
        if status.kind == "empty":
            initialize_database(database_url)
            status = inspect_database(database_url)
    except DatabaseMigrationError as exc:
        raise PrivateRunnerBlockedError(
            "DATABASE_UNSUPPORTED: database inspection or fresh initialization failed closed."
        ) from exc
    if (
        status.kind != "current"
        or not status.integrity_ok
        or status.foreign_key_violations != 0
    ):
        raise PrivateRunnerBlockedError(
            "DATABASE_UNSUPPORTED: only a fresh or integrity-clean current database is allowed."
        )


def ingest_certified_sources(session: object, *, rate_limiter: RateLimiter) -> object:
    """Future H4 call site: admission still rejects every uncertified revision."""

    return run_ingestion(
        session,  # type: ignore[arg-type]
        dependencies=pinned_network_dependencies(rate_limiter=rate_limiter),
    )


def _require_h4_execution_bridge() -> None:
    raise PrivateRunnerBlockedError(
        "H4_BLOCKED: no reviewed lease-fenced source-recheck executor binds "
        "ingestion to a scheduled job attempt, source receipt, terminal cycle, "
        "and DATA-10 checkpoint. Refusing unbound ingestion, database access, "
        "migration, snapshot persistence, or checkpoint creation."
    )


_ALLOWED_ARTIFACT_PREFIXES = ("snapshots/", "recovery/checkpoints/")


def _data_repository_root(data_dir: Path) -> Path:
    """Require the supplied directory itself to be one physical Git worktree."""

    candidate = data_dir.resolve(strict=True)
    if not candidate.is_dir() or candidate.is_symlink():
        raise PrivateRunnerBlockedError("DATA_REPOSITORY_CONTAINMENT: data directory is invalid.")
    try:
        root = subprocess.run(
            ["git", "-C", str(candidate), "rev-parse", "--show-toplevel"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except subprocess.CalledProcessError as exc:
        raise PrivateRunnerBlockedError(
            "DATA_REPOSITORY_CONTAINMENT: data directory is not a Git worktree."
        ) from exc
    if Path(root).resolve(strict=True) != candidate:
        raise PrivateRunnerBlockedError(
            "DATA_REPOSITORY_CONTAINMENT: data directory must be the worktree root."
        )
    return candidate


def _artifact_path(root: Path, raw_path: bytes) -> Path:
    """Resolve one Git status path only when it is a contained artifact path."""

    path = raw_path.decode("utf-8", "surrogateescape")
    if not path or os.path.isabs(path) or "\\" in path:
        raise PrivateRunnerBlockedError("DATA_REPOSITORY_CONTAINMENT: artifact path is invalid.")
    parts = Path(path).parts
    if not parts or any(part in {"", ".", "..", ".git", ".gitmodules"} for part in parts):
        raise PrivateRunnerBlockedError("DATA_REPOSITORY_CONTAINMENT: artifact path escapes its root.")
    if not path.startswith(_ALLOWED_ARTIFACT_PREFIXES):
        raise PrivateRunnerBlockedError(
            "DATA_REPOSITORY_CONTAINMENT: refusing a non-artifact data-repository change."
        )
    candidate = root.joinpath(*parts)
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise PrivateRunnerBlockedError(
            "DATA_REPOSITORY_CONTAINMENT: artifact path cannot be resolved safely."
        ) from exc
    if root not in resolved.parents:
        raise PrivateRunnerBlockedError("DATA_REPOSITORY_CONTAINMENT: artifact path escapes worktree.")
    return candidate


def _assert_regular_artifact(root: Path, raw_path: bytes) -> None:
    """Walk one new artifact without following links or accepting nested repos."""

    candidate = _artifact_path(root, raw_path)
    try:
        metadata = candidate.lstat()
    except OSError as exc:
        raise PrivateRunnerBlockedError(
            "DATA_REPOSITORY_CONTAINMENT: artifact path cannot be inspected safely."
        ) from exc
    if not candidate.is_file() or candidate.is_symlink() or metadata.st_nlink != 1:
        raise PrivateRunnerBlockedError(
            "DATA_REPOSITORY_CONTAINMENT: artifact must be one non-linked regular file."
        )
    parent = candidate.parent
    while parent != root:
        try:
            parent_metadata = parent.lstat()
        except OSError as exc:
            raise PrivateRunnerBlockedError(
                "DATA_REPOSITORY_CONTAINMENT: artifact parent cannot be inspected safely."
            ) from exc
        if parent.is_symlink() or not parent.is_dir() or (parent / ".git").exists():
            raise PrivateRunnerBlockedError(
                "DATA_REPOSITORY_CONTAINMENT: symlink or nested repository in artifact path."
            )
        _ = parent_metadata
        parent = parent.parent


def _walk_artifact_roots(root: Path) -> None:
    """Reject metadata, links, and special files Git might omit from status."""

    for relative_root in ("snapshots", "recovery/checkpoints"):
        artifact_root = root / relative_root
        if not artifact_root.exists() and not artifact_root.is_symlink():
            continue
        metadata = artifact_root.lstat()
        if artifact_root.is_symlink() or not stat.S_ISDIR(metadata.st_mode):
            raise PrivateRunnerBlockedError(
                "DATA_REPOSITORY_CONTAINMENT: artifact root is not a regular directory."
            )
        for directory, dirnames, filenames in os.walk(artifact_root, followlinks=False):
            current = Path(directory)
            for name in [*dirnames, *filenames]:
                if name in {".git", ".gitmodules"}:
                    raise PrivateRunnerBlockedError(
                        "DATA_REPOSITORY_CONTAINMENT: Git metadata is forbidden in artifact paths."
                    )
                child = current / name
                child_metadata = child.lstat()
                if child.is_symlink():
                    raise PrivateRunnerBlockedError(
                        "DATA_REPOSITORY_CONTAINMENT: symlink in artifact tree."
                    )
                if name in dirnames and not stat.S_ISDIR(child_metadata.st_mode):
                    raise PrivateRunnerBlockedError(
                        "DATA_REPOSITORY_CONTAINMENT: artifact directory is not a regular directory."
                    )
                if name in filenames and not stat.S_ISREG(child_metadata.st_mode):
                    raise PrivateRunnerBlockedError(
                        "DATA_REPOSITORY_CONTAINMENT: artifact is not a regular file."
                    )


def _status_entries(root: Path) -> list[bytes]:
    completed = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain=v1", "--untracked-files=all", "-z"],
        check=True,
        capture_output=True,
    )
    return [entry for entry in completed.stdout.split(b"\0") if entry]


def _assert_allowed_data_changes(data_dir: Path, *, staged: bool) -> None:
    """Reject every tracked change and admit only new, regular artifact files."""

    root = _data_repository_root(data_dir)
    _walk_artifact_roots(root)
    entries = _status_entries(root)
    if not entries:
        return
    for entry in entries:
        if len(entry) < 4:
            raise PrivateRunnerBlockedError("Data repository status entry is malformed.")
        state = entry[:2]
        raw_path = entry[3:]
        if not staged and state == b"??":
            _assert_regular_artifact(root, raw_path)
            continue
        if staged and state == b"A ":
            _assert_regular_artifact(root, raw_path)
            index = subprocess.run(
                ["git", "-C", str(root), "ls-files", "--stage", "--", raw_path.decode("utf-8", "surrogateescape")],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.splitlines()
            if len(index) != 1 or not index[0].startswith("100644 "):
                raise PrivateRunnerBlockedError(
                    "DATA_REPOSITORY_CONTAINMENT: staged artifact is not a regular file."
                )
            continue
        if state != b"??" or staged:
            raise PrivateRunnerBlockedError(
                "DATA_REPOSITORY_CONTAINMENT: refusing a tracked, non-additive, or unstaged change."
            )


def main(argv: list[str]) -> int:
    if argv == ["run"]:
        # Check the explicit composition is still constructible before H4 is
        # authorized. This is local object construction only: no DNS, network,
        # storage, database, migration, ingestion, or checkpoint operation.
        pinned_network_dependencies(rate_limiter=DenyAllP3RateLimiter())
        _require_h4_execution_bridge()
    if len(argv) == 3 and argv[0] == "assert-data-repo" and argv[1] in {"pre-add", "staged-adds"}:
        _assert_allowed_data_changes(Path(argv[2]), staged=argv[1] == "staged-adds")
        return 0
    raise PrivateRunnerBlockedError(
        "Usage: private_runner_p3.py run | assert-data-repo {pre-add|staged-adds} <directory>"
    )


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except PrivateRunnerBlockedError as exc:
        # Never echo source data, secret-bearing environment values, database
        # locators, or data-repository paths.
        print(str(exc), file=sys.stderr)
        raise SystemExit(2) from None
