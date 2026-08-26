from __future__ import annotations

import json
import os
import shutil

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


def test_manifest_root_that_is_a_symlink_is_rejected(tmp_path) -> None:
    """A fixture root reached through a symbolic link must never be read through it."""
    real = write_manifest_root(tmp_path / "real")
    link = tmp_path / "fixture-link"
    os.symlink(real, link)
    with pytest.raises(DiscoveryManifestError, match="regular directory"):
        load_manifest(link)


def test_symlinked_manifest_payload_is_rejected(tmp_path) -> None:
    """A symlinked manifest.json must not redirect the load to attacker bytes."""
    root = write_manifest_root(tmp_path / "fx")
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    manifest_path = root / "manifest.json"
    manifest_path.unlink()
    os.symlink(outside, manifest_path)
    with pytest.raises(DiscoveryManifestError, match="manifest.json"):
        load_manifest(root)


def test_symlinked_universe_payload_is_rejected(tmp_path) -> None:
    """A symlinked coverage-universe.json must not redirect the universe."""
    root = write_manifest_root(tmp_path / "fx")
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    universe_path = root / "coverage-universe.json"
    universe_path.unlink()
    os.symlink(outside, universe_path)
    with pytest.raises(DiscoveryManifestError, match="coverage universe"):
        load_manifest(root)


def test_targets_directory_symlink_escape_is_rejected(tmp_path) -> None:
    """A symlinked targets/ directory must not escape the fixture root."""
    root = write_manifest_root(tmp_path / "fx")
    attacker_dir = tmp_path / "attacker-targets"
    attacker_dir.mkdir()
    (attacker_dir / "malicious.json").write_text("{}", encoding="utf-8")
    targets_path = root / "targets"
    shutil.rmtree(targets_path)
    os.symlink(attacker_dir, targets_path)
    with pytest.raises(DiscoveryManifestError, match="symbolic link"):
        load_manifest(root)


def test_symlinked_target_payload_is_rejected(tmp_path) -> None:
    """A per-target payload symlink must not re-read outside the targets denominator."""
    root = write_manifest_root(tmp_path / "fx")
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    target_path = root / "targets" / "example-target-v1.json"
    target_path.unlink()
    os.symlink(outside, target_path)
    with pytest.raises(DiscoveryManifestError, match="cannot read"):
        load_manifest(root)


def test_target_directory_reaches_a_subdirectory_missing_a_payload(tmp_path) -> None:
    """The no-follow denominator still requires at least one valid target payload."""
    root = write_manifest_root(tmp_path / "fx")
    (root / "targets" / "example-target-v1.json").unlink()
    nested = root / "targets" / "nested"
    nested.mkdir()
    (nested / "ignored.json").write_text("{}", encoding="utf-8")
    with pytest.raises(DiscoveryManifestError, match="no discovery target"):
        load_manifest(root)
