"""Shared opt-in guard for PostgreSQL integration proof tests."""

from __future__ import annotations

import os
from pathlib import Path
from typing import NoReturn

import pytest


REQUIRE_PROOF_ENV = "LEDGER_REQUIRE_POSTGRESQL_PROOF"


def proof_is_required() -> bool:
    """Return whether CI must prove the real PostgreSQL path."""

    return os.environ.get(REQUIRE_PROOF_ENV) == "1"


def skip_or_fail(reason: str) -> NoReturn:
    """Skip locally, but fail when the CI proof contract is enabled."""

    if proof_is_required():
        pytest.fail(f"PostgreSQL proof gate failed: {reason}")
    pytest.skip(reason)


def require_executable_paths(paths: tuple[Path, ...], *, context: str) -> None:
    """Require fixed PostgreSQL client binaries when proof is configured."""

    missing = tuple(
        str(path)
        for path in paths
        if not path.is_file() or not os.access(path, os.X_OK)
    )
    if missing:
        skip_or_fail(
            f"{context} requires executable PostgreSQL client paths: "
            + ", ".join(missing)
        )
