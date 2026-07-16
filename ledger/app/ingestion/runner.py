from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.db import repositories as repo
from app.db.models import OfficialSourceRow, SourceSnapshot
from app.ingestion.admission import (
    SourceAdmission,
    resolve_claim_admission,
    resolve_fetch_admission,
    resolve_source_admission,
)
from app.ingestion.adapters import get_adapter
from app.ingestion.extractors.normalize import compute_claim_fingerprint
from app.ingestion.policy import can_ingest_source, source_admission_reason
from app.ingestion.safe_fetch import SafeFetchClient, SafeFetchError, build_fetch_plan
from app.matching.aliases import resolve_benchmark, resolve_model_entity
from app.runtime.dependencies import (
    RuntimeDependencies,
    RuntimeDependencyError,
    contained_runtime_dependencies,
    validate_runtime_dependencies,
)
from app.schemas.boundary import ClaimValidationInput, OfficialSource
from app.storage.base import (
    SnapshotStorageIntegrityError,
    SnapshotStorageProtocolError,
    SnapshotStorageRunner,
    StorageObjectAddress,
    StorageObjectKind,
    StorageStoreReceipt,
    StorageVerificationReceipt,
    compute_content_hash,
)


@dataclass
class IngestionSummary:
    sources_checked: int = 0
    snapshots_created: int = 0
    snapshots_reused: int = 0
    claims_extracted: int = 0
    claims_inserted: int = 0
    claims_unchanged: int = 0
    claims_needing_review: int = 0
    claims_rejected: int = 0
    errors: list[str] = field(default_factory=list)
    claim_rejections: list[dict[str, str]] = field(default_factory=list)
    dry_run_claims: list[dict[str, Any]] = field(default_factory=list)
    status: str = "completed"
    sources_attempted: int = 0
    sources_succeeded: int = 0
    sources_blocked: int = 0
    stopped_early: bool = False
    source_outcomes: list[dict[str, str]] = field(default_factory=list)


class IngestionBlockedError(RuntimeError):
    """Raised before a run record or snapshot is written for denied sources."""


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


_PERSISTED_COUNTERS = (
    "sources_checked",
    "snapshots_created",
    "snapshots_reused",
    "claims_extracted",
    "claims_inserted",
    "claims_unchanged",
    "claims_needing_review",
)


def _merge_source_summary(target: IngestionSummary, source: IngestionSummary) -> None:
    for field_name in _PERSISTED_COUNTERS[1:]:
        setattr(target, field_name, getattr(target, field_name) + getattr(source, field_name))
    target.dry_run_claims.extend(source.dry_run_claims)
    target.claims_rejected += source.claims_rejected
    target.claim_rejections.extend(source.claim_rejections)


def _persisted_counters(summary: IngestionSummary) -> dict[str, int]:
    return {field_name: getattr(summary, field_name) for field_name in _PERSISTED_COUNTERS}


def _run_metadata(summary: IngestionSummary) -> dict[str, Any]:
    return {
        "errors": list(summary.errors),
        "sources_attempted": summary.sources_attempted,
        "sources_succeeded": summary.sources_succeeded,
        "sources_failed": summary.sources_attempted - summary.sources_succeeded,
        "sources_blocked": summary.sources_blocked,
        "stopped_early": summary.stopped_early,
        "source_outcomes": list(summary.source_outcomes),
        "claims_rejected": summary.claims_rejected,
        "claim_rejections": list(summary.claim_rejections),
    }


def _require_verification_receipt(
    receipt: object,
    *,
    uri: str,
    content_hash: str,
    byte_length: int,
    expected_address: StorageObjectAddress | None = None,
) -> StorageVerificationReceipt:
    if type(receipt) is not StorageVerificationReceipt:
        raise SnapshotStorageProtocolError(
            "Snapshot storage returned a noncanonical verification receipt."
        )
    if type(receipt.address) is not StorageObjectAddress:
        raise SnapshotStorageProtocolError(
            "Snapshot verification receipt contains a noncanonical address."
        )
    if (
        receipt.address.uri != uri
        or receipt.address.content_sha256 != content_hash
        or receipt.address.object_kind is not StorageObjectKind.SNAPSHOT
        or receipt.expected_sha256 != content_hash
        or receipt.observed_sha256 != content_hash
        or receipt.byte_length != byte_length
    ):
        raise SnapshotStorageIntegrityError(
            "Snapshot verification receipt substituted its URI, kind, digest, or byte length."
        )
    if expected_address is not None and receipt.address != expected_address:
        raise SnapshotStorageIntegrityError(
            "Snapshot verification receipt substituted the stored object address or key."
        )
    return receipt


def _require_store_receipt(
    receipt: object,
    *,
    content_hash: str,
    byte_length: int,
) -> StorageStoreReceipt:
    if type(receipt) is not StorageStoreReceipt:
        raise SnapshotStorageProtocolError(
            "Snapshot storage returned a noncanonical store receipt."
        )
    if type(receipt.address) is not StorageObjectAddress:
        raise SnapshotStorageProtocolError(
            "Snapshot store receipt contains a noncanonical address."
        )
    if (
        receipt.address.object_kind is not StorageObjectKind.SNAPSHOT
        or receipt.address.content_sha256 != content_hash
        or receipt.byte_length != byte_length
    ):
        raise SnapshotStorageIntegrityError(
            "Snapshot store receipt substituted its kind, digest, or byte length."
        )
    return receipt


def _run_one_source(
    session: Session,
    *,
    source: OfficialSource,
    source_revision_id: str,
    source_admission: SourceAdmission,
    dependencies: RuntimeDependencies,
    storage: SnapshotStorageRunner | None,
    dry_run: bool,
    fixture_path: Path | None,
    fetch_client: SafeFetchClient | None,
) -> IngestionSummary:
    """Process one source; callers own the transaction boundary and merge."""
    source_summary = IngestionSummary()
    adapter_kwargs = {}
    if source.source_type == "fake" and fixture_path:
        adapter_kwargs["fixture_path"] = fixture_path
    adapter = get_adapter(source.source_type, parser_name=source.parser_name, **adapter_kwargs)
    # Real source admission always supplies an immutable policy. The empty
    # branch is deliberately retained for isolated transaction fixtures that
    # replace the resolver in-process; it is not reachable through the real
    # source-admission path.
    if source_admission.policy:
        if not adapter.requires_central_fetch:
            raise RuntimeError("A production-admitted source cannot use an adapter-owned fetch path.")
        if fetch_client is None:
            raise RuntimeError("Central fetch client is required for an admitted source.")
        if dry_run:
            raise SafeFetchError(
                "FETCH_DRY_RUN_FORBIDDEN",
                "dry-run requires a provided local fixture artifact and never calls transport",
            )
        fetch_plan = build_fetch_plan(
            source=source,
            source_admission=source_admission,
            accepted_content_types=adapter.accepted_content_types,
            settings=dependencies.fetch_settings,
        )
        fetch_result = fetch_client.fetch(fetch_plan)
    else:
        # This branch is reserved for isolated fixture adapters whose admission
        # resolver was replaced in-process and supplied no production policy.
        # A real admitted source always takes the runner-owned central path.
        fetch_result = adapter.fetch(source)
    snap_input = adapter.snapshot(source, fetch_result)
    fetch_admission = resolve_fetch_admission(
        source_admission=source_admission,
        source=source,
        fetch_result=fetch_result,
        snapshot_input=snap_input,
    )
    if not fetch_admission.accepted:
        raise RuntimeError(
            f"{fetch_admission.reason_code}: {fetch_admission.detail or 'fetch artifact was rejected'}"
        )
    content_hash = compute_content_hash(snap_input.raw_bytes)

    if dry_run:
        # No storage object is constructed and no database row is queried or
        # created.  The transient ID exists only to exercise normal claim
        # extraction and fingerprinting logic.
        snapshot = SourceSnapshot(
            id="00000000-0000-0000-0000-000000000000",
            official_source_id=source.id,
            source_revision_id=source_revision_id,
            raw_content_uri=f"dry-run://{source.id}/{content_hash}",
            content_hash=content_hash,
            content_type=snap_input.content_type,
        )
    else:
        if storage is None:
            raise RuntimeError("Persistent ingestion requires snapshot storage.")
        existing = repo.find_snapshot(
            session,
            source.id,
            content_hash,
            source_revision_id=source_revision_id,
        )
        if existing:
            # A matching database hash is not proof that its URI still
            # contains the recorded immutable bytes.  Do not reuse a
            # snapshot unless storage verifies the full digest.
            verification = storage.verify_snapshot(
                uri=existing.raw_content_uri,
                content_sha256=content_hash,
            )
            _require_verification_receipt(
                verification,
                uri=existing.raw_content_uri,
                content_hash=content_hash,
                byte_length=len(snap_input.raw_bytes),
            )
            snapshot = existing
            source_summary.snapshots_reused += 1
        else:
            store_receipt = _require_store_receipt(
                storage.store_snapshot(
                    raw_bytes=snap_input.raw_bytes,
                    object_kind=StorageObjectKind.SNAPSHOT,
                ),
                content_hash=content_hash,
                byte_length=len(snap_input.raw_bytes),
            )
            verification = _require_verification_receipt(
                storage.verify_snapshot(
                    uri=store_receipt.address.uri,
                    content_sha256=content_hash,
                ),
                uri=store_receipt.address.uri,
                content_hash=content_hash,
                byte_length=len(snap_input.raw_bytes),
                expected_address=store_receipt.address,
            )
            if store_receipt.verification_receipt_id != verification.receipt_id:
                raise SnapshotStorageIntegrityError(
                    "Snapshot store receipt is not bound to the returned verification receipt."
                )
            snapshot, snapshot_created = repo.insert_snapshot_if_new(
                session,
                official_source_id=source.id,
                source_revision_id=source_revision_id,
                raw_content_uri=store_receipt.address.uri,
                content_hash=store_receipt.address.content_sha256,
                content_type=snap_input.content_type,
                http_status=snap_input.http_status,
                etag=snap_input.etag,
                last_modified_header=snap_input.last_modified_header,
                fetch_metadata=snap_input.fetch_metadata or {},
                parser_version=snap_input.parser_version,
            )
            if (
                snapshot.raw_content_uri != store_receipt.address.uri
                or snapshot.content_hash != store_receipt.address.content_sha256
            ):
                raise SnapshotStorageIntegrityError(
                    "Snapshot database row substituted the canonical storage receipt address."
                )
            if snapshot_created:
                source_summary.snapshots_created += 1
            else:
                reused_verification = storage.verify_snapshot(
                    uri=snapshot.raw_content_uri,
                    content_sha256=content_hash,
                )
                _require_verification_receipt(
                    reused_verification,
                    uri=snapshot.raw_content_uri,
                    content_hash=content_hash,
                    byte_length=len(snap_input.raw_bytes),
                    expected_address=store_receipt.address,
                )
                source_summary.snapshots_reused += 1

    raw_bytes = snap_input.raw_bytes
    claims = adapter.extract_claims(source, snapshot, raw_bytes)
    source_summary.claims_extracted += len(claims)

    if source_admission.source_revision_decision_id is None:
        raise RuntimeError("Admitted source is missing an immutable source-revision decision id.")

    for claim_index, claim in enumerate(claims):
        # Every persistable claim is bound to the exact certification decision
        # that admitted its snapshot revision.  The decision is immutable and
        # the database trigger rejects an unbound future insert.
        claim.source_snapshot_id = UUID(str(snapshot.id))
        claim.source_revision_decision_id = UUID(str(source_admission.source_revision_decision_id))
        model_match = resolve_model_entity(session, claim.model_raw)
        benchmark_match = resolve_benchmark(session, claim.benchmark_raw, source.benchmark_id)
        claim.model_entity_id = model_match.entity_id
        claim.benchmark_id = benchmark_match.entity_id
        admission = resolve_claim_admission(
            source_admission=source_admission,
            source=source,
            claim=claim,
            raw_bytes=raw_bytes,
            model_match=model_match,
            benchmark_match=benchmark_match,
        )
        if not admission.verdict.accepted:
            source_summary.claims_rejected += 1
            source_summary.claim_rejections.append(
                {
                    "source_id": source.id,
                    "claim_index": str(claim_index),
                    "reason_code": admission.verdict.reason_code or "CLAIM_REJECTED",
                }
            )
            continue

        claim.score_numeric = admission.score_numeric
        claim.score_unit = admission.score_unit
        needs_review = admission.verdict.disposition == "quarantine"
        if needs_review:
            # An ambiguous/unregistered model is still a verbatim evidence
            # candidate. Preserve its raw name and require later review rather
            # than assigning the first matching alias.
            claim.model_entity_id = None
            claim.capture_status = "needs_review"
        else:
            # The adapter does not decide status; exact central evidence
            # admission does. Publication remains separately disabled.
            claim.capture_status = "parser_verified"

        validations = adapter.validate_claim(claim, raw_bytes)
        if any(validation.outcome == "fail" for validation in validations) or not any(
            validation.outcome == "pass" for validation in validations
        ):
            needs_review = True
            claim.capture_status = "needs_review"
        validations.append(
            ClaimValidationInput(
                validation_type="central_claim_admission",
                outcome="pass",
                validator="claim-admission-v1",
                notes=admission.verdict.reason_code or "exact_evidence_and_identity",
            )
        )
        if needs_review:
            source_summary.claims_needing_review += 1

        # Fingerprints exercise the same admission-bound identity in preview,
        # but the detached preview object never reaches session or storage.
        claim.claim_fingerprint = compute_claim_fingerprint(claim)

        if dry_run:
            source_summary.dry_run_claims.append(
                {
                    "model_raw": claim.model_raw,
                    "benchmark_raw": claim.benchmark_raw,
                    "score_raw": claim.score_raw,
                    "capture_status": claim.capture_status,
                    "evidence_location": claim.evidence_location,
                    "admission": admission.verdict.disposition,
                    "admission_reason": admission.verdict.reason_code,
                }
            )
            continue

        row_claim, inserted = repo.insert_claim_if_new(session, claim)
        if inserted:
            source_summary.claims_inserted += 1
            repo.insert_validations(session, row_claim.id, validations)
        else:
            source_summary.claims_unchanged += 1

    return source_summary


def run_ingestion(
    session: Session,
    *,
    source_id: str | None = None,
    benchmark_id: str | None = None,
    dry_run: bool = False,
    fail_fast: bool | None = None,
    fixture_path: Path | None = None,
    dependencies: RuntimeDependencies | None = None,
) -> IngestionSummary:
    if type(dry_run) is not bool:
        raise RuntimeDependencyError("dry_run must be a boolean.")
    runtime = (
        contained_runtime_dependencies()
        if dependencies is None
        else validate_runtime_dependencies(dependencies)
    )
    fail_fast = runtime.ingestion_fail_fast if fail_fast is None else fail_fast
    if type(fail_fast) is not bool:
        raise RuntimeDependencyError("fail_fast must be a boolean when explicitly supplied.")
    summary = IngestionSummary()
    sources = repo.list_active_sources(session, source_id=source_id, benchmark_id=benchmark_id)
    candidates = [(row, _row_to_source(row)) for row in sources]
    eligible = [(row, source) for row, source in candidates if can_ingest_source(source)]
    blocked: list[str] = []
    blocked_outcomes: list[dict[str, str]] = []
    for _, source in candidates:
        if can_ingest_source(source):
            continue
        reason = source_admission_reason(source) or "unknown reason"
        blocked.append(f"{source.id}: skipped by policy ({reason})")
        blocked_outcomes.append(
            {"source_id": source.id, "outcome": "skipped_policy", "message": reason}
        )

    # Static containment is intentionally cheap, but only the session-aware
    # resolver can prove that this exact immutable revision has one certified
    # decision and a typed evidence policy. Resolve it before storage/run
    # construction so an unapproved revision is a true no-write rejection.
    admitted_sources: list[tuple[OfficialSource, str, SourceAdmission]] = []
    for _, source in eligible:
        try:
            source_revision = repo.get_current_source_revision(session, source.id)
            source_admission = resolve_source_admission(
                session, source=source, source_revision=source_revision
            )
        except Exception as exc:  # noqa: BLE001 - fail closed before evidence storage
            detail = str(exc).strip() or exc.__class__.__name__
            blocked.append(f"{source.id}: rejected by source admission ({detail})")
            blocked_outcomes.append(
                {
                    "source_id": source.id,
                    "outcome": "skipped_admission",
                    "message": detail,
                }
            )
            continue
        if not source_admission.verdict.accepted:
            detail = source_admission.verdict.reason_code or "source admission rejected"
            if source_admission.verdict.detail:
                detail = f"{detail}: {source_admission.verdict.detail}"
            blocked.append(f"{source.id}: rejected by source admission ({detail})")
            blocked_outcomes.append(
                {
                    "source_id": source.id,
                    "outcome": "skipped_admission",
                    "message": detail,
                }
            )
            continue
        admitted_sources.append((source, source_revision.id, source_admission))

    # A denied request must not leave a misleading completed run, write a
    # snapshot, or create a claim.  This also makes `ingest --all` safe while
    # no registry source has been deliberately certified.
    if not admitted_sources:
        requested = source_id or benchmark_id or "all active sources"
        detail = "; ".join(blocked) if blocked else "no matching active source"
        raise IngestionBlockedError(f"No production-eligible source for {requested}: {detail}")

    central_fetch_required = any(admission.policy for _, _, admission in admitted_sources)
    if central_fetch_required:
        for source, _, admission in admitted_sources:
            if not admission.policy:
                continue
            adapter = get_adapter(source.source_type, parser_name=source.parser_name)
            if not adapter.requires_central_fetch:
                raise IngestionBlockedError(
                    f"Production-admitted source {source.id} uses a fixture-only adapter."
                )
        if dry_run:
            raise SafeFetchError(
                "FETCH_DRY_RUN_FORBIDDEN",
                "dry-run requires a provided local fixture artifact and never calls transport",
            )
        # This check is deliberately before client creation, DNS, limiter,
        # storage construction, or a database run row.
        runtime.require_network_fetch()

    # A preview is intentionally side-effect free: it does not call the
    # storage factory, create a fetch client, acquire operational state, or
    # create a run row. Fixture adapters receive only their supplied bytes.
    storage = None if dry_run else runtime.create_snapshot_storage()
    fetch_client = runtime.create_fetch_client() if central_fetch_required else None
    run = None
    if not dry_run:
        run_type = "source" if source_id else ("benchmark" if benchmark_id else "full")
        run = repo.create_ingestion_run(session, run_type=run_type, official_source_id=source_id)
    summary.errors.extend(blocked)
    summary.sources_blocked = len(blocked)
    summary.source_outcomes.extend(blocked_outcomes)

    for source, source_revision_id, source_admission in admitted_sources:
        summary.sources_attempted += 1
        summary.sources_checked += 1
        try:
            if dry_run:
                source_summary = _run_one_source(
                    session,
                    source=source,
                    source_revision_id=source_revision_id,
                    source_admission=source_admission,
                    dependencies=runtime,
                    storage=None,
                    dry_run=True,
                    fixture_path=fixture_path,
                    fetch_client=fetch_client,
                )
            else:
                # A nested transaction gives each source an all-or-nothing
                # database boundary while leaving the terminal run record in
                # the outer transaction. Content-addressed orphan bytes are
                # deliberately retained rather than deleting evidence after a
                # post-store database failure; they are not referenced by a
                # snapshot row and require a separately audited GC policy.
                with session.begin_nested():
                    source_summary = _run_one_source(
                        session,
                        source=source,
                        source_revision_id=source_revision_id,
                        source_admission=source_admission,
                        dependencies=runtime,
                        storage=storage,
                        dry_run=False,
                        fixture_path=fixture_path,
                        fetch_client=fetch_client,
                    )
            _merge_source_summary(summary, source_summary)
            summary.sources_succeeded += 1
            if source_summary.claims_rejected:
                reason_codes = sorted(
                    {entry["reason_code"] for entry in source_summary.claim_rejections}
                )
                msg = (
                    f"{source.id}: rejected {source_summary.claims_rejected} claim candidate(s) "
                    f"({', '.join(reason_codes)})"
                )
                summary.errors.append(msg)
                summary.source_outcomes.append(
                    {
                        "source_id": source.id,
                        "outcome": "completed_with_claim_rejections",
                        "message": ", ".join(reason_codes),
                    }
                )
            else:
                summary.source_outcomes.append({"source_id": source.id, "outcome": "succeeded"})
        except Exception as exc:  # noqa: BLE001 - per-source isolation
            detail = str(exc).strip() or exc.__class__.__name__
            msg = f"{source.id}: {detail}"
            summary.errors.append(msg)
            summary.source_outcomes.append(
                {
                    "source_id": source.id,
                    "outcome": "failed",
                    "error_type": exc.__class__.__name__,
                    "message": detail,
                }
            )
            if fail_fast:
                summary.stopped_early = True
                break

    summary.status = "completed" if not summary.errors else (
        "partial" if summary.sources_succeeded else "failed"
    )
    if run is not None:
        repo.finish_ingestion_run(
            session,
            run,
            status=summary.status,
            error_message="\n".join(summary.errors) or None,
            counters=_persisted_counters(summary),
            metadata=_run_metadata(summary),
        )
    return summary
