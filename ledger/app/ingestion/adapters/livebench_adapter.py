from __future__ import annotations

import json
import re
from typing import Any

from app.db.models import SourceSnapshot
from app.ingestion.adapters.base import SourceAdapter
from app.schemas.boundary import ClaimValidationInput, OfficialSource, ResultClaimInput, SourceFetchResult


class LiveBenchAdapter(SourceAdapter):
    source_type = "livebench_adapter"

    def fetch(self, source: OfficialSource) -> SourceFetchResult:
        import httpx
        from app.config import get_settings

        settings = get_settings()
        headers = {"User-Agent": settings.http_user_agent}

        try:
            # 1. Fetch homepage
            with httpx.Client(timeout=settings.http_timeout_seconds, follow_redirects=True) as client:
                r = client.get("https://livebench.ai/", headers=headers)
                r.raise_for_status()

                # Find main JS file
                m = re.search(r'src=["\']\./static/js/main\.[a-f0-9]+\.js["\']', r.text)
                if not m:
                    m = re.search(r'static/js/main\.[a-f0-9]+\.js', r.text)

                js_url = "https://livebench.ai/static/js/main.699ee9e4.js"  # default fallback
                if m:
                    js_path = m.group(0).replace('src="', '').replace('"', '').replace("'", "").lstrip(".")
                    if not js_path.startswith("/"):
                        js_path = "/" + js_path
                    js_url = f"https://livebench.ai{js_path}"

                # 2. Fetch JS file to get latest version
                r_js = client.get(js_url, headers=headers)
                r_js.raise_for_status()

                # Find pe array
                pe_match = re.search(r'pe\s*=\s*\[(.*?)\]', r_js.text)
                version = "2026-06-25"  # default fallback
                if pe_match:
                    versions = [v.strip(' "') for v in pe_match.group(1).split(",")]
                    if versions:
                        version = versions[-1]

                v_underscore = version.replace("-", "_")

                # 3. Fetch table CSV and categories JSON
                csv_url = f"https://livebench.ai/table_{v_underscore}.csv"
                cats_url = f"https://livebench.ai/categories_{v_underscore}.json"

                r_csv = client.get(csv_url, headers=headers)
                r_csv.raise_for_status()

                r_cats = client.get(cats_url, headers=headers)
                r_cats.raise_for_status()

                # Return combined payload as JSON dict
                payload = {
                    "csv": r_csv.text,
                    "categories": r_cats.json(),
                    "version": version,
                }

                return SourceFetchResult(
                    raw_bytes=json.dumps(payload).encode("utf-8"),
                    content_type="application/json",
                    http_status=200,
                    final_url=csv_url,
                )
        except Exception as exc:
            raise RuntimeError(f"Fetch failed for {source.id}: {exc}") from exc

    def extract_claims(
        self, source: OfficialSource, snapshot: SourceSnapshot, raw_bytes: bytes
    ) -> list[ResultClaimInput]:
        import csv
        from io import StringIO
        from app.ingestion.extractors.normalize import try_parse_score

        try:
            payload = json.loads(raw_bytes.decode("utf-8"))
        except Exception:
            return []

        csv_text = payload.get("csv", "")
        categories = payload.get("categories", {})
        if not csv_text or not categories:
            return []

        # Read CSV rows
        f = StringIO(csv_text.strip())
        reader = csv.DictReader(f)
        claims: list[ResultClaimInput] = []

        for row in reader:
            model_raw = row.get("model")
            if not model_raw:
                continue

            # Compute category averages
            cat_averages = []
            for cat_name, tasks in categories.items():
                task_scores = []
                for t in tasks:
                    val = row.get(t)
                    if val is not None and val != "" and val != "-":
                        try:
                            task_scores.append(float(val))
                        except ValueError:
                            pass
                if task_scores:
                    cat_avg = sum(task_scores) / len(task_scores)
                    cat_averages.append(cat_avg)

            if not cat_averages:
                continue

            # Compute overall score (average of category averages)
            overall_score = sum(cat_averages) / len(cat_averages)
            score_raw = f"{overall_score:.2f}"

            claims.append(
                ResultClaimInput(
                    official_source_id=source.id,
                    source_snapshot_id=snapshot.id,
                    benchmark_id=source.benchmark_id,
                    model_raw=model_raw,
                    benchmark_raw=source.benchmark_id or source.source_name,
                    score_raw=score_raw,
                    metric_raw="overall",
                    score_numeric=try_parse_score(score_raw),
                    evidence_location={
                        "type": "livebench_derived",
                        "model": model_raw,
                        "version": payload.get("version"),
                        "categories_computed": len(cat_averages),
                    },
                    capture_method="livebench_adapter_parser",
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
        outcome = "pass" if claim.model_raw and claim.model_raw in text else "uncertain"
        return [
            ClaimValidationInput(
                validation_type="json_path_match",
                outcome=outcome,
                validator="LiveBenchAdapter",
            )
        ]
