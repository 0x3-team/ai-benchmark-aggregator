from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import repositories as repo
from app.db.models import OfficialSourceRow
from app.ingestion.adapters import get_adapter
from app.ingestion.extractors.normalize import compute_claim_fingerprint
from app.ingestion.policy import can_ingest_source
from app.matching.aliases import match_benchmark, match_model_entity
from app.schemas.boundary import OfficialSource
from app.storage.local import LocalSnapshotStorage


@dataclass
class IngestionSummary:
    sources_checked: int = 0
    snapshots_created: int = 0
    snapshots_reused: int = 0
    claims_extracted: int = 0
    claims_inserted: int = 0
    claims_unchanged: int = 0
    claims_needing_review: int = 0
    errors: list[str] = field(default_factory=list)
    dry_run_claims: list[dict[str, Any]] = field(default_factory=list)


def _row_to_source(row: OfficialSourceRow) -> OfficialSource:
    return OfficialSource(
        id=row.id,
        benchmark_id=row.benchmark_id,
        source_name=row.source_name,
        source_url=row.source_url,
        source_type=row.source_type,
        officialness_level=row.officialness_level,
        machine_readable=row.machine_readable,
        requires_auth=row.requires_auth,
        supports_history=row.supports_history,
        update_cadence=row.update_cadence,
        parser_name=row.parser_name,
        parser_version=row.parser_version,
        parser_config=row.parser_config or {},
        status=row.status,
        notes=row.notes,
    )


def _ext_for_content_type(content_type: str | None, source_type: str) -> str:
    if content_type:
        if "json" in content_type:
            return "json"
        if "html" in content_type:
            return "html"
        if "csv" in content_type:
            return "csv"
    if "html" in source_type:
        return "html"
    if "csv" in source_type:
        return "csv"
    return "json"


def run_ingestion(
    session: Session,
    *,
    source_id: str | None = None,
    benchmark_id: str | None = None,
    dry_run: bool = False,
    fail_fast: bool | None = None,
    fixture_path: Path | None = None,
) -> IngestionSummary:
    settings = get_settings()
    fail_fast = settings.ingestion_fail_fast if fail_fast is None else fail_fast
    storage = LocalSnapshotStorage(settings.snapshot_local_root)
    summary = IngestionSummary()
    run_type = "dry_run" if dry_run else ("source" if source_id else ("benchmark" if benchmark_id else "full"))
    run = repo.create_ingestion_run(session, run_type=run_type, official_source_id=source_id)

    sources = repo.list_active_sources(session, source_id=source_id, benchmark_id=benchmark_id)
    for row in sources:
        source = _row_to_source(row)
        summary.sources_checked += 1
        try:
            if not can_ingest_source(source):
                summary.errors.append(f"{source.id}: skipped by policy")
                continue
            adapter_kwargs = {}
            if source.source_type == "fake" and fixture_path:
                adapter_kwargs["fixture_path"] = fixture_path
            adapter = get_adapter(source.source_type, parser_name=source.parser_name, **adapter_kwargs)
            fetch_result = adapter.fetch(source)
            snap_input = adapter.snapshot(source, fetch_result)
            ext = _ext_for_content_type(snap_input.content_type, source.source_type)
            uri, content_hash = storage.save(
                official_source_id=source.id,
                raw_bytes=snap_input.raw_bytes,
                extension=ext,
            )
            existing = repo.find_snapshot(session, source.id, content_hash)
            if existing:
                snapshot = existing
                summary.snapshots_reused += 1
            else:
                if dry_run:
                    # still need a transient id for fingerprinting; create ephemeral insert only if not dry
                    # For dry-run without insert, extract using a temporary snapshot object-like
                    from app.db.models import SourceSnapshot

                    snapshot = SourceSnapshot(
                        id="00000000-0000-0000-0000-000000000000",
                        official_source_id=source.id,
                        raw_content_uri=uri,
                        content_hash=content_hash,
                        content_type=snap_input.content_type,
                    )
                    summary.snapshots_created += 0  # not persisted
                else:
                    snapshot = repo.insert_snapshot(
                        session,
                        official_source_id=source.id,
                        raw_content_uri=uri,
                        content_hash=content_hash,
                        content_type=snap_input.content_type,
                        http_status=snap_input.http_status,
                        etag=snap_input.etag,
                        last_modified_header=snap_input.last_modified_header,
                        fetch_metadata=snap_input.fetch_metadata or {},
                        parser_version=snap_input.parser_version,
                    )
                    summary.snapshots_created += 1

            raw_bytes = snap_input.raw_bytes
            claims = adapter.extract_claims(source, snapshot, raw_bytes)
            summary.claims_extracted += len(claims)

            for claim in claims:
                claim.source_snapshot_id = UUID(str(snapshot.id)) if not dry_run else None
                claim.model_entity_id = match_model_entity(session, claim.model_raw)
                claim.benchmark_id = match_benchmark(session, claim.benchmark_raw, source.benchmark_id)
                if claim.model_entity_id is None or claim.benchmark_id is None:
                    if claim.capture_status != "needs_review":
                        claim.capture_status = "needs_review"
                    summary.claims_needing_review += 1

                validations = adapter.validate_claim(claim, raw_bytes)
                if any(v.outcome == "fail" for v in validations) or not any(
                    v.outcome == "pass" for v in validations
                ):
                    claim.capture_status = "needs_review"
                    summary.claims_needing_review += 1

                # fingerprint uses snapshot id; for dry-run use content hash as stand-in
                if dry_run:
                    claim.source_snapshot_id = UUID("00000000-0000-0000-0000-000000000000")
                claim.claim_fingerprint = compute_claim_fingerprint(claim)

                if dry_run:
                    summary.dry_run_claims.append(
                        {
                            "model_raw": claim.model_raw,
                            "benchmark_raw": claim.benchmark_raw,
                            "score_raw": claim.score_raw,
                            "capture_status": claim.capture_status,
                            "evidence_location": claim.evidence_location,
                        }
                    )
                    continue

                claim.source_snapshot_id = UUID(str(snapshot.id))
                claim.claim_fingerprint = compute_claim_fingerprint(claim)
                row_claim, inserted = repo.insert_claim_if_new(session, claim)
                if inserted:
                    summary.claims_inserted += 1
                    repo.insert_validations(session, row_claim.id, validations)
                else:
                    summary.claims_unchanged += 1
        except Exception as exc:  # noqa: BLE001 - per-source isolation
            msg = f"{source.id}: {exc}"
            summary.errors.append(msg)
            if fail_fast:
                repo.finish_ingestion_run(
                    session,
                    run,
                    status="failed",
                    error_message=msg,
                    counters=summary.__dict__,
                )
                raise

    status = "completed" if not summary.errors else ("partial" if summary.sources_checked else "failed")
    repo.finish_ingestion_run(
        session,
        run,
        status=status if not dry_run else "completed",
        counters={
            "sources_checked": summary.sources_checked,
            "snapshots_created": summary.snapshots_created,
            "snapshots_reused": summary.snapshots_reused,
            "claims_extracted": summary.claims_extracted,
            "claims_inserted": summary.claims_inserted,
            "claims_unchanged": summary.claims_unchanged,
            "claims_needing_review": summary.claims_needing_review,
        },
    )
    return summary
