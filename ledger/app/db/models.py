from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import JSON


# SQLite keeps its existing JSON/text and timestamp behavior. PostgreSQL's
# production head deliberately converts these columns to JSONB and TIMESTAMPTZ;
# the ORM must bind against those same native types instead of silently
# reintroducing naive wall-clock values or generic JSON semantics.
JSON_DOCUMENT = JSON().with_variant(JSONB(), "postgresql")
UTC_TIMESTAMP = DateTime(timezone=True)


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
    known_metrics: Mapped[list] = mapped_column(JSON_DOCUMENT, default=list)
    known_splits: Mapped[list] = mapped_column(JSON_DOCUMENT, default=list)
    known_settings: Mapped[list] = mapped_column(JSON_DOCUMENT, default=list)
    status: Mapped[str] = mapped_column(String(32), default="active")
    superseded_by_benchmark_id: Mapped[str | None] = mapped_column(
        String(128), ForeignKey("benchmarks.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, server_default=func.now(), onupdate=func.now())


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
    modalities: Mapped[list] = mapped_column(JSON_DOCUMENT, default=list)
    license: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, server_default=func.now(), onupdate=func.now())


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
    created_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, server_default=func.now())


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
    parser_config: Mapped[dict] = mapped_column(JSON_DOCUMENT, default=dict)
    status: Mapped[str] = mapped_column(String(32), default="active")
    notes: Mapped[str | None] = mapped_column(Text)
    # These fields are the current catalog projection, not the historical
    # source definition. The immutable definition is held by
    # OfficialSourceRevision; SQLite triggers permit a projection change only
    # when it exactly matches a newly selected source revision.
    current_revision_id: Mapped[str | None] = mapped_column(String(36))
    registry_managed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, server_default=func.now(), onupdate=func.now())


class OfficialSourceRevision(Base):
    """An immutable capture-time definition for one logical official source."""

    __tablename__ = "official_source_revisions"
    __table_args__ = (
        UniqueConstraint("official_source_id", "revision_ordinal", name="uq_source_revision_ordinal"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    official_source_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("official_sources.id"), nullable=False
    )
    revision_ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    definition_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    definition_json: Mapped[dict] = mapped_column(JSON_DOCUMENT, nullable=False)
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
    parser_config: Mapped[dict] = mapped_column(JSON_DOCUMENT, default=dict)
    status: Mapped[str] = mapped_column(String(32), default="active")
    notes: Mapped[str | None] = mapped_column(Text)
    origin: Mapped[str] = mapped_column(String(64), nullable=False)
    supersedes_revision_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("official_source_revisions.id")
    )
    created_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, server_default=func.now())


class SourceRevisionDecision(Base):
    """Append-only certification/quarantine decisions for a source revision."""

    __tablename__ = "source_revision_decisions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    source_revision_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("official_source_revisions.id"), nullable=False
    )
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(128), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(128), nullable=False)
    basis_json: Mapped[dict] = mapped_column(JSON_DOCUMENT, default=dict)
    actor: Mapped[str | None] = mapped_column(String(128))
    supersedes_decision_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("source_revision_decisions.id")
    )
    decided_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, server_default=func.now())


class SourceSnapshot(Base):
    __tablename__ = "source_snapshots"
    __table_args__ = (
        UniqueConstraint("source_revision_id", "content_hash", name="uq_source_revision_hash"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    official_source_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("official_sources.id"), nullable=False
    )
    source_revision_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("official_source_revisions.id"), nullable=False
    )
    captured_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, server_default=func.now())
    raw_content_uri: Mapped[str] = mapped_column(Text, nullable=False)
    rendered_screenshot_uri: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(128))
    http_status: Mapped[int | None] = mapped_column(Integer)
    etag: Mapped[str | None] = mapped_column(String(255))
    last_modified_header: Mapped[str | None] = mapped_column(String(255))
    fetch_metadata: Mapped[dict] = mapped_column(JSON_DOCUMENT, default=dict)
    parser_version: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, server_default=func.now())


class ResultClaim(Base):
    __tablename__ = "result_claims"
    __table_args__ = (
        UniqueConstraint("source_snapshot_id", "claim_fingerprint", name="uq_claim_fp"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    source_snapshot_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("source_snapshots.id"), nullable=False
    )
    source_revision_decision_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("source_revision_decisions.id")
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
    evaluation_version_raw: Mapped[str | None] = mapped_column(String(128))
    rank_raw: Mapped[str | None] = mapped_column(String(64))
    date_raw: Mapped[str | None] = mapped_column(String(64))
    score_numeric: Mapped[float | None] = mapped_column(Float)
    score_unit: Mapped[str | None] = mapped_column(String(32))
    evidence_text: Mapped[str | None] = mapped_column(Text)
    evidence_location: Mapped[dict] = mapped_column(JSON_DOCUMENT, default=dict)
    capture_method: Mapped[str] = mapped_column(String(64), nullable=False)
    capture_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    capture_status: Mapped[str] = mapped_column(String(32), default="unreviewed")
    scientific_status: Mapped[str] = mapped_column(String(64), default="unknown")
    officialness_level: Mapped[str | None] = mapped_column(String(8))
    claim_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, server_default=func.now())


class ClaimReviewDecision(Base):
    """Append-only resolution of claim identity and review status."""

    __tablename__ = "claim_review_decisions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    result_claim_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("result_claims.id"), nullable=False
    )
    model_entity_id: Mapped[str | None] = mapped_column(
        String(128), ForeignKey("model_entities.id")
    )
    benchmark_id: Mapped[str | None] = mapped_column(String(128), ForeignKey("benchmarks.id"))
    metric: Mapped[str | None] = mapped_column(String(128))
    split: Mapped[str | None] = mapped_column(String(128))
    setting: Mapped[str | None] = mapped_column(String(255))
    evaluation_version: Mapped[str | None] = mapped_column(String(128))
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(128), nullable=False)
    basis_json: Mapped[dict] = mapped_column(JSON_DOCUMENT, default=dict)
    actor: Mapped[str | None] = mapped_column(String(128))
    supersedes_decision_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("claim_review_decisions.id")
    )
    decided_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, server_default=func.now())


class ClaimPublicationDecision(Base):
    """Append-only publication eligibility decision for a reviewed claim."""

    __tablename__ = "claim_publication_decisions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    result_claim_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("result_claims.id"), nullable=False
    )
    claim_review_decision_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("claim_review_decisions.id"), nullable=False
    )
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(128), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(128), nullable=False)
    basis_json: Mapped[dict] = mapped_column(JSON_DOCUMENT, default=dict)
    actor: Mapped[str | None] = mapped_column(String(128))
    supersedes_decision_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("claim_publication_decisions.id")
    )
    decided_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, server_default=func.now())


class ClaimValidation(Base):
    __tablename__ = "claim_validations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    result_claim_id: Mapped[str] = mapped_column(String(36), ForeignKey("result_claims.id"), nullable=False)
    validation_type: Mapped[str] = mapped_column(String(64), nullable=False)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    validator: Mapped[str | None] = mapped_column(String(128))
    notes: Mapped[str | None] = mapped_column(Text)
    validated_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, server_default=func.now())


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
    created_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, server_default=func.now())


class IngestionRun(Base):
    __tablename__ = "ingestion_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    started_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(UTC_TIMESTAMP)
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
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON_DOCUMENT, default=dict)


class ScheduledCycleIntent(Base):
    """Immutable pre-dispatch truth for one deterministic scheduler slot."""

    __tablename__ = "scheduled_cycle_intents"
    __table_args__ = (
        UniqueConstraint(
            "environment",
            "lane",
            "scheduled_for",
            "schedule_policy_revision_id",
            name="uq_scheduled_cycle_intent_slot",
        ),
        ForeignKeyConstraint(
            ["cycle_id", "intent_sha256"],
            [
                "scheduled_cycle_intent_completions.cycle_id",
                "scheduled_cycle_intent_completions.intent_sha256",
            ],
            name="fk_cycle_intent_completion",
            deferrable=True,
            initially="DEFERRED",
        ),
    )

    cycle_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    environment: Mapped[str] = mapped_column(String(128), nullable=False)
    lane: Mapped[str] = mapped_column(String(32), nullable=False)
    scheduled_for: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, nullable=False)
    schedule_policy_revision_id: Mapped[str] = mapped_column(String(128), nullable=False)
    mode: Mapped[str] = mapped_column(String(32), nullable=False)
    job_count: Mapped[int] = mapped_column(Integer, nullable=False)
    intent_sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    payload_json: Mapped[dict] = mapped_column(JSON_DOCUMENT, nullable=False)


class ScheduledCycleIntentCompletion(Base):
    """Immutable commit-complete sentinel for a pre-dispatch job set."""

    __tablename__ = "scheduled_cycle_intent_completions"
    __table_args__ = (
        UniqueConstraint("cycle_id", "intent_sha256", name="uq_cycle_intent_completion"),
    )

    cycle_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("scheduled_cycle_intents.cycle_id"), primary_key=True
    )
    intent_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    job_count: Mapped[int] = mapped_column(Integer, nullable=False)


class ScheduledCycle(Base):
    """Immutable terminal receipt appended only after scheduled work concludes."""

    __tablename__ = "scheduled_cycles"
    __table_args__ = (
        UniqueConstraint(
            "environment",
            "lane",
            "scheduled_for",
            "schedule_policy_revision_id",
            name="uq_scheduled_cycle_slot",
        ),
    )

    cycle_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("scheduled_cycle_intents.cycle_id"),
        primary_key=True,
    )
    environment: Mapped[str] = mapped_column(String(128), nullable=False)
    lane: Mapped[str] = mapped_column(String(32), nullable=False)
    scheduled_for: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, nullable=False)
    schedule_policy_revision_id: Mapped[str] = mapped_column(String(128), nullable=False)
    mode: Mapped[str] = mapped_column(String(32), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    payload_json: Mapped[dict] = mapped_column(JSON_DOCUMENT, nullable=False)


class ScheduledJobIntent(Base):
    """Immutable logical work identity recorded before worker dispatch."""

    __tablename__ = "scheduled_job_intents"
    __table_args__ = (
        UniqueConstraint(
            "environment",
            "lane",
            "target_revision_id",
            "scheduled_for",
            "schedule_policy_revision_id",
            name="uq_scheduled_job_slot",
        ),
        UniqueConstraint("idempotency_key_sha256", name="uq_scheduled_job_idempotency"),
    )

    job_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    cycle_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("scheduled_cycle_intents.cycle_id"), nullable=False
    )
    environment: Mapped[str] = mapped_column(String(128), nullable=False)
    lane: Mapped[str] = mapped_column(String(32), nullable=False)
    target_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_revision_id: Mapped[str] = mapped_column(String(128), nullable=False)
    source_revision_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("official_source_revisions.id")
    )
    scheduled_for: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, nullable=False)
    schedule_policy_revision_id: Mapped[str] = mapped_column(String(128), nullable=False)
    idempotency_key_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    due_disposition: Mapped[str] = mapped_column(String(32), nullable=False)
    disposition_reason_code: Mapped[str] = mapped_column(String(128), nullable=False)
    intent_sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    payload_json: Mapped[dict] = mapped_column(JSON_DOCUMENT, nullable=False)


class ScheduledJobLeaseEvent(Base):
    """Immutable acquisition lineage behind the mutable current-lease row."""

    __tablename__ = "scheduled_job_lease_events"
    __table_args__ = (
        UniqueConstraint("job_id", "fencing_token", name="uq_job_lease_token"),
    )

    lease_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    job_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("scheduled_job_intents.job_id"), nullable=False
    )
    fencing_token: Mapped[int] = mapped_column(Integer, nullable=False)
    prior_lease_id: Mapped[str | None] = mapped_column(
        String(128), ForeignKey("scheduled_job_lease_events.lease_id")
    )
    worker_identity_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    acquired_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, nullable=False)
    initial_heartbeat_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, nullable=False)


class ScheduledJobLease(Base):
    """The sole mutable coordination projection; evidence lives in lease events."""

    __tablename__ = "scheduled_job_leases"
    __table_args__ = (
        UniqueConstraint("current_lease_id", name="uq_current_job_lease_event"),
    )

    job_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("scheduled_job_intents.job_id"), primary_key=True
    )
    current_lease_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("scheduled_job_lease_events.lease_id"), nullable=False
    )
    fencing_token: Mapped[int] = mapped_column(Integer, nullable=False)
    worker_identity_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    acquired_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, nullable=False)
    last_heartbeat_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)


class ScheduledJobAttempt(Base):
    """Immutable scheduled-job-attempt-v1 contract and exact lease binding."""

    __tablename__ = "scheduled_job_attempts"
    __table_args__ = (
        UniqueConstraint("job_id", "attempt_number", name="uq_job_attempt_number"),
        UniqueConstraint("job_id", "fencing_token", name="uq_job_attempt_token"),
    )

    attempt_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    cycle_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("scheduled_cycle_intents.cycle_id"), nullable=False
    )
    job_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("scheduled_job_intents.job_id"), nullable=False
    )
    lease_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("scheduled_job_lease_events.lease_id"), nullable=False
    )
    source_revision_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("official_source_revisions.id")
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    fencing_token: Mapped[int] = mapped_column(Integer, nullable=False)
    prior_fencing_token: Mapped[int | None] = mapped_column(Integer)
    worker_identity_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    lease_acquired_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, nullable=False)
    lease_expires_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, nullable=False)
    lease_last_heartbeat_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, nullable=False)
    started_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, nullable=False)
    ended_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, nullable=False)
    stage_reached: Mapped[str] = mapped_column(String(64), nullable=False)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    commit_disposition: Mapped[str] = mapped_column(String(32), nullable=False)
    source_check_receipt_id: Mapped[str | None] = mapped_column(
        String(128),
        ForeignKey(
            "source_check_receipts.receipt_id",
            name="fk_job_attempt_source_check",
            deferrable=True,
            initially="DEFERRED",
        ),
    )
    source_check_receipt_sha256: Mapped[str | None] = mapped_column(String(64))
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    payload_json: Mapped[dict] = mapped_column(JSON_DOCUMENT, nullable=False)


class SourceContractEnvelope(Base):
    """Immutable, non-authorizing source-contract-v2 bytes used as evidence."""

    __tablename__ = "source_contract_envelopes"

    contract_revision_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    contract_id: Mapped[str] = mapped_column(String(128), nullable=False)
    supersedes_contract_revision_id: Mapped[str | None] = mapped_column(
        String(128), ForeignKey("source_contract_envelopes.contract_revision_id")
    )
    official_source_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("official_sources.id"), nullable=False
    )
    source_revision_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("official_source_revisions.id"), nullable=False
    )
    certification_decision_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("source_revision_decisions.id")
    )
    certification_decision_sha256: Mapped[str | None] = mapped_column(String(64))
    schedule_policy_revision_id: Mapped[str] = mapped_column(String(128), nullable=False)
    lifecycle_status: Mapped[str] = mapped_column(String(32), nullable=False)
    contract_digest_sha256: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True
    )
    contract_definition_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[dict] = mapped_column(JSON_DOCUMENT, nullable=False)


class SourceCheckReceiptRecord(Base):
    """Immutable source-check-receipt-v1 evidence, never an authority decision."""

    __tablename__ = "source_check_receipts"
    __table_args__ = (
        UniqueConstraint("attempt_id", name="uq_source_check_attempt"),
    )

    receipt_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    attempt_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("scheduled_job_attempts.attempt_id"), nullable=False
    )
    job_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("scheduled_job_intents.job_id"), nullable=False
    )
    official_source_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("official_sources.id"), nullable=False
    )
    source_revision_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("official_source_revisions.id"), nullable=False
    )
    source_revision_decision_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("source_revision_decisions.id")
    )
    source_revision_decision_sha256: Mapped[str | None] = mapped_column(String(64))
    checked_source_revision_decision_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("source_revision_decisions.id")
    )
    checked_source_revision_decision_sha256: Mapped[str | None] = mapped_column(String(64))
    certification_check_outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    contract_id: Mapped[str] = mapped_column(String(128), nullable=False)
    contract_revision_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("source_contract_envelopes.contract_revision_id"), nullable=False
    )
    contract_digest_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    contract_definition_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    schedule_policy_revision_id: Mapped[str] = mapped_column(String(128), nullable=False)
    scheduled_for: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, nullable=False)
    fencing_token: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("source_snapshots.id")
    )
    snapshot_content_sha256: Mapped[str | None] = mapped_column(String(64))
    snapshot_storage_receipt_sha256: Mapped[str | None] = mapped_column(String(64))
    previous_snapshot_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("source_snapshots.id")
    )
    previous_snapshot_content_sha256: Mapped[str | None] = mapped_column(String(64))
    previous_snapshot_verification_receipt_sha256: Mapped[str | None] = mapped_column(String(64))
    batch_receipt_sha256: Mapped[str | None] = mapped_column(String(64))
    terminal_disposition: Mapped[str] = mapped_column(String(64), nullable=False)
    started_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, nullable=False)
    finished_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    payload_json: Mapped[dict] = mapped_column(JSON_DOCUMENT, nullable=False)


class ExtractionBatch(Base):
    """Accounting-only extraction projection from one validated check receipt."""

    __tablename__ = "extraction_batches"
    __table_args__ = (
        UniqueConstraint("source_check_receipt_id", name="uq_extraction_receipt"),
    )

    batch_receipt_sha256: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_check_receipt_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("source_check_receipts.receipt_id"), nullable=False
    )
    attempt_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("scheduled_job_attempts.attempt_id"), nullable=False
    )
    job_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("scheduled_job_intents.job_id"), nullable=False
    )
    source_revision_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("official_source_revisions.id"), nullable=False
    )
    source_revision_decision_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("source_revision_decisions.id")
    )
    snapshot_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("source_snapshots.id")
    )
    schema_fingerprint_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_records_observed: Mapped[int] = mapped_column(Integer, nullable=False)
    rows_parsed: Mapped[int] = mapped_column(Integer, nullable=False)
    claim_candidates_emitted: Mapped[int] = mapped_column(Integer, nullable=False)
    claims_admitted: Mapped[int] = mapped_column(Integer, nullable=False)
    records_excluded: Mapped[int] = mapped_column(Integer, nullable=False)
    records_rejected: Mapped[int] = mapped_column(Integer, nullable=False)
    records_quarantined: Mapped[int] = mapped_column(Integer, nullable=False)
    payload_json: Mapped[dict] = mapped_column(JSON_DOCUMENT, nullable=False)


class DiscoveryCandidate(Base):
    """Immutable, quarantined discovery-candidate-v1 proposal."""

    __tablename__ = "discovery_candidates"

    candidate_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    candidate_fingerprint_sha256: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True
    )
    candidate_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_revision_id: Mapped[str] = mapped_column(String(128), nullable=False)
    state: Mapped[str] = mapped_column(String(64), nullable=False)
    state_decision_reference: Mapped[str | None] = mapped_column(String(128))
    approved_source_revision_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("official_source_revisions.id")
    )
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    payload_json: Mapped[dict] = mapped_column(JSON_DOCUMENT, nullable=False)


class BenchmarkDefinitionRevision(Base):
    """Immutable benchmark-definition-revision-v1 contract."""

    __tablename__ = "benchmark_definition_revisions"

    benchmark_definition_revision_id: Mapped[str] = mapped_column(
        String(128), primary_key=True
    )
    benchmark_family_id: Mapped[str] = mapped_column(String(128), nullable=False)
    benchmark_edition_id: Mapped[str] = mapped_column(String(128), nullable=False)
    supersedes_definition_revision_id: Mapped[str | None] = mapped_column(
        String(128), ForeignKey("benchmark_definition_revisions.benchmark_definition_revision_id")
    )
    lifecycle_status: Mapped[str] = mapped_column(String(32), nullable=False)
    decision_reference: Mapped[str | None] = mapped_column(String(128))
    dimension_fingerprint_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    payload_json: Mapped[dict] = mapped_column(JSON_DOCUMENT, nullable=False)


class EvaluationSubjectRevision(Base):
    """Immutable evaluation-subject-v1 revision with exact raw composition."""

    __tablename__ = "evaluation_subject_revisions"

    subject_revision_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    subject_id: Mapped[str] = mapped_column(String(128), nullable=False)
    supersedes_subject_revision_id: Mapped[str | None] = mapped_column(
        String(128), ForeignKey("evaluation_subject_revisions.subject_revision_id")
    )
    subject_type: Mapped[str] = mapped_column(String(64), nullable=False)
    lifecycle_status: Mapped[str] = mapped_column(String(32), nullable=False)
    resolution_status: Mapped[str] = mapped_column(String(32), nullable=False)
    decision_reference: Mapped[str | None] = mapped_column(String(128))
    subject_fingerprint_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    observed_composition_fingerprint_sha256: Mapped[str] = mapped_column(
        String(64), nullable=False
    )
    raw_identity_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    model_entity_id: Mapped[str | None] = mapped_column(
        String(128), ForeignKey("model_entities.id")
    )
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    payload_json: Mapped[dict] = mapped_column(JSON_DOCUMENT, nullable=False)


class IdentityDecisionRecord(Base):
    """Append-only identity-decision-v1 chain for one discovery candidate."""

    __tablename__ = "identity_decisions"
    __table_args__ = (
        UniqueConstraint(
            "candidate_reference", "decision_sequence", name="uq_identity_decision_sequence"
        ),
    )

    decision_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    candidate_reference: Mapped[str] = mapped_column(
        String(128), ForeignKey("discovery_candidates.candidate_id"), nullable=False
    )
    observation_reference: Mapped[str] = mapped_column(String(128), nullable=False)
    identity_item_fingerprint_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    expected_prior_decision_id: Mapped[str | None] = mapped_column(
        String(128), ForeignKey("identity_decisions.decision_id")
    )
    decision_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    decision_status: Mapped[str] = mapped_column(String(32), nullable=False)
    decided_at: Mapped[datetime | None] = mapped_column(UTC_TIMESTAMP)
    selected_subject_id: Mapped[str | None] = mapped_column(String(128))
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    payload_json: Mapped[dict] = mapped_column(JSON_DOCUMENT, nullable=False)


class OpsIncident(Base):
    """Stable incident identity; mutable-looking state is derived from events."""

    __tablename__ = "ops_incidents"

    incident_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    incident_fingerprint_sha256: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True
    )
    family: Mapped[str] = mapped_column(String(64), nullable=False)
    incident_code: Mapped[str] = mapped_column(String(128), nullable=False)
    cause_code: Mapped[str] = mapped_column(String(128), nullable=False)
    environment: Mapped[str] = mapped_column(String(128), nullable=False)
    first_contract_sha256: Mapped[str] = mapped_column(String(64), nullable=False)


class OpsIncidentEvent(Base):
    """One immutable event in a single incident root/successor chain."""

    __tablename__ = "ops_incident_events"
    __table_args__ = (
        UniqueConstraint("incident_id", "event_ordinal", name="uq_incident_event_ordinal"),
        ForeignKeyConstraint(
            ["event_id", "outbox_batch_id"],
            [
                "notification_outbox_batches.incident_event_id",
                "notification_outbox_batches.outbox_batch_id",
            ],
            name="fk_incident_event_outbox_batch",
            deferrable=True,
            initially="DEFERRED",
        ),
    )

    event_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    incident_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("ops_incidents.incident_id"), nullable=False
    )
    event_ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    expected_prior_event_id: Mapped[str | None] = mapped_column(
        String(128), ForeignKey("ops_incident_events.event_id")
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    from_state: Mapped[str | None] = mapped_column(String(64))
    to_state: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, nullable=False)
    event_payload_json: Mapped[dict] = mapped_column(JSON_DOCUMENT, nullable=False)
    contract_content_sha256: Mapped[str | None] = mapped_column(String(64), unique=True)
    contract_payload_json: Mapped[dict | None] = mapped_column(JSON_DOCUMENT)
    outbox_batch_id: Mapped[str] = mapped_column(String(128), nullable=False)
    outbox_intent_count: Mapped[int] = mapped_column(Integer, nullable=False)


class NotificationOutboxItem(Base):
    """Immutable exact intent denominator for one incident-event transaction."""

    __tablename__ = "notification_outbox_items"
    __table_args__ = (
        UniqueConstraint(
            "incident_event_id", "intent_ordinal", name="uq_outbox_item_ordinal"
        ),
        UniqueConstraint("intent_id", name="uq_outbox_item_intent"),
    )

    incident_event_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("ops_incident_events.event_id"), primary_key=True
    )
    intent_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey(
            "notification_intents.intent_id",
            name="fk_outbox_item_intent",
            deferrable=True,
            initially="DEFERRED",
        ),
        primary_key=True,
    )
    intent_ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    outbox_batch_id: Mapped[str] = mapped_column(String(128), nullable=False)


class NotificationOutboxBatch(Base):
    """Immutable commit-complete sentinel for one exact local outbox batch."""

    __tablename__ = "notification_outbox_batches"
    __table_args__ = (
        UniqueConstraint(
            "incident_event_id", "outbox_batch_id", name="uq_outbox_batch_event"
        ),
    )

    incident_event_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("ops_incident_events.event_id"), primary_key=True
    )
    outbox_batch_id: Mapped[str] = mapped_column(String(128), nullable=False)
    intent_count: Mapped[int] = mapped_column(Integer, nullable=False)


class ReviewWorkItem(Base):
    """Stable review-work identity; state is derived from immutable events."""

    __tablename__ = "review_work_items"

    work_item_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    work_item_fingerprint_sha256: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True
    )
    environment: Mapped[str] = mapped_column(String(128), nullable=False)
    work_class: Mapped[str] = mapped_column(String(64), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(128), nullable=False)
    publication_blocking: Mapped[bool] = mapped_column(Boolean, nullable=False)
    first_contract_sha256: Mapped[str] = mapped_column(String(64), nullable=False)


class ReviewWorkItemEvent(Base):
    """One immutable transition in a review-work chain."""

    __tablename__ = "review_work_item_events"
    __table_args__ = (
        UniqueConstraint("work_item_id", "event_ordinal", name="uq_work_item_event_ordinal"),
    )

    event_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    work_item_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("review_work_items.work_item_id"), nullable=False
    )
    event_ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    expected_prior_event_id: Mapped[str | None] = mapped_column(
        String(128), ForeignKey("review_work_item_events.event_id")
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    from_state: Mapped[str | None] = mapped_column(String(64))
    to_state: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, nullable=False)
    event_payload_json: Mapped[dict] = mapped_column(JSON_DOCUMENT, nullable=False)
    contract_content_sha256: Mapped[str | None] = mapped_column(String(64), unique=True)
    contract_payload_json: Mapped[dict | None] = mapped_column(JSON_DOCUMENT)


class NotificationIntentRecord(Base):
    """Insert-only local outbox intent; this model has no delivery capability."""

    __tablename__ = "notification_intents"
    __table_args__ = (
        ForeignKeyConstraint(
            ["incident_event_id", "intent_id"],
            [
                "notification_outbox_items.incident_event_id",
                "notification_outbox_items.intent_id",
            ],
            name="fk_notification_intent_outbox",
        ),
    )

    intent_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    dedupe_key_sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    incident_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("ops_incidents.incident_id"), nullable=False
    )
    incident_event_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("ops_incident_events.event_id"), nullable=False
    )
    notification_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    route_id: Mapped[str] = mapped_column(String(128), nullable=False)
    dispatch_eligibility: Mapped[str] = mapped_column(String(32), nullable=False)
    outbox_batch_id: Mapped[str] = mapped_column(String(128), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    payload_json: Mapped[dict] = mapped_column(JSON_DOCUMENT, nullable=False)


class NotificationReceiptRecord(Base):
    """Append-only delivery/local-record receipt chain; never performs a send."""

    __tablename__ = "notification_receipts"
    __table_args__ = (
        UniqueConstraint("intent_id", name="uq_notification_receipt_intent"),
        UniqueConstraint("prior_receipt_id", name="uq_notification_receipt_prior"),
    )

    receipt_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    receipt_dedupe_key_sha256: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True
    )
    intent_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("notification_intents.intent_id"), nullable=False
    )
    incident_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("ops_incidents.incident_id"), nullable=False
    )
    route_id: Mapped[str] = mapped_column(String(128), nullable=False)
    adapter_id: Mapped[str] = mapped_column(String(128), nullable=False)
    adapter_version: Mapped[str] = mapped_column(String(128), nullable=False)
    prior_receipt_id: Mapped[str | None] = mapped_column(
        String(128), ForeignKey("notification_receipts.receipt_id")
    )
    finished_at: Mapped[datetime] = mapped_column(UTC_TIMESTAMP, nullable=False)
    outcome: Mapped[str] = mapped_column(String(64), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    payload_json: Mapped[dict] = mapped_column(JSON_DOCUMENT, nullable=False)
