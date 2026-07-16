"""Executable semantic validation for coverage and discovery contracts.

The JSON Schemas in ``docs/contracts`` describe the wire shape.  This module
implements the cross-field rules that JSON Schema cannot express reliably:
stable-identity uniqueness, denominator accounting, lifecycle bindings,
candidate fingerprints, canonical self-digests, and conservative URL safety.

The validators are deliberately pure and standard-library-only.  They perform
no file, network, database, clock, or environment access and never normalize or
mutate the supplied payload.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import date
import hashlib
import ipaddress
import json
import math
from pathlib import PurePosixPath, PureWindowsPath
import re
from typing import Any
from urllib.parse import unquote, urlsplit


class CoverageContractError(ValueError):
    """Raised when a coverage/discovery contract is not admissible."""


_STABLE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_REASON_CODE = re.compile(r"^[A-Z][A-Z0-9_]{2,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_DURATION = re.compile(
    r"^P(?!$)(?:[0-9]+D)?(?:T(?=[0-9])(?:[0-9]+H)?(?:[0-9]+M)?(?:[0-9]+S)?)?$"
)
_HOST = re.compile(
    r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)*"
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$"
)

_SELF_DIGEST_ALGORITHM = "sha256-canonical-json-v1"
_FORBIDDEN_AUTHORITY_FLAGS = (
    "certifiesSources",
    "authorizesCapture",
    "authorizesPublication",
    "frontendLoadable",
)
_MUTABLE_FIELD_NAMES = {
    "capturedat",
    "checkedat",
    "createdat",
    "fetchedat",
    "generatedat",
    "lastchecked",
    "lastcheckedat",
    "lastmodified",
    "lastmodifiedat",
    "observedat",
    "refreshedat",
    "retrievedat",
    "timestamp",
    "timestamps",
    "updatedat",
}


_UNIVERSE_KEYS = {
    "schemaVersion",
    "policyVersion",
    "availability",
    "universeRevisionId",
    "supersedesUniverseRevisionId",
    "effectiveOn",
    "decisionReference",
    "authority",
    "manifest",
    "scope",
    "cohorts",
    "benchmarks",
    "configuredSourceRoutes",
    "sourceClasses",
    "refreshPolicy",
    "exclusions",
    "publicWording",
}
_TARGET_KEYS = {
    "schemaVersion",
    "policyVersion",
    "availability",
    "targetRevisionId",
    "supersedesTargetRevisionId",
    "targetId",
    "configurationStatus",
    "decisionReference",
    "reasonCode",
    "authority",
    "manifest",
    "owner",
    "officialOrigin",
    "connector",
    "urlPolicy",
    "duePolicy",
    "termsReview",
    "correctionRoute",
    "budgets",
    "affectedBenchmarkIds",
}
_CANDIDATE_KEYS = {
    "schemaVersion",
    "policyVersion",
    "availability",
    "candidateId",
    "candidateFingerprintSha256",
    "candidateType",
    "state",
    "stateDecisionReference",
    "approvedSourceRevisionReference",
    "reasonCode",
    "targetRevisionId",
    "authority",
    "manifest",
    "owner",
    "candidateIdentity",
    "officialUrls",
    "affectedBenchmarkIds",
    "artifactHint",
    "termsHint",
    "evidenceReferences",
}


def _fail(path: str, message: str) -> None:
    raise CoverageContractError(f"{path}: {message}")


def _walk_json(value: Any, path: str = "$") -> None:
    """Reject values that cannot participate in deterministic canonical JSON."""

    if value is None or type(value) in (str, bool, int):
        return
    if type(value) is float:
        if not math.isfinite(value):
            _fail(path, "non-finite numbers are forbidden")
        return
    if type(value) is list:
        for index, item in enumerate(value):
            _walk_json(item, f"{path}[{index}]")
        return
    if type(value) is dict:
        for key, item in value.items():
            if type(key) is not str:
                _fail(path, "object keys must be strings")
            normalized_key = re.sub(r"[^a-z0-9]", "", key.lower())
            if (
                normalized_key in _MUTABLE_FIELD_NAMES
                or "mtime" in normalized_key
                or normalized_key.endswith("timestamp")
            ):
                _fail(f"{path}.{key}", "mutable timestamps/mtimes are forbidden")
            if normalized_key.endswith("path"):
                _relative_contract_path(item, f"{path}.{key}")
            _walk_json(item, f"{path}.{key}")
        return
    _fail(path, f"unsupported canonical JSON type {type(value).__name__}")


def canonical_json(value: Any) -> str:
    """Return the contract's compact, ASCII-escaped canonical JSON form."""

    _walk_json(value)
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def contract_self_digest(payload: dict[str, Any]) -> str:
    """Compute ``sha256-canonical-json-v1`` for a self-digested contract.

    Only ``manifest.contentSha256`` is replaced with ``null``.  Array order is
    preserved, as required by the contract; callers must not sort the document.
    """

    if type(payload) is not dict:
        _fail("$", "contract must be an object")
    material = deepcopy(payload)
    manifest = material.get("manifest")
    if type(manifest) is not dict or "contentSha256" not in manifest:
        _fail("$.manifest.contentSha256", "is required for self-digesting")
    manifest["contentSha256"] = None
    encoded = canonical_json(material).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def verify_contract_self_digest(payload: dict[str, Any]) -> None:
    """Verify a contract's declared canonical self-digest."""

    manifest = _object(payload.get("manifest"), "$.manifest", None)
    _constant(manifest.get("algorithm"), _SELF_DIGEST_ALGORITHM, "$.manifest.algorithm")
    declared = _sha256(manifest.get("contentSha256"), "$.manifest.contentSha256")
    actual = contract_self_digest(payload)
    if declared != actual:
        _fail(
            "$.manifest.contentSha256",
            f"self-digest mismatch (declared {declared}, computed {actual})",
        )


def _object(
    value: Any,
    path: str,
    exact_keys: set[str] | frozenset[str] | None,
) -> dict[str, Any]:
    if type(value) is not dict:
        _fail(path, "must be an object")
    if exact_keys is not None:
        present = set(value)
        if present != exact_keys:
            missing = sorted(exact_keys - present)
            extra = sorted(present - exact_keys)
            details: list[str] = []
            if missing:
                details.append(f"missing keys {missing}")
            if extra:
                details.append(f"unexpected keys {extra}")
            _fail(path, "; ".join(details))
    return value


def _array(value: Any, path: str, *, minimum: int = 0) -> list[Any]:
    if type(value) is not list:
        _fail(path, "must be an array")
    if len(value) < minimum:
        _fail(path, f"must contain at least {minimum} item(s)")
    return value


def _constant(value: Any, expected: Any, path: str) -> None:
    if value != expected or type(value) is not type(expected):
        _fail(path, f"must equal {expected!r}")


def _enum(value: Any, permitted: set[str] | frozenset[str], path: str) -> str:
    if type(value) is not str or value not in permitted:
        _fail(path, f"must be one of {sorted(permitted)}")
    return value


def _boolean(value: Any, path: str) -> bool:
    if type(value) is not bool:
        _fail(path, "must be a boolean")
    return value


def _integer(
    value: Any,
    path: str,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    if type(value) is not int:
        _fail(path, "must be an integer")
    if minimum is not None and value < minimum:
        _fail(path, f"must be at least {minimum}")
    if maximum is not None and value > maximum:
        _fail(path, f"must be at most {maximum}")
    return value


def _non_empty(value: Any, path: str) -> str:
    if type(value) is not str or not value.strip():
        _fail(path, "must be a non-empty string")
    return value


def _stable_id(value: Any, path: str, *, nullable: bool = False) -> str | None:
    if nullable and value is None:
        return None
    if type(value) is not str or _STABLE_ID.fullmatch(value) is None:
        _fail(path, "must be a stable lowercase identifier")
    return value


def _reason_code(value: Any, path: str) -> str:
    if type(value) is not str or _REASON_CODE.fullmatch(value) is None:
        _fail(path, "must be an explicit uppercase reason code")
    return value


def _sha256(value: Any, path: str, *, nullable: bool = False) -> str | None:
    if nullable and value is None:
        return None
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        _fail(path, "must be a lowercase 64-character SHA-256 digest")
    return value


def _date(value: Any, path: str, *, nullable: bool = False) -> str | None:
    if nullable and value is None:
        return None
    if type(value) is not str:
        _fail(path, "must be an ISO-8601 calendar date")
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        _fail(path, "must be an ISO-8601 calendar date")
    if parsed.isoformat() != value:
        _fail(path, "must use canonical YYYY-MM-DD form")
    return value


def _duration(value: Any, path: str) -> str:
    if type(value) is not str or _DURATION.fullmatch(value) is None:
        _fail(path, "must be a supported positive ISO-8601 duration")
    components = [int(number) for number in re.findall(r"[0-9]+", value)]
    if not components or not any(components):
        _fail(path, "duration must be greater than zero")
    return value


def _nullable_non_empty(value: Any, path: str) -> str | None:
    if value is None:
        return None
    return _non_empty(value, path)


def _relative_contract_path(value: Any, path: str) -> str:
    text = _non_empty(value, path)
    if "\\" in text:
        _fail(path, "must use a relative POSIX path")
    posix_path = PurePosixPath(text)
    windows_path = PureWindowsPath(text)
    if posix_path.is_absolute() or windows_path.is_absolute() or windows_path.drive:
        _fail(path, "absolute paths are forbidden")
    if text.startswith("~") or "://" in text:
        _fail(path, "must be a repository-relative path")
    if any(part in ("", ".", "..") for part in posix_path.parts):
        _fail(path, "path traversal and ambiguous path segments are forbidden")
    return text


def _host(value: Any, path: str) -> str:
    host = _non_empty(value, path)
    if host != host.lower() or _HOST.fullmatch(host) is None:
        _fail(path, "must be a lowercase DNS hostname")
    labels = host.split(".")
    if len(labels) < 2 or not any("a" <= char <= "z" for char in labels[-1]):
        _fail(path, "must be a dotted public-style DNS name with an alphabetic final label")
    legacy_numeric_label = re.compile(r"(?:[0-9]+|0x[0-9a-f]+)")
    if len(labels) <= 4 and all(legacy_numeric_label.fullmatch(label) for label in labels):
        _fail(path, "legacy numeric/hex address forms are forbidden")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        _fail(path, "IP-literal hosts are forbidden")
    if (
        host == "localhost"
        or host.endswith(".localhost")
        or host.endswith(".local")
        or host.endswith(".internal")
        or host.endswith(".home")
        or host.endswith(".lan")
    ):
        _fail(path, "local/private hostnames are forbidden")
    # Syntax checks cannot defeat DNS rebinding or a public name resolving to a
    # private address.  The later safe-fetch boundary must resolve every hop and
    # prove that the actual connected peer is public, without trusting DNS alone.
    return host


def _safe_https_url(value: Any, path: str) -> tuple[str, str]:
    url = _non_empty(value, path)
    if url != url.strip() or any(ord(char) < 0x20 for char in url):
        _fail(path, "URL contains whitespace or control characters")
    if "\\" in url:
        _fail(path, "URL backslashes are forbidden")
    if "?" in url or "#" in url:
        _fail(path, "URL query strings and fragments are forbidden")
    try:
        parsed = urlsplit(url)
    except ValueError as exc:
        _fail(path, f"invalid URL: {exc}")
    if parsed.scheme != "https" or not url.startswith("https://"):
        _fail(path, "only lowercase https URLs are permitted")
    if not parsed.netloc or parsed.hostname is None:
        _fail(path, "URL must include a hostname")
    if parsed.username is not None or parsed.password is not None or "@" in parsed.netloc:
        _fail(path, "URL userinfo/credentials are forbidden")
    try:
        port = parsed.port
    except ValueError as exc:
        _fail(path, f"invalid URL port: {exc}")
    if port is not None:
        _fail(path, "explicit URL ports are forbidden; omit the default HTTPS port")
    if parsed.netloc != parsed.hostname:
        _fail(path, "URL host must use canonical lowercase spelling")
    hostname = _host(parsed.hostname, f"{path}.hostname")
    if not parsed.path:
        _fail(path, "canonical URLs must include an explicit path; use '/' for a root URL")
    decoded_path = unquote(parsed.path)
    if "\\" in decoded_path or any(ord(char) < 0x20 for char in decoded_path):
        _fail(path, "URL path contains an unsafe encoded character")
    if any(segment in (".", "..") for segment in decoded_path.split("/")):
        _fail(path, "URL path traversal or dot segments are forbidden")
    return url, hostname


def _unique_scalar_array(
    value: Any,
    path: str,
    validator: Any,
    *,
    minimum: int = 0,
) -> list[Any]:
    items = _array(value, path, minimum=minimum)
    seen: dict[Any, int] = {}
    for index, item in enumerate(items):
        validator(item, f"{path}[{index}]")
        if item in seen:
            _fail(
                f"{path}[{index}]",
                f"duplicates item from index {seen[item]}",
            )
        seen[item] = index
    return items


def _unique_object_ids(
    objects: list[Any],
    path: str,
    id_key: str,
) -> dict[str, dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(objects):
        item = _object(raw, f"{path}[{index}]", None)
        identifier = _stable_id(item.get(id_key), f"{path}[{index}].{id_key}")
        assert identifier is not None
        if identifier in by_id:
            _fail(
                f"{path}[{index}].{id_key}",
                f"duplicate stable ID {identifier!r}",
            )
        by_id[identifier] = item
    return by_id


def _validate_authority_flags(authority: dict[str, Any], path: str) -> None:
    for key in _FORBIDDEN_AUTHORITY_FLAGS:
        _constant(authority.get(key), False, f"{path}.{key}")


def _validate_manifest_counts(
    manifest: dict[str, Any],
    expected: dict[str, int],
    path: str = "$.manifest",
) -> None:
    _constant(manifest.get("algorithm"), _SELF_DIGEST_ALGORITHM, f"{path}.algorithm")
    _sha256(manifest.get("contentSha256"), f"{path}.contentSha256")
    for key, actual in expected.items():
        declared = _integer(manifest.get(key), f"{path}.{key}", minimum=0)
        if declared != actual:
            _fail(f"{path}.{key}", f"declares {declared}, but payload contains {actual}")


def validate_coverage_universe(payload: dict[str, Any]) -> None:
    """Validate a ``coverage-universe-v1`` payload without side effects."""

    _walk_json(payload)
    root = _object(payload, "$", _UNIVERSE_KEYS)
    _constant(root["schemaVersion"], "1.0.0", "$.schemaVersion")
    _constant(root["policyVersion"], "coverage-universe-v1", "$.policyVersion")
    _constant(root["availability"], "coverage_definition_only", "$.availability")
    revision_id = _stable_id(root["universeRevisionId"], "$.universeRevisionId")
    supersedes = _stable_id(
        root["supersedesUniverseRevisionId"],
        "$.supersedesUniverseRevisionId",
        nullable=True,
    )
    if supersedes == revision_id:
        _fail("$.supersedesUniverseRevisionId", "a revision cannot supersede itself")

    authority = _object(
        root["authority"],
        "$.authority",
        {
            "classification",
            "approvalStatus",
            *_FORBIDDEN_AUTHORITY_FLAGS,
        },
    )
    _constant(authority["classification"], "coverage_definition_only", "$.authority.classification")
    approval = _enum(
        authority["approvalStatus"],
        {"draft_unapproved", "owner_approved"},
        "$.authority.approvalStatus",
    )
    _validate_authority_flags(authority, "$.authority")
    effective_on = _date(root["effectiveOn"], "$.effectiveOn", nullable=True)
    decision = _stable_id(root["decisionReference"], "$.decisionReference", nullable=True)
    if approval == "draft_unapproved":
        if effective_on is not None or decision is not None:
            _fail("$.authority.approvalStatus", "draft revisions cannot have effective/decision bindings")
    else:
        if effective_on is None or decision is None:
            _fail("$.authority.approvalStatus", "approved revisions require effectiveOn and decisionReference")

    cohorts = _array(root["cohorts"], "$.cohorts", minimum=1)
    benchmarks = _array(root["benchmarks"], "$.benchmarks", minimum=1)
    routes = _array(root["configuredSourceRoutes"], "$.configuredSourceRoutes")
    source_classes = _array(root["sourceClasses"], "$.sourceClasses", minimum=1)
    exclusions = _array(root["exclusions"], "$.exclusions")

    cohort_by_id = _unique_object_ids(cohorts, "$.cohorts", "cohortId")
    benchmark_by_id = _unique_object_ids(benchmarks, "$.benchmarks", "benchmarkId")
    route_by_id = _unique_object_ids(routes, "$.configuredSourceRoutes", "sourceRouteId")
    class_by_id = _unique_object_ids(source_classes, "$.sourceClasses", "sourceClassId")
    exclusion_by_id = _unique_object_ids(exclusions, "$.exclusions", "exclusionId")

    for index, item in enumerate(cohorts):
        path = f"$.cohorts[{index}]"
        cohort = _object(item, path, {"cohortId", "name", "purpose", "memberBenchmarkIds"})
        _non_empty(cohort["name"], f"{path}.name")
        _non_empty(cohort["purpose"], f"{path}.purpose")
        members = _unique_scalar_array(
            cohort["memberBenchmarkIds"],
            f"{path}.memberBenchmarkIds",
            _stable_id,
            minimum=1,
        )
        for member_id in members:
            if member_id not in benchmark_by_id:
                _fail(f"{path}.memberBenchmarkIds", f"unknown benchmark {member_id!r}")

    for index, item in enumerate(benchmarks):
        path = f"$.benchmarks[{index}]"
        benchmark = _object(item, path, {"benchmarkId", "coverageStatus", "reasonCode", "cohortIds"})
        status = _enum(benchmark["coverageStatus"], {"configured", "omitted"}, f"{path}.coverageStatus")
        _reason_code(benchmark["reasonCode"], f"{path}.reasonCode")
        cohort_ids = _unique_scalar_array(
            benchmark["cohortIds"], f"{path}.cohortIds", _stable_id, minimum=1
        )
        benchmark_id = benchmark["benchmarkId"]
        for cohort_id in cohort_ids:
            cohort = cohort_by_id.get(cohort_id)
            if cohort is None:
                _fail(f"{path}.cohortIds", f"unknown cohort {cohort_id!r}")
            if benchmark_id not in cohort["memberBenchmarkIds"]:
                _fail(f"{path}.cohortIds", f"membership in {cohort_id!r} is not bidirectional")
        if status == "omitted" and not benchmark["reasonCode"]:
            _fail(f"{path}.reasonCode", "omitted benchmarks require a reason")

    for cohort_id, cohort in cohort_by_id.items():
        for benchmark_id in cohort["memberBenchmarkIds"]:
            benchmark = benchmark_by_id[benchmark_id]
            if cohort_id not in benchmark["cohortIds"]:
                _fail(
                    f"$.cohorts[{cohort_id!r}].memberBenchmarkIds",
                    f"membership for {benchmark_id!r} is not bidirectional",
                )

    for index, item in enumerate(routes):
        path = f"$.configuredSourceRoutes[{index}]"
        route = _object(
            item,
            path,
            {"sourceRouteId", "benchmarkId", "registryStatus", "coverageStatus", "reasonCode"},
        )
        benchmark_id = _stable_id(route["benchmarkId"], f"{path}.benchmarkId")
        _non_empty(route["registryStatus"], f"{path}.registryStatus")
        route_status = _enum(route["coverageStatus"], {"configured", "omitted"}, f"{path}.coverageStatus")
        _reason_code(route["reasonCode"], f"{path}.reasonCode")
        if benchmark_id not in benchmark_by_id:
            _fail(f"{path}.benchmarkId", f"unknown benchmark {benchmark_id!r}")
        if route_status == "configured" and benchmark_by_id[benchmark_id]["coverageStatus"] != "configured":
            _fail(f"{path}.coverageStatus", "configured route cannot target an omitted benchmark")

    # A configured benchmark is a watch-root commitment, not merely a named
    # denominator member.  It must have at least one route record; that route
    # may be configured or explicitly omitted with its required reason code.
    routed_benchmark_ids = {route["benchmarkId"] for route in route_by_id.values()}
    for benchmark_id, benchmark in benchmark_by_id.items():
        if benchmark["coverageStatus"] == "configured" and benchmark_id not in routed_benchmark_ids:
            _fail(
                "$.configuredSourceRoutes",
                f"configured benchmark {benchmark_id!r} requires a configured or reasoned-omitted route",
            )

    priorities: list[int] = []
    for index, item in enumerate(source_classes):
        path = f"$.sourceClasses[{index}]"
        source_class = _object(
            item,
            path,
            {
                "sourceClassId",
                "priority",
                "methodFamily",
                "candidateUse",
                "discoveryOnly",
                "captureRequiresSeparateCertification",
                "publicationRequiresSeparateDecision",
            },
        )
        priorities.append(_integer(source_class["priority"], f"{path}.priority", minimum=1))
        _non_empty(source_class["methodFamily"], f"{path}.methodFamily")
        _non_empty(source_class["candidateUse"], f"{path}.candidateUse")
        _boolean(source_class["discoveryOnly"], f"{path}.discoveryOnly")
        _constant(
            source_class["captureRequiresSeparateCertification"],
            True,
            f"{path}.captureRequiresSeparateCertification",
        )
        _constant(
            source_class["publicationRequiresSeparateDecision"],
            True,
            f"{path}.publicationRequiresSeparateDecision",
        )
    expected_priorities = list(range(1, len(source_classes) + 1))
    if sorted(priorities) != expected_priorities:
        _fail("$.sourceClasses", f"priorities must be unique and contiguous: {expected_priorities}")

    scope = _object(root["scope"], "$.scope", {"name", "boundedStatement", "internetComplete", "registryInputs"})
    _non_empty(scope["name"], "$.scope.name")
    _non_empty(scope["boundedStatement"], "$.scope.boundedStatement")
    _constant(scope["internetComplete"], False, "$.scope.internetComplete")
    registry_inputs = _array(scope["registryInputs"], "$.scope.registryInputs", minimum=1)
    inputs_by_type: dict[str, dict[str, Any]] = {}
    registry_record_types = {"benchmark", "configured_source_route"}
    for index, raw in enumerate(registry_inputs):
        path = f"$.scope.registryInputs[{index}]"
        item = _object(
            raw,
            path,
            {"inputPath", "recordType", "selectionRule", "expectedUniqueCount", "semanticSha256"},
        )
        _relative_contract_path(item["inputPath"], f"{path}.inputPath")
        record_type = _enum(item["recordType"], registry_record_types, f"{path}.recordType")
        if record_type in inputs_by_type:
            _fail(f"{path}.recordType", f"duplicate registry input type {record_type!r}")
        inputs_by_type[record_type] = item
        _constant(item["selectionRule"], "all_unique_stable_ids", f"{path}.selectionRule")
        # This denominator describes the separately digest-pinned registry
        # input, not the bounded universe projection.  A difference is a
        # census reconciliation fact (for example, an out-of-universe row),
        # so it must remain visible rather than making the universe unreadable.
        _integer(item["expectedUniqueCount"], f"{path}.expectedUniqueCount", minimum=0)
        _sha256(item["semanticSha256"], f"{path}.semanticSha256")
    if set(inputs_by_type) != registry_record_types:
        _fail("$.scope.registryInputs", "must pin benchmark and configured-source-route registries")

    refresh = _object(
        root["refreshPolicy"],
        "$.refreshPolicy",
        {
            "discoveryPlanningCadence",
            "registryReconciliationCadence",
            "coverageOwnerReviewCadence",
            "stalenessThreshold",
            "termsReviewPolicy",
            "sourceRecheckAuthority",
        },
    )
    for key in (
        "discoveryPlanningCadence",
        "registryReconciliationCadence",
        "coverageOwnerReviewCadence",
        "stalenessThreshold",
    ):
        _duration(refresh[key], f"$.refreshPolicy.{key}")
    _non_empty(refresh["termsReviewPolicy"], "$.refreshPolicy.termsReviewPolicy")
    _constant(
        refresh["sourceRecheckAuthority"],
        "separate_certified_source_contract_only",
        "$.refreshPolicy.sourceRecheckAuthority",
    )

    for index, item in enumerate(exclusions):
        path = f"$.exclusions[{index}]"
        exclusion = _object(
            item,
            path,
            {
                "exclusionId",
                "excludedClass",
                "reasonCode",
                "rationale",
                "reconsiderationPolicy",
                "ownerRole",
                "reviewDueOn",
            },
        )
        _stable_id(exclusion["excludedClass"], f"{path}.excludedClass")
        _reason_code(exclusion["reasonCode"], f"{path}.reasonCode")
        _non_empty(exclusion["rationale"], f"{path}.rationale")
        _non_empty(exclusion["reconsiderationPolicy"], f"{path}.reconsiderationPolicy")
        _stable_id(exclusion["ownerRole"], f"{path}.ownerRole")
        _date(exclusion["reviewDueOn"], f"{path}.reviewDueOn")

    wording = _object(
        root["publicWording"],
        "$.publicWording",
        {"coverageLabel", "scopeStatement", "requiredDisclaimer", "forbiddenClaims"},
    )
    for key in ("coverageLabel", "scopeStatement", "requiredDisclaimer"):
        _non_empty(wording[key], f"$.publicWording.{key}")
    _unique_scalar_array(
        wording["forbiddenClaims"],
        "$.publicWording.forbiddenClaims",
        _non_empty,
        minimum=1,
    )

    manifest = _object(
        root["manifest"],
        "$.manifest",
        {
            "algorithm",
            "contentSha256",
            "benchmarkCount",
            "configuredSourceRouteCount",
            "sourceClassCount",
            "exclusionCount",
        },
    )
    _validate_manifest_counts(
        manifest,
        {
            "benchmarkCount": len(benchmark_by_id),
            "configuredSourceRouteCount": len(route_by_id),
            "sourceClassCount": len(class_by_id),
            "exclusionCount": len(exclusion_by_id),
        },
    )
    verify_contract_self_digest(root)


def validate_discovery_target(payload: dict[str, Any]) -> None:
    """Validate a bounded candidate-reconnaissance target contract."""

    _walk_json(payload)
    root = _object(payload, "$", _TARGET_KEYS)
    _constant(root["schemaVersion"], "1.0.0", "$.schemaVersion")
    _constant(root["policyVersion"], "discovery-target-v1", "$.policyVersion")
    _constant(root["availability"], "candidate_only", "$.availability")
    revision_id = _stable_id(root["targetRevisionId"], "$.targetRevisionId")
    supersedes = _stable_id(
        root["supersedesTargetRevisionId"], "$.supersedesTargetRevisionId", nullable=True
    )
    if supersedes == revision_id:
        _fail("$.supersedesTargetRevisionId", "a revision cannot supersede itself")
    _stable_id(root["targetId"], "$.targetId")
    status = _enum(
        root["configurationStatus"],
        {"draft", "configured", "paused", "blocked_terms", "blocked_permission", "retired"},
        "$.configurationStatus",
    )
    _reason_code(root["reasonCode"], "$.reasonCode")
    decision = _stable_id(root["decisionReference"], "$.decisionReference", nullable=True)

    authority = _object(
        root["authority"],
        "$.authority",
        {
            "classification",
            "approvalStatus",
            "permitsCandidateReconnaissance",
            *_FORBIDDEN_AUTHORITY_FLAGS,
        },
    )
    _constant(
        authority["classification"],
        "candidate_reconnaissance_only",
        "$.authority.classification",
    )
    approval = _enum(
        authority["approvalStatus"],
        {"draft_unapproved", "reconnaissance_approved"},
        "$.authority.approvalStatus",
    )
    permits = _boolean(
        authority["permitsCandidateReconnaissance"],
        "$.authority.permitsCandidateReconnaissance",
    )
    _validate_authority_flags(authority, "$.authority")
    if approval == "draft_unapproved" and decision is not None:
        _fail("$.decisionReference", "draft authority cannot bind an approval decision")
    if approval == "reconnaissance_approved" and decision is None:
        _fail("$.decisionReference", "approved authority requires a decision reference")
    if status == "draft" and approval != "draft_unapproved":
        _fail("$.authority.approvalStatus", "draft targets cannot claim reconnaissance approval")
    if status == "configured":
        if approval != "reconnaissance_approved" or decision is None or not permits:
            _fail(
                "$.configurationStatus",
                "configured targets require an approval decision and scoped reconnaissance permission",
            )
    elif permits:
        _fail(
            "$.authority.permitsCandidateReconnaissance",
            "only configured targets may permit candidate reconnaissance",
        )

    owner = _object(root["owner"], "$.owner", {"ownerId", "displayName", "officialRootUrl"})
    _stable_id(owner["ownerId"], "$.owner.ownerId")
    _non_empty(owner["displayName"], "$.owner.displayName")
    _safe_https_url(owner["officialRootUrl"], "$.owner.officialRootUrl")

    connector = _object(root["connector"], "$.connector", {"connectorId", "version", "observationClass"})
    _stable_id(connector["connectorId"], "$.connector.connectorId")
    _non_empty(connector["version"], "$.connector.version")
    _enum(
        connector["observationClass"],
        {
            "official_api_metadata",
            "official_repository_metadata",
            "official_dataset_metadata",
            "official_manifest_metadata",
            "official_structured_page_metadata",
            "manual_official_root",
        },
        "$.connector.observationClass",
    )

    url_policy = _object(
        root["urlPolicy"],
        "$.urlPolicy",
        {
            "requestMethod",
            "allowedHosts",
            "allowedFinalUrlPatterns",
            "discoveryOnlyPatterns",
            "allowCredentials",
            "allowFragments",
        },
    )
    _constant(url_policy["requestMethod"], "GET", "$.urlPolicy.requestMethod")
    allowed_hosts = _unique_scalar_array(
        url_policy["allowedHosts"], "$.urlPolicy.allowedHosts", _host, minimum=1
    )
    patterns = _unique_scalar_array(
        url_policy["allowedFinalUrlPatterns"],
        "$.urlPolicy.allowedFinalUrlPatterns",
        lambda value, path: _safe_https_url(value, path),
        minimum=1,
    )
    _constant(url_policy["discoveryOnlyPatterns"], True, "$.urlPolicy.discoveryOnlyPatterns")
    _constant(url_policy["allowCredentials"], False, "$.urlPolicy.allowCredentials")
    _constant(url_policy["allowFragments"], False, "$.urlPolicy.allowFragments")
    host_set = set(allowed_hosts)
    _, origin_host = _safe_https_url(root["officialOrigin"], "$.officialOrigin")
    if origin_host not in host_set:
        _fail("$.officialOrigin", f"hostname {origin_host!r} is absent from allowedHosts")
    for index, pattern in enumerate(patterns):
        _, pattern_host = _safe_https_url(pattern, f"$.urlPolicy.allowedFinalUrlPatterns[{index}]")
        if pattern_host not in host_set:
            _fail(
                f"$.urlPolicy.allowedFinalUrlPatterns[{index}]",
                f"hostname {pattern_host!r} is absent from allowedHosts",
            )

    due = _object(
        root["duePolicy"],
        "$.duePolicy",
        {"cadence", "maxJitterSeconds", "catchUpMissedSlots", "maxCatchUpSlots"},
    )
    _duration(due["cadence"], "$.duePolicy.cadence")
    _integer(due["maxJitterSeconds"], "$.duePolicy.maxJitterSeconds", minimum=0, maximum=3600)
    _boolean(due["catchUpMissedSlots"], "$.duePolicy.catchUpMissedSlots")
    _integer(due["maxCatchUpSlots"], "$.duePolicy.maxCatchUpSlots", minimum=0, maximum=4)

    terms = _object(
        root["termsReview"],
        "$.termsReview",
        {"status", "evidenceUrl", "reviewCadence", "reasonCode"},
    )
    terms_status = _enum(
        terms["status"],
        {"reviewed_for_reconnaissance", "review_required", "blocked_terms", "blocked_permission"},
        "$.termsReview.status",
    )
    if terms["evidenceUrl"] is not None:
        _safe_https_url(terms["evidenceUrl"], "$.termsReview.evidenceUrl")
    _duration(terms["reviewCadence"], "$.termsReview.reviewCadence")
    _reason_code(terms["reasonCode"], "$.termsReview.reasonCode")
    if status == "configured" and (
        terms_status != "reviewed_for_reconnaissance" or terms["evidenceUrl"] is None
    ):
        _fail(
            "$.termsReview",
            "configured reconnaissance requires reviewed terms and an evidence URL",
        )
    if status == "blocked_terms" and terms_status != "blocked_terms":
        _fail("$.termsReview.status", "blocked_terms target must have blocked_terms review status")
    if status == "blocked_permission" and terms_status != "blocked_permission":
        _fail(
            "$.termsReview.status",
            "blocked_permission target must have blocked_permission review status",
        )

    correction = _object(
        root["correctionRoute"],
        "$.correctionRoute",
        {"routeType", "locator", "reasonCode"},
    )
    route_type = _enum(
        correction["routeType"],
        {"official_contact_url", "official_repository_issue", "manual_governance"},
        "$.correctionRoute.routeType",
    )
    if correction["locator"] is not None:
        _safe_https_url(correction["locator"], "$.correctionRoute.locator")
    if route_type != "manual_governance" and correction["locator"] is None:
        _fail("$.correctionRoute.locator", "official correction routes require a locator")
    _reason_code(correction["reasonCode"], "$.correctionRoute.reasonCode")

    budgets = _object(
        root["budgets"],
        "$.budgets",
        {
            "maxRequestsPerRun",
            "maxBytesPerResponse",
            "maxRedirects",
            "timeoutSeconds",
            "maxConcurrency",
        },
    )
    max_requests = _integer(
        budgets["maxRequestsPerRun"], "$.budgets.maxRequestsPerRun", minimum=1, maximum=1000
    )
    _integer(budgets["maxBytesPerResponse"], "$.budgets.maxBytesPerResponse", minimum=1)
    _integer(budgets["maxRedirects"], "$.budgets.maxRedirects", minimum=0, maximum=10)
    _integer(budgets["timeoutSeconds"], "$.budgets.timeoutSeconds", minimum=1, maximum=120)
    concurrency = _integer(
        budgets["maxConcurrency"], "$.budgets.maxConcurrency", minimum=1, maximum=10
    )
    if concurrency > max_requests:
        _fail("$.budgets.maxConcurrency", "cannot exceed maxRequestsPerRun")

    affected = _unique_scalar_array(
        root["affectedBenchmarkIds"],
        "$.affectedBenchmarkIds",
        _stable_id,
        minimum=1,
    )
    manifest = _object(
        root["manifest"],
        "$.manifest",
        {
            "algorithm",
            "contentSha256",
            "affectedBenchmarkCount",
            "allowedHostCount",
            "allowedFinalPatternCount",
        },
    )
    _validate_manifest_counts(
        manifest,
        {
            "affectedBenchmarkCount": len(affected),
            "allowedHostCount": len(allowed_hosts),
            "allowedFinalPatternCount": len(patterns),
        },
    )
    verify_contract_self_digest(root)


def discovery_candidate_fingerprint(payload: dict[str, Any]) -> str:
    """Compute a candidate's stable identity fingerprint.

    The fingerprint intentionally excludes lifecycle, evidence, observations,
    and authority fields.  Its two set-like arrays are sorted lexicographically
    before canonical serialization, exactly as specified by the v1 contract.
    """

    if type(payload) is not dict:
        _fail("$", "candidate must be an object")
    candidate_type = payload.get("candidateType")
    target_revision_id = payload.get("targetRevisionId")
    identity = payload.get("candidateIdentity")
    official_urls = payload.get("officialUrls")
    affected_ids = payload.get("affectedBenchmarkIds")
    if type(candidate_type) is not str:
        _fail("$.candidateType", "is required for fingerprinting")
    if type(target_revision_id) is not str:
        _fail("$.targetRevisionId", "is required for fingerprinting")
    if type(identity) is not dict:
        _fail("$.candidateIdentity", "is required for fingerprinting")
    if type(official_urls) is not list or not all(type(item) is str for item in official_urls):
        _fail("$.officialUrls", "must be an array of strings for fingerprinting")
    if type(affected_ids) is not list or not all(type(item) is str for item in affected_ids):
        _fail("$.affectedBenchmarkIds", "must be an array of strings for fingerprinting")
    material = {
        "candidateType": candidate_type,
        "targetRevisionId": target_revision_id,
        "candidateIdentity": identity,
        "officialUrls": sorted(official_urls),
        "affectedBenchmarkIds": sorted(affected_ids),
    }
    return hashlib.sha256(canonical_json(material).encode("utf-8")).hexdigest()


def validate_discovery_candidate(payload: dict[str, Any]) -> None:
    """Validate a quarantined ``discovery-candidate-v1`` proposal."""

    _walk_json(payload)
    root = _object(payload, "$", _CANDIDATE_KEYS)
    _constant(root["schemaVersion"], "1.0.0", "$.schemaVersion")
    _constant(root["policyVersion"], "discovery-candidate-v1", "$.policyVersion")
    _constant(root["availability"], "candidate_only", "$.availability")
    _stable_id(root["candidateId"], "$.candidateId")
    declared_fingerprint = _sha256(
        root["candidateFingerprintSha256"], "$.candidateFingerprintSha256"
    )
    candidate_type = _enum(
        root["candidateType"],
        {"benchmark", "source", "model_metadata", "evaluation_subject"},
        "$.candidateType",
    )
    state = _enum(
        root["state"],
        {
            "observed",
            "auto_screened",
            "needs_governance",
            "contract_draft",
            "fixture_verified",
            "certification_pending",
            "approved_as_source_revision",
            "rejected_nonofficial",
            "rejected_unstructured",
            "blocked_terms",
            "blocked_permission",
            "blocked_incomplete_artifact",
            "unsupported_format",
            "superseded",
            "retired",
        },
        "$.state",
    )
    state_decision = _stable_id(
        root["stateDecisionReference"], "$.stateDecisionReference", nullable=True
    )
    approval_reference = _stable_id(
        root["approvedSourceRevisionReference"],
        "$.approvedSourceRevisionReference",
        nullable=True,
    )
    _reason_code(root["reasonCode"], "$.reasonCode")
    _stable_id(root["targetRevisionId"], "$.targetRevisionId")
    if state == "observed":
        if state_decision is not None or approval_reference is not None:
            _fail("$.state", "observed candidates cannot carry lifecycle decision references")
    else:
        if state_decision is None:
            _fail("$.stateDecisionReference", "every post-observation state requires a decision")
        if state == "approved_as_source_revision":
            if approval_reference is None:
                _fail(
                    "$.approvedSourceRevisionReference",
                    "approved state requires an approved source revision reference",
                )
            if candidate_type != "source":
                _fail("$.candidateType", "only source candidates can become source revisions")
        elif approval_reference is not None:
            _fail(
                "$.approvedSourceRevisionReference",
                "approval references are forbidden outside approved_as_source_revision",
            )

    authority = _object(
        root["authority"],
        "$.authority",
        {"classification", *_FORBIDDEN_AUTHORITY_FLAGS},
    )
    _constant(
        authority["classification"],
        "quarantined_proposal_only",
        "$.authority.classification",
    )
    _validate_authority_flags(authority, "$.authority")

    owner = _object(root["owner"], "$.owner", {"ownerId", "displayName", "officialRootUrls"})
    _stable_id(owner["ownerId"], "$.owner.ownerId", nullable=True)
    _non_empty(owner["displayName"], "$.owner.displayName")
    _unique_scalar_array(
        owner["officialRootUrls"],
        "$.owner.officialRootUrls",
        lambda value, path: _safe_https_url(value, path),
    )

    identity = _object(root["candidateIdentity"], "$.candidateIdentity", None)
    identity_type = identity.get("identityType")
    if identity_type != candidate_type:
        _fail("$.candidateIdentity.identityType", "must match candidateType")
    if candidate_type == "benchmark":
        identity = _object(
            identity,
            "$.candidateIdentity",
            {"identityType", "proposedBenchmarkId", "editionHint"},
        )
        _stable_id(identity["proposedBenchmarkId"], "$.candidateIdentity.proposedBenchmarkId")
        _nullable_non_empty(identity["editionHint"], "$.candidateIdentity.editionHint")
    elif candidate_type == "source":
        identity = _object(
            identity,
            "$.candidateIdentity",
            {"identityType", "proposedSourceId", "benchmarkId", "resultLocator"},
        )
        _stable_id(identity["proposedSourceId"], "$.candidateIdentity.proposedSourceId")
        _stable_id(identity["benchmarkId"], "$.candidateIdentity.benchmarkId")
        _safe_https_url(identity["resultLocator"], "$.candidateIdentity.resultLocator")
    elif candidate_type == "model_metadata":
        identity = _object(
            identity,
            "$.candidateIdentity",
            {"identityType", "modelRaw", "providerRaw"},
        )
        _non_empty(identity["modelRaw"], "$.candidateIdentity.modelRaw")
        _nullable_non_empty(identity["providerRaw"], "$.candidateIdentity.providerRaw")
    else:
        identity = _object(
            identity,
            "$.candidateIdentity",
            {"identityType", "subjectRaw", "subjectKindHint"},
        )
        _non_empty(identity["subjectRaw"], "$.candidateIdentity.subjectRaw")
        _enum(
            identity["subjectKindHint"],
            {"single_model", "endpoint", "agent_model_system", "ensemble", "submission", "unknown"},
            "$.candidateIdentity.subjectKindHint",
        )

    official_urls = _unique_scalar_array(
        root["officialUrls"],
        "$.officialUrls",
        lambda value, path: _safe_https_url(value, path),
        minimum=0,
    )
    affected_ids = _unique_scalar_array(
        root["affectedBenchmarkIds"],
        "$.affectedBenchmarkIds",
        _stable_id,
        minimum=0,
    )
    if candidate_type in {"benchmark", "source", "model_metadata"} and not official_urls:
        _fail("$.officialUrls", f"{candidate_type} candidates require at least one official URL")
    if candidate_type in {"source", "evaluation_subject"} and not affected_ids:
        _fail("$.affectedBenchmarkIds", f"{candidate_type} candidates require a benchmark")
    if candidate_type == "source" and identity["benchmarkId"] not in affected_ids:
        _fail(
            "$.candidateIdentity.benchmarkId",
            "source identity benchmark must appear in affectedBenchmarkIds",
        )

    artifact = _object(
        root["artifactHint"],
        "$.artifactHint",
        {"format", "structured", "revisionKind", "revisionLocator", "completenessHint", "parserHint"},
    )
    _enum(
        artifact["format"],
        {"api", "json", "csv", "parquet", "yaml", "html", "embedded_json", "manifest", "unknown"},
        "$.artifactHint.format",
    )
    _boolean(artifact["structured"], "$.artifactHint.structured")
    _enum(
        artifact["revisionKind"],
        {"immutable_commit", "release_tag", "content_digest", "mutable_endpoint", "unknown"},
        "$.artifactHint.revisionKind",
    )
    _nullable_non_empty(artifact["revisionLocator"], "$.artifactHint.revisionLocator")
    _enum(
        artifact["completenessHint"],
        {"complete", "incomplete", "preview_only", "unknown"},
        "$.artifactHint.completenessHint",
    )
    _stable_id(artifact["parserHint"], "$.artifactHint.parserHint", nullable=True)

    terms = _object(root["termsHint"], "$.termsHint", {"status", "evidenceUrl", "reasonCode"})
    _enum(
        terms["status"],
        {"unknown", "review_required", "reviewed_for_reconnaissance", "blocked_terms", "blocked_permission"},
        "$.termsHint.status",
    )
    if terms["evidenceUrl"] is not None:
        _safe_https_url(terms["evidenceUrl"], "$.termsHint.evidenceUrl")
    _reason_code(terms["reasonCode"], "$.termsHint.reasonCode")

    evidence = _array(root["evidenceReferences"], "$.evidenceReferences", minimum=1)
    _unique_object_ids(evidence, "$.evidenceReferences", "evidenceId")
    for index, raw in enumerate(evidence):
        path = f"$.evidenceReferences[{index}]"
        item = _object(
            raw,
            path,
            {"evidenceId", "evidenceType", "locator", "contentSha256", "observationRevision"},
        )
        _enum(
            item["evidenceType"],
            {"discovery_observation", "official_metadata", "terms_review", "manual_official_lead"},
            f"{path}.evidenceType",
        )
        _safe_https_url(item["locator"], f"{path}.locator")
        _sha256(item["contentSha256"], f"{path}.contentSha256", nullable=True)
        _nullable_non_empty(item["observationRevision"], f"{path}.observationRevision")

    manifest = _object(
        root["manifest"],
        "$.manifest",
        {
            "algorithm",
            "contentSha256",
            "officialUrlCount",
            "affectedBenchmarkCount",
            "evidenceReferenceCount",
        },
    )
    _validate_manifest_counts(
        manifest,
        {
            "officialUrlCount": len(official_urls),
            "affectedBenchmarkCount": len(affected_ids),
            "evidenceReferenceCount": len(evidence),
        },
    )
    actual_fingerprint = discovery_candidate_fingerprint(root)
    if declared_fingerprint != actual_fingerprint:
        _fail(
            "$.candidateFingerprintSha256",
            f"fingerprint mismatch (declared {declared_fingerprint}, computed {actual_fingerprint})",
        )
    verify_contract_self_digest(root)


__all__ = [
    "CoverageContractError",
    "canonical_json",
    "contract_self_digest",
    "discovery_candidate_fingerprint",
    "validate_coverage_universe",
    "validate_discovery_candidate",
    "validate_discovery_target",
    "verify_contract_self_digest",
]
