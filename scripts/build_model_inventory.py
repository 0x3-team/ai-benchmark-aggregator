#!/usr/bin/env python3
"""Build a review-only, source-hashed model inventory checkpoint."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml


UNAVAILABLE_ARTIFACT_KEYS = {
    "schemaVersion",
    "artifactKind",
    "artifactId",
    "availability",
    "policyVersion",
    "manifest",
    "reason",
    "models",
    "benchmarks",
    "sourceManifest",
    "scores",
}
UNAVAILABLE_MANIFEST_KEYS = {
    "algorithm",
    "contentSha256",
    "modelCount",
    "benchmarkCount",
    "sourceSnapshotCount",
    "scoreCount",
}
UNAVAILABLE_POLICY_VERSION = "official-release-artifact-v1"
CANONICAL_JSON_ALGORITHM = "sha256-canonical-json-v1"
LOWERCASE_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalize(value: object) -> str:
    return "".join(ch for ch in str(value).lower() if ch.isalnum())


def generated_at() -> str:
    source_date_epoch = os.environ.get("SOURCE_DATE_EPOCH")
    if source_date_epoch is None:
        now = datetime.now(timezone.utc)
    else:
        now = datetime.fromtimestamp(int(source_date_epoch), timezone.utc)
    return now.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def canonical_artifact_digest(artifact: dict) -> str:
    digest_input = {
        **artifact,
        "manifest": {**artifact["manifest"], "contentSha256": None},
    }
    canonical_json = json.dumps(
        digest_input,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def load_frontend_official_artifact(repo: Path) -> tuple[Path, dict, list[dict]]:
    path = repo / "src/data/official/export.unavailable.json"
    artifact = json.loads(path.read_text())
    if not isinstance(artifact, dict) or set(artifact) != UNAVAILABLE_ARTIFACT_KEYS:
        raise ValueError("frontend Official artifact has an invalid containment shape")
    if (
        artifact.get("schemaVersion") != "1.0.0"
        or artifact.get("artifactKind") != "official-release-artifact"
        or artifact.get("availability") != "unavailable"
        or not isinstance(artifact.get("artifactId"), str)
        or not artifact["artifactId"].strip()
    ):
        raise ValueError("frontend Official artifact is not the unavailable containment state")
    if artifact.get("policyVersion") != UNAVAILABLE_POLICY_VERSION:
        raise ValueError("frontend Official artifact has an unsupported policy version")
    if not isinstance(artifact.get("reason"), str) or not artifact["reason"].strip():
        raise ValueError("frontend Official artifact reason must be non-empty")
    manifest = artifact.get("manifest")
    if not isinstance(manifest, dict) or set(manifest) != UNAVAILABLE_MANIFEST_KEYS:
        raise ValueError("frontend Official artifact has an invalid containment manifest")
    if manifest.get("algorithm") != CANONICAL_JSON_ALGORITHM:
        raise ValueError("frontend Official artifact has an unsupported digest algorithm")
    content_sha256 = manifest.get("contentSha256")
    if not isinstance(content_sha256, str) or not LOWERCASE_SHA256.fullmatch(content_sha256):
        raise ValueError("frontend Official artifact has an invalid content digest")
    if any(
        manifest.get(key) != 0
        for key in ("modelCount", "benchmarkCount", "sourceSnapshotCount", "scoreCount")
    ):
        raise ValueError("frontend unavailable artifact manifest must contain zero records")
    for key in ("models", "benchmarks", "sourceManifest", "scores"):
        if artifact.get(key) != []:
            raise ValueError(f"frontend unavailable artifact {key} must be an empty array")
    if content_sha256 != canonical_artifact_digest(artifact):
        raise ValueError("frontend Official artifact digest does not match canonical content")
    return path, artifact, artifact["models"]


def main() -> int:
    if len(sys.argv) != 4:
        print("usage: build_model_inventory.py <openrouter.json> <huggingface.json> <output.json>", file=sys.stderr)
        return 2
    openrouter_path, huggingface_path, output_path = map(Path, sys.argv[1:])
    repo = Path.cwd()
    frontend_artifact_path, frontend_artifact, frontend_models = load_frontend_official_artifact(repo)
    registry_files = [
        repo / "ledger/app/registry/models.yaml",
        repo / "ledger/app/registry/models_frontier.yaml",
        repo / "ledger/app/registry/models_hf_seed.yaml",
    ]
    registry = []
    for path in registry_files:
        payload = yaml.safe_load(path.read_text()) or {}
        registry.extend({**row, "registryFile": str(path.relative_to(repo))} for row in payload.get("models", []))
    openrouter = (json.loads(openrouter_path.read_text()).get("data") or [])
    huggingface = json.loads(huggingface_path.read_text())
    candidates: dict[str, dict] = {}

    def add(kind: str, row: dict) -> None:
        identifier = str(row.get("id") or row.get("name") or row.get("modelId") or "")
        key = normalize(identifier)
        if not key:
            return
        item = candidates.setdefault(key, {
            "normalizedKey": key,
            "sourceKinds": [],
            "sourceIds": [],
            "registryIds": [],
            "providerIds": [],
            "disposition": "needs_review",
        })
        if kind not in item["sourceKinds"]:
            item["sourceKinds"].append(kind)
        if identifier not in item["sourceIds"]:
            item["sourceIds"].append(identifier)
        if kind == "registry" and identifier not in item["registryIds"]:
            item["registryIds"].append(identifier)
        if kind in {"openrouter", "huggingface"} and identifier not in item["providerIds"]:
            item["providerIds"].append(identifier)

    for row in registry:
        add("registry", row)
    for row in openrouter:
        add("openrouter", row)
    for row in huggingface:
        add("huggingface", row)

    candidates_list = [candidates[key] for key in sorted(candidates)]
    now = generated_at()
    output = {
        "schemaVersion": "model-inventory-checkpoint-v2",
        "generatedAt": now,
        "availability": "review_only",
        "runtimeMutation": False,
        "syntheticDataRemoved": True,
        "authority": "candidate_inventory_only",
        "counts": {
            "frontendOfficialArtifactModels": len(frontend_models),
            "registryRows": len(registry),
            "registryUniqueIds": len({row["id"] for row in registry}),
            "openRouterEntries": len(openrouter),
            "huggingFaceSampleEntries": len(huggingface),
            "normalizedCandidateKeys": len(candidates_list),
        },
        "sources": {
            "frontendOfficialArtifact": {
                "path": str(frontend_artifact_path.relative_to(repo)),
                "artifactId": frontend_artifact["artifactId"],
                "availability": frontend_artifact["availability"],
                "retrievedAt": now,
                "sha256": sha256(frontend_artifact_path),
                "count": len(frontend_models),
            },
            "registryFiles": [{"path": str(path.relative_to(repo)), "sha256": sha256(path), "rows": sum(1 for row in registry if row["registryFile"] == str(path.relative_to(repo)))} for path in registry_files],
            "openRouter": {"path": str(openrouter_path), "url": "https://openrouter.ai/api/v1/models", "retrievedAt": now, "sha256": sha256(openrouter_path), "count": len(openrouter)},
            "huggingFace": {"path": str(huggingface_path), "url": "https://huggingface.co/api/models?limit=100&sort=downloads&direction=-1", "retrievedAt": now, "sha256": sha256(huggingface_path), "count": len(huggingface)},
        },
        "dispositions": {"needsReview": len(candidates_list), "confirmed": 0, "deprecated": 0, "nonComparisonModel": 0, "syntheticFixture": 0},
        "candidates": candidates_list,
        "nextAction": "Reconcile canonical identities and classify scope before any runtime catalog or Official artifact mutation.",
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("x", encoding="utf-8") as handle:
        json.dump(output, handle, indent=2)
        handle.write("\n")
    print(json.dumps({"outputPath": str(output_path), "counts": output["counts"], "sha256": sha256(output_path)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
