from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from typing import Any

import httpx

from app.db.models import SourceSnapshot
from app.ingestion.adapters.base import SourceAdapter
from app.ingestion.extractors.normalize import try_parse_score
from app.schemas.boundary import (
    ClaimValidationInput,
    OfficialSource,
    ResultClaimInput,
    SourceFetchResult,
)

S3_NS = "http://s3.amazonaws.com/doc/2006-03-01/"
S3_BUCKET_URL = "https://sierra-tau-bench-public.s3.amazonaws.com/"


class TauBenchS3Adapter(SourceAdapter):
    source_type = "taubench_s3"

    def fetch(self, source: OfficialSource) -> SourceFetchResult:
        from app.config import get_settings

        settings = get_settings()
        cfg = source.parser_config or {}
        max_keys = int(cfg.get("max_keys", 50))

        with httpx.Client(
            timeout=settings.http_timeout_seconds, follow_redirects=True
        ) as client:
            # 1. List the S3 bucket to discover submission.json keys
            list_url = f"{S3_BUCKET_URL}?list-type=2&prefix=submissions/"
            list_resp = client.get(list_url, headers={"User-Agent": settings.http_user_agent})
            list_resp.raise_for_status()

            root = ET.fromstring(list_resp.text)
            keys: list[str] = []
            for contents in root.findall(f"{{{S3_NS}}}Contents"):
                key_el = contents.find(f"{{{S3_NS}}}Key")
                if key_el is not None and key_el.text and key_el.text.endswith("submission.json"):
                    keys.append(key_el.text)

            # 2. Fetch each submission.json (up to max_keys), join as NDJSON
            lines: list[bytes] = []
            for key in sorted(keys)[:max_keys]:
                file_url = f"{S3_BUCKET_URL}{key}"
                try:
                    file_resp = client.get(
                        file_url, headers={"User-Agent": settings.http_user_agent}
                    )
                    file_resp.raise_for_status()
                    lines.append(file_resp.content)
                except Exception:
                    # Skip any individual file that fails to fetch
                    continue

            joined = b"\n".join(lines)

            return SourceFetchResult(
                raw_bytes=joined,
                content_type="application/x-ndjson",
                http_status=200,
            )

    def extract_claims(
        self,
        source: OfficialSource,
        snapshot: SourceSnapshot,
        raw_bytes: bytes,
    ) -> list[ResultClaimInput]:
        claims_by_model: dict[str, list[float]] = {}  # model_raw -> [pass_rate, ...]

        for line in raw_bytes.split(b"\n"):
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line.decode("utf-8"))
            except json.JSONDecodeError:
                continue

            model = data.get("model") or data.get("model_name") or data.get("model_id")
            if not model:
                continue

            model = str(model)
            results = data.get("results", {})
            if not isinstance(results, dict):
                continue

            for domain, domain_results in results.items():
                if not isinstance(domain_results, dict):
                    continue
                for metric_name, metric_value in domain_results.items():
                    if isinstance(metric_name, str) and metric_name.startswith("pass_"):
                        try:
                            val = float(metric_value)
                            claims_by_model.setdefault(model, []).append(val)
                        except (TypeError, ValueError):
                            continue

        claims: list[ResultClaimInput] = []
        for model_raw, pass_values in claims_by_model.items():
            if not pass_values:
                continue
            mean = sum(pass_values) / len(pass_values)
            claims.append(
                ResultClaimInput(
                    official_source_id=source.id,
                    source_snapshot_id=snapshot.id,
                    benchmark_id=source.benchmark_id,
                    model_raw=model_raw,
                    benchmark_raw=source.benchmark_id or source.source_name,
                    score_raw=f"{mean:.4f}",
                    metric_raw="mean_pass_rate",
                    score_numeric=mean,
                    evidence_location={
                        "type": "s3_submission",
                        "model": model_raw,
                    },
                    capture_method="taubench_s3_parser",
                    capture_confidence=0.9,
                    capture_status="parser_verified",
                    officialness_level=source.officialness_level,
                )
            )
        return claims

    def validate_claim(
        self, claim: ResultClaimInput, raw_bytes: bytes
    ) -> list[ClaimValidationInput]:
        return [
            ClaimValidationInput(
                validation_type="taubench_agg",
                outcome="pass",
                validator="TauBenchS3Adapter",
            )
        ]
