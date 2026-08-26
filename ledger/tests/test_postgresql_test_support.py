from __future__ import annotations

from pathlib import Path

import pytest

from postgresql_test_support import (
    REQUIRE_PROOF_ENV,
    proof_is_required,
    require_executable_paths,
    skip_or_fail,
)


def test_missing_postgresql_proof_skips_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(REQUIRE_PROOF_ENV, raising=False)

    with pytest.raises(pytest.skip.Exception, match="missing PostgreSQL URL"):
        skip_or_fail("missing PostgreSQL URL")


def test_missing_postgresql_proof_fails_when_ci_gate_is_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(REQUIRE_PROOF_ENV, "1")

    with pytest.raises(pytest.fail.Exception, match="PostgreSQL proof gate failed"):
        skip_or_fail("missing PostgreSQL URL")


@pytest.mark.parametrize("value", [None, "", "0", "true"])
def test_gate_requires_exact_ci_value(
    monkeypatch: pytest.MonkeyPatch,
    value: str | None,
) -> None:
    if value is None:
        monkeypatch.delenv(REQUIRE_PROOF_ENV, raising=False)
    else:
        monkeypatch.setenv(REQUIRE_PROOF_ENV, value)

    assert not proof_is_required()


def test_missing_postgresql_client_path_fails_when_ci_gate_is_enabled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv(REQUIRE_PROOF_ENV, "1")
    missing_path = tmp_path / "pg_dump"

    with pytest.raises(pytest.fail.Exception, match="executable PostgreSQL client paths"):
        require_executable_paths((missing_path,), context="recovery")
