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


class HFBenchmarkAPIAdapter(SourceAdapter):
    source_type = "hf_benchmark_api"

    def fetch(self, source: OfficialSource) -> SourceFetchResult:
        settings = get_settings()
        headers = {"User-Agent": settings.http_user_agent}
        if settings.hf_token:
            # Never log token; only use as Authorization header
            headers["Authorization"] = f"Bearer {settings.hf_token}"
        mode = source.parser_config.get("mode", "discovery")
        url = source.source_url
        if mode == "leaderboard" and source.parser_config.get("dataset_id"):
            ds = source.parser_config["dataset_id"]
            url = f"https://huggingface.co/api/datasets/{ds}/leaderboard"
        try:
            with httpx.Client(timeout=settings.http_timeout_seconds, follow_redirects=True) as client:
                resp = client.get(url, headers=headers)
        except httpx.HTTPError as exc:
            raise RuntimeError(
                f"Network error fetching HF source={source.id}: {exc}"
            ) from exc
        if resp.status_code >= 400:
            raise RuntimeError(
                f"HTTP {resp.status_code} fetching HF source={source.id} ({url})"
            )
        raw = resp.content
        return SourceFetchResult(
            raw_bytes=raw,
            content_type=resp.headers.get("content-type"),
            http_status=resp.status_code,
            etag=resp.headers.get("etag"),
            last_modified_header=resp.headers.get("last-modified"),
            final_url=str(resp.url),
            headers={k: v for k, v in resp.headers.items() if k.lower() in {"etag", "last-modified", "content-type"}},
            metadata={"mode": mode, "url": url},
        )

    def extract_claims(
        self,
        source: OfficialSource,
        snapshot: SourceSnapshot,
        raw_bytes: bytes,
    ) -> list[ResultClaimInput]:
        data = json.loads(raw_bytes.decode("utf-8"))
        mode = source.parser_config.get("mode", "discovery")
        if mode == "discovery":
            # Discovery lists datasets; store metadata rows as low-confidence claims only if value present
            items = data if isinstance(data, list) else data.get("datasets") or []
            claims: list[ResultClaimInput] = []
            for i, item in enumerate(items[:500]):
                if not isinstance(item, dict):
                    continue
                model_raw = str(item.get("id") or item.get("name") or f"dataset-{i}")
                claims.append(
                    ResultClaimInput(
                        official_source_id=source.id,
                        source_snapshot_id=snapshot.id,
                        benchmark_id=source.benchmark_id,
                        model_raw=model_raw,
                        benchmark_raw="hf_official_benchmarks",
                        score_raw="n/a",
                        metric_raw="discovery",
                        evidence_location={"type": "json_path", "path": f"$[{i}].id"},
                        capture_method="hf_api",
                        capture_confidence=0.5,
                        capture_status="parser_verified",
                        officialness_level=source.officialness_level,
                        evidence_text=json.dumps({k: item.get(k) for k in ("id", "author") if k in item}),
                    )
                )
            return claims

        # leaderboard mode
        rows = data if isinstance(data, list) else data.get("leaderboard") or data.get("entries") or []
        claims = []
        for i, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            model_raw = str(row.get("model_id") or row.get("model") or row.get("fullname") or "unknown")
            value = row.get("value")
            if value is None:
                value = row.get("score")
            score_raw = str(value) if value is not None else ""
            rank_raw = str(row["rank"]) if row.get("rank") is not None else None
            claims.append(
                ResultClaimInput(
                    official_source_id=source.id,
                    source_snapshot_id=snapshot.id,
                    benchmark_id=source.benchmark_id,
                    model_raw=model_raw,
                    benchmark_raw=source.parser_config.get("dataset_id") or source.benchmark_id or source.source_name,
                    score_raw=score_raw,
                    metric_raw=str(row.get("metric")) if row.get("metric") is not None else None,
                    rank_raw=rank_raw,
                    score_numeric=try_parse_score(score_raw) if score_raw else None,
                    evidence_location={
                        "type": "json_path",
                        "path": f"$[{i}].value",
                        "model_path": f"$[{i}].model_id",
                        "rank_path": f"$[{i}].rank",
                    },
                    capture_method="hf_api",
                    capture_confidence=0.95,
                    capture_status="parser_verified" if score_raw else "needs_review",
                    officialness_level=source.officialness_level,
                    evidence_text=json.dumps(
                        {k: row.get(k) for k in ("source", "filename", "pull_request", "notes", "verified") if k in row}
                    )
                    or None,
                )
            )
        return claims

    def validate_claim(self, claim: ResultClaimInput, raw_bytes: bytes) -> list[ClaimValidationInput]:
        if claim.score_raw == "n/a":
            return [
                ClaimValidationInput(
                    validation_type="schema_validation",
                    outcome="pass",
                    validator="HFBenchmarkAPIAdapter",
                    notes="discovery metadata row",
                )
            ]
        try:
            data = json.loads(raw_bytes.decode("utf-8"))
        except json.JSONDecodeError:
            return [
                ClaimValidationInput(
                    validation_type="json_path_match",
                    outcome="fail",
                    validator="HFBenchmarkAPIAdapter",
                    notes="invalid json",
                )
            ]
        rows = data if isinstance(data, list) else data.get("leaderboard") or data.get("entries") or []
        for row in rows:
            if not isinstance(row, dict):
                continue
            model = str(row.get("model_id") or row.get("model") or row.get("fullname") or "")
            value = row.get("value")
            if value is None:
                value = row.get("score")
            if model == claim.model_raw and str(value) == claim.score_raw:
                return [
                    ClaimValidationInput(
                        validation_type="json_path_match",
                        outcome="pass",
                        validator="HFBenchmarkAPIAdapter",
                    )
                ]
        return [
            ClaimValidationInput(
                validation_type="json_path_match",
                outcome="uncertain",
                validator="HFBenchmarkAPIAdapter",
            )
        ]
