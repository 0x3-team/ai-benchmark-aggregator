from __future__ import annotations

import json

import pytest

from app.discovery.manifest import DiscoveryManifestError, load_manifest
from app.schemas.coverage_contracts import contract_self_digest
from discovery_fixtures import build_target, build_universe, write_manifest_root


def test_valid_manifest_loads_sorted_targets(tmp_path) -> None:
    root = write_manifest_root(
        tmp_path / "fx",
        targets={
            "target-beta-v1": build_target("target-beta-v1"),
            "target-alpha-v1": build_target("target-alpha-v1"),
        },
    )
    manifest = load_manifest(root)
    assert [t["targetRevisionId"] for t in manifest.targets] == [
        "target-alpha-v1",
        "target-beta-v1",
    ]
    assert manifest.environment == "fixture-local"
    assert manifest.lane == "discovery"
    assert manifest.cadence_seconds == 43_200
    assert manifest.mode == "synthetic_fixture"
    assert manifest.configured_benchmark_ids == frozenset({"example_benchmark"})


def test_missing_fixture_root_fails_closed(tmp_path) -> None:
    with pytest.raises(DiscoveryManifestError):
        load_manifest(tmp_path / "absent")


def test_non_fixture_mode_is_rejected(tmp_path) -> None:
    root = write_manifest_root(tmp_path / "fx", mode="production")
    with pytest.raises(DiscoveryManifestError, match="synthetic_fixture"):
        load_manifest(root)


def test_unknown_benchmark_reference_is_rejected(tmp_path) -> None:
    root = write_manifest_root(
        tmp_path / "fx",
        targets={
            "target-alpha-v1": build_target(
                "target-alpha-v1", benchmark_ids=("ghost_benchmark",)
            )
        },
    )
    with pytest.raises(DiscoveryManifestError, match="unknown"):
        load_manifest(root)


def test_duplicate_target_revision_is_rejected(tmp_path) -> None:
    root = write_manifest_root(
        tmp_path / "fx",
        targets={"target-alpha-v1": build_target("target-alpha-v1")},
    )
    payload = build_target("target-alpha-v1")
    payload["targetId"] = "target-alpha-v1-other"
    payload["manifest"]["contentSha256"] = contract_self_digest(payload)
    (root / "targets" / "zzz-duplicate.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )
    with pytest.raises(DiscoveryManifestError, match="duplicate targetRevisionId"):
        load_manifest(root)


def test_uncovered_configured_benchmark_is_rejected(tmp_path) -> None:
    root = write_manifest_root(
        tmp_path / "fx",
        universe=build_universe(("example_benchmark", "second_benchmark")),
    )
    with pytest.raises(DiscoveryManifestError, match="no discovery target"):
        load_manifest(root)


def test_invalid_target_payload_is_rejected(tmp_path) -> None:
    root = write_manifest_root(tmp_path / "fx")
    target_path = root / "targets" / "example-target-v1.json"
    payload = json.loads(target_path.read_text(encoding="utf-8"))
    payload["budgets"]["maxRequestsPerRun"] = 0
    payload["manifest"]["contentSha256"] = contract_self_digest(payload)
    target_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(DiscoveryManifestError, match="semantic validation"):
        load_manifest(root)


def test_malformed_anchor_is_rejected(tmp_path) -> None:
    root = write_manifest_root(tmp_path / "fx", anchor="2026-01-01 00:00:00")
    with pytest.raises(DiscoveryManifestError, match="anchorUtc"):
        load_manifest(root)
