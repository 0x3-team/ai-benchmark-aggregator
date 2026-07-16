from __future__ import annotations

from typing import Any

from app.db.models import SourceSnapshot
from app.ingestion.adapters.base import SourceAdapter
from app.ingestion.json_lexemes import (
    JsonLexemeError,
    canonical_config_json_path,
    decode_exact_json_script,
    decode_json_bytes,
    resolve_json_path,
    source_score_lexeme,
    source_text,
)
from app.schemas.boundary import ClaimValidationInput, OfficialSource, ResultClaimInput


class SWEBenchAdapter(SourceAdapter):
    """Parse either a pinned leaderboard JSON artifact or an explicit script fixture.

    The configured production candidate is the direct JSON artifact. Embedded
    script support remains typed and fail-closed for immutable historical
    artifacts, but it is never selected merely because an HTML page contains a
    similarly named element.
    """

    source_type = "swe_bench_adapter"
    accepted_content_types = frozenset(
        {
            "application/json",
            "application/*+json",
            "text/json",
            "text/html",
            "application/xhtml+xml",
        }
    )

    def _config(self, source: OfficialSource) -> dict[str, object] | None:
        cfg = source.parser_config or {}
        artifact_format = cfg.get("artifact_format", "embedded_json_script")
        category = cfg.get("category", "Verified")
        leaderboards_path = canonical_config_json_path(cfg.get("leaderboards_path", "$"))
        category_name_field = cfg.get("category_name_field", "name")
        results_field = cfg.get("results_field", "results")
        model_field = cfg.get("model_field", "name")
        score_field = cfg.get("score_field", "resolved")
        metric_raw = cfg.get("metric_raw", "% Resolved")
        script_id = cfg.get("script_id", "leaderboard-data")
        script_type = cfg.get("script_type")
        if (
            artifact_format not in {"direct_json", "embedded_json_script"}
            or not isinstance(category, str)
            or not category
            or leaderboards_path is None
            or not all(
                isinstance(value, str) and value
                for value in (category_name_field, results_field, model_field, score_field, metric_raw)
            )
            or not isinstance(script_id, str)
            or not script_id
            or script_type is not None
            and not isinstance(script_type, str)
        ):
            return None
        return {
            "artifact_format": artifact_format,
            "category": category,
            "leaderboards_path": leaderboards_path,
            "category_name_field": category_name_field,
            "results_field": results_field,
            "model_field": model_field,
            "score_field": score_field,
            "metric_raw": metric_raw,
            "script_id": script_id,
            "script_type": script_type,
        }

    def _document(
        self, raw_bytes: bytes, cfg: dict[str, object]
    ) -> tuple[Any | None, str | None]:
        if cfg["artifact_format"] == "direct_json":
            try:
                return decode_json_bytes(raw_bytes), None
            except JsonLexemeError:
                return None, "EVIDENCE_LOCATOR_INVALID"
        return decode_exact_json_script(
            raw_bytes,
            script_id=cfg["script_id"],
            script_type=cfg["script_type"],
        )

    def _category(
        self, data: Any, cfg: dict[str, object]
    ) -> tuple[int, dict[str, Any], list[Any]] | None:
        leaderboards, error = resolve_json_path(data, cfg["leaderboards_path"])
        if error or not isinstance(leaderboards, list):
            return None
        matches = [
            (index, category)
            for index, category in enumerate(leaderboards)
            if isinstance(category, dict)
            and source_text(category.get(cfg["category_name_field"])) == cfg["category"]
        ]
        if len(matches) != 1:
            return None
        category_index, category_data = matches[0]
        results = category_data.get(cfg["results_field"])
        if not isinstance(results, list):
            return None
        return category_index, category_data, results

    def extract_claims(
        self, source: OfficialSource, snapshot: SourceSnapshot, raw_bytes: bytes
    ) -> list[ResultClaimInput]:
        cfg = self._config(source)
        if cfg is None:
            return []
        data, error = self._document(raw_bytes, cfg)
        if error:
            return []
        category = self._category(data, cfg)
        if category is None:
            return []
        category_index, _category_data, results = category
        fields = {"model_raw": cfg["model_field"], "score_raw": cfg["score_field"]}
        record_prefix = (
            f"{cfg['leaderboards_path']}[{category_index}].{cfg['results_field']}"
        )
        assertion_path = f"{cfg['leaderboards_path']}[{category_index}].{cfg['category_name_field']}"
        claims: list[ResultClaimInput] = []
        for row_index, row in enumerate(results):
            if not isinstance(row, dict):
                continue
            model_raw = source_text(row.get(cfg["model_field"]))
            score_raw = source_score_lexeme(row.get(cfg["score_field"]))
            if model_raw is None or score_raw is None:
                continue
            if cfg["artifact_format"] == "direct_json":
                evidence_location: dict[str, object] = {
                    "type": "json_path_v1",
                    "record_path": f"{record_prefix}[{row_index}]",
                    "fields": fields,
                }
            else:
                evidence_location = {
                    "type": "json_script_path_v1",
                    "script_id": cfg["script_id"],
                    "script_type": cfg["script_type"],
                    "record_path": f"{record_prefix}[{row_index}]",
                    "fields": fields,
                    "assertions": [{"path": assertion_path, "equals": cfg["category"]}],
                }
            claims.append(
                ResultClaimInput(
                    official_source_id=source.id,
                    source_snapshot_id=snapshot.id,
                    benchmark_id=source.benchmark_id,
                    model_raw=model_raw,
                    benchmark_raw=source.benchmark_id or source.source_name,
                    score_raw=score_raw,
                    metric_raw=cfg["metric_raw"],
                    score_numeric=None,
                    evidence_location=evidence_location,
                    capture_method="swe_bench_adapter_parser",
                    capture_confidence=0.95,
                    capture_status="parser_verified",
                    officialness_level=source.officialness_level,
                )
            )
        return claims

    def validate_claim(self, claim: ResultClaimInput, raw_bytes: bytes) -> list[ClaimValidationInput]:
        locator = claim.evidence_location
        outcome = "uncertain"
        if isinstance(locator, dict):
            if locator.get("type") == "json_path_v1":
                try:
                    data = decode_json_bytes(raw_bytes)
                    error = None
                except JsonLexemeError:
                    data, error = None, "EVIDENCE_LOCATOR_INVALID"
            elif locator.get("type") == "json_script_path_v1":
                data, error = decode_exact_json_script(
                    raw_bytes,
                    script_id=locator.get("script_id"),
                    script_type=locator.get("script_type"),
                )
            else:
                data, error = None, "EVIDENCE_LOCATOR_INVALID"
            if not error:
                assertions = locator.get("assertions", [])
                assertions_match = isinstance(assertions, list) and all(
                    isinstance(assertion, dict)
                    and source_text(resolve_json_path(data, assertion.get("path"))[0])
                    == assertion.get("equals")
                    for assertion in assertions
                )
                record, record_error = resolve_json_path(data, locator.get("record_path"))
                fields = locator.get("fields")
                if (
                    assertions_match
                    and not record_error
                    and isinstance(record, dict)
                    and isinstance(fields, dict)
                    and isinstance(fields.get("model_raw"), str)
                    and isinstance(fields.get("score_raw"), str)
                    and source_text(record.get(fields["model_raw"])) == claim.model_raw
                    and source_score_lexeme(record.get(fields["score_raw"])) == claim.score_raw
                ):
                    outcome = "pass"
        return [
            ClaimValidationInput(
                validation_type="json_path_match",
                outcome=outcome,
                validator="SWEBenchAdapter",
            )
        ]
