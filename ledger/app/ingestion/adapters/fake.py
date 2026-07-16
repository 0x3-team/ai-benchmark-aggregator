from __future__ import annotations

import json
from pathlib import Path

from app.db.models import SourceSnapshot
from app.ingestion.adapters.base import SourceAdapter
from app.ingestion.extractors.normalize import try_parse_score
from app.schemas.boundary import (
    ClaimValidationInput,
    OfficialSource,
    ResultClaimInput,
    SourceFetchResult,
)


class FakeSourceAdapter(SourceAdapter):
    """Synthetic data helper for explicitly isolated test fixtures only.

    It is never a production source adapter.  The registry route is retired,
    production policy quarantines the ``fake`` source type, and the adapter
    itself requires a test-only mode before it will manufacture fixture bytes.
    """

    source_type = "fake"
    requires_central_fetch = False

    def __init__(self, fixture_path: Path | None = None) -> None:
        self.fixture_path = fixture_path

    def fetch(self, source: OfficialSource) -> SourceFetchResult:
        if source.parser_config.get("mode") != "test_fixture_only":
            raise RuntimeError(
                "Fake adapter is test-fixture only and cannot fetch an Official benchmark source."
            )
        if self.fixture_path and self.fixture_path.exists():
            raw = self.fixture_path.read_bytes()
        else:
            payload = source.parser_config.get("fixture_json") or {
                "leaderboard": [
                    {"model_id": "Fake-Model-1", "value": "42.5", "rank": 1, "metric": "acc"}
                ]
            }
            raw = json.dumps(payload).encode("utf-8")
        return SourceFetchResult(
            raw_bytes=raw,
            content_type="application/json",
            http_status=200,
            metadata={"adapter": "fake"},
        )

    def extract_claims(
        self,
        source: OfficialSource,
        snapshot: SourceSnapshot,
        raw_bytes: bytes,
    ) -> list[ResultClaimInput]:
        if source.parser_config.get("mode") != "test_fixture_only":
            return []
        data = json.loads(raw_bytes.decode("utf-8"))
        rows = data.get("leaderboard") or data.get("results") or []
        claims: list[ResultClaimInput] = []
        for i, row in enumerate(rows):
            model_raw = str(row.get("model_id") or row.get("model") or "unknown")
            score_raw = str(row.get("value") if row.get("value") is not None else row.get("score") or "")
            rank_raw = str(row.get("rank")) if row.get("rank") is not None else None
            metric_raw = row.get("metric")
            claims.append(
                ResultClaimInput(
                    official_source_id=source.id,
                    source_snapshot_id=snapshot.id,
                    benchmark_id=source.benchmark_id,
                    model_raw=model_raw,
                    benchmark_raw=source.benchmark_id or source.source_name,
                    score_raw=score_raw,
                    metric_raw=str(metric_raw) if metric_raw is not None else None,
                    rank_raw=rank_raw,
                    score_numeric=try_parse_score(score_raw),
                    evidence_location={
                        "type": "json_path",
                        "path": f"$.leaderboard[{i}].value",
                        "model_path": f"$.leaderboard[{i}].model_id",
                    },
                    capture_method="fake_adapter",
                    capture_confidence=1.0,
                    capture_status="parser_verified",
                    officialness_level=source.officialness_level,
                )
            )
        return claims

    def validate_claim(self, claim: ResultClaimInput, raw_bytes: bytes) -> list[ClaimValidationInput]:
        data = json.loads(raw_bytes.decode("utf-8"))
        path = (claim.evidence_location or {}).get("path", "")
        # simple check: score exists among values
        values = [str(r.get("value", r.get("score", ""))) for r in data.get("leaderboard", [])]
        outcome = "pass" if claim.score_raw in values else "fail"
        return [
            ClaimValidationInput(
                validation_type="json_path_match",
                outcome=outcome,
                validator="FakeSourceAdapter",
                notes=path,
            )
        ]
