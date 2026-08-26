#!/usr/bin/env python3
"""Build a review-only, source-hashed model inventory checkpoint."""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalize(value: object) -> str:
    return "".join(ch for ch in str(value).lower() if ch.isalnum())


def main() -> int:
    if len(sys.argv) != 4:
        print("usage: build_model_inventory.py <openrouter.json> <huggingface.json> <output.json>", file=sys.stderr)
        return 2
    openrouter_path, huggingface_path, output_path = map(Path, sys.argv[1:])
    repo = Path.cwd()
    frontend = json.loads((repo / "src/data/models.json").read_text())
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
            "frontendIds": [],
            "registryIds": [],
            "providerIds": [],
            "disposition": "needs_review",
        })
        if kind not in item["sourceKinds"]:
            item["sourceKinds"].append(kind)
        if identifier not in item["sourceIds"]:
            item["sourceIds"].append(identifier)
        if kind == "frontend" and identifier not in item["frontendIds"]:
            item["frontendIds"].append(identifier)
        if kind == "registry" and identifier not in item["registryIds"]:
            item["registryIds"].append(identifier)
        if kind in {"openrouter", "huggingface"} and identifier not in item["providerIds"]:
            item["providerIds"].append(identifier)

    for row in frontend:
        add("frontend", row)
    for row in registry:
        add("registry", row)
    for row in openrouter:
        add("openrouter", row)
    for row in huggingface:
        add("huggingface", row)

    candidates_list = [candidates[key] for key in sorted(candidates)]
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    exact_matches = sum(1 for row in registry if any(model["id"] == row["id"] for model in frontend))
    output = {
        "schemaVersion": "model-inventory-checkpoint-v1",
        "generatedAt": now,
        "availability": "review_only",
        "runtimeMutation": False,
        "syntheticDataRemoved": False,
        "authority": "candidate_inventory_only",
        "counts": {
            "frontendModels": len(frontend),
            "registryRows": len(registry),
            "registryUniqueIds": len({row["id"] for row in registry}),
            "openRouterEntries": len(openrouter),
            "huggingFaceSampleEntries": len(huggingface),
            "normalizedCandidateKeys": len(candidates_list),
            "exactFrontendRegistryMatches": exact_matches,
        },
        "sources": {
            "frontend": {"path": "src/data/models.json", "url": "local tracked Demo catalog", "retrievedAt": now, "sha256": sha256(repo / "src/data/models.json"), "count": len(frontend)},
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
