"""Fail-closed, deterministic candidate projection for the Official feed.

This module deliberately has two separate boundaries:

* :func:`project_official_feed` is a pure, offline read model used to prove the
  ledger selection contract against fixtures.  It creates a *candidate* feed,
  never a release artifact.
* :func:`export_official_json` remains disabled.  No caller can turn the
  candidate projection into a published Official artifact until the later
  release-artifact gate is implemented.

The distinction is important: an approved claim is necessary for a candidate
cell, but it is not authorization to publish a frontend artifact.
"""

from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any, Iterable, Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models, repositories as repo
from app.ingestion.admission import (
    ADMISSION_POLICY_SCHEMA,
    MAX_CERTIFIED_FETCH_BYTES,
    _evidence_contract_is_well_formed,
    _locator_matches_contract,
)


OFFICIAL_FEED_SCHEMA_VERSION = "1.0.0"
OFFICIAL_FEED_POLICY_VERSION = "official-feed-projection-v1"
OFFICIAL_FEED_AVAILABILITY = "candidate"
CANONICAL_JSON_ALGORITHM = "sha256-canonical-json-v1"

#: Conservative hard cardinality caps that bound output and heap for the
#: offline candidate projection and legacy inventory.
#:
#: These are deliberately conservative production values, not test-sized: a
#: nested JSON report with 250k claims / 2M related rows can consume several
#: GB once serialized, so the caps are set well below that while retaining
#: headroom above realistic local capture ledgers (tens of thousands of
#: claims).  Each cap is versioned and documented; loading at most ``cap + 1``
#: rows (via SQL ``LIMIT``) lets the loader fail closed on the first row past
#: the cap before any per-claim processing, so a partial report is never
#: produced.
MAX_CLAIMS = 50_000
MAX_SNAPSHOTS = 20_000
MAX_RELATED_ROWS = 200_000

#: Maximum elements per ``IN (...)`` chunk, kept far below the SQLite 999 /
#: PostgreSQL 32767 parameter ceilings so bounded batch loading is portable.
_BATCH_CHUNK = 500


class FeedResourceLimitError(ValueError):
    """Raised when a bounded read-model resource cap would be exceeded.

    The candidate/inventory paths are all-or-nothing: exceeding a cap must
    fail closed before any per-claim processing and must never emit a partial
    report.
    """


def _batch_ids(values: Iterable[str]) -> list[list[str]]:
    """Split an ID collection into bounded ``IN`` chunks."""
    ids = list(values)
    return [ids[index : index + _BATCH_CHUNK] for index in range(0, len(ids), _BATCH_CHUNK)]


def _grouped_by(rows: Iterable[Any], key_attr: str) -> dict[str, list[Any]]:
    """Group ORM rows by one attribute into ``{value: [rows]}``."""
    grouped: dict[str, list[Any]] = {}
    for row in rows:
        grouped.setdefault(getattr(row, key_attr), []).append(row)
    return grouped


def _load_plain_by_ids(
    session: Session,
    model: type[models.Base],
    id_attr: Any,
    ids: Iterable[str],
) -> list[Any]:
    """Load rows by a column in bounded IN chunks (no per-id query, no budget).

    The result set is inherently bounded: each IN chunk holds at most
    ``_BATCH_CHUNK`` distinct IDs, so a chunk returns at most that many rows.
    Deterministic primary-key ordering keeps results stable.
    """
    rows: list[Any] = []
    for chunk in _batch_ids(sorted(set(ids))):
        if not chunk:
            continue
        statement = (
            select(model)
            .where(id_attr.in_(chunk))
            .order_by(id_attr, model.id)
        )
        rows.extend(session.scalars(statement).all())
    return rows


def _load_budgeted_by_ids(
    session: Session,
    model: type[models.Base],
    id_attr: Any,
    ids: Iterable[str],
    *,
    budget: _Budget,
) -> list[Any]:
    """Load rows in bounded, deterministically ordered IN chunks against one
    persistent cross-chunk budget.

    IDs are sorted and deduplicated before chunking, each chunk query carries
    a deterministic primary-key ordering plus ``LIMIT budget.remaining + 1``,
    and if a chunk returns more than the remaining budget the loader fails
    closed immediately (with the budget's stable label).  The budget is then
    decremented by the actual row count before the next chunk, so it persists
    across all chunks and all related-row types.
    """
    rows: list[Any] = []
    ordered_ids = sorted(set(ids))
    for chunk in _batch_ids(ordered_ids):
        if not chunk:
            continue
        budget_remaining = budget.remaining
        statement = (
            select(model)
            .where(id_attr.in_(chunk))
            # Deterministic ordering: for non-unique id columns the model
            # primary key breaks ties so results are stable.
            .order_by(id_attr, model.id)
            .limit(budget_remaining + 1)
        )
        chunk_rows = list(session.scalars(statement).all())
        if len(chunk_rows) > budget_remaining:
            raise FeedResourceLimitError(
                f"{budget.label} exceed the documented cap of {budget.cap}"
            )
        budget.consume(len(chunk_rows))
        rows.extend(chunk_rows)
    return rows


class _Budget:
    """A persistent remaining-row budget with an aggregate cap and stable label."""

    def __init__(self, cap: int, label: str) -> None:
        self.cap = cap
        self.label = label
        self.remaining = cap

    def consume(self, count: int) -> None:
        if count > self.remaining:
            raise FeedResourceLimitError(
                f"{self.label} exceed the documented cap of {self.cap}"
            )
        self.remaining -= count


class FeedBatch:
    """One bounded, preloaded read-model context for the candidate projection.

    Loads every related row the eligibility policy needs in a bounded number
    of batch SELECTs (chunked below the SQLite/PostgreSQL parameter ceilings)
    so per-claim processing is pure and issues no queries.

    Two load shapes are used:

    - Unique-ID loads (sources, revisions, models, benchmarks): each IN chunk
      holds at most ``_BATCH_CHUNK`` distinct IDs, so a chunk returns at most
      that many rows and no SQL ``LIMIT`` is needed.  These do not consume the
      related-row budget.
    - Budgeted loads (snapshots and decision/validation rows): each chunk
      carries an SQL ``LIMIT`` at ``remaining budget + 1`` with a stable
      label, and the budget persists across all chunks and all related types,
      so a single oversized chunk cannot materialize an unbounded result;
      overflow is detected by actual ORM row count before per-claim
      processing.

    All fail-closed chain semantics are preserved by resolving chains in
    memory with the same pure resolution rules.
    """

    def __init__(
        self,
        session: Session,
        claims: list[models.ResultClaim],
    ) -> None:
        # Defensive shared-cap boundary: even when a caller passes a prebuilt
        # batch (bypassing analyze's own claim load), an oversized claim set
        # must fail closed before any related load.
        if len(claims) > MAX_CLAIMS:
            raise FeedResourceLimitError(
                f"claim count exceeds the documented cap of {MAX_CLAIMS}"
            )
        self.claims = claims
        claim_ids = [claim.id for claim in claims]
        snapshot_ids = list({claim.source_snapshot_id for claim in claims})
        revision_ids: set[str] = set()
        source_ids = {claim.official_source_id for claim in claims}
        decision_ids = {
            claim.source_revision_decision_id
            for claim in claims
            if claim.source_revision_decision_id
        }

        # Snapshots: aggregate cross-chunk budget with a stable label.
        snapshot_budget = _Budget(MAX_SNAPSHOTS, "snapshot count")
        self.snapshots = {
            snapshot.id: snapshot
            for snapshot in _load_budgeted_by_ids(
                session,
                models.SourceSnapshot,
                models.SourceSnapshot.id,
                snapshot_ids,
                budget=snapshot_budget,
            )
        }
        revision_ids.update(
            snapshot.source_revision_id for snapshot in self.snapshots.values()
        )
        # Sources/revisions/models/benchmarks are bounded by the claims and
        # snapshots already loaded (one row per referenced id), so they are
        # plain bounded IN-chunk loads and do NOT consume the related budget.
        self.revisions = {
            revision.id: revision
            for revision in _load_plain_by_ids(
                session,
                models.OfficialSourceRevision,
                models.OfficialSourceRevision.id,
                revision_ids,
            )
        }
        self.sources = {
            source.id: source
            for source in _load_plain_by_ids(
                session,
                models.OfficialSourceRow,
                models.OfficialSourceRow.id,
                source_ids,
            )
        }

        # Related decision/validation rows share ONE persistent budget across
        # all chunks and all types.  Source-revision decisions are loaded by
        # referenced revision id FIRST (covering superseded predecessors and
        # the capture-time chain), then only exact decision ids missing from
        # that map are queried — so a durable row is never materialized or
        # charged twice and an under-cap ledger is never falsely rejected.
        related_budget = _Budget(MAX_RELATED_ROWS, "related decision/validation rows")
        self.source_decisions: dict[str, models.SourceRevisionDecision] = {}
        if revision_ids:
            for chunk in _batch_ids(sorted(revision_ids)):
                budget_remaining = related_budget.remaining
                chunk_rows = list(
                    session.scalars(
                        select(models.SourceRevisionDecision)
                        .where(models.SourceRevisionDecision.source_revision_id.in_(chunk))
                        .order_by(
                            models.SourceRevisionDecision.source_revision_id,
                            models.SourceRevisionDecision.id,
                        )
                        .limit(budget_remaining + 1)
                    )
                )
                if len(chunk_rows) > budget_remaining:
                    raise FeedResourceLimitError(
                        f"{related_budget.label} exceed the documented cap of {related_budget.cap}"
                    )
                related_budget.consume(len(chunk_rows))
                for decision in chunk_rows:
                    self.source_decisions.setdefault(decision.id, decision)
        missing_decision_ids = [
            decision_id
            for decision_id in decision_ids
            if decision_id not in self.source_decisions
        ]
        for decision in _load_budgeted_by_ids(
            session,
            models.SourceRevisionDecision,
            models.SourceRevisionDecision.id,
            missing_decision_ids,
            budget=related_budget,
        ):
            self.source_decisions.setdefault(decision.id, decision)

        self.validations = _grouped_by(
            _load_budgeted_by_ids(
                session,
                models.ClaimValidation,
                models.ClaimValidation.result_claim_id,
                claim_ids,
                budget=related_budget,
            ),
            "result_claim_id",
        )
        self.review_decisions = _grouped_by(
            _load_budgeted_by_ids(
                session,
                models.ClaimReviewDecision,
                models.ClaimReviewDecision.result_claim_id,
                claim_ids,
                budget=related_budget,
            ),
            "result_claim_id",
        )
        self.publication_decisions = _grouped_by(
            _load_budgeted_by_ids(
                session,
                models.ClaimPublicationDecision,
                models.ClaimPublicationDecision.result_claim_id,
                claim_ids,
                budget=related_budget,
            ),
            "result_claim_id",
        )
        self.review_decisions_by_id = {
            decision.id: decision
            for decisions in self.review_decisions.values()
            for decision in decisions
        }
        self.publication_decisions_by_id = {
            decision.id: decision
            for decisions in self.publication_decisions.values()
            for decision in decisions
        }
        model_ids = {claim.model_entity_id for claim in claims if claim.model_entity_id}
        benchmark_ids = {
            claim.benchmark_id for claim in claims if claim.benchmark_id
        }
        for decisions in self.review_decisions.values():
            for decision in decisions:
                if decision.model_entity_id:
                    model_ids.add(decision.model_entity_id)
                if decision.benchmark_id:
                    benchmark_ids.add(decision.benchmark_id)
        self.models = {
            model.id: model
            for model in _load_plain_by_ids(
                session,
                models.ModelEntity,
                models.ModelEntity.id,
                model_ids,
            )
        }
        self.benchmarks = {
            benchmark.id: benchmark
            for benchmark in _load_plain_by_ids(
                session,
                models.Benchmark,
                models.Benchmark.id,
                benchmark_ids,
            )
        }

    def review_chain(self, claim: models.ResultClaim) -> list[models.ClaimReviewDecision]:
        return repo._resolve_review_chain(
            claim.id, self.review_decisions.get(claim.id, [])
        )

    def publication_chain(
        self, claim: models.ResultClaim
    ) -> list[models.ClaimPublicationDecision]:
        return repo._resolve_publication_chain(
            claim.id, self.publication_decisions.get(claim.id, [])
        )


_HEX_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_TOP_LEVEL_KEYS = frozenset(
    {
        "schemaVersion",
        "policyVersion",
        "availability",
        "manifest",
        "models",
        "benchmarks",
        "sourceManifest",
        "scores",
        "excludedClaims",
    }
)
_CELL_KEYS = frozenset(
    {"modelId", "benchmarkId", "metric", "split", "setting", "evaluationVersion"}
)
_MANIFEST_KEYS = frozenset(
    {
        "algorithm",
        "contentSha256",
        "scoreCount",
        "modelCount",
        "benchmarkCount",
        "sourceSnapshotCount",
    }
)


class OfficialPublicationDisabledError(RuntimeError):
    """Raised while the legacy all-claims exporter is quarantined."""


class FeedProjectionError(ValueError):
    """A candidate feed is malformed or cannot be safely projected."""


class FeedConflictError(FeedProjectionError):
    """More than one otherwise eligible claim targets one display cell."""

    def __init__(self, report: dict[str, Any]):
        self.report = report
        super().__init__(
            "Official feed projection has unresolved display-cell conflicts; "
            "no candidate feed was produced."
        )


@dataclass(frozen=True)
class _EligibleClaim:
    claim: models.ResultClaim
    model: models.ModelEntity
    benchmark: models.Benchmark
    cell: dict[str, str | None]
    provenance: dict[str, Any]


@dataclass(frozen=True)
class FeedCandidateAnalysis:
    """Read-only eligibility accounting shared by projections and diagnostics.

    ``eligible_candidates`` contains every claim that independently satisfies
    the LDR-08 selection policy.  It deliberately includes candidates that
    later collide on a display cell: a conflict is not a reason to erase the
    historical fact that each individual claim passed the eligibility gates.
    The public candidate projection remains all-or-nothing and will reject
    any analysis with ``conflicts``.
    """

    eligible_candidates: tuple[_EligibleClaim, ...]
    excluded_claims: tuple[dict[str, str], ...]
    conflicts: tuple[tuple[dict[str, str | None], tuple[_EligibleClaim, ...]], ...]


def _canonical_json(value: Any) -> str:
    """Return the only serialization used by the candidate digest."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def canonical_official_feed_json(payload: Mapping[str, Any]) -> str:
    """Serialize a candidate feed deterministically for offline comparison."""
    return _canonical_json(payload)


def _digest_payload(payload: Mapping[str, Any]) -> str:
    """Hash a document with its self-referential digest field blanked."""
    digest_input = deepcopy(dict(payload))
    manifest = digest_input.get("manifest")
    if isinstance(manifest, dict):
        manifest["contentSha256"] = None
    return hashlib.sha256(_canonical_json(digest_input).encode("utf-8")).hexdigest()


def official_feed_digest(payload: Mapping[str, Any]) -> str:
    """Return the versioned canonical digest for a candidate feed."""
    return _digest_payload(payload)


def _iso8601(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value.isoformat(timespec="microseconds")


def _cell_sort_key(cell: Mapping[str, str | None]) -> str:
    return _canonical_json(dict(cell))


def _is_nonempty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_finite_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _capture_time_policy_is_complete(
    decision: models.SourceRevisionDecision,
    revision: models.OfficialSourceRevision,
    claim: models.ResultClaim,
) -> bool:
    """Recheck the durable parts of admission without consulting current source state."""
    basis = decision.basis_json if isinstance(decision.basis_json, dict) else {}
    policy = basis.get("source_admission")
    if not isinstance(policy, dict):
        return False
    if policy.get("schema") != ADMISSION_POLICY_SCHEMA:
        return False
    if policy.get("definition_hash") != revision.definition_hash:
        return False
    if policy.get("source_kind") != "official_reported_result":
        return False

    adapter = policy.get("adapter")
    if not isinstance(adapter, dict):
        return False
    if adapter.get("parser_name") != revision.parser_name or adapter.get("parser_version") != revision.parser_version:
        return False

    approved_source_urls = policy.get("approved_source_urls")
    approved_final_urls = policy.get("approved_final_urls")
    if (
        not isinstance(approved_source_urls, list)
        or not isinstance(approved_final_urls, list)
        or revision.source_url not in approved_source_urls
        or not approved_final_urls
    ):
        return False

    locator_types = policy.get("locator_types")
    evidence_contracts = policy.get("evidence_contracts")
    if (
        not isinstance(locator_types, list)
        or not locator_types
        or not isinstance(evidence_contracts, dict)
        or set(evidence_contracts) != set(locator_types)
    ):
        return False
    for locator_type in locator_types:
        if not isinstance(locator_type, str):
            return False
        contract_ok, _detail = _evidence_contract_is_well_formed(
            locator_type, evidence_contracts.get(locator_type)
        )
        if not contract_ok:
            return False

    dimensions = policy.get("dimensions")
    if not isinstance(dimensions, dict):
        return False
    for field_name, value in (
        ("benchmark_raw", claim.benchmark_raw),
        ("metric_raw", claim.metric_raw),
        ("split_raw", claim.split_raw),
        ("setting_raw", claim.setting_raw),
        ("evaluation_version_raw", claim.evaluation_version_raw),
    ):
        declared = dimensions.get(field_name)
        if not isinstance(declared, dict) or declared.get("mode") not in {
            "revision_constant",
            "evidence_field",
        }:
            return False
        allowed_values = declared.get("allowed_values")
        if not isinstance(allowed_values, list) or value not in allowed_values:
            return False
        if declared.get("mode") == "revision_constant" and declared.get("value") != value:
            return False

    numeric = policy.get("numeric")
    if not isinstance(numeric, dict):
        return False
    if numeric.get("lexeme") not in {"decimal", "decimal_percent"}:
        return False
    if numeric.get("score_unit") != claim.score_unit:
        return False
    fetch = policy.get("fetch")
    max_bytes = fetch.get("max_bytes") if isinstance(fetch, dict) else None
    if type(max_bytes) is not int or not 1 <= max_bytes <= MAX_CERTIFIED_FETCH_BYTES:
        return False
    return True


def _source_provenance_batched(
    batch: FeedBatch, claim: models.ResultClaim
) -> tuple[dict[str, Any] | None, str | None]:
    """Batch-context counterpart of :func:`_source_provenance`.

    Identical fail-closed semantics and stable exclusion reasons, resolved
    entirely from the preloaded batch (no per-claim queries).
    """
    if not claim.source_revision_decision_id:
        return None, "SOURCE_DECISION_MISSING"
    snapshot = batch.snapshots.get(claim.source_snapshot_id)
    decision = batch.source_decisions.get(claim.source_revision_decision_id)
    if snapshot is None or decision is None:
        return None, "SOURCE_PROVENANCE_MISSING"
    revision = batch.revisions.get(snapshot.source_revision_id)
    source = batch.sources.get(claim.official_source_id)
    if revision is None or source is None:
        return None, "SOURCE_PROVENANCE_MISSING"
    if (
        snapshot.official_source_id != claim.official_source_id
        or revision.official_source_id != claim.official_source_id
        or decision.source_revision_id != snapshot.source_revision_id
    ):
        return None, "SOURCE_PROVENANCE_LINK_MISMATCH"
    effective_decision, decision_error = _effective_source_revision_decision_batched(
        batch, revision.id
    )
    if decision_error is not None:
        return None, decision_error
    assert effective_decision is not None
    if effective_decision.id != decision.id or decision.outcome != "certified":
        return None, "SOURCE_DECISION_NOT_CERTIFIED"
    if not _capture_time_policy_is_complete(decision, revision, claim):
        return None, "SOURCE_CERTIFICATION_POLICY_INVALID"
    if (
        not _is_nonempty_string(snapshot.content_hash)
        or _HEX_SHA256.fullmatch(snapshot.content_hash) is None
        or not _is_nonempty_string(revision.definition_hash)
        or _HEX_SHA256.fullmatch(revision.definition_hash) is None
    ):
        return None, "SNAPSHOT_HASH_INVALID"
    captured_at = _iso8601(snapshot.captured_at)
    if captured_at is None:
        return None, "SNAPSHOT_CAPTURE_TIME_MISSING"

    source_manifest_key = ":".join((source.id, revision.id, snapshot.id))
    return {
        "sourceManifestKey": source_manifest_key,
        "officialSourceId": source.id,
        "sourceRevisionId": revision.id,
        "sourceRevisionDecisionId": decision.id,
        "sourceName": revision.source_name,
        "sourceUrl": revision.source_url,
        "sourceType": revision.source_type,
        "sourceRevisionDefinitionSha256": revision.definition_hash,
        "sourceSnapshotId": snapshot.id,
        "snapshotContentSha256": snapshot.content_hash,
        "snapshotCapturedAt": captured_at,
    }, None


def _effective_source_revision_decision_batched(
    batch: FeedBatch, source_revision_id: str
) -> tuple[models.SourceRevisionDecision | None, str | None]:
    """Batch-context counterpart of :func:`_effective_source_revision_decision`.

    The claim binds a specific source-revision decision id, so the effective
    decision for the claim is that exact decision; the batch preloads every
    decision by id and the capture-time policy re-check below is unchanged.
    """
    decisions = [
        decision
        for decision in batch.source_decisions.values()
        if decision.source_revision_id == source_revision_id
    ]
    if not decisions:
        return None, "SOURCE_DECISION_MISSING"
    by_id = {decision.id: decision for decision in decisions}
    superseded: set[str] = set()
    for decision in decisions:
        parent_id = decision.supersedes_decision_id
        if parent_id is None:
            continue
        parent = by_id.get(parent_id)
        if parent is None or parent.source_revision_id != source_revision_id:
            return None, "SOURCE_DECISION_CHAIN_INVALID"
        superseded.add(parent_id)
    leaves = [decision for decision in decisions if decision.id not in superseded]
    if len(leaves) != 1:
        return None, "SOURCE_DECISION_CHAIN_AMBIGUOUS"
    current: models.SourceRevisionDecision | None = leaves[0]
    visited: set[str] = set()
    while current is not None:
        if current.id in visited:
            return None, "SOURCE_DECISION_CHAIN_CYCLIC"
        visited.add(current.id)
        current = (
            by_id.get(current.supersedes_decision_id)
            if current.supersedes_decision_id
            else None
        )
    return leaves[0], None


def _claim_locator_matches_capture_policy_batched(
    batch: FeedBatch, claim: models.ResultClaim
) -> bool:
    """Batch-context counterpart of :func:`_claim_locator_matches_capture_policy`."""
    if not claim.source_revision_decision_id:
        return False
    decision = batch.source_decisions.get(claim.source_revision_decision_id)
    basis = decision.basis_json if decision is not None and isinstance(decision.basis_json, dict) else {}
    policy = basis.get("source_admission")
    return isinstance(policy, dict) and _locator_matches_contract(claim.evidence_location, policy)


def _eligible_claim_batched(
    batch: FeedBatch, claim: models.ResultClaim
) -> tuple[_EligibleClaim | None, str | None]:
    """Batch-context counterpart of :func:`_eligible_claim` (no per-claim query)."""
    provenance, reason = _source_provenance_batched(batch, claim)
    if reason is not None:
        return None, reason
    assert provenance is not None

    validations = batch.validations.get(claim.id, [])
    if not validations:
        return None, "VALIDATION_MISSING"
    if any(validation.outcome != "pass" for validation in validations):
        return None, "VALIDATION_NOT_ALL_PASS"

    try:
        review_chain = batch.review_chain(claim)
    except repo.ClaimReviewChainError:
        return None, "REVIEW_CHAIN_INVALID"
    if not review_chain:
        return None, "REVIEW_DECISION_MISSING"
    effective_review = review_chain[0]
    if effective_review.outcome != "validation_reviewed":
        return None, "REVIEW_NOT_VALIDATION_REVIEWED"
    reviewed_model = next(
        (decision.model_entity_id for decision in review_chain if decision.model_entity_id is not None),
        claim.model_entity_id,
    )
    reviewed_benchmark = next(
        (decision.benchmark_id for decision in review_chain if decision.benchmark_id is not None),
        claim.benchmark_id,
    )
    if reviewed_model is None or reviewed_benchmark is None:
        return None, "DISPLAY_IDENTITY_UNRESOLVED"

    try:
        publication_chain = batch.publication_chain(claim)
    except repo.ClaimReviewChainError:
        return None, "PUBLICATION_CHAIN_INVALID"
    if not publication_chain:
        return None, "PUBLICATION_NOT_APPROVED"
    publication = publication_chain[0]
    if (
        publication.outcome != "approved"
        or publication.claim_review_decision_id != effective_review.id
    ):
        return None, "PUBLICATION_NOT_APPROVED"

    if not _is_finite_number(claim.score_numeric):
        return None, "SCORE_NOT_FINITE_NUMERIC"
    if not all(
        _is_nonempty_string(value)
        for value in (claim.model_raw, claim.benchmark_raw, claim.score_raw, claim.capture_method)
    ):
        return None, "RAW_CLAIM_FIELDS_INCOMPLETE"
    if not isinstance(claim.evidence_location, dict) or not _is_nonempty_string(
        claim.evidence_location.get("type")
    ):
        return None, "EVIDENCE_LOCATION_INCOMPLETE"
    if not _claim_locator_matches_capture_policy_batched(batch, claim):
        return None, "EVIDENCE_LOCATION_CONTRACT_MISMATCH"

    model = batch.models.get(reviewed_model)
    benchmark = batch.benchmarks.get(reviewed_benchmark)
    if model is None or benchmark is None:
        return None, "DISPLAY_IDENTITY_MISSING"

    reviewed_metric = next(
        (decision.metric for decision in review_chain if decision.metric is not None), claim.metric_raw
    )
    reviewed_split = next(
        (decision.split for decision in review_chain if decision.split is not None), claim.split_raw
    )
    reviewed_setting = next(
        (decision.setting for decision in review_chain if decision.setting is not None), claim.setting_raw
    )
    reviewed_evaluation_version = next(
        (decision.evaluation_version for decision in review_chain if decision.evaluation_version is not None),
        claim.evaluation_version_raw,
    )

    cell: dict[str, str | None] = {
        "modelId": model.id,
        "benchmarkId": benchmark.id,
        "metric": reviewed_metric,
        "split": reviewed_split,
        "setting": reviewed_setting,
        "evaluationVersion": reviewed_evaluation_version,
    }
    full_provenance = {
        **provenance,
        "claimReviewDecisionId": effective_review.id,
        "claimPublicationDecisionId": publication.id,
        "captureMethod": claim.capture_method,
    }
    return _EligibleClaim(
        claim=claim,
        model=model,
        benchmark=benchmark,
        cell=cell,
        provenance=full_provenance,
    ), None


def _model_record(model: models.ModelEntity) -> dict[str, Any]:
    return {
        "id": model.id,
        "canonicalName": model.canonical_name,
        "displayName": model.display_name,
        "provider": model.provider,
        "modelFamily": model.model_family,
        "status": model.status,
    }


def _benchmark_record(benchmark: models.Benchmark) -> dict[str, Any]:
    return {
        "id": benchmark.id,
        "canonicalName": benchmark.canonical_name,
        "displayName": benchmark.display_name,
        "benchmarkFamily": benchmark.benchmark_family,
        "primaryMetric": benchmark.primary_metric,
        "status": benchmark.status,
    }


def _source_manifest_record(provenance: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: provenance[key]
        for key in (
            "sourceManifestKey",
            "officialSourceId",
            "sourceRevisionId",
            "sourceRevisionDecisionId",
            "sourceName",
            "sourceUrl",
            "sourceType",
            "sourceRevisionDefinitionSha256",
            "sourceSnapshotId",
            "snapshotContentSha256",
            "snapshotCapturedAt",
        )
    }


def _score_record(candidate: _EligibleClaim) -> dict[str, Any]:
    return {
        "cell": candidate.cell,
        "claimId": candidate.claim.id,
        "value": float(candidate.claim.score_numeric),
        "scoreRaw": candidate.claim.score_raw,
        "scoreUnit": candidate.claim.score_unit,
        "evidenceText": candidate.claim.evidence_text,
        "evidenceLocation": deepcopy(candidate.claim.evidence_location),
        "provenance": candidate.provenance,
    }


def _conflict_report(
    conflicts: Iterable[tuple[dict[str, str | None], Iterable[_EligibleClaim]]],
    excluded_claims: list[dict[str, str]],
) -> dict[str, Any]:
    rows = []
    for cell, candidates in conflicts:
        rows.append(
            {
                "cell": cell,
                "claims": [
                    {
                        "claimId": candidate.claim.id,
                        "scoreRaw": candidate.claim.score_raw,
                        "value": float(candidate.claim.score_numeric),
                        "evidenceLocation": deepcopy(candidate.claim.evidence_location),
                        "provenance": candidate.provenance,
                    }
                    for candidate in sorted(candidates, key=lambda candidate: candidate.claim.id)
                ],
            }
        )
    rows.sort(key=lambda row: _cell_sort_key(row["cell"]))
    return {
        "schemaVersion": OFFICIAL_FEED_SCHEMA_VERSION,
        "policyVersion": OFFICIAL_FEED_POLICY_VERSION,
        "status": "conflict",
        "conflicts": rows,
        "excludedClaims": excluded_claims,
    }


def analyze_official_feed_candidates(
    session: Session, *, batch: FeedBatch | None = None
) -> FeedCandidateAnalysis:
    """Account for every claim under the deterministic candidate policy.

    This is an offline read model.  It does not choose a winner for a
    conflicting display cell and it does not write an assessment back to the
    ledger.  Callers that need a candidate feed must reject conflicts rather
    than treating this analysis as a partial export.

    Cardinality is hard-bounded: claims are loaded with an SQL
    ``LIMIT MAX_CLAIMS + 1`` (overflow is detected before per-claim
    processing), and related decision/validation rows are batch-loaded in
    bounded chunks with per-chunk remaining-budget limits.  Any overflow
    raises :class:`FeedResourceLimitError` before per-claim processing, so a
    partial candidate/inventory artifact is never produced.  A caller may pass
    a prebuilt ``batch`` (built once) so a report call shares one bounded
    context instead of building a duplicate.
    """
    with session.no_autoflush:
        if batch is None:
            claims = list(
                session.scalars(
                    select(models.ResultClaim)
                    .order_by(models.ResultClaim.id)
                    .limit(MAX_CLAIMS + 1)
                )
            )
            if len(claims) > MAX_CLAIMS:
                raise FeedResourceLimitError(
                    f"claim count exceeds the documented cap of {MAX_CLAIMS}"
                )
            batch = FeedBatch(session, claims)
        eligible_by_cell: dict[str, list[_EligibleClaim]] = defaultdict(list)
        excluded_claims: list[dict[str, str]] = []
        for claim in batch.claims:
            candidate, reason = _eligible_claim_batched(batch, claim)
            if candidate is None:
                assert reason is not None
                excluded_claims.append({"claimId": claim.id, "reasonCode": reason})
                continue
            eligible_by_cell[_cell_sort_key(candidate.cell)].append(candidate)

        excluded_claims.sort(key=lambda row: (row["claimId"], row["reasonCode"]))
        conflicts = [
            (candidates[0].cell, tuple(sorted(candidates, key=lambda candidate: candidate.claim.id)))
            for candidates in eligible_by_cell.values()
            if len(candidates) > 1
        ]
        conflicts.sort(key=lambda row: _cell_sort_key(row[0]))
        eligible_candidates = tuple(
            sorted(
                (candidate for candidates in eligible_by_cell.values() for candidate in candidates),
                key=lambda candidate: (_cell_sort_key(candidate.cell), candidate.claim.id),
            )
        )
        return FeedCandidateAnalysis(
            eligible_candidates=eligible_candidates,
            excluded_claims=tuple(excluded_claims),
            conflicts=tuple(conflicts),
        )


def project_official_feed(session: Session) -> dict[str, Any]:
    """Project eligible ledger evidence into a deterministic candidate feed.

    This function never writes to the session, does not read snapshot bytes,
    and intentionally does not accept an output path.  It is an offline
    contract check, not an Official-publication API.
    """
    with session.no_autoflush:
        analysis = analyze_official_feed_candidates(session)
        if analysis.conflicts:
            raise FeedConflictError(
                _conflict_report(analysis.conflicts, list(analysis.excluded_claims))
            )

        # With no conflict, every independently eligible candidate owns one
        # unique display cell.  There is no implicit recency/row-order winner.
        selected = list(analysis.eligible_candidates)
        models_by_id = {candidate.model.id: candidate.model for candidate in selected}
        benchmarks_by_id = {candidate.benchmark.id: candidate.benchmark for candidate in selected}
        source_manifest_by_key = {
            candidate.provenance["sourceManifestKey"]: _source_manifest_record(candidate.provenance)
            for candidate in selected
        }

        payload: dict[str, Any] = {
            "schemaVersion": OFFICIAL_FEED_SCHEMA_VERSION,
            "policyVersion": OFFICIAL_FEED_POLICY_VERSION,
            # This is deliberately not a frontend-loadable published artifact.
            "availability": OFFICIAL_FEED_AVAILABILITY,
            "manifest": {
                "algorithm": CANONICAL_JSON_ALGORITHM,
                "contentSha256": None,
                "scoreCount": len(selected),
                "modelCount": len(models_by_id),
                "benchmarkCount": len(benchmarks_by_id),
                "sourceSnapshotCount": len(source_manifest_by_key),
            },
            "models": [_model_record(models_by_id[key]) for key in sorted(models_by_id)],
            "benchmarks": [_benchmark_record(benchmarks_by_id[key]) for key in sorted(benchmarks_by_id)],
            "sourceManifest": [
                source_manifest_by_key[key]
                for key in sorted(
                    source_manifest_by_key,
                    key=lambda item: _canonical_json(source_manifest_by_key[item]),
                )
            ],
            "scores": [_score_record(candidate) for candidate in selected],
            "excludedClaims": list(analysis.excluded_claims),
        }
        payload["manifest"]["contentSha256"] = official_feed_digest(payload)
        return validate_official_feed(payload)


def _require_exact_keys(value: object, expected: frozenset[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        raise FeedProjectionError(f"{label} has an invalid contract shape.")
    return value


def _require_sorted_unique_ids(rows: object, label: str) -> list[dict[str, Any]]:
    if not isinstance(rows, list):
        raise FeedProjectionError(f"{label} must be an array.")
    parsed: list[dict[str, Any]] = []
    ids: list[str] = []
    for row in rows:
        item = _require_exact_keys(
            row,
            frozenset({"id", "canonicalName", "displayName", "provider", "modelFamily", "status"})
            if label == "models"
            else frozenset(
                {"id", "canonicalName", "displayName", "benchmarkFamily", "primaryMetric", "status"}
            ),
            f"{label} entry",
        )
        if not _is_nonempty_string(item.get("id")):
            raise FeedProjectionError(f"{label} contains an invalid id.")
        for key in ("canonicalName", "displayName", "status"):
            if not _is_nonempty_string(item.get(key)):
                raise FeedProjectionError(f"{label} contains incomplete display metadata.")
        nullable_keys = ("provider", "modelFamily") if label == "models" else (
            "benchmarkFamily",
            "primaryMetric",
        )
        if any(item[key] is not None and not isinstance(item[key], str) for key in nullable_keys):
            raise FeedProjectionError(f"{label} contains invalid optional display metadata.")
        ids.append(item["id"])
        parsed.append(item)
    if ids != sorted(ids) or len(set(ids)) != len(ids):
        raise FeedProjectionError(f"{label} must be sorted and have unique ids.")
    return parsed


def validate_official_feed(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the candidate contract and its deterministic digest.

    The validator is intentionally local and dependency-free so CI can check
    fixtures offline.  It verifies semantic requirements that JSON Schema
    alone cannot express: canonical order, unique cells, provenance links,
    finite values, and the self-hash.
    """
    document = _require_exact_keys(dict(payload), _TOP_LEVEL_KEYS, "Official feed")
    if document["schemaVersion"] != OFFICIAL_FEED_SCHEMA_VERSION:
        raise FeedProjectionError("Official feed has an unsupported schema version.")
    if document["policyVersion"] != OFFICIAL_FEED_POLICY_VERSION:
        raise FeedProjectionError("Official feed has an unsupported policy version.")
    if document["availability"] != OFFICIAL_FEED_AVAILABILITY:
        raise FeedProjectionError("Candidate projection cannot claim published availability.")

    manifest = _require_exact_keys(document["manifest"], _MANIFEST_KEYS, "Official feed manifest")
    if manifest["algorithm"] != CANONICAL_JSON_ALGORITHM:
        raise FeedProjectionError("Official feed manifest uses an unsupported digest algorithm.")
    if not _is_nonempty_string(manifest["contentSha256"]) or _HEX_SHA256.fullmatch(manifest["contentSha256"]) is None:
        raise FeedProjectionError("Official feed manifest has an invalid content digest.")
    if any(not isinstance(manifest[key], int) or isinstance(manifest[key], bool) or manifest[key] < 0 for key in (
        "scoreCount", "modelCount", "benchmarkCount", "sourceSnapshotCount"
    )):
        raise FeedProjectionError("Official feed manifest has invalid count fields.")

    model_rows = _require_sorted_unique_ids(document["models"], "models")
    benchmark_rows = _require_sorted_unique_ids(document["benchmarks"], "benchmarks")
    model_ids = {row["id"] for row in model_rows}
    benchmark_ids = {row["id"] for row in benchmark_rows}

    source_manifest = document["sourceManifest"]
    if not isinstance(source_manifest, list):
        raise FeedProjectionError("Official feed sourceManifest must be an array.")
    source_keys: list[str] = []
    source_by_key: dict[str, dict[str, Any]] = {}
    source_expected = frozenset(
        {
            "sourceManifestKey",
            "officialSourceId",
            "sourceRevisionId",
            "sourceRevisionDecisionId",
            "sourceName",
            "sourceUrl",
            "sourceType",
            "sourceRevisionDefinitionSha256",
            "sourceSnapshotId",
            "snapshotContentSha256",
            "snapshotCapturedAt",
        }
    )
    for source in source_manifest:
        row = _require_exact_keys(source, source_expected, "Official feed source manifest entry")
        for key in source_expected:
            if not _is_nonempty_string(row.get(key)):
                raise FeedProjectionError("Official feed source manifest has incomplete provenance.")
        if (
            _HEX_SHA256.fullmatch(row["sourceRevisionDefinitionSha256"]) is None
            or _HEX_SHA256.fullmatch(row["snapshotContentSha256"]) is None
        ):
            raise FeedProjectionError("Official feed source manifest has an invalid SHA-256 value.")
        source_keys.append(row["sourceManifestKey"])
        source_by_key[row["sourceManifestKey"]] = row
    source_sort_keys = [_canonical_json(source) for source in source_manifest]
    if source_sort_keys != sorted(source_sort_keys) or len(set(source_keys)) != len(source_keys):
        raise FeedProjectionError("Official feed sourceManifest must be sorted and unique.")

    scores = document["scores"]
    if not isinstance(scores, list):
        raise FeedProjectionError("Official feed scores must be an array.")
    score_expected = frozenset(
        {
            "cell",
            "claimId",
            "value",
            "scoreRaw",
            "scoreUnit",
            "evidenceText",
            "evidenceLocation",
            "provenance",
        }
    )
    score_cells: list[str] = []
    score_claim_ids: set[str] = set()
    for score in scores:
        row = _require_exact_keys(score, score_expected, "Official feed score")
        cell = _require_exact_keys(row["cell"], _CELL_KEYS, "Official feed score cell")
        if not _is_nonempty_string(cell.get("modelId")) or not _is_nonempty_string(cell.get("benchmarkId")):
            raise FeedProjectionError("Official feed score has an unresolved display identity.")
        if cell["modelId"] not in model_ids or cell["benchmarkId"] not in benchmark_ids:
            raise FeedProjectionError("Official feed score references absent display metadata.")
        if any(cell[key] is not None and not isinstance(cell[key], str) for key in (
            "metric", "split", "setting", "evaluationVersion"
        )):
            raise FeedProjectionError("Official feed score has invalid display dimensions.")
        if not _is_nonempty_string(row.get("claimId")) or not _is_finite_number(row.get("value")):
            raise FeedProjectionError("Official feed score is missing a finite selected value.")
        if row["claimId"] in score_claim_ids:
            raise FeedProjectionError("Official feed scores must not repeat a claim id.")
        score_claim_ids.add(row["claimId"])
        if not _is_nonempty_string(row.get("scoreRaw")):
            raise FeedProjectionError("Official feed score is missing its raw score lexeme.")
        if row["scoreUnit"] is not None and not isinstance(row["scoreUnit"], str):
            raise FeedProjectionError("Official feed score has an invalid score unit.")
        if row["evidenceText"] is not None and not isinstance(row["evidenceText"], str):
            raise FeedProjectionError("Official feed score has invalid evidence text.")
        if not isinstance(row["evidenceLocation"], dict) or not _is_nonempty_string(
            row["evidenceLocation"].get("type")
        ):
            raise FeedProjectionError("Official feed score has incomplete evidence location.")
        provenance = _require_exact_keys(
            row["provenance"],
            frozenset(
                {
                    "sourceManifestKey",
                    "officialSourceId",
                    "sourceRevisionId",
                    "sourceRevisionDecisionId",
                    "sourceName",
                    "sourceUrl",
                    "sourceType",
                    "sourceRevisionDefinitionSha256",
                    "sourceSnapshotId",
                    "snapshotContentSha256",
                    "snapshotCapturedAt",
                    "claimReviewDecisionId",
                    "claimPublicationDecisionId",
                    "captureMethod",
                }
            ),
            "Official feed score provenance",
        )
        if provenance["sourceManifestKey"] not in source_keys:
            raise FeedProjectionError("Official feed score references an absent source manifest entry.")
        for key, value in provenance.items():
            if not _is_nonempty_string(value):
                raise FeedProjectionError("Official feed score has incomplete provenance.")
        source = source_by_key[provenance["sourceManifestKey"]]
        for key in source_expected:
            if provenance[key] != source[key]:
                raise FeedProjectionError(
                    "Official feed score provenance does not match its source manifest entry."
                )
        score_cells.append(_cell_sort_key(cell))
    if score_cells != sorted(score_cells) or len(set(score_cells)) != len(score_cells):
        raise FeedProjectionError("Official feed scores must be sorted and unique by display cell.")

    excluded = document["excludedClaims"]
    if not isinstance(excluded, list):
        raise FeedProjectionError("Official feed excludedClaims must be an array.")
    excluded_keys: list[tuple[str, str]] = []
    excluded_claim_ids: set[str] = set()
    for row in excluded:
        parsed = _require_exact_keys(row, frozenset({"claimId", "reasonCode"}), "Excluded claim")
        if not _is_nonempty_string(parsed.get("claimId")) or not _is_nonempty_string(parsed.get("reasonCode")):
            raise FeedProjectionError("Official feed excludedClaims has an invalid row.")
        if parsed["claimId"] in excluded_claim_ids:
            raise FeedProjectionError("Official feed excludedClaims must not repeat a claim id.")
        excluded_claim_ids.add(parsed["claimId"])
        excluded_keys.append((parsed["claimId"], parsed["reasonCode"]))
    if excluded_keys != sorted(excluded_keys) or len(set(excluded_keys)) != len(excluded_keys):
        raise FeedProjectionError("Official feed excludedClaims must be sorted and unique.")
    if score_claim_ids & excluded_claim_ids:
        raise FeedProjectionError("Official feed cannot both select and exclude one claim.")

    if manifest["scoreCount"] != len(scores):
        raise FeedProjectionError("Official feed manifest score count does not match scores.")
    if manifest["modelCount"] != len(model_rows) or manifest["benchmarkCount"] != len(benchmark_rows):
        raise FeedProjectionError("Official feed manifest metadata counts do not match.")
    if manifest["sourceSnapshotCount"] != len(source_manifest):
        raise FeedProjectionError("Official feed manifest source count does not match.")
    if manifest["contentSha256"] != official_feed_digest(document):
        raise FeedProjectionError("Official feed manifest digest does not match canonical content.")
    return document


def export_official_json(session: Session, out_path: Path) -> dict[str, Any]:
    """Refuse the unsafe legacy projection during Official-mode containment.

    The internal candidate projection above is deliberately not an output-path
    API.  A later FEED/release task must add an immutable artifact owner and
    explicit publication gate before this public command is enabled.
    """

    del session, out_path
    raise OfficialPublicationDisabledError(
        "Official export is disabled until the governed release-artifact gate is implemented."
    )
