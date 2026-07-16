"""Create the pre-governance ledger schema baseline.

This revision is intentionally a hand-authored representation of the schema
that existed before versioned migrations.  A populated unversioned database is
never upgraded through this revision directly: the migration service first
verifies its exact legacy signature and stamps this baseline.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0001_legacy_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "benchmarks",
        sa.Column("id", sa.String(length=128), primary_key=True),
        sa.Column("canonical_name", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("benchmark_family", sa.String(length=128)),
        sa.Column("description", sa.Text()),
        sa.Column("owner_name", sa.String(length=255)),
        sa.Column("owner_type", sa.String(length=64)),
        sa.Column("official_home_url", sa.Text()),
        sa.Column("official_repo_url", sa.Text()),
        sa.Column("official_dataset_url", sa.Text()),
        sa.Column("official_leaderboard_url", sa.Text()),
        sa.Column("official_docs_url", sa.Text()),
        sa.Column("has_official_leaderboard", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("has_official_result_api", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("has_official_result_files", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("has_private_test_set", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("primary_metric", sa.String(length=128)),
        sa.Column("known_metrics", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("known_splits", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("known_settings", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("superseded_by_benchmark_id", sa.String(length=128)),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["superseded_by_benchmark_id"], ["benchmarks.id"]),
    )
    op.create_table(
        "model_entities",
        sa.Column("id", sa.String(length=128), primary_key=True),
        sa.Column("canonical_name", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("entity_type", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=128)),
        sa.Column("developer", sa.String(length=128)),
        sa.Column("model_family", sa.String(length=128)),
        sa.Column("access_type", sa.String(length=64)),
        sa.Column("official_model_url", sa.Text()),
        sa.Column("official_docs_url", sa.Text()),
        sa.Column("official_card_url", sa.Text()),
        sa.Column("official_repo_url", sa.Text()),
        sa.Column("official_hf_repo", sa.String(length=255)),
        sa.Column("api_model_id", sa.String(length=255)),
        sa.Column("api_version", sa.String(length=128)),
        sa.Column("endpoint_fingerprint", sa.String(length=255)),
        sa.Column("artifact_hash", sa.String(length=128)),
        sa.Column("weights_revision", sa.String(length=128)),
        sa.Column("tokenizer_revision", sa.String(length=128)),
        sa.Column("base_model_entity_id", sa.String(length=128)),
        sa.Column("release_date", sa.Date()),
        sa.Column("deprecation_date", sa.Date()),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("context_window", sa.Integer()),
        sa.Column("modalities", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("license", sa.String(length=128)),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["base_model_entity_id"], ["model_entities.id"]),
    )
    op.create_table(
        "aliases",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("entity_type", sa.String(length=32), nullable=False),
        sa.Column("entity_id", sa.String(length=128), nullable=False),
        sa.Column("alias_text", sa.String(length=512), nullable=False),
        sa.Column("alias_source", sa.String(length=255)),
        sa.Column("source_url", sa.Text()),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("is_official_alias", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("entity_type", "entity_id", "alias_text", name="uq_alias"),
    )
    op.create_table(
        "official_sources",
        sa.Column("id", sa.String(length=128), primary_key=True),
        sa.Column("benchmark_id", sa.String(length=128)),
        sa.Column("source_name", sa.String(length=255), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("source_type", sa.String(length=64), nullable=False),
        sa.Column("officialness_level", sa.String(length=8), nullable=False),
        sa.Column("machine_readable", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("requires_auth", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("supports_history", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("update_cadence", sa.String(length=64)),
        sa.Column("parser_name", sa.String(length=128)),
        sa.Column("parser_version", sa.String(length=64)),
        sa.Column("parser_config", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("notes", sa.Text()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["benchmark_id"], ["benchmarks.id"]),
        sa.UniqueConstraint("benchmark_id", "source_url", name="uq_source_url"),
    )
    op.create_table(
        "source_snapshots",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("official_source_id", sa.String(length=128), nullable=False),
        sa.Column("captured_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("raw_content_uri", sa.Text(), nullable=False),
        sa.Column("rendered_screenshot_uri", sa.Text()),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("content_type", sa.String(length=128)),
        sa.Column("http_status", sa.Integer()),
        sa.Column("etag", sa.String(length=255)),
        sa.Column("last_modified_header", sa.String(length=255)),
        sa.Column("fetch_metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("parser_version", sa.String(length=64)),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["official_source_id"], ["official_sources.id"]),
        sa.UniqueConstraint("official_source_id", "content_hash", name="uq_source_hash"),
    )
    op.create_table(
        "result_claims",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("source_snapshot_id", sa.String(length=36), nullable=False),
        sa.Column("official_source_id", sa.String(length=128), nullable=False),
        sa.Column("benchmark_id", sa.String(length=128)),
        sa.Column("model_entity_id", sa.String(length=128)),
        sa.Column("model_raw", sa.String(length=512), nullable=False),
        sa.Column("benchmark_raw", sa.String(length=512), nullable=False),
        sa.Column("score_raw", sa.String(length=128), nullable=False),
        sa.Column("metric_raw", sa.String(length=128)),
        sa.Column("split_raw", sa.String(length=128)),
        sa.Column("setting_raw", sa.String(length=255)),
        sa.Column("rank_raw", sa.String(length=64)),
        sa.Column("date_raw", sa.String(length=64)),
        sa.Column("score_numeric", sa.Float()),
        sa.Column("score_unit", sa.String(length=32)),
        sa.Column("evidence_text", sa.Text()),
        sa.Column("evidence_location", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("capture_method", sa.String(length=64), nullable=False),
        sa.Column("capture_confidence", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("capture_status", sa.String(length=32), nullable=False, server_default="unreviewed"),
        sa.Column("scientific_status", sa.String(length=64), nullable=False, server_default="unknown"),
        sa.Column("officialness_level", sa.String(length=8)),
        sa.Column("claim_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["source_snapshot_id"], ["source_snapshots.id"]),
        sa.ForeignKeyConstraint(["official_source_id"], ["official_sources.id"]),
        sa.ForeignKeyConstraint(["benchmark_id"], ["benchmarks.id"]),
        sa.ForeignKeyConstraint(["model_entity_id"], ["model_entities.id"]),
        sa.UniqueConstraint("source_snapshot_id", "claim_fingerprint", name="uq_claim_fp"),
    )
    op.create_table(
        "claim_validations",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("result_claim_id", sa.String(length=36), nullable=False),
        sa.Column("validation_type", sa.String(length=64), nullable=False),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("validator", sa.String(length=128)),
        sa.Column("notes", sa.Text()),
        sa.Column("validated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["result_claim_id"], ["result_claims.id"]),
    )
    op.create_table(
        "claim_relationships",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("claim_id", sa.String(length=36), nullable=False),
        sa.Column("related_claim_id", sa.String(length=36), nullable=False),
        sa.Column("relationship_type", sa.String(length=64), nullable=False),
        sa.Column("notes", sa.Text()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["claim_id"], ["result_claims.id"]),
        sa.ForeignKeyConstraint(["related_claim_id"], ["result_claims.id"]),
        sa.UniqueConstraint("claim_id", "related_claim_id", "relationship_type", name="uq_claim_rel"),
    )
    op.create_table(
        "ingestion_runs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("started_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("finished_at", sa.DateTime()),
        sa.Column("run_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="running"),
        sa.Column("official_source_id", sa.String(length=128)),
        sa.Column("sources_checked", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("snapshots_created", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("snapshots_reused", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("claims_extracted", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("claims_inserted", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("claims_unchanged", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("claims_needing_review", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text()),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.ForeignKeyConstraint(["official_source_id"], ["official_sources.id"]),
    )


def downgrade() -> None:
    raise RuntimeError("Ledger migrations are recovery-only: restore the verified pre-migration backup instead of downgrading.")
