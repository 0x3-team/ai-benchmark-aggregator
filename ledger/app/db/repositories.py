from __future__ import annotations

import base64
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any
from uuid import UUID

from sqlalchemy import String, cast, func, select, tuple_
from sqlalchemy.orm import Session

from app.db import models
from app.schemas.boundary import ClaimValidationInput, ResultClaimInput


class SourceRevisionRequiredError(ValueError):
    """A source-revision or logical-source identity invariant was violated."""


class ClaimReviewChainError(ValueError):
    """A claim review history cannot be resolved to one safe effective leaf."""


class ReviewWorkflowUnavailableError(ValueError):
    """A retired mutable review helper was called during containment."""


@dataclass(frozen=True)
class SourceReconciliation:
    source: models.OfficialSourceRow
    revision: models.OfficialSourceRevision
    disposition: str
    revision_created: bool


@dataclass(frozen=True)
class ClaimReviewProjection:
    """Read-only effective display identity over a review-decision chain.

    Captured claim fields are immutable observations.  A reviewer can append a
    sparse correction for any display dimension, so readers must project the
    newest non-null review value without ever updating the captured row.
    """

    model_entity_id: str | None
    benchmark_id: str | None
    metric: str | None
    split: str | None
    setting: str | None
    evaluation_version: str | None
    effective_decision_id: str | None
    chain_error: str | None = None


@dataclass(frozen=True)
class ClaimPublicationProjection:
    """Read-only effective publication state over an append-only chain."""

    outcome: str | None
    claim_review_decision_id: str | None
    effective_decision_id: str | None
    chain_error: str | None = None


@dataclass(frozen=True)
class ReviewQueueItem:
    """A single review-queue entry with its already-computed projection.

    Carrying the projection here means CLI/page rendering performs no per-row
    repository query: resolving the projection is purely in-memory.
    """

    claim: models.ResultClaim
    projection: ClaimReviewProjection


@dataclass(frozen=True)
class ReviewQueuePage:
    """One bounded review-queue page with explicit cursor/metadata.

    ``next_cursor`` is the opaque-but-caller-visible continuation token; pass
    it back as ``cursor`` to fetch the following page.  ``exhausted`` is true
    only when the claims table is fully consumed (no further rows at all), so a
    caller can render an explicit end-of-queue.  ``scanned`` is the number of
    ``ResultClaim`` rows read within this page's single bounded SQL window.
    """

    items: list[ReviewQueueItem]
    next_cursor: str | None
    exhausted: bool
    scanned: int
    projected: int = 0


_SOURCE_DEFINITION_FIELDS = (
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


def _canonical_json(value: dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)


def _source_definition_from_mapping(data: dict[str, Any], *, fallback: models.OfficialSourceRow | None = None) -> dict[str, Any]:
    definition: dict[str, Any] = {}
    for field in _SOURCE_DEFINITION_FIELDS:
        if field in data:
            value = data[field]
        elif fallback is not None:
            value = getattr(fallback, field)
        elif field == "parser_config":
            value = {}
        elif field in {"machine_readable", "requires_auth", "supports_history"}:
            value = False
        elif field == "status":
            value = "active"
        else:
            value = None
        if field == "parser_config":
            definition[field] = value or {}
        elif field in {"machine_readable", "requires_auth", "supports_history"}:
            definition[field] = bool(value)
        else:
            definition[field] = value
    return definition


def _source_definition_from_row(row: models.OfficialSourceRow) -> dict[str, Any]:
    return _source_definition_from_mapping({}, fallback=row)


def _definition_hash(definition: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(definition).encode("utf-8")).hexdigest()


def upsert_benchmark(session: Session, data: dict[str, Any]) -> models.Benchmark:
    """Upsert one benchmark, preserving the public per-row identity-get contract.

    Single-row callers keep the exact prior behavior (one identity ``get`` +
    ``flush``).  The registry seed path uses the batched :func:`_upsert_many`
    seam instead so it preloads rows in a constant number of SELECTs.
    """
    row = session.get(models.Benchmark, data["id"])
    if row is None:
        row = models.Benchmark(**{k: v for k, v in data.items() if hasattr(models.Benchmark, k)})
        session.add(row)
    else:
        for k, v in data.items():
            if hasattr(row, k) and k != "id":
                setattr(row, k, v)
    session.flush()
    return row


def _upsert_benchmark_from_map(
    session: Session, data: dict[str, Any], existing: dict[str, models.Benchmark]
) -> models.Benchmark:
    """Identity-get-free upsert backed by a preloaded ``{id: row}`` map.

    New rows are merely ``session.add``ed (no per-row ``flush``); the caller
    flushes once after the whole benchmark group so the number of flush/insert
    statements is constant, not proportional to row count.  Public
    :func:`upsert_benchmark` is unchanged for single-row callers.
    """
    row = existing.get(data["id"])
    if row is None:
        row = models.Benchmark(**{k: v for k, v in data.items() if hasattr(models.Benchmark, k)})
        session.add(row)
    else:
        for k, v in data.items():
            if hasattr(row, k) and k != "id":
                setattr(row, k, v)
    return row


def upsert_model_entity(session: Session, data: dict[str, Any]) -> models.ModelEntity:
    """Upsert one model_entity, preserving the public per-row identity contract."""
    row = session.get(models.ModelEntity, data["id"])
    if row is None:
        row = models.ModelEntity(**{k: v for k, v in data.items() if hasattr(models.ModelEntity, k)})
        session.add(row)
    else:
        for k, v in data.items():
            if hasattr(row, k) and k != "id":
                setattr(row, k, v)
    session.flush()
    return row


def _upsert_model_entity_from_map(
    session: Session, data: dict[str, Any], existing: dict[str, models.ModelEntity]
) -> models.ModelEntity:
    """Bulk counterpart of :func:`upsert_model_entity` using a preloaded map.

    New rows are merely ``session.add``ed (no per-row ``flush``); caller flushes
    once after the whole model group.
    """
    row = existing.get(data["id"])
    if row is None:
        row = models.ModelEntity(**{k: v for k, v in data.items() if hasattr(models.ModelEntity, k)})
        session.add(row)
    else:
        for k, v in data.items():
            if hasattr(row, k) and k != "id":
                setattr(row, k, v)
    return row


#: The only entity types an alias may target.  An alias row is a polymorphic
#: pointer with no database FK, so matching must not trust a dangling or
#: arbitrary ``entity_type``/``entity_id``.  We reject anything else before
#: ``insertion`` so a poisoned alias can never return a nonexistent identity.
_ALLOWED_ALIAS_ENTITY_TYPES = ("benchmark", "model_entity")


def _alias_entity_model(entity_type: str) -> type[models.Base]:
    if entity_type == "benchmark":
        return models.Benchmark
    if entity_type == "model_entity":
        return models.ModelEntity
    raise ValueError(
        f"Invalid alias entity_type {entity_type!r}; must be one of "
        f"{', '.join(_ALLOWED_ALIAS_ENTITY_TYPES)}"
    )


def add_alias(
    session: Session,
    *,
    entity_type: str,
    entity_id: str,
    alias_text: str,
    is_official_alias: bool = False,
    alias_source: str | None = None,
) -> models.Alias:
    # Fail closed before insertion: the polymorphic alias column has no FK, so a
    # caller-provided type/id must be valid and must reference an existing row.
    entity_model = _alias_entity_model(entity_type)
    if session.get(entity_model, entity_id) is None:
        raise ValueError(
            f"Cannot create alias for nonexistent {entity_type} {entity_id!r}."
        )
    existing = session.scalar(
        select(models.Alias).where(
            models.Alias.entity_type == entity_type,
            models.Alias.entity_id == entity_id,
            models.Alias.alias_text == alias_text,
        )
    )
    if existing:
        return existing
    row = models.Alias(
        entity_type=entity_type,
        entity_id=entity_id,
        alias_text=alias_text,
        is_official_alias=is_official_alias,
        alias_source=alias_source,
    )
    session.add(row)
    session.flush()
    return row


@dataclass(frozen=True)
class _AliasSeedRequest:
    entity_type: str
    entity_id: str
    alias_text: str
    is_official_alias: bool = False
    alias_source: str | None = None


#: Maximum tuple-IN elements per existing-alias lookup batch.  This keeps the
#: ``(...) IN ...`` parameter list small enough for both SQLite and PostgreSQL
#: variable limits (typically 999 for SQLite older versions, 32767 for PG) while
#: the number of SELECTs stays bounded and independent of the alias count: O(size
#: / batch).  A bounded-but-large registry (e.g. 50k aliases) uses ~102 lookups,
#: never a single unbounded tuple.
_ALIAS_LOOKUP_BATCH = 250


def add_aliases_bulk(
    session: Session,
    aliases: Sequence[_AliasSeedRequest],
    *,
    known_entity_ids: dict[str, set[str]] | None = None,
) -> int:
    """Bulk-insert missing aliases for seeding, preserving uniqueness semantics.

    This is the bounded bulk counterpart of :func:`add_alias` used only by the
    registry seed path: it loads the *current* ``(entity_type, entity_id,
    alias_text)`` rows in bounded chunks and inserts only the missing ones, so
    the number of ``SELECT`` statements grows sub-linearly (O(n/chunk)) and
    never exceeds SQLite/PostgreSQL parameter limits.  The public
    :func:`add_alias` API (per-alias look-and-insert) is unchanged.

    The unique constraint on ``(entity_type, entity_id, alias_text)`` is
    preserved: an already-present alias is skipped (idempotent), and a
    duplicate within ``aliases`` is inserted once because the missing set is
    deduplicated identically to how the constraint would reject it.

    Aliases carry a polymorphic ``entity_id`` with no database foreign key. A
    required ``known_target_ids`` mapping (``entity_type -> set of entity ids
    that exist this run``) lets the seed path fail closed on a dangling target
    without an extra per-alias SELECT, keeping the statement count constant for
    the constant-SELECT registry seed contract.  A caller that does not supply
    it degrades to an explicit in-loop ``session.get`` existence check so a
    dangling alias can never be inserted by any path.
    """
    if not aliases:
        return 0
    # Validate entity_type up front and, when the caller did not preload the
    # target id map, check each target exists (fail closed on dangling ids).
    known = known_entity_ids or {}
    for alias in aliases:
        model = _alias_entity_model(alias.entity_type)
        if alias.entity_type in known:
            if alias.entity_id not in known[alias.entity_type]:
                raise ValueError(
                    f"Cannot create alias for nonexistent {alias.entity_type} "
                    f"{alias.entity_id!r}."
                )
        elif session.get(model, alias.entity_id) is None:
            raise ValueError(
                f"Cannot create alias for nonexistent {alias.entity_type} "
                f"{alias.entity_id!r}."
            )
    # Load existing aliases only for the target entity ids/types in bounded
    # chunks, accumulating an in-memory key set; in-memory filtering below
    # decides insert (no per-alias SELECT).
    existing_pairs: set[tuple[str, str, str]] = set()
    for i in range(0, len(aliases), _ALIAS_LOOKUP_BATCH):
        chunk = aliases[i : i + _ALIAS_LOOKUP_BATCH]
        keys = [(a.entity_type, a.entity_id, a.alias_text) for a in chunk]
        rows = session.scalars(
            select(models.Alias).where(
                tuple_(models.Alias.entity_type, models.Alias.entity_id, models.Alias.alias_text).in_(
                    keys
                )
            )
        )
        existing_pairs.update((a.entity_type, a.entity_id, a.alias_text) for a in rows)
    seen: set[tuple[str, str, str]] = set()
    inserted = 0
    for alias in aliases:
        key = (alias.entity_type, alias.entity_id, alias.alias_text)
        if key in existing_pairs or key in seen:
            continue
        seen.add(key)
        session.add(
            models.Alias(
                entity_type=alias.entity_type,
                entity_id=alias.entity_id,
                alias_text=alias.alias_text,
                is_official_alias=alias.is_official_alias,
                alias_source=alias.alias_source,
            )
        )
        inserted += 1
    session.flush()
    return inserted


_SOURCE_PROJECTION_FIELDS = tuple(field for field in _SOURCE_DEFINITION_FIELDS if field != "benchmark_id")


def _source_definition_from_revision(revision: models.OfficialSourceRevision) -> dict[str, Any]:
    raw_definition = revision.definition_json
    if not isinstance(raw_definition, dict):
        raise SourceRevisionRequiredError(
            f"Source revision {revision.id!r} does not contain a valid immutable definition."
        )
    return _source_definition_from_mapping(raw_definition)


def _source_projection_data(definition: dict[str, Any]) -> dict[str, Any]:
    return {field: definition[field] for field in _SOURCE_PROJECTION_FIELDS}


def _assert_source_identity_available(
    session: Session,
    *,
    source_id: str,
    benchmark_id: str | None,
    source_url: str,
) -> None:
    same_url_row = session.scalar(
        select(models.OfficialSourceRow).where(
            models.OfficialSourceRow.benchmark_id == benchmark_id,
            models.OfficialSourceRow.source_url == source_url,
            models.OfficialSourceRow.id != source_id,
        )
    )
    if same_url_row is not None:
        raise ValueError(
            "Refusing to remap an existing logical source identity: "
            f"{same_url_row.id!r} already owns benchmark URL {source_url!r}."
        )


def _create_source_revision(
    session: Session,
    *,
    source: models.OfficialSourceRow,
    definition: dict[str, Any],
    origin: str,
) -> models.OfficialSourceRevision:
    # PostgreSQL must serialize ordinal allocation per logical source. The
    # unique (source, ordinal) constraint remains the final guard, but a
    # MAX(...)+1 read by itself permits two concurrent transactions to choose
    # the same ordinal. SQLite ignores FOR UPDATE and retains its existing
    # single-writer behavior.
    locked_source = session.scalar(
        select(models.OfficialSourceRow)
        .where(models.OfficialSourceRow.id == source.id)
        .with_for_update()
    )
    if locked_source is None:
        raise SourceRevisionRequiredError(
            f"Logical source {source.id!r} disappeared before revision allocation."
        )
    source = locked_source
    definition = _source_definition_from_mapping(definition)
    if source.benchmark_id != definition["benchmark_id"]:
        raise SourceRevisionRequiredError(
            f"Source revision for {source.id!r} cannot change the logical benchmark identity."
        )
    definition_hash = _definition_hash(definition)
    ordinal = (
        session.scalar(
            select(func.max(models.OfficialSourceRevision.revision_ordinal)).where(
                models.OfficialSourceRevision.official_source_id == source.id
            )
        )
        or 0
    ) + 1
    previous_revision_id = source.current_revision_id
    revision = models.OfficialSourceRevision(
        official_source_id=source.id,
        revision_ordinal=ordinal,
        definition_hash=definition_hash,
        definition_json=definition,
        source_name=definition["source_name"],
        source_url=definition["source_url"],
        source_type=definition["source_type"],
        officialness_level=definition["officialness_level"],
        machine_readable=definition["machine_readable"],
        requires_auth=definition["requires_auth"],
        supports_history=definition["supports_history"],
        update_cadence=definition["update_cadence"],
        parser_name=definition["parser_name"],
        parser_version=definition["parser_version"],
        parser_config=definition["parser_config"],
        status=definition["status"],
        notes=definition["notes"],
        origin=origin,
        supersedes_revision_id=previous_revision_id,
    )
    session.add(revision)
    session.flush()
    return revision


def _apply_current_source_projection(
    session: Session,
    *,
    source: models.OfficialSourceRow,
    revision: models.OfficialSourceRevision,
    registry_managed: bool | None = None,
) -> None:
    # Assign directly from the immutable row so the SQLite trigger can prove
    # the mutable catalog projection is exactly the selected revision.
    for field in _SOURCE_PROJECTION_FIELDS:
        setattr(source, field, getattr(revision, field))
    source.current_revision_id = revision.id
    if registry_managed is not None:
        source.registry_managed = registry_managed
    session.flush()


def _append_reconciliation_decision(
    session: Session,
    *,
    revision: models.OfficialSourceRevision,
    outcome: str,
    reason_code: str,
    actor: str,
    basis_json: dict[str, Any],
) -> models.SourceRevisionDecision:
    return append_source_revision_decision(
        session,
        source_revision_id=revision.id,
        outcome=outcome,
        policy_version="registry-reconciliation-v1",
        reason_code=reason_code,
        basis_json=basis_json,
        actor=actor,
    )


def _reconcile_official_source(
    session: Session,
    data: dict[str, Any],
    *,
    registry_managed: bool = False,
) -> SourceReconciliation:
    """Idempotently reconcile one logical source through immutable revisions."""
    if not data.get("id"):
        raise ValueError("Official source reconciliation requires a stable source id.")
    source_id = str(data["id"])
    # Lock before deriving the proposed fallback/current revision so two
    # PostgreSQL reconcilers cannot both reason from the same stale projection.
    # SQLite compiles this as its existing ordinary SELECT under the
    # single-writer transaction model.
    source = session.scalar(
        select(models.OfficialSourceRow)
        .where(models.OfficialSourceRow.id == source_id)
        .with_for_update()
    )
    proposed = _source_definition_from_mapping(data, fallback=source)

    if source is None:
        _assert_source_identity_available(
            session,
            source_id=source_id,
            benchmark_id=proposed["benchmark_id"],
            source_url=proposed["source_url"],
        )
        source = models.OfficialSourceRow(
            id=source_id,
            benchmark_id=proposed["benchmark_id"],
            registry_managed=registry_managed,
            **_source_projection_data(proposed),
        )
        session.add(source)
        session.flush()
        revision = _create_source_revision(
            session,
            source=source,
            definition=proposed,
            origin="registry_seed" if registry_managed else "manual_seed",
        )
        _append_reconciliation_decision(
            session,
            revision=revision,
            outcome="quarantined",
            reason_code="uncertified_source_revision",
            actor="registry_seed" if registry_managed else "manual_seed",
            basis_json={
                "assessment": "A new source revision is quarantined until governed certification.",
                "definition_hash": revision.definition_hash,
            },
        )
        _apply_current_source_projection(
            session,
            source=source,
            revision=revision,
            registry_managed=registry_managed,
        )
        return SourceReconciliation(source, revision, "created", True)

    if source.benchmark_id != proposed["benchmark_id"]:
        raise SourceRevisionRequiredError(
            f"Logical source {source.id!r} cannot change benchmark identity; create a new source id."
        )
    _assert_source_identity_available(
        session,
        source_id=source.id,
        benchmark_id=proposed["benchmark_id"],
        source_url=proposed["source_url"],
    )
    current = get_current_source_revision(session, source.id)
    proposed_hash = _definition_hash(proposed)
    if current.definition_hash == proposed_hash:
        if registry_managed and not source.registry_managed:
            source.registry_managed = True
            session.flush()
        return SourceReconciliation(source, current, "unchanged", False)

    matching_revision = _create_source_revision(
        session,
        source=source,
        definition=proposed,
        origin="registry_update" if registry_managed else "manual_update",
    )
    reason_code = "source_reintroduced" if current.status == "retired" else "registry_definition_changed"
    _append_reconciliation_decision(
        session,
        revision=matching_revision,
        outcome="quarantined",
        reason_code=reason_code,
        actor="registry_seed" if registry_managed else "manual_seed",
        basis_json={
            "previous_revision_id": current.id,
            "definition_hash": matching_revision.definition_hash,
        },
    )
    _apply_current_source_projection(
        session,
        source=source,
        revision=matching_revision,
        registry_managed=True if registry_managed else None,
    )
    disposition = "reactivated" if current.status == "retired" else "revised"
    return SourceReconciliation(source, matching_revision, disposition, True)


def reconcile_official_source(
    session: Session,
    data: dict[str, Any],
    *,
    registry_managed: bool = False,
) -> SourceReconciliation:
    """Idempotently reconcile one logical source through immutable revisions.

    A savepoint makes a failed source transition self-contained for callers
    that choose to recover and continue using an outer session. Registry-wide
    callers additionally wrap the complete manifest in their own savepoint.
    """
    with session.begin_nested():
        return _reconcile_official_source(
            session,
            data,
            registry_managed=registry_managed,
        )


def upsert_official_source(session: Session, data: dict[str, Any]) -> models.OfficialSourceRow:
    """Compatibility wrapper for non-registry callers.

    The result is always reconciled through an immutable revision; it never
    mutates a source definition in place.
    """
    return reconcile_official_source(session, data).source


def _retire_registry_sources_not_in(
    session: Session,
    *,
    source_ids: set[str],
) -> list[SourceReconciliation]:
    """Append a revoked retirement revision for missing registry-managed sources."""
    retired: list[SourceReconciliation] = []
    sources = list(
        session.scalars(
            select(models.OfficialSourceRow).where(models.OfficialSourceRow.registry_managed.is_(True))
        )
    )
    for source in sources:
        if source.id in source_ids:
            continue
        current = get_current_source_revision(session, source.id)
        if current.status == "retired":
            continue
        definition = _source_definition_from_revision(current)
        definition["status"] = "retired"
        retirement = _create_source_revision(
            session,
            source=source,
            definition=definition,
            origin="registry_retirement",
        )
        _append_reconciliation_decision(
            session,
            revision=retirement,
            outcome="revoked",
            reason_code="removed_from_registry",
            actor="registry_seed",
            basis_json={
                "previous_revision_id": current.id,
                "removed_source_id": source.id,
            },
        )
        _apply_current_source_projection(session, source=source, revision=retirement)
        retired.append(SourceReconciliation(source, retirement, "retired", True))
    return retired


def retire_registry_sources_not_in(
    session: Session,
    *,
    source_ids: set[str],
) -> list[SourceReconciliation]:
    """Append revoked retirement revisions for missing managed sources atomically."""
    with session.begin_nested():
        return _retire_registry_sources_not_in(session, source_ids=source_ids)


def ensure_initial_source_revision(
    session: Session,
    source: models.OfficialSourceRow,
) -> models.OfficialSourceRevision:
    """Compatibility guard for old callers that supplied a source without a revision."""
    if source.current_revision_id:
        return get_current_source_revision(session, source.id)
    definition = _source_definition_from_row(source)
    revision = _create_source_revision(
        session,
        source=source,
        definition=definition,
        origin="legacy_reconciliation",
    )
    _append_reconciliation_decision(
        session,
        revision=revision,
        outcome="quarantined",
        reason_code="source_revision_missing",
        actor="migration_guard",
        basis_json={"definition_hash": revision.definition_hash},
    )
    _apply_current_source_projection(session, source=source, revision=revision)
    return revision


def get_current_source_revision(
    session: Session, official_source_id: str
) -> models.OfficialSourceRevision:
    source = session.get(models.OfficialSourceRow, official_source_id)
    if source is None or not source.current_revision_id:
        raise SourceRevisionRequiredError(
            f"Source {official_source_id!r} has no current immutable source revision."
        )
    revision = session.get(models.OfficialSourceRevision, source.current_revision_id)
    if revision is None or revision.official_source_id != official_source_id:
        raise SourceRevisionRequiredError(
            f"Source {official_source_id!r} has an invalid immutable source revision pointer."
        )
    return revision


def find_snapshot(
    session: Session, official_source_id: str, content_hash: str, *, source_revision_id: str
) -> models.SourceSnapshot | None:
    return session.scalar(
        select(models.SourceSnapshot).where(
            models.SourceSnapshot.official_source_id == official_source_id,
            models.SourceSnapshot.source_revision_id == source_revision_id,
            models.SourceSnapshot.content_hash == content_hash,
        )
    )


def insert_snapshot_if_new(
    session: Session,
    *,
    official_source_id: str,
    source_revision_id: str,
    raw_content_uri: str,
    content_hash: str,
    content_type: str | None,
    http_status: int | None,
    etag: str | None,
    last_modified_header: str | None,
    fetch_metadata: dict[str, Any],
    parser_version: str | None = None,
) -> tuple[models.SourceSnapshot, bool]:
    revision = get_current_source_revision(session, official_source_id)
    if revision.id != source_revision_id:
        raise SourceRevisionRequiredError(
            f"Snapshot source revision {source_revision_id!r} is not current for {official_source_id!r}."
        )
    existing = find_snapshot(
        session, official_source_id, content_hash, source_revision_id=source_revision_id
    )
    if existing:
        return existing, False
    row = models.SourceSnapshot(
        official_source_id=official_source_id,
        source_revision_id=source_revision_id,
        raw_content_uri=raw_content_uri,
        content_hash=content_hash,
        content_type=content_type,
        http_status=http_status,
        etag=etag,
        last_modified_header=last_modified_header,
        fetch_metadata=fetch_metadata or {},
        parser_version=parser_version,
    )
    session.add(row)
    session.flush()
    return row, True


def insert_snapshot(
    session: Session,
    *,
    official_source_id: str,
    source_revision_id: str,
    raw_content_uri: str,
    content_hash: str,
    content_type: str | None,
    http_status: int | None,
    etag: str | None,
    last_modified_header: str | None,
    fetch_metadata: dict[str, Any],
    parser_version: str | None = None,
) -> models.SourceSnapshot:
    """Compatibility wrapper for callers that only need the snapshot row."""
    row, _ = insert_snapshot_if_new(
        session,
        official_source_id=official_source_id,
        source_revision_id=source_revision_id,
        raw_content_uri=raw_content_uri,
        content_hash=content_hash,
        content_type=content_type,
        http_status=http_status,
        etag=etag,
        last_modified_header=last_modified_header,
        fetch_metadata=fetch_metadata,
        parser_version=parser_version,
    )
    return row


def find_claim(
    session: Session, source_snapshot_id: str, claim_fingerprint: str
) -> models.ResultClaim | None:
    return session.scalar(
        select(models.ResultClaim).where(
            models.ResultClaim.source_snapshot_id == source_snapshot_id,
            models.ResultClaim.claim_fingerprint == claim_fingerprint,
        )
    )


def insert_claim_if_new(session: Session, claim: ResultClaimInput) -> tuple[models.ResultClaim, bool]:
    assert claim.source_snapshot_id is not None
    assert claim.claim_fingerprint is not None
    snap_id = str(claim.source_snapshot_id)
    existing = find_claim(session, snap_id, claim.claim_fingerprint)
    if existing:
        return existing, False
    row = models.ResultClaim(
        source_snapshot_id=snap_id,
        source_revision_decision_id=(
            str(claim.source_revision_decision_id) if claim.source_revision_decision_id else None
        ),
        official_source_id=claim.official_source_id,
        benchmark_id=claim.benchmark_id,
        model_entity_id=claim.model_entity_id,
        model_raw=claim.model_raw,
        benchmark_raw=claim.benchmark_raw,
        score_raw=claim.score_raw,
        metric_raw=claim.metric_raw,
        split_raw=claim.split_raw,
        setting_raw=claim.setting_raw,
        evaluation_version_raw=claim.evaluation_version_raw,
        rank_raw=claim.rank_raw,
        date_raw=claim.date_raw,
        score_numeric=claim.score_numeric,
        score_unit=claim.score_unit,
        evidence_text=claim.evidence_text,
        evidence_location=claim.evidence_location or {},
        capture_method=claim.capture_method,
        capture_confidence=claim.capture_confidence,
        capture_status=claim.capture_status,
        scientific_status=claim.scientific_status,
        officialness_level=claim.officialness_level,
        claim_fingerprint=claim.claim_fingerprint,
    )
    session.add(row)
    session.flush()
    return row, True


def insert_validations(
    session: Session, claim_id: str, validations: list[ClaimValidationInput]
) -> None:
    for v in validations:
        session.add(
            models.ClaimValidation(
                result_claim_id=claim_id,
                validation_type=v.validation_type,
                outcome=v.outcome,
                validator=v.validator,
                notes=v.notes,
            )
        )
    session.flush()


def append_source_revision_decision(
    session: Session,
    *,
    source_revision_id: str,
    outcome: str,
    policy_version: str,
    reason_code: str,
    basis_json: dict[str, Any] | None = None,
    actor: str | None = None,
    supersedes_decision_id: str | None = None,
) -> models.SourceRevisionDecision:
    if session.get(models.OfficialSourceRevision, source_revision_id) is None:
        raise ValueError(f"Unknown source revision: {source_revision_id}")
    if outcome not in {"quarantined", "revoked"}:
        raise ValueError(
            "Source certification is unavailable during containment; only quarantined or revoked "
            "source-revision decisions may be appended until the governed certification workflow lands."
        )
    row = models.SourceRevisionDecision(
        source_revision_id=source_revision_id,
        outcome=outcome,
        policy_version=policy_version,
        reason_code=reason_code,
        basis_json=basis_json or {},
        actor=actor,
        supersedes_decision_id=supersedes_decision_id,
    )
    session.add(row)
    session.flush()
    return row


def _resolve_review_chain(
    result_claim_id: str, decisions: Sequence[models.ClaimReviewDecision]
) -> list[models.ClaimReviewDecision]:
    """Pure, fail-closed resolution of one effective review chain from a grouped set.

    ``decisions`` must already be filtered to ``result_claim_id`` (the single
    grouped IN query in :func:`_load_review_chains`).  A branch, a foreign
    parent, or a cycle has no deterministic effective state and must remain
    fail-closed rather than being picked by timestamp or insertion order.
    """
    if not decisions:
        return []

    by_id = {decision.id: decision for decision in decisions}
    superseded: set[str] = set()
    for decision in decisions:
        parent_id = decision.supersedes_decision_id
        if parent_id is None:
            continue
        parent = by_id.get(parent_id)
        if parent is None or parent.result_claim_id != result_claim_id:
            raise ClaimReviewChainError(
                f"Claim {result_claim_id} has a review decision with an invalid parent."
            )
        superseded.add(parent_id)

    leaves = [decision for decision in decisions if decision.id not in superseded]
    if len(leaves) != 1:
        raise ClaimReviewChainError(
            f"Claim {result_claim_id} has {len(leaves)} effective review decisions; manual resolution is blocked."
        )

    chain: list[models.ClaimReviewDecision] = []
    visited: set[str] = set()
    current: models.ClaimReviewDecision | None = leaves[0]
    while current is not None:
        if current.id in visited:
            raise ClaimReviewChainError(f"Claim {result_claim_id} has a cyclic review-decision chain.")
        visited.add(current.id)
        chain.append(current)
        current = by_id.get(current.supersedes_decision_id) if current.supersedes_decision_id else None
    return chain


def _load_review_decisions(
    session: Session, result_claim_ids: Sequence[str]
) -> dict[str, list[models.ClaimReviewDecision]]:
    """Group-load review decisions for a bounded claim window in one IN query.

    Returns ``{claim_id: [decisions]}`` preserving the existing fail-closed
    semantics: the bag of decisions for each claim is handed to the pure
    :func:`_resolve_review_chain` per claim.  Missing keys are absent from the
    map and resolve to an empty chain (sparse projection fallback).
    """
    grouped: dict[str, list[models.ClaimReviewDecision]] = {}
    if not result_claim_ids:
        return grouped
    rows = session.scalars(
        select(models.ClaimReviewDecision).where(
            models.ClaimReviewDecision.result_claim_id.in_(list(result_claim_ids))
        )
    )
    for decision in rows:
        grouped.setdefault(decision.result_claim_id, []).append(decision)
    return grouped


def _claim_review_chain(
    session: Session, result_claim_id: str
) -> list[models.ClaimReviewDecision]:
    """Return the one effective review chain, ordered leaf to root.

    Review decisions are evidence, not a mutable status field.  A branch, a
    foreign parent, or a cycle has no deterministic effective state and must
    remain fail-closed rather than being picked by timestamp or insertion
    order.
    """
    decisions = list(
        session.scalars(
            select(models.ClaimReviewDecision).where(
                models.ClaimReviewDecision.result_claim_id == result_claim_id
            )
        )
    )
    return _resolve_review_chain(result_claim_id, decisions)


def get_effective_claim_review_decision(
    session: Session, result_claim_id: str
) -> models.ClaimReviewDecision | None:
    """Return the sole effective decision, or fail closed on an invalid chain."""
    chain = _claim_review_chain(session, result_claim_id)
    return chain[0] if chain else None


def get_claim_review_projection(session: Session, claim: models.ResultClaim) -> ClaimReviewProjection:
    """Resolve reviewed display dimensions without rewriting the captured claim.

    Fail-closed, public contract: an unresolvable review chain yields a
    ``chain_error`` projection (never a raise), so a caller rendering a queue
    page or inventory report cannot crash on a corrupt chain and the invalid
    state is preserved and surfaced rather than silently dropped.
    """
    try:
        chain = _claim_review_chain(session, claim.id)
    except ClaimReviewChainError as exc:
        return _project_review(claim, [], chain_error=str(exc))
    return _project_review(claim, chain)


def _project_review(
    claim: models.ResultClaim,
    chain: list[models.ClaimReviewDecision],
    chain_error: str | None = None,
) -> ClaimReviewProjection:
    """Pure projection of display identity over an already-resolved chain."""
    if chain_error is not None:
        return ClaimReviewProjection(
            model_entity_id=None,
            benchmark_id=None,
            metric=None,
            split=None,
            setting=None,
            evaluation_version=None,
            effective_decision_id=None,
            chain_error=chain_error,
        )

    # Identity decisions are sparse: later validation/quarantine decisions do
    # not erase an earlier resolved identity merely because their model field
    # is null.  The captured admission mapping remains the fallback when no
    # review decision has supplied a correction.
    reviewed_model = next(
        (decision.model_entity_id for decision in chain if decision.model_entity_id is not None),
        claim.model_entity_id,
    )
    reviewed_benchmark = next(
        (decision.benchmark_id for decision in chain if decision.benchmark_id is not None),
        claim.benchmark_id,
    )
    reviewed_metric = next(
        (decision.metric for decision in chain if decision.metric is not None), claim.metric_raw
    )
    reviewed_split = next((decision.split for decision in chain if decision.split is not None), claim.split_raw)
    reviewed_setting = next(
        (decision.setting for decision in chain if decision.setting is not None), claim.setting_raw
    )
    reviewed_evaluation_version = next(
        (decision.evaluation_version for decision in chain if decision.evaluation_version is not None),
        claim.evaluation_version_raw,
    )
    return ClaimReviewProjection(
        model_entity_id=reviewed_model,
        benchmark_id=reviewed_benchmark,
        metric=reviewed_metric,
        split=reviewed_split,
        setting=reviewed_setting,
        evaluation_version=reviewed_evaluation_version,
        effective_decision_id=chain[0].id if chain else None,
    )


def _resolve_publication_chain(
    result_claim_id: str, decisions: Sequence[models.ClaimPublicationDecision]
) -> list[models.ClaimPublicationDecision]:
    """Pure, fail-closed resolution of one effective publication chain.

    Mirrors :func:`_resolve_review_chain`.  ``decisions`` must already be
    filtered to ``result_claim_id``.  Publication history follows the same
    fail-closed semantics as review history: a branching or non-leaf chain has
    no safe current state, so callers receive an explicit error rather than a
    timestamp-derived answer.
    """
    if not decisions:
        return []

    by_id = {decision.id: decision for decision in decisions}
    superseded: set[str] = set()
    for decision in decisions:
        parent_id = decision.supersedes_decision_id
        if parent_id is None:
            continue
        parent = by_id.get(parent_id)
        if parent is None or parent.result_claim_id != result_claim_id:
            raise ClaimReviewChainError(
                f"Claim {result_claim_id} has a publication decision with an invalid parent."
            )
        superseded.add(parent_id)

    leaves = [decision for decision in decisions if decision.id not in superseded]
    if len(leaves) != 1:
        raise ClaimReviewChainError(
            f"Claim {result_claim_id} has {len(leaves)} effective publication decisions; "
            "manual resolution is blocked."
        )

    chain: list[models.ClaimPublicationDecision] = []
    visited: set[str] = set()
    current: models.ClaimPublicationDecision | None = leaves[0]
    while current is not None:
        if current.id in visited:
            raise ClaimReviewChainError(
                f"Claim {result_claim_id} has a cyclic publication-decision chain."
            )
        visited.add(current.id)
        chain.append(current)
        current = by_id.get(current.supersedes_decision_id) if current.supersedes_decision_id else None
    return chain


def _load_publication_decisions(
    session: Session, result_claim_ids: Sequence[str]
) -> dict[str, list[models.ClaimPublicationDecision]]:
    """Group-load publication decisions for a bounded claim window in one IN query."""
    grouped: dict[str, list[models.ClaimPublicationDecision]] = {}
    if not result_claim_ids:
        return grouped
    rows = session.scalars(
        select(models.ClaimPublicationDecision).where(
            models.ClaimPublicationDecision.result_claim_id.in_(list(result_claim_ids))
        )
    )
    for decision in rows:
        grouped.setdefault(decision.result_claim_id, []).append(decision)
    return grouped


def _claim_publication_chain(
    session: Session, result_claim_id: str
) -> list[models.ClaimPublicationDecision]:
    """Return the one effective element, in the same order as the legacy
    walker."""
    decisions = list(
        session.scalars(
            select(models.ClaimPublicationDecision).where(
                models.ClaimPublicationDecision.result_claim_id == result_claim_id
            )
        )
    )
    return _resolve_publication_chain(result_claim_id, decisions)


def get_effective_claim_publication_decision(
    session: Session, result_claim_id: str
) -> models.ClaimPublicationDecision | None:
    """Return the sole effective publication decision, or fail closed."""
    chain = _claim_publication_chain(session, result_claim_id)
    return chain[0] if chain else None


def get_claim_publication_projection(
    session: Session, claim: models.ResultClaim
) -> ClaimPublicationProjection:
    """Return a fail-closed public read model for publication state."""
    try:
        decision = get_effective_claim_publication_decision(session, claim.id)
    except ClaimReviewChainError as exc:
        return ClaimPublicationProjection(
            outcome=None,
            claim_review_decision_id=None,
            effective_decision_id=None,
            chain_error=str(exc),
        )
    if decision is None:
        return ClaimPublicationProjection(
            outcome=None,
            claim_review_decision_id=None,
            effective_decision_id=None,
        )
    return ClaimPublicationProjection(
        outcome=decision.outcome,
        claim_review_decision_id=decision.claim_review_decision_id,
        effective_decision_id=decision.id,
    )


def append_claim_review_decision(
    session: Session,
    *,
    result_claim_id: str,
    outcome: str,
    reason_code: str,
    model_entity_id: str | None = None,
    benchmark_id: str | None = None,
    metric: str | None = None,
    split: str | None = None,
    setting: str | None = None,
    evaluation_version: str | None = None,
    basis_json: dict[str, Any] | None = None,
    actor: str | None = None,
    supersedes_decision_id: str | None = None,
) -> models.ClaimReviewDecision:
    if session.get(models.ResultClaim, result_claim_id) is None:
        raise ValueError(f"Unknown result claim: {result_claim_id}")
    if outcome not in {
        "identity_resolved",
        "needs_review",
        "validation_reviewed",
        "quarantined",
        "revoked",
    }:
        raise ValueError(
            "Claim review status promotion is unavailable during containment; use an append-only "
            "identity, review, quarantine, or revocation decision."
        )
    if not reason_code.strip():
        raise ValueError("Claim review decisions require a stable non-empty reason code.")
    if model_entity_id is not None and session.get(models.ModelEntity, model_entity_id) is None:
        raise ValueError(f"Unknown model entity: {model_entity_id}")
    if benchmark_id is not None and session.get(models.Benchmark, benchmark_id) is None:
        raise ValueError(f"Unknown benchmark: {benchmark_id}")

    effective = get_effective_claim_review_decision(session, result_claim_id)
    expected_parent_id = effective.id if effective is not None else None
    if supersedes_decision_id != expected_parent_id:
        if expected_parent_id is None:
            raise ClaimReviewChainError(
                "The first claim review decision must not supersede another decision."
            )
        raise ClaimReviewChainError(
            "A new claim review decision must supersede the sole current effective decision."
        )
    row = models.ClaimReviewDecision(
        result_claim_id=result_claim_id,
        model_entity_id=model_entity_id,
        benchmark_id=benchmark_id,
        metric=metric,
        split=split,
        setting=setting,
        evaluation_version=evaluation_version,
        outcome=outcome,
        reason_code=reason_code,
        basis_json=basis_json or {},
        actor=actor,
        supersedes_decision_id=supersedes_decision_id,
    )
    session.add(row)
    session.flush()
    return row


def append_manual_model_mapping(
    session: Session,
    *,
    result_claim_id: str,
    model_entity_id: str,
    actor: str = "cli",
) -> models.ClaimReviewDecision:
    """Record a human identity correction without promoting claim validity."""
    claim = session.get(models.ResultClaim, result_claim_id)
    if claim is None:
        raise ValueError(f"Unknown result claim: {result_claim_id}")
    if session.get(models.ModelEntity, model_entity_id) is None:
        raise ValueError(f"Unknown model entity: {model_entity_id}")
    effective = get_effective_claim_review_decision(session, result_claim_id)
    return append_claim_review_decision(
        session,
        result_claim_id=result_claim_id,
        model_entity_id=model_entity_id,
        outcome="identity_resolved",
        reason_code="manual_model_mapping",
        basis_json={
            "schema": "claim-review-v1",
            "identity_action": "manual_model_mapping",
            "model_raw": claim.model_raw,
            "preserves_capture_status": claim.capture_status,
        },
        actor=actor,
        supersedes_decision_id=effective.id if effective is not None else None,
    )


def append_claim_publication_decision(
    session: Session,
    *,
    result_claim_id: str,
    claim_review_decision_id: str,
    outcome: str,
    policy_version: str,
    reason_code: str,
    basis_json: dict[str, Any] | None = None,
    actor: str | None = None,
    supersedes_decision_id: str | None = None,
) -> models.ClaimPublicationDecision:
    review = session.get(models.ClaimReviewDecision, claim_review_decision_id)
    if review is None or review.result_claim_id != result_claim_id:
        raise ValueError("Publication decision must reference a review decision for the same claim.")
    effective = get_effective_claim_review_decision(session, result_claim_id)
    if effective is None or effective.id != review.id:
        raise ClaimReviewChainError(
            "Publication decision must reference the sole current effective claim review decision."
        )
    if outcome not in {"quarantined", "revoked"}:
        raise ValueError(
            "Official publication approval is unavailable during containment; only quarantined or "
            "revoked publication decisions may be appended."
        )
    effective_publication = get_effective_claim_publication_decision(session, result_claim_id)
    expected_parent_id = effective_publication.id if effective_publication is not None else None
    if supersedes_decision_id != expected_parent_id:
        if expected_parent_id is None:
            raise ClaimReviewChainError(
                "The first claim publication decision must not supersede another decision."
            )
        raise ClaimReviewChainError(
            "A new claim publication decision must supersede the sole current effective decision."
        )
    row = models.ClaimPublicationDecision(
        result_claim_id=result_claim_id,
        claim_review_decision_id=claim_review_decision_id,
        outcome=outcome,
        policy_version=policy_version,
        reason_code=reason_code,
        basis_json=basis_json or {},
        actor=actor,
        supersedes_decision_id=supersedes_decision_id,
    )
    session.add(row)
    session.flush()
    return row


def create_ingestion_run(
    session: Session, *, run_type: str, official_source_id: str | None = None
) -> models.IngestionRun:
    row = models.IngestionRun(run_type=run_type, official_source_id=official_source_id, status="running")
    session.add(row)
    session.flush()
    return row


#: The only counters ``finish_ingestion_run`` may persist.  Every key must be an
#: exact allowlisted column name; anything else (metadata payload, a renamed
#: column) is rejected rather than silently ignored via ``hasattr``.
INGESTION_RUN_COUNTER_KEYS = frozenset(
    {
        "sources_checked",
        "snapshots_created",
        "snapshots_reused",
        "claims_extracted",
        "claims_inserted",
        "claims_unchanged",
        "claims_needing_review",
    }
)
#: The only terminal statuses a run may be finalized into.
INGESTION_RUN_TERMINAL_STATUSES = frozenset({"completed", "partial", "failed"})


def finish_ingestion_run(
    session: Session,
    run: models.IngestionRun,
    *,
    status: str,
    error_message: str | None = None,
    counters: dict[str, int] | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    if status not in INGESTION_RUN_TERMINAL_STATUSES:
        raise ValueError(
            f"ingestion run terminal status must be one of "
            f"{sorted(INGESTION_RUN_TERMINAL_STATUSES)}, got {status!r}"
        )
    if run.status != "running" or run.finished_at is not None:
        raise ValueError(
            "ingestion run identity/history is immutable; only one terminal finalization is allowed"
        )
    counters = counters or {}
    for key, value in counters.items():
        if key not in INGESTION_RUN_COUNTER_KEYS:
            raise ValueError(f"unknown ingestion run counter: {key!r}")
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"ingestion run counter {key!r} must be a non-negative integer, got {value!r}")
        if value < 0:
            raise ValueError(f"ingestion run counter {key!r} must be a non-negative integer, got {value!r}")
    run.status = status
    run.finished_at = func.current_timestamp()
    run.error_message = error_message
    for key, value in counters.items():
        setattr(run, key, value)
    if metadata is not None:
        run.metadata_json = metadata
    session.flush()


def list_active_sources(
    session: Session,
    *,
    source_id: str | None = None,
    benchmark_id: str | None = None,
) -> list[models.OfficialSourceRow]:
    q = (
        select(models.OfficialSourceRow)
        .where(models.OfficialSourceRow.status == "active")
        .order_by(models.OfficialSourceRow.id)
    )
    if source_id:
        q = q.where(models.OfficialSourceRow.id == source_id)
    if benchmark_id:
        q = q.where(models.OfficialSourceRow.benchmark_id == benchmark_id)
    return list(session.scalars(q))


def list_claims(
    session: Session,
    *,
    benchmark_id: str | None = None,
    limit: int = 50,
) -> list[models.ResultClaim]:
    q = select(models.ResultClaim).order_by(models.ResultClaim.created_at.desc()).limit(limit)
    if benchmark_id:
        q = q.where(models.ResultClaim.benchmark_id == benchmark_id)
    return list(session.scalars(q))


def get_claim(session: Session, claim_id: str) -> models.ResultClaim | None:
    return session.get(models.ResultClaim, claim_id)


def map_claim_benchmark(session: Session, claim_id: str, benchmark_id: str) -> models.ResultClaim | None:
    """Retired mutable compatibility helper.

    A benchmark correction must be recorded as an explicit review decision by
    a future governed workflow; it cannot rewrite the captured claim or use a
    mapping action as an implicit validation promotion.
    """
    del session, claim_id, benchmark_id
    raise ReviewWorkflowUnavailableError(
        "Mutable benchmark mapping is disabled; append a governed claim review decision instead."
    )


def mark_parser_verified(session: Session, claim_id: str) -> models.ResultClaim | None:
    """Retired mutable compatibility helper."""
    del session, claim_id
    raise ReviewWorkflowUnavailableError(
        "Parser-status promotion is disabled; capture status is immutable after claim insertion."
    )


def _validate_bounded(name: str, value: int) -> int:
    """Strict positive bounded validation for page sizing.

    A review-queue page is claimed *bounded*: ``limit`` (the requested output
    count, which is also the SQL window) is capped at ``REVIEW_QUEUE_MAX_SCAN``
    (10,000 rows).  This is the proven acceptance-fixture upper bound: the
    window is at most 10,000 rows, the in-memory projection pass is bounded by
    it, and the output list can never exceed it, so output <= limit <= max.
    """
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{name} must be a positive integer, got {value!r}")
    if value < 1:
        raise ValueError(f"{name} must be a positive integer, got {value!r}")
    if value > REVIEW_QUEUE_MAX_SCAN:
        raise ValueError(
            f"{name} exceeds the documented review-queue maximum of {REVIEW_QUEUE_MAX_SCAN}, "
            f"got {value!r}"
        )
    return value


#: Proven conservative cap for a single review-queue window and ``limit``.  The
#: 10,000-row acceptance fixture runs at exactly this bound; the in-memory
#: projection pass and output list are bounded by it.
REVIEW_QUEUE_MAX_SCAN = 10_000
#: Version this cursor format so a breaking token change is explicit.  The
#: token ``v1.<...>`` is base64url-text (no whitespace/quotes), so it is safe to
#: embed in a shell command line or URL without quoting.
_REVIEW_CURSOR_PREFIX = "v1."
_REVIEW_TIMESTAMP_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:[+-]\d{2}:?\d{2}|Z)?$"
)


def _cursor_datetime_str(created_at) -> str:
    """Render a boundary ``created_at`` preserving full timestamp precision.

    SQLite persists ``DateTime`` as the same text the ORM bound on insert
    (``YYYY-MM-DD HH:MM:SS`` at second precision from ``CURRENT_TIMESTAMP``, or
    with ``.ffffff`` microseconds for a Python-side value).  Rendering the
    boundary with :meth:`datetime.isoformat` (dropping the trailing ``+00:00``
    when naive) reproduces that exact stored text so the ``(created_at, id)``
    comparator matches precisely instead of silently losing microseconds.
    """
    if isinstance(created_at, datetime):
        if created_at.tzinfo is not None:
            # Convert to a common UTC instant *before* dropping tz, so the
            # persisted wall-clock text is the UTC time regardless of the
            # original offset; never gut the tzinfo outright.
            created_at = created_at.astimezone(timezone.utc).replace(tzinfo=None)
        return created_at.isoformat(sep=" ")
    if hasattr(created_at, "isoformat"):
        return created_at.isoformat(sep=" ")
    return str(created_at)


def _serialize_cursor(created_at, claim_id: str) -> str:
    """Serialize a concrete (created_at, id) cursor to an opaque token.

    Format: ``v1.<base64url(canonical JSON of {"created_at", "id"})>``.
    ``created_at`` keeps full precision; ``claim_id`` is a 36-char UUID, so the
    token is canonical and shell-safe.
    """
    created = _cursor_datetime_str(created_at)
    payload = _canonical_json({"created_at": created, "id": claim_id})
    token = base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii").rstrip("=")
    return _REVIEW_CURSOR_PREFIX + token


def _parse_review_cursor(cursor: str) -> tuple[str, str] | None:
    """Parse a next_cursor token back to (created_at_str, id).

    Strict, canonical, fail-closed.  Validates the base64url token, decodes it,
    enforces exactly the two canonical keys, validates the timestamp format and
    UUID shape, and finally requires that re-serializing the validated
    (created_at, id) reproduces the *original* base64url token byte-for-byte.
    Truncated, extra-key, invalid-time, invalid-id, and non-canonical tokens all
    return ``None`` so the caller rejects them fail-closed.
    """
    if not cursor or not isinstance(cursor, str) or not cursor.startswith(_REVIEW_CURSOR_PREFIX):
        return None
    token_b64 = cursor[len(_REVIEW_CURSOR_PREFIX):]
    try:
        raw = base64.urlsafe_b64decode(token_b64.encode("ascii") + b"=" * (-len(token_b64) % 4))
    except (ValueError, TypeError):
        return None
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    created_raw = payload.get("created_at")
    claim_id = payload.get("id")
    if not isinstance(created_raw, str) or not isinstance(claim_id, str) or not claim_id:
        return None
    # Exactly two keys; extra or missing keys are non-canonical.
    if set(payload) != {"created_at", "id"}:
        return None
    # Validate the timestamp is a real, parseable ISO datetime in the full
    # precision the serializer emits.
    try:
        parsed = datetime.fromisoformat(created_raw.replace(" ", "T"))
    except ValueError:
        return None
    if not _REVIEW_TIMESTAMP_RE.match(created_raw):
        return None
    # Strict UUID: ``UUID(claim_id)`` accepts several spellings (braces, urn,
    # hex-without-hyphens); require the canonical ``str()`` form back.
    try:
        if str(UUID(claim_id)) != claim_id:
            return None
    except (ValueError, AttributeError, TypeError):
        return None
    # Canonical timestamp: re-serializing the *parsed* datetime through the same
    # UTC-normalized renderer must reproduce ``created_raw`` exactly.  This is
    # stronger than the whitespace/duplicate-key byte check alone: it rejects any
    # non-canonical or non-UTC-normalized spelling of an otherwise-valid time.
    if _cursor_datetime_str(parsed) != created_raw:
        return None
    # Canonical byte check: the validated (created_at, id) must reproduce the
    # exact base64url body the caller sent.  Because ``json.loads`` would
    # otherwise tolerate extra whitespace or duplicate keys, this strict compare
    # rejects any non-canonical spelling of an otherwise-valid cursor.
    canonical = _canonical_json({"created_at": created_raw, "id": claim_id}).encode("utf-8")
    canonical_b64 = base64.urlsafe_b64encode(canonical).decode("ascii").rstrip("=")
    if canonical_b64 != token_b64:
        return None
    return created_raw, claim_id


def list_review_queue_page(
    session: Session,
    *,
    limit: int = 50,
    cursor: str | None = None,
) -> ReviewQueuePage:
    """Return exactly one bounded review-queue page.

    The page loads at most ``limit`` (== the SQL window) ``ResultClaim`` rows in
    a single ordered query using a stable ``(created_at, id)`` descending
    cursor, then resolves each window claim's review projection from one grouped
    IN query (no per-row ``SELECT``).  ``limit`` is the requested output count
    and is also the SQL window, so ``scanned <= limit <= REVIEW_QUEUE_MAX_SCAN``
    and ``len(items) <= limit``.  SQLite compares the timestamp against the
    exact persisted text (cast to text to match); PostgreSQL binds a native
    ``timestamptz`` literal.

    ``exhausted`` is true only when no more rows remain.  Because the window and
    the output cap are the same ``limit``, an exact-full final window is not
    distinguishable from "more rows remain" without a second query, so a caller
    that reaches an exact-full page fires one more page; that page returns zero
    rows with ``exhausted=True``.  This one extra empty page at the true end is
    documented and the CLI renders it truthfully, never as a running queue.
    """
    limit = _validate_bounded("limit", limit)

    concurrency_cursor = _parse_review_cursor(cursor) if cursor is not None else None
    if cursor is not None and concurrency_cursor is None:
        raise ValueError(f"Invalid review-queue cursor: {cursor!r}")

    q = select(models.ResultClaim)
    if concurrency_cursor is not None:
        created_str, claim_id = concurrency_cursor
        if session.bind is not None and session.bind.dialect.name == "sqlite":
            # SQLite persists ``DateTime`` as the exact bound text; compare the
            # stored column (cast to text) against that same text string.
            created_col = cast(models.ResultClaim.created_at, String)
            q = q.where(
                (created_col < created_str)
                | ((created_col == created_str) & (models.ResultClaim.id < claim_id))
            )
        else:
            # PostgreSQL stores ``timestamptz``; bind a native UTC-aware datetime
            # literal so the comparison is instant-accurate (never naive).
            created_value = datetime.fromisoformat(created_str.replace(" ", "T")).replace(
                tzinfo=timezone.utc
            )
            q = q.where(
                (models.ResultClaim.created_at < created_value)
                | (
                    (models.ResultClaim.created_at == created_value)
                    & (models.ResultClaim.id < claim_id)
                )
            )
    rows = list(
        session.scalars(
            q.order_by(models.ResultClaim.created_at.desc(), models.ResultClaim.id.desc()).limit(
                limit
            )
        )
    )
    scanned = len(rows)

    decisions_by_claim = _load_review_decisions(
        session, [claim.id for claim in rows]
    )
    items: list[ReviewQueueItem] = []
    for claim in rows:
        try:
            chain = _resolve_review_chain(claim.id, decisions_by_claim.get(claim.id, ()))
        except ClaimReviewChainError as exc:
            projection = _project_review(claim, [], chain_error=str(exc))
        else:
            projection = _project_review(claim, chain)
        if (
            projection.chain_error is not None
            or projection.model_entity_id is None
            or claim.capture_status == "needs_review"
        ):
            items.append(ReviewQueueItem(claim=claim, projection=projection))

    # ``exhausted`` means the claims table is fully consumed.  The window equals
    # ``limit``: a window shorter than ``limit`` proves depletion; a window that
    # fills ``limit`` exactly only *may* have more, so the caller makes one final
    # empty page to confirm.  A continuation is only meaningful when a future
    # page could hold rows.
    exhausted = scanned < limit
    if not exhausted:
        last = rows[-1]
        next_cursor = _serialize_cursor(last.created_at, last.id)
    else:
        next_cursor = None

    return ReviewQueuePage(
        items=items,
        next_cursor=next_cursor,
        exhausted=exhausted,
        scanned=scanned,
        projected=len(rows),
    )


def list_review_queue(session: Session, limit: int = 100) -> list[models.ResultClaim]:
    """Compatibility wrapper returning the first bounded review-queue page.

    This is the pre-existing public helper with identical first-page semantics:
    it returns the first ``limit`` eligible claims using the same bounded SQL
    window as :func:`list_review_queue_page`.  It deliberately does **not**
    page; callers that need continuation metadata should use the explicit page
    API.
    """
    page = list_review_queue_page(session, limit=limit, cursor=None)
    return [item.claim for item in page.items]


def list_snapshots(session: Session, source_id: str, limit: int = 50) -> list[models.SourceSnapshot]:
    q = (
        select(models.SourceSnapshot)
        .where(models.SourceSnapshot.official_source_id == source_id)
        .order_by(models.SourceSnapshot.captured_at.desc())
        .limit(limit)
    )
    return list(session.scalars(q))


def map_claim_model(session: Session, claim_id: str, model_entity_id: str) -> models.ResultClaim | None:
    """Retired mutable compatibility helper.

    Call :func:`append_manual_model_mapping` from the explicitly named review
    command.  Keeping this stub fail-closed prevents old callers from quietly
    regaining a status-promotion path.
    """
    del session, claim_id, model_entity_id
    raise ReviewWorkflowUnavailableError(
        "Mutable model mapping is disabled; use append_manual_model_mapping."
    )


def mark_human_verified(session: Session, claim_id: str) -> models.ResultClaim | None:
    """Retired mutable compatibility helper."""
    del session, claim_id
    raise ReviewWorkflowUnavailableError(
        "Human-verification promotion is disabled until governed review decisions are implemented."
    )
