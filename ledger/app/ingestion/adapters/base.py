from __future__ import annotations

from abc import ABC, abstractmethod

from app.db.models import SourceSnapshot
from app.schemas.boundary import (
    ClaimValidationInput,
    OfficialSource,
    ResultClaimInput,
    SourceFetchResult,
    SourceSnapshotInput,
)
from app.ingestion.safe_fetch import SafeFetchError


class SourceAdapter(ABC):
    source_type: str
    # Network-capable adapters inherit ``fetch`` below. Retired/test-only
    # adapters must opt out explicitly and never be selected for production.
    requires_central_fetch = True
    accepted_content_types: frozenset[str] = frozenset(
        {
            "application/json",
            "application/*+json",
            "text/json",
            "text/csv",
            "application/csv",
            "text/html",
            "application/xhtml+xml",
            "text/yaml",
            "text/x-yaml",
            "application/x-yaml",
        }
    )

    def fetch(self, source: OfficialSource) -> SourceFetchResult:
        """Reject adapter-owned acquisition; the runner supplies captured bytes."""

        _ = source
        raise SafeFetchError(
            "FETCH_PLAN_REQUIRED",
            "network artifacts must be fetched by the ingestion runner before adapter parsing",
        )

    def snapshot(self, source: OfficialSource, fetch_result: SourceFetchResult) -> SourceSnapshotInput:
        return SourceSnapshotInput(
            official_source_id=source.id,
            raw_bytes=fetch_result.raw_bytes,
            content_type=fetch_result.content_type,
            http_status=fetch_result.http_status,
            etag=fetch_result.etag,
            last_modified_header=fetch_result.last_modified_header,
            fetch_metadata={
                **(fetch_result.metadata or {}),
                "final_url": fetch_result.final_url,
                "headers": fetch_result.headers,
            },
        )

    @abstractmethod
    def extract_claims(
        self,
        source: OfficialSource,
        snapshot: SourceSnapshot,
        raw_bytes: bytes,
    ) -> list[ResultClaimInput]:
        """Extract exact raw claims from the snapshot."""

    def validate_claim(
        self,
        claim: ResultClaimInput,
        raw_bytes: bytes,
    ) -> list[ClaimValidationInput]:
        if claim.score_raw and claim.score_raw.encode("utf-8") in raw_bytes:
            return [
                ClaimValidationInput(
                    validation_type="source_contains_value",
                    outcome="pass",
                    validator=self.__class__.__name__,
                    notes="score_raw found in raw snapshot bytes",
                )
            ]
        # text fallback
        try:
            text = raw_bytes.decode("utf-8", errors="replace")
        except Exception:
            text = ""
        if claim.score_raw and claim.score_raw in text:
            return [
                ClaimValidationInput(
                    validation_type="source_contains_value",
                    outcome="pass",
                    validator=self.__class__.__name__,
                )
            ]
        return [
            ClaimValidationInput(
                validation_type="source_contains_value",
                outcome="uncertain",
                validator=self.__class__.__name__,
                notes="score_raw not found in raw bytes",
            )
        ]
