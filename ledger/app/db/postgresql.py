"""Provider-neutral PostgreSQL migration and least-privilege contracts.

This module does not provision roles or open a connection on import. Operators
must execute the rendered role SQL with a reviewed administrative identity,
then grant the NOLOGIN group roles to separately managed login identities.
"""

from __future__ import annotations

import re

from sqlalchemy.engine import make_url


POSTGRESQL_MIGRATION_LOCK_KEY = 6_566_933_159_028_912_801
POSTGRESQL_SCHEMA = "public"

POSTGRESQL_REQUIRED_TABLES = frozenset(
    {
        "aliases",
        "benchmarks",
        "claim_publication_decisions",
        "claim_relationships",
        "claim_review_decisions",
        "claim_validations",
        "ingestion_runs",
        "model_entities",
        "official_source_revisions",
        "official_sources",
        "result_claims",
        "source_revision_decisions",
        "source_snapshots",
    }
)

# DATA-09 operational relations are part of the exact PostgreSQL head, but
# remain outside the official-claim/publication authority boundary.
POSTGRESQL_OPERATIONAL_TABLES = frozenset(
    {
        "benchmark_definition_revisions",
        "discovery_candidates",
        "evaluation_subject_revisions",
        "extraction_batches",
        "identity_decisions",
        "notification_intents",
        "notification_outbox_batches",
        "notification_outbox_items",
        "notification_receipts",
        "ops_incident_events",
        "ops_incidents",
        "review_work_item_events",
        "review_work_items",
        "scheduled_cycle_intent_completions",
        "scheduled_cycle_intents",
        "scheduled_cycles",
        "scheduled_job_attempts",
        "scheduled_job_intents",
        "scheduled_job_lease_events",
        "scheduled_job_leases",
        "source_check_receipts",
        "source_contract_envelopes",
    }
)
POSTGRESQL_REQUIRED_TABLES = frozenset(
    POSTGRESQL_REQUIRED_TABLES | POSTGRESQL_OPERATIONAL_TABLES
)

POSTGRESQL_REQUIRED_CONSTRAINTS = {
    "alembic_version_pkc": "PRIMARY KEY (version_num)",
    "aliases_pkey": "PRIMARY KEY (id)",
    "benchmarks_pkey": "PRIMARY KEY (id)",
    "benchmarks_superseded_by_benchmark_id_fkey": (
        "FOREIGN KEY (superseded_by_benchmark_id) REFERENCES benchmarks(id)"
    ),
    "claim_publication_decisions_claim_review_decision_id_fkey": (
        "FOREIGN KEY (claim_review_decision_id) REFERENCES claim_review_decisions(id)"
    ),
    "claim_publication_decisions_pkey": "PRIMARY KEY (id)",
    "claim_publication_decisions_result_claim_id_fkey": (
        "FOREIGN KEY (result_claim_id) REFERENCES result_claims(id)"
    ),
    "claim_publication_decisions_supersedes_decision_id_fkey": (
        "FOREIGN KEY (supersedes_decision_id) REFERENCES claim_publication_decisions(id)"
    ),
    "claim_relationships_claim_id_fkey": "FOREIGN KEY (claim_id) REFERENCES result_claims(id)",
    "claim_relationships_pkey": "PRIMARY KEY (id)",
    "claim_relationships_related_claim_id_fkey": (
        "FOREIGN KEY (related_claim_id) REFERENCES result_claims(id)"
    ),
    "claim_review_decisions_benchmark_id_fkey": (
        "FOREIGN KEY (benchmark_id) REFERENCES benchmarks(id)"
    ),
    "claim_review_decisions_model_entity_id_fkey": (
        "FOREIGN KEY (model_entity_id) REFERENCES model_entities(id)"
    ),
    "claim_review_decisions_pkey": "PRIMARY KEY (id)",
    "claim_review_decisions_result_claim_id_fkey": (
        "FOREIGN KEY (result_claim_id) REFERENCES result_claims(id)"
    ),
    "claim_review_decisions_supersedes_decision_id_fkey": (
        "FOREIGN KEY (supersedes_decision_id) REFERENCES claim_review_decisions(id)"
    ),
    "claim_validations_pkey": "PRIMARY KEY (id)",
    "claim_validations_result_claim_id_fkey": (
        "FOREIGN KEY (result_claim_id) REFERENCES result_claims(id)"
    ),
    "fk_result_claims_source_revision_decision": (
        "FOREIGN KEY (source_revision_decision_id) REFERENCES source_revision_decisions(id)"
    ),
    "fk_source_snapshots_source_revision": (
        "FOREIGN KEY (source_revision_id) REFERENCES official_source_revisions(id)"
    ),
    "ingestion_runs_official_source_id_fkey": (
        "FOREIGN KEY (official_source_id) REFERENCES official_sources(id)"
    ),
    "ingestion_runs_pkey": "PRIMARY KEY (id)",
    "model_entities_base_model_entity_id_fkey": (
        "FOREIGN KEY (base_model_entity_id) REFERENCES model_entities(id)"
    ),
    "model_entities_pkey": "PRIMARY KEY (id)",
    "official_source_revisions_official_source_id_fkey": (
        "FOREIGN KEY (official_source_id) REFERENCES official_sources(id)"
    ),
    "official_source_revisions_pkey": "PRIMARY KEY (id)",
    "official_source_revisions_supersedes_revision_id_fkey": (
        "FOREIGN KEY (supersedes_revision_id) REFERENCES official_source_revisions(id)"
    ),
    "official_sources_benchmark_id_fkey": "FOREIGN KEY (benchmark_id) REFERENCES benchmarks(id)",
    "official_sources_pkey": "PRIMARY KEY (id)",
    "result_claims_benchmark_id_fkey": "FOREIGN KEY (benchmark_id) REFERENCES benchmarks(id)",
    "result_claims_model_entity_id_fkey": (
        "FOREIGN KEY (model_entity_id) REFERENCES model_entities(id)"
    ),
    "result_claims_official_source_id_fkey": (
        "FOREIGN KEY (official_source_id) REFERENCES official_sources(id)"
    ),
    "result_claims_pkey": "PRIMARY KEY (id)",
    "result_claims_source_snapshot_id_fkey": (
        "FOREIGN KEY (source_snapshot_id) REFERENCES source_snapshots(id)"
    ),
    "source_revision_decisions_pkey": "PRIMARY KEY (id)",
    "source_revision_decisions_source_revision_id_fkey": (
        "FOREIGN KEY (source_revision_id) REFERENCES official_source_revisions(id)"
    ),
    "source_revision_decisions_supersedes_decision_id_fkey": (
        "FOREIGN KEY (supersedes_decision_id) REFERENCES source_revision_decisions(id)"
    ),
    "source_snapshots_official_source_id_fkey": (
        "FOREIGN KEY (official_source_id) REFERENCES official_sources(id)"
    ),
    "source_snapshots_pkey": "PRIMARY KEY (id)",
    "uq_alias": "UNIQUE (entity_type, entity_id, alias_text)",
    "uq_claim_fp": "UNIQUE (source_snapshot_id, claim_fingerprint)",
    "uq_claim_rel": "UNIQUE (claim_id, related_claim_id, relationship_type)",
    "uq_source_revision_hash": "UNIQUE (source_revision_id, content_hash)",
    "uq_source_revision_ordinal": "UNIQUE (official_source_id, revision_ordinal)",
    "uq_source_url": "UNIQUE (benchmark_id, source_url)",
}

# Constraint names are only schema-unique by convention; PostgreSQL permits
# the same name on different tables. Strict status therefore binds every
# reviewed definition to its owning table rather than collapsing rows by name.
POSTGRESQL_REQUIRED_CONSTRAINT_TABLES = {
    "alembic_version_pkc": "alembic_version",
    "aliases_pkey": "aliases",
    "benchmarks_pkey": "benchmarks",
    "benchmarks_superseded_by_benchmark_id_fkey": "benchmarks",
    "claim_publication_decisions_claim_review_decision_id_fkey": "claim_publication_decisions",
    "claim_publication_decisions_pkey": "claim_publication_decisions",
    "claim_publication_decisions_result_claim_id_fkey": "claim_publication_decisions",
    "claim_publication_decisions_supersedes_decision_id_fkey": "claim_publication_decisions",
    "claim_relationships_claim_id_fkey": "claim_relationships",
    "claim_relationships_pkey": "claim_relationships",
    "claim_relationships_related_claim_id_fkey": "claim_relationships",
    "claim_review_decisions_benchmark_id_fkey": "claim_review_decisions",
    "claim_review_decisions_model_entity_id_fkey": "claim_review_decisions",
    "claim_review_decisions_pkey": "claim_review_decisions",
    "claim_review_decisions_result_claim_id_fkey": "claim_review_decisions",
    "claim_review_decisions_supersedes_decision_id_fkey": "claim_review_decisions",
    "claim_validations_pkey": "claim_validations",
    "claim_validations_result_claim_id_fkey": "claim_validations",
    "fk_result_claims_source_revision_decision": "result_claims",
    "fk_source_snapshots_source_revision": "source_snapshots",
    "ingestion_runs_official_source_id_fkey": "ingestion_runs",
    "ingestion_runs_pkey": "ingestion_runs",
    "model_entities_base_model_entity_id_fkey": "model_entities",
    "model_entities_pkey": "model_entities",
    "official_source_revisions_official_source_id_fkey": "official_source_revisions",
    "official_source_revisions_pkey": "official_source_revisions",
    "official_source_revisions_supersedes_revision_id_fkey": "official_source_revisions",
    "official_sources_benchmark_id_fkey": "official_sources",
    "official_sources_pkey": "official_sources",
    "result_claims_benchmark_id_fkey": "result_claims",
    "result_claims_model_entity_id_fkey": "result_claims",
    "result_claims_official_source_id_fkey": "result_claims",
    "result_claims_pkey": "result_claims",
    "result_claims_source_snapshot_id_fkey": "result_claims",
    "source_revision_decisions_pkey": "source_revision_decisions",
    "source_revision_decisions_source_revision_id_fkey": "source_revision_decisions",
    "source_revision_decisions_supersedes_decision_id_fkey": "source_revision_decisions",
    "source_snapshots_official_source_id_fkey": "source_snapshots",
    "source_snapshots_pkey": "source_snapshots",
    "uq_alias": "aliases",
    "uq_claim_fp": "result_claims",
    "uq_claim_rel": "claim_relationships",
    "uq_source_revision_hash": "source_snapshots",
    "uq_source_revision_ordinal": "official_source_revisions",
    "uq_source_url": "official_sources",
}

# Compact reviewed fingerprints keep the 0010 native inventory strict without
# duplicating more than one hundred constraint definitions in application code.
# The status inspector canonicalizes every operational constraint name, owner
# table, definition, validation/deferrability posture, type, and backing-index
# state before comparing this digest.
POSTGRESQL_OPERATIONAL_CONSTRAINT_INVENTORY_SHA256 = (
    "7b920df11cb35b6cd141e512c818091ff6485711577027138d0b7ad86f52d1d7"
)
POSTGRESQL_DEFERRABLE_CONSTRAINTS = frozenset(
    {
        "fk_cycle_intent_completion",
        "fk_incident_event_outbox_batch",
        "fk_job_attempt_source_check",
        "fk_outbox_item_intent",
    }
)
POSTGRESQL_INITIALLY_DEFERRED_CONSTRAINTS = POSTGRESQL_DEFERRABLE_CONSTRAINTS

POSTGRESQL_REQUIRED_INDEXES = {
    "ix_benchmarks_superseded_by": (
        "benchmarks", ("superseded_by_benchmark_id",), False, None
    ),
    "ix_claim_publications_claim_decided": (
        "claim_publication_decisions", ("result_claim_id", "decided_at", "id"), False, None
    ),
    "ix_claim_publications_review": (
        "claim_publication_decisions", ("claim_review_decision_id",), False, None
    ),
    "ix_claim_relationships_related": (
        "claim_relationships", ("related_claim_id",), False, None
    ),
    "ix_claim_reviews_benchmark": (
        "claim_review_decisions", ("benchmark_id",), False, None
    ),
    "ix_claim_reviews_claim_decided": (
        "claim_review_decisions", ("result_claim_id", "decided_at", "id"), False, None
    ),
    "ix_claim_reviews_model": (
        "claim_review_decisions", ("model_entity_id",), False, None
    ),
    "ix_claim_validations_claim_type_outcome": (
        "claim_validations", ("result_claim_id", "validation_type", "outcome"), False, None
    ),
    "ix_ingestion_runs_source_started": (
        "ingestion_runs", ("official_source_id", "started_at"), False, None
    ),
    "ix_model_entities_base": ("model_entities", ("base_model_entity_id",), False, None),
    "ix_result_claims_benchmark": ("result_claims", ("benchmark_id",), False, None),
    "ix_result_claims_model_entity": ("result_claims", ("model_entity_id",), False, None),
    "ix_result_claims_official_source": (
        "result_claims", ("official_source_id",), False, None
    ),
    "ix_result_claims_source_decision": (
        "result_claims", ("source_revision_decision_id",), False, None
    ),
    "ix_source_decisions_revision_decided": (
        "source_revision_decisions", ("source_revision_id", "decided_at", "id"), False, None
    ),
    "ix_source_revisions_supersedes": (
        "official_source_revisions", ("supersedes_revision_id",), False, None
    ),
    "ix_source_snapshots_official_source": (
        "source_snapshots", ("official_source_id",), False, None
    ),
    "uq_claim_publication_root": (
        "claim_publication_decisions",
        ("result_claim_id",),
        True,
        "(supersedes_decision_id IS NULL)",
    ),
    "uq_claim_publication_successor": (
        "claim_publication_decisions",
        ("supersedes_decision_id",),
        True,
        "(supersedes_decision_id IS NOT NULL)",
    ),
    "uq_claim_review_root": (
        "claim_review_decisions",
        ("result_claim_id",),
        True,
        "(supersedes_decision_id IS NULL)",
    ),
    "uq_claim_review_successor": (
        "claim_review_decisions",
        ("supersedes_decision_id",),
        True,
        "(supersedes_decision_id IS NOT NULL)",
    ),
    "uq_source_decision_root": (
        "source_revision_decisions",
        ("source_revision_id",),
        True,
        "(supersedes_decision_id IS NULL)",
    ),
    "uq_source_decision_successor": (
        "source_revision_decisions",
        ("supersedes_decision_id",),
        True,
        "(supersedes_decision_id IS NOT NULL)",
    ),
}

# Canonical digest of every non-constraint-backed operational index, including
# exact columns, partial predicate, uniqueness, validity/readiness/liveness,
# access method, and executable pg_get_indexdef text.
POSTGRESQL_OPERATIONAL_INDEX_INVENTORY_SHA256 = (
    "d86f87975aa6a63b211709331b9f58544d03b123aa05383bfe6039cdeeb32be7"
)

POSTGRESQL_REQUIRED_TRIGGER_BINDINGS = {
    "trg_benchmarks_id_no_update": (
        "benchmarks",
        "ledger_reject_append_only_mutation",
        19,
        ("id",),
    ),
    "trg_claim_publication_decisions_chain_insert": (
        "claim_publication_decisions",
        "ledger_validate_claim_publication_chain",
        7,
        (),
    ),
    "trg_claim_publication_decisions_no_mutation": (
        "claim_publication_decisions",
        "ledger_reject_append_only_mutation",
        27,
        (),
    ),
    "trg_claim_relationships_no_mutation": (
        "claim_relationships",
        "ledger_reject_append_only_mutation",
        27,
        (),
    ),
    "trg_claim_review_decisions_chain_insert": (
        "claim_review_decisions",
        "ledger_validate_claim_review_chain",
        7,
        (),
    ),
    "trg_claim_review_decisions_no_mutation": (
        "claim_review_decisions",
        "ledger_reject_append_only_mutation",
        27,
        (),
    ),
    "trg_claim_validations_no_mutation": (
        "claim_validations",
        "ledger_reject_append_only_mutation",
        27,
        (),
    ),
    "trg_ingestion_runs_no_delete": (
        "ingestion_runs",
        "ledger_reject_ingestion_run_delete",
        11,
        (),
    ),
    "trg_ingestion_runs_finalize_once": (
        "ingestion_runs",
        "ledger_validate_ingestion_run_finalization",
        19,
        (),
    ),
    "trg_model_entities_id_no_update": (
        "model_entities",
        "ledger_reject_append_only_mutation",
        19,
        ("id",),
    ),
    "trg_official_source_revisions_definition_insert": (
        "official_source_revisions",
        "ledger_validate_source_revision_definition",
        7,
        (),
    ),
    "trg_official_source_revisions_no_mutation": (
        "official_source_revisions",
        "ledger_reject_append_only_mutation",
        27,
        (),
    ),
    "trg_official_sources_current_revision": (
        "official_sources",
        "ledger_validate_source_links",
        23,
        ("current_revision_id",),
    ),
    "trg_official_sources_projection_no_update": (
        "official_sources",
        "ledger_validate_source_projection_update",
        19,
        (),
    ),
    "trg_result_claims_admission_decision_insert": (
        "result_claims",
        "ledger_validate_result_claim_admission",
        7,
        (),
    ),
    "trg_result_claims_no_mutation": (
        "result_claims",
        "ledger_validate_result_claim_mutation",
        27,
        (),
    ),
    "trg_source_revision_decisions_chain_insert": (
        "source_revision_decisions",
        "ledger_validate_source_decision_chain",
        7,
        (),
    ),
    "trg_source_revision_decisions_no_mutation": (
        "source_revision_decisions",
        "ledger_reject_append_only_mutation",
        27,
        (),
    ),
    "trg_source_snapshots_no_mutation": (
        "source_snapshots",
        "ledger_reject_append_only_mutation",
        27,
        (),
    ),
    "trg_source_snapshots_revision": (
        "source_snapshots",
        "ledger_validate_source_links",
        23,
        ("official_source_id", "source_revision_id"),
    ),
}

POSTGRESQL_REQUIRED_TRIGGERS = frozenset(POSTGRESQL_REQUIRED_TRIGGER_BINDINGS)

# Canonical digest of all non-internal triggers attached to operational tables:
# name, table, function, event/timing bits, column bindings, enabled state, and
# absence of an unreviewed WHEN predicate.
POSTGRESQL_OPERATIONAL_TRIGGER_INVENTORY_SHA256 = (
    "2aaa300b6d30ce5ed008a8b1cf5965ede09b5d505b9acbdc271d53c2253dbd0b"
)

POSTGRESQL_REQUIRED_FUNCTIONS = frozenset(
    {
        "ledger_reject_append_only_mutation",
        "ledger_reject_ingestion_run_delete",
        "ledger_validate_ingestion_run_finalization",
        "ledger_validate_claim_publication_chain",
        "ledger_validate_claim_review_chain",
        "ledger_validate_job_lease_projection",
        "ledger_validate_operational_chain",
        "ledger_validate_operational_completion",
        "ledger_validate_operational_reference",
        "ledger_validate_result_claim_admission",
        "ledger_validate_result_claim_mutation",
        "ledger_validate_source_decision_chain",
        "ledger_validate_source_links",
        "ledger_validate_source_projection_update",
        "ledger_validate_source_revision_definition",
    }
)

# SHA-256 of PostgreSQL's stored ``pg_proc.prosrc`` for each zero-argument
# trigger function. This binds strict head status to the reviewed executable
# body, not merely a function name that an owner could replace in place.
POSTGRESQL_REQUIRED_FUNCTION_FINGERPRINTS = {
    "ledger_reject_append_only_mutation": "c0d5f48d43b07efa802675795c7ed251c73734cc093ed0e02093a070717cdfec",
    "ledger_reject_ingestion_run_delete": "36a9d67adf5743c47d431bbc948c7d7d2327d0f617fd9b75dab38562c27568a9",
    "ledger_validate_ingestion_run_finalization": "ef8d5772f2190cc090f9abc46df46ea892c5b7b0e87807076469a539062d8934",
    "ledger_validate_claim_publication_chain": "51eb42b6480f03be31821864fab3a0f351f34d5f23d0b1210fbebc633f36be68",
    "ledger_validate_claim_review_chain": "62f6d0c28d7455a03cc00f82667031906ba02f7d042e77ad7b7aada0c424b5e2",
    "ledger_validate_job_lease_projection": "e3a077e4401478934bb5b4ad5b4b2796e1c37d42f786a3b942b31194c037c18c",
    "ledger_validate_operational_chain": "55c35331d8d0c3c07abec63a441726830b61aa9bcf7196a356c58d995172a02b",
    "ledger_validate_operational_completion": "fa8c9c00c1e22a645e2cef51a744fa3c773f73515bea5260392e2723c7c3693f",
    "ledger_validate_operational_reference": "9dfef3ab9e6c14bd1fbe9c1e3ea6511bcd6425c4bd3ea15a3acf604b21e2ae40",
    "ledger_validate_result_claim_admission": "69621773f254e7812611d00b19df6bd059ad33fb4b7387c0e5a586111fae47bd",
    "ledger_validate_result_claim_mutation": "cd9cf415af58ee5202ca7ec798f1b0d6a160b964edcca8e9936f90990a007e18",
    "ledger_validate_source_decision_chain": "6091f5992f07ea94af2b3197f994c91fa7710a438009d9ab2edcdd5b95fe1e90",
    "ledger_validate_source_links": "202eca4aac0203092adf81fd21fd8df91e740d73a28511d49d9d81a7155c74f4",
    "ledger_validate_source_projection_update": "974f98f6dbe5f8390f125e5a137e7d2b7d426ea27d0c18e9c5436219486b84b1",
    "ledger_validate_source_revision_definition": "0a1b95121e6797a687c00a47fdd020f9e56653207afc2186d00a96f3fe8dfe56",
}

POSTGRESQL_JSONB_COLUMNS = frozenset(
    {
        ("benchmarks", "known_metrics"),
        ("benchmarks", "known_splits"),
        ("benchmarks", "known_settings"),
        ("claim_publication_decisions", "basis_json"),
        ("claim_review_decisions", "basis_json"),
        ("ingestion_runs", "metadata"),
        ("model_entities", "modalities"),
        ("official_source_revisions", "definition_json"),
        ("official_source_revisions", "parser_config"),
        ("official_sources", "parser_config"),
        ("result_claims", "evidence_location"),
        ("source_revision_decisions", "basis_json"),
        ("source_snapshots", "fetch_metadata"),
    }
)
POSTGRESQL_JSONB_COLUMNS = frozenset(
    POSTGRESQL_JSONB_COLUMNS
    | {
        ("benchmark_definition_revisions", "payload_json"),
        ("discovery_candidates", "payload_json"),
        ("evaluation_subject_revisions", "payload_json"),
        ("extraction_batches", "payload_json"),
        ("identity_decisions", "payload_json"),
        ("notification_intents", "payload_json"),
        ("notification_receipts", "payload_json"),
        ("ops_incident_events", "contract_payload_json"),
        ("ops_incident_events", "event_payload_json"),
        ("review_work_item_events", "contract_payload_json"),
        ("review_work_item_events", "event_payload_json"),
        ("scheduled_cycle_intents", "payload_json"),
        ("scheduled_cycles", "payload_json"),
        ("scheduled_job_attempts", "payload_json"),
        ("scheduled_job_intents", "payload_json"),
        ("source_check_receipts", "payload_json"),
        ("source_contract_envelopes", "payload_json"),
    }
)

POSTGRESQL_TIMESTAMPTZ_COLUMNS = frozenset(
    {
        ("aliases", "created_at"),
        ("benchmarks", "created_at"),
        ("benchmarks", "updated_at"),
        ("claim_publication_decisions", "decided_at"),
        ("claim_relationships", "created_at"),
        ("claim_review_decisions", "decided_at"),
        ("claim_validations", "validated_at"),
        ("ingestion_runs", "finished_at"),
        ("ingestion_runs", "started_at"),
        ("model_entities", "created_at"),
        ("model_entities", "updated_at"),
        ("official_source_revisions", "created_at"),
        ("official_sources", "created_at"),
        ("official_sources", "updated_at"),
        ("result_claims", "created_at"),
        ("source_revision_decisions", "decided_at"),
        ("source_snapshots", "captured_at"),
        ("source_snapshots", "created_at"),
    }
)
POSTGRESQL_LEGACY_NULLABLE_TIMESTAMP_COLUMNS = POSTGRESQL_TIMESTAMPTZ_COLUMNS
POSTGRESQL_TIMESTAMPTZ_COLUMNS = frozenset(
    POSTGRESQL_TIMESTAMPTZ_COLUMNS
    | {
        ("identity_decisions", "decided_at"),
        ("notification_receipts", "finished_at"),
        ("ops_incident_events", "occurred_at"),
        ("review_work_item_events", "occurred_at"),
        ("scheduled_cycle_intents", "scheduled_for"),
        ("scheduled_cycles", "scheduled_for"),
        ("scheduled_job_attempts", "ended_at"),
        ("scheduled_job_attempts", "lease_acquired_at"),
        ("scheduled_job_attempts", "lease_expires_at"),
        ("scheduled_job_attempts", "lease_last_heartbeat_at"),
        ("scheduled_job_attempts", "started_at"),
        ("scheduled_job_intents", "scheduled_for"),
        ("scheduled_job_lease_events", "acquired_at"),
        ("scheduled_job_lease_events", "expires_at"),
        ("scheduled_job_lease_events", "initial_heartbeat_at"),
        ("scheduled_job_leases", "acquired_at"),
        ("scheduled_job_leases", "expires_at"),
        ("scheduled_job_leases", "last_heartbeat_at"),
        ("source_check_receipts", "finished_at"),
        ("source_check_receipts", "scheduled_for"),
        ("source_check_receipts", "started_at"),
    }
)

# Exact executable defaults at migration head.  Columns omitted from this map
# must have no database default.  Keeping this contract beside the native type
# inventory lets strict preflight reject a forged fixed audit timestamp or a
# newly introduced function-bearing default even when type/nullability still
# look correct.
POSTGRESQL_REQUIRED_COLUMN_DEFAULTS = {
    ("aliases", "confidence"): "'1'::double precision",
    ("aliases", "is_official_alias"): "false",
    ("aliases", "created_at"): "CURRENT_TIMESTAMP",
    ("benchmarks", "has_official_leaderboard"): "false",
    ("benchmarks", "has_official_result_api"): "false",
    ("benchmarks", "has_official_result_files"): "false",
    ("benchmarks", "has_private_test_set"): "false",
    ("benchmarks", "known_metrics"): "'[]'::json",
    ("benchmarks", "known_splits"): "'[]'::json",
    ("benchmarks", "known_settings"): "'[]'::json",
    ("benchmarks", "status"): "'active'::character varying",
    ("benchmarks", "created_at"): "CURRENT_TIMESTAMP",
    ("benchmarks", "updated_at"): "CURRENT_TIMESTAMP",
    ("claim_publication_decisions", "basis_json"): "'{}'::json",
    ("claim_publication_decisions", "decided_at"): "CURRENT_TIMESTAMP",
    ("claim_relationships", "created_at"): "CURRENT_TIMESTAMP",
    ("claim_review_decisions", "basis_json"): "'{}'::json",
    ("claim_review_decisions", "decided_at"): "CURRENT_TIMESTAMP",
    ("claim_validations", "validated_at"): "CURRENT_TIMESTAMP",
    ("ingestion_runs", "started_at"): "CURRENT_TIMESTAMP",
    ("ingestion_runs", "status"): "'running'::character varying",
    ("ingestion_runs", "sources_checked"): "0",
    ("ingestion_runs", "snapshots_created"): "0",
    ("ingestion_runs", "snapshots_reused"): "0",
    ("ingestion_runs", "claims_extracted"): "0",
    ("ingestion_runs", "claims_inserted"): "0",
    ("ingestion_runs", "claims_unchanged"): "0",
    ("ingestion_runs", "claims_needing_review"): "0",
    ("ingestion_runs", "metadata"): "'{}'::json",
    ("model_entities", "status"): "'active'::character varying",
    ("model_entities", "modalities"): "'[]'::json",
    ("model_entities", "created_at"): "CURRENT_TIMESTAMP",
    ("model_entities", "updated_at"): "CURRENT_TIMESTAMP",
    ("official_source_revisions", "machine_readable"): "false",
    ("official_source_revisions", "requires_auth"): "false",
    ("official_source_revisions", "supports_history"): "false",
    ("official_source_revisions", "parser_config"): "'{}'::json",
    ("official_source_revisions", "status"): "'active'::character varying",
    ("official_source_revisions", "created_at"): "CURRENT_TIMESTAMP",
    ("official_sources", "machine_readable"): "false",
    ("official_sources", "requires_auth"): "false",
    ("official_sources", "supports_history"): "false",
    ("official_sources", "parser_config"): "'{}'::json",
    ("official_sources", "status"): "'active'::character varying",
    ("official_sources", "created_at"): "CURRENT_TIMESTAMP",
    ("official_sources", "updated_at"): "CURRENT_TIMESTAMP",
    ("official_sources", "registry_managed"): "false",
    ("result_claims", "evidence_location"): "'{}'::json",
    ("result_claims", "capture_confidence"): "'0'::double precision",
    ("result_claims", "capture_status"): "'unreviewed'::character varying",
    ("result_claims", "scientific_status"): "'unknown'::character varying",
    ("result_claims", "created_at"): "CURRENT_TIMESTAMP",
    ("source_revision_decisions", "basis_json"): "'{}'::json",
    ("source_revision_decisions", "decided_at"): "CURRENT_TIMESTAMP",
    ("source_snapshots", "captured_at"): "CURRENT_TIMESTAMP",
    ("source_snapshots", "fetch_metadata"): "'{}'::json",
    ("source_snapshots", "created_at"): "CURRENT_TIMESTAMP",
}

POSTGRESQL_CONNECTION_CONTRACT = {
    "migration": (
        "direct or session-pooled connection with SET ROLE to the NOLOGIN migrator owner; "
        "transaction pooling is unsupported"
    ),
    "runtime": "bounded pool; transaction pooling requires unnamed prepared statements",
    "backup_restore": "direct connection tested independently from runtime",
    "tls": "verify-full with the provider CA in production",
    "defaults": "no provider, host, port, credential, or live DATABASE_URL is implicit",
}

_IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")

_AUDIT_TABLES = tuple(sorted(POSTGRESQL_REQUIRED_TABLES))

_MIGRATOR_OWNED_TABLES = ("alembic_version", *_AUDIT_TABLES)

_INGESTION_READ_TABLES = (
    "aliases",
    "benchmarks",
    "claim_validations",
    "ingestion_runs",
    "model_entities",
    "official_source_revisions",
    "official_sources",
    "result_claims",
    "source_revision_decisions",
    "source_snapshots",
    "discovery_candidates",
    "extraction_batches",
    "notification_intents",
    "notification_outbox_batches",
    "notification_outbox_items",
    "notification_receipts",
    "ops_incident_events",
    "ops_incidents",
    "scheduled_cycle_intent_completions",
    "scheduled_cycle_intents",
    "scheduled_cycles",
    "scheduled_job_attempts",
    "scheduled_job_intents",
    "scheduled_job_lease_events",
    "scheduled_job_leases",
    "source_check_receipts",
    "source_contract_envelopes",
)

_INGESTION_INSERT_TABLES = (
    "claim_validations",
    "ingestion_runs",
    "result_claims",
    "source_snapshots",
    "discovery_candidates",
    "extraction_batches",
    "notification_intents",
    "notification_outbox_batches",
    "notification_outbox_items",
    "notification_receipts",
    "ops_incident_events",
    "ops_incidents",
    "scheduled_cycle_intent_completions",
    "scheduled_cycle_intents",
    "scheduled_cycles",
    "scheduled_job_attempts",
    "scheduled_job_intents",
    "scheduled_job_lease_events",
    "scheduled_job_leases",
    "source_check_receipts",
    "source_contract_envelopes",
)

# A PostgreSQL foreign-key check uses a key-share lock and therefore needs an
# UPDATE privilege on at least one referenced column. Only identity columns are
# granted, and every one is protected by an immutable-id or append-only guard.
_INGESTION_REFERENCE_ID_TABLES = (
    "benchmarks",
    "model_entities",
    "official_source_revisions",
    "official_sources",
    "result_claims",
    "source_revision_decisions",
    "source_snapshots",
)

# The runner inserts a run as ``running`` and finalizes it once with these
# fields. Identity/source/start fields and terminal rows are trigger-frozen.
_INGESTION_RUN_UPDATE_COLUMNS = (
    "finished_at",
    "status",
    "sources_checked",
    "snapshots_created",
    "snapshots_reused",
    "claims_extracted",
    "claims_inserted",
    "claims_unchanged",
    "claims_needing_review",
    "error_message",
    "metadata",
)

_INGESTION_OPERATIONAL_REFERENCE_COLUMNS = {
    "notification_intents": ("intent_id",),
    "notification_outbox_batches": ("incident_event_id", "outbox_batch_id"),
    "notification_outbox_items": ("incident_event_id", "intent_id"),
    "notification_receipts": ("receipt_id",),
    "ops_incident_events": ("event_id",),
    "ops_incidents": ("incident_id",),
    "scheduled_cycle_intents": ("cycle_id",),
    "scheduled_job_attempts": ("attempt_id",),
    "scheduled_job_intents": ("job_id",),
    "scheduled_job_lease_events": ("lease_id",),
    "source_check_receipts": ("receipt_id",),
    "source_contract_envelopes": ("contract_revision_id",),
}

_GOVERNANCE_READ_TABLES = _AUDIT_TABLES

_GOVERNANCE_INSERT_TABLES = (
    "benchmark_definition_revisions",
    "evaluation_subject_revisions",
    "identity_decisions",
    "review_work_item_events",
    "review_work_items",
)

_GOVERNANCE_REFERENCE_COLUMNS = {
    "benchmark_definition_revisions": ("benchmark_definition_revision_id",),
    "discovery_candidates": ("candidate_id",),
    "evaluation_subject_revisions": ("subject_revision_id",),
    "identity_decisions": ("decision_id",),
    "model_entities": ("id",),
    "review_work_item_events": ("event_id",),
    "review_work_items": ("work_item_id",),
}

_ARTIFACT_READ_TABLES = (
    "aliases",
    "benchmarks",
    "claim_publication_decisions",
    "claim_review_decisions",
    "claim_validations",
    "model_entities",
    "official_source_revisions",
    "official_sources",
    "result_claims",
    "source_revision_decisions",
    "source_snapshots",
)


def is_postgresql_url(database_url: str) -> bool:
    """Return whether SQLAlchemy recognizes a PostgreSQL-family URL."""
    try:
        return make_url(database_url).get_backend_name() == "postgresql"
    except Exception:
        return False


def redacted_postgresql_url(database_url: str) -> str:
    """Render a PostgreSQL locator without password or query-string secrets."""
    url = make_url(database_url)
    if url.get_backend_name() != "postgresql":
        raise ValueError("Expected a PostgreSQL database URL.")
    # Query parameters may contain SSL key paths, provider routing tokens, or
    # percent-encoded socket locations. The status receipt does not need them.
    safe = url.set(password="***" if url.password is not None else None, query={})
    return safe.render_as_string(hide_password=True)


def _identifier(value: str, *, label: str) -> str:
    if not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"{label} must be a lowercase PostgreSQL identifier (maximum 63 bytes).")
    return value


def render_least_privilege_role_sql(
    *,
    schema: str = "public",
    migrator_role: str = "benchmark_ledger_migrator",
    ingestion_role: str = "benchmark_ledger_ingestion",
    governance_role: str = "benchmark_ledger_governance",
    artifact_role: str = "benchmark_ledger_artifact",
    audit_role: str = "benchmark_ledger_audit",
) -> str:
    """Render reviewable role SQL without credentials or provider assumptions.

    The migrator group owns schema evolution. Ingestion can append capture
    evidence but cannot govern it; governance can append decisions but cannot
    create claims; artifact and audit identities are read-only. No role can log
    in until an operator separately grants it to a managed login identity.
    """
    schema = _identifier(schema, label="schema")
    migrator_role = _identifier(migrator_role, label="migrator_role")
    ingestion_role = _identifier(ingestion_role, label="ingestion_role")
    governance_role = _identifier(governance_role, label="governance_role")
    artifact_role = _identifier(artifact_role, label="artifact_role")
    audit_role = _identifier(audit_role, label="audit_role")
    roles = (migrator_role, ingestion_role, governance_role, artifact_role, audit_role)
    if len(set(roles)) != len(roles):
        raise ValueError("Ledger PostgreSQL role identifiers must be distinct.")
    role_literals = ", ".join(f"'{role}'" for role in roles)
    runtime_role_literals = ", ".join(
        f"'{role}'" for role in (ingestion_role, governance_role, artifact_role, audit_role)
    )
    create_blocks = "\n".join(
        f"""DO $role$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN
        CREATE ROLE {role} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
    END IF;
END;
$role$;"""
        for role in roles
    )
    membership_guard = f"""DO $membership$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_auth_members membership
        JOIN pg_roles granted_role ON granted_role.oid = membership.roleid
        JOIN pg_roles member_role ON member_role.oid = membership.member
        WHERE granted_role.rolname IN ({role_literals})
           OR member_role.rolname IN ({role_literals})
    ) THEN
        RAISE EXCEPTION
            'managed ledger roles must not have pre-existing memberships; review and revoke them first';
    END IF;
END;
$membership$;"""
    ownership_guard = f"""DO $ownership$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_database database_object
        JOIN pg_roles owner_role ON owner_role.oid = database_object.datdba
        WHERE database_object.datname = current_database()
          AND owner_role.rolname IN ({runtime_role_literals})
        UNION ALL
        SELECT 1
        FROM pg_namespace namespace
        JOIN pg_roles owner_role ON owner_role.oid = namespace.nspowner
        WHERE namespace.nspname = '{schema}'
          AND owner_role.rolname IN ({runtime_role_literals})
        UNION ALL
        SELECT 1
        FROM pg_class relation
        JOIN pg_namespace namespace ON namespace.oid = relation.relnamespace
        JOIN pg_roles owner_role ON owner_role.oid = relation.relowner
        WHERE namespace.nspname = '{schema}'
          AND owner_role.rolname IN ({runtime_role_literals})
        UNION ALL
        SELECT 1
        FROM pg_proc function_object
        JOIN pg_namespace namespace ON namespace.oid = function_object.pronamespace
        JOIN pg_roles owner_role ON owner_role.oid = function_object.proowner
        WHERE namespace.nspname = '{schema}'
          AND owner_role.rolname IN ({runtime_role_literals})
        UNION ALL
        SELECT 1
        FROM pg_type type_object
        JOIN pg_namespace namespace ON namespace.oid = type_object.typnamespace
        JOIN pg_roles owner_role ON owner_role.oid = type_object.typowner
        WHERE namespace.nspname = '{schema}'
          AND owner_role.rolname IN ({runtime_role_literals})
    ) THEN
        RAISE EXCEPTION
            'runtime ledger roles must not own the current database, target schema, or target-schema objects';
    END IF;
END;
$ownership$;"""
    ingestion_read = ", ".join(f"{schema}.{table}" for table in _INGESTION_READ_TABLES)
    ingestion_insert = ", ".join(f"{schema}.{table}" for table in _INGESTION_INSERT_TABLES)
    ingestion_reference_ids = ", ".join(
        f"{schema}.{table}" for table in _INGESTION_REFERENCE_ID_TABLES
    )
    ingestion_operational_reference_grants = "\n".join(
        f"GRANT UPDATE ({', '.join(columns)}) ON {schema}.{table} TO {ingestion_role};"
        for table, columns in sorted(_INGESTION_OPERATIONAL_REFERENCE_COLUMNS.items())
    )
    governance_read = ", ".join(f"{schema}.{table}" for table in _GOVERNANCE_READ_TABLES)
    governance_insert = ", ".join(f"{schema}.{table}" for table in _GOVERNANCE_INSERT_TABLES)
    governance_reference_grants = "\n".join(
        f"GRANT UPDATE ({', '.join(columns)}) ON {schema}.{table} TO {governance_role};"
        for table, columns in sorted(_GOVERNANCE_REFERENCE_COLUMNS.items())
    )
    artifact_read = ", ".join(f"{schema}.{table}" for table in _ARTIFACT_READ_TABLES)
    audit_read = ", ".join(f"{schema}.{table}" for table in _AUDIT_TABLES)
    guard_functions = ", ".join(
        f"{schema}.{function_name}()" for function_name in sorted(POSTGRESQL_REQUIRED_FUNCTIONS)
    )
    # The migrator is the object owner. Revoking ordinary object ACLs from an
    # owner can break PostgreSQL's internal referential-integrity trigger
    # execution on a repeated convergence run, even though ownership remains.
    # Runtime roles are fully scrubbed; the migrator is normalized by ownership,
    # role attributes, schema grants, and the no-membership guard.
    runtime_roles = ", ".join((ingestion_role, governance_role, artifact_role, audit_role))
    ownership_sql = "\n".join(
        f"ALTER TABLE {schema}.{table} OWNER TO {migrator_role};"
        for table in _MIGRATOR_OWNED_TABLES
    )
    function_ownership_sql = "\n".join(
        f"ALTER FUNCTION {schema}.{function_name}() OWNER TO {migrator_role};"
        for function_name in sorted(POSTGRESQL_REQUIRED_FUNCTIONS)
    )
    return f"""-- Review and run as the schema owner/role administrator.
{create_blocks}
{membership_guard}
{ownership_guard}

ALTER ROLE {migrator_role} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS;
ALTER ROLE {ingestion_role} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS;
ALTER ROLE {governance_role} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS;
ALTER ROLE {artifact_role} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS;
ALTER ROLE {audit_role} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS;
ALTER ROLE {migrator_role} RESET ALL;
ALTER ROLE {ingestion_role} RESET ALL;
ALTER ROLE {governance_role} RESET ALL;
ALTER ROLE {artifact_role} RESET ALL;
ALTER ROLE {audit_role} RESET ALL;

REVOKE ALL ON SCHEMA {schema} FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA {schema} FROM PUBLIC;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA {schema} FROM PUBLIC;
REVOKE ALL ON FUNCTION {guard_functions} FROM PUBLIC;
REVOKE ALL ON SCHEMA {schema} FROM {runtime_roles};
REVOKE ALL ON ALL TABLES IN SCHEMA {schema} FROM {runtime_roles};
REVOKE ALL ON ALL SEQUENCES IN SCHEMA {schema} FROM {runtime_roles};
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA {schema} FROM {runtime_roles};

-- Existing and future schema evolution must run after SET ROLE to this
-- NOLOGIN owner group. Managed login identities are assigned separately.
{ownership_sql}
{function_ownership_sql}

GRANT USAGE, CREATE ON SCHEMA {schema} TO {migrator_role};
GRANT USAGE ON SCHEMA {schema} TO {ingestion_role}, {governance_role}, {artifact_role}, {audit_role};
GRANT SELECT ON {ingestion_read} TO {ingestion_role};
GRANT INSERT ON {ingestion_insert} TO {ingestion_role};
GRANT UPDATE (id) ON {ingestion_reference_ids} TO {ingestion_role};
GRANT UPDATE ({', '.join(_INGESTION_RUN_UPDATE_COLUMNS)}) ON {schema}.ingestion_runs TO {ingestion_role};
GRANT UPDATE ON {schema}.scheduled_job_leases TO {ingestion_role};
{ingestion_operational_reference_grants}
GRANT SELECT ON {governance_read} TO {governance_role};
GRANT INSERT ON {governance_insert} TO {governance_role};
{governance_reference_grants}
GRANT SELECT ON {artifact_read} TO {artifact_role};
GRANT SELECT ON {audit_read} TO {audit_role};

ALTER DEFAULT PRIVILEGES FOR ROLE {migrator_role} IN SCHEMA {schema}
    REVOKE ALL ON TABLES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE {migrator_role} IN SCHEMA {schema}
    REVOKE ALL ON SEQUENCES FROM PUBLIC;
"""
