"""Builders for deterministic DSC-01 discovery fixture roots.

Payloads start from the checked-in ``docs/contracts/examples`` documents and
are re-signed after every mutation, so fixtures always satisfy the COV-02
semantic validators.  Nothing here is importable by runtime code.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.schemas.coverage_contracts import contract_self_digest


EXAMPLES = Path(__file__).resolve().parents[2] / "docs" / "contracts" / "examples"

DEFAULT_ANCHOR = "2026-01-01T00:00:00Z"
DEFAULT_CADENCE_SECONDS = 43_200
DEFAULT_ENVIRONMENT = "fixture-local"
DEFAULT_POLICY_REVISION = "fixture-schedule-policy-v1"
HOST = "benchmarks.example.org"


def _example(name: str) -> dict[str, Any]:
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


def build_universe(
    benchmark_ids: tuple[str, ...] = ("example_benchmark",),
    *,
    omitted: tuple[str, ...] = (),
) -> dict[str, Any]:
    payload = _example("coverage-universe-v1.valid.json")
    configured = [item for item in benchmark_ids if item not in omitted]
    payload["benchmarks"] = [
        {
            "benchmarkId": benchmark_id,
            "coverageStatus": "omitted" if benchmark_id in omitted else "configured",
            "reasonCode": (
                "EXAMPLE_UNIVERSE_OMISSION"
                if benchmark_id in omitted
                else "EXAMPLE_REGISTRY_MEMBER"
            ),
            "cohortIds": ["example-cohort"],
        }
        for benchmark_id in benchmark_ids
    ]
    payload["cohorts"][0]["memberBenchmarkIds"] = list(benchmark_ids)
    payload["configuredSourceRoutes"] = [
        {
            "sourceRouteId": f"route_{benchmark_id}",
            "benchmarkId": benchmark_id,
            "registryStatus": "active",
            "coverageStatus": "configured",
            "reasonCode": "EXAMPLE_CONFIGURED_ROUTE",
        }
        for benchmark_id in configured
    ]
    payload["manifest"]["benchmarkCount"] = len(benchmark_ids)
    payload["manifest"]["configuredSourceRouteCount"] = len(configured)
    payload["manifest"]["contentSha256"] = contract_self_digest(payload)
    return payload


def build_target(
    target_revision_id: str,
    *,
    benchmark_ids: tuple[str, ...] = ("example_benchmark",),
    status: str = "configured",
    cadence: str = "PT12H",
    connector_id: str = "static-fixture",
) -> dict[str, Any]:
    payload = _example("discovery-target-v1.valid.json")
    payload["targetRevisionId"] = target_revision_id
    payload["targetId"] = f"{target_revision_id}-root"
    payload["configurationStatus"] = status
    payload["affectedBenchmarkIds"] = list(benchmark_ids)
    payload["manifest"]["affectedBenchmarkCount"] = len(benchmark_ids)
    payload["duePolicy"]["cadence"] = cadence
    payload["connector"]["connectorId"] = connector_id
    if status == "configured":
        payload["decisionReference"] = "target-decision-example-v1"
        payload["reasonCode"] = "EXAMPLE_RECONNAISSANCE_APPROVED"
        payload["authority"]["approvalStatus"] = "reconnaissance_approved"
        payload["authority"]["permitsCandidateReconnaissance"] = True
        payload["termsReview"]["status"] = "reviewed_for_reconnaissance"
        payload["termsReview"]["reasonCode"] = "EXAMPLE_TERMS_REVIEWED"
    elif status == "blocked_terms":
        payload["termsReview"]["status"] = "blocked_terms"
    elif status == "blocked_permission":
        payload["termsReview"]["status"] = "blocked_permission"
    payload["manifest"]["contentSha256"] = contract_self_digest(payload)
    return payload


def build_candidate_spec(
    source_id: str,
    *,
    benchmark_id: str = "example_benchmark",
    url_path: str = "/example/results.json",
) -> dict[str, Any]:
    url = f"https://{HOST}{url_path}"
    return {
        "candidateType": "source",
        "candidateIdentity": {
            "identityType": "source",
            "proposedSourceId": source_id,
            "benchmarkId": benchmark_id,
            "resultLocator": url,
        },
        "officialUrls": [url],
        "affectedBenchmarkIds": [benchmark_id],
        "owner": {
            "ownerId": "example-owner",
            "displayName": "Example benchmark owner",
            "officialRootUrls": [f"https://{HOST}/"],
        },
        "artifactHint": {
            "format": "json",
            "structured": True,
            "revisionKind": "content_digest",
            "revisionLocator": "fixture-revision-v1",
            "completenessHint": "complete",
            "parserHint": "generic_json",
        },
        "termsHint": {
            "status": "reviewed_for_reconnaissance",
            "evidenceUrl": f"https://{HOST}/example/terms/",
            "reasonCode": "EXAMPLE_TERMS_REVIEWED",
        },
        "reasonCode": "FIXTURE_CANDIDATE_OBSERVED",
        "evidenceReferences": [
            {
                "evidenceId": f"ev-{source_id}",
                "evidenceType": "discovery_observation",
                "locator": url,
                "contentSha256": None,
                "observationRevision": "fixture-revision-v1",
            }
        ],
    }


def write_manifest_root(
    root: Path,
    *,
    universe: dict[str, Any] | None = None,
    targets: dict[str, dict[str, Any]] | None = None,
    observations: dict[str, dict[str, Any]] | None = None,
    anchor: str = DEFAULT_ANCHOR,
    cadence_seconds: int = DEFAULT_CADENCE_SECONDS,
    environment: str = DEFAULT_ENVIRONMENT,
    policy_revision: str = DEFAULT_POLICY_REVISION,
    mode: str = "synthetic_fixture",
) -> Path:
    """Materialize one deterministic fixture root on disk."""

    if universe is None:
        universe = build_universe()
    if targets is None:
        targets = {"example-target-v1": build_target("example-target-v1")}
    root.mkdir(parents=True, exist_ok=True)
    (root / "targets").mkdir(exist_ok=True)
    manifest = {
        "schemaVersion": "1.0.0",
        "policyVersion": "discovery-run-manifest-v1",
        "environment": environment,
        "lane": "discovery",
        "schedulePolicyRevisionId": policy_revision,
        "anchorUtc": anchor,
        "cadenceSeconds": cadence_seconds,
        "mode": mode,
    }
    (root / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (root / "coverage-universe.json").write_text(
        json.dumps(universe, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    for revision_id, payload in targets.items():
        (root / "targets" / f"{revision_id}.json").write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    if observations is not None:
        (root / "connectors").mkdir(exist_ok=True)
        (root / "connectors" / "static.json").write_text(
            json.dumps({"targets": observations}, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return root


def standard_observations(*revision_ids: str) -> dict[str, dict[str, Any]]:
    """One candidate-bearing observation per target revision ID."""

    return {
        revision_id: {
            "candidates": [
                build_candidate_spec(f"{revision_id}-source"),
            ],
            "reviewRequired": False,
        }
        for revision_id in revision_ids
    }
