from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, StrictStr


class OfficialSource(BaseModel):
    id: str
    benchmark_id: str | None = None
    source_name: str
    source_url: str
    source_type: str
    officialness_level: str
    machine_readable: bool = False
    requires_auth: bool = False
    supports_history: bool = False
    update_cadence: str | None = None
    parser_name: str | None = None
    parser_version: str | None = None
    parser_config: dict[str, Any] = Field(default_factory=dict)
    status: str = "active"
    notes: str | None = None


class SourceFetchResult(BaseModel):
    raw_bytes: bytes
    content_type: str | None = None
    http_status: int | None = None
    etag: str | None = None
    last_modified_header: str | None = None
    final_url: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SourceSnapshotInput(BaseModel):
    official_source_id: str
    raw_bytes: bytes
    content_type: str | None = None
    http_status: int | None = None
    etag: str | None = None
    last_modified_header: str | None = None
    fetch_metadata: dict[str, Any] = Field(default_factory=dict)
    parser_version: str | None = None
    captured_at: datetime | None = None


class ResultClaimInput(BaseModel):
    source_snapshot_id: UUID | None = None
    source_revision_decision_id: UUID | None = None
    official_source_id: str
    benchmark_id: str | None = None
    model_entity_id: str | None = None
    model_raw: StrictStr
    benchmark_raw: StrictStr
    score_raw: StrictStr
    metric_raw: StrictStr | None = None
    split_raw: StrictStr | None = None
    setting_raw: StrictStr | None = None
    evaluation_version_raw: StrictStr | None = None
    rank_raw: StrictStr | None = None
    date_raw: StrictStr | None = None
    score_numeric: float | None = None
    score_unit: str | None = None
    evidence_text: str | None = None
    evidence_location: dict[str, Any] = Field(default_factory=dict)
    capture_method: str
    capture_confidence: float = 0.0
    capture_status: str = "unreviewed"
    scientific_status: str = "unknown"
    officialness_level: str | None = None
    claim_fingerprint: str | None = None


class ClaimValidationInput(BaseModel):
    result_claim_id: UUID | None = None
    validation_type: str
    outcome: str
    validator: str | None = None
    notes: str | None = None
