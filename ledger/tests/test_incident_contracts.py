from __future__ import annotations

from copy import deepcopy
import json
import math
from pathlib import Path

import pytest

from app.schemas.incident_contracts import (
    IncidentContractError,
    contract_self_digest,
    derive_incident_event_id,
    derive_work_event_id,
    incident_fingerprint,
    notification_intent_dedupe_key,
    notification_receipt_dedupe_key,
    payload_digest,
    validate_incident_notification_binding,
    validate_notification_intent,
    validate_notification_pair,
    validate_notification_receipt,
    validate_ops_incident,
    validate_review_work_item,
    work_item_fingerprint,
)


ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / "docs" / "contracts"
EXAMPLES = CONTRACTS / "examples"


def _load(name: str) -> dict:
    return json.loads((EXAMPLES / f"{name}.valid.json").read_text(encoding="utf-8"))


def _incident() -> dict:
    return _load("ops-incident-v1")


def _work() -> dict:
    return _load("review-work-item-v1")


def _intent() -> dict:
    return _load("notification-intent-v1")


def _receipt() -> dict:
    return _load("notification-receipt-v1")


def _resign(payload: dict) -> None:
    payload["manifest"]["contentSha256"] = "0" * 64
    payload["manifest"]["contentSha256"] = contract_self_digest(payload)


def _rechain_incident(payload: dict) -> None:
    fingerprint = incident_fingerprint(payload)
    payload["incidentFingerprintSha256"] = fingerprint
    payload["incidentId"] = "incident-" + fingerprint
    prior = None
    occurrences = []
    for event in sorted(payload["events"], key=lambda row: row["eventOrdinal"]):
        event["expectedPriorEventId"] = prior
        event["eventId"] = derive_incident_event_id(
            fingerprint, event["eventOrdinal"], prior, event["eventType"], event["occurredAt"]
        )
        prior = event["eventId"]
        if event["eventType"] in {"OPENED", "OCCURRENCE_RECORDED", "REOPENED"}:
            occurrences.append(event["occurredAt"])
    payload["currentState"] = sorted(payload["events"], key=lambda row: row["eventOrdinal"])[-1]["toState"]
    payload["occurrenceCount"] = len(occurrences)
    payload["firstOccurredAt"], payload["lastOccurredAt"] = occurrences[0], occurrences[-1]
    payload["manifest"]["eventCount"] = len(payload["events"])


def _append_incident_event(
    payload: dict,
    event_type: str,
    to_state: str,
    occurred_at: str,
    *,
    resolution_ref: dict | None = None,
) -> None:
    prior = max(payload["events"], key=lambda row: row["eventOrdinal"])
    payload["events"].append(
        {
            "eventId": "placeholder",
            "eventOrdinal": len(payload["events"]) + 1,
            "eventType": event_type,
            "expectedPriorEventId": prior["eventId"],
            "fromState": prior["toState"],
            "toState": to_state,
            "occurredAt": occurred_at,
            "actorRole": "operations-owner",
            "reasonCode": event_type + "_BY_FIXTURE",
            "acknowledgementEvidenceRef": None,
            "resolutionEvidenceRef": deepcopy(resolution_ref),
            "safeContext": {
                "contextCode": "SYNTHETIC_FIXTURE_ONLY",
                "sourceControlledDataIncluded": False,
            },
        }
    )
    _rechain_incident(payload)


def _closed_then_reopened() -> dict:
    payload = _incident()
    _append_incident_event(payload, "MITIGATED", "MITIGATED", "2026-07-15T00:20:00Z")
    evidence = {"evidenceId": "resolution-evidence-fixture-v1", "contentSha256": "b" * 64}
    payload["resolutionEvidenceRefs"] = [evidence]
    payload["manifest"]["resolutionEvidenceReferenceCount"] = 1
    _append_incident_event(payload, "RESOLVED", "RESOLVED", "2026-07-15T00:30:00Z", resolution_ref=evidence)
    _append_incident_event(payload, "CLOSED", "CLOSED", "2026-07-15T00:40:00Z")
    _append_incident_event(payload, "REOPENED", "OPEN", "2026-07-15T01:00:00Z")
    payload["sla"]["acknowledgedAt"] = None
    payload["sla"]["mitigatedAt"] = None
    _resign(payload)
    return payload


def _resolved_incident(*, mode: str = "synthetic_fixture") -> dict:
    payload = _incident()
    _append_incident_event(payload, "MITIGATED", "MITIGATED", "2026-07-15T00:20:00Z")
    evidence = {"evidenceId": "resolution-evidence-fixture-v1", "contentSha256": "b" * 64}
    payload["resolutionEvidenceRefs"] = [evidence]
    payload["manifest"]["resolutionEvidenceReferenceCount"] = 1
    _append_incident_event(payload, "RESOLVED", "RESOLVED", "2026-07-15T00:30:00Z", resolution_ref=evidence)
    payload["sla"]["mitigatedAt"] = "2026-07-15T00:20:00Z"
    payload["mode"] = mode
    _resign(payload)
    return payload


def _append_work_event(payload: dict, event_type: str, to_state: str, at: str, *, decision: str | None = None, review_at: str | None = None) -> None:
    prior = max(payload["events"], key=lambda row: row["eventOrdinal"])
    event = {
        "eventId": "placeholder",
        "eventOrdinal": len(payload["events"]) + 1,
        "eventType": event_type,
        "expectedPriorEventId": prior["eventId"],
        "fromState": prior["toState"],
        "toState": to_state,
        "occurredAt": at,
        "actorRole": "identity-reviewer",
        "reasonCode": event_type + "_BY_FIXTURE",
        "decisionReference": decision,
        "nextReviewAt": review_at,
        "safeContext": {"contextCode": "SYNTHETIC_FIXTURE_ONLY", "sourceControlledDataIncluded": False},
    }
    event["eventId"] = derive_work_event_id(
        payload["workItemFingerprintSha256"], event["eventOrdinal"], prior["eventId"], event_type, at
    )
    payload["events"].append(event)
    payload["currentState"] = to_state
    payload["duePolicy"]["nextReviewAt"] = review_at if to_state == "DEFERRED" else None
    if to_state in {"RESOLVED", "REJECTED", "BLOCKED"}:
        payload["duePolicy"]["terminalAt"] = at
    payload["manifest"]["eventCount"] = len(payload["events"])
    _resign(payload)


def _blocked_external_intent() -> dict:
    payload = _intent()
    payload["route"].update(
        {
            "routeId": "email-route-fixture-v1",
            "routeType": "email",
            "external": True,
            "authorityStatus": "externally_blocked",
            "failureDomain": "primary_outbox",
        }
    )
    payload["dispatchEligibility"] = "blocked_authority"
    dedupe = notification_intent_dedupe_key(payload)
    payload["dedupeKeySha256"] = dedupe
    payload["intentId"] = "notification-intent-" + dedupe
    _resign(payload)
    return payload


def _approved_external_intent() -> dict:
    payload = _blocked_external_intent()
    payload["mode"] = "shadow"
    payload["route"].update(
        {"authorityStatus": "approved_external", "authorityDecisionReference": "route-decision-fixture-v1"}
    )
    payload["dispatchEligibility"] = "eligible_external"
    for key in (
        "dataMinimizationDecisionReference", "recipientAuthorityDecisionReference",
        "retentionDecisionReference", "authenticationDecisionReference", "ownerDecisionReference",
    ):
        payload["authority"][key] = key.lower()
    _resign(payload)
    return payload


def _recovery_intent(incident: dict) -> dict:
    payload = _approved_external_intent()
    latest = max(incident["events"], key=lambda row: row["eventOrdinal"])
    payload.update(
        {
            "incidentId": incident["incidentId"],
            "incidentFingerprintSha256": incident["incidentFingerprintSha256"],
            "incidentFamily": incident["family"],
            "incidentCode": incident["incidentCode"],
            "incidentEventId": latest["eventId"],
            "incidentEventType": latest["eventType"],
            "notificationKind": "recovery",
            "severity": incident["severity"],
        }
    )
    payload["payload"].update(
        {
            "environment": incident["environment"],
            "incidentId": incident["incidentId"],
            "incidentCode": incident["incidentCode"],
            "severity": incident["severity"],
            "currentState": incident["currentState"],
            "occurrenceCount": incident["occurrenceCount"],
            "runbookId": incident["runbookId"],
            "nextActionCode": incident["nextActionCode"],
            "recoveryState": "recovered",
        }
    )
    payload["payloadSha256"] = payload_digest(payload["payload"])
    dedupe = notification_intent_dedupe_key(payload)
    payload["dedupeKeySha256"] = dedupe
    payload["intentId"] = "notification-intent-" + dedupe
    _resign(payload)
    return payload


def _rebind_receipt(receipt: dict, intent: dict) -> None:
    receipt["intentBinding"].update(
        {
            "intentId": intent["intentId"],
            "intentContentSha256": intent["manifest"]["contentSha256"],
            "intentDedupeKeySha256": intent["dedupeKeySha256"],
            "payloadSha256": intent["payloadSha256"],
            "routeId": intent["route"]["routeId"],
        }
    )
    dedupe = notification_receipt_dedupe_key(receipt)
    receipt["receiptDedupeKeySha256"] = dedupe
    receipt["receiptId"] = "notification-receipt-" + dedupe
    _resign(receipt)


def _approved_delivery_receipt(intent: dict) -> dict:
    receipt = _receipt()
    receipt.update({"mode": "shadow", "routeAuthorityStatus": "approved_external", "outcome": "delivered"})
    receipt["attempts"][0].update({"outcome": "delivered", "causeCode": "DELIVERY_CONFIRMED"})
    _rebind_receipt(receipt, intent)
    return receipt


def test_four_synthetic_examples_are_valid_and_non_authoritative() -> None:
    incident, work, intent, receipt = _incident(), _work(), _intent(), _receipt()
    validate_ops_incident(incident)
    validate_review_work_item(work)
    validate_notification_pair(intent, receipt)
    assert {incident["mode"], work["mode"], intent["mode"], receipt["mode"]} == {"synthetic_fixture"}
    assert incident["authority"]["authorizesPublication"] is False
    assert receipt["effects"] == {"acknowledgesIncident": False, "resolvesIncident": False, "mutatesEvidence": False}


def test_contract_schemas_are_draft_2020_12_closed_objects() -> None:
    for name in ("ops-incident-v1", "review-work-item-v1", "notification-intent-v1", "notification-receipt-v1"):
        schema = json.loads((CONTRACTS / f"{name}.schema.json").read_text(encoding="utf-8"))
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert schema["additionalProperties"] is False


def test_example_self_digests_and_manifest_denominators_are_exact() -> None:
    incident, work, intent, receipt = _incident(), _work(), _intent(), _receipt()
    for payload in (incident, work, intent, receipt):
        assert contract_self_digest(payload) == payload["manifest"]["contentSha256"]
    assert incident["manifest"]["eventCount"] == len(incident["events"])
    assert work["manifest"]["subjectReferenceCount"] == len(work["subjectRefs"])
    assert receipt["manifest"]["attemptCount"] == len(receipt["attempts"])


def test_incident_reopen_preserves_fingerprint_and_counts_a_new_occurrence() -> None:
    payload = _closed_then_reopened()
    original = _incident()["incidentFingerprintSha256"]
    validate_ops_incident(payload)
    assert payload["incidentFingerprintSha256"] == original
    assert payload["occurrenceCount"] == 2
    assert payload["currentState"] == "OPEN"


def test_incident_may_reopen_directly_from_resolved_before_closure() -> None:
    payload = _incident()
    _append_incident_event(payload, "MITIGATED", "MITIGATED", "2026-07-15T00:20:00Z")
    evidence = {"evidenceId": "resolution-evidence-fixture-v1", "contentSha256": "b" * 64}
    payload["resolutionEvidenceRefs"] = [evidence]
    payload["manifest"]["resolutionEvidenceReferenceCount"] = 1
    _append_incident_event(payload, "RESOLVED", "RESOLVED", "2026-07-15T00:30:00Z", resolution_ref=evidence)
    _append_incident_event(payload, "REOPENED", "OPEN", "2026-07-15T00:40:00Z")
    payload["sla"]["acknowledgedAt"] = None
    payload["sla"]["mitigatedAt"] = None
    _resign(payload)
    validate_ops_incident(payload)
    assert payload["occurrenceCount"] == 2


@pytest.mark.parametrize(
    ("index", "field", "value", "match"),
    [
        (1, "expectedPriorEventId", "incident-event-stale", "expectedPrior"),
        (2, "fromState", "OPEN", "illegal incident state"),
        (2, "toState", "MITIGATED", "illegal incident state"),
        (1, "eventOrdinal", 1, "contiguous"),
    ],
)
def test_incident_rejects_stale_branched_or_illegal_event_chains(index: int, field: str, value: object, match: str) -> None:
    payload = _incident()
    payload["events"][index][field] = value
    _resign(payload)
    with pytest.raises(IncidentContractError, match=match):
        validate_ops_incident(payload)


def test_active_duplicate_occurrence_reuses_fingerprint_and_updates_exact_count() -> None:
    payload = _incident()
    _append_incident_event(payload, "OCCURRENCE_RECORDED", "INVESTIGATING", "2026-07-15T00:15:00Z")
    _resign(payload)
    validate_ops_incident(payload)
    assert payload["occurrenceCount"] == 2
    assert payload["firstOccurredAt"] != payload["lastOccurredAt"]


def test_active_duplicate_occurrence_does_not_move_current_episode_sla_deadlines() -> None:
    payload = _incident()
    payload.update({"severity": "SEV1", "severityBasis": "escalated_by_decision", "severityDecisionReference": "severity-decision-fixture-v1"})
    next(tag for tag in payload["tags"] if tag["tagKey"] == "sev")["tagValue"] = "SEV1"
    payload["sla"].update(
        {
            "policyStatus": "approved", "policyDecisionReference": "sla-decision-fixture-v1",
            "calculationStatus": "active", "clockType": "elapsed_utc",
            "acknowledgeWithinSeconds": 1800, "mitigateWithinSeconds": 14400,
            "acknowledgeDueAt": "2026-07-15T00:30:00Z", "mitigateDueAt": "2026-07-15T04:00:00Z",
            "acknowledgedOnTime": True,
        }
    )
    _append_incident_event(payload, "OCCURRENCE_RECORDED", "INVESTIGATING", "2026-07-15T00:15:00Z")
    _resign(payload)
    validate_ops_incident(payload)
    assert payload["lastOccurredAt"] == "2026-07-15T00:15:00Z"
    assert payload["sla"]["acknowledgeDueAt"] == "2026-07-15T00:30:00Z"


def test_fingerprint_and_digest_are_invariant_to_set_and_event_reordering() -> None:
    payload = _incident()
    payload["affectedRefs"].append({"referenceType": "job", "referenceId": "scheduled-job-example"})
    payload["manifest"]["affectedReferenceCount"] = 2
    _rechain_incident(payload)
    _resign(payload)
    reordered = deepcopy(payload)
    reordered["affectedRefs"].reverse()
    reordered["tags"].reverse()
    reordered["events"].reverse()
    assert incident_fingerprint(payload) == incident_fingerprint(reordered)
    assert contract_self_digest(payload) == contract_self_digest(reordered)
    validate_ops_incident(reordered)


def test_duplicate_affected_reference_fails_closed() -> None:
    payload = _incident()
    payload["affectedRefs"].append(deepcopy(payload["affectedRefs"][0]))
    payload["manifest"]["affectedReferenceCount"] = 2
    _resign(payload)
    with pytest.raises(IncidentContractError, match="duplicate typed reference"):
        validate_ops_incident(payload)


@pytest.mark.parametrize("bad", ["SEV0", "SEV1", "SEV3"])
def test_taxonomy_default_severity_cannot_be_relabelled(bad: str) -> None:
    payload = _incident()
    payload["severity"] = bad
    _resign(payload)
    with pytest.raises(IncidentContractError, match="taxonomy default"):
        validate_ops_incident(payload)


def test_stricter_severity_requires_append_only_decision_reference() -> None:
    payload = _incident()
    payload.update({"severity": "SEV1", "severityBasis": "escalated_by_decision", "severityDecisionReference": "severity-decision-fixture-v1"})
    next(tag for tag in payload["tags"] if tag["tagKey"] == "sev")["tagValue"] = "SEV1"
    payload["sla"].update(
        {
            "policyStatus": "approved",
            "policyDecisionReference": "sla-decision-fixture-v1",
            "calculationStatus": "active",
            "clockType": "elapsed_utc",
            "acknowledgeWithinSeconds": 1800,
            "mitigateWithinSeconds": 14400,
            "acknowledgeDueAt": "2026-07-15T00:30:00Z",
            "mitigateDueAt": "2026-07-15T04:00:00Z",
            "acknowledgedOnTime": True,
        }
    )
    _resign(payload)
    validate_ops_incident(payload)


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("acknowledgeWithinSeconds", 1801, "severity targets"),
        ("acknowledgeDueAt", "2026-07-15T00:31:00Z", "derive exactly"),
        ("acknowledgedOnTime", False, "acknowledgedOnTime"),
    ],
)
def test_elapsed_sla_contradictions_fail(field: str, value: object, match: str) -> None:
    payload = _incident()
    payload.update({"severity": "SEV1", "severityBasis": "escalated_by_decision", "severityDecisionReference": "severity-decision-fixture-v1"})
    next(tag for tag in payload["tags"] if tag["tagKey"] == "sev")["tagValue"] = "SEV1"
    payload["sla"].update(
        {
            "policyStatus": "approved", "policyDecisionReference": "sla-decision-fixture-v1",
            "calculationStatus": "active", "clockType": "elapsed_utc",
            "acknowledgeWithinSeconds": 1800, "mitigateWithinSeconds": 14400,
            "acknowledgeDueAt": "2026-07-15T00:30:00Z", "mitigateDueAt": "2026-07-15T04:00:00Z",
            "acknowledgedOnTime": True,
        }
    )
    payload["sla"][field] = value
    _resign(payload)
    with pytest.raises(IncidentContractError, match=match):
        validate_ops_incident(payload)


def test_acknowledgement_and_resolution_evidence_are_not_interchangeable() -> None:
    payload = _incident()
    payload["events"][1]["resolutionEvidenceRef"] = payload["events"][1]["acknowledgementEvidenceRef"]
    payload["events"][1]["acknowledgementEvidenceRef"] = None
    _resign(payload)
    with pytest.raises(IncidentContractError, match="acknowledgement requires separate"):
        validate_ops_incident(payload)


def test_resolution_evidence_must_match_both_listed_id_and_digest() -> None:
    payload = _resolved_incident()
    resolved = next(event for event in payload["events"] if event["eventType"] == "RESOLVED")
    resolved["resolutionEvidenceRef"]["contentSha256"] = "c" * 64
    _resign(payload)
    with pytest.raises(IncidentContractError, match="target-perspective"):
        validate_ops_incident(payload)


def test_containment_requires_decision_and_cannot_mutate_evidence() -> None:
    payload = _incident()
    payload["containmentRefs"] = [{"containmentId": "pause-fixture-v1", "actionType": "paused", "decisionReference": "pause-decision-v1", "affectedRef": payload["affectedRefs"][0]}]
    payload["manifest"]["containmentReferenceCount"] = 1
    _resign(payload)
    validate_ops_incident(payload)
    payload["authority"]["mutatesEvidence"] = True
    _resign(payload)
    with pytest.raises(IncidentContractError, match="mutatesEvidence"):
        validate_ops_incident(payload)


def test_containment_must_target_an_exact_affected_reference() -> None:
    payload = _incident()
    payload["containmentRefs"] = [
        {
            "containmentId": "pause-fixture-v1", "actionType": "paused",
            "decisionReference": "pause-decision-v1",
            "affectedRef": {"referenceType": "job", "referenceId": "unaffected-job"},
        }
    ]
    payload["manifest"]["containmentReferenceCount"] = 1
    _resign(payload)
    with pytest.raises(IncidentContractError, match="exact affected reference"):
        validate_ops_incident(payload)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("area", "fetch"), ("sev", "SEV1"), ("state", "OPEN"),
        ("owner", "different-owner"), ("cause", "DIFFERENT_CAUSE"),
        ("source", "unaffected-source"),
    ],
)
def test_reserved_incident_tags_cannot_contradict_bound_facts(key: str, value: str) -> None:
    payload = _incident()
    existing = next((tag for tag in payload["tags"] if tag["tagKey"] == key), None)
    if existing is None:
        payload["tags"].append({"tagKey": key, "tagValue": value})
    else:
        existing["tagValue"] = value
    payload["manifest"]["tagCount"] = len(payload["tags"])
    _resign(payload)
    with pytest.raises(IncidentContractError, match="reserved|source tag"):
        validate_ops_incident(payload)


def test_malformed_or_nonfinite_incident_rows_fail_with_typed_contract_error() -> None:
    for value in ("not-an-event", math.nan):
        payload = _incident()
        if isinstance(value, str):
            payload["events"].append(value)
        else:
            payload["occurrenceCount"] = value
        with pytest.raises(IncidentContractError):
            validate_ops_incident(payload)


def test_work_claim_defer_reopen_and_resolve_chain_is_explicit() -> None:
    payload = _work()
    _append_work_event(payload, "CLAIMED", "CLAIMED", "2026-07-15T00:20:00Z")
    _append_work_event(payload, "DEFERRED", "DEFERRED", "2026-07-15T00:30:00Z", review_at="2026-07-16T00:30:00Z")
    _append_work_event(payload, "REOPENED", "OPEN", "2026-07-16T00:30:00Z")
    _append_work_event(payload, "RESOLVED", "RESOLVED", "2026-07-16T01:00:00Z", decision="identity-decision-fixture-v1")
    validate_review_work_item(payload)
    assert payload["duePolicy"]["onTime"] is None
    assert payload["authority"]["timeoutMayApprove"] is False


def test_work_terminal_action_requires_decision_not_timeout() -> None:
    payload = _work()
    _append_work_event(payload, "RESOLVED", "RESOLVED", "2026-07-15T01:00:00Z")
    with pytest.raises(IncidentContractError, match="explicit decision"):
        validate_review_work_item(payload)


def test_work_deferral_requires_exact_current_review_time() -> None:
    payload = _work()
    _append_work_event(payload, "DEFERRED", "DEFERRED", "2026-07-15T00:30:00Z", review_at="2026-07-16T00:30:00Z")
    payload["duePolicy"]["nextReviewAt"] = "2026-07-17T00:30:00Z"
    _resign(payload)
    with pytest.raises(IncidentContractError, match="nextReviewAt"):
        validate_review_work_item(payload)


@pytest.mark.parametrize("field", ["authorizesCapture", "authorizesPublication", "timeoutMayApprove", "mutatesEvidence"])
def test_work_item_never_inherits_authority(field: str) -> None:
    payload = _work()
    payload["authority"][field] = True
    _resign(payload)
    with pytest.raises(IncidentContractError, match=field):
        validate_review_work_item(payload)


def test_release_conflict_work_cannot_clear_publication_block() -> None:
    payload = _work()
    payload.update({"workClass": "display_conflict", "reasonCode": "DISPLAY_CELL_DUPLICATE", "publicationBlocking": False})
    fingerprint = work_item_fingerprint(payload)
    payload["workItemFingerprintSha256"] = fingerprint
    payload["workItemId"] = "work-item-" + fingerprint
    payload["events"][0]["eventId"] = derive_work_event_id(fingerprint, 1, None, "CREATED", payload["events"][0]["occurredAt"])
    _resign(payload)
    with pytest.raises(IncidentContractError, match="release block"):
        validate_review_work_item(payload)


def test_work_manifest_denominators_and_stale_prior_fail_closed() -> None:
    payload = _work()
    payload["manifest"]["subjectReferenceCount"] = 2
    _resign(payload)
    with pytest.raises(IncidentContractError, match="subjectReferenceCount"):
        validate_review_work_item(payload)
    payload = _work()
    _append_work_event(payload, "CLAIMED", "CLAIMED", "2026-07-15T00:20:00Z")
    payload["events"][1]["expectedPriorEventId"] = "work-event-stale"
    _resign(payload)
    with pytest.raises(IncidentContractError, match="expectedPrior"):
        validate_review_work_item(payload)


def test_work_item_identity_is_separated_by_environment() -> None:
    shadow = _work()
    production = deepcopy(shadow)
    production["environment"] = "production"
    assert work_item_fingerprint(shadow) != work_item_fingerprint(production)
    fingerprint = work_item_fingerprint(production)
    production["workItemFingerprintSha256"] = fingerprint
    production["workItemId"] = "work-item-" + fingerprint
    production["events"][0]["eventId"] = derive_work_event_id(
        fingerprint, 1, None, "CREATED", production["events"][0]["occurredAt"]
    )
    _resign(production)
    validate_review_work_item(production)


def test_notification_payload_is_exactly_redacted_and_cross_bound() -> None:
    payload = _intent()
    payload["payload"]["severity"] = "SEV1"
    payload["payloadSha256"] = payload_digest(payload["payload"])
    _resign(payload)
    with pytest.raises(IncidentContractError, match="payload.severity"):
        validate_notification_intent(payload)


def test_intent_binds_exact_latest_incident_event_and_redacted_incident_facts() -> None:
    validate_incident_notification_binding(_incident(), _intent())


@pytest.mark.parametrize(
    ("location", "field", "value"),
    [
        ("root", "incidentEventId", "incident-event-stale"),
        ("root", "incidentFingerprintSha256", "f" * 64),
        ("root", "incidentFamily", "FETCH"),
        ("payload", "environment", "different-environment"),
        ("payload", "occurrenceCount", 2),
        ("payload", "runbookId", "different-runbook"),
        ("payload", "nextActionCode", "DIFFERENT_ACTION"),
    ],
)
def test_incident_intent_cross_binding_rejects_stale_or_mixed_facts(location: str, field: str, value: object) -> None:
    intent = _intent()
    target = intent if location == "root" else intent["payload"]
    target[field] = value
    if field == "incidentFamily":
        intent["incidentCode"] = "TRANSIENT"
        intent["payload"]["incidentCode"] = "TRANSIENT"
        intent["payloadSha256"] = payload_digest(intent["payload"])
    if location == "payload":
        intent["payloadSha256"] = payload_digest(intent["payload"])
    if field in {"incidentEventId", "incidentFingerprintSha256"}:
        dedupe = notification_intent_dedupe_key(intent)
        intent["dedupeKeySha256"] = dedupe
        intent["intentId"] = "notification-intent-" + dedupe
    _resign(intent)
    with pytest.raises(IncidentContractError, match="exact latest incident|exact incident fact"):
        validate_incident_notification_binding(_incident(), intent)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("rawModel", "vendor/raw-model"),
        ("score", "99.7"),
        ("sourceUrl", "https://origin.invalid/?token=secret"),
        ("query", "?api_key=sk-live"),
        ("path", "../../secret"),
        ("html", "<script>alert(1)</script>"),
        ("markdown", "[click](https://evil.invalid)"),
    ],
)
def test_notification_payload_rejects_unallowlisted_source_or_secret_fields(field: str, value: str) -> None:
    payload = _intent()
    payload["payload"][field] = value
    with pytest.raises(IncidentContractError, match="fields mismatch"):
        validate_notification_intent(payload)


@pytest.mark.parametrize("value", ["<b>runbook</b>", "../../etc/passwd", "runbook\u0000secret", "token=sk-live", "[markdown]"])
def test_notification_allowlisted_identifiers_reject_markup_control_secret_and_path_lexemes(value: str) -> None:
    payload = _intent()
    payload["payload"]["runbookId"] = value
    with pytest.raises(IncidentContractError, match="stable lowercase"):
        validate_notification_intent(payload)


def test_external_route_cannot_escalate_without_all_authority_decisions() -> None:
    payload = _blocked_external_intent()
    validate_notification_intent(payload)
    payload["route"].update({"authorityStatus": "approved_external", "authorityDecisionReference": "route-decision-v1"})
    payload["dispatchEligibility"] = "eligible_external"
    payload["mode"] = "shadow"
    _resign(payload)
    with pytest.raises(IncidentContractError, match="every privacy"):
        validate_notification_intent(payload)


def test_synthetic_fixture_can_never_be_approved_for_external_dispatch() -> None:
    payload = _blocked_external_intent()
    payload["route"].update({"authorityStatus": "approved_external", "authorityDecisionReference": "route-decision-v1"})
    payload["dispatchEligibility"] = "eligible_external"
    for key in (
        "dataMinimizationDecisionReference", "recipientAuthorityDecisionReference",
        "retentionDecisionReference", "authenticationDecisionReference", "ownerDecisionReference",
    ):
        payload["authority"][key] = key.lower()
    _resign(payload)
    with pytest.raises(IncidentContractError, match="real mode"):
        validate_notification_intent(payload)


def test_notification_family_incident_is_recursively_suppressed() -> None:
    payload = _intent()
    payload.update({"incidentFamily": "NOTIFY", "incidentCode": "DELIVERY_FAILED"})
    payload["payload"]["incidentCode"] = "DELIVERY_FAILED"
    payload["recursionDisposition"] = "suppressed_notify_family"
    payload["dispatchEligibility"] = "suppressed_recursive"
    payload["payloadSha256"] = payload_digest(payload["payload"])
    dedupe = notification_intent_dedupe_key(payload)
    payload["dedupeKeySha256"] = dedupe
    payload["intentId"] = "notification-intent-" + dedupe
    _resign(payload)
    validate_notification_intent(payload)
    payload["recursionDisposition"] = "not_recursive"
    _resign(payload)
    with pytest.raises(IncidentContractError, match="recursive storms"):
        validate_notification_intent(payload)


def test_recovery_kind_binds_resolved_latest_incident_and_exact_recovery_receipt() -> None:
    incident = _resolved_incident(mode="shadow")
    intent = _recovery_intent(incident)
    receipt = _approved_delivery_receipt(intent)
    receipt["outcome"] = "recovery_delivered"
    receipt["recovery"] = {
        "priorReceiptId": "prior-failed-receipt-v1",
        "recoveryIntentId": intent["intentId"],
        "recoveredAt": "2026-07-15T00:31:00Z",
    }
    _resign(receipt)
    validate_incident_notification_binding(incident, intent)
    validate_notification_pair(intent, receipt)


def test_recovery_kind_rejects_active_event_and_nonrecovery_receipt() -> None:
    intent = _approved_external_intent()
    intent["notificationKind"] = "recovery"
    intent["payload"]["recoveryState"] = "recovered"
    intent["payloadSha256"] = payload_digest(intent["payload"])
    dedupe = notification_intent_dedupe_key(intent)
    intent["dedupeKeySha256"] = dedupe
    intent["intentId"] = "notification-intent-" + dedupe
    _resign(intent)
    with pytest.raises(IncidentContractError, match="resolved/closed"):
        validate_notification_intent(intent)

    incident = _resolved_incident(mode="shadow")
    recovery_intent = _recovery_intent(incident)
    ordinary_receipt = _approved_delivery_receipt(recovery_intent)
    with pytest.raises(IncidentContractError, match="recovery notification kind"):
        validate_notification_pair(recovery_intent, ordinary_receipt)


def test_recovery_receipt_rejects_nonrecovery_intent() -> None:
    intent = _approved_external_intent()
    receipt = _approved_delivery_receipt(intent)
    receipt["outcome"] = "recovery_delivered"
    receipt["recovery"] = {
        "priorReceiptId": "prior-failed-receipt-v1",
        "recoveryIntentId": intent["intentId"],
        "recoveredAt": "2026-07-15T00:31:00Z",
    }
    _resign(receipt)
    with pytest.raises(IncidentContractError, match="recovery notification kind"):
        validate_notification_pair(intent, receipt)


def test_canary_kind_requires_and_accepts_exact_observed_canary_receipt() -> None:
    intent = _approved_external_intent()
    intent["notificationKind"] = "canary"
    dedupe = notification_intent_dedupe_key(intent)
    intent["dedupeKeySha256"] = dedupe
    intent["intentId"] = "notification-intent-" + dedupe
    _resign(intent)
    receipt = _approved_delivery_receipt(intent)
    receipt["canary"] = {
        "isCanary": True,
        "canaryId": "notification-canary-fixture-v1",
        "expectedBy": "2026-07-15T00:15:00Z",
        "observedAt": "2026-07-15T00:14:00Z",
    }
    _resign(receipt)
    validate_notification_pair(intent, receipt)

    missing_observation = deepcopy(receipt)
    missing_observation["canary"]["observedAt"] = None
    _resign(missing_observation)
    with pytest.raises(IncidentContractError, match="observed canary"):
        validate_notification_pair(intent, missing_observation)


def test_observed_canary_receipt_rejects_noncanary_intent() -> None:
    intent = _approved_external_intent()
    receipt = _approved_delivery_receipt(intent)
    receipt["canary"] = {
        "isCanary": True,
        "canaryId": "notification-canary-fixture-v1",
        "expectedBy": "2026-07-15T00:15:00Z",
        "observedAt": "2026-07-15T00:14:00Z",
    }
    _resign(receipt)
    with pytest.raises(IncidentContractError, match="observed canary"):
        validate_notification_pair(intent, receipt)


@pytest.mark.parametrize("binding_field", ["intentId", "intentContentSha256", "intentDedupeKeySha256", "payloadSha256", "routeId"])
def test_receipt_must_bind_the_exact_intent_and_payload(binding_field: str) -> None:
    intent, receipt = _intent(), _receipt()
    receipt["intentBinding"][binding_field] = "f" * 64 if binding_field.endswith("Sha256") else "fabricated-binding"
    if binding_field in {"intentId", "routeId"}:
        dedupe = notification_receipt_dedupe_key(receipt)
        receipt["receiptDedupeKeySha256"] = dedupe
        receipt["receiptId"] = "notification-receipt-" + dedupe
    _resign(receipt)
    with pytest.raises(IncidentContractError, match="exact intent"):
        validate_notification_pair(intent, receipt)


def test_receipt_self_digest_and_attempt_denominator_fail_closed() -> None:
    payload = _receipt()
    payload["manifest"]["contentSha256"] = "f" * 64
    with pytest.raises(IncidentContractError, match="self-digest"):
        validate_notification_receipt(payload)
    payload = _receipt()
    payload["manifest"]["attemptCount"] = 2
    _resign(payload)
    with pytest.raises(IncidentContractError, match="attemptCount"):
        validate_notification_receipt(payload)


def test_blocked_external_intent_and_receipt_are_valid_but_deliver_nothing() -> None:
    intent = _blocked_external_intent()
    receipt = _receipt()
    receipt.update({"routeAuthorityStatus": "externally_blocked", "outcome": "blocked_authority"})
    receipt["attempts"][0].update({"outcome": "blocked_authority", "causeCode": "EXTERNAL_AUTHORITY_BLOCKED"})
    _rebind_receipt(receipt, intent)
    validate_notification_pair(intent, receipt)


def test_receipt_outcome_cannot_escalate_blocked_route_to_delivery() -> None:
    intent = _blocked_external_intent()
    receipt = _receipt()
    receipt.update({"routeAuthorityStatus": "externally_blocked", "outcome": "delivered"})
    receipt["attempts"][0].update({"outcome": "delivered", "causeCode": "FABRICATED_DELIVERY"})
    _rebind_receipt(receipt, intent)
    with pytest.raises(IncidentContractError, match="delivery requires approved|not legal"):
        validate_notification_pair(intent, receipt)


def test_retry_chain_rejects_nontransient_predecessor_and_fourth_attempt() -> None:
    payload = _receipt()
    payload["attempts"].append(deepcopy(payload["attempts"][0]))
    payload["attempts"][1].update({"attemptNumber": 2, "startedAt": "2026-07-15T00:11:00Z", "endedAt": "2026-07-15T00:11:00Z"})
    payload["manifest"]["attemptCount"] = 2
    _resign(payload)
    with pytest.raises(IncidentContractError, match="only a transient failure"):
        validate_notification_receipt(payload)
    payload["attempts"].append(deepcopy(payload["attempts"][1]))
    payload["attempts"].append(deepcopy(payload["attempts"][1]))
    payload["manifest"]["attemptCount"] = 4
    with pytest.raises(IncidentContractError, match="bounded integer|fields mismatch|attempt"):
        validate_notification_receipt(payload)


def test_retry_exhaustion_is_exactly_three_attempts_and_respects_retry_deadlines() -> None:
    intent = _approved_external_intent()
    receipt = _receipt()
    receipt.update({"mode": "shadow", "routeAuthorityStatus": "approved_external", "outcome": "retry_exhausted"})
    receipt["attempts"] = [
        {
            "attemptNumber": 1, "startedAt": "2026-07-15T00:10:01Z", "endedAt": "2026-07-15T00:10:02Z",
            "outcome": "failed_transient", "causeCode": "PROVIDER_TIMEOUT",
            "safeProviderMessageReferenceSha256": None, "retryAt": "2026-07-15T00:11:00Z",
        },
        {
            "attemptNumber": 2, "startedAt": "2026-07-15T00:11:00Z", "endedAt": "2026-07-15T00:11:02Z",
            "outcome": "failed_transient", "causeCode": "PROVIDER_TIMEOUT",
            "safeProviderMessageReferenceSha256": None, "retryAt": "2026-07-15T00:13:00Z",
        },
        {
            "attemptNumber": 3, "startedAt": "2026-07-15T00:13:00Z", "endedAt": "2026-07-15T00:13:02Z",
            "outcome": "failed_transient", "causeCode": "PROVIDER_TIMEOUT",
            "safeProviderMessageReferenceSha256": None, "retryAt": None,
        },
    ]
    receipt["manifest"]["attemptCount"] = 3
    _rebind_receipt(receipt, intent)
    validate_notification_pair(intent, receipt)

    too_early = deepcopy(receipt)
    too_early["attempts"][1]["startedAt"] = "2026-07-15T00:10:30Z"
    _resign(too_early)
    with pytest.raises(IncidentContractError, match="prior retryAt"):
        validate_notification_receipt(too_early)

    fourth_retry = deepcopy(receipt)
    fourth_retry["attempts"][2]["retryAt"] = "2026-07-15T00:15:00Z"
    _resign(fourth_retry)
    with pytest.raises(IncidentContractError, match="fourth attempt"):
        validate_notification_receipt(fourth_retry)


def test_dead_letter_and_recovery_fields_cannot_be_fabricated() -> None:
    payload = _receipt()
    payload["deadLetter"].update({"status": "dead_lettered", "deadLetterReferenceId": "dead-letter-fixture-v1"})
    _resign(payload)
    with pytest.raises(IncidentContractError, match="non-dead-letter"):
        validate_notification_receipt(payload)
    payload = _receipt()
    payload["recovery"]["priorReceiptId"] = "prior-receipt-fixture"
    _resign(payload)
    with pytest.raises(IncidentContractError, match="recovery fields"):
        validate_notification_receipt(payload)


@pytest.mark.parametrize("field", ["acknowledgesIncident", "resolvesIncident", "mutatesEvidence"])
def test_notification_receipt_never_changes_incident_or_evidence(field: str) -> None:
    payload = _receipt()
    payload["effects"][field] = True
    _resign(payload)
    with pytest.raises(IncidentContractError, match=field):
        validate_notification_receipt(payload)


def test_notification_dedupe_and_canonical_attempt_order_are_stable() -> None:
    intent, receipt = _intent(), _receipt()
    assert notification_intent_dedupe_key(intent) == intent["dedupeKeySha256"]
    assert notification_receipt_dedupe_key(receipt) == receipt["receiptDedupeKeySha256"]
    assert payload_digest(intent["payload"]) == intent["payloadSha256"]
    assert contract_self_digest(receipt) == receipt["manifest"]["contentSha256"]


def test_nonfinite_and_mutable_payload_shapes_fail_before_receipt_creation() -> None:
    payload = _intent()
    payload["payload"]["occurrenceCount"] = math.inf
    with pytest.raises(IncidentContractError, match="non-finite"):
        validate_notification_intent(payload)
    payload = _intent()
    payload["payload"]["occurrenceCount"] = [1]
    with pytest.raises(IncidentContractError, match="unsupported JSON type|bounded integer"):
        validate_notification_intent(payload)
