from __future__ import annotations

from urllib.parse import unquote, urlsplit

from app.schemas.boundary import OfficialSource

TRUSTED_OFFICIALNESS_LEVELS = {"O5", "O4", "O3", "O2", "O1"}

# Static containment deliberately makes production ingestion opt-in.  The
# officialness label is useful source metadata, but it is not a source-
# revision certification or publication decision.  The central LDR-05 resolver
# adds that immutable decision and typed-evidence requirement after this cheap
# first-pass classification.
REQUIRED_GOVERNANCE = {
    "production_eligible": True,
    "result_kind": "reported_result",
    "direct_source_only": True,
}

# These adapters/source forms are known not to be direct, source-reported
# result records in the current codebase.  They stay blocked even if somebody
# accidentally adds an optimistic governance flag to a registry entry.
BLOCKED_SOURCE_TYPES = {
    "fake",
    "fixture",
    "mock",
    "synthetic",
    "fallback",
    "html_table",
    "web_js_spa",
}
BLOCKED_PARSER_NAMES = {
    "fake",
    "hf_benchmark_api",  # dataset discovery metadata, not reported results
    "artificial_analysis_api",
    "lmsys_arena_api",
    "livebench_adapter",
    "livecodebench_adapter",
    "taubench_s3",
}
BLOCKED_ARTICLE_PATH_SEGMENTS = {
    "/article",
    "/blog",
    "/news",
    "/newsletter",
    "/post",
    "/press",
}

ARC_PRIZE_AUTOMATION_BLOCKED_ENDPOINTS = frozenset(
    {
        (
            "arcprize.org",
            "/media/data/leaderboard/v2.json",
        ),
    }
)


def _is_terms_blocked_endpoint(source_url: str) -> bool:
    parsed = urlsplit(source_url)
    host = (parsed.hostname or "").rstrip(".").casefold()
    path = unquote(parsed.path).rstrip("/").casefold()
    return (host, path) in ARC_PRIZE_AUTOMATION_BLOCKED_ENDPOINTS



def _is_preview_first_rows_endpoint(source_url: str) -> bool:
    """True for Hugging Face's preview-only first-rows dataset endpoint."""

    path = unquote(urlsplit(source_url).path).rstrip("/").casefold()
    return path.endswith("/first-rows")


def source_admission_reason(source: OfficialSource) -> str | None:
    """Return a stable fail-closed reason when a source cannot be ingested.

    This is an ingestion containment control, not a claim-publication policy.
    Official publication remains disabled until the later deterministic export
    and explicit publication-decision work is complete.
    """

    if source.status != "active":
        return "source is not active"
    if source.officialness_level not in TRUSTED_OFFICIALNESS_LEVELS:
        return "source officialness level is not trusted"
    if not source.machine_readable:
        return "source is not a structured machine-readable result feed"
    if source.source_type in BLOCKED_SOURCE_TYPES:
        return f"source type {source.source_type!r} is quarantined"
    if source.parser_name in BLOCKED_PARSER_NAMES:
        return f"parser {source.parser_name!r} is quarantined"
    if any(
        source.parser_config.get(marker) is True
        for marker in ("mock", "mock_used", "fallback", "fallback_used", "derived", "derived_score")
    ):
        return "mock, fallback, or derived source configuration is not a result source"
    if source.parser_config.get("mode") == "discovery":
        return "discovery metadata is not a result source"
    if _is_preview_first_rows_endpoint(source.source_url):
        return "preview first-rows endpoint is not a complete source artifact"
    if _is_terms_blocked_endpoint(source.source_url):
        return "source terms prohibit automated collection for this endpoint pending written permission"
    if source.parser_config.get("automation_collection_prohibited") is True:
        return "source terms prohibit automated collection pending an owner-approved exception"
    if any(segment in source.source_url.lower() for segment in BLOCKED_ARTICLE_PATH_SEGMENTS):
        return "blog/article sources are not result sources"

    governance = source.parser_config.get("governance")
    if not isinstance(governance, dict):
        return "missing governance declaration"
    for key, expected in REQUIRED_GOVERNANCE.items():
        if governance.get(key) != expected:
            return f"governance.{key} must be {expected!r}"
    return None


def can_ingest_source(source: OfficialSource) -> bool:
    """Whether a registry source is permitted through the Phase-0 boundary."""

    return source_admission_reason(source) is None
