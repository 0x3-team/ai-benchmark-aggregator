from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import JSON


def _uuid() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class Benchmark(Base):
    __tablename__ = "benchmarks"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    canonical_name: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    benchmark_family: Mapped[str | None] = mapped_column(String(128))
    description: Mapped[str | None] = mapped_column(Text)
    owner_name: Mapped[str | None] = mapped_column(String(255))
    owner_type: Mapped[str | None] = mapped_column(String(64))
    official_home_url: Mapped[str | None] = mapped_column(Text)
    official_repo_url: Mapped[str | None] = mapped_column(Text)
    official_dataset_url: Mapped[str | None] = mapped_column(Text)
    official_leaderboard_url: Mapped[str | None] = mapped_column(Text)
    official_docs_url: Mapped[str | None] = mapped_column(Text)
    has_official_leaderboard: Mapped[bool] = mapped_column(Boolean, default=False)
    has_official_result_api: Mapped[bool] = mapped_column(Boolean, default=False)
    has_official_result_files: Mapped[bool] = mapped_column(Boolean, default=False)
    has_private_test_set: Mapped[bool] = mapped_column(Boolean, default=False)
    primary_metric: Mapped[str | None] = mapped_column(String(128))
    known_metrics: Mapped[list] = mapped_column(JSON, default=list)
    known_splits: Mapped[list] = mapped_column(JSON, default=list)
    known_settings: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(32), default="active")
    superseded_by_benchmark_id: Mapped[str | None] = mapped_column(
        String(128), ForeignKey("benchmarks.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class ModelEntity(Base):
    __tablename__ = "model_entities"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    canonical_name: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str | None] = mapped_column(String(128))
    developer: Mapped[str | None] = mapped_column(String(128))
    model_family: Mapped[str | None] = mapped_column(String(128))
    access_type: Mapped[str | None] = mapped_column(String(64))
    official_model_url: Mapped[str | None] = mapped_column(Text)
    official_docs_url: Mapped[str | None] = mapped_column(Text)
    official_card_url: Mapped[str | None] = mapped_column(Text)
    official_repo_url: Mapped[str | None] = mapped_column(Text)
    official_hf_repo: Mapped[str | None] = mapped_column(String(255))
    api_model_id: Mapped[str | None] = mapped_column(String(255))
    api_version: Mapped[str | None] = mapped_column(String(128))
    endpoint_fingerprint: Mapped[str | None] = mapped_column(String(255))
    artifact_hash: Mapped[str | None] = mapped_column(String(128))
    weights_revision: Mapped[str | None] = mapped_column(String(128))
    tokenizer_revision: Mapped[str | None] = mapped_column(String(128))
    base_model_entity_id: Mapped[str | None] = mapped_column(
        String(128), ForeignKey("model_entities.id"), nullable=True
    )
    release_date: Mapped[date | None] = mapped_column(Date)
    deprecation_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(32), default="active")
    context_window: Mapped[int | None] = mapped_column(Integer)
    modalities: Mapped[list] = mapped_column(JSON, default=list)
    license: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class Alias(Base):
    __tablename__ = "aliases"
    __table_args__ = (UniqueConstraint("entity_type", "entity_id", "alias_text", name="uq_alias"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(128), nullable=False)
    alias_text: Mapped[str] = mapped_column(String(512), nullable=False)
    alias_source: Mapped[str | None] = mapped_column(String(255))
    source_url: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    is_official_alias: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class OfficialSourceRow(Base):
    __tablename__ = "official_sources"
    __table_args__ = (UniqueConstraint("benchmark_id", "source_url", name="uq_source_url"),)

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    benchmark_id: Mapped[str | None] = mapped_column(String(128), ForeignKey("benchmarks.id"))
    source_name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[str] = mapped_column(String(64), nullable=False)
    officialness_level: Mapped[str] = mapped_column(String(8), nullable=False)
    machine_readable: Mapped[bool] = mapped_column(Boolean, default=False)
    requires_auth: Mapped[bool] = mapped_column(Boolean, default=False)
    supports_history: Mapped[bool] = mapped_column(Boolean, default=False)
    update_cadence: Mapped[str | None] = mapped_column(String(64))
    parser_name: Mapped[str | None] = mapped_column(String(128))
    parser_version: Mapped[str | None] = mapped_column(String(64))
    parser_config: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(32), default="active")
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class SourceSnapshot(Base):
    __tablename__ = "source_snapshots"
    __table_args__ = (
        UniqueConstraint("official_source_id", "content_hash", name="uq_source_hash"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    official_source_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("official_sources.id"), nullable=False
    )
    captured_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    raw_content_uri: Mapped[str] = mapped_column(Text, nullable=False)
    rendered_screenshot_uri: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(128))
    http_status: Mapped[int | None] = mapped_column(Integer)
    etag: Mapped[str | None] = mapped_column(String(255))
    last_modified_header: Mapped[str | None] = mapped_column(String(255))
    fetch_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
    parser_version: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ResultClaim(Base):
    __tablename__ = "result_claims"
    __table_args__ = (
        UniqueConstraint("source_snapshot_id", "claim_fingerprint", name="uq_claim_fp"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    source_snapshot_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("source_snapshots.id"), nullable=False
    )
    official_source_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("official_sources.id"), nullable=False
    )
    benchmark_id: Mapped[str | None] = mapped_column(String(128), ForeignKey("benchmarks.id"))
    model_entity_id: Mapped[str | None] = mapped_column(String(128), ForeignKey("model_entities.id"))
    model_raw: Mapped[str] = mapped_column(String(512), nullable=False)
    benchmark_raw: Mapped[str] = mapped_column(String(512), nullable=False)
    score_raw: Mapped[str] = mapped_column(String(128), nullable=False)
    metric_raw: Mapped[str | None] = mapped_column(String(128))
    split_raw: Mapped[str | None] = mapped_column(String(128))
    setting_raw: Mapped[str | None] = mapped_column(String(255))
    rank_raw: Mapped[str | None] = mapped_column(String(64))
    date_raw: Mapped[str | None] = mapped_column(String(64))
    score_numeric: Mapped[float | None] = mapped_column(Float)
    score_unit: Mapped[str | None] = mapped_column(String(32))
    evidence_text: Mapped[str | None] = mapped_column(Text)
    evidence_location: Mapped[dict] = mapped_column(JSON, default=dict)
    capture_method: Mapped[str] = mapped_column(String(64), nullable=False)
    capture_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    capture_status: Mapped[str] = mapped_column(String(32), default="unreviewed")
    scientific_status: Mapped[str] = mapped_column(String(64), default="unknown")
    officialness_level: Mapped[str | None] = mapped_column(String(8))
    claim_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ClaimValidation(Base):
    __tablename__ = "claim_validations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    result_claim_id: Mapped[str] = mapped_column(String(36), ForeignKey("result_claims.id"), nullable=False)
    validation_type: Mapped[str] = mapped_column(String(64), nullable=False)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    validator: Mapped[str | None] = mapped_column(String(128))
    notes: Mapped[str | None] = mapped_column(Text)
    validated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ClaimRelationship(Base):
    __tablename__ = "claim_relationships"
    __table_args__ = (
        UniqueConstraint("claim_id", "related_claim_id", "relationship_type", name="uq_claim_rel"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    claim_id: Mapped[str] = mapped_column(String(36), ForeignKey("result_claims.id"), nullable=False)
    related_claim_id: Mapped[str] = mapped_column(String(36), ForeignKey("result_claims.id"), nullable=False)
    relationship_type: Mapped[str] = mapped_column(String(64), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class IngestionRun(Base):
    __tablename__ = "ingestion_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    started_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    run_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="running")
    official_source_id: Mapped[str | None] = mapped_column(String(128), ForeignKey("official_sources.id"))
    sources_checked: Mapped[int] = mapped_column(Integer, default=0)
    snapshots_created: Mapped[int] = mapped_column(Integer, default=0)
    snapshots_reused: Mapped[int] = mapped_column(Integer, default=0)
    claims_extracted: Mapped[int] = mapped_column(Integer, default=0)
    claims_inserted: Mapped[int] = mapped_column(Integer, default=0)
    claims_unchanged: Mapped[int] = mapped_column(Integer, default=0)
    claims_needing_review: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
