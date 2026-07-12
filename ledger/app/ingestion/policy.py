from __future__ import annotations

from app.schemas.boundary import OfficialSource

TRUSTED_OFFICIALNESS_LEVELS = {"O5", "O4", "O3", "O2", "O1"}


def can_ingest_source(source: OfficialSource) -> bool:
    return source.status == "active" and source.officialness_level in TRUSTED_OFFICIALNESS_LEVELS
