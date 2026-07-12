from __future__ import annotations

import json
import os
from typing import Any

from app.db.models import SourceSnapshot
from app.ingestion.adapters.base import SourceAdapter
from app.ingestion.extractors.normalize import try_parse_score
from app.schemas.boundary import ClaimValidationInput, OfficialSource, ResultClaimInput, SourceFetchResult


class LMSYSArenaAPIAdapter(SourceAdapter):
    source_type = "lmsys_arena_api"

    def fetch(self, source: OfficialSource) -> SourceFetchResult:
        import httpx
        from app.config import get_settings

        settings = get_settings()
        headers = {"User-Agent": settings.http_user_agent}

        # Check API key if requires_auth is True
        api_key = None
        if source.requires_auth:
            env_var = source.parser_config.get("api_key_env", "LMSYS_API_KEY")
            api_key = os.environ.get(env_var)
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"

        # Try primary URL first
        url = source.source_url
        if url == "https://lmarena.ai/leaderboard" or url == "https://lmarena.ai/api/leaderboard":
            url = "https://lmarena.ai/api/leaderboard"

        try:
            with httpx.Client(timeout=settings.http_timeout_seconds, follow_redirects=True) as client:
                resp = client.get(url, headers=headers)
                if resp.status_code == 200:
                    return SourceFetchResult(
                        raw_bytes=resp.content,
                        content_type=resp.headers.get("content-type"),
                        http_status=resp.status_code,
                        final_url=str(resp.url),
                    )
        except Exception as exc:
            print(f"Primary fetch for {source.id} failed: {exc}")

        # Fallback to public endpoint
        fallback_url = "https://api.wulong.dev/arena-ai-leaderboards/v1/leaderboard?name=text"
        print(f"LMSYSArenaAPIAdapter: falling back to {fallback_url}")
        try:
            with httpx.Client(timeout=settings.http_timeout_seconds, follow_redirects=True) as client:
                resp = client.get(fallback_url, headers={"User-Agent": settings.http_user_agent})
                resp.raise_for_status()
                return SourceFetchResult(
                    raw_bytes=resp.content,
                    content_type=resp.headers.get("content-type"),
                    http_status=resp.status_code,
                    final_url=str(resp.url),
                    metadata={"fallback_used": True},
                )
        except Exception as exc:
            raise RuntimeError(f"LMSYS Chatbot Arena fetch and fallback both failed: {exc}") from exc

    def extract_claims(
        self, source: OfficialSource, snapshot: SourceSnapshot, raw_bytes: bytes
    ) -> list[ResultClaimInput]:
        try:
            data = json.loads(raw_bytes.decode("utf-8"))
        except Exception:
            return []

        models_list = data.get("models", [])
        claims: list[ResultClaimInput] = []

        for i, item in enumerate(models_list):
            if not isinstance(item, dict):
                continue
            # LMSYS fields: rank, model, score (Elo), vendor/org
            model_raw = str(item.get("model", ""))
            score_raw = str(item.get("score", ""))
            if not model_raw or not score_raw:
                continue

            rank_raw = str(item.get("rank")) if item.get("rank") is not None else None

            claims.append(
                ResultClaimInput(
                    official_source_id=source.id,
                    source_snapshot_id=snapshot.id,
                    benchmark_id=source.benchmark_id,
                    model_raw=model_raw,
                    benchmark_raw=source.benchmark_id or source.source_name,
                    score_raw=score_raw,
                    metric_raw="Elo",
                    rank_raw=rank_raw,
                    score_numeric=try_parse_score(score_raw) if score_raw else None,
                    evidence_location={
                        "type": "json_path",
                        "path": f"$.models[{i}].score",
                        "model_path": f"$.models[{i}].model",
                        "rank_path": f"$.models[{i}].rank",
                    },
                    capture_method="lmsys_arena_api_parser",
                    capture_confidence=0.95,
                    capture_status="parser_verified",
                    officialness_level=source.officialness_level,
                )
            )
        return claims

    def validate_claim(self, claim: ResultClaimInput, raw_bytes: bytes) -> list[ClaimValidationInput]:
        try:
            text = raw_bytes.decode("utf-8")
        except Exception:
            text = ""
        outcome = "pass" if claim.score_raw and claim.score_raw in text else "uncertain"
        return [
            ClaimValidationInput(
                validation_type="json_path_match",
                outcome=outcome,
                validator="LMSYSArenaAPIAdapter",
            )
        ]
