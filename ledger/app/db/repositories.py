from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models
from app.schemas.boundary import ClaimValidationInput, ResultClaimInput


def upsert_benchmark(session: Session, data: dict[str, Any]) -> models.Benchmark:
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


def upsert_model_entity(session: Session, data: dict[str, Any]) -> models.ModelEntity:
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


def add_alias(
    session: Session,
    *,
    entity_type: str,
    entity_id: str,
    alias_text: str,
    is_official_alias: bool = False,
    alias_source: str | None = None,
) -> models.Alias:
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


def upsert_official_source(session: Session, data: dict[str, Any]) -> models.OfficialSourceRow:
    row = session.get(models.OfficialSourceRow, data["id"])
    if row is None:
        # Idempotent against the (benchmark_id, source_url) unique constraint:
        # a prior seed may hold the same logical source under a different id.
        row = session.scalar(
            select(models.OfficialSourceRow).where(
                models.OfficialSourceRow.benchmark_id == data.get("benchmark_id"),
                models.OfficialSourceRow.source_url == data.get("source_url"),
            )
        )
    if row is None:
        row = models.OfficialSourceRow(**{k: v for k, v in data.items() if hasattr(models.OfficialSourceRow, k)})
        session.add(row)
    else:
        for k, v in data.items():
            if hasattr(row, k) and k != "id":
                setattr(row, k, v)
    session.flush()
    return row


def find_snapshot(
    session: Session, official_source_id: str, content_hash: str
) -> models.SourceSnapshot | None:
    return session.scalar(
        select(models.SourceSnapshot).where(
            models.SourceSnapshot.official_source_id == official_source_id,
            models.SourceSnapshot.content_hash == content_hash,
        )
    )


def insert_snapshot(
    session: Session,
    *,
    official_source_id: str,
    raw_content_uri: str,
    content_hash: str,
    content_type: str | None,
    http_status: int | None,
    etag: str | None,
    last_modified_header: str | None,
    fetch_metadata: dict[str, Any],
    parser_version: str | None = None,
) -> models.SourceSnapshot:
    existing = find_snapshot(session, official_source_id, content_hash)
    if existing:
        return existing
    row = models.SourceSnapshot(
        official_source_id=official_source_id,
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
        official_source_id=claim.official_source_id,
        benchmark_id=claim.benchmark_id,
        model_entity_id=claim.model_entity_id,
        model_raw=claim.model_raw,
        benchmark_raw=claim.benchmark_raw,
        score_raw=claim.score_raw,
        metric_raw=claim.metric_raw,
        split_raw=claim.split_raw,
        setting_raw=claim.setting_raw,
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


def create_ingestion_run(
    session: Session, *, run_type: str, official_source_id: str | None = None
) -> models.IngestionRun:
    row = models.IngestionRun(run_type=run_type, official_source_id=official_source_id, status="running")
    session.add(row)
    session.flush()
    return row


def finish_ingestion_run(
    session: Session,
    run: models.IngestionRun,
    *,
    status: str,
    error_message: str | None = None,
    counters: dict[str, int] | None = None,
) -> None:
    run.status = status
    run.finished_at = datetime.now(timezone.utc).replace(tzinfo=None)
    run.error_message = error_message
    if counters:
        for k, v in counters.items():
            if hasattr(run, k):
                setattr(run, k, v)
    session.flush()


def list_active_sources(
    session: Session,
    *,
    source_id: str | None = None,
    benchmark_id: str | None = None,
) -> list[models.OfficialSourceRow]:
    q = select(models.OfficialSourceRow).where(models.OfficialSourceRow.status == "active")
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
    claim = session.get(models.ResultClaim, claim_id)
    if not claim:
        return None
    claim.benchmark_id = benchmark_id
    if claim.capture_status == "needs_review" and claim.model_entity_id is not None:
        claim.capture_status = "parser_verified"
    session.flush()
    return claim


def mark_parser_verified(session: Session, claim_id: str) -> models.ResultClaim | None:
    claim = session.get(models.ResultClaim, claim_id)
    if not claim:
        return None
    if claim.capture_status == "needs_review":
        claim.capture_status = "parser_verified"
    session.flush()
    return claim


def list_review_queue(session: Session, limit: int = 100) -> list[models.ResultClaim]:
    q = (
        select(models.ResultClaim)
        .where(
            (models.ResultClaim.model_entity_id.is_(None))
            | (models.ResultClaim.capture_status == "needs_review")
        )
        .order_by(models.ResultClaim.created_at.desc())
        .limit(limit)
    )
    return list(session.scalars(q))


def list_snapshots(session: Session, source_id: str, limit: int = 50) -> list[models.SourceSnapshot]:
    q = (
        select(models.SourceSnapshot)
        .where(models.SourceSnapshot.official_source_id == source_id)
        .order_by(models.SourceSnapshot.captured_at.desc())
        .limit(limit)
    )
    return list(session.scalars(q))


def map_claim_model(session: Session, claim_id: str, model_entity_id: str) -> models.ResultClaim | None:
    claim = session.get(models.ResultClaim, claim_id)
    if not claim:
        return None
    claim.model_entity_id = model_entity_id
    if claim.capture_status == "needs_review":
        claim.capture_status = "parser_verified"
    session.flush()
    return claim


def mark_human_verified(session: Session, claim_id: str) -> models.ResultClaim | None:
    claim = session.get(models.ResultClaim, claim_id)
    if not claim:
        return None
    claim.capture_status = "human_verified"
    session.add(
        models.ClaimValidation(
            result_claim_id=claim_id,
            validation_type="human_review",
            outcome="pass",
            validator="human",
            notes="Marked human verified via CLI",
        )
    )
    session.flush()
    return claim
