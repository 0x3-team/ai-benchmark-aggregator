"""Deterministic, append-only legacy reconciliation inventory.

The ledger remains the system of record for historical claims and snapshots.
This module deliberately *does not* alter a claim, append a decision, select a
conflict winner, read snapshot bytes, or write an export artifact.  It is an
offline diagnostic view which explains why a historical row is or is not part
of the LDR-08 candidate projection.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
import hashlib
import json
import math
from typing import Any, Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models, repositories as repo
from app.export.official_json import (
    CANONICAL_JSON_ALGORITHM,
    FeedCandidateAnalysis,
    FeedResourceLimitError,
    MAX_CLAIMS,
    MAX_SNAPSHOTS,
    FeedBatch,
    _cell_sort_key,
    _iso8601,
    analyze_official_feed_candidates,
)


LEGACY_INVENTORY_SCHEMA_VERSION = "1.0.0"
LEGACY_INVENTORY_POLICY_VERSION = "legacy-inventory-v1"
LEGACY_INVENTORY_AVAILABILITY = "report_only"

_TOP_LEVEL_KEYS = frozenset(
    {
        "schemaVersion",
        "policyVersion",
        "availability",
        "manifest",
        "summary",
        "claims",
        "snapshots",
        "conflicts",
    }
)
_MANIFEST_KEYS = frozenset(
    {
        "algorithm",
        "contentSha256",
        "claimCount",
        "snapshotCount",
        "candidateClaimCount",
        "excludedClaimCount",
        "conflictedClaimCount",
        "conflictCellCount",
    }
)
_SUMMARY_KEYS = frozenset(
    {
        "candidateProjectionStatus",
        "selectedCellCount",
        "reportOnlyQuarantine",
        "dispositionCounts",
        "omissionReasonCounts",
        "observedRiskSignalCounts",
        "evidenceCounts",
        "explicitQuarantineDecisionCount",
        "explicitRevocationDecisionCount",
    }
)
_CLAIM_KEYS = frozenset(
    {
        "claimId",
        "sourceSnapshotId",
        "sourceSnapshotPresent",
        "source",
        "raw",
        "parsed",
        "capture",
        "evidence",
        "decisions",
        "reportDisposition",
        "omissionReasonCode",
        "observedRiskSignals",
    }
)
_SNAPSHOT_KEYS = frozenset(
    {
        "snapshotId",
        "officialSourceId",
        "sourceRevisionId",
        "contentSha256",
        "capturedAt",
        "contentType",
        "hasRawContentUri",
        "claimCount",
    }
)
_CONFLICT_KEYS = frozenset({"cell", "claimIds"})
_DISPOSITIONS = frozenset({"candidate", "omitted", "conflicted"})
_SOURCE_KEYS = frozenset(
    {
        "officialSourceId",
        "officialSourcePresent",
        "sourceRevisionId",
        "sourceRevisionPresent",
        "sourceType",
        "sourceRevisionStatus",
    }
)
_DECISION_KEYS = frozenset({"effectiveDecisionId", "outcome", "reasonCode", "chainValid"})
_DECISIONS_KEYS = frozenset({"captureSource", "review", "publication"})
_EVIDENCE_COUNT_KEYS = frozenset(
    {"claimsWithEvidenceLocation", "claimsWithEvidenceText", "snapshotsWithContentHash"}
)
_EVIDENCE_KEYS = frozenset(
    {"location", "hasLocation", "locationSha256", "hasEvidenceText", "evidenceTextSha256"}
)


class LegacyInventoryError(ValueError):
    """The report would not faithfully account for immutable ledger rows."""


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def canonical_legacy_inventory_json(payload: Mapping[str, Any]) -> str:
    """Serialize an inventory report for offline comparison and CLI output."""
    return _canonical_json(payload)


def _digest_payload(payload: Mapping[str, Any]) -> str:
    digest_input = deepcopy(dict(payload))
    manifest = digest_input.get("manifest")
    if isinstance(manifest, dict):
        manifest["contentSha256"] = None
    return hashlib.sha256(_canonical_json(digest_input).encode("utf-8")).hexdigest()


def legacy_inventory_digest(payload: Mapping[str, Any]) -> str:
    """Return the self-hash used by the deterministic read-only report."""
    return _digest_payload(payload)


def _nonempty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _finite_number_or_none(value: object) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)):
        return float(value)
    return None


def _value_digest(value: object) -> str | None:
    if value is None:
        return None
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _decision_record(row: object | None, *, chain_valid: bool) -> dict[str, Any]:
    return {
        "effectiveDecisionId": getattr(row, "id", None),
        "outcome": getattr(row, "outcome", None),
        "reasonCode": getattr(row, "reason_code", None),
        "chainValid": chain_valid,
    }


def _capture_risk_signals(
    claim: models.ResultClaim,
    *,
    snapshot: models.SourceSnapshot | None,
    revision: models.OfficialSourceRevision | None,
    review_decision: models.ClaimReviewDecision | None,
    publication_decision: models.ClaimPublicationDecision | None,
) -> list[str]:
    """Surface observed legacy risk facts without inventing a new status.

    These signals are intentionally supplementary.  Candidate eligibility is
    defined only by the LDR-08 analysis and is never altered by a report-only
    label here.
    """
    signals: set[str] = set()
    method = claim.capture_method.lower()
    if "derived" in method:
        signals.add("DERIVED_CAPTURE_METHOD")
    if any(token in method for token in ("fake", "synthetic", "mock")):
        signals.add("SYNTHETIC_CAPTURE_METHOD")
    if "discovery" in method:
        signals.add("DISCOVERY_CAPTURE_METHOD")
    if "fallback" in method:
        signals.add("FALLBACK_CAPTURE_METHOD")

    location = claim.evidence_location
    if isinstance(location, dict) and location.get("type") == "derived_analytics":
        signals.add("DERIVED_EVIDENCE_LOCATION")
    if claim.capture_status in {"unreviewed", "needs_review"}:
        signals.add("PROVISIONAL_CAPTURE_STATUS")
    if claim.source_revision_decision_id is None:
        signals.add("LEGACY_UNASSESSED")
    if snapshot is None:
        signals.add("MISSING_SNAPSHOT")
    if revision is None:
        signals.add("MISSING_SOURCE_REVISION")
    else:
        source_type = revision.source_type.lower()
        if source_type == "fake":
            signals.add("SYNTHETIC_SOURCE_TYPE")
        if "discovery" in source_type:
            signals.add("DISCOVERY_SOURCE_TYPE")

    if review_decision is not None and review_decision.outcome in {"quarantined", "revoked"}:
        signals.add(f"REVIEW_{review_decision.outcome.upper()}")
    if publication_decision is not None and publication_decision.outcome in {
        "quarantined",
        "revoked",
    }:
        signals.add(f"PUBLICATION_{publication_decision.outcome.upper()}")
    return sorted(signals)


def _claim_record_batched(
    batch: FeedBatch,
    claim: models.ResultClaim,
    *,
    snapshot: models.SourceSnapshot | None,
    source: models.OfficialSourceRow | None,
    revision: models.OfficialSourceRevision | None,
    disposition: str,
    omission_reason: str | None,
) -> tuple[dict[str, Any], bool, bool]:
    """Batch-context counterpart of the former session-based record builder.

    Review/publication chains and the three decision rows are resolved
    entirely from the preloaded ``FeedBatch``, preserving the same
    fail-closed semantics and identical record fields.
    """
    try:
        review_chain = batch.review_chain(claim)
        review_chain_error: str | None = None
    except repo.ClaimReviewChainError as exc:
        review_chain = []
        review_chain_error = str(exc)
    try:
        publication_chain = batch.publication_chain(claim)
        publication_chain_error: str | None = None
    except repo.ClaimReviewChainError as exc:
        publication_chain = []
        publication_chain_error = str(exc)
    review = repo._project_review(claim, review_chain, chain_error=review_chain_error)
    publication = _project_publication(publication_chain, publication_chain_error)

    source_decision = (
        batch.source_decisions.get(claim.source_revision_decision_id)
        if claim.source_revision_decision_id
        else None
    )
    review_decision = (
        batch.review_decisions_by_id.get(review.effective_decision_id)
        if review.effective_decision_id
        else None
    )
    publication_decision = (
        batch.publication_decisions_by_id.get(publication.effective_decision_id)
        if publication.effective_decision_id
        else None
    )
    explicit_quarantine = any(
        decision is not None and decision.outcome == "quarantined"
        for decision in (source_decision, review_decision, publication_decision)
    )
    explicit_revocation = any(
        decision is not None and decision.outcome == "revoked"
        for decision in (source_decision, review_decision, publication_decision)
    )

    evidence_location = deepcopy(claim.evidence_location)
    record = {
        "claimId": claim.id,
        "sourceSnapshotId": claim.source_snapshot_id,
        "sourceSnapshotPresent": snapshot is not None,
        "source": {
            "officialSourceId": claim.official_source_id,
            "officialSourcePresent": source is not None,
            "sourceRevisionId": snapshot.source_revision_id if snapshot is not None else None,
            "sourceRevisionPresent": revision is not None,
            "sourceType": revision.source_type if revision is not None else None,
            "sourceRevisionStatus": revision.status if revision is not None else None,
        },
        "raw": {
            "model": claim.model_raw,
            "benchmark": claim.benchmark_raw,
            "score": claim.score_raw,
            "metric": claim.metric_raw,
            "split": claim.split_raw,
            "setting": claim.setting_raw,
            "evaluationVersion": claim.evaluation_version_raw,
        },
        "parsed": {
            "scoreNumeric": _finite_number_or_none(claim.score_numeric),
            "scoreNumericState": "finite"
            if _finite_number_or_none(claim.score_numeric) is not None
            else "missing_or_non_finite",
            "scoreUnit": claim.score_unit,
        },
        "capture": {
            "method": claim.capture_method,
            "status": claim.capture_status,
            "scientificStatus": claim.scientific_status,
            "confidence": _finite_number_or_none(claim.capture_confidence),
            "officialnessLevel": claim.officialness_level,
        },
        "evidence": {
            "location": evidence_location,
            "hasLocation": isinstance(evidence_location, dict) and bool(evidence_location),
            "locationSha256": _value_digest(evidence_location),
            "hasEvidenceText": _nonempty_string(claim.evidence_text),
            "evidenceTextSha256": _value_digest(claim.evidence_text),
        },
        "decisions": {
            "captureSource": _decision_record(source_decision, chain_valid=True),
            "review": _decision_record(review_decision, chain_valid=review.chain_error is None),
            "publication": _decision_record(
                publication_decision, chain_valid=publication.chain_error is None
            ),
        },
        "reportDisposition": disposition,
        "omissionReasonCode": omission_reason,
        "observedRiskSignals": _capture_risk_signals(
            claim,
            snapshot=snapshot,
            revision=revision,
            review_decision=review_decision,
            publication_decision=publication_decision,
        ),
    }
    return record, explicit_quarantine, explicit_revocation


def _project_publication(
    chain: list[models.ClaimPublicationDecision],
    chain_error: str | None,
) -> repo.ClaimPublicationProjection:
    """Pure publication projection from an in-memory chain.

    Mirrors the repository's ``get_claim_publication_projection`` semantics:
    a chain error yields a fail-closed projection, an empty chain yields a
    no-decision projection, otherwise the leaf decision's fields are used.
    """
    if chain_error is not None:
        return repo.ClaimPublicationProjection(
            outcome=None,
            claim_review_decision_id=None,
            effective_decision_id=None,
            chain_error=chain_error,
        )
    if not chain:
        return repo.ClaimPublicationProjection(
            outcome=None,
            claim_review_decision_id=None,
            effective_decision_id=None,
        )
    decision = chain[0]
    return repo.ClaimPublicationProjection(
        outcome=decision.outcome,
        claim_review_decision_id=decision.claim_review_decision_id,
        effective_decision_id=decision.id,
    )


def _conflict_records(analysis: FeedCandidateAnalysis) -> tuple[list[dict[str, Any]], set[str]]:
    rows: list[dict[str, Any]] = []
    conflict_claim_ids: set[str] = set()
    for cell, candidates in analysis.conflicts:
        claim_ids = [candidate.claim.id for candidate in candidates]
        conflict_claim_ids.update(claim_ids)
        rows.append({"cell": deepcopy(cell), "claimIds": claim_ids})
    rows.sort(key=lambda row: _cell_sort_key(row["cell"]))
    return rows, conflict_claim_ids


def _count_rows(counter: Counter[str]) -> list[dict[str, Any]]:
    return [{"code": code, "count": counter[code]} for code in sorted(counter)]


def build_legacy_inventory_report(session: Session) -> dict[str, Any]:
    """Build a deterministic report covering every historical claim and snapshot.

    The report remains useful when the candidate projection has a conflict:
    conflicting rows are labelled ``conflicted`` and the projection status is
    ``conflict`` rather than raising or silently returning a partial feed.

    Cardinality is hard-bounded (SQL ``LIMIT cap + 1`` on claims and
    snapshots, per-chunk remaining-budget limits on related rows).  A resource
    cap overflow is converted to :class:`LegacyInventoryError` so the CLI can
    emit one stable generic refusal and never a partial report.
    """
    try:
        return _build_legacy_inventory_report(session)
    except FeedResourceLimitError as exc:
        raise LegacyInventoryError(str(exc)) from None


def _build_legacy_inventory_report(session: Session) -> dict[str, Any]:
    with session.no_autoflush:
        claims = list(
            session.scalars(
                select(models.ResultClaim).order_by(models.ResultClaim.id).limit(MAX_CLAIMS + 1)
            )
        )
        if len(claims) > MAX_CLAIMS:
            raise LegacyInventoryError(
                f"claim count exceeds the documented inventory cap of {MAX_CLAIMS}"
            )
        snapshots = list(
            session.scalars(
                select(models.SourceSnapshot).order_by(models.SourceSnapshot.id).limit(MAX_SNAPSHOTS + 1)
            )
        )
        if len(snapshots) > MAX_SNAPSHOTS:
            raise LegacyInventoryError(
                f"snapshot count exceeds the documented inventory cap of {MAX_SNAPSHOTS}"
            )
        snapshots_by_id = {snapshot.id: snapshot for snapshot in snapshots}
        # One bounded context shared by the candidate analysis and the per-claim
        # inventory records (no duplicate batch build, no per-claim query).
        #
        # Snapshot note: the legacy report must surface EVERY snapshot,
        # including orphan snapshots not referenced by any claim, so it loads
        # the full (bounded, SQL LIMIT cap+1) snapshot set above for its
        # snapshot section.  FeedBatch independently loads the claim-referenced
        # snapshot subset under the same shared MAX_SNAPSHOTS cap for the
        # candidate analysis.  This bounded duplicate is deliberate: it keeps
        # FeedBatch a self-contained reusable context with its own cap guard,
        # and the two loads serve different row sets (full vs claim-referenced).
        batch = FeedBatch(session, claims)
        # Sources/revisions come from the bounded batch (only rows referenced
        # by the loaded claims/snapshots) — never an unbounded all-table scan.
        sources = dict(batch.sources)
        revisions = dict(batch.revisions)
        analysis = analyze_official_feed_candidates(session, batch=batch)
        excluded_by_claim_id = {
            row["claimId"]: row["reasonCode"] for row in analysis.excluded_claims
        }
        conflict_rows, conflict_claim_ids = _conflict_records(analysis)
        eligible_claim_ids = {candidate.claim.id for candidate in analysis.eligible_candidates}
        all_claim_ids = {claim.id for claim in claims}
        accounted_claim_ids = set(excluded_by_claim_id) | eligible_claim_ids
        if accounted_claim_ids != all_claim_ids or set(excluded_by_claim_id) & eligible_claim_ids:
            raise LegacyInventoryError("Candidate analysis did not account for every claim exactly once.")
        if not conflict_claim_ids <= eligible_claim_ids:
            raise LegacyInventoryError("A conflict referenced a claim outside the eligible candidate set.")

        snapshot_claim_counts = Counter(claim.source_snapshot_id for claim in claims)
        snapshot_rows = [
            {
                "snapshotId": snapshot.id,
                "officialSourceId": snapshot.official_source_id,
                "sourceRevisionId": snapshot.source_revision_id,
                "contentSha256": snapshot.content_hash,
                "capturedAt": _iso8601(snapshot.captured_at),
                "contentType": snapshot.content_type,
                "hasRawContentUri": _nonempty_string(snapshot.raw_content_uri),
                "claimCount": snapshot_claim_counts[snapshot.id],
            }
            for snapshot in snapshots
        ]

        claim_rows: list[dict[str, Any]] = []
        dispositions: Counter[str] = Counter()
        omission_reasons: Counter[str] = Counter()
        observed_risk_signals: Counter[str] = Counter()
        explicit_quarantines = 0
        explicit_revocations = 0
        for claim in claims:
            snapshot = snapshots_by_id.get(claim.source_snapshot_id)
            revision = revisions.get(snapshot.source_revision_id) if snapshot is not None else None
            source = sources.get(claim.official_source_id)
            if claim.id in conflict_claim_ids:
                disposition, omission_reason = "conflicted", "DISPLAY_CELL_CONFLICT"
            elif claim.id in excluded_by_claim_id:
                disposition, omission_reason = "omitted", excluded_by_claim_id[claim.id]
            else:
                disposition, omission_reason = "candidate", None
            record, explicit_quarantine, explicit_revocation = _claim_record_batched(
                batch,
                claim,
                snapshot=snapshot,
                source=source,
                revision=revision,
                disposition=disposition,
                omission_reason=omission_reason,
            )
            claim_rows.append(record)
            dispositions[disposition] += 1
            if omission_reason is not None:
                omission_reasons[omission_reason] += 1
            observed_risk_signals.update(record["observedRiskSignals"])
            explicit_quarantines += int(explicit_quarantine)
            explicit_revocations += int(explicit_revocation)

        candidate_claim_count = dispositions["candidate"]
        payload: dict[str, Any] = {
            "schemaVersion": LEGACY_INVENTORY_SCHEMA_VERSION,
            "policyVersion": LEGACY_INVENTORY_POLICY_VERSION,
            # A reconciliation report is not an Official artifact, even when
            # it identifies a clean candidate subset.
            "availability": LEGACY_INVENTORY_AVAILABILITY,
            "manifest": {
                "algorithm": CANONICAL_JSON_ALGORITHM,
                "contentSha256": None,
                "claimCount": len(claim_rows),
                "snapshotCount": len(snapshot_rows),
                "candidateClaimCount": candidate_claim_count,
                "excludedClaimCount": dispositions["omitted"],
                "conflictedClaimCount": dispositions["conflicted"],
                "conflictCellCount": len(conflict_rows),
            },
            "summary": {
                "candidateProjectionStatus": "conflict" if conflict_rows else "candidate",
                # Strict LDR-08 projection produces no partial selected cells
                # if one or more conflicts remain unresolved.
                "selectedCellCount": 0 if conflict_rows else candidate_claim_count,
                "reportOnlyQuarantine": True,
                "dispositionCounts": _count_rows(dispositions),
                "omissionReasonCounts": _count_rows(omission_reasons),
                "observedRiskSignalCounts": _count_rows(observed_risk_signals),
                "evidenceCounts": {
                    "claimsWithEvidenceLocation": sum(
                        int(row["evidence"]["hasLocation"]) for row in claim_rows
                    ),
                    "claimsWithEvidenceText": sum(
                        int(row["evidence"]["hasEvidenceText"]) for row in claim_rows
                    ),
                    "snapshotsWithContentHash": sum(
                        int(_nonempty_string(row["contentSha256"])) for row in snapshot_rows
                    ),
                },
                "explicitQuarantineDecisionCount": explicit_quarantines,
                "explicitRevocationDecisionCount": explicit_revocations,
            },
            "claims": claim_rows,
            "snapshots": snapshot_rows,
            "conflicts": conflict_rows,
        }
        payload["manifest"]["contentSha256"] = legacy_inventory_digest(payload)
        return validate_legacy_inventory_report(payload)


def _require_exact_mapping(value: object, expected: frozenset[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        raise LegacyInventoryError(f"{label} has an invalid contract shape.")
    return value


def _require_nonnegative_int(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise LegacyInventoryError(f"{label} must be a non-negative integer.")
    return value


def _validate_count_rows(value: object, label: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise LegacyInventoryError(f"{label} must be an array.")
    parsed: list[dict[str, Any]] = []
    codes: list[str] = []
    for row in value:
        item = _require_exact_mapping(row, frozenset({"code", "count"}), f"{label} entry")
        if not _nonempty_string(item["code"]):
            raise LegacyInventoryError(f"{label} contains an invalid code.")
        _require_nonnegative_int(item["count"], f"{label} count")
        codes.append(item["code"])
        parsed.append(item)
    if codes != sorted(codes) or len(codes) != len(set(codes)):
        raise LegacyInventoryError(f"{label} must be sorted and unique by code.")
    return parsed


def validate_legacy_inventory_report(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate deterministic accounting without requiring a JSON Schema runtime."""
    document = _require_exact_mapping(dict(payload), _TOP_LEVEL_KEYS, "Legacy inventory")
    if document["schemaVersion"] != LEGACY_INVENTORY_SCHEMA_VERSION:
        raise LegacyInventoryError("Legacy inventory has an unsupported schema version.")
    if document["policyVersion"] != LEGACY_INVENTORY_POLICY_VERSION:
        raise LegacyInventoryError("Legacy inventory has an unsupported policy version.")
    if document["availability"] != LEGACY_INVENTORY_AVAILABILITY:
        raise LegacyInventoryError("Legacy inventory must remain report-only.")

    manifest = _require_exact_mapping(document["manifest"], _MANIFEST_KEYS, "Legacy inventory manifest")
    if manifest["algorithm"] != CANONICAL_JSON_ALGORITHM:
        raise LegacyInventoryError("Legacy inventory manifest uses an unsupported digest algorithm.")
    digest = manifest["contentSha256"]
    if not isinstance(digest, str) or len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise LegacyInventoryError("Legacy inventory manifest has an invalid content digest.")
    for key in _MANIFEST_KEYS - {"algorithm", "contentSha256"}:
        _require_nonnegative_int(manifest[key], f"Legacy inventory manifest {key}")

    if not isinstance(document["claims"], list):
        raise LegacyInventoryError("Legacy inventory claims must be an array.")
    claim_ids: list[str] = []
    dispositions: Counter[str] = Counter()
    omission_reasons: Counter[str] = Counter()
    observed_risk_signals: Counter[str] = Counter()
    explicit_quarantines = 0
    explicit_revocations = 0
    for row in document["claims"]:
        claim = _require_exact_mapping(row, _CLAIM_KEYS, "Legacy inventory claim")
        if not _nonempty_string(claim["claimId"]):
            raise LegacyInventoryError("Legacy inventory claim has an invalid claimId.")
        if not _nonempty_string(claim["sourceSnapshotId"]):
            raise LegacyInventoryError("Legacy inventory claim has an invalid sourceSnapshotId.")
        if claim["reportDisposition"] not in _DISPOSITIONS:
            raise LegacyInventoryError("Legacy inventory claim has an invalid report disposition.")
        if claim["reportDisposition"] == "candidate":
            if claim["omissionReasonCode"] is not None:
                raise LegacyInventoryError("Candidate inventory claims cannot have an omission reason.")
        elif not _nonempty_string(claim["omissionReasonCode"]):
            raise LegacyInventoryError("Omitted inventory claims require an omission reason.")
        if not isinstance(claim["sourceSnapshotPresent"], bool):
            raise LegacyInventoryError("Legacy inventory claim has an invalid sourceSnapshotPresent flag.")
        source = _require_exact_mapping(claim["source"], _SOURCE_KEYS, "Legacy inventory claim source")
        if not _nonempty_string(source["officialSourceId"]) or not isinstance(
            source["officialSourcePresent"], bool
        ) or not isinstance(source["sourceRevisionPresent"], bool):
            raise LegacyInventoryError("Legacy inventory claim source has invalid presence metadata.")
        evidence = _require_exact_mapping(claim["evidence"], _EVIDENCE_KEYS, "Legacy inventory claim evidence")
        if not isinstance(evidence["hasLocation"], bool) or not isinstance(
            evidence["hasEvidenceText"], bool
        ):
            raise LegacyInventoryError("Legacy inventory claim evidence has invalid presence metadata.")
        if evidence["hasLocation"] != (isinstance(evidence["location"], dict) and bool(evidence["location"])):
            raise LegacyInventoryError("Legacy inventory claim evidence has inconsistent location metadata.")
        if evidence["locationSha256"] != _value_digest(evidence["location"]):
            raise LegacyInventoryError("Legacy inventory claim evidence location digest does not match.")
        decisions = _require_exact_mapping(
            claim["decisions"], _DECISIONS_KEYS, "Legacy inventory claim decisions"
        )
        decision_outcomes: list[str | None] = []
        for label in ("captureSource", "review", "publication"):
            decision = _require_exact_mapping(
                decisions[label], _DECISION_KEYS, f"Legacy inventory claim {label} decision"
            )
            if not isinstance(decision["chainValid"], bool):
                raise LegacyInventoryError("Legacy inventory decision has an invalid chainValid flag.")
            if decision["outcome"] is not None and not _nonempty_string(decision["outcome"]):
                raise LegacyInventoryError("Legacy inventory decision has an invalid outcome.")
            decision_outcomes.append(decision["outcome"])
        explicit_quarantines += int("quarantined" in decision_outcomes)
        explicit_revocations += int("revoked" in decision_outcomes)
        if not isinstance(claim["observedRiskSignals"], list) or any(
            not _nonempty_string(signal) for signal in claim["observedRiskSignals"]
        ) or claim["observedRiskSignals"] != sorted(set(claim["observedRiskSignals"])):
            raise LegacyInventoryError("Legacy inventory claim risk signals must be sorted unique strings.")
        claim_ids.append(claim["claimId"])
        dispositions[claim["reportDisposition"]] += 1
        if claim["omissionReasonCode"] is not None:
            omission_reasons[claim["omissionReasonCode"]] += 1
        observed_risk_signals.update(claim["observedRiskSignals"])
    if claim_ids != sorted(claim_ids) or len(claim_ids) != len(set(claim_ids)):
        raise LegacyInventoryError("Legacy inventory claims must be sorted and unique by claimId.")

    if not isinstance(document["snapshots"], list):
        raise LegacyInventoryError("Legacy inventory snapshots must be an array.")
    snapshot_ids: list[str] = []
    snapshot_claim_counts: Counter[str] = Counter()
    for row in document["snapshots"]:
        snapshot = _require_exact_mapping(row, _SNAPSHOT_KEYS, "Legacy inventory snapshot")
        if not _nonempty_string(snapshot["snapshotId"]):
            raise LegacyInventoryError("Legacy inventory snapshot has an invalid snapshotId.")
        _require_nonnegative_int(snapshot["claimCount"], "Legacy inventory snapshot claimCount")
        snapshot_ids.append(snapshot["snapshotId"])
        snapshot_claim_counts[snapshot["snapshotId"]] = snapshot["claimCount"]
    if snapshot_ids != sorted(snapshot_ids) or len(snapshot_ids) != len(set(snapshot_ids)):
        raise LegacyInventoryError("Legacy inventory snapshots must be sorted and unique by snapshotId.")
    referenced_snapshot_counts: Counter[str] = Counter()
    for claim in document["claims"]:
        snapshot_id = claim["sourceSnapshotId"]
        present = claim["sourceSnapshotPresent"]
        if (snapshot_id in snapshot_claim_counts) != present:
            raise LegacyInventoryError("Legacy inventory claim has inconsistent snapshot presence metadata.")
        if present:
            referenced_snapshot_counts[snapshot_id] += 1
    if any(snapshot_claim_counts[snapshot_id] != referenced_snapshot_counts[snapshot_id] for snapshot_id in snapshot_ids):
        raise LegacyInventoryError("Legacy inventory snapshot claim counts do not match claim references.")

    if not isinstance(document["conflicts"], list):
        raise LegacyInventoryError("Legacy inventory conflicts must be an array.")
    conflict_claim_ids: set[str] = set()
    conflict_cells: list[str] = []
    for row in document["conflicts"]:
        conflict = _require_exact_mapping(row, _CONFLICT_KEYS, "Legacy inventory conflict")
        if not isinstance(conflict["cell"], dict) or not isinstance(conflict["claimIds"], list):
            raise LegacyInventoryError("Legacy inventory conflict has invalid cell or claim IDs.")
        ids = conflict["claimIds"]
        if len(ids) < 2 or any(not _nonempty_string(claim_id) for claim_id in ids) or ids != sorted(ids):
            raise LegacyInventoryError("Legacy inventory conflicts need sorted unique claim IDs.")
        if len(ids) != len(set(ids)):
            raise LegacyInventoryError("Legacy inventory conflict repeats a claim ID.")
        conflict_cells.append(_cell_sort_key(conflict["cell"]))
        conflict_claim_ids.update(ids)
    if conflict_cells != sorted(conflict_cells) or len(conflict_cells) != len(set(conflict_cells)):
        raise LegacyInventoryError("Legacy inventory conflicts must be sorted and unique by cell.")

    summary = _require_exact_mapping(document["summary"], _SUMMARY_KEYS, "Legacy inventory summary")
    if summary["candidateProjectionStatus"] not in {"candidate", "conflict"}:
        raise LegacyInventoryError("Legacy inventory has an invalid candidate projection status.")
    if not isinstance(summary["reportOnlyQuarantine"], bool) or not summary["reportOnlyQuarantine"]:
        raise LegacyInventoryError("Legacy inventory must state its report-only quarantine semantics.")
    _require_nonnegative_int(summary["selectedCellCount"], "Legacy inventory selectedCellCount")
    evidence_counts = _require_exact_mapping(
        summary["evidenceCounts"], _EVIDENCE_COUNT_KEYS, "Legacy inventory evidenceCounts"
    )
    for key in _EVIDENCE_COUNT_KEYS:
        _require_nonnegative_int(evidence_counts[key], f"Legacy inventory evidenceCounts {key}")
    if evidence_counts != {
        "claimsWithEvidenceLocation": sum(
            int(
                isinstance(claim["evidence"], dict)
                and claim["evidence"].get("hasLocation") is True
            )
            for claim in document["claims"]
        ),
        "claimsWithEvidenceText": sum(
            int(
                isinstance(claim["evidence"], dict)
                and claim["evidence"].get("hasEvidenceText") is True
            )
            for claim in document["claims"]
        ),
        "snapshotsWithContentHash": sum(
            int(_nonempty_string(snapshot["contentSha256"])) for snapshot in document["snapshots"]
        ),
    }:
        raise LegacyInventoryError("Legacy inventory evidence counts do not match its rows.")
    if summary["explicitQuarantineDecisionCount"] != explicit_quarantines:
        raise LegacyInventoryError("Legacy inventory quarantine-decision count does not match claims.")
    if summary["explicitRevocationDecisionCount"] != explicit_revocations:
        raise LegacyInventoryError("Legacy inventory revocation-decision count does not match claims.")
    disposition_rows = _validate_count_rows(summary["dispositionCounts"], "Legacy inventory dispositionCounts")
    omission_rows = _validate_count_rows(summary["omissionReasonCounts"], "Legacy inventory omissionReasonCounts")
    signal_rows = _validate_count_rows(summary["observedRiskSignalCounts"], "Legacy inventory observedRiskSignalCounts")

    if manifest["claimCount"] != len(claim_ids) or manifest["snapshotCount"] != len(snapshot_ids):
        raise LegacyInventoryError("Legacy inventory manifest counts do not match its rows.")
    if manifest["candidateClaimCount"] != dispositions["candidate"]:
        raise LegacyInventoryError("Legacy inventory candidate count does not match claim dispositions.")
    if manifest["excludedClaimCount"] != dispositions["omitted"]:
        raise LegacyInventoryError("Legacy inventory excluded count does not match claim dispositions.")
    if manifest["conflictedClaimCount"] != dispositions["conflicted"]:
        raise LegacyInventoryError("Legacy inventory conflicted count does not match claim dispositions.")
    if manifest["conflictCellCount"] != len(conflict_cells):
        raise LegacyInventoryError("Legacy inventory conflict-cell count does not match conflicts.")
    if summary["candidateProjectionStatus"] == "conflict":
        if not conflict_cells or summary["selectedCellCount"] != 0:
            raise LegacyInventoryError("A conflicted inventory cannot claim selected candidate cells.")
    elif conflict_cells or summary["selectedCellCount"] != dispositions["candidate"]:
        raise LegacyInventoryError("A conflict-free inventory has inconsistent selected cells.")
    if {row["code"]: row["count"] for row in disposition_rows} != dict(sorted(dispositions.items())):
        raise LegacyInventoryError("Legacy inventory disposition summary does not match claims.")
    if {row["code"]: row["count"] for row in omission_rows} != dict(sorted(omission_reasons.items())):
        raise LegacyInventoryError("Legacy inventory omission summary does not match claims.")
    if {row["code"]: row["count"] for row in signal_rows} != dict(sorted(observed_risk_signals.items())):
        raise LegacyInventoryError("Legacy inventory risk-signal summary does not match claims.")
    claim_by_id = {row["claimId"]: row for row in document["claims"]}
    if not conflict_claim_ids <= set(claim_by_id):
        raise LegacyInventoryError("Legacy inventory conflict references an unknown claim.")
    if any(claim_by_id[claim_id]["reportDisposition"] != "conflicted" for claim_id in conflict_claim_ids):
        raise LegacyInventoryError("Legacy inventory conflict claims must have conflicted disposition.")
    if sum(snapshot_claim_counts.values()) > len(claim_ids):
        raise LegacyInventoryError("Legacy inventory snapshot counts exceed total claims.")
    if digest != legacy_inventory_digest(document):
        raise LegacyInventoryError("Legacy inventory manifest content digest does not match the report.")
    return document
