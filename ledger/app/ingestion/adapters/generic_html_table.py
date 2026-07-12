from __future__ import annotations

import re

import httpx
from bs4 import BeautifulSoup

from app.config import get_settings
from app.db.models import SourceSnapshot
from app.ingestion.adapters.base import SourceAdapter
from app.ingestion.extractors.normalize import try_parse_score
from app.schemas.boundary import OfficialSource, ResultClaimInput, SourceFetchResult

# Zero-width and invisible characters to strip from headers.
_ZERO_WIDTH_RE = re.compile("[\u200b-\u200f\u2060\ufeff\u00ad]")


def _normalize_header(text: str) -> str:
    """Collapse all whitespace (incl. newlines/tabs/nbsp) and strip surrounding space.

    Real-world leaderboards often embed newlines or use non-breaking spaces and
    wrapping whitespace inside header cells; we must match on normalized text.

    Also strips zero-width spaces, word joiners, BOM, and soft hyphens.
    """
    text = _ZERO_WIDTH_RE.sub("", text)
    text = text.replace("\xa0", " ")  # nbsp → space
    return " ".join(text.split()).strip()


def _normalize_header_key(text: str) -> str:
    """Normalize a header for case-insensitive key matching."""
    return _normalize_header(text).lower()


class GenericHTMLTableAdapter(SourceAdapter):
    source_type = "html_table"

    # Optional column config keys that map to claim fields.
    _OPTIONAL_COLUMNS = {
        "metric_column": "metric_raw",
        "split_column": "split_raw",
        "rank_column": "rank_raw",
        "date_column": "date_raw",
    }

    def fetch(self, source: OfficialSource) -> SourceFetchResult:
        settings = get_settings()
        try:
            with httpx.Client(timeout=settings.http_timeout_seconds, follow_redirects=True) as client:
                resp = client.get(source.source_url, headers={"User-Agent": settings.http_user_agent})
        except httpx.HTTPError as exc:
            raise RuntimeError(
                f"Network error fetching HTML leaderboard for source={source.id}: {exc}"
            ) from exc
        if resp.status_code >= 400:
            raise RuntimeError(
                f"HTTP {resp.status_code} fetching HTML leaderboard for source={source.id} "
                f"({source.source_url})"
            )
        return SourceFetchResult(
            raw_bytes=resp.content,
            content_type=resp.headers.get("content-type", "text/html"),
            http_status=resp.status_code,
            final_url=str(resp.url),
        )

    def extract_claims(
        self, source: OfficialSource, snapshot: SourceSnapshot, raw_bytes: bytes
    ) -> list[ResultClaimInput]:
        cfg = source.parser_config or {}
        model_column = cfg.get("model_column", "Model")
        score_column = cfg.get("score_column", "Score")
        table_index = int(cfg.get("table_index", 0))
        soup = BeautifulSoup(raw_bytes, "lxml")
        tables = soup.find_all("table")
        table, table_index = self._select_table(tables, cfg, table_index)
        if table is None:
            return []

        header_row = table.find("tr")
        if not header_row:
            return []

        headers_display = [_normalize_header(c.get_text()) for c in header_row.find_all(["th", "td"])]
        headers_key = [h.lower() for h in headers_display]

        # Resolve required columns case-insensitively.
        try:
            model_idx = headers_key.index(_normalize_header_key(model_column))
            score_idx = headers_key.index(_normalize_header_key(score_column))
        except ValueError:
            return []

        # Resolve optional columns case-insensitively.
        optional_indices: dict[str, int] = {}
        for cfg_key, claim_field in self._OPTIONAL_COLUMNS.items():
            col_name = cfg.get(cfg_key)
            if col_name:
                try:
                    optional_indices[claim_field] = headers_key.index(_normalize_header_key(col_name))
                except ValueError:
                    pass  # column not present — skip gracefully

        claims: list[ResultClaimInput] = []
        rows = table.find_all("tr")[1:]
        for r_i, tr in enumerate(rows):
            # Read exact cell text; strip outer whitespace but preserve inner content.
            cells = [c.get_text().strip() for c in tr.find_all(["td", "th"])]
            max_needed = max([model_idx, score_idx] + list(optional_indices.values()), default=0)
            if len(cells) <= max_needed:
                continue
            model_raw = cells[model_idx]
            score_raw = cells[score_idx]
            if not model_raw or not score_raw:
                continue

            claim_kwargs: dict = {
                "official_source_id": source.id,
                "source_snapshot_id": snapshot.id,
                "benchmark_id": source.benchmark_id,
                "model_raw": model_raw,
                "benchmark_raw": source.benchmark_id or source.source_name,
                "score_raw": score_raw,
                "metric_raw": score_column,
                "score_numeric": try_parse_score(score_raw),
                "evidence_location": {
                    "type": "html_table_cell",
                    "table_index": table_index,
                    "row_index": r_i,
                    "column_name": score_column,
                    "model_column": model_column,
                },
                "capture_method": "html_table_parser",
                "capture_confidence": 0.9,
                "capture_status": "parser_verified",
                "officialness_level": source.officialness_level,
            }

            # Attach optional column values.
            for claim_field, idx in optional_indices.items():
                if idx < len(cells) and cells[idx]:
                    claim_kwargs[claim_field] = cells[idx]

            claims.append(ResultClaimInput(**claim_kwargs))
        return claims

    def _select_table(self, tables: list, cfg: dict, table_index: int):
        """Pick the table by index, falling back to a table_hint substring search.

        If *table_index* is within range but the table does not contain the
        required columns (case-insensitive normalized match), the method falls
        back to scanning all tables for *table_hint*, then to a full column
        scan.  Returns ``(table, chosen_index)``.
        """
        model_col = _normalize_header_key(cfg.get("model_column", "Model"))
        score_col = _normalize_header_key(cfg.get("score_column", "Score"))
        expected_cols = {model_col, score_col}

        def _headers_at(idx: int) -> set[str]:
            tr = tables[idx].find("tr")
            if not tr:
                return set()
            return {_normalize_header_key(c.get_text()) for c in tr.find_all(["th", "td"])}

        if tables:
            # 1) Try the requested table_index.
            if table_index < len(tables):
                if expected_cols.issubset(_headers_at(table_index)):
                    return tables[table_index], table_index

            # 2) Fallback: table_hint substring search across ALL tables.
            table_hint = cfg.get("table_hint")
            if table_hint:
                hint = _normalize_header_key(table_hint)
                for i, t in enumerate(tables):
                    text = _normalize_header_key(t.get_text(" "))
                    if hint in text:
                        return t, i

            # 3) Last resort: scan all tables for matching columns.
            for i, t in enumerate(tables):
                if expected_cols.issubset(_headers_at(i)):
                    return t, i

        return None, table_index
