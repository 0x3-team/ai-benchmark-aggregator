from __future__ import annotations

import json
from typing import Any

import httpx

from app.config import get_settings
from app.db.models import SourceSnapshot
from app.ingestion.adapters.base import SourceAdapter
from app.ingestion.extractors.normalize import try_parse_score
from app.schemas.boundary import (
    ClaimValidationInput,
    OfficialSource,
    ResultClaimInput,
    SourceFetchResult,
)

# Accuracy-like metric name patterns; skip metadata / count / runtime stats
_NON_ACCURACY_PREFIXES = (
    "num_",
    "finish_reason",
    "batch_size",
    "inference_",
    "training_",
    "prompt_truncated",
    "max_prob",
    "platt_coef",
    "platt_intercept",
)


def _is_accuracy_metric(name: str) -> bool:
    """Return True for performance metrics, False for metadata/count stats."""
    lower = name.lower()
    return not any(lower.startswith(p) for p in _NON_ACCURACY_PREFIXES)


class HelmJSONAdapter(SourceAdapter):
    source_type = "helm_json"

    def fetch(self, source: OfficialSource) -> SourceFetchResult:
        settings = get_settings()
        headers = {"User-Agent": settings.http_user_agent}
        url = source.source_url
        try:
            with httpx.Client(
                timeout=settings.http_timeout_seconds, follow_redirects=True
            ) as client:
                resp = client.get(url, headers=headers)
        except httpx.HTTPError as exc:
            raise RuntimeError(
                f"Network error fetching HELM source={source.id}: {exc}"
            ) from exc
        if resp.status_code >= 400:
            raise RuntimeError(
                f"HTTP {resp.status_code} fetching HELM source={source.id} ({url})"
            )
        return SourceFetchResult(
            raw_bytes=resp.content,
            content_type=resp.headers.get("content-type"),
            http_status=resp.status_code,
            etag=resp.headers.get("etag"),
            last_modified_header=resp.headers.get("last-modified"),
            final_url=str(resp.url),
            headers={
                k: v
                for k, v in resp.headers.items()
                if k.lower() in {"etag", "last-modified", "content-type"}
            },
            metadata={"url": url},
        )

    def extract_claims(
        self,
        source: OfficialSource,
        snapshot: SourceSnapshot,
        raw_bytes: bytes,
    ) -> list[ResultClaimInput]:
        data = json.loads(raw_bytes.decode("utf-8"))

        # Support two possible top-level shapes:
        #   1) {"groups": [{"runs": [{"run_name": ..., "metrics": [...]}]}]}
        #   2) Flat list of runs: [{"run_spec": {"adapter_spec": {"model": ...}}, "stats": [...]}]
        runs: list[dict[str, Any]] = []
        if isinstance(data, dict) and "groups" in data:
            for group in data["groups"]:
                runs.extend(group.get("runs", []))
        elif isinstance(data, list):
            runs = data

        model_field = source.parser_config.get("model_field", "model")
        score_field = source.parser_config.get("score_field", "mean")
        metric_field = source.parser_config.get("metric_field", "name")

        claims: list[ResultClaimInput] = []
        for run in runs:
            if not isinstance(run, dict):
                continue

            # Extract model name from shape 1 (run_name / model_field) or shape 2 (run_spec.adapter_spec.model)
            if "run_spec" in run:
                model_raw = str(
                    run["run_spec"]
                    .get("adapter_spec", {})
                    .get(model_field, "unknown")
                )
            else:
                model_raw = str(run.get("run_name") or run.get(model_field) or "unknown")

            # Extract metrics
            metrics: list[dict[str, Any]] = []
            if "metrics" in run:
                # Shape 1: {name, value}
                metrics = run.get("metrics", [])
            elif "stats" in run:
                # Shape 2: [{"name": {"name": ..., "split": ..., ...}, "mean": ...}]
                metrics = run.get("stats", [])

            for m in metrics:
                if not isinstance(m, dict):
                    continue

                # Extract metric name
                if isinstance(m.get("name"), dict):
                    # Shape 2: nested name object
                    metric_name = m["name"].get(metric_field) or m["name"].get("name")
                    split = m["name"].get("split")
                else:
                    # Shape 1: flat
                    metric_name = m.get(metric_field) or m.get("name")
                    split = m.get("split")

                metric_name = str(metric_name) if metric_name else None
                if not metric_name:
                    continue

                if not _is_accuracy_metric(metric_name):
                    continue

                # Extract score value
                value = m.get(score_field)
                if value is None:
                    value = m.get("value")

                # Skip non-numeric
                if value is None:
                    continue
                try:
                    float(value)
                except (TypeError, ValueError):
                    continue

                score_raw = str(value)
                score_numeric = try_parse_score(score_raw)

                claims.append(
                    ResultClaimInput(
                        official_source_id=source.id,
                        source_snapshot_id=snapshot.id,
                        benchmark_id=source.benchmark_id,
                        model_raw=model_raw,
                        benchmark_raw=source.benchmark_id
                        or source.source_name,
                        score_raw=score_raw,
                        metric_raw=metric_name,
                        split_raw=split,
                        score_numeric=score_numeric,
                        evidence_location={
                            "type": "helm_json",
                            "model_path": model_field,
                        },
                        capture_method="helm_json_parser",
                        capture_confidence=0.85,
                        capture_status="parser_verified",
                        officialness_level=source.officialness_level,
                    )
                )

        return claims

    def validate_claim(
        self,
        claim: ResultClaimInput,
        raw_bytes: bytes,
    ) -> list[ClaimValidationInput]:
        try:
            text = raw_bytes.decode("utf-8", errors="replace")
        except Exception:
            text = ""
        if claim.score_raw and claim.score_raw in text:
            return [
                ClaimValidationInput(
                    validation_type="helm_json_match",
                    outcome="pass",
                    validator="HelmJSONAdapter",
                )
            ]
        return [
            ClaimValidationInput(
                validation_type="helm_json_match",
                outcome="uncertain",
                validator="HelmJSONAdapter",
                notes="score_raw not found in raw bytes",
            )
        ]
