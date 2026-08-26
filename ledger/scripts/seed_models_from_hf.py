#!/usr/bin/env python3
"""OFFLINE, review-only candidate generator for Hugging Face model identities.

This is a deliberate replacement for the previous live-fetch rewriter. It no
longer:

  * performs any outbound ``urllib.request.urlopen`` / ``httpx.get`` call,
  * or pulls the top-N downloads from the Hugging Face API,

and it NEVER writes an active registry file (``models_frontier.yaml``,
``models.yaml``, ``models_hf_seed.yaml``). It reads an already-exported,
committed candidate snapshot as input, and emits a brand-new review file with
`O_EXCL`-style no-overwrite semantics so it cannot clobber existing work.

Exit codes:
  0  candidates written (or reviewed as empty)
  2  an input/output/collision precondition was not met (fail closed)
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import yaml

# The governed model manifests this tool must never mutate. It may only read
# them to report collisions for human review.
READ_ONLY_REGISTRY_FILES = (
    "models_frontier.yaml",
    "models.yaml",
    "models_hf_seed.yaml",
)

# Fields an HF candidate carries that are purely provenance for the review
# queue. They are surfaced in the candidate output so a reviewer understands
# the source of a suggestion, but are not authoritative model registry fields.
HF_PROVENANCE_FIELDS = ("downloads", "likes", "pipeline_tag", "createdAt")


def _read_review_input(path: Path) -> list[dict[str, Any]]:
    """Read an already-exported candidate snapshot (YAML or JSON).

    The file is a list of model candidate maps, each carrying at least ``id``.
    A malformed doc fails closed rather than generating a partial queue.
    """
    if not path.exists():
        raise FileNotFoundError(f"review input does not exist: {path}")
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise ValueError(f"review input is empty: {path}")
    try:
        if path.suffix.lower() in (".yaml", ".yml"):
            payload = yaml.safe_load(text)
        else:
            import json

            payload = json.loads(text)
    except Exception as exc:  # noqa: BLE001 - surface a stable causal message
        raise ValueError(f"unable to parse review input {path}: {exc}") from exc
    if isinstance(payload, dict):
        payload = payload.get("models") or payload.get("candidates") or []
    if not isinstance(payload, list):
        raise ValueError(f"review input must be a list of candidate maps: {path}")
    # Fail closed: account for EVERY input row. A non-mapping row, a row with a
    # missing/blank id, or aliases that are not a list of strings abort the whole
    # run so no partial queue is ever generated. Index+reason keep the error
    # deterministic for a human to locate.
    candidates: list[dict[str, Any]] = []
    for index, row in enumerate(payload):
        if not isinstance(row, dict):
            raise ValueError(
                f"review input row {index} is not a mapping: {row!r} (path: {path})"
            )
        row_id = row.get("id")
        if not row_id or not str(row_id).strip():
            raise ValueError(
                f"review input row {index} is missing a non-blank 'id' (path: {path})"
            )
        aliases = row.get("aliases")
        if aliases is not None and (
            not isinstance(aliases, list) or not all(isinstance(a, str) for a in aliases)
        ):
            raise ValueError(
                f"review input row {index} has 'aliases' that is not a list of "
                f"strings: {aliases!r} (path: {path})"
            )
        candidates.append(row)
    return candidates


def _collisions(candidates: list[dict[str, Any]], registry_dir: Path) -> dict[str, list[str]]:
    """Return candidate model IDs already present in any read-only registry file.

    Values are the registry files (relative paths) that already define the ID.
    The tool never resolves these automatically; it reports them for a human to
    reconcile, matching the fail-closed but review-first disposition.
    """
    collisions: dict[str, list[str]] = {}
    for candidate in candidates:
        candidate_id = candidate.get("id")
        if not candidate_id:
            continue
        existing: list[str] = []
        for name in READ_ONLY_REGISTRY_FILES:
            registry_file = registry_dir / name
            if not registry_file.exists():
                continue
            document = yaml.safe_load(registry_file.read_text(encoding="utf-8")) or {}
            for model in document.get("models") or []:
                if isinstance(model, dict) and str(model.get("id")) == str(candidate_id):
                    existing.append(str(registry_file))
                    break
        if existing:
            collisions[str(candidate_id)] = existing
    return collisions


def _build_output(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    """Project candidates into the review-file schema, pruning provenance.

    Only the fields surfaced in the review queue are kept; the transient HF
    download/like counters are provenance for a curator's decision, not model
    registry fields. Aliases default to the canonical HF id.
    """
    model_rows: list[dict[str, Any]] = []
    for candidate in candidates:
        model_id = candidate.get("id")
        if not model_id:
            continue
        canonical_name = candidate.get("canonical_name") or str(model_id).split("/")[-1]
        display_name = candidate.get("display_name") or canonical_name.replace("-", " ").replace("_", " ")
        display_name = " ".join(display_name.split())
        aliases = list(candidate.get("aliases") or [])
        if str(model_id) not in aliases:
            aliases.insert(0, str(model_id))
        row = {
            "id": str(model_id),
            "canonical_name": canonical_name,
            "display_name": display_name,
            "entity_type": candidate.get("entity_type", "chat_model"),
            "provider": candidate.get("provider", "unknown"),
            "access_type": candidate.get("access_type", "open_weights"),
            "status": "active",
            "aliases": aliases,
        }
        model_rows.append(row)
    return {"registry_path": "NONE (review only)", "models": model_rows}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--input",
        type=Path,
        required=True,
        help="Existing exported candidate model list (YAML or JSON). Never fetched.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="New review queue file to write. Refuses to overwrite an existing file.",
    )
    parser.add_argument(
        "--registry-dir",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "app" / "registry",
        help="Registry directory to scan for existing (read-only) model IDs.",
    )
    args = parser.parse_args()

    try:
        candidates = _read_review_input(args.input)
    except (FileNotFoundError, ValueError) as exc:
        print(f"ERROR: {exc}")
        return 1

    collisions = _collisions(candidates, args.registry_dir)
    if collisions:
        print("COLLISIONS (review required; nothing written):")
        for model_id, files in sorted(collisions.items()):
            print(f"  {model_id!r} already defined by: {', '.join(files)}")
        print("No output file was written. Resolve the collisions, then rerun.")
        return 1

    if args.output.exists():
        print(f"ERROR: refusing to overwrite existing file (no-overwrite): {args.output}")
        print("Choose a new --output path. Nothing was written.")
        return 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    payload = _build_output(candidates)
    with args.output.open("x", encoding="utf-8") as handled:
        yaml.safe_dump(payload, handled, sort_keys=False, allow_unicode=True)

    print(f"wrote {len(payload['models'])} review candidates to {args.output}")
    print("Review them, then reconcile into models_frontier.yaml manually. Not written by this tool.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())