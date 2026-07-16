"""Add guarded operational persistence and immutable event lineages.

The new relations retain Phase 1 scheduling, source-check, discovery,
identity, incident, review-work, and notification contracts.  They grant no
source certification, claim review/publication, release, or frontend authority.
Only ``scheduled_job_leases`` is mutable, and its projection is fenced by an
immutable lease-event chain plus exact-current-token guards.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from migrations._dialect import is_postgresql, is_sqlite


revision = "0010_operational_persistence"
down_revision = "0009_postgresql_guardrails"
branch_labels = None
depends_on = None


JSON_DOCUMENT = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
UTC_TIMESTAMP = sa.DateTime(timezone=True)


IMMUTABLE_TABLES = (
    "scheduled_cycle_intents",
    "scheduled_cycle_intent_completions",
    "scheduled_cycles",
    "scheduled_job_intents",
    "scheduled_job_lease_events",
    "scheduled_job_attempts",
    "source_contract_envelopes",
    "source_check_receipts",
    "extraction_batches",
    "discovery_candidates",
    "benchmark_definition_revisions",
    "evaluation_subject_revisions",
    "identity_decisions",
    "ops_incidents",
    "ops_incident_events",
    "notification_outbox_items",
    "notification_outbox_batches",
    "review_work_items",
    "review_work_item_events",
    "notification_intents",
    "notification_receipts",
)


def _create_tables() -> None:
    op.create_table(
        "scheduled_cycle_intents",
        sa.Column("cycle_id", sa.String(128), nullable=False),
        sa.Column("environment", sa.String(128), nullable=False),
        sa.Column("lane", sa.String(32), nullable=False),
        sa.Column("scheduled_for", UTC_TIMESTAMP, nullable=False),
        sa.Column("schedule_policy_revision_id", sa.String(128), nullable=False),
        sa.Column("mode", sa.String(32), nullable=False),
        sa.Column("job_count", sa.Integer(), nullable=False),
        sa.Column("intent_sha256", sa.String(64), nullable=False),
        sa.Column("payload_json", JSON_DOCUMENT, nullable=False),
        sa.PrimaryKeyConstraint("cycle_id", name="scheduled_cycle_intents_pkey"),
        sa.UniqueConstraint(
            "environment",
            "lane",
            "scheduled_for",
            "schedule_policy_revision_id",
            name="uq_scheduled_cycle_intent_slot",
        ),
        sa.UniqueConstraint("intent_sha256", name="uq_scheduled_cycle_intent_content"),
        *(
            (
                sa.ForeignKeyConstraint(
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
            if is_sqlite()
            else ()
        ),
    )
    op.create_table(
        "scheduled_cycles",
        sa.Column("cycle_id", sa.String(128), nullable=False),
        sa.Column("environment", sa.String(128), nullable=False),
        sa.Column("lane", sa.String(32), nullable=False),
        sa.Column("scheduled_for", UTC_TIMESTAMP, nullable=False),
        sa.Column("schedule_policy_revision_id", sa.String(128), nullable=False),
        sa.Column("mode", sa.String(32), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("payload_json", JSON_DOCUMENT, nullable=False),
        sa.PrimaryKeyConstraint("cycle_id", name="scheduled_cycles_pkey"),
        sa.ForeignKeyConstraint(
            ["cycle_id"],
            ["scheduled_cycle_intents.cycle_id"],
            name="fk_scheduled_cycle_intent",
        ),
        sa.UniqueConstraint(
            "environment",
            "lane",
            "scheduled_for",
            "schedule_policy_revision_id",
            name="uq_scheduled_cycle_slot",
        ),
        sa.UniqueConstraint("content_sha256", name="uq_scheduled_cycle_content"),
    )
    op.create_table(
        "scheduled_job_intents",
        sa.Column("job_id", sa.String(128), nullable=False),
        sa.Column("cycle_id", sa.String(128), nullable=False),
        sa.Column("environment", sa.String(128), nullable=False),
        sa.Column("lane", sa.String(32), nullable=False),
        sa.Column("target_type", sa.String(32), nullable=False),
        sa.Column("target_revision_id", sa.String(128), nullable=False),
        sa.Column("source_revision_id", sa.String(36), nullable=True),
        sa.Column("scheduled_for", UTC_TIMESTAMP, nullable=False),
        sa.Column("schedule_policy_revision_id", sa.String(128), nullable=False),
        sa.Column("idempotency_key_sha256", sa.String(64), nullable=False),
        sa.Column("due_disposition", sa.String(32), nullable=False),
        sa.Column("disposition_reason_code", sa.String(128), nullable=False),
        sa.Column("intent_sha256", sa.String(64), nullable=False),
        sa.Column("payload_json", JSON_DOCUMENT, nullable=False),
        sa.PrimaryKeyConstraint("job_id", name="scheduled_job_intents_pkey"),
        sa.ForeignKeyConstraint(
            ["cycle_id"],
            ["scheduled_cycle_intents.cycle_id"],
            name="fk_scheduled_job_cycle_intent",
        ),
        sa.ForeignKeyConstraint(
            ["source_revision_id"],
            ["official_source_revisions.id"],
            name="fk_scheduled_job_source_revision",
        ),
        sa.UniqueConstraint(
            "environment",
            "lane",
            "target_revision_id",
            "scheduled_for",
            "schedule_policy_revision_id",
            name="uq_scheduled_job_slot",
        ),
        sa.UniqueConstraint(
            "idempotency_key_sha256", name="uq_scheduled_job_idempotency"
        ),
        sa.UniqueConstraint("intent_sha256", name="uq_scheduled_job_intent_content"),
    )
    op.create_table(
        "scheduled_cycle_intent_completions",
        sa.Column("cycle_id", sa.String(128), nullable=False),
        sa.Column("intent_sha256", sa.String(64), nullable=False),
        sa.Column("job_count", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint(
            "cycle_id", name="scheduled_cycle_intent_completions_pkey"
        ),
        sa.ForeignKeyConstraint(
            ["cycle_id"],
            ["scheduled_cycle_intents.cycle_id"],
            name="fk_cycle_intent_completion_cycle",
        ),
        sa.UniqueConstraint(
            "cycle_id", "intent_sha256", name="uq_cycle_intent_completion"
        ),
    )
    op.create_table(
        "scheduled_job_lease_events",
        sa.Column("lease_id", sa.String(128), nullable=False),
        sa.Column("job_id", sa.String(128), nullable=False),
        sa.Column("fencing_token", sa.Integer(), nullable=False),
        sa.Column("prior_lease_id", sa.String(128), nullable=True),
        sa.Column("worker_identity_sha256", sa.String(64), nullable=False),
        sa.Column("acquired_at", UTC_TIMESTAMP, nullable=False),
        sa.Column("expires_at", UTC_TIMESTAMP, nullable=False),
        sa.Column("initial_heartbeat_at", UTC_TIMESTAMP, nullable=False),
        sa.PrimaryKeyConstraint("lease_id", name="scheduled_job_lease_events_pkey"),
        sa.ForeignKeyConstraint(
            ["job_id"], ["scheduled_job_intents.job_id"], name="fk_job_lease_event_job"
        ),
        sa.ForeignKeyConstraint(
            ["prior_lease_id"],
            ["scheduled_job_lease_events.lease_id"],
            name="fk_job_lease_event_prior",
        ),
        sa.UniqueConstraint("job_id", "fencing_token", name="uq_job_lease_token"),
    )
    op.create_table(
        "scheduled_job_leases",
        sa.Column("job_id", sa.String(128), nullable=False),
        sa.Column("current_lease_id", sa.String(128), nullable=False),
        sa.Column("fencing_token", sa.Integer(), nullable=False),
        sa.Column("worker_identity_sha256", sa.String(64), nullable=False),
        sa.Column("acquired_at", UTC_TIMESTAMP, nullable=False),
        sa.Column("expires_at", UTC_TIMESTAMP, nullable=False),
        sa.Column("last_heartbeat_at", UTC_TIMESTAMP, nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.PrimaryKeyConstraint("job_id", name="scheduled_job_leases_pkey"),
        sa.ForeignKeyConstraint(
            ["job_id"], ["scheduled_job_intents.job_id"], name="fk_job_lease_job"
        ),
        sa.ForeignKeyConstraint(
            ["current_lease_id"],
            ["scheduled_job_lease_events.lease_id"],
            name="fk_job_lease_current_event",
        ),
        sa.UniqueConstraint("current_lease_id", name="uq_current_job_lease_event"),
    )
    op.create_table(
        "scheduled_job_attempts",
        sa.Column("attempt_id", sa.String(128), nullable=False),
        sa.Column("cycle_id", sa.String(128), nullable=False),
        sa.Column("job_id", sa.String(128), nullable=False),
        sa.Column("lease_id", sa.String(128), nullable=False),
        sa.Column("source_revision_id", sa.String(36), nullable=True),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("fencing_token", sa.Integer(), nullable=False),
        sa.Column("prior_fencing_token", sa.Integer(), nullable=True),
        sa.Column("worker_identity_sha256", sa.String(64), nullable=False),
        sa.Column("lease_acquired_at", UTC_TIMESTAMP, nullable=False),
        sa.Column("lease_expires_at", UTC_TIMESTAMP, nullable=False),
        sa.Column("lease_last_heartbeat_at", UTC_TIMESTAMP, nullable=False),
        sa.Column("started_at", UTC_TIMESTAMP, nullable=False),
        sa.Column("ended_at", UTC_TIMESTAMP, nullable=False),
        sa.Column("stage_reached", sa.String(64), nullable=False),
        sa.Column("outcome", sa.String(32), nullable=False),
        sa.Column("commit_disposition", sa.String(32), nullable=False),
        sa.Column("source_check_receipt_id", sa.String(128), nullable=True),
        sa.Column("source_check_receipt_sha256", sa.String(64), nullable=True),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("payload_json", JSON_DOCUMENT, nullable=False),
        sa.PrimaryKeyConstraint("attempt_id", name="scheduled_job_attempts_pkey"),
        sa.ForeignKeyConstraint(
            ["cycle_id"],
            ["scheduled_cycle_intents.cycle_id"],
            name="fk_job_attempt_cycle_intent",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"], ["scheduled_job_intents.job_id"], name="fk_job_attempt_job"
        ),
        sa.ForeignKeyConstraint(
            ["lease_id"],
            ["scheduled_job_lease_events.lease_id"],
            name="fk_job_attempt_lease",
        ),
        sa.ForeignKeyConstraint(
            ["source_revision_id"],
            ["official_source_revisions.id"],
            name="fk_job_attempt_source_revision",
        ),
        *(
            (
                sa.ForeignKeyConstraint(
                    ["source_check_receipt_id"],
                    ["source_check_receipts.receipt_id"],
                    name="fk_job_attempt_source_check",
                    deferrable=True,
                    initially="DEFERRED",
                ),
            )
            if is_sqlite()
            else ()
        ),
        sa.UniqueConstraint("job_id", "attempt_number", name="uq_job_attempt_number"),
        sa.UniqueConstraint("job_id", "fencing_token", name="uq_job_attempt_token"),
        sa.UniqueConstraint("content_sha256", name="uq_job_attempt_content"),
    )
    op.create_table(
        "source_contract_envelopes",
        sa.Column("contract_revision_id", sa.String(128), nullable=False),
        sa.Column("contract_id", sa.String(128), nullable=False),
        sa.Column("supersedes_contract_revision_id", sa.String(128), nullable=True),
        sa.Column("official_source_id", sa.String(128), nullable=False),
        sa.Column("source_revision_id", sa.String(36), nullable=False),
        sa.Column("certification_decision_id", sa.String(36), nullable=True),
        sa.Column("certification_decision_sha256", sa.String(64), nullable=True),
        sa.Column("schedule_policy_revision_id", sa.String(128), nullable=False),
        sa.Column("lifecycle_status", sa.String(32), nullable=False),
        sa.Column("contract_digest_sha256", sa.String(64), nullable=False),
        sa.Column("contract_definition_sha256", sa.String(64), nullable=False),
        sa.Column("payload_json", JSON_DOCUMENT, nullable=False),
        sa.PrimaryKeyConstraint(
            "contract_revision_id", name="source_contract_envelopes_pkey"
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_contract_revision_id"],
            ["source_contract_envelopes.contract_revision_id"],
            name="fk_source_contract_prior",
        ),
        sa.ForeignKeyConstraint(
            ["official_source_id"],
            ["official_sources.id"],
            name="fk_source_contract_source",
        ),
        sa.ForeignKeyConstraint(
            ["source_revision_id"],
            ["official_source_revisions.id"],
            name="fk_source_contract_revision",
        ),
        sa.ForeignKeyConstraint(
            ["certification_decision_id"],
            ["source_revision_decisions.id"],
            name="fk_source_contract_decision",
        ),
        sa.UniqueConstraint(
            "contract_digest_sha256", name="uq_source_contract_content"
        ),
    )
    op.create_table(
        "source_check_receipts",
        sa.Column("receipt_id", sa.String(128), nullable=False),
        sa.Column("attempt_id", sa.String(128), nullable=False),
        sa.Column("job_id", sa.String(128), nullable=False),
        sa.Column("official_source_id", sa.String(128), nullable=False),
        sa.Column("source_revision_id", sa.String(36), nullable=False),
        sa.Column("source_revision_decision_id", sa.String(36), nullable=True),
        sa.Column("source_revision_decision_sha256", sa.String(64), nullable=True),
        sa.Column("checked_source_revision_decision_id", sa.String(36), nullable=True),
        sa.Column("checked_source_revision_decision_sha256", sa.String(64), nullable=True),
        sa.Column("certification_check_outcome", sa.String(32), nullable=False),
        sa.Column("contract_id", sa.String(128), nullable=False),
        sa.Column("contract_revision_id", sa.String(128), nullable=False),
        sa.Column("contract_digest_sha256", sa.String(64), nullable=False),
        sa.Column("contract_definition_sha256", sa.String(64), nullable=False),
        sa.Column("schedule_policy_revision_id", sa.String(128), nullable=False),
        sa.Column("scheduled_for", UTC_TIMESTAMP, nullable=False),
        sa.Column("fencing_token", sa.Integer(), nullable=False),
        sa.Column("snapshot_id", sa.String(36), nullable=True),
        sa.Column("snapshot_content_sha256", sa.String(64), nullable=True),
        sa.Column("snapshot_storage_receipt_sha256", sa.String(64), nullable=True),
        sa.Column("previous_snapshot_id", sa.String(36), nullable=True),
        sa.Column("previous_snapshot_content_sha256", sa.String(64), nullable=True),
        sa.Column("previous_snapshot_verification_receipt_sha256", sa.String(64), nullable=True),
        sa.Column("batch_receipt_sha256", sa.String(64), nullable=True),
        sa.Column("terminal_disposition", sa.String(64), nullable=False),
        sa.Column("started_at", UTC_TIMESTAMP, nullable=False),
        sa.Column("finished_at", UTC_TIMESTAMP, nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("payload_json", JSON_DOCUMENT, nullable=False),
        sa.PrimaryKeyConstraint("receipt_id", name="source_check_receipts_pkey"),
        sa.ForeignKeyConstraint(
            ["attempt_id"], ["scheduled_job_attempts.attempt_id"], name="fk_source_check_attempt"
        ),
        sa.ForeignKeyConstraint(
            ["job_id"], ["scheduled_job_intents.job_id"], name="fk_source_check_job"
        ),
        sa.ForeignKeyConstraint(
            ["official_source_id"], ["official_sources.id"], name="fk_source_check_source"
        ),
        sa.ForeignKeyConstraint(
            ["source_revision_id"],
            ["official_source_revisions.id"],
            name="fk_source_check_revision",
        ),
        sa.ForeignKeyConstraint(
            ["source_revision_decision_id"],
            ["source_revision_decisions.id"],
            name="fk_source_check_decision",
        ),
        sa.ForeignKeyConstraint(
            ["checked_source_revision_decision_id"],
            ["source_revision_decisions.id"],
            name="fk_source_check_checked_decision",
        ),
        sa.ForeignKeyConstraint(
            ["contract_revision_id"],
            ["source_contract_envelopes.contract_revision_id"],
            name="fk_source_check_contract",
        ),
        sa.ForeignKeyConstraint(
            ["snapshot_id"], ["source_snapshots.id"], name="fk_source_check_snapshot"
        ),
        sa.ForeignKeyConstraint(
            ["previous_snapshot_id"],
            ["source_snapshots.id"],
            name="fk_source_check_previous_snapshot",
        ),
        sa.UniqueConstraint("attempt_id", name="uq_source_check_attempt"),
        sa.UniqueConstraint("content_sha256", name="uq_source_check_content"),
    )
    op.create_table(
        "extraction_batches",
        sa.Column("batch_receipt_sha256", sa.String(64), nullable=False),
        sa.Column("source_check_receipt_id", sa.String(128), nullable=False),
        sa.Column("attempt_id", sa.String(128), nullable=False),
        sa.Column("job_id", sa.String(128), nullable=False),
        sa.Column("source_revision_id", sa.String(36), nullable=False),
        sa.Column("source_revision_decision_id", sa.String(36), nullable=True),
        sa.Column("snapshot_id", sa.String(36), nullable=True),
        sa.Column("schema_fingerprint_sha256", sa.String(64), nullable=False),
        sa.Column("source_records_observed", sa.Integer(), nullable=False),
        sa.Column("rows_parsed", sa.Integer(), nullable=False),
        sa.Column("claim_candidates_emitted", sa.Integer(), nullable=False),
        sa.Column("claims_admitted", sa.Integer(), nullable=False),
        sa.Column("records_excluded", sa.Integer(), nullable=False),
        sa.Column("records_rejected", sa.Integer(), nullable=False),
        sa.Column("records_quarantined", sa.Integer(), nullable=False),
        sa.Column("payload_json", JSON_DOCUMENT, nullable=False),
        sa.PrimaryKeyConstraint("batch_receipt_sha256", name="extraction_batches_pkey"),
        sa.ForeignKeyConstraint(
            ["source_check_receipt_id"],
            ["source_check_receipts.receipt_id"],
            name="fk_extraction_receipt",
        ),
        sa.ForeignKeyConstraint(
            ["attempt_id"], ["scheduled_job_attempts.attempt_id"], name="fk_extraction_attempt"
        ),
        sa.ForeignKeyConstraint(
            ["job_id"], ["scheduled_job_intents.job_id"], name="fk_extraction_job"
        ),
        sa.ForeignKeyConstraint(
            ["source_revision_id"],
            ["official_source_revisions.id"],
            name="fk_extraction_revision",
        ),
        sa.ForeignKeyConstraint(
            ["source_revision_decision_id"],
            ["source_revision_decisions.id"],
            name="fk_extraction_decision",
        ),
        sa.ForeignKeyConstraint(
            ["snapshot_id"], ["source_snapshots.id"], name="fk_extraction_snapshot"
        ),
        sa.UniqueConstraint("source_check_receipt_id", name="uq_extraction_receipt"),
    )
    op.create_table(
        "discovery_candidates",
        sa.Column("candidate_id", sa.String(128), nullable=False),
        sa.Column("candidate_fingerprint_sha256", sa.String(64), nullable=False),
        sa.Column("candidate_type", sa.String(32), nullable=False),
        sa.Column("target_revision_id", sa.String(128), nullable=False),
        sa.Column("state", sa.String(64), nullable=False),
        sa.Column("state_decision_reference", sa.String(128), nullable=True),
        sa.Column("approved_source_revision_id", sa.String(36), nullable=True),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("payload_json", JSON_DOCUMENT, nullable=False),
        sa.PrimaryKeyConstraint("candidate_id", name="discovery_candidates_pkey"),
        sa.ForeignKeyConstraint(
            ["approved_source_revision_id"],
            ["official_source_revisions.id"],
            name="fk_discovery_approved_revision",
        ),
        sa.UniqueConstraint(
            "candidate_fingerprint_sha256", name="uq_discovery_candidate_fingerprint"
        ),
        sa.UniqueConstraint("content_sha256", name="uq_discovery_candidate_content"),
    )
    op.create_table(
        "benchmark_definition_revisions",
        sa.Column("benchmark_definition_revision_id", sa.String(128), nullable=False),
        sa.Column("benchmark_family_id", sa.String(128), nullable=False),
        sa.Column("benchmark_edition_id", sa.String(128), nullable=False),
        sa.Column("supersedes_definition_revision_id", sa.String(128), nullable=True),
        sa.Column("lifecycle_status", sa.String(32), nullable=False),
        sa.Column("decision_reference", sa.String(128), nullable=True),
        sa.Column("dimension_fingerprint_sha256", sa.String(64), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("payload_json", JSON_DOCUMENT, nullable=False),
        sa.PrimaryKeyConstraint(
            "benchmark_definition_revision_id", name="benchmark_definition_revisions_pkey"
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_definition_revision_id"],
            ["benchmark_definition_revisions.benchmark_definition_revision_id"],
            name="fk_benchmark_definition_prior",
        ),
        sa.UniqueConstraint("content_sha256", name="uq_benchmark_definition_content"),
    )
    op.create_table(
        "evaluation_subject_revisions",
        sa.Column("subject_revision_id", sa.String(128), nullable=False),
        sa.Column("subject_id", sa.String(128), nullable=False),
        sa.Column("supersedes_subject_revision_id", sa.String(128), nullable=True),
        sa.Column("subject_type", sa.String(64), nullable=False),
        sa.Column("lifecycle_status", sa.String(32), nullable=False),
        sa.Column("resolution_status", sa.String(32), nullable=False),
        sa.Column("decision_reference", sa.String(128), nullable=True),
        sa.Column("subject_fingerprint_sha256", sa.String(64), nullable=False),
        sa.Column("observed_composition_fingerprint_sha256", sa.String(64), nullable=False),
        sa.Column("raw_identity_sha256", sa.String(64), nullable=False),
        sa.Column("model_entity_id", sa.String(128), nullable=True),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("payload_json", JSON_DOCUMENT, nullable=False),
        sa.PrimaryKeyConstraint("subject_revision_id", name="evaluation_subject_revisions_pkey"),
        sa.ForeignKeyConstraint(
            ["supersedes_subject_revision_id"],
            ["evaluation_subject_revisions.subject_revision_id"],
            name="fk_subject_revision_prior",
        ),
        sa.ForeignKeyConstraint(
            ["model_entity_id"], ["model_entities.id"], name="fk_subject_revision_model"
        ),
        sa.UniqueConstraint("content_sha256", name="uq_subject_revision_content"),
    )
    op.create_table(
        "identity_decisions",
        sa.Column("decision_id", sa.String(128), nullable=False),
        sa.Column("candidate_reference", sa.String(128), nullable=False),
        sa.Column("observation_reference", sa.String(128), nullable=False),
        sa.Column("identity_item_fingerprint_sha256", sa.String(64), nullable=False),
        sa.Column("expected_prior_decision_id", sa.String(128), nullable=True),
        sa.Column("decision_sequence", sa.Integer(), nullable=False),
        sa.Column("decision_status", sa.String(32), nullable=False),
        sa.Column("decided_at", UTC_TIMESTAMP, nullable=True),
        sa.Column("selected_subject_id", sa.String(128), nullable=True),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("payload_json", JSON_DOCUMENT, nullable=False),
        sa.PrimaryKeyConstraint("decision_id", name="identity_decisions_pkey"),
        sa.ForeignKeyConstraint(
            ["candidate_reference"],
            ["discovery_candidates.candidate_id"],
            name="fk_identity_candidate",
        ),
        sa.ForeignKeyConstraint(
            ["expected_prior_decision_id"],
            ["identity_decisions.decision_id"],
            name="fk_identity_prior",
        ),
        sa.UniqueConstraint(
            "candidate_reference", "decision_sequence", name="uq_identity_decision_sequence"
        ),
        sa.UniqueConstraint("content_sha256", name="uq_identity_decision_content"),
    )
    op.create_table(
        "ops_incidents",
        sa.Column("incident_id", sa.String(128), nullable=False),
        sa.Column("incident_fingerprint_sha256", sa.String(64), nullable=False),
        sa.Column("family", sa.String(64), nullable=False),
        sa.Column("incident_code", sa.String(128), nullable=False),
        sa.Column("cause_code", sa.String(128), nullable=False),
        sa.Column("environment", sa.String(128), nullable=False),
        sa.Column("first_contract_sha256", sa.String(64), nullable=False),
        sa.PrimaryKeyConstraint("incident_id", name="ops_incidents_pkey"),
        sa.UniqueConstraint(
            "incident_fingerprint_sha256", name="uq_ops_incident_fingerprint"
        ),
    )
    op.create_table(
        "ops_incident_events",
        sa.Column("event_id", sa.String(128), nullable=False),
        sa.Column("incident_id", sa.String(128), nullable=False),
        sa.Column("event_ordinal", sa.Integer(), nullable=False),
        sa.Column("expected_prior_event_id", sa.String(128), nullable=True),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("from_state", sa.String(64), nullable=True),
        sa.Column("to_state", sa.String(64), nullable=False),
        sa.Column("occurred_at", UTC_TIMESTAMP, nullable=False),
        sa.Column("event_payload_json", JSON_DOCUMENT, nullable=False),
        sa.Column("contract_content_sha256", sa.String(64), nullable=True),
        sa.Column("contract_payload_json", JSON_DOCUMENT, nullable=True),
        sa.Column("outbox_batch_id", sa.String(128), nullable=False),
        sa.Column("outbox_intent_count", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("event_id", name="ops_incident_events_pkey"),
        sa.ForeignKeyConstraint(
            ["incident_id"], ["ops_incidents.incident_id"], name="fk_incident_event_incident"
        ),
        sa.ForeignKeyConstraint(
            ["expected_prior_event_id"],
            ["ops_incident_events.event_id"],
            name="fk_incident_event_prior",
        ),
        *(
            (
                sa.ForeignKeyConstraint(
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
            if is_sqlite()
            else ()
        ),
        sa.UniqueConstraint("incident_id", "event_ordinal", name="uq_incident_event_ordinal"),
        sa.UniqueConstraint("contract_content_sha256", name="uq_incident_contract_content"),
    )
    op.create_table(
        "review_work_items",
        sa.Column("work_item_id", sa.String(128), nullable=False),
        sa.Column("work_item_fingerprint_sha256", sa.String(64), nullable=False),
        sa.Column("environment", sa.String(128), nullable=False),
        sa.Column("work_class", sa.String(64), nullable=False),
        sa.Column("reason_code", sa.String(128), nullable=False),
        sa.Column("publication_blocking", sa.Boolean(), nullable=False),
        sa.Column("first_contract_sha256", sa.String(64), nullable=False),
        sa.PrimaryKeyConstraint("work_item_id", name="review_work_items_pkey"),
        sa.UniqueConstraint(
            "work_item_fingerprint_sha256", name="uq_review_work_item_fingerprint"
        ),
    )
    op.create_table(
        "review_work_item_events",
        sa.Column("event_id", sa.String(128), nullable=False),
        sa.Column("work_item_id", sa.String(128), nullable=False),
        sa.Column("event_ordinal", sa.Integer(), nullable=False),
        sa.Column("expected_prior_event_id", sa.String(128), nullable=True),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("from_state", sa.String(64), nullable=True),
        sa.Column("to_state", sa.String(64), nullable=False),
        sa.Column("occurred_at", UTC_TIMESTAMP, nullable=False),
        sa.Column("event_payload_json", JSON_DOCUMENT, nullable=False),
        sa.Column("contract_content_sha256", sa.String(64), nullable=True),
        sa.Column("contract_payload_json", JSON_DOCUMENT, nullable=True),
        sa.PrimaryKeyConstraint("event_id", name="review_work_item_events_pkey"),
        sa.ForeignKeyConstraint(
            ["work_item_id"], ["review_work_items.work_item_id"], name="fk_work_event_item"
        ),
        sa.ForeignKeyConstraint(
            ["expected_prior_event_id"],
            ["review_work_item_events.event_id"],
            name="fk_work_event_prior",
        ),
        sa.UniqueConstraint("work_item_id", "event_ordinal", name="uq_work_event_ordinal"),
        sa.UniqueConstraint("contract_content_sha256", name="uq_work_contract_content"),
    )
    op.create_table(
        "notification_intents",
        sa.Column("intent_id", sa.String(128), nullable=False),
        sa.Column("dedupe_key_sha256", sa.String(64), nullable=False),
        sa.Column("incident_id", sa.String(128), nullable=False),
        sa.Column("incident_event_id", sa.String(128), nullable=False),
        sa.Column("notification_kind", sa.String(32), nullable=False),
        sa.Column("route_id", sa.String(128), nullable=False),
        sa.Column("dispatch_eligibility", sa.String(32), nullable=False),
        sa.Column("outbox_batch_id", sa.String(128), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("payload_json", JSON_DOCUMENT, nullable=False),
        sa.PrimaryKeyConstraint("intent_id", name="notification_intents_pkey"),
        sa.ForeignKeyConstraint(
            ["incident_id"], ["ops_incidents.incident_id"], name="fk_notification_intent_incident"
        ),
        sa.ForeignKeyConstraint(
            ["incident_event_id"],
            ["ops_incident_events.event_id"],
            name="fk_notification_intent_event",
        ),
        *(
            (
                sa.ForeignKeyConstraint(
                    ["incident_event_id", "intent_id"],
                    [
                        "notification_outbox_items.incident_event_id",
                        "notification_outbox_items.intent_id",
                    ],
                    name="fk_notification_intent_outbox",
                ),
            )
            if is_sqlite()
            else ()
        ),
        sa.UniqueConstraint("dedupe_key_sha256", name="uq_notification_intent_dedupe"),
        sa.UniqueConstraint("content_sha256", name="uq_notification_intent_content"),
    )
    op.create_table(
        "notification_outbox_items",
        sa.Column("incident_event_id", sa.String(128), nullable=False),
        sa.Column("intent_id", sa.String(128), nullable=False),
        sa.Column("intent_ordinal", sa.Integer(), nullable=False),
        sa.Column("outbox_batch_id", sa.String(128), nullable=False),
        sa.PrimaryKeyConstraint(
            "incident_event_id", "intent_id", name="notification_outbox_items_pkey"
        ),
        sa.ForeignKeyConstraint(
            ["incident_event_id"],
            ["ops_incident_events.event_id"],
            name="fk_outbox_item_event",
        ),
        sa.ForeignKeyConstraint(
            ["intent_id"],
            ["notification_intents.intent_id"],
            name="fk_outbox_item_intent",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.UniqueConstraint(
            "incident_event_id", "intent_ordinal", name="uq_outbox_item_ordinal"
        ),
        sa.UniqueConstraint("intent_id", name="uq_outbox_item_intent"),
    )
    op.create_table(
        "notification_outbox_batches",
        sa.Column("incident_event_id", sa.String(128), nullable=False),
        sa.Column("outbox_batch_id", sa.String(128), nullable=False),
        sa.Column("intent_count", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint(
            "incident_event_id", name="notification_outbox_batches_pkey"
        ),
        sa.ForeignKeyConstraint(
            ["incident_event_id"],
            ["ops_incident_events.event_id"],
            name="fk_outbox_batch_event",
        ),
        sa.UniqueConstraint(
            "incident_event_id", "outbox_batch_id", name="uq_outbox_batch_event"
        ),
    )
    op.create_table(
        "notification_receipts",
        sa.Column("receipt_id", sa.String(128), nullable=False),
        sa.Column("receipt_dedupe_key_sha256", sa.String(64), nullable=False),
        sa.Column("intent_id", sa.String(128), nullable=False),
        sa.Column("incident_id", sa.String(128), nullable=False),
        sa.Column("route_id", sa.String(128), nullable=False),
        sa.Column("adapter_id", sa.String(128), nullable=False),
        sa.Column("adapter_version", sa.String(128), nullable=False),
        sa.Column("prior_receipt_id", sa.String(128), nullable=True),
        sa.Column("finished_at", UTC_TIMESTAMP, nullable=False),
        sa.Column("outcome", sa.String(64), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("payload_json", JSON_DOCUMENT, nullable=False),
        sa.PrimaryKeyConstraint("receipt_id", name="notification_receipts_pkey"),
        sa.ForeignKeyConstraint(
            ["intent_id"], ["notification_intents.intent_id"], name="fk_notification_receipt_intent"
        ),
        sa.ForeignKeyConstraint(
            ["incident_id"], ["ops_incidents.incident_id"], name="fk_notification_receipt_incident"
        ),
        sa.ForeignKeyConstraint(
            ["prior_receipt_id"],
            ["notification_receipts.receipt_id"],
            name="fk_notification_receipt_prior",
        ),
        sa.UniqueConstraint(
            "receipt_dedupe_key_sha256", name="uq_notification_receipt_dedupe"
        ),
        sa.UniqueConstraint("intent_id", name="uq_notification_receipt_intent"),
        sa.UniqueConstraint("prior_receipt_id", name="uq_notification_receipt_prior"),
        sa.UniqueConstraint("content_sha256", name="uq_notification_receipt_content"),
    )


def _create_postgresql_deferred_pairs() -> None:
    op.create_foreign_key(
        "fk_cycle_intent_completion",
        "scheduled_cycle_intents",
        "scheduled_cycle_intent_completions",
        ["cycle_id", "intent_sha256"],
        ["cycle_id", "intent_sha256"],
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_job_attempt_source_check",
        "scheduled_job_attempts",
        "source_check_receipts",
        ["source_check_receipt_id"],
        ["receipt_id"],
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_incident_event_outbox_batch",
        "ops_incident_events",
        "notification_outbox_batches",
        ["event_id", "outbox_batch_id"],
        ["incident_event_id", "outbox_batch_id"],
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_notification_intent_outbox",
        "notification_intents",
        "notification_outbox_items",
        ["incident_event_id", "intent_id"],
        ["incident_event_id", "intent_id"],
    )


def _create_indexes() -> None:
    indexes = (
        ("ix_source_contract_source", "source_contract_envelopes", ["official_source_id"]),
        ("ix_source_contract_revision", "source_contract_envelopes", ["source_revision_id"]),
        ("ix_source_contract_decision", "source_contract_envelopes", ["certification_decision_id"]),
        ("ix_scheduled_jobs_cycle", "scheduled_job_intents", ["cycle_id"]),
        ("ix_scheduled_jobs_source", "scheduled_job_intents", ["source_revision_id"]),
        ("ix_job_attempts_cycle", "scheduled_job_attempts", ["cycle_id"]),
        ("ix_job_attempts_lease", "scheduled_job_attempts", ["lease_id"]),
        ("ix_job_attempts_source", "scheduled_job_attempts", ["source_revision_id"]),
        ("ix_source_checks_job", "source_check_receipts", ["job_id"]),
        ("ix_source_checks_source", "source_check_receipts", ["official_source_id"]),
        ("ix_source_checks_revision", "source_check_receipts", ["source_revision_id"]),
        ("ix_source_checks_decision", "source_check_receipts", ["source_revision_decision_id"]),
        ("ix_source_checks_checked_decision", "source_check_receipts", ["checked_source_revision_decision_id"]),
        ("ix_source_checks_snapshot", "source_check_receipts", ["snapshot_id"]),
        ("ix_source_checks_previous_snapshot", "source_check_receipts", ["previous_snapshot_id"]),
        ("ix_extraction_attempt", "extraction_batches", ["attempt_id"]),
        ("ix_extraction_job", "extraction_batches", ["job_id"]),
        ("ix_extraction_revision", "extraction_batches", ["source_revision_id"]),
        ("ix_extraction_decision", "extraction_batches", ["source_revision_decision_id"]),
        ("ix_extraction_snapshot", "extraction_batches", ["snapshot_id"]),
        ("ix_discovery_approved_revision", "discovery_candidates", ["approved_source_revision_id"]),
        ("ix_benchmark_definition_family", "benchmark_definition_revisions", ["benchmark_family_id"]),
        ("ix_subject_revisions_subject", "evaluation_subject_revisions", ["subject_id"]),
        ("ix_subject_revisions_model", "evaluation_subject_revisions", ["model_entity_id"]),
        ("ix_identity_selected_subject", "identity_decisions", ["selected_subject_id"]),
        ("ix_incident_events_incident", "ops_incident_events", ["incident_id"]),
        ("ix_work_events_item", "review_work_item_events", ["work_item_id"]),
        ("ix_notification_intents_incident", "notification_intents", ["incident_id"]),
        ("ix_notification_intents_event", "notification_intents", ["incident_event_id"]),
    )
    for name, table, columns in indexes:
        op.create_index(name, table, columns, unique=False)

    for name, table, columns, predicate in (
        (
            "uq_source_contract_root",
            "source_contract_envelopes",
            ["contract_id"],
            "supersedes_contract_revision_id IS NULL",
        ),
        (
            "uq_source_contract_successor",
            "source_contract_envelopes",
            ["supersedes_contract_revision_id"],
            "supersedes_contract_revision_id IS NOT NULL",
        ),
        (
            "uq_job_lease_root",
            "scheduled_job_lease_events",
            ["job_id"],
            "prior_lease_id IS NULL",
        ),
        (
            "uq_job_lease_successor",
            "scheduled_job_lease_events",
            ["prior_lease_id"],
            "prior_lease_id IS NOT NULL",
        ),
        (
            "uq_benchmark_definition_root",
            "benchmark_definition_revisions",
            ["benchmark_family_id"],
            "supersedes_definition_revision_id IS NULL",
        ),
        (
            "uq_benchmark_definition_successor",
            "benchmark_definition_revisions",
            ["supersedes_definition_revision_id"],
            "supersedes_definition_revision_id IS NOT NULL",
        ),
        (
            "uq_subject_revision_root",
            "evaluation_subject_revisions",
            ["subject_id"],
            "supersedes_subject_revision_id IS NULL",
        ),
        (
            "uq_subject_revision_successor",
            "evaluation_subject_revisions",
            ["supersedes_subject_revision_id"],
            "supersedes_subject_revision_id IS NOT NULL",
        ),
        (
            "uq_identity_decision_root",
            "identity_decisions",
            ["candidate_reference"],
            "expected_prior_decision_id IS NULL",
        ),
        (
            "uq_identity_decision_successor",
            "identity_decisions",
            ["expected_prior_decision_id"],
            "expected_prior_decision_id IS NOT NULL",
        ),
        (
            "uq_incident_event_root",
            "ops_incident_events",
            ["incident_id"],
            "expected_prior_event_id IS NULL",
        ),
        (
            "uq_incident_event_successor",
            "ops_incident_events",
            ["expected_prior_event_id"],
            "expected_prior_event_id IS NOT NULL",
        ),
        (
            "uq_work_event_root",
            "review_work_item_events",
            ["work_item_id"],
            "expected_prior_event_id IS NULL",
        ),
        (
            "uq_work_event_successor",
            "review_work_item_events",
            ["expected_prior_event_id"],
            "expected_prior_event_id IS NOT NULL",
        ),
    ):
        where = sa.text(predicate)
        op.create_index(
            name,
            table,
            columns,
            unique=True,
            postgresql_where=where,
            sqlite_where=where,
        )


def _create_sqlite_guards() -> None:
    for table in IMMUTABLE_TABLES:
        op.execute(
            f"""
            CREATE TRIGGER trg_{table}_no_update
            BEFORE UPDATE ON {table}
            FOR EACH ROW
            BEGIN
                SELECT RAISE(ABORT, '{table} is append-only');
            END
            """
        )
        op.execute(
            f"""
            CREATE TRIGGER trg_{table}_no_delete
            BEFORE DELETE ON {table}
            FOR EACH ROW
            BEGIN
                SELECT RAISE(ABORT, '{table} is append-only');
            END
            """
        )

    op.execute(
        """
        CREATE TRIGGER trg_cycle_intent_completion_insert
        BEFORE INSERT ON scheduled_cycle_intent_completions
        FOR EACH ROW
        WHEN NOT EXISTS (
            SELECT 1 FROM scheduled_cycle_intents cycle
            WHERE cycle.cycle_id = NEW.cycle_id
              AND cycle.intent_sha256 = NEW.intent_sha256
              AND cycle.job_count = NEW.job_count
              AND json_extract(cycle.payload_json, '$.recordType') = 'scheduled-cycle-intent-v1'
              AND json_extract(cycle.payload_json, '$.cycleId') = cycle.cycle_id
              AND json_extract(cycle.payload_json, '$.environment') = cycle.environment
              AND json_extract(cycle.payload_json, '$.lane') = cycle.lane
              AND json_extract(cycle.payload_json, '$.scheduledFor') = strftime('%Y-%m-%dT%H:%M:%SZ', cycle.scheduled_for)
              AND json_extract(cycle.payload_json, '$.schedulePolicyRevisionId') = cycle.schedule_policy_revision_id
              AND json_extract(cycle.payload_json, '$.mode') = cycle.mode
              AND json_array_length(json_extract(cycle.payload_json, '$.jobs')) = cycle.job_count
              AND (
                  SELECT COUNT(*) FROM scheduled_job_intents job
                  WHERE job.cycle_id = cycle.cycle_id
              ) = cycle.job_count
              AND NOT EXISTS (
                  SELECT 1 FROM scheduled_job_intents job
                  WHERE job.cycle_id = cycle.cycle_id
                    AND (
                        job.environment <> cycle.environment
                        OR job.lane <> cycle.lane
                        OR job.scheduled_for <> cycle.scheduled_for
                        OR job.schedule_policy_revision_id <> cycle.schedule_policy_revision_id
                        OR json_extract(job.payload_json, '$.jobId') <> job.job_id
                        OR json_extract(job.payload_json, '$.idempotencyKeySha256') <> job.idempotency_key_sha256
                        OR json_extract(job.payload_json, '$.targetType') <> job.target_type
                        OR json_extract(job.payload_json, '$.targetRevisionId') <> job.target_revision_id
                        OR json_extract(job.payload_json, '$.sourceRevisionId') IS NOT job.source_revision_id
                        OR json_extract(job.payload_json, '$.dueDisposition') <> job.due_disposition
                        OR json_extract(job.payload_json, '$.dispositionReasonCode') <> job.disposition_reason_code
                        OR NOT EXISTS (
                            SELECT 1 FROM json_each(cycle.payload_json, '$.jobs') item
                            WHERE json_extract(item.value, '$.jobId') = job.job_id
                              AND json_extract(item.value, '$.idempotencyKeySha256') = job.idempotency_key_sha256
                              AND json_extract(item.value, '$.targetType') = job.target_type
                              AND json_extract(item.value, '$.targetRevisionId') = job.target_revision_id
                              AND json_extract(item.value, '$.sourceRevisionId') IS job.source_revision_id
                              AND json_extract(item.value, '$.dueDisposition') = job.due_disposition
                              AND json_extract(item.value, '$.dispositionReasonCode') = job.disposition_reason_code
                        )
                    )
              )
          )
        BEGIN
            SELECT RAISE(ABORT, 'cycle intent completion requires the exact immutable job denominator');
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_scheduled_cycles_terminal_insert
        BEFORE INSERT ON scheduled_cycles
        FOR EACH ROW
        WHEN NOT EXISTS (
            SELECT 1 FROM scheduled_cycle_intents cycle
            JOIN scheduled_cycle_intent_completions completion
              ON completion.cycle_id = cycle.cycle_id
             AND completion.intent_sha256 = cycle.intent_sha256
             AND completion.job_count = cycle.job_count
            WHERE cycle.cycle_id = NEW.cycle_id
              AND cycle.environment = NEW.environment
              AND cycle.lane = NEW.lane
              AND cycle.scheduled_for = NEW.scheduled_for
              AND cycle.schedule_policy_revision_id = NEW.schedule_policy_revision_id
              AND cycle.mode = NEW.mode
              AND json_extract(NEW.payload_json, '$.cycleId') = NEW.cycle_id
              AND json_extract(NEW.payload_json, '$.environment') = NEW.environment
              AND json_extract(NEW.payload_json, '$.lane') = NEW.lane
              AND json_extract(NEW.payload_json, '$.slot.scheduledFor') = strftime('%Y-%m-%dT%H:%M:%SZ', NEW.scheduled_for)
              AND json_extract(NEW.payload_json, '$.schedulePolicyRevisionId') = NEW.schedule_policy_revision_id
              AND json_extract(NEW.payload_json, '$.mode') = NEW.mode
              AND json_extract(NEW.payload_json, '$.state') = 'terminal'
              AND json_extract(NEW.payload_json, '$.manifest.contentSha256') = NEW.content_sha256
              AND json_array_length(json_extract(NEW.payload_json, '$.jobs')) = cycle.job_count
              AND NOT EXISTS (
                  SELECT 1 FROM scheduled_job_intents job
                  WHERE job.cycle_id = cycle.cycle_id
                    AND NOT EXISTS (
                        SELECT 1 FROM json_each(NEW.payload_json, '$.jobs') item
                        WHERE json_extract(item.value, '$.jobId') = job.job_id
                          AND json_extract(item.value, '$.idempotencyKeySha256') = job.idempotency_key_sha256
                          AND json_extract(item.value, '$.targetType') = job.target_type
                          AND json_extract(item.value, '$.targetRevisionId') = job.target_revision_id
                          AND json_extract(item.value, '$.sourceRevisionId') IS job.source_revision_id
                          AND json_extract(item.value, '$.dueDisposition') = job.due_disposition
                          AND json_extract(item.value, '$.dispositionReasonCode') = job.disposition_reason_code
                          AND CAST(json_extract(item.value, '$.attemptCount') AS INTEGER) = (
                              SELECT COUNT(*) FROM scheduled_job_attempts attempt
                              WHERE attempt.job_id = job.job_id
                                AND attempt.cycle_id = cycle.cycle_id
                          )
                          AND NOT EXISTS (
                              SELECT 1 FROM json_each(item.value, '$.attemptReceiptIds') listed
                              WHERE NOT EXISTS (
                                  SELECT 1 FROM scheduled_job_attempts attempt
                                  WHERE attempt.attempt_id = listed.value
                                    AND attempt.job_id = job.job_id
                                    AND attempt.cycle_id = cycle.cycle_id
                              )
                          )
                          AND NOT EXISTS (
                              SELECT 1 FROM scheduled_job_attempts attempt
                              WHERE attempt.job_id = job.job_id
                                AND attempt.cycle_id = cycle.cycle_id
                                AND NOT EXISTS (
                                    SELECT 1 FROM json_each(item.value, '$.attemptReceiptIds') listed
                                    WHERE listed.value = attempt.attempt_id
                                )
                          )
                          AND json_extract(item.value, '$.terminalOutputReference.referenceType') = 'source_check_receipt'
                          AND EXISTS (
                              SELECT 1
                              FROM scheduled_job_attempts final_attempt
                              JOIN source_check_receipts receipt
                                ON receipt.attempt_id = final_attempt.attempt_id
                               AND receipt.job_id = final_attempt.job_id
                               AND receipt.receipt_id = final_attempt.source_check_receipt_id
                               AND receipt.content_sha256 = final_attempt.source_check_receipt_sha256
                              JOIN scheduled_job_leases lease
                                ON lease.job_id = final_attempt.job_id
                               AND lease.current_lease_id = final_attempt.lease_id
                               AND lease.fencing_token = final_attempt.fencing_token
                               AND lease.last_heartbeat_at = final_attempt.lease_last_heartbeat_at
                               AND lease.state = json_extract(final_attempt.payload_json, '$.lease.state')
                              WHERE final_attempt.job_id = job.job_id
                                AND final_attempt.cycle_id = cycle.cycle_id
                                AND final_attempt.attempt_number = CAST(json_extract(item.value, '$.attemptCount') AS INTEGER)
                                AND receipt.receipt_id = json_extract(item.value, '$.terminalOutputReference.referenceId')
                                AND receipt.content_sha256 = json_extract(item.value, '$.terminalOutputReference.contentSha256')
                                AND receipt.terminal_disposition = json_extract(item.value, '$.terminalDisposition')
                          )
                    )
              )
          )
        BEGIN
            SELECT RAISE(ABORT, 'terminal cycle requires exact intent, attempts, and immutable output evidence');
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_source_contracts_reference_insert
        BEFORE INSERT ON source_contract_envelopes
        FOR EACH ROW
        WHEN NOT EXISTS (
            SELECT 1
            FROM official_source_revisions revision
            WHERE revision.id = NEW.source_revision_id
              AND revision.official_source_id = NEW.official_source_id
              AND json_extract(NEW.payload_json, '$.contractId') = NEW.contract_id
              AND json_extract(NEW.payload_json, '$.contractRevisionId') = NEW.contract_revision_id
              AND json_extract(NEW.payload_json, '$.supersedesContractRevisionId') IS NEW.supersedes_contract_revision_id
              AND json_extract(NEW.payload_json, '$.logicalSource.sourceId') = NEW.official_source_id
              AND json_extract(NEW.payload_json, '$.logicalSource.sourceRevisionId') = NEW.source_revision_id
              AND json_extract(NEW.payload_json, '$.schedule.schedulePolicyRevisionId') = NEW.schedule_policy_revision_id
              AND json_extract(NEW.payload_json, '$.lifecycleStatus') = NEW.lifecycle_status
              AND json_extract(NEW.payload_json, '$.manifest.contentSha256') = NEW.contract_digest_sha256
              AND json_extract(NEW.payload_json, '$.manifest.definitionSha256') = NEW.contract_definition_sha256
              AND json_extract(NEW.payload_json, '$.certification.decisionId') IS NEW.certification_decision_id
              AND json_extract(NEW.payload_json, '$.certification.decisionDigestSha256') IS NEW.certification_decision_sha256
              AND (
                  (
                      NEW.certification_decision_id IS NULL
                      AND NEW.certification_decision_sha256 IS NULL
                      AND json_extract(NEW.payload_json, '$.certification.decisionOutcome') = 'not_assessed'
                  ) OR EXISTS (
                      SELECT 1 FROM source_revision_decisions decision
                      WHERE decision.id = NEW.certification_decision_id
                        AND decision.source_revision_id = NEW.source_revision_id
                        AND decision.outcome = json_extract(NEW.payload_json, '$.certification.decisionOutcome')
                        AND json_extract(decision.basis_json, '$.sourceContractDecisionEvidence.decisionDigestSha256') = NEW.certification_decision_sha256
                        AND json_extract(decision.basis_json, '$.sourceContractDecisionEvidence.contractDefinitionSha256') = NEW.contract_definition_sha256
                        AND json_extract(decision.basis_json, '$.sourceContractDecisionEvidence.effectiveOn') = json_extract(NEW.payload_json, '$.certification.effectiveOn')
                        AND json_extract(decision.basis_json, '$.sourceContractDecisionEvidence.expiresOn') = json_extract(NEW.payload_json, '$.certification.expiresOn')
                  )
              )
              AND (
                  NEW.supersedes_contract_revision_id IS NULL
                  OR EXISTS (
                      SELECT 1 FROM source_contract_envelopes parent
                      WHERE parent.contract_revision_id = NEW.supersedes_contract_revision_id
                        AND parent.contract_id = NEW.contract_id
                  )
              )
          )
        BEGIN
            SELECT RAISE(ABORT, 'source contract requires exact source and durable decision evidence');
        END
        """
    )

    op.execute(
        """
        CREATE TRIGGER trg_scheduled_job_intents_reference_insert
        BEFORE INSERT ON scheduled_job_intents
        FOR EACH ROW
        WHEN EXISTS (
            SELECT 1 FROM scheduled_cycle_intent_completions completion
            WHERE completion.cycle_id = NEW.cycle_id
        ) OR NOT EXISTS (
            SELECT 1 FROM scheduled_cycle_intents cycle
            JOIN json_each(cycle.payload_json, '$.jobs') item
              ON json_extract(item.value, '$.jobId') = NEW.job_id
             AND json_extract(item.value, '$.idempotencyKeySha256') = NEW.idempotency_key_sha256
             AND json_extract(item.value, '$.targetType') = NEW.target_type
             AND json_extract(item.value, '$.targetRevisionId') = NEW.target_revision_id
             AND json_extract(item.value, '$.sourceRevisionId') IS NEW.source_revision_id
             AND json_extract(item.value, '$.dueDisposition') = NEW.due_disposition
             AND json_extract(item.value, '$.dispositionReasonCode') = NEW.disposition_reason_code
            WHERE cycle.cycle_id = NEW.cycle_id
              AND cycle.environment = NEW.environment
              AND cycle.lane = NEW.lane
              AND cycle.scheduled_for = NEW.scheduled_for
              AND cycle.schedule_policy_revision_id = NEW.schedule_policy_revision_id
              AND json_extract(NEW.payload_json, '$.jobId') = NEW.job_id
              AND json_extract(NEW.payload_json, '$.idempotencyKeySha256') = NEW.idempotency_key_sha256
              AND json_extract(NEW.payload_json, '$.targetType') = NEW.target_type
              AND json_extract(NEW.payload_json, '$.targetRevisionId') = NEW.target_revision_id
              AND json_extract(NEW.payload_json, '$.sourceRevisionId') IS NEW.source_revision_id
              AND json_extract(NEW.payload_json, '$.dueDisposition') = NEW.due_disposition
              AND json_extract(NEW.payload_json, '$.dispositionReasonCode') = NEW.disposition_reason_code
          )
        BEGIN
            SELECT RAISE(ABORT, 'scheduled job intent must belong to an open exact cycle intent');
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_job_lease_events_chain_insert
        BEFORE INSERT ON scheduled_job_lease_events
        FOR EACH ROW
        WHEN NEW.acquired_at >= NEW.expires_at
        OR NEW.initial_heartbeat_at < NEW.acquired_at
        OR NEW.initial_heartbeat_at > NEW.expires_at
        OR EXISTS (
            SELECT 1 FROM scheduled_job_intents job
            JOIN scheduled_cycles terminal ON terminal.cycle_id = job.cycle_id
            WHERE job.job_id = NEW.job_id
        )
        OR (
            NEW.prior_lease_id IS NULL AND NEW.fencing_token <> 1
        ) OR (
            NEW.prior_lease_id IS NOT NULL AND NOT EXISTS (
                SELECT 1 FROM scheduled_job_lease_events parent
                JOIN scheduled_job_leases current
                  ON current.job_id = parent.job_id
                 AND current.current_lease_id = parent.lease_id
                WHERE parent.lease_id = NEW.prior_lease_id
                  AND parent.job_id = NEW.job_id
                  AND NEW.fencing_token = parent.fencing_token + 1
                  AND NEW.acquired_at >= parent.acquired_at
                  AND (
                      current.state <> 'leased'
                      OR julianday('now') >= julianday(current.expires_at)
                  )
            )
        )
        BEGIN
            SELECT RAISE(ABORT, 'job lease events require one exact monotonic lineage');
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_benchmark_definitions_chain_insert
        BEFORE INSERT ON benchmark_definition_revisions
        FOR EACH ROW
        WHEN NEW.supersedes_definition_revision_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM benchmark_definition_revisions parent
              WHERE parent.benchmark_definition_revision_id = NEW.supersedes_definition_revision_id
                AND parent.benchmark_family_id = NEW.benchmark_family_id
          )
        BEGIN
            SELECT RAISE(ABORT, 'benchmark definition parent belongs to another family');
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_subject_revisions_chain_insert
        BEFORE INSERT ON evaluation_subject_revisions
        FOR EACH ROW
        WHEN NEW.supersedes_subject_revision_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM evaluation_subject_revisions parent
              WHERE parent.subject_revision_id = NEW.supersedes_subject_revision_id
                AND parent.subject_id = NEW.subject_id
                AND parent.subject_type = NEW.subject_type
                AND parent.observed_composition_fingerprint_sha256 = NEW.observed_composition_fingerprint_sha256
                AND parent.raw_identity_sha256 = NEW.raw_identity_sha256
                AND (parent.model_entity_id IS NULL OR parent.model_entity_id IS NEW.model_entity_id)
          )
        BEGIN
            SELECT RAISE(ABORT, 'subject revision changed aggregate or raw composition');
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_identity_decisions_chain_insert
        BEFORE INSERT ON identity_decisions
        FOR EACH ROW
        WHEN (
            NEW.expected_prior_decision_id IS NULL AND NEW.decision_sequence <> 1
        ) OR (
            NEW.expected_prior_decision_id IS NOT NULL AND NOT EXISTS (
                SELECT 1 FROM identity_decisions parent
                WHERE parent.decision_id = NEW.expected_prior_decision_id
                  AND parent.candidate_reference = NEW.candidate_reference
                  AND parent.observation_reference = NEW.observation_reference
                  AND parent.identity_item_fingerprint_sha256 = NEW.identity_item_fingerprint_sha256
                  AND NEW.decision_sequence = parent.decision_sequence + 1
                  AND (
                      NEW.decided_at IS NULL
                      OR parent.decided_at IS NULL
                      OR NEW.decided_at > parent.decided_at
                  )
            )
        ) OR (
            NEW.selected_subject_id IS NOT NULL AND NOT EXISTS (
                SELECT 1 FROM evaluation_subject_revisions subject
                WHERE subject.subject_id = NEW.selected_subject_id
                  AND subject.lifecycle_status = 'reviewed'
                  AND subject.resolution_status = 'resolved'
                  AND subject.decision_reference IS NOT NULL
                  AND NOT EXISTS (
                      SELECT 1 FROM evaluation_subject_revisions successor
                      WHERE successor.supersedes_subject_revision_id = subject.subject_revision_id
                  )
            )
        )
        BEGIN
            SELECT RAISE(ABORT, 'identity decisions require one exact candidate lineage');
        END
        """
    )
    for table, aggregate, parent, ordinal, message in (
        (
            "ops_incident_events",
            "incident_id",
            "expected_prior_event_id",
            "event_ordinal",
            "incident event",
        ),
        (
            "review_work_item_events",
            "work_item_id",
            "expected_prior_event_id",
            "event_ordinal",
            "work-item event",
        ),
    ):
        op.execute(
            f"""
            CREATE TRIGGER trg_{table}_chain_insert
            BEFORE INSERT ON {table}
            FOR EACH ROW
            WHEN (
                NEW.{parent} IS NULL
                AND (NEW.{ordinal} <> 1 OR NEW.from_state IS NOT NULL)
            ) OR (
                NEW.{parent} IS NOT NULL AND NOT EXISTS (
                    SELECT 1 FROM {table} parent
                    WHERE parent.event_id = NEW.{parent}
                      AND parent.{aggregate} = NEW.{aggregate}
                      AND NEW.{ordinal} = parent.{ordinal} + 1
                      AND NEW.from_state IS parent.to_state
                )
            )
            BEGIN
                SELECT RAISE(ABORT, '{message} requires one exact linear lineage');
            END
            """
        )
    op.execute(
        """
        CREATE TRIGGER trg_notification_receipts_reference_insert
        BEFORE INSERT ON notification_receipts
        FOR EACH ROW
        WHEN NOT EXISTS (
            SELECT 1 FROM notification_intents intent
            WHERE intent.intent_id = NEW.intent_id
              AND intent.incident_id = NEW.incident_id
              AND intent.route_id = NEW.route_id
              AND json_extract(NEW.payload_json, '$.receiptId') = NEW.receipt_id
              AND json_extract(NEW.payload_json, '$.receiptDedupeKeySha256') = NEW.receipt_dedupe_key_sha256
              AND json_extract(NEW.payload_json, '$.intentBinding.intentId') = NEW.intent_id
              AND json_extract(NEW.payload_json, '$.intentBinding.intentContentSha256') = intent.content_sha256
              AND json_extract(NEW.payload_json, '$.intentBinding.intentDedupeKeySha256') = intent.dedupe_key_sha256
              AND json_extract(NEW.payload_json, '$.intentBinding.payloadSha256') = json_extract(intent.payload_json, '$.payloadSha256')
              AND json_extract(NEW.payload_json, '$.intentBinding.routeId') = NEW.route_id
              AND json_extract(NEW.payload_json, '$.intentBinding.adapterId') = NEW.adapter_id
              AND json_extract(NEW.payload_json, '$.intentBinding.adapterVersion') = NEW.adapter_version
              AND json_extract(NEW.payload_json, '$.outcome') = NEW.outcome
              AND json_extract(NEW.payload_json, '$.manifest.contentSha256') = NEW.content_sha256
              AND strftime('%Y-%m-%dT%H:%M:%SZ', NEW.finished_at) = (
                  SELECT MAX(json_extract(attempt.value, '$.endedAt'))
                  FROM json_each(NEW.payload_json, '$.attempts') attempt
              )
        ) OR (
            NEW.prior_receipt_id IS NULL
            AND (
                NEW.outcome = 'recovery_delivered'
                OR json_extract(NEW.payload_json, '$.recovery.priorReceiptId') IS NOT NULL
            )
        ) OR (
            NEW.prior_receipt_id IS NOT NULL AND NOT EXISTS (
                SELECT 1
                FROM notification_receipts prior
                JOIN notification_intents current_intent
                  ON current_intent.intent_id = NEW.intent_id
                WHERE prior.receipt_id = NEW.prior_receipt_id
                  AND prior.receipt_id <> NEW.receipt_id
                  AND prior.intent_id <> NEW.intent_id
                  AND prior.incident_id = NEW.incident_id
                  AND prior.route_id = NEW.route_id
                  AND current_intent.notification_kind = 'recovery'
                  AND NEW.outcome = 'recovery_delivered'
                  AND json_extract(NEW.payload_json, '$.recovery.priorReceiptId') = prior.receipt_id
                  AND json_extract(NEW.payload_json, '$.recovery.recoveryIntentId') = NEW.intent_id
                  AND prior.finished_at <= datetime(json_extract(NEW.payload_json, '$.recovery.recoveredAt'))
                  AND datetime(json_extract(NEW.payload_json, '$.recovery.recoveredAt')) <= NEW.finished_at
            )
        )
        BEGIN
            SELECT RAISE(ABORT, 'notification receipt requires one exact intent or cross-intent recovery predecessor');
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_job_leases_insert
        BEFORE INSERT ON scheduled_job_leases
        FOR EACH ROW
        WHEN NEW.acquired_at >= NEW.expires_at
        OR NEW.last_heartbeat_at < NEW.acquired_at
        OR NEW.last_heartbeat_at > NEW.expires_at
        OR NOT EXISTS (
            SELECT 1 FROM scheduled_job_lease_events event
            WHERE event.lease_id = NEW.current_lease_id
              AND event.job_id = NEW.job_id
              AND event.fencing_token = NEW.fencing_token
              AND event.worker_identity_sha256 = NEW.worker_identity_sha256
              AND event.acquired_at = NEW.acquired_at
              AND event.expires_at = NEW.expires_at
              AND event.initial_heartbeat_at = NEW.last_heartbeat_at
        ) OR NEW.state <> 'leased'
        BEGIN
            SELECT RAISE(ABORT, 'current lease must exactly project its root acquisition');
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_job_leases_update
        BEFORE UPDATE ON scheduled_job_leases
        FOR EACH ROW
        WHEN NEW.job_id IS NOT OLD.job_id
          OR NEW.state NOT IN ('leased', 'released', 'expired', 'superseded')
          OR NEW.last_heartbeat_at < OLD.last_heartbeat_at
          OR NEW.last_heartbeat_at > NEW.expires_at
          OR (
              NEW.current_lease_id IS OLD.current_lease_id
              AND (
                  NEW.fencing_token IS NOT OLD.fencing_token
                  OR NEW.worker_identity_sha256 IS NOT OLD.worker_identity_sha256
                  OR NEW.acquired_at IS NOT OLD.acquired_at
                  OR NEW.expires_at IS NOT OLD.expires_at
                  OR (
                      OLD.state = 'leased'
                      AND NEW.state NOT IN ('leased', 'released', 'expired', 'superseded')
                  )
                  OR (
                      OLD.state <> 'leased'
                      AND (
                          NEW.state IS NOT OLD.state
                          OR NEW.last_heartbeat_at IS NOT OLD.last_heartbeat_at
                      )
                  )
                  OR (
                      OLD.state = 'leased'
                      AND NEW.state <> 'leased'
                      AND NOT EXISTS (
                          SELECT 1 FROM scheduled_job_attempts attempt
                          WHERE attempt.job_id = NEW.job_id
                            AND attempt.lease_id = NEW.current_lease_id
                            AND attempt.fencing_token = NEW.fencing_token
                            AND attempt.lease_last_heartbeat_at = NEW.last_heartbeat_at
                            AND json_extract(attempt.payload_json, '$.lease.state') = NEW.state
                      )
                  )
              )
          )
          OR (
              NEW.current_lease_id IS NOT OLD.current_lease_id
              AND (
                  (
                      OLD.state = 'leased'
                      AND julianday('now') < julianday(OLD.expires_at)
                  )
                  OR NOT EXISTS (
                      SELECT 1 FROM scheduled_job_lease_events event
                      WHERE event.lease_id = NEW.current_lease_id
                        AND event.prior_lease_id = OLD.current_lease_id
                        AND event.job_id = NEW.job_id
                        AND event.fencing_token = OLD.fencing_token + 1
                        AND NEW.fencing_token = event.fencing_token
                        AND NEW.worker_identity_sha256 = event.worker_identity_sha256
                        AND NEW.acquired_at = event.acquired_at
                        AND NEW.expires_at = event.expires_at
                        AND NEW.last_heartbeat_at = event.initial_heartbeat_at
                        AND NEW.state = 'leased'
                  )
              )
          )
        BEGIN
            SELECT RAISE(ABORT, 'current lease projection rejected stale or non-monotonic mutation');
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_job_leases_no_delete
        BEFORE DELETE ON scheduled_job_leases
        FOR EACH ROW
        BEGIN
            SELECT RAISE(ABORT, 'current lease projection cannot be deleted');
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_job_attempts_reference_insert
        BEFORE INSERT ON scheduled_job_attempts
        FOR EACH ROW
        WHEN EXISTS (
            SELECT 1 FROM scheduled_cycles terminal
            WHERE terminal.cycle_id = NEW.cycle_id
        )
        OR NEW.attempt_number < 1 OR NEW.attempt_number > 3
        OR NOT EXISTS (
            SELECT 1
            FROM scheduled_job_intents job
            JOIN scheduled_job_leases lease ON lease.job_id = job.job_id
            JOIN scheduled_job_lease_events event
              ON event.lease_id = NEW.lease_id
             AND event.job_id = NEW.job_id
             AND event.fencing_token = NEW.fencing_token
            WHERE job.job_id = NEW.job_id
              AND job.cycle_id = NEW.cycle_id
              AND job.source_revision_id IS NEW.source_revision_id
              AND job.due_disposition <> 'not_due'
              AND json_extract(NEW.payload_json, '$.environment') = job.environment
              AND json_extract(NEW.payload_json, '$.lane') = job.lane
              AND json_extract(NEW.payload_json, '$.schedulePolicyRevisionId') = job.schedule_policy_revision_id
              AND json_extract(NEW.payload_json, '$.scheduledFor') = strftime('%Y-%m-%dT%H:%M:%SZ', job.scheduled_for)
              AND json_extract(NEW.payload_json, '$.targetType') = job.target_type
              AND json_extract(NEW.payload_json, '$.targetRevisionId') = job.target_revision_id
              AND lease.current_lease_id = NEW.lease_id
              AND lease.fencing_token = NEW.fencing_token
              AND lease.worker_identity_sha256 = NEW.worker_identity_sha256
              AND lease.state = 'leased'
              AND (
                  NEW.commit_disposition <> 'accepted_current'
                  OR julianday('now') <= julianday(lease.expires_at)
              )
              AND NEW.lease_last_heartbeat_at >= lease.last_heartbeat_at
              AND NEW.lease_last_heartbeat_at <= lease.expires_at
              AND event.worker_identity_sha256 = NEW.worker_identity_sha256
              AND event.acquired_at = NEW.lease_acquired_at
              AND event.expires_at = NEW.lease_expires_at
              AND (
                  (NEW.prior_fencing_token IS NULL AND event.prior_lease_id IS NULL)
                  OR EXISTS (
                      SELECT 1 FROM scheduled_job_lease_events parent
                      WHERE parent.lease_id = event.prior_lease_id
                        AND parent.fencing_token = NEW.prior_fencing_token
                  )
              )
        )
        OR json_extract(NEW.payload_json, '$.workerIdentitySha256') IS NOT NEW.worker_identity_sha256
        OR json_extract(NEW.payload_json, '$.attemptId') IS NOT NEW.attempt_id
        OR json_extract(NEW.payload_json, '$.jobId') IS NOT NEW.job_id
        OR json_extract(NEW.payload_json, '$.cycleId') IS NOT NEW.cycle_id
        OR CAST(json_extract(NEW.payload_json, '$.attemptNumber') AS INTEGER) IS NOT NEW.attempt_number
        OR json_extract(NEW.payload_json, '$.sourceRevisionId') IS NOT NEW.source_revision_id
        OR json_extract(NEW.payload_json, '$.timing.startedAt') IS NOT strftime('%Y-%m-%dT%H:%M:%SZ', NEW.started_at)
        OR json_extract(NEW.payload_json, '$.timing.endedAt') IS NOT strftime('%Y-%m-%dT%H:%M:%SZ', NEW.ended_at)
        OR json_extract(NEW.payload_json, '$.stageReached') IS NOT NEW.stage_reached
        OR json_extract(NEW.payload_json, '$.outcome') IS NOT NEW.outcome
        OR json_extract(NEW.payload_json, '$.lease.commitDisposition') IS NOT NEW.commit_disposition
        OR json_extract(NEW.payload_json, '$.manifest.contentSha256') IS NOT NEW.content_sha256
        OR CAST(json_extract(NEW.payload_json, '$.lease.fencingToken') AS INTEGER) IS NOT NEW.fencing_token
        OR CAST(json_extract(NEW.payload_json, '$.lease.priorFencingToken') AS INTEGER) IS NOT NEW.prior_fencing_token
        OR json_extract(NEW.payload_json, '$.lease.leaseId') IS NOT NEW.lease_id
        OR json_extract(NEW.payload_json, '$.lease.acquiredAt') IS NOT strftime('%Y-%m-%dT%H:%M:%SZ', NEW.lease_acquired_at)
        OR json_extract(NEW.payload_json, '$.lease.expiresAt') IS NOT strftime('%Y-%m-%dT%H:%M:%SZ', NEW.lease_expires_at)
        OR json_extract(NEW.payload_json, '$.lease.lastHeartbeatAt') IS NOT strftime('%Y-%m-%dT%H:%M:%SZ', NEW.lease_last_heartbeat_at)
        OR (
            NEW.attempt_number = 1
            AND NEW.prior_fencing_token IS NOT NULL
        )
        OR (
            NEW.attempt_number > 1
            AND NOT EXISTS (
                SELECT 1 FROM scheduled_job_attempts prior
                WHERE prior.job_id = NEW.job_id
                  AND prior.cycle_id = NEW.cycle_id
                  AND prior.attempt_number = NEW.attempt_number - 1
                  AND prior.fencing_token = NEW.prior_fencing_token
                  AND prior.fencing_token < NEW.fencing_token
            )
        )
        OR (
            NEW.source_check_receipt_id IS NULL
            AND EXISTS (
                SELECT 1 FROM json_each(NEW.payload_json, '$.outputReferences') reference
                WHERE json_extract(reference.value, '$.referenceType') = 'source_check_receipt'
            )
        )
        OR (
            NEW.source_check_receipt_id IS NOT NULL
            AND (
                1 <> (
                    SELECT COUNT(*) FROM json_each(NEW.payload_json, '$.outputReferences') reference
                    WHERE json_extract(reference.value, '$.referenceType') = 'source_check_receipt'
                )
                OR NOT EXISTS (
                    SELECT 1 FROM json_each(NEW.payload_json, '$.outputReferences') reference
                    WHERE json_extract(reference.value, '$.referenceType') = 'source_check_receipt'
                      AND json_extract(reference.value, '$.referenceId') = NEW.source_check_receipt_id
                      AND json_extract(reference.value, '$.contentSha256') = NEW.source_check_receipt_sha256
                )
            )
        )
        BEGIN
            SELECT RAISE(ABORT, 'attempt requires exact current worker, lease, heartbeat, and source binding');
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_source_checks_reference_insert
        BEFORE INSERT ON source_check_receipts
        FOR EACH ROW
        WHEN EXISTS (
            SELECT 1 FROM scheduled_job_intents job
            JOIN scheduled_cycles terminal ON terminal.cycle_id = job.cycle_id
            WHERE job.job_id = NEW.job_id
        )
        OR NOT EXISTS (
            SELECT 1
            FROM scheduled_job_attempts attempt
            JOIN scheduled_job_leases lease
              ON lease.job_id = attempt.job_id
             AND lease.current_lease_id = attempt.lease_id
             AND lease.fencing_token = attempt.fencing_token
             AND lease.last_heartbeat_at = attempt.lease_last_heartbeat_at
             AND lease.state = json_extract(attempt.payload_json, '$.lease.state')
            JOIN official_source_revisions revision
              ON revision.id = NEW.source_revision_id
             AND revision.official_source_id = NEW.official_source_id
            JOIN source_contract_envelopes contract
              ON contract.contract_revision_id = NEW.contract_revision_id
             AND contract.contract_id = NEW.contract_id
             AND contract.official_source_id = NEW.official_source_id
             AND contract.source_revision_id = NEW.source_revision_id
             AND contract.certification_decision_id IS NEW.source_revision_decision_id
             AND contract.certification_decision_sha256 IS NEW.source_revision_decision_sha256
             AND contract.schedule_policy_revision_id = NEW.schedule_policy_revision_id
             AND contract.contract_digest_sha256 = NEW.contract_digest_sha256
             AND contract.contract_definition_sha256 = NEW.contract_definition_sha256
            WHERE attempt.attempt_id = NEW.attempt_id
              AND attempt.job_id = NEW.job_id
              AND attempt.source_revision_id = NEW.source_revision_id
              AND attempt.fencing_token = NEW.fencing_token
              AND attempt.source_check_receipt_id = NEW.receipt_id
              AND attempt.source_check_receipt_sha256 = NEW.content_sha256
              AND json_extract(NEW.payload_json, '$.receiptId') = NEW.receipt_id
              AND json_extract(NEW.payload_json, '$.identity.attemptId') = NEW.attempt_id
              AND json_extract(NEW.payload_json, '$.identity.jobId') = NEW.job_id
              AND json_extract(NEW.payload_json, '$.identity.sourceId') = NEW.official_source_id
              AND json_extract(NEW.payload_json, '$.identity.sourceRevisionId') = NEW.source_revision_id
              AND json_extract(NEW.payload_json, '$.identity.certificationDecisionId') IS NEW.source_revision_decision_id
              AND json_extract(NEW.payload_json, '$.identity.certificationDecisionDigestSha256') IS NEW.source_revision_decision_sha256
              AND json_extract(NEW.payload_json, '$.identity.contractId') = NEW.contract_id
              AND json_extract(NEW.payload_json, '$.identity.contractRevisionId') = NEW.contract_revision_id
              AND json_extract(NEW.payload_json, '$.identity.contractDigestSha256') = NEW.contract_digest_sha256
              AND json_extract(NEW.payload_json, '$.identity.contractDefinitionSha256') = NEW.contract_definition_sha256
              AND json_extract(NEW.payload_json, '$.identity.schedulePolicyRevisionId') = NEW.schedule_policy_revision_id
              AND json_extract(NEW.payload_json, '$.identity.scheduledSlot') = strftime('%Y-%m-%dT%H:%M:%SZ', NEW.scheduled_for)
              AND CAST(json_extract(NEW.payload_json, '$.identity.fencingToken') AS INTEGER) = NEW.fencing_token
              AND json_extract(NEW.payload_json, '$.snapshot.snapshotId') IS NEW.snapshot_id
              AND json_extract(NEW.payload_json, '$.snapshot.snapshotContentSha256') IS NEW.snapshot_content_sha256
              AND json_extract(NEW.payload_json, '$.snapshot.storageReceiptSha256') IS NEW.snapshot_storage_receipt_sha256
              AND json_extract(NEW.payload_json, '$.conditionalMetadata.previousSnapshotId') IS NEW.previous_snapshot_id
              AND json_extract(NEW.payload_json, '$.conditionalMetadata.previousSnapshotContentSha256') IS NEW.previous_snapshot_content_sha256
              AND json_extract(NEW.payload_json, '$.conditionalMetadata.previousSnapshotVerificationReceiptSha256') IS NEW.previous_snapshot_verification_receipt_sha256
              AND json_extract(NEW.payload_json, '$.extraction.batchReceiptSha256') IS NEW.batch_receipt_sha256
              AND json_extract(NEW.payload_json, '$.terminalDisposition') = NEW.terminal_disposition
              AND json_extract(NEW.payload_json, '$.execution.startedAt') = strftime('%Y-%m-%dT%H:%M:%SZ', NEW.started_at)
              AND json_extract(NEW.payload_json, '$.execution.finishedAt') = strftime('%Y-%m-%dT%H:%M:%SZ', NEW.finished_at)
              AND json_extract(NEW.payload_json, '$.manifest.contentSha256') = NEW.content_sha256
              AND json_extract(NEW.payload_json, '$.certificationCheck.outcome') = NEW.certification_check_outcome
              AND json_extract(NEW.payload_json, '$.certificationCheck.checkedDecisionId') IS NEW.checked_source_revision_decision_id
              AND json_extract(NEW.payload_json, '$.certificationCheck.checkedDecisionDigestSha256') IS NEW.checked_source_revision_decision_sha256
              AND json_extract(NEW.payload_json, '$.certificationCheck.checkedSourceRevisionId') = NEW.source_revision_id
              AND json_extract(NEW.payload_json, '$.certificationCheck.checkedContractDigestSha256') = NEW.contract_digest_sha256
              AND json_extract(NEW.payload_json, '$.certificationCheck.checkedContractDefinitionSha256') = NEW.contract_definition_sha256
        ) OR (
            NEW.checked_source_revision_decision_id IS NULL
            AND NEW.certification_check_outcome <> 'missing'
        ) OR (
            NEW.checked_source_revision_decision_id IS NOT NULL AND NOT EXISTS (
                SELECT 1 FROM source_revision_decisions decision
                WHERE decision.id = NEW.checked_source_revision_decision_id
                  AND decision.source_revision_id = NEW.source_revision_id
                  AND decision.decided_at <= NEW.started_at
                  AND json_extract(decision.basis_json, '$.sourceContractDecisionEvidence.decisionDigestSha256') = NEW.checked_source_revision_decision_sha256
                  AND json_extract(decision.basis_json, '$.sourceContractDecisionEvidence.contractDefinitionSha256') = NEW.contract_definition_sha256
                  AND (
                      NEW.certification_check_outcome = 'mismatch'
                      OR decision.outcome = CASE
                          WHEN NEW.certification_check_outcome = 'expired' THEN 'certified'
                          ELSE NEW.certification_check_outcome
                      END
                  )
                  AND NOT EXISTS (
                      SELECT 1 FROM source_revision_decisions successor
                      WHERE successor.supersedes_decision_id = decision.id
                        AND successor.decided_at <= NEW.started_at
                  )
            )
        ) OR (
            NEW.snapshot_id IS NOT NULL AND NOT EXISTS (
                SELECT 1 FROM source_snapshots snapshot
                WHERE snapshot.id = NEW.snapshot_id
                  AND snapshot.source_revision_id = NEW.source_revision_id
                  AND snapshot.official_source_id = NEW.official_source_id
                  AND snapshot.content_hash = NEW.snapshot_content_sha256
                  AND json_extract(snapshot.fetch_metadata, '$.storageReceiptSha256') IS NEW.snapshot_storage_receipt_sha256
            )
        ) OR (
            NEW.previous_snapshot_id IS NOT NULL AND NOT EXISTS (
                SELECT 1 FROM source_snapshots snapshot
                WHERE snapshot.id = NEW.previous_snapshot_id
                  AND snapshot.source_revision_id = NEW.source_revision_id
                  AND snapshot.official_source_id = NEW.official_source_id
                  AND snapshot.content_hash = NEW.previous_snapshot_content_sha256
                  AND json_extract(snapshot.fetch_metadata, '$.storageVerificationReceiptSha256') = NEW.previous_snapshot_verification_receipt_sha256
            )
        ) OR (
            (NEW.checked_source_revision_decision_id IS NULL)
            <> (NEW.checked_source_revision_decision_sha256 IS NULL)
        ) OR (
            (NEW.snapshot_id IS NULL) <> (NEW.snapshot_content_sha256 IS NULL)
            OR (NEW.snapshot_id IS NULL) <> (NEW.snapshot_storage_receipt_sha256 IS NULL)
        ) OR (
            (NEW.previous_snapshot_id IS NULL) <> (NEW.previous_snapshot_content_sha256 IS NULL)
            OR (NEW.previous_snapshot_id IS NULL) <> (NEW.previous_snapshot_verification_receipt_sha256 IS NULL)
        )
        BEGIN
            SELECT RAISE(ABORT, 'source check requires exact attempt/revision/decision/snapshot bindings');
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_extraction_batches_reference_insert
        BEFORE INSERT ON extraction_batches
        FOR EACH ROW
        WHEN NOT EXISTS (
            SELECT 1 FROM source_check_receipts receipt
            WHERE receipt.receipt_id = NEW.source_check_receipt_id
              AND receipt.attempt_id = NEW.attempt_id
              AND receipt.job_id = NEW.job_id
              AND receipt.source_revision_id = NEW.source_revision_id
              AND receipt.source_revision_decision_id IS NEW.source_revision_decision_id
              AND receipt.snapshot_id IS NEW.snapshot_id
              AND receipt.batch_receipt_sha256 = NEW.batch_receipt_sha256
              AND json_extract(NEW.payload_json, '$.batchReceiptSha256') = NEW.batch_receipt_sha256
              AND json_extract(NEW.payload_json, '$.schemaFingerprintSha256') = NEW.schema_fingerprint_sha256
              AND CAST(json_extract(NEW.payload_json, '$.sourceRecordsObserved') AS INTEGER) = NEW.source_records_observed
              AND CAST(json_extract(NEW.payload_json, '$.rowsParsed') AS INTEGER) = NEW.rows_parsed
              AND CAST(json_extract(NEW.payload_json, '$.claimCandidatesEmitted') AS INTEGER) = NEW.claim_candidates_emitted
              AND CAST(json_extract(NEW.payload_json, '$.claimsAdmitted') AS INTEGER) = NEW.claims_admitted
              AND CAST(json_extract(NEW.payload_json, '$.recordsExcluded') AS INTEGER) = NEW.records_excluded
              AND CAST(json_extract(NEW.payload_json, '$.recordsRejected') AS INTEGER) = NEW.records_rejected
              AND CAST(json_extract(NEW.payload_json, '$.recordsQuarantined') AS INTEGER) = NEW.records_quarantined
        )
        BEGIN
            SELECT RAISE(ABORT, 'extraction batch must exactly project its source-check receipt');
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_outbox_items_reference_insert
        BEFORE INSERT ON notification_outbox_items
        FOR EACH ROW
        WHEN NOT EXISTS (
            SELECT 1 FROM ops_incident_events event
            WHERE event.event_id = NEW.incident_event_id
              AND event.outbox_batch_id = NEW.outbox_batch_id
              AND event.outbox_intent_count > NEW.intent_ordinal
              AND (
                  SELECT COUNT(*) FROM notification_outbox_items existing
                  WHERE existing.incident_event_id = NEW.incident_event_id
              ) < event.outbox_intent_count
        )
        BEGIN
            SELECT RAISE(ABORT, 'outbox item exceeds or changes the immutable event denominator');
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_notification_intents_reference_insert
        BEFORE INSERT ON notification_intents
        FOR EACH ROW
        WHEN NOT EXISTS (
            SELECT 1
            FROM ops_incident_events event
            JOIN notification_outbox_items item
              ON item.incident_event_id = event.event_id
             AND item.intent_id = NEW.intent_id
            WHERE event.event_id = NEW.incident_event_id
              AND event.incident_id = NEW.incident_id
              AND event.outbox_batch_id = NEW.outbox_batch_id
              AND item.outbox_batch_id = NEW.outbox_batch_id
              AND json_extract(NEW.payload_json, '$.intentId') = NEW.intent_id
              AND json_extract(NEW.payload_json, '$.dedupeKeySha256') = NEW.dedupe_key_sha256
              AND json_extract(NEW.payload_json, '$.incidentId') = NEW.incident_id
              AND json_extract(NEW.payload_json, '$.incidentEventId') = NEW.incident_event_id
              AND json_extract(NEW.payload_json, '$.notificationKind') = NEW.notification_kind
              AND json_extract(NEW.payload_json, '$.route.routeId') = NEW.route_id
              AND json_extract(NEW.payload_json, '$.dispatchEligibility') = NEW.dispatch_eligibility
              AND json_extract(NEW.payload_json, '$.manifest.contentSha256') = NEW.content_sha256
        )
        BEGIN
            SELECT RAISE(ABORT, 'notification intent must bind its exact incident event outbox batch');
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_outbox_batches_completion_insert
        BEFORE INSERT ON notification_outbox_batches
        FOR EACH ROW
        WHEN NOT EXISTS (
            SELECT 1 FROM ops_incident_events event
            WHERE event.event_id = NEW.incident_event_id
              AND event.outbox_batch_id = NEW.outbox_batch_id
              AND event.outbox_intent_count = NEW.intent_count
              AND (
                  SELECT COUNT(*) FROM notification_outbox_items item
                  WHERE item.incident_event_id = NEW.incident_event_id
                    AND item.outbox_batch_id = NEW.outbox_batch_id
              ) = NEW.intent_count
              AND (
                  SELECT COUNT(*) FROM notification_intents intent
                  WHERE intent.incident_event_id = NEW.incident_event_id
                    AND intent.outbox_batch_id = NEW.outbox_batch_id
              ) = NEW.intent_count
          )
        BEGIN
            SELECT RAISE(ABORT, 'outbox completion requires the exact item and intent denominator');
        END
        """
    )


def _create_postgresql_guards() -> None:
    for table in IMMUTABLE_TABLES:
        op.execute(
            f"""
            CREATE TRIGGER trg_{table}_no_mutation
            BEFORE UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION ledger_reject_append_only_mutation()
            """
        )

    op.execute(
        """
        CREATE FUNCTION ledger_validate_operational_chain()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, public
        AS $function$
        BEGIN
            IF TG_TABLE_NAME = 'scheduled_job_lease_events' THEN
                IF NEW.acquired_at >= NEW.expires_at
                   OR NEW.initial_heartbeat_at < NEW.acquired_at
                   OR NEW.initial_heartbeat_at > NEW.expires_at
                   OR EXISTS (
                       SELECT 1 FROM scheduled_job_intents job
                       JOIN scheduled_cycles terminal ON terminal.cycle_id = job.cycle_id
                       WHERE job.job_id = NEW.job_id
                   ) THEN
                    RAISE EXCEPTION 'job lease event has an invalid interval or terminal job'
                        USING ERRCODE = '23514';
                ELSIF NEW.prior_lease_id IS NULL THEN
                    IF NEW.fencing_token <> 1 THEN
                        RAISE EXCEPTION 'job lease root requires fencing token one'
                            USING ERRCODE = '23514';
                    END IF;
                ELSIF NOT EXISTS (
                    SELECT 1 FROM scheduled_job_lease_events parent
                    JOIN scheduled_job_leases current
                      ON current.job_id = parent.job_id
                     AND current.current_lease_id = parent.lease_id
                    WHERE parent.lease_id = NEW.prior_lease_id
                      AND parent.job_id = NEW.job_id
                      AND NEW.fencing_token = parent.fencing_token + 1
                      AND NEW.acquired_at >= parent.acquired_at
                      AND (
                          current.state <> 'leased'
                          OR clock_timestamp() >= current.expires_at
                      )
                ) THEN
                    RAISE EXCEPTION 'job lease events require one exact monotonic lineage'
                        USING ERRCODE = '23514';
                END IF;
            ELSIF TG_TABLE_NAME = 'source_contract_envelopes' THEN
                IF NEW.supersedes_contract_revision_id IS NOT NULL
                   AND NOT EXISTS (
                       SELECT 1 FROM source_contract_envelopes parent
                       WHERE parent.contract_revision_id = NEW.supersedes_contract_revision_id
                         AND parent.contract_id = NEW.contract_id
                   ) THEN
                    RAISE EXCEPTION 'source contract predecessor belongs to another contract'
                        USING ERRCODE = '23514';
                END IF;
            ELSIF TG_TABLE_NAME = 'benchmark_definition_revisions' THEN
                IF NEW.supersedes_definition_revision_id IS NOT NULL
                   AND NOT EXISTS (
                       SELECT 1 FROM benchmark_definition_revisions parent
                       WHERE parent.benchmark_definition_revision_id = NEW.supersedes_definition_revision_id
                         AND parent.benchmark_family_id = NEW.benchmark_family_id
                   ) THEN
                    RAISE EXCEPTION 'benchmark definition parent belongs to another family'
                        USING ERRCODE = '23514';
                END IF;
            ELSIF TG_TABLE_NAME = 'evaluation_subject_revisions' THEN
                IF NEW.supersedes_subject_revision_id IS NOT NULL
                   AND NOT EXISTS (
                       SELECT 1 FROM evaluation_subject_revisions parent
                       WHERE parent.subject_revision_id = NEW.supersedes_subject_revision_id
                         AND parent.subject_id = NEW.subject_id
                         AND parent.subject_type = NEW.subject_type
                         AND parent.observed_composition_fingerprint_sha256 = NEW.observed_composition_fingerprint_sha256
                         AND parent.raw_identity_sha256 = NEW.raw_identity_sha256
                         AND (parent.model_entity_id IS NULL OR parent.model_entity_id IS NOT DISTINCT FROM NEW.model_entity_id)
                   ) THEN
                    RAISE EXCEPTION 'subject revision changed aggregate or raw composition'
                        USING ERRCODE = '23514';
                END IF;
            ELSIF TG_TABLE_NAME = 'identity_decisions' THEN
                IF NEW.expected_prior_decision_id IS NULL THEN
                    IF NEW.decision_sequence <> 1 THEN
                        RAISE EXCEPTION 'identity decision root requires sequence one'
                            USING ERRCODE = '23514';
                    END IF;
                ELSIF NOT EXISTS (
                    SELECT 1 FROM identity_decisions parent
                    WHERE parent.decision_id = NEW.expected_prior_decision_id
                      AND parent.candidate_reference = NEW.candidate_reference
                      AND parent.observation_reference = NEW.observation_reference
                      AND parent.identity_item_fingerprint_sha256 = NEW.identity_item_fingerprint_sha256
                      AND NEW.decision_sequence = parent.decision_sequence + 1
                      AND (
                          NEW.decided_at IS NULL
                          OR parent.decided_at IS NULL
                          OR NEW.decided_at > parent.decided_at
                      )
                ) THEN
                    RAISE EXCEPTION 'identity decisions require one exact candidate lineage'
                        USING ERRCODE = '23514';
                END IF;
                IF NEW.selected_subject_id IS NOT NULL
                   AND NOT EXISTS (
                       SELECT 1 FROM evaluation_subject_revisions subject
                       WHERE subject.subject_id = NEW.selected_subject_id
                         AND subject.lifecycle_status = 'reviewed'
                         AND subject.resolution_status = 'resolved'
                         AND subject.decision_reference IS NOT NULL
                         AND NOT EXISTS (
                             SELECT 1 FROM evaluation_subject_revisions successor
                             WHERE successor.supersedes_subject_revision_id = subject.subject_revision_id
                         )
                   ) THEN
                    RAISE EXCEPTION 'identity decision selected subject is absent'
                        USING ERRCODE = '23514';
                END IF;
            ELSIF TG_TABLE_NAME = 'ops_incident_events' THEN
                IF NEW.expected_prior_event_id IS NULL THEN
                    IF NEW.event_ordinal <> 1 OR NEW.from_state IS NOT NULL THEN
                        RAISE EXCEPTION 'incident event root requires ordinal one'
                            USING ERRCODE = '23514';
                    END IF;
                ELSIF NOT EXISTS (
                    SELECT 1 FROM ops_incident_events parent
                    WHERE parent.event_id = NEW.expected_prior_event_id
                      AND parent.incident_id = NEW.incident_id
                      AND NEW.event_ordinal = parent.event_ordinal + 1
                      AND NEW.from_state IS NOT DISTINCT FROM parent.to_state
                ) THEN
                    RAISE EXCEPTION 'incident event requires one exact linear lineage'
                        USING ERRCODE = '23514';
                END IF;
            ELSIF TG_TABLE_NAME = 'review_work_item_events' THEN
                IF NEW.expected_prior_event_id IS NULL THEN
                    IF NEW.event_ordinal <> 1 OR NEW.from_state IS NOT NULL THEN
                        RAISE EXCEPTION 'work-item event root requires ordinal one'
                            USING ERRCODE = '23514';
                    END IF;
                ELSIF NOT EXISTS (
                    SELECT 1 FROM review_work_item_events parent
                    WHERE parent.event_id = NEW.expected_prior_event_id
                      AND parent.work_item_id = NEW.work_item_id
                      AND NEW.event_ordinal = parent.event_ordinal + 1
                      AND NEW.from_state IS NOT DISTINCT FROM parent.to_state
                ) THEN
                    RAISE EXCEPTION 'work-item event requires one exact linear lineage'
                        USING ERRCODE = '23514';
                END IF;
            ELSIF TG_TABLE_NAME = 'notification_receipts' THEN
                IF NOT EXISTS (
                    SELECT 1 FROM notification_intents intent
                    WHERE intent.intent_id = NEW.intent_id
                      AND intent.incident_id = NEW.incident_id
                      AND intent.route_id = NEW.route_id
                      AND (NEW.payload_json ->> 'receiptId') = NEW.receipt_id
                      AND (NEW.payload_json ->> 'receiptDedupeKeySha256') = NEW.receipt_dedupe_key_sha256
                      AND (NEW.payload_json -> 'intentBinding' ->> 'intentId') = NEW.intent_id
                      AND (NEW.payload_json -> 'intentBinding' ->> 'intentContentSha256') = intent.content_sha256
                      AND (NEW.payload_json -> 'intentBinding' ->> 'intentDedupeKeySha256') = intent.dedupe_key_sha256
                      AND (NEW.payload_json -> 'intentBinding' ->> 'payloadSha256') = (intent.payload_json ->> 'payloadSha256')
                      AND (NEW.payload_json -> 'intentBinding' ->> 'routeId') = NEW.route_id
                      AND (NEW.payload_json -> 'intentBinding' ->> 'adapterId') = NEW.adapter_id
                      AND (NEW.payload_json -> 'intentBinding' ->> 'adapterVersion') = NEW.adapter_version
                      AND (NEW.payload_json ->> 'outcome') = NEW.outcome
                      AND (NEW.payload_json -> 'manifest' ->> 'contentSha256') = NEW.content_sha256
                      AND NEW.finished_at = (
                          SELECT MAX((attempt ->> 'endedAt')::timestamptz)
                          FROM jsonb_array_elements(NEW.payload_json -> 'attempts') attempt
                      )
                ) OR (
                    NEW.prior_receipt_id IS NULL
                    AND (
                        NEW.outcome = 'recovery_delivered'
                        OR NEW.payload_json -> 'recovery' ->> 'priorReceiptId' IS NOT NULL
                    )
                ) OR (
                    NEW.prior_receipt_id IS NOT NULL AND NOT EXISTS (
                        SELECT 1
                        FROM notification_receipts prior
                        JOIN notification_intents current_intent
                          ON current_intent.intent_id = NEW.intent_id
                        WHERE prior.receipt_id = NEW.prior_receipt_id
                          AND prior.receipt_id <> NEW.receipt_id
                          AND prior.intent_id <> NEW.intent_id
                          AND prior.incident_id = NEW.incident_id
                          AND prior.route_id = NEW.route_id
                          AND current_intent.notification_kind = 'recovery'
                          AND NEW.outcome = 'recovery_delivered'
                          AND NEW.payload_json -> 'recovery' ->> 'priorReceiptId' = prior.receipt_id
                          AND NEW.payload_json -> 'recovery' ->> 'recoveryIntentId' = NEW.intent_id
                          AND prior.finished_at <= (NEW.payload_json -> 'recovery' ->> 'recoveredAt')::timestamptz
                          AND (NEW.payload_json -> 'recovery' ->> 'recoveredAt')::timestamptz <= NEW.finished_at
                    )
                ) THEN
                    RAISE EXCEPTION 'notification receipt requires one exact intent or recovery predecessor'
                        USING ERRCODE = '23514';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $function$
        """
    )
    for trigger_name, table in (
        ("trg_job_lease_events_chain_insert", "scheduled_job_lease_events"),
        ("trg_source_contracts_chain_insert", "source_contract_envelopes"),
        ("trg_benchmark_definitions_chain_insert", "benchmark_definition_revisions"),
        ("trg_subject_revisions_chain_insert", "evaluation_subject_revisions"),
        ("trg_identity_decisions_chain_insert", "identity_decisions"),
        ("trg_incident_events_chain_insert", "ops_incident_events"),
        ("trg_work_events_chain_insert", "review_work_item_events"),
        ("trg_notification_receipts_reference_insert", "notification_receipts"),
    ):
        op.execute(
            f"""
            CREATE TRIGGER {trigger_name}
            BEFORE INSERT ON {table}
            FOR EACH ROW EXECUTE FUNCTION ledger_validate_operational_chain()
            """
        )

    op.execute(
        """
        CREATE FUNCTION ledger_validate_job_lease_projection()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, public
        AS $function$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'current lease projection cannot be deleted'
                    USING ERRCODE = '23000';
            END IF;
            IF TG_OP = 'INSERT' THEN
                IF NEW.state <> 'leased'
                   OR NEW.acquired_at >= NEW.expires_at
                   OR NEW.last_heartbeat_at < NEW.acquired_at
                   OR NEW.last_heartbeat_at > NEW.expires_at
                   OR NOT EXISTS (
                    SELECT 1 FROM scheduled_job_lease_events event
                    WHERE event.lease_id = NEW.current_lease_id
                      AND event.job_id = NEW.job_id
                      AND event.fencing_token = NEW.fencing_token
                      AND event.worker_identity_sha256 = NEW.worker_identity_sha256
                      AND event.acquired_at = NEW.acquired_at
                      AND event.expires_at = NEW.expires_at
                      AND event.initial_heartbeat_at = NEW.last_heartbeat_at
                ) THEN
                    RAISE EXCEPTION 'current lease must exactly project its root acquisition'
                        USING ERRCODE = '23514';
                END IF;
                RETURN NEW;
            END IF;
            IF NEW.job_id IS DISTINCT FROM OLD.job_id
               OR NEW.state NOT IN ('leased', 'released', 'expired', 'superseded')
               OR NEW.last_heartbeat_at < OLD.last_heartbeat_at
               OR NEW.last_heartbeat_at > NEW.expires_at THEN
                RAISE EXCEPTION 'current lease projection rejected stale mutation'
                    USING ERRCODE = '23514';
            END IF;
            IF NEW.current_lease_id IS NOT DISTINCT FROM OLD.current_lease_id THEN
                IF NEW.fencing_token IS DISTINCT FROM OLD.fencing_token
                   OR NEW.worker_identity_sha256 IS DISTINCT FROM OLD.worker_identity_sha256
                   OR NEW.acquired_at IS DISTINCT FROM OLD.acquired_at
                   OR NEW.expires_at IS DISTINCT FROM OLD.expires_at
                   OR (
                       OLD.state = 'leased'
                       AND NEW.state NOT IN ('leased', 'released', 'expired', 'superseded')
                   )
                   OR (
                       OLD.state <> 'leased'
                       AND (
                           NEW.state IS DISTINCT FROM OLD.state
                           OR NEW.last_heartbeat_at IS DISTINCT FROM OLD.last_heartbeat_at
                       )
                   )
                   OR (
                       OLD.state = 'leased'
                       AND NEW.state <> 'leased'
                       AND NOT EXISTS (
                           SELECT 1 FROM scheduled_job_attempts attempt
                           WHERE attempt.job_id = NEW.job_id
                             AND attempt.lease_id = NEW.current_lease_id
                             AND attempt.fencing_token = NEW.fencing_token
                             AND attempt.lease_last_heartbeat_at = NEW.last_heartbeat_at
                             AND attempt.payload_json -> 'lease' ->> 'state' = NEW.state
                       )
                   ) THEN
                    RAISE EXCEPTION 'same lease may update only heartbeat and terminal state'
                        USING ERRCODE = '23514';
                END IF;
            ELSIF (
                       OLD.state = 'leased'
                       AND clock_timestamp() < OLD.expires_at
                  )
               OR NOT EXISTS (
                   SELECT 1 FROM scheduled_job_lease_events event
                   WHERE event.lease_id = NEW.current_lease_id
                     AND event.prior_lease_id = OLD.current_lease_id
                     AND event.job_id = NEW.job_id
                     AND event.fencing_token = OLD.fencing_token + 1
                     AND NEW.fencing_token = event.fencing_token
                     AND NEW.worker_identity_sha256 = event.worker_identity_sha256
                     AND NEW.acquired_at = event.acquired_at
                     AND NEW.expires_at = event.expires_at
                     AND NEW.last_heartbeat_at = event.initial_heartbeat_at
                     AND NEW.state = 'leased'
               ) THEN
                RAISE EXCEPTION 'replacement lease must be the exact next acquisition event'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $function$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_job_leases_projection
        BEFORE INSERT OR UPDATE OR DELETE ON scheduled_job_leases
        FOR EACH ROW EXECUTE FUNCTION ledger_validate_job_lease_projection()
        """
    )

    op.execute(
        """
        CREATE FUNCTION ledger_validate_operational_reference()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, public
        AS $function$
        DECLARE
            current_token integer;
            current_lease text;
            current_worker text;
            current_heartbeat timestamptz;
            current_expiry timestamptz;
            current_state text;
        BEGIN
            IF TG_TABLE_NAME = 'scheduled_job_intents' THEN
                IF EXISTS (
                    SELECT 1 FROM scheduled_cycle_intent_completions completion
                    WHERE completion.cycle_id = NEW.cycle_id
                ) OR NOT EXISTS (
                    SELECT 1
                    FROM scheduled_cycle_intents cycle
                    JOIN LATERAL jsonb_array_elements(cycle.payload_json -> 'jobs') item ON TRUE
                    WHERE cycle.cycle_id = NEW.cycle_id
                      AND cycle.environment = NEW.environment
                      AND cycle.lane = NEW.lane
                      AND cycle.scheduled_for = NEW.scheduled_for
                      AND cycle.schedule_policy_revision_id = NEW.schedule_policy_revision_id
                      AND item ->> 'jobId' = NEW.job_id
                      AND item ->> 'idempotencyKeySha256' = NEW.idempotency_key_sha256
                      AND item ->> 'targetType' = NEW.target_type
                      AND item ->> 'targetRevisionId' = NEW.target_revision_id
                      AND item ->> 'sourceRevisionId' IS NOT DISTINCT FROM NEW.source_revision_id
                      AND item ->> 'dueDisposition' = NEW.due_disposition
                      AND item ->> 'dispositionReasonCode' = NEW.disposition_reason_code
                      AND NEW.payload_json ->> 'jobId' = NEW.job_id
                      AND NEW.payload_json ->> 'idempotencyKeySha256' = NEW.idempotency_key_sha256
                      AND NEW.payload_json ->> 'targetType' = NEW.target_type
                      AND NEW.payload_json ->> 'targetRevisionId' = NEW.target_revision_id
                      AND NEW.payload_json ->> 'sourceRevisionId' IS NOT DISTINCT FROM NEW.source_revision_id
                      AND NEW.payload_json ->> 'dueDisposition' = NEW.due_disposition
                      AND NEW.payload_json ->> 'dispositionReasonCode' = NEW.disposition_reason_code
                ) THEN
                    RAISE EXCEPTION 'scheduled job intent must belong to an open exact cycle intent'
                        USING ERRCODE = '23514';
                END IF;
            ELSIF TG_TABLE_NAME = 'scheduled_job_attempts' THEN
                SELECT lease.fencing_token, lease.current_lease_id,
                       lease.worker_identity_sha256, lease.last_heartbeat_at,
                       lease.expires_at, lease.state
                  INTO current_token, current_lease, current_worker,
                       current_heartbeat, current_expiry, current_state
                FROM scheduled_job_leases lease
                WHERE lease.job_id = NEW.job_id
                FOR UPDATE;
                IF EXISTS (
                       SELECT 1 FROM scheduled_cycles terminal
                       WHERE terminal.cycle_id = NEW.cycle_id
                   )
                   OR NEW.attempt_number < 1 OR NEW.attempt_number > 3
                   OR current_token IS DISTINCT FROM NEW.fencing_token
                   OR current_lease IS DISTINCT FROM NEW.lease_id
                   OR current_worker IS DISTINCT FROM NEW.worker_identity_sha256
                   OR current_state IS DISTINCT FROM 'leased'
                   OR (
                       NEW.commit_disposition = 'accepted_current'
                       AND clock_timestamp() > current_expiry
                   )
                   OR NEW.lease_last_heartbeat_at < current_heartbeat
                   OR NEW.lease_last_heartbeat_at > current_expiry
                   OR (NEW.payload_json ->> 'workerIdentitySha256') IS DISTINCT FROM NEW.worker_identity_sha256
                   OR (NEW.payload_json ->> 'attemptId') IS DISTINCT FROM NEW.attempt_id
                   OR (NEW.payload_json ->> 'jobId') IS DISTINCT FROM NEW.job_id
                   OR (NEW.payload_json ->> 'cycleId') IS DISTINCT FROM NEW.cycle_id
                   OR (NEW.payload_json ->> 'attemptNumber')::integer IS DISTINCT FROM NEW.attempt_number
                   OR (NEW.payload_json ->> 'sourceRevisionId') IS DISTINCT FROM NEW.source_revision_id
                   OR (NEW.payload_json -> 'timing' ->> 'startedAt')::timestamptz IS DISTINCT FROM NEW.started_at
                   OR (NEW.payload_json -> 'timing' ->> 'endedAt')::timestamptz IS DISTINCT FROM NEW.ended_at
                   OR (NEW.payload_json ->> 'stageReached') IS DISTINCT FROM NEW.stage_reached
                   OR (NEW.payload_json ->> 'outcome') IS DISTINCT FROM NEW.outcome
                   OR (NEW.payload_json -> 'lease' ->> 'commitDisposition') IS DISTINCT FROM NEW.commit_disposition
                   OR (NEW.payload_json -> 'manifest' ->> 'contentSha256') IS DISTINCT FROM NEW.content_sha256
                   OR (NEW.payload_json -> 'lease' ->> 'leaseId') IS DISTINCT FROM NEW.lease_id
                   OR (NEW.payload_json -> 'lease' ->> 'fencingToken')::integer IS DISTINCT FROM NEW.fencing_token
                   OR (NEW.payload_json -> 'lease' ->> 'priorFencingToken')::integer IS DISTINCT FROM NEW.prior_fencing_token
                   OR (NEW.payload_json -> 'lease' ->> 'acquiredAt')::timestamptz IS DISTINCT FROM NEW.lease_acquired_at
                   OR (NEW.payload_json -> 'lease' ->> 'expiresAt')::timestamptz IS DISTINCT FROM NEW.lease_expires_at
                   OR (NEW.payload_json -> 'lease' ->> 'lastHeartbeatAt')::timestamptz IS DISTINCT FROM NEW.lease_last_heartbeat_at
                   OR NOT EXISTS (
                       SELECT 1
                       FROM scheduled_job_intents job
                       JOIN scheduled_job_lease_events event
                         ON event.lease_id = NEW.lease_id
                        AND event.job_id = NEW.job_id
                        AND event.fencing_token = NEW.fencing_token
                       WHERE job.job_id = NEW.job_id
                         AND job.cycle_id = NEW.cycle_id
                         AND job.source_revision_id IS NOT DISTINCT FROM NEW.source_revision_id
                         AND job.due_disposition <> 'not_due'
                         AND NEW.payload_json ->> 'environment' = job.environment
                         AND NEW.payload_json ->> 'lane' = job.lane
                         AND NEW.payload_json ->> 'schedulePolicyRevisionId' = job.schedule_policy_revision_id
                         AND (NEW.payload_json ->> 'scheduledFor')::timestamptz = job.scheduled_for
                         AND NEW.payload_json ->> 'targetType' = job.target_type
                         AND NEW.payload_json ->> 'targetRevisionId' = job.target_revision_id
                         AND event.worker_identity_sha256 = NEW.worker_identity_sha256
                         AND event.acquired_at = NEW.lease_acquired_at
                         AND event.expires_at = NEW.lease_expires_at
                         AND (
                             (NEW.prior_fencing_token IS NULL AND event.prior_lease_id IS NULL)
                             OR EXISTS (
                                 SELECT 1 FROM scheduled_job_lease_events parent
                                 WHERE parent.lease_id = event.prior_lease_id
                                   AND parent.fencing_token = NEW.prior_fencing_token
                             )
                         )
                   )
                   OR (
                       NEW.attempt_number = 1
                       AND NEW.prior_fencing_token IS NOT NULL
                   )
                   OR (
                       NEW.attempt_number > 1
                       AND NOT EXISTS (
                           SELECT 1 FROM scheduled_job_attempts prior
                           WHERE prior.job_id = NEW.job_id
                             AND prior.cycle_id = NEW.cycle_id
                             AND prior.attempt_number = NEW.attempt_number - 1
                             AND prior.fencing_token = NEW.prior_fencing_token
                             AND prior.fencing_token < NEW.fencing_token
                       )
                   )
                   OR (
                       NEW.source_check_receipt_id IS NULL
                       AND EXISTS (
                           SELECT 1 FROM jsonb_array_elements(NEW.payload_json -> 'outputReferences') reference
                           WHERE reference ->> 'referenceType' = 'source_check_receipt'
                       )
                   )
                   OR (
                       NEW.source_check_receipt_id IS NOT NULL
                       AND (
                           1 <> (
                               SELECT COUNT(*) FROM jsonb_array_elements(NEW.payload_json -> 'outputReferences') reference
                               WHERE reference ->> 'referenceType' = 'source_check_receipt'
                           )
                           OR NOT EXISTS (
                               SELECT 1 FROM jsonb_array_elements(NEW.payload_json -> 'outputReferences') reference
                               WHERE reference ->> 'referenceType' = 'source_check_receipt'
                                 AND reference ->> 'referenceId' = NEW.source_check_receipt_id
                                 AND reference ->> 'contentSha256' = NEW.source_check_receipt_sha256
                           )
                       )
                   ) THEN
                    RAISE EXCEPTION 'attempt requires exact current worker, lease, heartbeat, and source binding'
                        USING ERRCODE = '23514';
                END IF;
            ELSIF TG_TABLE_NAME = 'source_contract_envelopes' THEN
                IF NOT EXISTS (
                    SELECT 1 FROM official_source_revisions revision
                    WHERE revision.id = NEW.source_revision_id
                      AND revision.official_source_id = NEW.official_source_id
                      AND NEW.payload_json ->> 'contractId' = NEW.contract_id
                      AND NEW.payload_json ->> 'contractRevisionId' = NEW.contract_revision_id
                      AND NEW.payload_json ->> 'supersedesContractRevisionId' IS NOT DISTINCT FROM NEW.supersedes_contract_revision_id
                      AND NEW.payload_json -> 'logicalSource' ->> 'sourceId' = NEW.official_source_id
                      AND NEW.payload_json -> 'logicalSource' ->> 'sourceRevisionId' = NEW.source_revision_id
                      AND NEW.payload_json -> 'schedule' ->> 'schedulePolicyRevisionId' = NEW.schedule_policy_revision_id
                      AND NEW.payload_json ->> 'lifecycleStatus' = NEW.lifecycle_status
                      AND NEW.payload_json -> 'manifest' ->> 'contentSha256' = NEW.contract_digest_sha256
                      AND NEW.payload_json -> 'manifest' ->> 'definitionSha256' = NEW.contract_definition_sha256
                      AND NEW.payload_json -> 'certification' ->> 'decisionId' IS NOT DISTINCT FROM NEW.certification_decision_id
                      AND NEW.payload_json -> 'certification' ->> 'decisionDigestSha256' IS NOT DISTINCT FROM NEW.certification_decision_sha256
                      AND (
                          (
                              NEW.certification_decision_id IS NULL
                              AND NEW.certification_decision_sha256 IS NULL
                              AND NEW.payload_json -> 'certification' ->> 'decisionOutcome' = 'not_assessed'
                          ) OR EXISTS (
                              SELECT 1 FROM source_revision_decisions decision
                              WHERE decision.id = NEW.certification_decision_id
                                AND decision.source_revision_id = NEW.source_revision_id
                                AND decision.outcome = NEW.payload_json -> 'certification' ->> 'decisionOutcome'
                                AND decision.basis_json -> 'sourceContractDecisionEvidence' ->> 'decisionDigestSha256' = NEW.certification_decision_sha256
                                AND decision.basis_json -> 'sourceContractDecisionEvidence' ->> 'contractDefinitionSha256' = NEW.contract_definition_sha256
                                AND decision.basis_json -> 'sourceContractDecisionEvidence' ->> 'effectiveOn' = NEW.payload_json -> 'certification' ->> 'effectiveOn'
                                AND decision.basis_json -> 'sourceContractDecisionEvidence' ->> 'expiresOn' = NEW.payload_json -> 'certification' ->> 'expiresOn'
                          )
                      )
                ) THEN
                    RAISE EXCEPTION 'source contract requires exact source and durable decision evidence'
                        USING ERRCODE = '23514';
                END IF;
            ELSIF TG_TABLE_NAME = 'source_check_receipts' THEN
                SELECT lease.fencing_token, lease.current_lease_id
                  INTO current_token, current_lease
                FROM scheduled_job_leases lease
                WHERE lease.job_id = NEW.job_id
                FOR UPDATE;
                IF EXISTS (
                       SELECT 1 FROM scheduled_job_intents job
                       JOIN scheduled_cycles terminal ON terminal.cycle_id = job.cycle_id
                       WHERE job.job_id = NEW.job_id
                   )
                   OR current_token IS DISTINCT FROM NEW.fencing_token
                   OR NOT EXISTS (
                       SELECT 1
                       FROM scheduled_job_attempts attempt
                       JOIN scheduled_job_leases lease
                         ON lease.job_id = attempt.job_id
                        AND lease.current_lease_id = attempt.lease_id
                        AND lease.fencing_token = attempt.fencing_token
                        AND lease.last_heartbeat_at = attempt.lease_last_heartbeat_at
                        AND lease.state = attempt.payload_json -> 'lease' ->> 'state'
                       JOIN official_source_revisions revision
                         ON revision.id = NEW.source_revision_id
                        AND revision.official_source_id = NEW.official_source_id
                       JOIN source_contract_envelopes contract
                         ON contract.contract_revision_id = NEW.contract_revision_id
                        AND contract.contract_id = NEW.contract_id
                        AND contract.official_source_id = NEW.official_source_id
                        AND contract.source_revision_id = NEW.source_revision_id
                        AND contract.certification_decision_id IS NOT DISTINCT FROM NEW.source_revision_decision_id
                        AND contract.certification_decision_sha256 IS NOT DISTINCT FROM NEW.source_revision_decision_sha256
                        AND contract.schedule_policy_revision_id = NEW.schedule_policy_revision_id
                        AND contract.contract_digest_sha256 = NEW.contract_digest_sha256
                        AND contract.contract_definition_sha256 = NEW.contract_definition_sha256
                       WHERE attempt.attempt_id = NEW.attempt_id
                         AND attempt.job_id = NEW.job_id
                         AND attempt.source_revision_id = NEW.source_revision_id
                         AND attempt.fencing_token = NEW.fencing_token
                         AND attempt.source_check_receipt_id = NEW.receipt_id
                         AND attempt.source_check_receipt_sha256 = NEW.content_sha256
                         AND NEW.payload_json ->> 'receiptId' = NEW.receipt_id
                         AND NEW.payload_json -> 'identity' ->> 'attemptId' = NEW.attempt_id
                         AND NEW.payload_json -> 'identity' ->> 'jobId' = NEW.job_id
                         AND NEW.payload_json -> 'identity' ->> 'sourceId' = NEW.official_source_id
                         AND NEW.payload_json -> 'identity' ->> 'sourceRevisionId' = NEW.source_revision_id
                         AND NEW.payload_json -> 'identity' ->> 'certificationDecisionId' IS NOT DISTINCT FROM NEW.source_revision_decision_id
                         AND NEW.payload_json -> 'identity' ->> 'certificationDecisionDigestSha256' IS NOT DISTINCT FROM NEW.source_revision_decision_sha256
                         AND NEW.payload_json -> 'identity' ->> 'contractId' = NEW.contract_id
                         AND NEW.payload_json -> 'identity' ->> 'contractRevisionId' = NEW.contract_revision_id
                         AND NEW.payload_json -> 'identity' ->> 'contractDigestSha256' = NEW.contract_digest_sha256
                         AND NEW.payload_json -> 'identity' ->> 'contractDefinitionSha256' = NEW.contract_definition_sha256
                         AND NEW.payload_json -> 'identity' ->> 'schedulePolicyRevisionId' = NEW.schedule_policy_revision_id
                         AND (NEW.payload_json -> 'identity' ->> 'scheduledSlot')::timestamptz = NEW.scheduled_for
                         AND (NEW.payload_json -> 'identity' ->> 'fencingToken')::integer = NEW.fencing_token
                         AND NEW.payload_json -> 'snapshot' ->> 'snapshotId' IS NOT DISTINCT FROM NEW.snapshot_id
                         AND NEW.payload_json -> 'snapshot' ->> 'snapshotContentSha256' IS NOT DISTINCT FROM NEW.snapshot_content_sha256
                         AND NEW.payload_json -> 'snapshot' ->> 'storageReceiptSha256' IS NOT DISTINCT FROM NEW.snapshot_storage_receipt_sha256
                         AND NEW.payload_json -> 'conditionalMetadata' ->> 'previousSnapshotId' IS NOT DISTINCT FROM NEW.previous_snapshot_id
                         AND NEW.payload_json -> 'conditionalMetadata' ->> 'previousSnapshotContentSha256' IS NOT DISTINCT FROM NEW.previous_snapshot_content_sha256
                         AND NEW.payload_json -> 'conditionalMetadata' ->> 'previousSnapshotVerificationReceiptSha256' IS NOT DISTINCT FROM NEW.previous_snapshot_verification_receipt_sha256
                         AND NEW.payload_json -> 'extraction' ->> 'batchReceiptSha256' IS NOT DISTINCT FROM NEW.batch_receipt_sha256
                         AND NEW.payload_json ->> 'terminalDisposition' = NEW.terminal_disposition
                         AND (NEW.payload_json -> 'execution' ->> 'startedAt')::timestamptz = NEW.started_at
                         AND (NEW.payload_json -> 'execution' ->> 'finishedAt')::timestamptz = NEW.finished_at
                         AND NEW.payload_json -> 'manifest' ->> 'contentSha256' = NEW.content_sha256
                         AND NEW.payload_json -> 'certificationCheck' ->> 'outcome' = NEW.certification_check_outcome
                         AND NEW.payload_json -> 'certificationCheck' ->> 'checkedDecisionId' IS NOT DISTINCT FROM NEW.checked_source_revision_decision_id
                         AND NEW.payload_json -> 'certificationCheck' ->> 'checkedDecisionDigestSha256' IS NOT DISTINCT FROM NEW.checked_source_revision_decision_sha256
                         AND NEW.payload_json -> 'certificationCheck' ->> 'checkedSourceRevisionId' = NEW.source_revision_id
                         AND NEW.payload_json -> 'certificationCheck' ->> 'checkedContractDigestSha256' = NEW.contract_digest_sha256
                         AND NEW.payload_json -> 'certificationCheck' ->> 'checkedContractDefinitionSha256' = NEW.contract_definition_sha256
                   )
                   OR (
                       NEW.source_revision_decision_id IS NOT NULL
                       AND NOT EXISTS (
                           SELECT 1 FROM source_revision_decisions decision
                           WHERE decision.id = NEW.source_revision_decision_id
                             AND decision.source_revision_id = NEW.source_revision_id
                       )
                   )
                   OR (
                       NEW.checked_source_revision_decision_id IS NULL
                       AND NEW.certification_check_outcome <> 'missing'
                   )
                   OR (
                       NEW.checked_source_revision_decision_id IS NOT NULL
                       AND NOT EXISTS (
                           SELECT 1 FROM source_revision_decisions decision
                           WHERE decision.id = NEW.checked_source_revision_decision_id
                             AND decision.source_revision_id = NEW.source_revision_id
                             AND decision.decided_at <= NEW.started_at
                             AND decision.basis_json -> 'sourceContractDecisionEvidence' ->> 'decisionDigestSha256' = NEW.checked_source_revision_decision_sha256
                             AND decision.basis_json -> 'sourceContractDecisionEvidence' ->> 'contractDefinitionSha256' = NEW.contract_definition_sha256
                             AND (
                                 NEW.certification_check_outcome = 'mismatch'
                                 OR decision.outcome = CASE
                                     WHEN NEW.certification_check_outcome = 'expired' THEN 'certified'
                                     ELSE NEW.certification_check_outcome
                                 END
                             )
                             AND NOT EXISTS (
                                 SELECT 1 FROM source_revision_decisions successor
                                 WHERE successor.supersedes_decision_id = decision.id
                                   AND successor.decided_at <= NEW.started_at
                             )
                       )
                   )
                   OR (
                       NEW.snapshot_id IS NOT NULL
                       AND NOT EXISTS (
                           SELECT 1 FROM source_snapshots snapshot
                           WHERE snapshot.id = NEW.snapshot_id
                             AND snapshot.source_revision_id = NEW.source_revision_id
                             AND snapshot.official_source_id = NEW.official_source_id
                             AND snapshot.content_hash = NEW.snapshot_content_sha256
                             AND snapshot.fetch_metadata ->> 'storageReceiptSha256' IS NOT DISTINCT FROM NEW.snapshot_storage_receipt_sha256
                       )
                   )
                   OR (
                       NEW.previous_snapshot_id IS NOT NULL
                       AND NOT EXISTS (
                           SELECT 1 FROM source_snapshots snapshot
                           WHERE snapshot.id = NEW.previous_snapshot_id
                             AND snapshot.source_revision_id = NEW.source_revision_id
                             AND snapshot.official_source_id = NEW.official_source_id
                             AND snapshot.content_hash = NEW.previous_snapshot_content_sha256
                             AND snapshot.fetch_metadata ->> 'storageVerificationReceiptSha256' = NEW.previous_snapshot_verification_receipt_sha256
                       )
                   )
                   OR (NEW.checked_source_revision_decision_id IS NULL)
                      <> (NEW.checked_source_revision_decision_sha256 IS NULL)
                   OR (NEW.snapshot_id IS NULL) <> (NEW.snapshot_content_sha256 IS NULL)
                   OR (NEW.snapshot_id IS NULL) <> (NEW.snapshot_storage_receipt_sha256 IS NULL)
                   OR (NEW.previous_snapshot_id IS NULL) <> (NEW.previous_snapshot_content_sha256 IS NULL)
                   OR (NEW.previous_snapshot_id IS NULL) <> (NEW.previous_snapshot_verification_receipt_sha256 IS NULL)
                THEN
                    RAISE EXCEPTION 'source check requires exact attempt/revision/decision/snapshot bindings'
                        USING ERRCODE = '23514';
                END IF;
            ELSIF TG_TABLE_NAME = 'extraction_batches' THEN
                IF NOT EXISTS (
                    SELECT 1 FROM source_check_receipts receipt
                    WHERE receipt.receipt_id = NEW.source_check_receipt_id
                      AND receipt.attempt_id = NEW.attempt_id
                      AND receipt.job_id = NEW.job_id
                      AND receipt.source_revision_id = NEW.source_revision_id
                      AND receipt.source_revision_decision_id IS NOT DISTINCT FROM NEW.source_revision_decision_id
                      AND receipt.snapshot_id IS NOT DISTINCT FROM NEW.snapshot_id
                      AND receipt.batch_receipt_sha256 = NEW.batch_receipt_sha256
                      AND NEW.payload_json ->> 'batchReceiptSha256' = NEW.batch_receipt_sha256
                      AND NEW.payload_json ->> 'schemaFingerprintSha256' = NEW.schema_fingerprint_sha256
                      AND (NEW.payload_json ->> 'sourceRecordsObserved')::integer = NEW.source_records_observed
                      AND (NEW.payload_json ->> 'rowsParsed')::integer = NEW.rows_parsed
                      AND (NEW.payload_json ->> 'claimCandidatesEmitted')::integer = NEW.claim_candidates_emitted
                      AND (NEW.payload_json ->> 'claimsAdmitted')::integer = NEW.claims_admitted
                      AND (NEW.payload_json ->> 'recordsExcluded')::integer = NEW.records_excluded
                      AND (NEW.payload_json ->> 'recordsRejected')::integer = NEW.records_rejected
                      AND (NEW.payload_json ->> 'recordsQuarantined')::integer = NEW.records_quarantined
                ) THEN
                    RAISE EXCEPTION 'extraction batch must exactly project its source-check receipt'
                        USING ERRCODE = '23514';
                END IF;
            ELSIF TG_TABLE_NAME = 'notification_outbox_items' THEN
                IF NOT EXISTS (
                    SELECT 1 FROM ops_incident_events event
                    WHERE event.event_id = NEW.incident_event_id
                      AND event.outbox_batch_id = NEW.outbox_batch_id
                      AND event.outbox_intent_count > NEW.intent_ordinal
                      AND (
                          SELECT COUNT(*) FROM notification_outbox_items existing
                          WHERE existing.incident_event_id = NEW.incident_event_id
                      ) < event.outbox_intent_count
                ) THEN
                    RAISE EXCEPTION 'outbox item exceeds or changes the immutable event denominator'
                        USING ERRCODE = '23514';
                END IF;
            ELSIF TG_TABLE_NAME = 'notification_intents' THEN
                IF NOT EXISTS (
                    SELECT 1
                    FROM ops_incident_events event
                    JOIN notification_outbox_items item
                      ON item.incident_event_id = event.event_id
                     AND item.intent_id = NEW.intent_id
                    WHERE event.event_id = NEW.incident_event_id
                      AND event.incident_id = NEW.incident_id
                      AND event.outbox_batch_id = NEW.outbox_batch_id
                      AND item.outbox_batch_id = NEW.outbox_batch_id
                      AND NEW.payload_json ->> 'intentId' = NEW.intent_id
                      AND NEW.payload_json ->> 'dedupeKeySha256' = NEW.dedupe_key_sha256
                      AND NEW.payload_json ->> 'incidentId' = NEW.incident_id
                      AND NEW.payload_json ->> 'incidentEventId' = NEW.incident_event_id
                      AND NEW.payload_json ->> 'notificationKind' = NEW.notification_kind
                      AND NEW.payload_json -> 'route' ->> 'routeId' = NEW.route_id
                      AND NEW.payload_json ->> 'dispatchEligibility' = NEW.dispatch_eligibility
                      AND NEW.payload_json -> 'manifest' ->> 'contentSha256' = NEW.content_sha256
                ) THEN
                    RAISE EXCEPTION 'notification intent must bind its exact incident event outbox batch'
                        USING ERRCODE = '23514';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $function$
        """
    )
    for trigger_name, table in (
        ("trg_scheduled_job_intents_reference_insert", "scheduled_job_intents"),
        ("trg_job_attempts_reference_insert", "scheduled_job_attempts"),
        ("trg_source_contracts_reference_insert", "source_contract_envelopes"),
        ("trg_source_checks_reference_insert", "source_check_receipts"),
        ("trg_extraction_batches_reference_insert", "extraction_batches"),
        ("trg_outbox_items_reference_insert", "notification_outbox_items"),
        ("trg_notification_intents_reference_insert", "notification_intents"),
    ):
        op.execute(
            f"""
            CREATE TRIGGER {trigger_name}
            BEFORE INSERT ON {table}
            FOR EACH ROW EXECUTE FUNCTION ledger_validate_operational_reference()
            """
        )

    op.execute(
        """
        CREATE FUNCTION ledger_validate_operational_completion()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, public
        AS $function$
        BEGIN
            IF TG_TABLE_NAME = 'scheduled_cycle_intent_completions' THEN
                IF NOT EXISTS (
                    SELECT 1 FROM scheduled_cycle_intents cycle
                    WHERE cycle.cycle_id = NEW.cycle_id
                      AND cycle.intent_sha256 = NEW.intent_sha256
                      AND cycle.job_count = NEW.job_count
                      AND cycle.payload_json ->> 'recordType' = 'scheduled-cycle-intent-v1'
                      AND cycle.payload_json ->> 'cycleId' = cycle.cycle_id
                      AND cycle.payload_json ->> 'environment' = cycle.environment
                      AND cycle.payload_json ->> 'lane' = cycle.lane
                      AND (cycle.payload_json ->> 'scheduledFor')::timestamptz = cycle.scheduled_for
                      AND cycle.payload_json ->> 'schedulePolicyRevisionId' = cycle.schedule_policy_revision_id
                      AND cycle.payload_json ->> 'mode' = cycle.mode
                      AND jsonb_array_length(cycle.payload_json -> 'jobs') = cycle.job_count
                      AND (
                          SELECT COUNT(*) FROM scheduled_job_intents job
                          WHERE job.cycle_id = cycle.cycle_id
                      ) = cycle.job_count
                      AND NOT EXISTS (
                          SELECT 1 FROM scheduled_job_intents job
                          WHERE job.cycle_id = cycle.cycle_id
                            AND (
                                job.environment <> cycle.environment
                                OR job.lane <> cycle.lane
                                OR job.scheduled_for <> cycle.scheduled_for
                                OR job.schedule_policy_revision_id <> cycle.schedule_policy_revision_id
                                OR job.payload_json ->> 'jobId' IS DISTINCT FROM job.job_id
                                OR job.payload_json ->> 'idempotencyKeySha256' IS DISTINCT FROM job.idempotency_key_sha256
                                OR job.payload_json ->> 'targetType' IS DISTINCT FROM job.target_type
                                OR job.payload_json ->> 'targetRevisionId' IS DISTINCT FROM job.target_revision_id
                                OR job.payload_json ->> 'sourceRevisionId' IS DISTINCT FROM job.source_revision_id
                                OR job.payload_json ->> 'dueDisposition' IS DISTINCT FROM job.due_disposition
                                OR job.payload_json ->> 'dispositionReasonCode' IS DISTINCT FROM job.disposition_reason_code
                                OR NOT EXISTS (
                                    SELECT 1 FROM jsonb_array_elements(cycle.payload_json -> 'jobs') item
                                    WHERE item ->> 'jobId' = job.job_id
                                      AND item ->> 'idempotencyKeySha256' = job.idempotency_key_sha256
                                      AND item ->> 'targetType' = job.target_type
                                      AND item ->> 'targetRevisionId' = job.target_revision_id
                                      AND item ->> 'sourceRevisionId' IS NOT DISTINCT FROM job.source_revision_id
                                      AND item ->> 'dueDisposition' = job.due_disposition
                                      AND item ->> 'dispositionReasonCode' = job.disposition_reason_code
                                )
                            )
                      )
                ) THEN
                    RAISE EXCEPTION 'cycle intent completion requires the exact immutable job denominator'
                        USING ERRCODE = '23514';
                END IF;
            ELSIF TG_TABLE_NAME = 'scheduled_cycles' THEN
                IF NOT EXISTS (
                    SELECT 1 FROM scheduled_cycle_intents cycle
                    JOIN scheduled_cycle_intent_completions completion
                      ON completion.cycle_id = cycle.cycle_id
                     AND completion.intent_sha256 = cycle.intent_sha256
                     AND completion.job_count = cycle.job_count
                    WHERE cycle.cycle_id = NEW.cycle_id
                      AND cycle.environment = NEW.environment
                      AND cycle.lane = NEW.lane
                      AND cycle.scheduled_for = NEW.scheduled_for
                      AND cycle.schedule_policy_revision_id = NEW.schedule_policy_revision_id
                      AND cycle.mode = NEW.mode
                      AND NEW.payload_json ->> 'cycleId' = NEW.cycle_id
                      AND NEW.payload_json ->> 'environment' = NEW.environment
                      AND NEW.payload_json ->> 'lane' = NEW.lane
                      AND (NEW.payload_json -> 'slot' ->> 'scheduledFor')::timestamptz = NEW.scheduled_for
                      AND NEW.payload_json ->> 'schedulePolicyRevisionId' = NEW.schedule_policy_revision_id
                      AND NEW.payload_json ->> 'mode' = NEW.mode
                      AND NEW.payload_json ->> 'state' = 'terminal'
                      AND NEW.payload_json -> 'manifest' ->> 'contentSha256' = NEW.content_sha256
                      AND jsonb_array_length(NEW.payload_json -> 'jobs') = cycle.job_count
                      AND NOT EXISTS (
                          SELECT 1 FROM scheduled_job_intents job
                          WHERE job.cycle_id = cycle.cycle_id
                            AND NOT EXISTS (
                                SELECT 1 FROM jsonb_array_elements(NEW.payload_json -> 'jobs') item
                                WHERE item ->> 'jobId' = job.job_id
                                  AND item ->> 'idempotencyKeySha256' = job.idempotency_key_sha256
                                  AND item ->> 'targetType' = job.target_type
                                  AND item ->> 'targetRevisionId' = job.target_revision_id
                                  AND item ->> 'sourceRevisionId' IS NOT DISTINCT FROM job.source_revision_id
                                  AND item ->> 'dueDisposition' = job.due_disposition
                                  AND item ->> 'dispositionReasonCode' = job.disposition_reason_code
                                  AND (item ->> 'attemptCount')::integer = (
                                      SELECT COUNT(*) FROM scheduled_job_attempts attempt
                                      WHERE attempt.job_id = job.job_id
                                        AND attempt.cycle_id = cycle.cycle_id
                                  )
                                  AND NOT EXISTS (
                                      SELECT 1 FROM jsonb_array_elements_text(item -> 'attemptReceiptIds') AS listed(value)
                                      WHERE NOT EXISTS (
                                          SELECT 1 FROM scheduled_job_attempts attempt
                                          WHERE attempt.attempt_id = listed.value
                                            AND attempt.job_id = job.job_id
                                            AND attempt.cycle_id = cycle.cycle_id
                                      )
                                  )
                                  AND NOT EXISTS (
                                      SELECT 1 FROM scheduled_job_attempts attempt
                                      WHERE attempt.job_id = job.job_id
                                        AND attempt.cycle_id = cycle.cycle_id
                                        AND NOT EXISTS (
                                            SELECT 1 FROM jsonb_array_elements_text(item -> 'attemptReceiptIds') AS listed(value)
                                            WHERE listed.value = attempt.attempt_id
                                        )
                                  )
                                  AND item -> 'terminalOutputReference' ->> 'referenceType' = 'source_check_receipt'
                                  AND EXISTS (
                                      SELECT 1
                                      FROM scheduled_job_attempts final_attempt
                                      JOIN source_check_receipts receipt
                                        ON receipt.attempt_id = final_attempt.attempt_id
                                       AND receipt.job_id = final_attempt.job_id
                                       AND receipt.receipt_id = final_attempt.source_check_receipt_id
                                       AND receipt.content_sha256 = final_attempt.source_check_receipt_sha256
                                      JOIN scheduled_job_leases lease
                                        ON lease.job_id = final_attempt.job_id
                                       AND lease.current_lease_id = final_attempt.lease_id
                                       AND lease.fencing_token = final_attempt.fencing_token
                                       AND lease.last_heartbeat_at = final_attempt.lease_last_heartbeat_at
                                       AND lease.state = final_attempt.payload_json -> 'lease' ->> 'state'
                                      WHERE final_attempt.job_id = job.job_id
                                        AND final_attempt.cycle_id = cycle.cycle_id
                                        AND final_attempt.attempt_number = (item ->> 'attemptCount')::integer
                                        AND receipt.receipt_id = item -> 'terminalOutputReference' ->> 'referenceId'
                                        AND receipt.content_sha256 = item -> 'terminalOutputReference' ->> 'contentSha256'
                                        AND receipt.terminal_disposition = item ->> 'terminalDisposition'
                                  )
                            )
                      )
                ) THEN
                    RAISE EXCEPTION 'terminal cycle requires exact intent, attempts, and immutable output evidence'
                        USING ERRCODE = '23514';
                END IF;
            ELSIF TG_TABLE_NAME = 'notification_outbox_batches' THEN
                IF NOT EXISTS (
                    SELECT 1 FROM ops_incident_events event
                    WHERE event.event_id = NEW.incident_event_id
                      AND event.outbox_batch_id = NEW.outbox_batch_id
                      AND event.outbox_intent_count = NEW.intent_count
                      AND (
                          SELECT COUNT(*) FROM notification_outbox_items item
                          WHERE item.incident_event_id = NEW.incident_event_id
                            AND item.outbox_batch_id = NEW.outbox_batch_id
                      ) = NEW.intent_count
                      AND (
                          SELECT COUNT(*) FROM notification_intents intent
                          WHERE intent.incident_event_id = NEW.incident_event_id
                            AND intent.outbox_batch_id = NEW.outbox_batch_id
                      ) = NEW.intent_count
                ) THEN
                    RAISE EXCEPTION 'outbox completion requires the exact item and intent denominator'
                        USING ERRCODE = '23514';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $function$
        """
    )
    for trigger_name, table in (
        ("trg_cycle_intent_completion_insert", "scheduled_cycle_intent_completions"),
        ("trg_scheduled_cycles_terminal_insert", "scheduled_cycles"),
        ("trg_outbox_batches_completion_insert", "notification_outbox_batches"),
    ):
        op.execute(
            f"""
            CREATE TRIGGER {trigger_name}
            BEFORE INSERT ON {table}
            FOR EACH ROW EXECUTE FUNCTION ledger_validate_operational_completion()
            """
        )

    for function_name in (
        "ledger_validate_job_lease_projection",
        "ledger_validate_operational_chain",
        "ledger_validate_operational_completion",
        "ledger_validate_operational_reference",
    ):
        op.execute(f"REVOKE ALL ON FUNCTION {function_name}() FROM PUBLIC")


def upgrade() -> None:
    _create_tables()
    if is_postgresql():
        _create_postgresql_deferred_pairs()
    _create_indexes()
    if is_sqlite():
        _create_sqlite_guards()
        return
    if is_postgresql():
        _create_postgresql_guards()
        return
    raise RuntimeError("Ledger migrations support only SQLite and PostgreSQL.")


def downgrade() -> None:
    raise RuntimeError(
        "Ledger migrations are recovery-only: restore the verified pre-migration backup instead of downgrading."
    )
