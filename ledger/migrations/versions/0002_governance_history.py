"""Add immutable source revisions and append-only governance decisions.

Existing rows are retained verbatim.  This revision adds a quarantined
assessment around legacy evidence instead of treating legacy status columns as
certification or publication approval.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from alembic import op
import sqlalchemy as sa

from migrations._dialect import is_offline, is_sqlite


revision = "0002_governance_history"
down_revision = "0001_legacy_schema"
branch_labels = None
depends_on = None

_SOURCE_FIELDS = (
    "benchmark_id",
    "source_name",
    "source_url",
    "source_type",
    "officialness_level",
    "machine_readable",
    "requires_auth",
    "supports_history",
    "update_cadence",
    "parser_name",
    "parser_version",
    "parser_config",
    "status",
    "notes",
)


def _json_value(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _canonical_json(value: dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)


def _legacy_id(kind: str, stable_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"benchmark-ledger:{kind}:{stable_id}"))


def _create_governance_tables() -> None:
    op.create_table(
        "official_source_revisions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("official_source_id", sa.String(length=128), nullable=False),
        sa.Column("revision_ordinal", sa.Integer(), nullable=False),
        sa.Column("definition_hash", sa.String(length=64), nullable=False),
        sa.Column("definition_json", sa.JSON(), nullable=False),
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
        sa.Column("origin", sa.String(length=64), nullable=False),
        sa.Column("supersedes_revision_id", sa.String(length=36)),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["official_source_id"], ["official_sources.id"]),
        sa.ForeignKeyConstraint(["supersedes_revision_id"], ["official_source_revisions.id"]),
        sa.UniqueConstraint("official_source_id", "revision_ordinal", name="uq_source_revision_ordinal"),
        sa.UniqueConstraint("official_source_id", "definition_hash", name="uq_source_revision_definition"),
    )
    op.create_table(
        "source_revision_decisions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("source_revision_id", sa.String(length=36), nullable=False),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("policy_version", sa.String(length=128), nullable=False),
        sa.Column("reason_code", sa.String(length=128), nullable=False),
        sa.Column("basis_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("actor", sa.String(length=128)),
        sa.Column("supersedes_decision_id", sa.String(length=36)),
        sa.Column("decided_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["source_revision_id"], ["official_source_revisions.id"]),
        sa.ForeignKeyConstraint(["supersedes_decision_id"], ["source_revision_decisions.id"]),
    )
    op.create_table(
        "claim_review_decisions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("result_claim_id", sa.String(length=36), nullable=False),
        sa.Column("model_entity_id", sa.String(length=128)),
        sa.Column("benchmark_id", sa.String(length=128)),
        sa.Column("metric", sa.String(length=128)),
        sa.Column("split", sa.String(length=128)),
        sa.Column("setting", sa.String(length=255)),
        sa.Column("evaluation_version", sa.String(length=128)),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("reason_code", sa.String(length=128), nullable=False),
        sa.Column("basis_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("actor", sa.String(length=128)),
        sa.Column("supersedes_decision_id", sa.String(length=36)),
        sa.Column("decided_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["result_claim_id"], ["result_claims.id"]),
        sa.ForeignKeyConstraint(["model_entity_id"], ["model_entities.id"]),
        sa.ForeignKeyConstraint(["benchmark_id"], ["benchmarks.id"]),
        sa.ForeignKeyConstraint(["supersedes_decision_id"], ["claim_review_decisions.id"]),
    )
    op.create_table(
        "claim_publication_decisions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("result_claim_id", sa.String(length=36), nullable=False),
        sa.Column("claim_review_decision_id", sa.String(length=36), nullable=False),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("policy_version", sa.String(length=128), nullable=False),
        sa.Column("reason_code", sa.String(length=128), nullable=False),
        sa.Column("basis_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("actor", sa.String(length=128)),
        sa.Column("supersedes_decision_id", sa.String(length=36)),
        sa.Column("decided_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["result_claim_id"], ["result_claims.id"]),
        sa.ForeignKeyConstraint(["claim_review_decision_id"], ["claim_review_decisions.id"]),
        sa.ForeignKeyConstraint(["supersedes_decision_id"], ["claim_publication_decisions.id"]),
    )


def _backfill_legacy_evidence() -> None:
    bind = op.get_bind()
    source_rows = bind.execute(sa.text("SELECT * FROM official_sources ORDER BY id")).mappings().all()
    source_revisions: dict[str, str] = {}

    for source in source_rows:
        definition = {field: _json_value(source[field], {}) if field == "parser_config" else source[field] for field in _SOURCE_FIELDS}
        definition["parser_config"] = _json_value(definition["parser_config"], {})
        for boolean_field in ("machine_readable", "requires_auth", "supports_history"):
            definition[boolean_field] = bool(definition[boolean_field])
        encoded_definition = _canonical_json(definition)
        definition_hash = hashlib.sha256(encoded_definition.encode("utf-8")).hexdigest()
        revision_id = _legacy_id("source-revision", f"{source['id']}:{definition_hash}")
        source_revisions[source["id"]] = revision_id

        bind.execute(
            sa.text(
                """
                INSERT INTO official_source_revisions (
                    id, official_source_id, revision_ordinal, definition_hash,
                    definition_json, source_name, source_url, source_type,
                    officialness_level, machine_readable, requires_auth,
                    supports_history, update_cadence, parser_name, parser_version,
                    parser_config, status, notes, origin, supersedes_revision_id
                ) VALUES (
                    :id, :official_source_id, 1, :definition_hash,
                    :definition_json, :source_name, :source_url, :source_type,
                    :officialness_level, :machine_readable, :requires_auth,
                    :supports_history, :update_cadence, :parser_name, :parser_version,
                    :parser_config, :status, :notes, 'legacy_backfill', NULL
                )
                """
            ),
            {
                "id": revision_id,
                "official_source_id": source["id"],
                "definition_hash": definition_hash,
                "definition_json": encoded_definition,
                "source_name": definition["source_name"],
                "source_url": definition["source_url"],
                "source_type": definition["source_type"],
                "officialness_level": definition["officialness_level"],
                "machine_readable": definition["machine_readable"],
                "requires_auth": definition["requires_auth"],
                "supports_history": definition["supports_history"],
                "update_cadence": definition["update_cadence"],
                "parser_name": definition["parser_name"],
                "parser_version": definition["parser_version"],
                "parser_config": _canonical_json(definition["parser_config"]),
                "status": definition["status"],
                "notes": definition["notes"],
            },
        )
        decision_id = _legacy_id("source-decision", revision_id)
        bind.execute(
            sa.text(
                """
                INSERT INTO source_revision_decisions (
                    id, source_revision_id, outcome, policy_version, reason_code,
                    basis_json, actor, supersedes_decision_id
                ) VALUES (
                    :id, :source_revision_id, 'quarantined', 'legacy-assessment-v1',
                    'legacy_unassessed', :basis_json, 'migration', NULL
                )
                """
            ),
            {
                "id": decision_id,
                "source_revision_id": revision_id,
                "basis_json": _canonical_json(
                    {
                        "assessment": "Legacy source definition was preserved but has not been certified.",
                        "legacy_source_id": source["id"],
                    }
                ),
            },
        )

    for source_id, revision_id in source_revisions.items():
        bind.execute(
            sa.text("UPDATE official_sources SET current_revision_id = :revision_id WHERE id = :source_id"),
            {"revision_id": revision_id, "source_id": source_id},
        )
        bind.execute(
            sa.text(
                "UPDATE source_snapshots SET source_revision_id = :revision_id "
                "WHERE official_source_id = :source_id"
            ),
            {"revision_id": revision_id, "source_id": source_id},
        )

    claim_rows = bind.execute(sa.text("SELECT id FROM result_claims ORDER BY id")).mappings().all()
    for claim in claim_rows:
        review_id = _legacy_id("claim-review", claim["id"])
        publication_id = _legacy_id("claim-publication", claim["id"])
        basis_json = _canonical_json(
            {
                "assessment": "Legacy claim was retained without retroactive approval.",
                "legacy_claim_id": claim["id"],
            }
        )
        bind.execute(
            sa.text(
                """
                INSERT INTO claim_review_decisions (
                    id, result_claim_id, outcome, reason_code, basis_json, actor,
                    supersedes_decision_id
                ) VALUES (
                    :id, :claim_id, 'needs_review', 'legacy_unassessed',
                    :basis_json, 'migration', NULL
                )
                """
            ),
            {"id": review_id, "claim_id": claim["id"], "basis_json": basis_json},
        )
        bind.execute(
            sa.text(
                """
                INSERT INTO claim_publication_decisions (
                    id, result_claim_id, claim_review_decision_id, outcome,
                    policy_version, reason_code, basis_json, actor,
                    supersedes_decision_id
                ) VALUES (
                    :id, :claim_id, :review_id, 'quarantined',
                    'legacy-assessment-v1', 'legacy_unassessed', :basis_json,
                    'migration', NULL
                )
                """
            ),
            {
                "id": publication_id,
                "claim_id": claim["id"],
                "review_id": review_id,
                "basis_json": basis_json,
            },
        )


def upgrade() -> None:
    _create_governance_tables()
    if is_sqlite():
        # SQLite needs a batch rebuild to add these columns while retaining the
        # pre-existing legacy constraint names. PostgreSQL must never recreate
        # either referenced table: dependent foreign keys make that unsafe.
        with op.batch_alter_table("official_sources", recreate="always") as batch_op:
            batch_op.add_column(sa.Column("current_revision_id", sa.String(length=36), nullable=True))
        with op.batch_alter_table("source_snapshots", recreate="always") as batch_op:
            batch_op.add_column(sa.Column("source_revision_id", sa.String(length=36), nullable=True))
    else:
        op.add_column(
            "official_sources",
            sa.Column("current_revision_id", sa.String(length=36), nullable=True),
        )
        op.add_column(
            "source_snapshots",
            sa.Column("source_revision_id", sa.String(length=36), nullable=True),
        )

    # Offline SQL is a fresh-schema artifact and therefore has no legacy rows
    # to assess. Online upgrades retain the deterministic quarantine backfill.
    if not is_offline():
        _backfill_legacy_evidence()


def downgrade() -> None:
    raise RuntimeError("Ledger migrations are recovery-only: restore the verified pre-migration backup instead of downgrading.")
