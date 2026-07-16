"""Pure semantic validation for source-contract-v2 and source-check-receipt-v1.

The JSON Schemas describe wire shape.  These standard-library-only validators
enforce the cross-field trust boundary: a contract cannot certify itself, a
receipt cannot imply certification or publication, URL policy is exact, and a
changed response cannot reach extraction without an immutable reverified
snapshot.  This module performs no file, clock, environment, network, or
database access and never mutates its input.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import ipaddress
import json
import math
import re
from typing import Any
from urllib.parse import parse_qsl, unquote, urlsplit


class SourceContractError(ValueError):
    """Raised when a source contract or check receipt is contradictory."""


_STABLE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_REASON = re.compile(r"^[A-Z][A-Z0-9_]{2,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_HOST = re.compile(
    r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?$"
)
_DURATION = re.compile(
    r"^P(?!$)(?:[0-9]+D)?(?:T(?=[0-9])(?:[0-9]+H)?(?:[0-9]+M)?(?:[0-9]+S)?)?$"
)
_MIME = re.compile(r"^[a-z0-9!#$&^_.+-]+/[a-z0-9!#$&^_.+*-]+$")
_HEADER = re.compile(r"^[A-Za-z0-9!#$%&'*+.^_`|~-]+$")
_DECIMAL = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?\Z")
_ALGORITHM = "sha256-canonical-json-v1"
_SENSITIVE_QUERY_NAMES = {
    "access_token",
    "api_key",
    "apikey",
    "authorization",
    "key",
    "password",
    "secret",
    "signature",
    "token",
}
_FORBIDDEN_SECRET_KEYS = {
    "authorization",
    "credentialvalue",
    "headerValues",
    "password",
    "secret",
    "secretvalue",
    "token",
}
_MUTABLE_CONTRACT_KEYS = {
    "checkedat",
    "createdat",
    "fetchedat",
    "generatedat",
    "lastchecked",
    "lastmodified",
    "observedat",
    "retrievedat",
    "timestamp",
    "updatedat",
}

_CONTRACT_KEYS = {
    "schemaVersion",
    "policyVersion",
    "availability",
    "contractId",
    "contractRevisionId",
    "supersedesContractRevisionId",
    "lifecycleStatus",
    "reasonCode",
    "logicalSource",
    "authority",
    "certification",
    "manifest",
    "termsReuse",
    "transport",
    "implementationBinding",
    "extraction",
    "completeness",
    "drift",
    "schedule",
    "storage",
}
_RECEIPT_KEYS = {
    "schemaVersion",
    "policyVersion",
    "availability",
    "receiptId",
    "identity",
    "manifest",
    "authority",
    "terminalDisposition",
    "reasonCode",
    "certificationCheck",
    "request",
    "networkEvidence",
    "response",
    "conditionalMetadata",
    "snapshot",
    "extraction",
    "incidentReferences",
    "execution",
}
_DIMENSIONS = (
    "benchmark_raw",
    "evaluation_version_raw",
    "metric_raw",
    "setting_raw",
    "split_raw",
)
_LOCATOR_TYPES = {
    "csv_cell_v1",
    "json_path_v1",
    "json_script_path_v1",
    "parquet_cell_v1",
}
_MIME_TYPES = {
    "application/json",
    "application/ld+json",
    "application/octet-stream",
    "application/parquet",
    "application/vnd.apache.parquet",
    "application/*+json",
    "text/csv",
    "text/html",
    "text/tab-separated-values",
}
_RETRYABLE_CLASSES = {
    "connection_reset",
    "database_serialization",
    "http_429",
    "http_5xx",
    "object_store_unavailable",
    "timeout",
}
_FETCH_FAILURE_CODES: dict[str, set[str]] = {
    "dns": {"DNS_POLICY_FAILED", "DNS_REBIND_DETECTED", "DNS_RESOLUTION_FAILED"},
    "connect": {"CONNECT_FAILED", "CONNECT_TIMEOUT"},
    "tls_peer": {
        "CONNECTED_PEER_PROOF_MISSING",
        "CONNECTED_PEER_UNSAFE",
        "TLS_FAILED",
    },
    "request": {"CONNECTION_RESET", "REQUEST_TIMEOUT"},
    "redirect": {"REDIRECT_LIMIT_EXCEEDED", "REDIRECT_UNAPPROVED"},
    "response_headers": {
        "CONTENT_LENGTH_EXCEEDED",
        "HTTP_429",
        "HTTP_5XX",
        "MIME_UNAPPROVED",
    },
    "response_body": {"BODY_SIZE_EXCEEDED", "BODY_TIMEOUT", "BODY_TRUNCATED"},
}


def _fail(path: str, message: str) -> None:
    raise SourceContractError(f"{path}: {message}")


def _walk_json(value: Any, path: str = "$", *, contract: bool = False) -> None:
    if value is None or type(value) in (str, bool, int):
        return
    if type(value) is float:
        if not math.isfinite(value):
            _fail(path, "non-finite numbers are forbidden")
        return
    if type(value) is list:
        for index, item in enumerate(value):
            _walk_json(item, f"{path}[{index}]", contract=contract)
        return
    if type(value) is dict:
        for key, item in value.items():
            if type(key) is not str:
                _fail(path, "object keys must be strings")
            normalized = re.sub(r"[^a-z0-9]", "", key.lower())
            if normalized in {re.sub(r"[^a-z0-9]", "", item.lower()) for item in _FORBIDDEN_SECRET_KEYS}:
                _fail(f"{path}.{key}", "secret/header values are forbidden from contracts and receipts")
            if contract and (
                normalized in _MUTABLE_CONTRACT_KEYS
                or "mtime" in normalized
                or normalized.endswith("timestamp")
            ):
                _fail(f"{path}.{key}", "mutable observation timestamps/mtimes are forbidden")
            _walk_json(item, f"{path}.{key}", contract=contract)
        return
    _fail(path, f"unsupported canonical JSON type {type(value).__name__}")


def canonical_json(value: Any) -> str:
    """Compact ASCII canonical JSON with recursively sorted object keys."""

    _walk_json(value)
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def _self_digest(payload: dict[str, Any]) -> str:
    if type(payload) is not dict:
        _fail("$", "payload must be an object")
    material = deepcopy(payload)
    manifest = material.get("manifest")
    if type(manifest) is not dict or "contentSha256" not in manifest:
        _fail("$.manifest.contentSha256", "is required")
    manifest["contentSha256"] = None
    return hashlib.sha256(canonical_json(material).encode("utf-8")).hexdigest()


def _source_definition_material(payload: dict[str, Any]) -> dict[str, Any]:
    """Return the certification-neutral governed source definition.

    The external decision binds this material. Activation/certification fields
    are neutralized so the later decision ID/digest can be added to the final
    immutable envelope without introducing a hash cycle.
    """

    if type(payload) is not dict:
        _fail("$", "payload must be an object")
    material = deepcopy(payload)
    manifest = material.get("manifest")
    if type(manifest) is not dict or not {
        "contentSha256",
        "definitionSha256",
    } <= set(manifest):
        _fail("$.manifest", "content and definition digest fields are required")
    manifest["contentSha256"] = None
    manifest["definitionSha256"] = None

    certification = material.get("certification")
    if type(certification) is not dict:
        _fail("$.certification", "is required for definition canonicalization")
    certification.update(
        {
            "decisionId": None,
            "decisionDigestSha256": None,
            "decisionOutcome": "not_assessed",
            "decidedSourceRevisionId": None,
            "decidedContractDefinitionSha256": None,
            "effectiveOn": None,
            "expiresOn": None,
        }
    )

    # These are the activation envelope driven by an external decision, not
    # source-fetch/extraction semantics reviewed by that decision.
    material["lifecycleStatus"] = "draft_unapproved"
    material["reasonCode"] = "DEFINITION_DIGEST_NEUTRAL"
    authority = material.get("authority")
    if type(authority) is not dict:
        _fail("$.authority", "is required for definition canonicalization")
    authority["approvalStatus"] = "draft_unapproved"
    authority["captureEligible"] = False
    schedule = material.get("schedule")
    if type(schedule) is not dict:
        _fail("$.schedule", "is required for definition canonicalization")
    schedule["enabled"] = False
    return material


def source_contract_definition_digest(payload: dict[str, Any]) -> str:
    """Digest the governed definition an external certification must bind."""

    material = _source_definition_material(payload)
    return hashlib.sha256(canonical_json(material).encode("utf-8")).hexdigest()


def source_contract_digest(payload: dict[str, Any]) -> str:
    """Digest the final envelope, including definition and decision bindings."""

    return _self_digest(payload)


def source_check_receipt_digest(payload: dict[str, Any]) -> str:
    """Return the canonical self-digest for a source-check-receipt-v1 payload."""

    return _self_digest(payload)


def derive_source_check_receipt_id(attempt_id: str) -> str:
    """Derive the single logical check-receipt ID for a scheduled attempt."""

    if type(attempt_id) is not str or _STABLE_ID.fullmatch(attempt_id) is None:
        _fail("attemptId", "must be a stable lowercase identifier")
    digest = hashlib.sha256(
        canonical_json(
            {
                "identityKind": "source-check-receipt-id-v1",
                "attemptId": attempt_id,
            }
        ).encode("utf-8")
    ).hexdigest()
    return "source-check-receipt-" + digest


def _object(value: Any, path: str, keys: set[str] | None = None) -> dict[str, Any]:
    if type(value) is not dict:
        _fail(path, "must be an object")
    if keys is not None and set(value) != keys:
        missing = sorted(keys - set(value))
        extra = sorted(set(value) - keys)
        _fail(path, f"missing keys {missing}; unexpected keys {extra}")
    return value


def _array(value: Any, path: str, *, minimum: int = 0) -> list[Any]:
    if type(value) is not list or len(value) < minimum:
        _fail(path, f"must be an array with at least {minimum} item(s)")
    return value


def _enum(value: Any, allowed: set[str], path: str) -> str:
    if type(value) is not str or value not in allowed:
        _fail(path, f"must be one of {sorted(allowed)}")
    return value


def _constant(value: Any, expected: Any, path: str) -> None:
    if type(value) is not type(expected) or value != expected:
        _fail(path, f"must equal {expected!r}")


def _boolean(value: Any, path: str) -> bool:
    if type(value) is not bool:
        _fail(path, "must be a boolean")
    return value


def _integer(value: Any, path: str, *, minimum: int = 0, maximum: int | None = None) -> int:
    if type(value) is not int or value < minimum or (maximum is not None and value > maximum):
        _fail(path, f"must be an integer in range {minimum}..{maximum or 'unbounded'}")
    return value


def _text(value: Any, path: str, *, nullable: bool = False) -> str | None:
    if nullable and value is None:
        return None
    if type(value) is not str or not value or value != value.strip():
        _fail(path, "must be a nonempty exact string")
    return value


def _stable_id(value: Any, path: str, *, nullable: bool = False) -> str | None:
    if nullable and value is None:
        return None
    if type(value) is not str or _STABLE_ID.fullmatch(value) is None:
        _fail(path, "must be a stable lowercase identifier")
    return value


def _reason(value: Any, path: str) -> str:
    if type(value) is not str or _REASON.fullmatch(value) is None:
        _fail(path, "must be an uppercase reason code")
    return value


def _sha256(value: Any, path: str, *, nullable: bool = False) -> str | None:
    if nullable and value is None:
        return None
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        _fail(path, "must be a lowercase SHA-256 digest")
    return value


def _date(value: Any, path: str, *, nullable: bool = False) -> date | None:
    if nullable and value is None:
        return None
    if type(value) is not str:
        _fail(path, "must be a canonical ISO date")
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        _fail(path, "must be a canonical ISO date")
    if parsed.isoformat() != value:
        _fail(path, "must be a canonical ISO date")
    return parsed


def _instant(value: Any, path: str) -> datetime:
    if type(value) is not str or not value.endswith("Z"):
        _fail(path, "must be a canonical UTC instant ending in Z")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        _fail(path, "must be a canonical UTC instant")
    if parsed.tzinfo != timezone.utc or parsed.isoformat(timespec="seconds").replace("+00:00", "Z") != value:
        _fail(path, "must use second-precision canonical UTC form")
    return parsed


def _duration(value: Any, path: str) -> str:
    if type(value) is not str or _DURATION.fullmatch(value) is None:
        _fail(path, "must be a supported ISO duration")
    if not any(int(number) for number in re.findall(r"\d+", value)):
        _fail(path, "duration must be positive")
    return value


def _decimal_lexeme(value: Any, path: str, *, minimum: Decimal | None = None) -> Decimal:
    if type(value) is not str or _DECIMAL.fullmatch(value) is None:
        _fail(path, "must be an exact finite decimal lexeme")
    try:
        parsed = Decimal(value)
    except InvalidOperation:
        _fail(path, "must be an exact finite decimal lexeme")
    if not parsed.is_finite() or (minimum is not None and parsed < minimum):
        _fail(path, "decimal lexeme is outside the allowed range")
    return parsed


def _sorted_unique_strings(
    value: Any,
    path: str,
    *,
    minimum: int = 0,
    validator: Any = _text,
) -> list[str]:
    rows = _array(value, path, minimum=minimum)
    parsed = [validator(item, f"{path}[{index}]") for index, item in enumerate(rows)]
    if rows != sorted(rows) or len(set(rows)) != len(rows):
        _fail(path, "must be sorted and unique")
    return parsed


def _host(value: Any, path: str) -> str:
    host = _text(value, path)
    assert host is not None
    if host != host.lower() or _HOST.fullmatch(host) is None or host.endswith("."):
        _fail(path, "must be an unambiguous lowercase dotted public-style hostname")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        _fail(path, "IP-literal hosts are forbidden")
    if host.endswith((".local", ".internal", ".localhost")):
        _fail(path, "local/private host suffixes are forbidden")
    return host


def _canonical_https_url(value: Any, path: str, *, query_policy: dict[str, Any]) -> str:
    url = _text(value, path)
    assert url is not None
    if any(char in url for char in ("\r", "\n", "\t", " ")):
        _fail(path, "URL whitespace/control characters are forbidden")
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        _fail(path, "must be an absolute credential-free HTTPS URL")
    if parsed.fragment:
        _fail(path, "URL fragments are forbidden")
    try:
        port = parsed.port
    except ValueError:
        _fail(path, "URL port is invalid")
    if port is not None:
        _fail(path, "explicit URL ports are forbidden; policy separately fixes port 443")
    hostname = parsed.hostname
    if hostname is None or parsed.netloc != hostname:
        _fail(path, "URL host spelling must be canonical lowercase without aliases")
    _host(hostname, f"{path}.host")
    if not parsed.path or not parsed.path.startswith("/") or "//" in parsed.path:
        _fail(path, "URL must have one canonical absolute path")
    decoded_path = unquote(parsed.path)
    if any(segment in {".", ".."} for segment in decoded_path.split("/")):
        _fail(path, "URL dot segments, including percent-encoded forms, are forbidden")
    if unquote(url) != url:
        _fail(path, "percent-encoded URL aliases are forbidden in exact allowlists")
    mode = query_policy["mode"]
    try:
        pairs = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True)
    except ValueError:
        _fail(path, "query string is malformed or ambiguous")
    if mode == "none" and pairs:
        _fail(path, "query parameters are forbidden")
    names = [name for name, _value in pairs]
    if len(names) != len(set(names)):
        _fail(path, "duplicate query parameter names are forbidden")
    for name in names:
        lowered = name.lower()
        if lowered in _SENSITIVE_QUERY_NAMES or lowered.startswith("x-amz-"):
            _fail(path, "credential-like query parameters are forbidden")
        if name not in query_policy["allowedParameterNames"]:
            _fail(path, "query parameter is not explicitly approved")
    return url


def _verify_manifest(payload: dict[str, Any], path: str = "$.manifest") -> dict[str, Any]:
    manifest = _object(payload.get("manifest"), path, None)
    _constant(manifest.get("algorithm"), _ALGORITHM, f"{path}.algorithm")
    declared = _sha256(manifest.get("contentSha256"), f"{path}.contentSha256")
    actual = _self_digest(payload)
    if declared != actual:
        _fail(f"{path}.contentSha256", "self-digest mismatch")
    return manifest


def validate_source_contract(
    payload: dict[str, Any],
    *,
    as_of: date | None = None,
) -> None:
    """Validate one immutable source-contract-v2 definition.

    ``as_of`` is explicit so expiry checks remain deterministic and never read
    the process clock.  Omitting it validates immutable chronology only.
    """

    _walk_json(payload, contract=True)
    contract = _object(payload, "$", _CONTRACT_KEYS)
    _constant(contract["schemaVersion"], "2.0.0", "$.schemaVersion")
    _constant(contract["policyVersion"], "source-contract-v2", "$.policyVersion")
    _constant(contract["availability"], "contract_only", "$.availability")
    contract_id = _stable_id(contract["contractId"], "$.contractId")
    contract_revision_id = _stable_id(contract["contractRevisionId"], "$.contractRevisionId")
    supersedes_contract = _stable_id(
        contract["supersedesContractRevisionId"],
        "$.supersedesContractRevisionId",
        nullable=True,
    )
    if supersedes_contract == contract_revision_id:
        _fail("$.supersedesContractRevisionId", "a contract revision cannot supersede itself")
    lifecycle = _enum(
        contract["lifecycleStatus"],
        {"draft_unapproved", "certification_pending", "approved", "paused", "revoked", "retired"},
        "$.lifecycleStatus",
    )
    _reason(contract["reasonCode"], "$.reasonCode")

    logical = _object(
        contract["logicalSource"],
        "$.logicalSource",
        {
            "sourceId",
            "sourceRevisionId",
            "proposalId",
            "benchmarkRevisionId",
            "ownerName",
            "officialnessLevel",
            "methodPriority",
            "artifactMode",
        },
    )
    source_id = _stable_id(logical["sourceId"], "$.logicalSource.sourceId")
    source_revision_id = _stable_id(
        logical["sourceRevisionId"], "$.logicalSource.sourceRevisionId"
    )
    proposal_id = _stable_id(logical["proposalId"], "$.logicalSource.proposalId")
    _stable_id(logical["benchmarkRevisionId"], "$.logicalSource.benchmarkRevisionId")
    _text(logical["ownerName"], "$.logicalSource.ownerName")
    _enum(logical["officialnessLevel"], {f"O{index}" for index in range(6)}, "$.logicalSource.officialnessLevel")
    method_priority = _integer(logical["methodPriority"], "$.logicalSource.methodPriority", minimum=1, maximum=5)
    artifact_mode = _enum(
        logical["artifactMode"],
        {"immutable_revision", "approved_mutable_endpoint"},
        "$.logicalSource.artifactMode",
    )
    if len({contract_id, contract_revision_id, source_id, source_revision_id, proposal_id}) != 5:
        _fail("$.logicalSource", "contract/source/proposal identities must be distinct")

    authority = _object(
        contract["authority"],
        "$.authority",
        {
            "classification",
            "approvalStatus",
            "selfApprovalAllowed",
            "certifiesSource",
            "authorizesCapture",
            "captureEligible",
            "authorizesPublication",
            "frontendLoadable",
        },
    )
    _constant(authority["classification"], "source_contract_definition_only", "$.authority.classification")
    approval_status = _enum(
        authority["approvalStatus"],
        {"draft_unapproved", "external_review_pending", "external_certification_bound"},
        "$.authority.approvalStatus",
    )
    for field in (
        "selfApprovalAllowed",
        "certifiesSource",
        "authorizesCapture",
        "authorizesPublication",
        "frontendLoadable",
    ):
        _constant(authority[field], False, f"$.authority.{field}")
    capture_eligible = _boolean(authority["captureEligible"], "$.authority.captureEligible")

    certification = _object(
        contract["certification"],
        "$.certification",
        {
            "decisionId",
            "decisionDigestSha256",
            "decisionOutcome",
            "decidedSourceRevisionId",
            "decidedContractDefinitionSha256",
            "effectiveOn",
            "expiresOn",
        },
    )
    decision_id = _stable_id(certification["decisionId"], "$.certification.decisionId", nullable=True)
    decision_digest = _sha256(
        certification["decisionDigestSha256"],
        "$.certification.decisionDigestSha256",
        nullable=True,
    )
    decision_outcome = _enum(
        certification["decisionOutcome"],
        {"not_assessed", "certified", "quarantined", "revoked"},
        "$.certification.decisionOutcome",
    )
    decided_revision = _stable_id(
        certification["decidedSourceRevisionId"],
        "$.certification.decidedSourceRevisionId",
        nullable=True,
    )
    decided_definition_digest = _sha256(
        certification["decidedContractDefinitionSha256"],
        "$.certification.decidedContractDefinitionSha256",
        nullable=True,
    )
    certification_effective = _date(
        certification["effectiveOn"], "$.certification.effectiveOn", nullable=True
    )
    certification_expires = _date(
        certification["expiresOn"], "$.certification.expiresOn", nullable=True
    )
    certification_values = (
        decision_id,
        decision_digest,
        decided_revision,
        decided_definition_digest,
        certification_effective,
        certification_expires,
    )
    if decision_outcome == "not_assessed":
        if any(value is not None for value in certification_values):
            _fail("$.certification", "not_assessed certification must not invent decision bindings")
    else:
        if any(value is None for value in certification_values):
            _fail("$.certification", "assessed certification needs every immutable decision binding")
        if decided_revision != source_revision_id:
            _fail("$.certification.decidedSourceRevisionId", "decision binds a different source revision")
        assert certification_effective is not None and certification_expires is not None
        if certification_effective > certification_expires:
            _fail("$.certification", "certification expires before it becomes effective")

    manifest = _object(
        contract["manifest"],
        "$.manifest",
        {
            "algorithm",
            "contentSha256",
            "definitionSha256",
            "approvedSourceUrlCount",
            "approvedFinalUrlCount",
            "acceptedMimeTypeCount",
            "locatorTypeCount",
            "displayDimensionCount",
            "recordExclusionCount",
            "parserFixtureCount",
        },
    )
    _constant(manifest["algorithm"], _ALGORITHM, "$.manifest.algorithm")
    definition_digest = _sha256(
        manifest["definitionSha256"], "$.manifest.definitionSha256"
    )
    for field in set(manifest) - {"algorithm", "contentSha256", "definitionSha256"}:
        _integer(manifest[field], f"$.manifest.{field}")

    terms = _object(
        contract["termsReuse"],
        "$.termsReuse",
        {
            "status",
            "decisionReference",
            "evidenceDate",
            "effectiveOn",
            "reviewDueOn",
            "expiresOn",
            "reuseScope",
            "correctionRoute",
        },
    )
    terms_status = _enum(
        terms["status"],
        {"unknown", "blocked_terms", "blocked_permission", "reviewed_permitted"},
        "$.termsReuse.status",
    )
    terms_decision = _stable_id(
        terms["decisionReference"], "$.termsReuse.decisionReference", nullable=True
    )
    evidence_date = _date(terms["evidenceDate"], "$.termsReuse.evidenceDate", nullable=True)
    terms_effective = _date(terms["effectiveOn"], "$.termsReuse.effectiveOn", nullable=True)
    review_due = _date(terms["reviewDueOn"], "$.termsReuse.reviewDueOn", nullable=True)
    terms_expires = _date(terms["expiresOn"], "$.termsReuse.expiresOn", nullable=True)
    reuse_scope = _text(terms["reuseScope"], "$.termsReuse.reuseScope", nullable=True)
    correction_policy = {"mode": "none", "allowedParameterNames": []}
    _canonical_https_url(
        terms["correctionRoute"], "$.termsReuse.correctionRoute", query_policy=correction_policy
    )
    terms_bindings = (
        terms_decision,
        evidence_date,
        terms_effective,
        review_due,
        terms_expires,
        reuse_scope,
    )
    if terms_status == "reviewed_permitted":
        if any(value is None for value in terms_bindings):
            _fail("$.termsReuse", "permitted reuse requires decision, dates, scope, and expiry")
        assert evidence_date and terms_effective and review_due and terms_expires
        if not evidence_date <= terms_effective <= review_due <= terms_expires:
            _fail("$.termsReuse", "terms dates must be evidence <= effective <= review <= expiry")
    elif terms_status in {"blocked_terms", "blocked_permission"}:
        if any(value is None for value in (terms_decision, evidence_date, review_due)):
            _fail("$.termsReuse", "blocked terms need a decision, evidence date, and review date")
        if any(value is not None for value in (terms_effective, terms_expires, reuse_scope)):
            _fail("$.termsReuse", "blocked terms cannot carry a permitted reuse binding")
        assert evidence_date and review_due
        if evidence_date > review_due:
            _fail("$.termsReuse", "blocked terms review cannot predate its evidence")
    elif any(value is not None for value in terms_bindings):
        _fail("$.termsReuse", "unknown terms cannot carry decision or reuse bindings")

    transport = _object(
        contract["transport"],
        "$.transport",
        {
            "requestMethod",
            "approvedSourceUrls",
            "approvedFinalUrls",
            "allowedHosts",
            "allowedPorts",
            "queryPolicy",
            "requestHeaderNames",
            "credential",
            "redirectPolicy",
            "peerPolicy",
            "conditionalRequests",
            "revisionDiscovery",
            "acceptedMimeTypes",
            "maxBytes",
            "timeoutSeconds",
        },
    )
    _constant(transport["requestMethod"], "GET", "$.transport.requestMethod")
    query_policy = _object(
        transport["queryPolicy"],
        "$.transport.queryPolicy",
        {"mode", "allowedParameterNames"},
    )
    query_mode = _enum(query_policy["mode"], {"none", "exact_allowlist"}, "$.transport.queryPolicy.mode")
    allowed_query_names = _sorted_unique_strings(
        query_policy["allowedParameterNames"], "$.transport.queryPolicy.allowedParameterNames"
    )
    if query_mode == "none" and allowed_query_names:
        _fail("$.transport.queryPolicy", "none mode cannot retain allowed parameter names")
    source_urls = _sorted_unique_strings(
        transport["approvedSourceUrls"], "$.transport.approvedSourceUrls", minimum=1
    )
    final_urls = _sorted_unique_strings(
        transport["approvedFinalUrls"], "$.transport.approvedFinalUrls", minimum=1
    )
    source_urls = [
        _canonical_https_url(url, f"$.transport.approvedSourceUrls[{index}]", query_policy=query_policy)
        for index, url in enumerate(source_urls)
    ]
    final_urls = [
        _canonical_https_url(url, f"$.transport.approvedFinalUrls[{index}]", query_policy=query_policy)
        for index, url in enumerate(final_urls)
    ]
    hosts = _sorted_unique_strings(
        transport["allowedHosts"], "$.transport.allowedHosts", minimum=1, validator=_host
    )
    exact_hosts = sorted({urlsplit(url).hostname for url in [*source_urls, *final_urls]})
    if hosts != exact_hosts:
        _fail("$.transport.allowedHosts", "must equal the exact URL hostname set")
    ports = _array(transport["allowedPorts"], "$.transport.allowedPorts", minimum=1)
    if ports != [443]:
        _fail("$.transport.allowedPorts", "must be exactly [443]")
    header_names = _sorted_unique_strings(
        transport["requestHeaderNames"], "$.transport.requestHeaderNames", minimum=1
    )
    if any(_HEADER.fullmatch(name) is None for name in header_names):
        _fail("$.transport.requestHeaderNames", "contains an invalid HTTP header name")
    credential = _object(
        transport["credential"],
        "$.transport.credential",
        {"credentialClass", "credentialReference"},
    )
    credential_class = _enum(
        credential["credentialClass"],
        {"none", "bearer_token_env", "api_key_env", "oauth_client_env"},
        "$.transport.credential.credentialClass",
    )
    credential_reference = _stable_id(
        credential["credentialReference"],
        "$.transport.credential.credentialReference",
        nullable=True,
    )
    if (credential_class == "none") != (credential_reference is None):
        _fail("$.transport.credential", "credential reference must exist only for a named credential class")
    if credential_class == "none" and "Authorization" in header_names:
        _fail("$.transport.requestHeaderNames", "Authorization requires a governed credential class")
    redirect = _object(
        transport["redirectPolicy"],
        "$.transport.redirectPolicy",
        {"mode", "maxRedirects"},
    )
    redirect_mode = _enum(
        redirect["mode"], {"deny", "allow_exact_final"}, "$.transport.redirectPolicy.mode"
    )
    max_redirects = _integer(
        redirect["maxRedirects"], "$.transport.redirectPolicy.maxRedirects", maximum=5
    )
    if redirect_mode == "deny":
        if max_redirects != 0 or source_urls != final_urls:
            _fail("$.transport.redirectPolicy", "deny mode needs zero redirects and identical URL sets")
    elif max_redirects < 1:
        _fail("$.transport.redirectPolicy.maxRedirects", "redirect-enabled mode needs a positive limit")
    peer = _object(
        transport["peerPolicy"],
        "$.transport.peerPolicy",
        {
            "requireTls",
            "minimumTlsVersion",
            "verifyConnectedPeer",
            "rejectPrivateAddresses",
            "verifyDnsEveryHop",
        },
    )
    for field in ("requireTls", "verifyConnectedPeer", "rejectPrivateAddresses", "verifyDnsEveryHop"):
        _constant(peer[field], True, f"$.transport.peerPolicy.{field}")
    _enum(peer["minimumTlsVersion"], {"TLS1.2", "TLS1.3"}, "$.transport.peerPolicy.minimumTlsVersion")
    conditional = _object(
        transport["conditionalRequests"],
        "$.transport.conditionalRequests",
        {"mode", "requirePreviousSnapshotFor304"},
    )
    _enum(
        conditional["mode"],
        {"none", "etag", "last_modified", "etag_or_last_modified"},
        "$.transport.conditionalRequests.mode",
    )
    _constant(
        conditional["requirePreviousSnapshotFor304"],
        True,
        "$.transport.conditionalRequests.requirePreviousSnapshotFor304",
    )
    revision_discovery = _object(
        transport["revisionDiscovery"],
        "$.transport.revisionDiscovery",
        {"mode", "revisionField", "requireStableRevision"},
    )
    revision_mode = _enum(
        revision_discovery["mode"],
        {"immutable_url", "etag_and_content_hash", "manifest_revision"},
        "$.transport.revisionDiscovery.mode",
    )
    _text(revision_discovery["revisionField"], "$.transport.revisionDiscovery.revisionField")
    _constant(
        revision_discovery["requireStableRevision"],
        True,
        "$.transport.revisionDiscovery.requireStableRevision",
    )
    if artifact_mode == "immutable_revision" and revision_mode != "immutable_url":
        _fail("$.transport.revisionDiscovery.mode", "immutable artifacts require immutable_url mode")
    if artifact_mode == "approved_mutable_endpoint" and revision_mode == "immutable_url":
        _fail("$.transport.revisionDiscovery.mode", "mutable endpoints require revision discovery")
    mime_types = _sorted_unique_strings(
        transport["acceptedMimeTypes"], "$.transport.acceptedMimeTypes", minimum=1
    )
    if any(_MIME.fullmatch(mime) is None or mime not in _MIME_TYPES for mime in mime_types):
        _fail("$.transport.acceptedMimeTypes", "contains an unsupported or malformed MIME type")
    _integer(transport["maxBytes"], "$.transport.maxBytes", minimum=1, maximum=64 * 1024 * 1024)
    _integer(transport["timeoutSeconds"], "$.transport.timeoutSeconds", minimum=1, maximum=60)

    implementation = _object(
        contract["implementationBinding"],
        "$.implementationBinding",
        {
            "status",
            "currentAdmissionPolicy",
            "currentSafeFetchPolicy",
            "connectedPeerProof",
            "parquetLocatorSupport",
        },
    )
    implementation_status = _enum(
        implementation["status"],
        {"contract_only_not_wired", "fixture_verified_not_live", "wired_peer_verified"},
        "$.implementationBinding.status",
    )
    _constant(
        implementation["currentAdmissionPolicy"],
        "source-admission-v2",
        "$.implementationBinding.currentAdmissionPolicy",
    )
    _constant(
        implementation["currentSafeFetchPolicy"],
        "safe-fetch-v1",
        "$.implementationBinding.currentSafeFetchPolicy",
    )
    peer_proof_status = _enum(
        implementation["connectedPeerProof"],
        {"required_not_implemented", "implemented_verified"},
        "$.implementationBinding.connectedPeerProof",
    )
    parquet_status = _enum(
        implementation["parquetLocatorSupport"],
        {"contract_only", "implemented_verified"},
        "$.implementationBinding.parquetLocatorSupport",
    )

    extraction = _object(
        contract["extraction"],
        "$.extraction",
        {
            "parser",
            "structuredFormat",
            "locatorTypes",
            "evidenceContracts",
            "allowedDisplayDimensions",
            "dimensions",
            "numericPolicy",
            "recordExclusions",
        },
    )
    parser = _object(
        extraction["parser"],
        "$.extraction.parser",
        {"name", "version", "fixtureDigests"},
    )
    _stable_id(parser["name"], "$.extraction.parser.name")
    _text(parser["version"], "$.extraction.parser.version")
    fixture_digests = _sorted_unique_strings(
        parser["fixtureDigests"], "$.extraction.parser.fixtureDigests", minimum=1, validator=_sha256
    )
    structured_format = _enum(
        extraction["structuredFormat"], {"api", "csv", "html", "json", "parquet"}, "$.extraction.structuredFormat"
    )
    locator_types = _sorted_unique_strings(
        extraction["locatorTypes"], "$.extraction.locatorTypes", minimum=1
    )
    if not set(locator_types) <= _LOCATOR_TYPES:
        _fail("$.extraction.locatorTypes", "contains an unsupported locator family")
    format_locators = {
        "api": {"json_path_v1"},
        "csv": {"csv_cell_v1"},
        "html": {"json_script_path_v1"},
        "json": {"json_path_v1", "json_script_path_v1"},
        "parquet": {"parquet_cell_v1"},
    }
    if not set(locator_types) <= format_locators[structured_format]:
        _fail("$.extraction.locatorTypes", "locator family is incompatible with structured format")
    evidence_contracts = _array(
        extraction["evidenceContracts"], "$.extraction.evidenceContracts", minimum=1
    )
    evidence_locator_types: list[str] = []
    allowed_evidence_fields = {"model_raw", "score_raw", "rank_raw", *_DIMENSIONS}
    evidence_fields_by_locator: dict[str, set[str]] = {}
    for index, raw_evidence in enumerate(evidence_contracts):
        path = f"$.extraction.evidenceContracts[{index}]"
        evidence = _object(
            raw_evidence,
            path,
            {"locatorType", "recordLocatorTemplate", "fields"},
        )
        locator_type = _enum(evidence["locatorType"], _LOCATOR_TYPES, f"{path}.locatorType")
        locator_template = _text(evidence["recordLocatorTemplate"], f"{path}.recordLocatorTemplate")
        assert locator_template is not None
        if locator_type in {"json_path_v1", "json_script_path_v1"}:
            if locator_template.count("{row_index}") != 1 or not locator_template.startswith("$"):
                _fail(f"{path}.recordLocatorTemplate", "JSON locators need one indexed JSON path")
        elif locator_type == "csv_cell_v1":
            if locator_template != "row:{row_index}":
                _fail(
                    f"{path}.recordLocatorTemplate",
                    "CSV locators must use the exact row:{row_index} template",
                )
        elif locator_type == "parquet_cell_v1":
            if locator_template != "row-group:{row_group}:row:{row_index}":
                _fail(
                    f"{path}.recordLocatorTemplate",
                    "Parquet locators need exact row-group and row coordinates",
                )
        fields = _object(evidence["fields"], f"{path}.fields", None)
        if not {"model_raw", "score_raw"} <= set(fields) or not set(fields) <= allowed_evidence_fields:
            _fail(f"{path}.fields", "must bind model_raw/score_raw and only approved raw fields")
        for raw_field, source_field in fields.items():
            if raw_field not in allowed_evidence_fields:
                _fail(f"{path}.fields.{raw_field}", "unapproved evidence field")
            _text(source_field, f"{path}.fields.{raw_field}")
        evidence_locator_types.append(locator_type)
        evidence_fields_by_locator[locator_type] = set(fields)
    if evidence_locator_types != sorted(evidence_locator_types) or len(set(evidence_locator_types)) != len(evidence_locator_types):
        _fail("$.extraction.evidenceContracts", "must be sorted and unique by locatorType")
    if set(evidence_locator_types) != set(locator_types):
        _fail("$.extraction.evidenceContracts", "must bind exactly every declared locatorType")
    display_dimensions = _sorted_unique_strings(
        extraction["allowedDisplayDimensions"],
        "$.extraction.allowedDisplayDimensions",
        minimum=len(_DIMENSIONS),
    )
    if display_dimensions != list(_DIMENSIONS):
        _fail("$.extraction.allowedDisplayDimensions", "must be exactly the five governed raw dimensions")
    dimensions = _object(extraction["dimensions"], "$.extraction.dimensions", set(_DIMENSIONS))
    for dimension_name in _DIMENSIONS:
        dimension = _object(
            dimensions[dimension_name],
            f"$.extraction.dimensions.{dimension_name}",
            {"mode", "value", "allowedValues"},
        )
        mode = _enum(
            dimension["mode"],
            {"revision_constant", "evidence_field"},
            f"$.extraction.dimensions.{dimension_name}.mode",
        )
        value = _text(
            dimension["value"],
            f"$.extraction.dimensions.{dimension_name}.value",
            nullable=True,
        )
        allowed_values = _sorted_unique_strings(
            dimension["allowedValues"],
            f"$.extraction.dimensions.{dimension_name}.allowedValues",
            minimum=1,
        )
        if mode == "revision_constant":
            if value is None or value not in allowed_values:
                _fail(f"$.extraction.dimensions.{dimension_name}", "constant must be explicitly allowed")
        else:
            if value is not None or any(
                dimension_name not in fields for fields in evidence_fields_by_locator.values()
            ):
                _fail(f"$.extraction.dimensions.{dimension_name}", "evidence mode needs every typed field binding")
    numeric = _object(
        extraction["numericPolicy"],
        "$.extraction.numericPolicy",
        {"lexeme", "scoreUnit", "minimumLexeme", "maximumLexeme", "permitDerivedScores", "coerceRawValues"},
    )
    numeric_lexeme = _enum(
        numeric["lexeme"], {"decimal", "decimal_percent"}, "$.extraction.numericPolicy.lexeme"
    )
    score_unit = _enum(
        numeric["scoreUnit"], {"fraction", "percent", "points"}, "$.extraction.numericPolicy.scoreUnit"
    )
    if numeric_lexeme == "decimal_percent" and score_unit != "percent":
        _fail("$.extraction.numericPolicy", "decimal_percent requires percent scoreUnit")
    minimum_score = _decimal_lexeme(numeric["minimumLexeme"], "$.extraction.numericPolicy.minimumLexeme")
    maximum_score = _decimal_lexeme(numeric["maximumLexeme"], "$.extraction.numericPolicy.maximumLexeme")
    if minimum_score > maximum_score:
        _fail("$.extraction.numericPolicy", "minimum score exceeds maximum")
    _constant(numeric["permitDerivedScores"], False, "$.extraction.numericPolicy.permitDerivedScores")
    _constant(numeric["coerceRawValues"], False, "$.extraction.numericPolicy.coerceRawValues")
    exclusions = _array(extraction["recordExclusions"], "$.extraction.recordExclusions")
    exclusion_ids: list[str] = []
    for index, raw_exclusion in enumerate(exclusions):
        path = f"$.extraction.recordExclusions[{index}]"
        exclusion = _object(
            raw_exclusion,
            path,
            {"exclusionId", "reasonCode", "predicate", "decisionReference"},
        )
        exclusion_ids.append(_stable_id(exclusion["exclusionId"], f"{path}.exclusionId"))
        _reason(exclusion["reasonCode"], f"{path}.reasonCode")
        _text(exclusion["predicate"], f"{path}.predicate")
        _stable_id(exclusion["decisionReference"], f"{path}.decisionReference")
    if exclusion_ids != sorted(exclusion_ids) or len(set(exclusion_ids)) != len(exclusion_ids):
        _fail("$.extraction.recordExclusions", "must be sorted and unique by exclusionId")

    completeness = _object(
        contract["completeness"],
        "$.completeness",
        {
            "scope",
            "expectedMinRecords",
            "expectedMaxRecords",
            "maxShards",
            "maxClaimCandidatesPerRecord",
            "requireEveryRecordAccounted",
            "requireNonzero",
            "rejectDuplicateLocators",
            "allowedExclusionIds",
            "accountingEquation",
            "quarantineOnUnexplainedLoss",
        },
    )
    _enum(
        completeness["scope"],
        {"complete_artifact", "complete_endpoint_result", "complete_manifest"},
        "$.completeness.scope",
    )
    minimum_records = _integer(completeness["expectedMinRecords"], "$.completeness.expectedMinRecords", minimum=1)
    maximum_records = _integer(completeness["expectedMaxRecords"], "$.completeness.expectedMaxRecords", minimum=1)
    if minimum_records > maximum_records:
        _fail("$.completeness", "minimum expected records exceeds maximum")
    _integer(completeness["maxShards"], "$.completeness.maxShards", minimum=1, maximum=10000)
    _integer(
        completeness["maxClaimCandidatesPerRecord"],
        "$.completeness.maxClaimCandidatesPerRecord",
        minimum=1,
        maximum=16,
    )
    for field in (
        "requireEveryRecordAccounted",
        "requireNonzero",
        "rejectDuplicateLocators",
        "quarantineOnUnexplainedLoss",
    ):
        _constant(completeness[field], True, f"$.completeness.{field}")
    allowed_exclusions = _sorted_unique_strings(
        completeness["allowedExclusionIds"], "$.completeness.allowedExclusionIds"
    )
    if allowed_exclusions != exclusion_ids:
        _fail("$.completeness.allowedExclusionIds", "must equal governed record exclusions")
    _constant(
        completeness["accountingEquation"],
        "observed=parsed+excluded+rejected+quarantined",
        "$.completeness.accountingEquation",
    )

    drift = _object(
        contract["drift"],
        "$.drift",
        {
            "schemaFingerprintPolicy",
            "approvedSchemaSha256",
            "baselineMinRecords",
            "baselineMaxRecords",
            "maxRecordCountChangeRatio",
            "pauseOnSchemaDrift",
            "pauseOnLocatorDrift",
            "pauseOnDimensionDrift",
            "pauseOnTermsChange",
            "incidentOwnerRole",
            "runbookId",
        },
    )
    _enum(
        drift["schemaFingerprintPolicy"],
        {"exact", "approved_additive"},
        "$.drift.schemaFingerprintPolicy",
    )
    _sha256(drift["approvedSchemaSha256"], "$.drift.approvedSchemaSha256")
    baseline_min = _integer(drift["baselineMinRecords"], "$.drift.baselineMinRecords", minimum=1)
    baseline_max = _integer(drift["baselineMaxRecords"], "$.drift.baselineMaxRecords", minimum=1)
    if baseline_min > baseline_max:
        _fail("$.drift", "baseline minimum exceeds maximum")
    ratio = _decimal_lexeme(
        drift["maxRecordCountChangeRatio"],
        "$.drift.maxRecordCountChangeRatio",
        minimum=Decimal("0"),
    )
    if ratio > Decimal("1"):
        _fail("$.drift.maxRecordCountChangeRatio", "ratio must not exceed one")
    for field in (
        "pauseOnSchemaDrift",
        "pauseOnLocatorDrift",
        "pauseOnDimensionDrift",
        "pauseOnTermsChange",
    ):
        _constant(drift[field], True, f"$.drift.{field}")
    _stable_id(drift["incidentOwnerRole"], "$.drift.incidentOwnerRole")
    _stable_id(drift["runbookId"], "$.drift.runbookId")

    schedule = _object(
        contract["schedule"],
        "$.schedule",
        {
            "schedulePolicyRevisionId",
            "cadence",
            "completionGrace",
            "maxAttempts",
            "retryableClasses",
            "rateLimitPerMinute",
            "maxConcurrency",
            "enabled",
        },
    )
    _stable_id(schedule["schedulePolicyRevisionId"], "$.schedule.schedulePolicyRevisionId")
    _duration(schedule["cadence"], "$.schedule.cadence")
    _duration(schedule["completionGrace"], "$.schedule.completionGrace")
    _integer(schedule["maxAttempts"], "$.schedule.maxAttempts", minimum=1, maximum=3)
    retry_classes = _sorted_unique_strings(schedule["retryableClasses"], "$.schedule.retryableClasses")
    if not set(retry_classes) <= _RETRYABLE_CLASSES:
        _fail("$.schedule.retryableClasses", "contains a non-retryable policy class")
    _integer(schedule["rateLimitPerMinute"], "$.schedule.rateLimitPerMinute", minimum=1, maximum=600)
    _integer(schedule["maxConcurrency"], "$.schedule.maxConcurrency", minimum=1, maximum=10)
    schedule_enabled = _boolean(schedule["enabled"], "$.schedule.enabled")

    storage = _object(
        contract["storage"],
        "$.storage",
        {
            "snapshotBeforeExtraction",
            "immutableObjectRequired",
            "conditionalNoOverwrite",
            "readBackSha256Required",
            "preserveSnapshotOnExtractionFailure",
        },
    )
    for field in storage:
        _constant(storage[field], True, f"$.storage.{field}")

    expected_counts = {
        "approvedSourceUrlCount": len(source_urls),
        "approvedFinalUrlCount": len(final_urls),
        "acceptedMimeTypeCount": len(mime_types),
        "locatorTypeCount": len(locator_types),
        "displayDimensionCount": len(display_dimensions),
        "recordExclusionCount": len(exclusions),
        "parserFixtureCount": len(fixture_digests),
    }
    for field, expected in expected_counts.items():
        if manifest[field] != expected:
            _fail(f"$.manifest.{field}", f"must equal payload count {expected}")

    actual_definition_digest = source_contract_definition_digest(payload)
    if definition_digest != actual_definition_digest:
        _fail("$.manifest.definitionSha256", "governed source-definition digest mismatch")
    if decision_outcome != "not_assessed" and decided_definition_digest != definition_digest:
        _fail(
            "$.certification.decidedContractDefinitionSha256",
            "external decision binds a different governed source definition",
        )

    if lifecycle == "draft_unapproved":
        if approval_status != "draft_unapproved" or capture_eligible or schedule_enabled:
            _fail("$.authority", "draft contract must remain unapproved, ineligible, and unscheduled")
        if decision_outcome != "not_assessed":
            _fail("$.certification", "draft contract cannot carry certification")
    elif lifecycle == "certification_pending":
        if approval_status != "external_review_pending" or capture_eligible or schedule_enabled:
            _fail("$.authority", "pending contract cannot fetch or schedule itself")
        if decision_outcome != "not_assessed":
            _fail("$.certification", "pending contract has no effective certification yet")
    elif lifecycle == "approved":
        if (
            approval_status != "external_certification_bound"
            or not capture_eligible
            or not schedule_enabled
            or decision_outcome != "certified"
            or terms_status != "reviewed_permitted"
        ):
            _fail("$", "approved contract needs external certification, permitted terms, and schedule")
        if implementation_status != "wired_peer_verified" or peer_proof_status != "implemented_verified":
            _fail("$.implementationBinding", "approval requires a wired connected-peer proof")
        if method_priority == 5:
            _fail("$.logicalSource.methodPriority", "browser reconnaissance cannot be capture-approved")
        if "parquet_cell_v1" in locator_types and parquet_status != "implemented_verified":
            _fail("$.implementationBinding.parquetLocatorSupport", "approved Parquet needs implemented locator support")
        if as_of is not None:
            assert certification_effective and certification_expires and terms_effective and review_due and terms_expires
            if as_of < certification_effective or as_of < terms_effective:
                _fail("$", "contract is not yet effective on the supplied date")
            if as_of > certification_expires:
                _fail("$.certification.expiresOn", "certification is expired on the supplied date")
            if as_of > review_due or as_of > terms_expires:
                _fail("$.termsReuse", "terms review or reuse authority is expired on the supplied date")
    else:
        if capture_eligible or schedule_enabled:
            _fail("$", "paused/revoked/retired contracts cannot remain capture-eligible or scheduled")
        if lifecycle == "revoked" and decision_outcome != "revoked":
            _fail("$.certification.decisionOutcome", "revoked lifecycle needs an external revoked decision")

    _verify_manifest(payload)


def validate_source_check_receipt(
    payload: dict[str, Any],
    *,
    source_contract: dict[str, Any] | None = None,
    as_of: date | None = None,
) -> None:
    """Validate an immutable source-check receipt and optional contract binding."""

    _walk_json(payload)
    if source_contract is not None:
        # Validate immutable shape and chronology first. Runtime eligibility is
        # checked below only for terminals that were allowed to perform work;
        # this permits an expired/paused contract to produce its required
        # fail-closed blocked receipt.
        validate_source_contract(source_contract)
    receipt = _object(payload, "$", _RECEIPT_KEYS)
    _constant(receipt["schemaVersion"], "1.0.0", "$.schemaVersion")
    _constant(receipt["policyVersion"], "source-check-receipt-v1", "$.policyVersion")
    availability = _enum(
        receipt["availability"],
        {"operational_receipt_only", "synthetic_evidence_only"},
        "$.availability",
    )
    receipt_id = _stable_id(receipt["receiptId"], "$.receiptId")

    identity = _object(
        receipt["identity"],
        "$.identity",
        {
            "sourceId",
            "sourceRevisionId",
            "contractId",
            "contractRevisionId",
            "contractDigestSha256",
            "contractDefinitionSha256",
            "certificationDecisionId",
            "certificationDecisionDigestSha256",
            "schedulePolicyRevisionId",
            "scheduledSlot",
            "jobId",
            "attemptId",
            "attemptNumber",
            "fencingToken",
            "expectedFencingToken",
        },
    )
    for field in (
        "sourceId",
        "sourceRevisionId",
        "contractId",
        "contractRevisionId",
        "schedulePolicyRevisionId",
        "jobId",
        "attemptId",
    ):
        _stable_id(identity[field], f"$.identity.{field}")
    _constant(
        receipt_id,
        derive_source_check_receipt_id(identity["attemptId"]),
        "$.receiptId",
    )
    _sha256(identity["contractDigestSha256"], "$.identity.contractDigestSha256")
    contract_definition_digest = _sha256(
        identity["contractDefinitionSha256"],
        "$.identity.contractDefinitionSha256",
    )
    decision_id = _stable_id(
        identity["certificationDecisionId"],
        "$.identity.certificationDecisionId",
        nullable=True,
    )
    decision_digest = _sha256(
        identity["certificationDecisionDigestSha256"],
        "$.identity.certificationDecisionDigestSha256",
        nullable=True,
    )
    if (decision_id is None) != (decision_digest is None):
        _fail("$.identity", "certification decision ID and digest must be present together")
    scheduled_slot = _instant(identity["scheduledSlot"], "$.identity.scheduledSlot")
    scheduled_date = scheduled_slot.date()
    if source_contract is not None and as_of is not None and as_of != scheduled_date:
        _fail(
            "$.identity.scheduledSlot",
            "explicit as_of must equal the deterministic scheduled-slot date",
        )
    attempt_number = _integer(identity["attemptNumber"], "$.identity.attemptNumber", minimum=1)
    fencing_token = _integer(identity["fencingToken"], "$.identity.fencingToken", minimum=1)
    expected_fencing = _integer(
        identity["expectedFencingToken"], "$.identity.expectedFencingToken", minimum=1
    )
    if fencing_token != expected_fencing:
        _fail("$.identity.fencingToken", "stale/mismatched fencing token")
    if len({receipt_id, identity["jobId"], identity["attemptId"]}) != 3:
        _fail("$.identity", "receipt, job, and attempt identities must be distinct")

    manifest = _object(
        receipt["manifest"],
        "$.manifest",
        {"algorithm", "contentSha256", "incidentReferenceCount"},
    )
    _constant(manifest["algorithm"], _ALGORITHM, "$.manifest.algorithm")
    _integer(manifest["incidentReferenceCount"], "$.manifest.incidentReferenceCount")

    authority = _object(
        receipt["authority"],
        "$.authority",
        {
            "classification",
            "certifiesSource",
            "authorizesCapture",
            "authorizesPublication",
            "createsClaims",
            "frontendLoadable",
        },
    )
    _constant(authority["classification"], "source_check_receipt_only", "$.authority.classification")
    for field in set(authority) - {"classification"}:
        _constant(authority[field], False, f"$.authority.{field}")

    terminal = _enum(
        receipt["terminalDisposition"],
        {
            "completed_unchanged",
            "completed_changed",
            "completed_with_review",
            "policy_blocked",
            "terms_quarantined",
            "retryable_failed",
            "attempted_policy_failed",
            "schema_quarantined",
            "snapshot_integrity_failed",
            "extraction_incomplete",
            "identity_review_required",
            "display_conflict",
            "operator_paused",
        },
        "$.terminalDisposition",
    )
    _reason(receipt["reasonCode"], "$.reasonCode")
    if availability == "synthetic_evidence_only" and terminal.startswith("completed_"):
        _fail("$.terminalDisposition", "synthetic evidence cannot claim a completed live source check")

    certification = _object(
        receipt["certificationCheck"],
        "$.certificationCheck",
        {
            "outcome",
            "checkedDecisionId",
            "checkedDecisionDigestSha256",
            "checkedSourceRevisionId",
            "checkedContractDigestSha256",
            "checkedContractDefinitionSha256",
            "checkedBeforeFetch",
            "checkedBeforeClaimWrite",
            "effectiveForAttempt",
        },
    )
    certification_outcome = _enum(
        certification["outcome"],
        {"certified", "missing", "expired", "mismatch", "quarantined", "revoked"},
        "$.certificationCheck.outcome",
    )
    checked_decision_id = _stable_id(
        certification["checkedDecisionId"],
        "$.certificationCheck.checkedDecisionId",
        nullable=True,
    )
    checked_decision_digest = _sha256(
        certification["checkedDecisionDigestSha256"],
        "$.certificationCheck.checkedDecisionDigestSha256",
        nullable=True,
    )
    checked_revision = _stable_id(
        certification["checkedSourceRevisionId"],
        "$.certificationCheck.checkedSourceRevisionId",
    )
    checked_contract_digest = _sha256(
        certification["checkedContractDigestSha256"],
        "$.certificationCheck.checkedContractDigestSha256",
    )
    checked_contract_definition_digest = _sha256(
        certification["checkedContractDefinitionSha256"],
        "$.certificationCheck.checkedContractDefinitionSha256",
    )
    _constant(certification["checkedBeforeFetch"], True, "$.certificationCheck.checkedBeforeFetch")
    _constant(
        certification["checkedBeforeClaimWrite"],
        True,
        "$.certificationCheck.checkedBeforeClaimWrite",
    )
    effective_for_attempt = _boolean(
        certification["effectiveForAttempt"], "$.certificationCheck.effectiveForAttempt"
    )
    if checked_revision != identity["sourceRevisionId"]:
        _fail("$.certificationCheck.checkedSourceRevisionId", "does not bind receipt source revision")
    if checked_contract_digest != identity["contractDigestSha256"]:
        _fail("$.certificationCheck.checkedContractDigestSha256", "does not bind receipt contract digest")
    if checked_contract_definition_digest != contract_definition_digest:
        _fail(
            "$.certificationCheck.checkedContractDefinitionSha256",
            "does not bind receipt contract definition digest",
        )
    if certification_outcome == "certified":
        if (
            not effective_for_attempt
            or decision_id is None
            or checked_decision_id != decision_id
            or checked_decision_digest != decision_digest
        ):
            _fail("$.certificationCheck", "certified outcome lacks the exact effective decision binding")
    elif certification_outcome == "missing":
        if effective_for_attempt or checked_decision_id is not None or checked_decision_digest is not None:
            _fail("$.certificationCheck", "missing outcome cannot invent an observed decision")
    elif certification_outcome == "mismatch":
        if (
            effective_for_attempt
            or checked_decision_id is None
            or checked_decision_digest is None
            or (
                checked_decision_id == decision_id
                and checked_decision_digest == decision_digest
            )
        ):
            _fail("$.certificationCheck", "mismatch needs one different observed decision binding")
    else:
        if effective_for_attempt:
            _fail("$.certificationCheck.effectiveForAttempt", "non-certified outcome cannot be effective")
        if (
            decision_id is None
            or checked_decision_id != decision_id
            or checked_decision_digest != decision_digest
        ):
            _fail("$.certificationCheck", "certification state must bind the expected external decision")

    request = _object(
        receipt["request"],
        "$.request",
        {
            "disposition",
            "method",
            "requestedUrl",
            "finalUrl",
            "lastApprovedUrl",
            "redirectCount",
            "statusCode",
            "conditionalRequestUsed",
            "responseBodyReceived",
            "failureStage",
            "failureCode",
        },
    )
    request_disposition = _enum(
        request["disposition"],
        {"not_started", "attempted_failed", "completed"},
        "$.request.disposition",
    )
    _constant(request["method"], "GET", "$.request.method")
    no_query_policy = {"mode": "none", "allowedParameterNames": []}
    receipt_query_policy = (
        source_contract["transport"]["queryPolicy"]
        if source_contract is not None
        else no_query_policy
    )
    requested_url = _canonical_https_url(
        request["requestedUrl"],
        "$.request.requestedUrl",
        query_policy=receipt_query_policy,
    )
    final_url = request["finalUrl"]
    if final_url is not None:
        final_url = _canonical_https_url(
            final_url,
            "$.request.finalUrl",
            query_policy=receipt_query_policy,
        )
    last_approved_url = request["lastApprovedUrl"]
    if last_approved_url is not None:
        last_approved_url = _canonical_https_url(
            last_approved_url,
            "$.request.lastApprovedUrl",
            query_policy=receipt_query_policy,
        )
    redirect_count = _integer(request["redirectCount"], "$.request.redirectCount", maximum=5)
    status_code = request["statusCode"]
    if status_code is not None:
        status_code = _integer(status_code, "$.request.statusCode", minimum=100, maximum=599)
    conditional_used = _boolean(
        request["conditionalRequestUsed"], "$.request.conditionalRequestUsed"
    )
    body_received = _boolean(request["responseBodyReceived"], "$.request.responseBodyReceived")
    failure_stage = request["failureStage"]
    if failure_stage is not None:
        failure_stage = _enum(
            failure_stage,
            set(_FETCH_FAILURE_CODES),
            "$.request.failureStage",
        )
    failure_code = request["failureCode"]
    if failure_code is not None:
        failure_code = _enum(
            failure_code,
            set().union(*_FETCH_FAILURE_CODES.values()),
            "$.request.failureCode",
        )
    if (failure_stage is None) != (failure_code is None):
        _fail("$.request", "failure stage and code must be present together")
    if failure_stage is not None and failure_code not in _FETCH_FAILURE_CODES[failure_stage]:
        _fail("$.request.failureCode", "does not belong to the declared failure stage")
    if request_disposition == "not_started":
        if (
            final_url is not None
            or last_approved_url is not None
            or redirect_count
            or status_code is not None
            or conditional_used
            or body_received
            or failure_stage is not None
        ):
            _fail("$.request", "not_started request cannot contain response/final URL facts")
    elif request_disposition == "completed":
        if (
            final_url is None
            or last_approved_url != final_url
            or status_code is None
            or failure_stage is not None
        ):
            _fail(
                "$.request",
                "completed request needs one exact final/last-approved URL, status, and no failure",
            )
    else:
        if failure_stage is None or body_received:
            _fail("$.request", "attempted_failed needs a typed failure and no complete body")
        if failure_stage in {"dns", "connect", "tls_peer"} and (
            final_url is not None or last_approved_url is None or status_code is not None
        ):
            _fail(
                "$.request",
                "pre-request network failure needs the exact approved attempted URL and no HTTP response facts",
            )
        if failure_stage == "redirect" and (
            final_url is not None
            or last_approved_url is None
            or status_code is None
            or not 300 <= status_code <= 399
            or redirect_count < 1
        ):
            _fail("$.request", "redirect failure needs a redirect status/count and no unsafe final URL")
        if failure_stage in {"response_headers", "response_body"} and (
            final_url is None
            or last_approved_url != final_url
            or status_code is None
        ):
            _fail("$.request", "response failure needs the last approved final URL and HTTP status")
        if failure_stage == "request" and last_approved_url is None:
            _fail("$.request.lastApprovedUrl", "request-stage failure needs the approved URL attempted")
    if availability == "synthetic_evidence_only" and request_disposition != "not_started":
        _fail("$.request.disposition", "synthetic evidence cannot claim a live fetch attempt")

    network = _object(
        receipt["networkEvidence"],
        "$.networkEvidence",
        {
            "dnsPolicyStatus",
            "connectedPeerStatus",
            "tlsStatus",
            "connectedPeerAddressClass",
            "finalHost",
        },
    )
    dns_status = _enum(
        network["dnsPolicyStatus"], {"not_checked", "passed", "failed"}, "$.networkEvidence.dnsPolicyStatus"
    )
    peer_status = _enum(
        network["connectedPeerStatus"],
        {"not_checked", "passed", "failed", "required_not_implemented"},
        "$.networkEvidence.connectedPeerStatus",
    )
    tls_status = _enum(
        network["tlsStatus"], {"not_checked", "passed", "failed"}, "$.networkEvidence.tlsStatus"
    )
    address_class = _enum(
        network["connectedPeerAddressClass"],
        {"not_observed", "public", "unsafe"},
        "$.networkEvidence.connectedPeerAddressClass",
    )
    final_host = network["finalHost"]
    if final_host is not None:
        final_host = _host(final_host, "$.networkEvidence.finalHost")
    if request_disposition == "completed":
        if (dns_status, peer_status, tls_status, address_class) != (
            "passed",
            "passed",
            "passed",
            "public",
        ):
            _fail("$.networkEvidence", "completed fetch needs DNS, connected-peer, and TLS proof")
        if final_url is None or final_host != urlsplit(final_url).hostname:
            _fail("$.networkEvidence.finalHost", "must equal the exact final URL host")
    elif request_disposition == "not_started":
        if (
            dns_status != "not_checked"
            or peer_status != "not_checked"
            or tls_status != "not_checked"
            or address_class != "not_observed"
            or final_host is not None
        ):
            _fail("$.networkEvidence", "unstarted request cannot claim network proof")
    else:
        requested_host = urlsplit(requested_url).hostname
        assert failure_stage is not None and failure_code is not None and requested_host is not None
        if last_approved_url is None:
            _fail("$.request.lastApprovedUrl", "attempted failure needs its exact approved attempted URL")
        attempted_host = urlsplit(last_approved_url).hostname
        assert attempted_host is not None
        if failure_stage == "dns":
            if (dns_status, peer_status, tls_status, address_class, final_host) != (
                "failed",
                "not_checked",
                "not_checked",
                "not_observed",
                attempted_host,
            ):
                _fail(
                    "$.networkEvidence",
                    "DNS failure must bind the attempted approved host and stop before connection evidence",
                )
        elif failure_stage == "connect":
            if (dns_status, peer_status, tls_status, address_class, final_host) != (
                "passed",
                "not_checked",
                "not_checked",
                "not_observed",
                attempted_host,
            ):
                _fail("$.networkEvidence", "connect failure needs only passed DNS evidence")
        elif failure_stage == "tls_peer":
            expected_tls_peer: dict[str, tuple[str, str, str]] = {
                "TLS_FAILED": ("passed", "failed", "public"),
                "CONNECTED_PEER_UNSAFE": ("failed", "not_checked", "unsafe"),
                "CONNECTED_PEER_PROOF_MISSING": (
                    "required_not_implemented",
                    "not_checked",
                    "not_observed",
                ),
            }
            expected_peer, expected_tls, expected_address = expected_tls_peer[failure_code]
            if (
                dns_status != "passed"
                or peer_status != expected_peer
                or tls_status != expected_tls
                or address_class != expected_address
                or final_host != attempted_host
            ):
                _fail("$.networkEvidence", "TLS/peer failure evidence contradicts its failure code")
        else:
            if last_approved_url is None:
                _fail("$.request.lastApprovedUrl", "post-connect failure needs its last approved URL")
            expected_final_host = urlsplit(last_approved_url).hostname
            if (dns_status, peer_status, tls_status, address_class) != (
                "passed",
                "passed",
                "passed",
                "public",
            ) or final_host != expected_final_host:
                _fail(
                    "$.networkEvidence",
                    "post-connect failure needs passed DNS/peer/TLS evidence for the last approved host",
                )

    response = _object(
        receipt["response"],
        "$.response",
        {
            "contentChanged",
            "bytesReceived",
            "contentSha256",
            "mimeType",
            "retryClassification",
            "retryAfterSeconds",
        },
    )
    content_changed = response["contentChanged"]
    if content_changed is not None and type(content_changed) is not bool:
        _fail("$.response.contentChanged", "must be boolean or null")
    bytes_received = _integer(response["bytesReceived"], "$.response.bytesReceived")
    content_digest = _sha256(
        response["contentSha256"], "$.response.contentSha256", nullable=True
    )
    mime_type = response["mimeType"]
    if mime_type is not None:
        mime_type = _text(mime_type, "$.response.mimeType")
        if _MIME.fullmatch(mime_type) is None:
            _fail("$.response.mimeType", "malformed MIME type")
    retry_classification = _enum(
        response["retryClassification"],
        {"none", "transient", "rate_limited", "non_retryable_policy", "non_retryable_contract"},
        "$.response.retryClassification",
    )
    retry_after = response["retryAfterSeconds"]
    if retry_after is not None:
        retry_after = _integer(retry_after, "$.response.retryAfterSeconds", minimum=1, maximum=86400)
    if retry_classification == "rate_limited" and retry_after is None:
        _fail("$.response.retryAfterSeconds", "rate-limited response needs a bounded retry delay")
    if retry_classification != "rate_limited" and retry_after is not None:
        _fail("$.response.retryAfterSeconds", "retry delay is allowed only for rate limiting")
    if request_disposition == "not_started" and (
        content_changed is not None
        or bytes_received != 0
        or content_digest is not None
        or mime_type is not None
    ):
        _fail("$.response", "an unstarted request cannot carry response body facts")
    if request_disposition == "attempted_failed":
        assert failure_stage is not None and failure_code is not None
        if content_changed is not None or content_digest is not None:
            _fail("$.response", "failed attempt cannot claim complete/change-hashed response bytes")
        if failure_stage != "response_body" and bytes_received != 0:
            _fail("$.response.bytesReceived", "bytes are allowed only for a partial body failure")
        if failure_stage not in {"response_headers", "response_body"} and mime_type is not None:
            _fail("$.response.mimeType", "pre-response failure cannot claim a MIME type")
        if failure_code == "MIME_UNAPPROVED" and mime_type is None:
            _fail("$.response.mimeType", "MIME failure must record the observed redacted MIME type")
        if failure_code == "HTTP_429" and (
            status_code != 429 or retry_classification != "rate_limited"
        ):
            _fail("$.response", "HTTP_429 failure needs status 429 and rate-limited retry")
        if failure_code == "HTTP_5XX" and (
            status_code is None
            or not 500 <= status_code <= 599
            or retry_classification != "transient"
        ):
            _fail("$.response", "HTTP_5XX failure needs a 5xx status and transient retry")
        if failure_code == "BODY_SIZE_EXCEEDED" and bytes_received < 1:
            _fail("$.response.bytesReceived", "body-size failure needs the observed partial byte count")

    conditional = _object(
        receipt["conditionalMetadata"],
        "$.conditionalMetadata",
        {
            "previousSnapshotId",
            "previousSnapshotContentSha256",
            "previousSnapshotVerificationReceiptSha256",
            "etagRequestSha256",
            "lastModifiedRequestSha256",
            "etagResponseSha256",
            "lastModifiedResponseSha256",
        },
    )
    previous_snapshot_id = _stable_id(
        conditional["previousSnapshotId"], "$.conditionalMetadata.previousSnapshotId", nullable=True
    )
    conditional_digests: dict[str, str | None] = {}
    for field in (
        "previousSnapshotContentSha256",
        "previousSnapshotVerificationReceiptSha256",
        "etagRequestSha256",
        "lastModifiedRequestSha256",
        "etagResponseSha256",
        "lastModifiedResponseSha256",
    ):
        conditional_digests[field] = _sha256(
            conditional[field], f"$.conditionalMetadata.{field}", nullable=True
        )
    previous_snapshot_content_digest = conditional_digests[
        "previousSnapshotContentSha256"
    ]
    previous_snapshot_verification_digest = conditional_digests[
        "previousSnapshotVerificationReceiptSha256"
    ]
    if previous_snapshot_id is None and (
        previous_snapshot_content_digest is not None
        or previous_snapshot_verification_digest is not None
    ):
        _fail(
            "$.conditionalMetadata",
            "no-prior-snapshot case cannot carry prior content/verification bindings",
        )
    if previous_snapshot_id is not None and (
        previous_snapshot_content_digest is None
        or previous_snapshot_verification_digest is None
    ):
        _fail(
            "$.conditionalMetadata",
            "prior snapshot reference needs exact content and verification-receipt digests",
        )
    if request_disposition == "not_started" and (
        previous_snapshot_id is not None
        or any(value is not None for value in conditional_digests.values())
    ):
        _fail("$.conditionalMetadata", "an unstarted request cannot carry conditional HTTP facts")

    snapshot = _object(
        receipt["snapshot"],
        "$.snapshot",
        {
            "snapshotId",
            "snapshotContentSha256",
            "storageReceiptSha256",
            "status",
            "immutable",
            "readBackVerified",
            "committedBeforeExtraction",
        },
    )
    snapshot_status = _enum(
        snapshot["status"],
        {"not_created", "committed_reverified", "integrity_failed"},
        "$.snapshot.status",
    )
    snapshot_id = _stable_id(snapshot["snapshotId"], "$.snapshot.snapshotId", nullable=True)
    snapshot_digest = _sha256(
        snapshot["snapshotContentSha256"], "$.snapshot.snapshotContentSha256", nullable=True
    )
    storage_receipt_digest = _sha256(
        snapshot["storageReceiptSha256"], "$.snapshot.storageReceiptSha256", nullable=True
    )
    immutable_snapshot = _boolean(snapshot["immutable"], "$.snapshot.immutable")
    read_back = _boolean(snapshot["readBackVerified"], "$.snapshot.readBackVerified")
    before_extraction = _boolean(
        snapshot["committedBeforeExtraction"], "$.snapshot.committedBeforeExtraction"
    )
    if snapshot_status == "not_created":
        if any(value is not None for value in (snapshot_id, snapshot_digest, storage_receipt_digest)) or any(
            (immutable_snapshot, read_back, before_extraction)
        ):
            _fail("$.snapshot", "not_created snapshot cannot carry identity or verification")
    elif snapshot_status == "committed_reverified":
        if any(value is None for value in (snapshot_id, snapshot_digest, storage_receipt_digest)) or not all(
            (immutable_snapshot, read_back, before_extraction)
        ):
            _fail("$.snapshot", "committed snapshot needs immutable read-back proof before extraction")
        if snapshot_digest != content_digest:
            _fail("$.snapshot.snapshotContentSha256", "snapshot digest differs from response bytes")
    else:
        if read_back or before_extraction:
            _fail("$.snapshot", "integrity-failed snapshot cannot be verified/committed for extraction")

    extraction = _object(
        receipt["extraction"],
        "$.extraction",
        {
            "disposition",
            "sourceRecordsObserved",
            "rowsParsed",
            "claimCandidatesEmitted",
            "claimsAdmitted",
            "recordsExcluded",
            "recordsRejected",
            "recordsQuarantined",
            "evidenceLocatorCoverageCount",
            "duplicateLocatorCount",
            "unexplainedRecordCount",
            "schemaFingerprintSha256",
            "batchReceiptSha256",
            "dimensionsObserved",
        },
    )
    extraction_disposition = _enum(
        extraction["disposition"], {"not_run", "accounted", "quarantined"}, "$.extraction.disposition"
    )
    count_fields = (
        "sourceRecordsObserved",
        "rowsParsed",
        "claimCandidatesEmitted",
        "claimsAdmitted",
        "recordsExcluded",
        "recordsRejected",
        "recordsQuarantined",
        "evidenceLocatorCoverageCount",
        "duplicateLocatorCount",
        "unexplainedRecordCount",
    )
    counts = {field: _integer(extraction[field], f"$.extraction.{field}") for field in count_fields}
    schema_fingerprint = _sha256(
        extraction["schemaFingerprintSha256"],
        "$.extraction.schemaFingerprintSha256",
        nullable=True,
    )
    batch_digest = _sha256(
        extraction["batchReceiptSha256"], "$.extraction.batchReceiptSha256", nullable=True
    )
    dimensions_observed = _sorted_unique_strings(
        extraction["dimensionsObserved"], "$.extraction.dimensionsObserved"
    )
    if not set(dimensions_observed) <= set(_DIMENSIONS):
        _fail("$.extraction.dimensionsObserved", "contains an unapproved display dimension")
    if extraction_disposition == "not_run":
        if any(counts.values()) or schema_fingerprint is not None or batch_digest is not None or dimensions_observed:
            _fail("$.extraction", "not_run extraction cannot carry accounting results")
    else:
        if schema_fingerprint is None or batch_digest is None:
            _fail("$.extraction", "executed extraction needs schema and batch digests")
        if counts["sourceRecordsObserved"] != (
            counts["rowsParsed"]
            + counts["recordsExcluded"]
            + counts["recordsRejected"]
            + counts["recordsQuarantined"]
        ):
            _fail("$.extraction", "record accounting does not balance")
        candidates_per_record = (
            source_contract["completeness"]["maxClaimCandidatesPerRecord"]
            if source_contract is not None
            else 1
        )
        if counts["claimCandidatesEmitted"] > counts["rowsParsed"] * candidates_per_record:
            _fail(
                "$.extraction.claimCandidatesEmitted",
                "exceeds the governed per-record claim-candidate cap",
            )
        if counts["claimsAdmitted"] > counts["claimCandidatesEmitted"]:
            _fail("$.extraction.claimsAdmitted", "cannot exceed claim candidates")
        if counts["evidenceLocatorCoverageCount"] != counts["claimCandidatesEmitted"]:
            _fail("$.extraction.evidenceLocatorCoverageCount", "must cover every claim candidate")
        if extraction_disposition == "accounted" and (
            counts["unexplainedRecordCount"] or counts["duplicateLocatorCount"]
        ):
            _fail("$.extraction", "accounted extraction cannot retain unexplained/duplicate locators")

    incident_references = _sorted_unique_strings(
        receipt["incidentReferences"], "$.incidentReferences", validator=_stable_id
    )
    if manifest["incidentReferenceCount"] != len(incident_references):
        _fail("$.manifest.incidentReferenceCount", "does not match incident references")

    execution = _object(
        receipt["execution"],
        "$.execution",
        {"startedAt", "finishedAt", "durationMs"},
    )
    started_at = _instant(execution["startedAt"], "$.execution.startedAt")
    finished_at = _instant(execution["finishedAt"], "$.execution.finishedAt")
    duration_ms = _integer(execution["durationMs"], "$.execution.durationMs")
    if finished_at < started_at or int((finished_at - started_at).total_seconds() * 1000) != duration_ms:
        _fail("$.execution", "duration must exactly match start/finish instants")
    if started_at < scheduled_slot:
        _fail("$.execution.startedAt", "attempt cannot start before its scheduled slot")
    if attempt_number < 1:  # pragma: no cover - already enforced, documents identity dependency
        _fail("$.identity.attemptNumber", "must be positive")

    changed_terminals = {
        "completed_changed",
        "completed_with_review",
        "schema_quarantined",
        "extraction_incomplete",
        "identity_review_required",
        "display_conflict",
    }
    blocked_terminals = {"policy_blocked", "terms_quarantined", "operator_paused"}
    retryable_failure_codes = {
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
    if terminal in blocked_terminals:
        if request_disposition != "not_started" or snapshot_status != "not_created" or extraction_disposition != "not_run":
            _fail("$", "blocked/paused receipt cannot fetch, snapshot, or extract")
        if not incident_references:
            _fail("$.incidentReferences", "blocked receipt needs an incident/review reference")
    elif terminal == "completed_unchanged":
        if certification_outcome != "certified":
            _fail("$.certificationCheck.outcome", "unchanged success requires effective certification")
        if (
            request_disposition != "completed"
            or status_code != 304
            or body_received
            or not conditional_used
            or previous_snapshot_id is None
            or previous_snapshot_content_digest is None
            or previous_snapshot_verification_digest is None
            or (
                conditional_digests["etagRequestSha256"] is None
                and conditional_digests["lastModifiedRequestSha256"] is None
            )
            or content_changed is not False
            or bytes_received != 0
            or content_digest is not None
            or mime_type is not None
            or snapshot_status != "not_created"
            or extraction_disposition != "not_run"
            or retry_classification != "none"
        ):
            _fail("$", "completed_unchanged must be a bodyless conditional 304 reusing a prior snapshot")
    elif terminal in changed_terminals:
        if certification_outcome != "certified":
            _fail("$.certificationCheck.outcome", "changed artifact handling requires certification")
        if (
            request_disposition != "completed"
            or status_code != 200
            or not body_received
            or content_changed is not True
            or bytes_received < 1
            or content_digest is None
            or mime_type is None
            or snapshot_status != "committed_reverified"
            or retry_classification != "none"
        ):
            _fail("$", "changed 200 must be bounded, hashed, and snapshotted before extraction")
        required_extraction = (
            "accounted"
            if terminal
            in {
                "completed_changed",
                "completed_with_review",
                "identity_review_required",
                "display_conflict",
            }
            else "quarantined"
        )
        if extraction_disposition != required_extraction:
            _fail("$.extraction.disposition", f"{terminal} requires {required_extraction}")
        if required_extraction == "accounted" and (
            counts["sourceRecordsObserved"] < 1
            or counts["claimCandidatesEmitted"] < 1
            or dimensions_observed != list(_DIMENSIONS)
        ):
            _fail(
                "$.extraction",
                "accounted changed completion needs records, claim candidates, and all governed dimensions",
            )
        if terminal == "completed_changed" and (
            counts["recordsRejected"]
            or counts["recordsQuarantined"]
            or counts["claimsAdmitted"] != counts["claimCandidatesEmitted"]
        ):
            _fail("$.extraction", "completed_changed requires a fully admitted accounted batch")
    elif terminal == "snapshot_integrity_failed":
        if (
            certification_outcome != "certified"
            or request_disposition != "completed"
            or status_code != 200
            or not body_received
            or content_changed is not True
            or bytes_received < 1
            or content_digest is None
            or snapshot_status != "integrity_failed"
            or extraction_disposition != "not_run"
        ):
            _fail("$", "snapshot integrity failure must preserve changed-response facts and skip extraction")
    elif terminal == "retryable_failed":
        if (
            certification_outcome != "certified"
            or request_disposition != "attempted_failed"
            or snapshot_status != "not_created"
            or extraction_disposition != "not_run"
            or failure_code not in retryable_failure_codes
        ):
            _fail("$", "retryable failure needs a certified truthful attempt and no snapshot/extraction")
        if retry_classification not in {"transient", "rate_limited"}:
            _fail("$.response.retryClassification", "retryable failure needs an explicitly transient class")
    elif terminal == "attempted_policy_failed":
        if (
            certification_outcome != "certified"
            or request_disposition != "attempted_failed"
            or snapshot_status != "not_created"
            or extraction_disposition != "not_run"
            or failure_code in retryable_failure_codes
            or retry_classification
            not in {"non_retryable_policy", "non_retryable_contract"}
        ):
            _fail(
                "$",
                "attempted policy failure needs a certified typed non-retryable attempt and no writes",
            )

    if terminal not in {"completed_unchanged", "completed_changed"} and not incident_references:
        _fail("$.incidentReferences", "abnormal/review terminal needs an incident reference")

    if source_contract is not None:
        if terminal not in blocked_terminals and certification_outcome == "certified":
            validate_source_contract(source_contract, as_of=scheduled_date)
        if (
            identity["sourceId"] != source_contract["logicalSource"]["sourceId"]
            or identity["sourceRevisionId"] != source_contract["logicalSource"]["sourceRevisionId"]
            or identity["contractId"] != source_contract["contractId"]
            or identity["contractRevisionId"] != source_contract["contractRevisionId"]
            or identity["contractDigestSha256"] != source_contract["manifest"]["contentSha256"]
            or identity["contractDefinitionSha256"]
            != source_contract["manifest"]["definitionSha256"]
            or identity["schedulePolicyRevisionId"]
            != source_contract["schedule"]["schedulePolicyRevisionId"]
        ):
            _fail("$.identity", "receipt does not bind the exact source contract revision")
        contract_certification = source_contract["certification"]
        if decision_id != contract_certification["decisionId"] or decision_digest != contract_certification["decisionDigestSha256"]:
            _fail("$.identity.certificationDecisionId", "receipt decision differs from source contract")
        contract_decision_outcome = contract_certification["decisionOutcome"]
        if certification_outcome == "certified":
            if contract_decision_outcome != "certified":
                _fail("$.certificationCheck.outcome", "contract does not carry a certified decision")
            effective_on = date.fromisoformat(contract_certification["effectiveOn"])
            expires_on = date.fromisoformat(contract_certification["expiresOn"])
            if not effective_on <= scheduled_date <= expires_on:
                _fail("$.certificationCheck.outcome", "certification is not effective for the scheduled slot")
        elif certification_outcome == "expired":
            if (
                contract_decision_outcome != "certified"
                or scheduled_date <= date.fromisoformat(contract_certification["expiresOn"])
            ):
                _fail("$.certificationCheck.outcome", "expired outcome is not supported by the bound decision/slot")
        elif certification_outcome in {"quarantined", "revoked"} and contract_decision_outcome != certification_outcome:
            _fail("$.certificationCheck.outcome", "receipt decision state differs from the source contract")
        contract_terms = source_contract["termsReuse"]
        terms_effective_for_slot = False
        if contract_terms["status"] == "reviewed_permitted":
            terms_effective_for_slot = (
                date.fromisoformat(contract_terms["effectiveOn"])
                <= scheduled_date
                <= date.fromisoformat(contract_terms["reviewDueOn"])
                and scheduled_date <= date.fromisoformat(contract_terms["expiresOn"])
            )
        if certification_outcome == "certified":
            if terminal == "terms_quarantined" and terms_effective_for_slot:
                _fail(
                    "$.terminalDisposition",
                    "terms_quarantined contradicts terms effective for the scheduled slot",
                )
            if terminal != "terms_quarantined" and not terms_effective_for_slot:
                _fail(
                    "$.terminalDisposition",
                    "ineffective terms for the scheduled slot require terms_quarantined",
                )
        if requested_url not in source_contract["transport"]["approvedSourceUrls"]:
            _fail("$.request.requestedUrl", "is outside the exact source URL allowlist")
        if final_url is not None and final_url not in source_contract["transport"]["approvedFinalUrls"]:
            _fail("$.request.finalUrl", "is outside the exact final URL allowlist")
        if last_approved_url is not None and last_approved_url not in {
            *source_contract["transport"]["approvedSourceUrls"],
            *source_contract["transport"]["approvedFinalUrls"],
        }:
            _fail("$.request.lastApprovedUrl", "is outside the exact approved URL sets")
        if (
            redirect_count > source_contract["transport"]["redirectPolicy"]["maxRedirects"]
            and not (
                request_disposition == "attempted_failed"
                and failure_code
                in {"REDIRECT_LIMIT_EXCEEDED", "REDIRECT_UNAPPROVED"}
            )
        ):
            _fail("$.request.redirectCount", "exceeds the source contract redirect limit")
        if bytes_received > source_contract["transport"]["maxBytes"] and not (
            request_disposition == "attempted_failed"
            and failure_code == "BODY_SIZE_EXCEEDED"
        ):
            _fail("$.response.bytesReceived", "exceeds the source contract byte limit")
        if (
            mime_type is not None
            and mime_type not in source_contract["transport"]["acceptedMimeTypes"]
            and not (
                request_disposition == "attempted_failed"
                and failure_code == "MIME_UNAPPROVED"
            )
        ):
            _fail("$.response.mimeType", "is outside the source contract MIME allowlist")
        if not set(dimensions_observed) <= set(source_contract["extraction"]["allowedDisplayDimensions"]):
            _fail("$.extraction.dimensionsObserved", "contains a contract-unapproved dimension")
        if certification_outcome == "certified" and source_contract["lifecycleStatus"] != "approved" and not (
            terminal == "operator_paused"
            and source_contract["lifecycleStatus"] == "paused"
        ):
            _fail("$.certificationCheck", "receipt cannot promote a non-approved source contract")
        if source_contract["implementationBinding"]["connectedPeerProof"] != "implemented_verified" and request_disposition == "completed":
            _fail("$.networkEvidence.connectedPeerStatus", "contract records connected-peer proof as not implemented")
        if terminal in {
            "completed_changed",
            "completed_with_review",
            "identity_review_required",
            "display_conflict",
        }:
            expected_minimum = source_contract["completeness"]["expectedMinRecords"]
            expected_maximum = source_contract["completeness"]["expectedMaxRecords"]
            if not expected_minimum <= counts["sourceRecordsObserved"] <= expected_maximum:
                _fail("$.extraction.sourceRecordsObserved", "is outside the contract cardinality bounds")
            if (
                source_contract["drift"]["schemaFingerprintPolicy"] == "exact"
                and schema_fingerprint != source_contract["drift"]["approvedSchemaSha256"]
            ):
                _fail("$.extraction.schemaFingerprintSha256", "does not match the exact approved schema")

    _verify_manifest(payload)
