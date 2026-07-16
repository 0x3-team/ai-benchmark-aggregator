from __future__ import annotations

from copy import deepcopy
from datetime import date
import json
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

import pytest

from app.schemas.source_contracts import (
    SourceContractError,
    canonical_json,
    derive_source_check_receipt_id,
    source_check_receipt_digest,
    source_contract_definition_digest,
    source_contract_digest,
    validate_source_check_receipt,
    validate_source_contract,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = REPOSITORY_ROOT / "docs" / "contracts"
EXAMPLES = CONTRACTS / "examples"


def _load(name: str) -> dict[str, Any]:
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


def _draft_contract() -> dict[str, Any]:
    return _load("source-contract-v2.valid.json")


def _blocked_receipt() -> dict[str, Any]:
    return _load("source-check-receipt-v1.valid.json")


def _sign_contract(contract: dict[str, Any]) -> dict[str, Any]:
    definition_digest = source_contract_definition_digest(contract)
    contract["manifest"]["definitionSha256"] = definition_digest
    if contract["certification"]["decisionOutcome"] != "not_assessed":
        contract["certification"][
            "decidedContractDefinitionSha256"
        ] = definition_digest
    contract["manifest"]["contentSha256"] = source_contract_digest(contract)
    return contract


def _sign_receipt(receipt: dict[str, Any]) -> dict[str, Any]:
    receipt["manifest"]["contentSha256"] = source_check_receipt_digest(receipt)
    return receipt


def _approved_contract() -> dict[str, Any]:
    contract = _draft_contract()
    contract["lifecycleStatus"] = "approved"
    contract["reasonCode"] = "EXTERNAL_CERTIFICATION_BOUND"
    contract["authority"]["approvalStatus"] = "external_certification_bound"
    contract["authority"]["captureEligible"] = True
    contract["certification"] = {
        "decisionId": "example-source-certification-r1",
        "decisionDigestSha256": "c" * 64,
        "decisionOutcome": "certified",
        "decidedSourceRevisionId": contract["logicalSource"]["sourceRevisionId"],
        "decidedContractDefinitionSha256": None,
        "effectiveOn": "2026-07-01",
        "expiresOn": "2026-12-31",
    }
    contract["termsReuse"] = {
        "status": "reviewed_permitted",
        "decisionReference": "example-reuse-decision-r1",
        "evidenceDate": "2026-06-15",
        "effectiveOn": "2026-07-01",
        "reviewDueOn": "2026-10-01",
        "expiresOn": "2026-12-31",
        "reuseScope": "Capture immutable official score reports with provenance.",
        "correctionRoute": "https://governance.example.com/corrections",
    }
    contract["implementationBinding"]["status"] = "wired_peer_verified"
    contract["implementationBinding"]["connectedPeerProof"] = "implemented_verified"
    contract["schedule"]["enabled"] = True
    return _sign_contract(contract)


def _completed_changed_receipt(contract: dict[str, Any]) -> dict[str, Any]:
    receipt = _blocked_receipt()
    certification = contract["certification"]
    identity = receipt["identity"]
    identity["contractDigestSha256"] = contract["manifest"]["contentSha256"]
    identity["contractDefinitionSha256"] = contract["manifest"]["definitionSha256"]
    identity["certificationDecisionId"] = certification["decisionId"]
    identity["certificationDecisionDigestSha256"] = certification["decisionDigestSha256"]
    receipt["availability"] = "operational_receipt_only"
    receipt["terminalDisposition"] = "completed_changed"
    receipt["reasonCode"] = "SOURCE_CHANGED_AND_ACCOUNTED"
    receipt["certificationCheck"] = {
        "outcome": "certified",
        "checkedDecisionId": certification["decisionId"],
        "checkedDecisionDigestSha256": certification["decisionDigestSha256"],
        "checkedSourceRevisionId": contract["logicalSource"]["sourceRevisionId"],
        "checkedContractDigestSha256": contract["manifest"]["contentSha256"],
        "checkedContractDefinitionSha256": contract["manifest"]["definitionSha256"],
        "checkedBeforeFetch": True,
        "checkedBeforeClaimWrite": True,
        "effectiveForAttempt": True,
    }
    receipt["request"] = {
        "disposition": "completed",
        "method": "GET",
        "requestedUrl": contract["transport"]["approvedSourceUrls"][0],
        "finalUrl": contract["transport"]["approvedFinalUrls"][0],
        "lastApprovedUrl": contract["transport"]["approvedFinalUrls"][0],
        "redirectCount": 0,
        "statusCode": 200,
        "conditionalRequestUsed": False,
        "responseBodyReceived": True,
        "failureStage": None,
        "failureCode": None,
    }
    receipt["networkEvidence"] = {
        "dnsPolicyStatus": "passed",
        "connectedPeerStatus": "passed",
        "tlsStatus": "passed",
        "connectedPeerAddressClass": "public",
        "finalHost": contract["transport"]["allowedHosts"][0],
    }
    receipt["response"] = {
        "contentChanged": True,
        "bytesReceived": 256,
        "contentSha256": "d" * 64,
        "mimeType": "application/json",
        "retryClassification": "none",
        "retryAfterSeconds": None,
    }
    receipt["conditionalMetadata"] = {
        "previousSnapshotId": None,
        "previousSnapshotContentSha256": None,
        "previousSnapshotVerificationReceiptSha256": None,
        "etagRequestSha256": None,
        "lastModifiedRequestSha256": None,
        "etagResponseSha256": "1" * 64,
        "lastModifiedResponseSha256": None,
    }
    receipt["snapshot"] = {
        "snapshotId": "example-source-snapshot-r2",
        "snapshotContentSha256": "d" * 64,
        "storageReceiptSha256": "e" * 64,
        "status": "committed_reverified",
        "immutable": True,
        "readBackVerified": True,
        "committedBeforeExtraction": True,
    }
    receipt["extraction"] = {
        "disposition": "accounted",
        "sourceRecordsObserved": 2,
        "rowsParsed": 2,
        "claimCandidatesEmitted": 2,
        "claimsAdmitted": 2,
        "recordsExcluded": 0,
        "recordsRejected": 0,
        "recordsQuarantined": 0,
        "evidenceLocatorCoverageCount": 2,
        "duplicateLocatorCount": 0,
        "unexplainedRecordCount": 0,
        "schemaFingerprintSha256": contract["drift"]["approvedSchemaSha256"],
        "batchReceiptSha256": "f" * 64,
        "dimensionsObserved": contract["extraction"]["allowedDisplayDimensions"].copy(),
    }
    receipt["incidentReferences"] = []
    receipt["manifest"]["incidentReferenceCount"] = 0
    return _sign_receipt(receipt)


def _completed_unchanged_receipt(contract: dict[str, Any]) -> dict[str, Any]:
    receipt = _completed_changed_receipt(contract)
    receipt["terminalDisposition"] = "completed_unchanged"
    receipt["reasonCode"] = "SOURCE_NOT_MODIFIED"
    receipt["request"]["statusCode"] = 304
    receipt["request"]["conditionalRequestUsed"] = True
    receipt["request"]["responseBodyReceived"] = False
    receipt["response"] = {
        "contentChanged": False,
        "bytesReceived": 0,
        "contentSha256": None,
        "mimeType": None,
        "retryClassification": "none",
        "retryAfterSeconds": None,
    }
    receipt["conditionalMetadata"] = {
        "previousSnapshotId": "example-source-snapshot-r1",
        "previousSnapshotContentSha256": "3" * 64,
        "previousSnapshotVerificationReceiptSha256": "4" * 64,
        "etagRequestSha256": "2" * 64,
        "lastModifiedRequestSha256": None,
        "etagResponseSha256": None,
        "lastModifiedResponseSha256": None,
    }
    receipt["snapshot"] = {
        "snapshotId": None,
        "snapshotContentSha256": None,
        "storageReceiptSha256": None,
        "status": "not_created",
        "immutable": False,
        "readBackVerified": False,
        "committedBeforeExtraction": False,
    }
    receipt["extraction"] = {
        "disposition": "not_run",
        "sourceRecordsObserved": 0,
        "rowsParsed": 0,
        "claimCandidatesEmitted": 0,
        "claimsAdmitted": 0,
        "recordsExcluded": 0,
        "recordsRejected": 0,
        "recordsQuarantined": 0,
        "evidenceLocatorCoverageCount": 0,
        "duplicateLocatorCount": 0,
        "unexplainedRecordCount": 0,
        "schemaFingerprintSha256": None,
        "batchReceiptSha256": None,
        "dimensionsObserved": [],
    }
    return _sign_receipt(receipt)


def _runtime_blocked_receipt(
    contract: dict[str, Any],
    *,
    certification_outcome: str,
    terminal: str,
    scheduled_day: str = "2026-07-15",
) -> dict[str, Any]:
    receipt = _blocked_receipt()
    certification = contract["certification"]
    receipt["availability"] = "operational_receipt_only"
    receipt["terminalDisposition"] = terminal
    receipt["reasonCode"] = (
        "SOURCE_TERMS_REVIEW_EXPIRED"
        if terminal == "terms_quarantined"
        else "SOURCE_CERTIFICATION_EXPIRED"
    )
    receipt["identity"]["contractDigestSha256"] = contract["manifest"]["contentSha256"]
    receipt["identity"]["contractDefinitionSha256"] = contract["manifest"][
        "definitionSha256"
    ]
    receipt["identity"]["certificationDecisionId"] = certification["decisionId"]
    receipt["identity"]["certificationDecisionDigestSha256"] = certification[
        "decisionDigestSha256"
    ]
    receipt["certificationCheck"] = {
        "outcome": certification_outcome,
        "checkedDecisionId": certification["decisionId"],
        "checkedDecisionDigestSha256": certification["decisionDigestSha256"],
        "checkedSourceRevisionId": contract["logicalSource"]["sourceRevisionId"],
        "checkedContractDigestSha256": contract["manifest"]["contentSha256"],
        "checkedContractDefinitionSha256": contract["manifest"]["definitionSha256"],
        "checkedBeforeFetch": True,
        "checkedBeforeClaimWrite": True,
        "effectiveForAttempt": certification_outcome == "certified",
    }
    receipt["request"]["requestedUrl"] = contract["transport"]["approvedSourceUrls"][0]
    receipt["networkEvidence"]["connectedPeerStatus"] = "not_checked"
    receipt["identity"]["scheduledSlot"] = f"{scheduled_day}T00:00:00Z"
    receipt["execution"] = {
        "startedAt": f"{scheduled_day}T00:00:00Z",
        "finishedAt": f"{scheduled_day}T00:00:01Z",
        "durationMs": 1000,
    }
    return _sign_receipt(receipt)


def _failed_attempt_receipt(
    contract: dict[str, Any],
    *,
    stage: str,
    code: str,
) -> dict[str, Any]:
    receipt = _completed_changed_receipt(contract)
    retryable_codes = {
        "BODY_TIMEOUT",
        "BODY_TRUNCATED",
        "CONNECT_FAILED",
        "CONNECT_TIMEOUT",
        "CONNECTION_RESET",
        "DNS_RESOLUTION_FAILED",
        "HTTP_429",
        "HTTP_5XX",
        "REQUEST_TIMEOUT",
    }
    is_retryable = code in retryable_codes
    receipt["terminalDisposition"] = (
        "retryable_failed" if is_retryable else "attempted_policy_failed"
    )
    receipt["reasonCode"] = code
    requested_url = contract["transport"]["approvedSourceUrls"][0]
    final_url: str | None = None
    last_approved_url: str | None = requested_url
    status_code: int | None = None
    redirect_count = 0
    if stage == "redirect":
        status_code = 302
        redirect_count = 1
        last_approved_url = requested_url
    elif stage in {"response_headers", "response_body"}:
        final_url = contract["transport"]["approvedFinalUrls"][0]
        last_approved_url = final_url
        status_code = 429 if code == "HTTP_429" else 503 if code == "HTTP_5XX" else 200
    receipt["request"] = {
        "disposition": "attempted_failed",
        "method": "GET",
        "requestedUrl": requested_url,
        "finalUrl": final_url,
        "lastApprovedUrl": last_approved_url,
        "redirectCount": redirect_count,
        "statusCode": status_code,
        "conditionalRequestUsed": False,
        "responseBodyReceived": False,
        "failureStage": stage,
        "failureCode": code,
    }
    requested_host = urlsplit(requested_url).hostname
    assert requested_host is not None
    if stage == "dns":
        receipt["networkEvidence"] = {
            "dnsPolicyStatus": "failed",
            "connectedPeerStatus": "not_checked",
            "tlsStatus": "not_checked",
            "connectedPeerAddressClass": "not_observed",
            "finalHost": requested_host,
        }
    elif stage == "connect":
        receipt["networkEvidence"] = {
            "dnsPolicyStatus": "passed",
            "connectedPeerStatus": "not_checked",
            "tlsStatus": "not_checked",
            "connectedPeerAddressClass": "not_observed",
            "finalHost": requested_host,
        }
    elif stage == "tls_peer":
        peer_facts = {
            "TLS_FAILED": ("passed", "failed", "public"),
            "CONNECTED_PEER_UNSAFE": ("failed", "not_checked", "unsafe"),
            "CONNECTED_PEER_PROOF_MISSING": (
                "required_not_implemented",
                "not_checked",
                "not_observed",
            ),
        }
        peer_status, tls_status, address_class = peer_facts[code]
        receipt["networkEvidence"] = {
            "dnsPolicyStatus": "passed",
            "connectedPeerStatus": peer_status,
            "tlsStatus": tls_status,
            "connectedPeerAddressClass": address_class,
            "finalHost": requested_host,
        }
    else:
        last_approved_host = urlsplit(last_approved_url).hostname
        assert last_approved_host is not None
        receipt["networkEvidence"] = {
            "dnsPolicyStatus": "passed",
            "connectedPeerStatus": "passed",
            "tlsStatus": "passed",
            "connectedPeerAddressClass": "public",
            "finalHost": last_approved_host,
        }
    bytes_received = 0
    mime_type: str | None = None
    if stage == "response_body":
        bytes_received = (
            contract["transport"]["maxBytes"] + 1
            if code == "BODY_SIZE_EXCEEDED"
            else 64
        )
        mime_type = "application/json"
    elif code == "MIME_UNAPPROVED":
        mime_type = "application/x-unapproved"
    retry_classification = (
        "rate_limited"
        if code == "HTTP_429"
        else "transient"
        if is_retryable
        else "non_retryable_policy"
    )
    receipt["response"] = {
        "contentChanged": None,
        "bytesReceived": bytes_received,
        "contentSha256": None,
        "mimeType": mime_type,
        "retryClassification": retry_classification,
        "retryAfterSeconds": 60 if code == "HTTP_429" else None,
    }
    receipt["conditionalMetadata"] = {
        "previousSnapshotId": None,
        "previousSnapshotContentSha256": None,
        "previousSnapshotVerificationReceiptSha256": None,
        "etagRequestSha256": None,
        "lastModifiedRequestSha256": None,
        "etagResponseSha256": None,
        "lastModifiedResponseSha256": None,
    }
    receipt["snapshot"] = {
        "snapshotId": None,
        "snapshotContentSha256": None,
        "storageReceiptSha256": None,
        "status": "not_created",
        "immutable": False,
        "readBackVerified": False,
        "committedBeforeExtraction": False,
    }
    receipt["extraction"] = {
        "disposition": "not_run",
        "sourceRecordsObserved": 0,
        "rowsParsed": 0,
        "claimCandidatesEmitted": 0,
        "claimsAdmitted": 0,
        "recordsExcluded": 0,
        "recordsRejected": 0,
        "recordsQuarantined": 0,
        "evidenceLocatorCoverageCount": 0,
        "duplicateLocatorCount": 0,
        "unexplainedRecordCount": 0,
        "schemaFingerprintSha256": None,
        "batchReceiptSha256": None,
        "dimensionsObserved": [],
    }
    receipt["incidentReferences"] = ["incident-example-fetch-failure"]
    receipt["manifest"]["incidentReferenceCount"] = 1
    return _sign_receipt(receipt)


def _reject_contract(
    mutate: Callable[[dict[str, Any]], None],
    match: str,
    *,
    approved: bool = False,
    as_of: date | None = None,
) -> None:
    contract = _approved_contract() if approved else _draft_contract()
    mutate(contract)
    _sign_contract(contract)
    with pytest.raises(SourceContractError, match=match):
        validate_source_contract(contract, as_of=as_of)


def _reject_receipt(
    mutate: Callable[[dict[str, Any]], None],
    match: str,
    *,
    unchanged: bool = False,
) -> None:
    contract = _approved_contract()
    receipt = (
        _completed_unchanged_receipt(contract)
        if unchanged
        else _completed_changed_receipt(contract)
    )
    mutate(receipt)
    _sign_receipt(receipt)
    with pytest.raises(SourceContractError, match=match):
        validate_source_check_receipt(
            receipt,
            source_contract=contract,
            as_of=date(2026, 7, 15),
        )


def test_draft_2020_12_schemas_and_synthetic_examples_are_parseable() -> None:
    for schema_name in (
        "source-contract-v2.schema.json",
        "source-check-receipt-v1.schema.json",
    ):
        schema = json.loads((CONTRACTS / schema_name).read_text(encoding="utf-8"))
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert schema["additionalProperties"] is False
        assert schema["type"] == "object"

    contract = _draft_contract()
    receipt = _blocked_receipt()
    assert contract["lifecycleStatus"] == "draft_unapproved"
    assert contract["authority"]["captureEligible"] is False
    assert receipt["availability"] == "synthetic_evidence_only"
    assert receipt["terminalDisposition"] == "policy_blocked"
    validate_source_contract(contract)
    validate_source_check_receipt(receipt, source_contract=contract)


def test_source_check_receipt_identity_is_deterministic_per_attempt() -> None:
    receipt = _blocked_receipt()
    expected = derive_source_check_receipt_id(receipt["identity"]["attemptId"])
    assert receipt["receiptId"] == expected
    assert derive_source_check_receipt_id(receipt["identity"]["attemptId"]) == expected

    substituted = deepcopy(receipt)
    substituted["receiptId"] = "replayed-under-another-receipt-id"
    _sign_receipt(substituted)
    with pytest.raises(SourceContractError, match="receiptId"):
        validate_source_check_receipt(substituted)


def test_externally_bound_contract_and_changed_and_unchanged_receipts_validate() -> None:
    contract = _approved_contract()
    validate_source_contract(contract, as_of=date(2026, 7, 15))
    validate_source_check_receipt(
        _completed_changed_receipt(contract),
        source_contract=contract,
        as_of=date(2026, 7, 15),
    )
    validate_source_check_receipt(
        _completed_unchanged_receipt(contract),
        source_contract=contract,
        as_of=date(2026, 7, 15),
    )


@pytest.mark.parametrize(
    ("structured_format", "locator_type", "mime_type", "filename", "locator_template"),
    [
        ("json", "json_path_v1", "application/json", "results.json", "$.results[{row_index}]"),
        ("csv", "csv_cell_v1", "text/csv", "results.csv", "row:{row_index}"),
        (
            "parquet",
            "parquet_cell_v1",
            "application/vnd.apache.parquet",
            "results.parquet",
            "row-group:{row_group}:row:{row_index}",
        ),
        (
            "html",
            "json_script_path_v1",
            "text/html",
            "leaderboard.html",
            "$.leaderboard.rows[{row_index}]",
        ),
    ],
)
def test_draft_contract_families_cover_structured_source_formats_without_enabling_them(
    structured_format: str,
    locator_type: str,
    mime_type: str,
    filename: str,
    locator_template: str,
) -> None:
    contract = _draft_contract()
    url = f"https://results.example.com/releases/example-v1/{filename}"
    contract["transport"]["approvedSourceUrls"] = [url]
    contract["transport"]["approvedFinalUrls"] = [url]
    contract["transport"]["acceptedMimeTypes"] = [mime_type]
    contract["extraction"]["structuredFormat"] = structured_format
    contract["extraction"]["locatorTypes"] = [locator_type]
    contract["extraction"]["evidenceContracts"][0]["locatorType"] = locator_type
    contract["extraction"]["evidenceContracts"][0][
        "recordLocatorTemplate"
    ] = locator_template
    _sign_contract(contract)

    validate_source_contract(contract)
    assert contract["lifecycleStatus"] == "draft_unapproved"
    assert contract["schedule"]["enabled"] is False
    assert contract["implementationBinding"]["connectedPeerProof"] == "required_not_implemented"
    if structured_format == "parquet":
        assert contract["implementationBinding"]["parquetLocatorSupport"] == "contract_only"


def test_draft_contract_cannot_self_approve_or_schedule() -> None:
    _reject_contract(
        lambda value: value["authority"].update(
            {"certifiesSource": True, "captureEligible": True}
        ),
        "authority.certifiesSource",
    )
    _reject_contract(
        lambda value: value["schedule"].update({"enabled": True}),
        "draft contract",
    )


def test_exact_external_certification_revision_and_expiry_are_enforced() -> None:
    _reject_contract(
        lambda value: value["certification"].update(
            {"decidedSourceRevisionId": "different-source-revision-r1"}
        ),
        "different source revision",
        approved=True,
    )
    _reject_contract(
        lambda value: None,
        "certification is expired",
        approved=True,
        as_of=date(2027, 1, 1),
    )
    _reject_contract(
        lambda value: None,
        "terms review or reuse authority is expired",
        approved=True,
        as_of=date(2026, 11, 1),
    )


def test_terms_states_require_dated_decisions_without_implying_permission() -> None:
    blocked = _draft_contract()
    blocked["termsReuse"] = {
        "status": "blocked_permission",
        "decisionReference": "example-permission-block-r1",
        "evidenceDate": "2026-07-01",
        "effectiveOn": None,
        "reviewDueOn": "2026-08-01",
        "expiresOn": None,
        "reuseScope": None,
        "correctionRoute": "https://governance.example.com/corrections",
    }
    _sign_contract(blocked)
    validate_source_contract(blocked)

    _reject_contract(
        lambda value: value["termsReuse"].update(
            {"status": "blocked_permission", "reviewDueOn": "2026-08-01"}
        ),
        "blocked terms need a decision",
    )
    _reject_contract(
        lambda value: value["termsReuse"].update(
            {"decisionReference": "invented-permission-decision"}
        ),
        "unknown terms cannot carry",
    )


def test_approved_contract_rejects_browser_capture_and_unimplemented_parquet() -> None:
    _reject_contract(
        lambda value: value["logicalSource"].update({"methodPriority": 5}),
        "browser reconnaissance",
        approved=True,
    )

    def parquet_without_implementation(value: dict[str, Any]) -> None:
        value["extraction"]["structuredFormat"] = "parquet"
        value["extraction"]["locatorTypes"] = ["parquet_cell_v1"]
        value["extraction"]["evidenceContracts"][0]["locatorType"] = "parquet_cell_v1"
        value["extraction"]["evidenceContracts"][0][
            "recordLocatorTemplate"
        ] = "row-group:{row_group}:row:{row_index}"

    _reject_contract(
        parquet_without_implementation,
        "approved Parquet",
        approved=True,
    )


@pytest.mark.parametrize(
    ("bad_url", "match"),
    [
        ("http://results.example.com/releases/example-v1/results.json", "HTTPS"),
        ("https://results.example.com:443/releases/example-v1/results.json", "explicit URL ports"),
        ("https://user@results.example.com/releases/example-v1/results.json", "credential-free HTTPS"),
        ("https://results.example.com/releases/../private/results.json", "dot segments"),
        ("https://results.example.com/releases/%2e%2e/private/results.json", "dot segments"),
    ],
)
def test_contract_rejects_ambiguous_or_unsafe_source_urls(bad_url: str, match: str) -> None:
    def mutate(value: dict[str, Any]) -> None:
        value["transport"]["approvedSourceUrls"] = [bad_url]
        value["transport"]["approvedFinalUrls"] = [bad_url]

    _reject_contract(mutate, match)


def test_query_policy_rejects_malformed_duplicate_and_secret_parameters() -> None:
    def configure(value: dict[str, Any], url: str, names: list[str]) -> None:
        value["transport"]["queryPolicy"] = {
            "mode": "exact_allowlist",
            "allowedParameterNames": names,
        }
        value["transport"]["approvedSourceUrls"] = [url]
        value["transport"]["approvedFinalUrls"] = [url]

    _reject_contract(
        lambda value: configure(
            value,
            "https://results.example.com/releases/example-v1/results.json?view",
            ["view"],
        ),
        "malformed or ambiguous",
    )
    _reject_contract(
        lambda value: configure(
            value,
            "https://results.example.com/releases/example-v1/results.json?view=a&view=b",
            ["view"],
        ),
        "duplicate query",
    )
    _reject_contract(
        lambda value: configure(
            value,
            "https://results.example.com/releases/example-v1/results.json?token=secret",
            ["token"],
        ),
        "credential-like query",
    )


def test_exact_static_query_allowlist_can_bind_a_receipt() -> None:
    contract = _draft_contract()
    url = "https://results.example.com/releases/example-v1/results.json?view=official"
    contract["transport"]["queryPolicy"] = {
        "mode": "exact_allowlist",
        "allowedParameterNames": ["view"],
    }
    contract["transport"]["approvedSourceUrls"] = [url]
    contract["transport"]["approvedFinalUrls"] = [url]
    _sign_contract(contract)
    receipt = _blocked_receipt()
    receipt["identity"]["contractDigestSha256"] = contract["manifest"]["contentSha256"]
    receipt["identity"]["contractDefinitionSha256"] = contract["manifest"][
        "definitionSha256"
    ]
    receipt["certificationCheck"]["checkedContractDigestSha256"] = contract["manifest"]["contentSha256"]
    receipt["certificationCheck"][
        "checkedContractDefinitionSha256"
    ] = contract["manifest"]["definitionSha256"]
    receipt["request"]["requestedUrl"] = url
    _sign_receipt(receipt)
    validate_source_check_receipt(receipt, source_contract=contract)


def test_redirect_policy_and_host_manifest_are_exact() -> None:
    def differing_final(value: dict[str, Any]) -> None:
        value["transport"]["approvedFinalUrls"] = [
            "https://cdn.example.com/releases/example-v1/results.json"
        ]
        value["transport"]["allowedHosts"] = ["cdn.example.com", "results.example.com"]

    _reject_contract(differing_final, "deny mode")

    _reject_contract(
        lambda value: value["transport"].update(
            {"allowedHosts": ["mirror.example.com", "results.example.com"]}
        ),
        "exact URL hostname set",
    )


def test_secret_fields_and_ungoverned_authorization_header_are_rejected() -> None:
    contract = _draft_contract()
    contract["token"] = "do-not-store-this"  # type: ignore[typeddict-unknown-key]
    with pytest.raises(SourceContractError, match="secret/header values"):
        validate_source_contract(contract)

    _reject_contract(
        lambda value: value["transport"].update(
            {"requestHeaderNames": ["Accept", "Authorization", "User-Agent"]}
        ),
        "Authorization requires",
    )


def test_mime_size_locator_dimensions_and_evidence_are_fail_closed() -> None:
    _reject_contract(
        lambda value: value["transport"].update(
            {"acceptedMimeTypes": ["application/x-python-pickle"]}
        ),
        "unsupported",
    )
    _reject_contract(
        lambda value: value["transport"].update({"maxBytes": 67108865}),
        "range",
    )
    _reject_contract(
        lambda value: value["extraction"].update(
            {"allowedDisplayDimensions": ["benchmark_raw", "vendor_raw"]}
        ),
        "at least 5",
    )
    _reject_contract(
        lambda value: value["extraction"].update({"structuredFormat": "csv"}),
        "incompatible",
    )
    _reject_contract(
        lambda value: value["extraction"]["dimensions"]["metric_raw"].update(
            {"allowedValues": []}
        ),
        "at least 1",
    )

    def drop_model_evidence(value: dict[str, Any]) -> None:
        del value["extraction"]["evidenceContracts"][0]["fields"]["model_raw"]

    _reject_contract(drop_model_evidence, "bind model_raw/score_raw")


def test_numeric_policy_rejects_nonfinite_lexemes_and_coercion() -> None:
    _reject_contract(
        lambda value: value["extraction"]["numericPolicy"].update(
            {"maximumLexeme": "NaN"}
        ),
        "finite decimal lexeme",
    )
    _reject_contract(
        lambda value: value["extraction"]["numericPolicy"].update(
            {"coerceRawValues": True}
        ),
        "coerceRawValues",
    )


def test_mutable_observation_fields_and_nonfinite_json_are_rejected() -> None:
    contract = _draft_contract()
    contract["transport"]["lastChecked"] = "2026-07-15T00:00:00Z"
    with pytest.raises(SourceContractError, match="mutable observation"):
        validate_source_contract(contract)

    contract = _draft_contract()
    contract["schedule"]["rateLimitPerMinute"] = float("inf")
    with pytest.raises(SourceContractError, match="non-finite"):
        validate_source_contract(contract)


def test_manifest_digest_detects_mutation_and_is_mapping_order_deterministic() -> None:
    contract = _draft_contract()
    contract["logicalSource"]["ownerName"] = "Mutated after signing"
    with pytest.raises(SourceContractError, match="source-definition digest mismatch"):
        validate_source_contract(contract)

    original = _draft_contract()
    reordered = {key: original[key] for key in reversed(list(original))}
    assert canonical_json(original) == canonical_json(reordered)
    assert source_contract_digest(original) == source_contract_digest(reordered)


def test_definition_digest_breaks_the_external_certification_envelope_cycle() -> None:
    contract = _approved_contract()
    definition_digest = contract["manifest"]["definitionSha256"]
    envelope_digest = contract["manifest"]["contentSha256"]
    assert contract["certification"]["decidedContractDefinitionSha256"] == definition_digest

    changed_envelope = deepcopy(contract)
    changed_envelope["certification"]["decisionDigestSha256"] = "8" * 64
    assert source_contract_definition_digest(changed_envelope) == definition_digest
    changed_envelope["manifest"]["contentSha256"] = source_contract_digest(
        changed_envelope
    )
    assert changed_envelope["manifest"]["contentSha256"] != envelope_digest
    validate_source_contract(changed_envelope, as_of=date(2026, 7, 15))

    tampered_definition = deepcopy(contract)
    tampered_definition["transport"]["maxBytes"] += 1
    tampered_definition["manifest"][
        "definitionSha256"
    ] = source_contract_definition_digest(tampered_definition)
    tampered_definition["manifest"]["contentSha256"] = source_contract_digest(
        tampered_definition
    )
    with pytest.raises(SourceContractError, match="external decision binds a different"):
        validate_source_contract(tampered_definition, as_of=date(2026, 7, 15))


def test_receipt_binds_both_contract_definition_and_final_envelope_digests() -> None:
    contract = _approved_contract()
    receipt = _completed_changed_receipt(contract)
    receipt["identity"]["contractDefinitionSha256"] = "7" * 64
    receipt["certificationCheck"]["checkedContractDefinitionSha256"] = "7" * 64
    _sign_receipt(receipt)
    with pytest.raises(SourceContractError, match="exact source contract revision"):
        validate_source_check_receipt(receipt, source_contract=contract)

    receipt = _completed_changed_receipt(contract)
    receipt["certificationCheck"]["checkedContractDefinitionSha256"] = "7" * 64
    _sign_receipt(receipt)
    with pytest.raises(SourceContractError, match="contract definition digest"):
        validate_source_check_receipt(receipt, source_contract=contract)


def test_receipt_authority_cannot_certify_publish_or_create_claims() -> None:
    _reject_receipt(
        lambda value: value["authority"].update(
            {"certifiesSource": True, "authorizesPublication": True, "createsClaims": True}
        ),
        "authority",
    )


def test_receipt_exact_certification_contract_and_fence_bindings_are_enforced() -> None:
    _reject_receipt(
        lambda value: value["certificationCheck"].update(
            {"checkedDecisionDigestSha256": "9" * 64}
        ),
        "exact effective decision binding",
    )
    _reject_receipt(
        lambda value: value["identity"].update({"expectedFencingToken": 2}),
        "fencing token",
    )
    _reject_receipt(
        lambda value: value["identity"].update(
            {"contractRevisionId": "different-contract-revision-r1"}
        ),
        "exact source contract revision",
    )

    contract = _approved_contract()
    premature_expiry = _runtime_blocked_receipt(
        contract,
        certification_outcome="expired",
        terminal="policy_blocked",
    )
    with pytest.raises(SourceContractError, match="expired outcome is not supported"):
        validate_source_check_receipt(
            premature_expiry,
            source_contract=contract,
            as_of=date(2026, 7, 15),
        )

    mismatch = _runtime_blocked_receipt(
        contract,
        certification_outcome="expired",
        terminal="policy_blocked",
    )
    mismatch["certificationCheck"].update(
        {
            "outcome": "mismatch",
            "checkedDecisionId": "different-source-certification-r1",
            "checkedDecisionDigestSha256": "9" * 64,
        }
    )
    mismatch["reasonCode"] = "SOURCE_CERTIFICATION_BINDING_MISMATCH"
    _sign_receipt(mismatch)
    validate_source_check_receipt(
        mismatch,
        source_contract=contract,
        as_of=date(2026, 7, 15),
    )


def test_changed_200_requires_reverified_snapshot_before_extraction() -> None:
    def remove_snapshot(value: dict[str, Any]) -> None:
        value["snapshot"] = {
            "snapshotId": None,
            "snapshotContentSha256": None,
            "storageReceiptSha256": None,
            "status": "not_created",
            "immutable": False,
            "readBackVerified": False,
            "committedBeforeExtraction": False,
        }

    _reject_receipt(remove_snapshot, "changed 200")
    _reject_receipt(
        lambda value: value["snapshot"].update(
            {"snapshotContentSha256": "8" * 64}
        ),
        "differs from response bytes",
    )


@pytest.mark.parametrize(
    ("stage", "code"),
    [
        ("dns", "DNS_RESOLUTION_FAILED"),
        ("dns", "DNS_POLICY_FAILED"),
        ("connect", "CONNECT_TIMEOUT"),
        ("tls_peer", "CONNECTED_PEER_UNSAFE"),
        ("tls_peer", "TLS_FAILED"),
        ("tls_peer", "CONNECTED_PEER_PROOF_MISSING"),
        ("request", "REQUEST_TIMEOUT"),
        ("redirect", "REDIRECT_UNAPPROVED"),
        ("response_headers", "HTTP_429"),
        ("response_headers", "MIME_UNAPPROVED"),
        ("response_body", "BODY_TRUNCATED"),
        ("response_body", "BODY_SIZE_EXCEEDED"),
    ],
)
def test_failed_fetch_stages_are_truthful_terminal_attempts_without_writes(
    stage: str,
    code: str,
) -> None:
    contract = _approved_contract()
    receipt = _failed_attempt_receipt(contract, stage=stage, code=code)
    validate_source_check_receipt(receipt, source_contract=contract)
    assert receipt["request"]["disposition"] == "attempted_failed"
    assert receipt["snapshot"]["status"] == "not_created"
    assert receipt["extraction"]["disposition"] == "not_run"


def test_redirect_failure_binds_last_approved_url_and_host_across_hosts() -> None:
    contract = _approved_contract()
    contract["transport"]["approvedFinalUrls"] = [
        "https://cdn.example.com/releases/example-v1/results.json"
    ]
    contract["transport"]["allowedHosts"] = ["cdn.example.com", "results.example.com"]
    contract["transport"]["redirectPolicy"] = {
        "mode": "allow_exact_final",
        "maxRedirects": 3,
    }
    _sign_contract(contract)
    receipt = _failed_attempt_receipt(
        contract,
        stage="redirect",
        code="REDIRECT_UNAPPROVED",
    )
    receipt["request"]["lastApprovedUrl"] = contract["transport"][
        "approvedFinalUrls"
    ][0]
    receipt["request"]["redirectCount"] = 2
    receipt["networkEvidence"]["finalHost"] = "cdn.example.com"
    _sign_receipt(receipt)
    validate_source_check_receipt(receipt, source_contract=contract)

    wrong_host = deepcopy(receipt)
    wrong_host["networkEvidence"]["finalHost"] = "results.example.com"
    _sign_receipt(wrong_host)
    with pytest.raises(SourceContractError, match="last approved host"):
        validate_source_check_receipt(wrong_host, source_contract=contract)


@pytest.mark.parametrize(
    ("stage", "code"),
    [
        ("dns", "DNS_POLICY_FAILED"),
        ("connect", "CONNECT_FAILED"),
        ("tls_peer", "TLS_FAILED"),
    ],
)
def test_redirect_hop_network_failure_binds_exact_attempted_url_and_host(
    stage: str,
    code: str,
) -> None:
    contract = _approved_contract()
    redirected_url = "https://cdn.example.com/releases/example-v1/results.json"
    contract["transport"]["approvedFinalUrls"] = [redirected_url]
    contract["transport"]["allowedHosts"] = ["cdn.example.com", "results.example.com"]
    contract["transport"]["redirectPolicy"] = {
        "mode": "allow_exact_final",
        "maxRedirects": 3,
    }
    _sign_contract(contract)
    receipt = _failed_attempt_receipt(contract, stage=stage, code=code)
    receipt["request"]["lastApprovedUrl"] = redirected_url
    receipt["request"]["redirectCount"] = 1
    receipt["networkEvidence"]["finalHost"] = "cdn.example.com"
    _sign_receipt(receipt)

    validate_source_check_receipt(receipt, source_contract=contract)

    receipt["request"]["lastApprovedUrl"] = contract["transport"]["approvedSourceUrls"][0]
    _sign_receipt(receipt)
    with pytest.raises(SourceContractError, match="DNS failure|connect failure|TLS/peer failure"):
        validate_source_check_receipt(receipt, source_contract=contract)


@pytest.mark.parametrize(
    ("stage", "code"),
    [
        ("dns", "DNS_POLICY_FAILED"),
        ("tls_peer", "CONNECTED_PEER_UNSAFE"),
        ("tls_peer", "TLS_FAILED"),
        ("tls_peer", "CONNECTED_PEER_PROOF_MISSING"),
    ],
)
def test_failed_network_evidence_cannot_be_relabelled_unattempted(
    stage: str,
    code: str,
) -> None:
    contract = _approved_contract()
    receipt = _failed_attempt_receipt(contract, stage=stage, code=code)
    receipt["request"].update(
        {
            "disposition": "not_started",
            "finalUrl": None,
            "lastApprovedUrl": None,
            "redirectCount": 0,
            "statusCode": None,
            "conditionalRequestUsed": False,
            "responseBodyReceived": False,
            "failureStage": None,
            "failureCode": None,
        }
    )
    _sign_receipt(receipt)
    with pytest.raises(SourceContractError, match="unstarted request cannot claim network proof"):
        validate_source_check_receipt(receipt, source_contract=contract)


def test_retryable_terminal_requires_an_actual_failed_attempt() -> None:
    contract = _approved_contract()
    receipt = _failed_attempt_receipt(
        contract,
        stage="dns",
        code="DNS_RESOLUTION_FAILED",
    )
    receipt["request"].update(
        {
            "disposition": "not_started",
            "lastApprovedUrl": None,
            "failureStage": None,
            "failureCode": None,
        }
    )
    receipt["networkEvidence"] = {
        "dnsPolicyStatus": "not_checked",
        "connectedPeerStatus": "not_checked",
        "tlsStatus": "not_checked",
        "connectedPeerAddressClass": "not_observed",
        "finalHost": None,
    }
    _sign_receipt(receipt)
    with pytest.raises(SourceContractError, match="truthful attempt"):
        validate_source_check_receipt(receipt, source_contract=contract)


def test_304_must_be_bodyless_reuse_without_a_new_snapshot() -> None:
    _reject_receipt(
        lambda value: value["request"].update({"responseBodyReceived": True}),
        "bodyless conditional 304",
        unchanged=True,
    )
    _reject_receipt(
        lambda value: value["conditionalMetadata"].update(
            {"previousSnapshotId": None}
        ),
        "no-prior-snapshot",
        unchanged=True,
    )
    _reject_receipt(
        lambda value: value["conditionalMetadata"].update(
            {"etagRequestSha256": None, "lastModifiedRequestSha256": None}
        ),
        "bodyless conditional 304",
        unchanged=True,
    )

    def attach_new_snapshot(value: dict[str, Any]) -> None:
        value["response"].update(
            {"contentSha256": "d" * 64, "mimeType": "application/json"}
        )
        value["snapshot"] = {
            "snapshotId": "contradictory-304-snapshot",
            "snapshotContentSha256": "d" * 64,
            "storageReceiptSha256": "e" * 64,
            "status": "committed_reverified",
            "immutable": True,
            "readBackVerified": True,
            "committedBeforeExtraction": True,
        }

    _reject_receipt(attach_new_snapshot, "bodyless conditional 304", unchanged=True)


def test_304_requires_prior_content_and_verification_receipt_digests() -> None:
    _reject_receipt(
        lambda value: value["conditionalMetadata"].update(
            {"previousSnapshotContentSha256": None}
        ),
        "exact content and verification-receipt digests",
        unchanged=True,
    )
    _reject_receipt(
        lambda value: value["conditionalMetadata"].update(
            {"previousSnapshotVerificationReceiptSha256": None}
        ),
        "exact content and verification-receipt digests",
        unchanged=True,
    )


def test_governed_wide_records_allow_multiple_candidates_only_within_contract_cap() -> None:
    contract = _approved_contract()
    contract["completeness"]["maxClaimCandidatesPerRecord"] = 2
    _sign_contract(contract)
    receipt = _completed_changed_receipt(contract)
    receipt["extraction"].update(
        {
            "sourceRecordsObserved": 1,
            "rowsParsed": 1,
            "claimCandidatesEmitted": 2,
            "claimsAdmitted": 2,
            "evidenceLocatorCoverageCount": 2,
        }
    )
    _sign_receipt(receipt)
    validate_source_check_receipt(receipt, source_contract=contract)

    without_contract = deepcopy(receipt)
    with pytest.raises(SourceContractError, match="per-record claim-candidate cap"):
        validate_source_check_receipt(without_contract)

    over_cap = deepcopy(receipt)
    over_cap["extraction"].update(
        {
            "claimCandidatesEmitted": 3,
            "claimsAdmitted": 3,
            "evidenceLocatorCoverageCount": 3,
        }
    )
    _sign_receipt(over_cap)
    with pytest.raises(SourceContractError, match="per-record claim-candidate cap"):
        validate_source_check_receipt(over_cap, source_contract=contract)

    _reject_contract(
        lambda value: value["completeness"].update(
            {"maxClaimCandidatesPerRecord": 17}
        ),
        "range",
    )


@pytest.mark.parametrize(
    "terminal",
    [
        "completed_changed",
        "completed_with_review",
        "identity_review_required",
        "display_conflict",
    ],
)
def test_changed_accounted_terminals_reject_zero_candidate_collapse(terminal: str) -> None:
    contract = _approved_contract()
    receipt = _completed_changed_receipt(contract)
    receipt["terminalDisposition"] = terminal
    receipt["extraction"].update(
        {
            "claimCandidatesEmitted": 0,
            "claimsAdmitted": 0,
            "evidenceLocatorCoverageCount": 0,
        }
    )
    if terminal != "completed_changed":
        receipt["incidentReferences"] = ["incident-example-zero-candidate-collapse"]
        receipt["manifest"]["incidentReferenceCount"] = 1
    _sign_receipt(receipt)
    with pytest.raises(SourceContractError, match="needs records, claim candidates"):
        validate_source_check_receipt(receipt, source_contract=contract)


def test_receipt_exact_url_mime_size_dimension_and_peer_policy_are_enforced() -> None:
    _reject_receipt(
        lambda value: value["request"].update(
            {"requestedUrl": "https://results.example.com/releases/other/results.json"}
        ),
        "outside the exact source URL allowlist",
    )
    _reject_receipt(
        lambda value: value["response"].update({"bytesReceived": 1048577}),
        "exceeds the source contract byte limit",
    )
    _reject_receipt(
        lambda value: value["response"].update({"mimeType": "text/csv"}),
        "outside the source contract MIME allowlist",
    )
    _reject_receipt(
        lambda value: value["extraction"].update(
            {"dimensionsObserved": ["benchmark_raw", "vendor_raw"]}
        ),
        "unapproved display dimension",
    )
    _reject_receipt(
        lambda value: value["extraction"].update(
            {
                "dimensionsObserved": [
                    "benchmark_raw",
                    "evaluation_version_raw",
                    "metric_raw",
                    "setting_raw",
                ]
            }
        ),
        "all governed dimensions",
    )
    _reject_receipt(
        lambda value: value["networkEvidence"].update(
            {"connectedPeerStatus": "required_not_implemented"}
        ),
        "connected-peer",
    )


def test_receipt_extraction_accounting_incidents_and_timing_are_exact() -> None:
    _reject_receipt(
        lambda value: value["extraction"].update({"rowsParsed": 1}),
        "record accounting does not balance",
    )
    _reject_receipt(
        lambda value: value["manifest"].update({"incidentReferenceCount": 1}),
        "does not match incident references",
    )
    _reject_receipt(
        lambda value: value["execution"].update({"durationMs": 999}),
        "duration must exactly match",
    )
    _reject_receipt(
        lambda value: value["extraction"].update(
            {"schemaFingerprintSha256": "7" * 64}
        ),
        "exact approved schema",
    )


def test_expired_certification_and_terms_still_produce_bound_blocked_receipts() -> None:
    contract = _approved_contract()
    validate_source_check_receipt(
        _runtime_blocked_receipt(
            contract,
            certification_outcome="expired",
            terminal="policy_blocked",
            scheduled_day="2027-01-01",
        ),
        source_contract=contract,
    )

    wrong_terms_terminal = _runtime_blocked_receipt(
        contract,
        certification_outcome="certified",
        terminal="policy_blocked",
        scheduled_day="2026-11-01",
    )
    with pytest.raises(SourceContractError, match="require terms_quarantined"):
        validate_source_check_receipt(
            wrong_terms_terminal,
            source_contract=contract,
        )

    current_slot_receipt = _completed_changed_receipt(contract)
    with pytest.raises(SourceContractError, match="as_of must equal"):
        validate_source_check_receipt(
            current_slot_receipt,
            source_contract=contract,
            as_of=date(2026, 7, 16),
        )
    validate_source_check_receipt(
        _runtime_blocked_receipt(
            contract,
            certification_outcome="certified",
            terminal="terms_quarantined",
            scheduled_day="2026-11-01",
        ),
        source_contract=contract,
    )


@pytest.mark.parametrize("terminal", ["identity_review_required", "display_conflict"])
def test_review_terminals_preserve_accounted_snapshot_and_open_incident(terminal: str) -> None:
    contract = _approved_contract()
    receipt = _completed_changed_receipt(contract)
    receipt["terminalDisposition"] = terminal
    receipt["reasonCode"] = "SOURCE_RESULT_REQUIRES_REVIEW"
    receipt["incidentReferences"] = ["incident-example-result-review"]
    receipt["manifest"]["incidentReferenceCount"] = 1
    _sign_receipt(receipt)
    validate_source_check_receipt(
        receipt,
        source_contract=contract,
        as_of=date(2026, 7, 15),
    )


def test_blocked_and_synthetic_receipts_cannot_smuggle_a_fetch_or_success() -> None:
    contract = _draft_contract()
    receipt = _blocked_receipt()
    receipt["availability"] = "operational_receipt_only"
    receipt["request"].update(
        {
            "disposition": "completed",
                "finalUrl": receipt["request"]["requestedUrl"],
                "lastApprovedUrl": receipt["request"]["requestedUrl"],
            "statusCode": 200,
            "responseBodyReceived": True,
        }
    )
    receipt["networkEvidence"] = {
        "dnsPolicyStatus": "passed",
        "connectedPeerStatus": "passed",
        "tlsStatus": "passed",
        "connectedPeerAddressClass": "public",
        "finalHost": "results.example.com",
    }
    _sign_receipt(receipt)
    with pytest.raises(SourceContractError, match="blocked/paused receipt"):
        validate_source_check_receipt(receipt, source_contract=contract)

    receipt = _blocked_receipt()
    receipt["terminalDisposition"] = "completed_changed"
    _sign_receipt(receipt)
    with pytest.raises(SourceContractError, match="synthetic evidence"):
        validate_source_check_receipt(receipt)


def test_receipt_digest_detects_mutation_without_resigning() -> None:
    receipt = _blocked_receipt()
    receipt["reasonCode"] = "MUTATED_AFTER_SIGNING"
    with pytest.raises(SourceContractError, match="self-digest mismatch"):
        validate_source_check_receipt(receipt)
