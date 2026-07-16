"""Pure semantic validation for benchmark and evaluated-system identity contracts.

The JSON Schemas in ``docs/contracts`` own the portable wire shape.  These
standard-library-only validators enforce the graph, identity, comparability,
linearity, fingerprint, and containment rules that are deliberately stricter
than JSON Schema alone.  They perform no file, clock, network, database, or
environment access and never mutate their inputs.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime
import hashlib
import ipaddress
import json
import math
import re
from typing import Any, Callable, Iterable
from urllib.parse import unquote, urlsplit


class DomainIdentityContractError(ValueError):
    """Raised when a domain identity contract is inadmissible."""


_STABLE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_REASON_CODE = re.compile(r"^[A-Z][A-Z0-9_]{2,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_UTC_SECOND = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_HOST = re.compile(
    r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?$"
)
_ALGORITHM = "sha256-canonical-json-v1"
_MUTABLE_NAMES = {
    "capturedat",
    "checkedat",
    "createdat",
    "effectiveat",
    "fetchedat",
    "generatedat",
    "lastchecked",
    "lastmodified",
    "observedat",
    "refreshedat",
    "timestamp",
    "timestamps",
    "updatedat",
}
_DISPLAY_DIMENSIONS = [
    "modelId",
    "benchmarkId",
    "metric",
    "split",
    "setting",
    "evaluationVersion",
]


def _fail(path: str, message: str) -> None:
    raise DomainIdentityContractError(f"{path}: {message}")


def _walk_json(value: Any, path: str = "$") -> None:
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
            normalized = re.sub(r"[^a-z0-9]", "", key.lower())
            if (
                normalized in _MUTABLE_NAMES
                or "mtime" in normalized
                or normalized.endswith("timestamp")
            ):
                _fail(f"{path}.{key}", "mutable timestamps/mtimes are forbidden")
            _walk_json(item, f"{path}.{key}")
        return
    _fail(path, f"unsupported canonical JSON type {type(value).__name__}")


def canonical_json(value: Any) -> str:
    """Return compact canonical JSON with sorted keys and preserved array order."""

    _walk_json(value)
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def contract_self_digest(payload: dict[str, Any]) -> str:
    """Hash a contract after replacing only ``manifest.contentSha256`` with null."""

    if type(payload) is not dict:
        _fail("$", "contract must be an object")
    material = deepcopy(payload)
    manifest = material.get("manifest")
    if type(manifest) is not dict or "contentSha256" not in manifest:
        _fail("$.manifest.contentSha256", "is required for self-digesting")
    manifest["contentSha256"] = None
    return hashlib.sha256(canonical_json(material).encode("utf-8")).hexdigest()


def verify_contract_self_digest(payload: dict[str, Any]) -> None:
    manifest = _object(payload.get("manifest"), "$.manifest", None)
    _constant(manifest.get("algorithm"), _ALGORITHM, "$.manifest.algorithm")
    declared = _sha256(manifest.get("contentSha256"), "$.manifest.contentSha256")
    actual = contract_self_digest(payload)
    if declared != actual:
        _fail(
            "$.manifest.contentSha256",
            f"self-digest mismatch (declared {declared}, computed {actual})",
        )


def _object(value: Any, path: str, keys: set[str] | None) -> dict[str, Any]:
    if type(value) is not dict:
        _fail(path, "must be an object")
    if keys is not None and set(value) != keys:
        missing = sorted(keys - set(value))
        extra = sorted(set(value) - keys)
        parts = []
        if missing:
            parts.append(f"missing keys {missing}")
        if extra:
            parts.append(f"unexpected keys {extra}")
        _fail(path, "; ".join(parts))
    return value


def _array(value: Any, path: str, minimum: int = 0) -> list[Any]:
    if type(value) is not list:
        _fail(path, "must be an array")
    if len(value) < minimum:
        _fail(path, f"must contain at least {minimum} item(s)")
    return value


def _constant(value: Any, expected: Any, path: str) -> None:
    if type(value) is not type(expected) or value != expected:
        _fail(path, f"must equal {expected!r}")


def _enum(value: Any, choices: set[str], path: str) -> str:
    if type(value) is not str or value not in choices:
        _fail(path, f"must be one of {sorted(choices)}")
    return value


def _boolean(value: Any, path: str) -> bool:
    if type(value) is not bool:
        _fail(path, "must be a boolean")
    return value


def _integer(value: Any, path: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        _fail(path, f"must be an integer >= {minimum}")
    return value


def _non_empty(value: Any, path: str) -> str:
    if type(value) is not str or not value.strip():
        _fail(path, "must be a non-empty string")
    return value


def _nullable_string(value: Any, path: str) -> str | None:
    if value is None:
        return None
    return _non_empty(value, path)


def _stable_id(value: Any, path: str, nullable: bool = False) -> str | None:
    if nullable and value is None:
        return None
    if type(value) is not str or _STABLE_ID.fullmatch(value) is None:
        _fail(path, "must be a stable lowercase identifier")
    return value


def _reason(value: Any, path: str, nullable: bool = False) -> str | None:
    if nullable and value is None:
        return None
    if type(value) is not str or _REASON_CODE.fullmatch(value) is None:
        _fail(path, "must be an explicit uppercase reason code")
    return value


def _sha256(value: Any, path: str, nullable: bool = False) -> str | None:
    if nullable and value is None:
        return None
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        _fail(path, "must be a lowercase 64-character SHA-256 digest")
    return value


def _date_only(value: Any, path: str, nullable: bool = False) -> date | None:
    if nullable and value is None:
        return None
    if type(value) is not str or _DATE_ONLY.fullmatch(value) is None:
        _fail(path, "must be an exact canonical ISO date (YYYY-MM-DD)")
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        _fail(path, "must be a valid canonical ISO date")
    if parsed.isoformat() != value:
        _fail(path, "must be an exact canonical ISO date (YYYY-MM-DD)")
    return parsed


def _utc_second(value: Any, path: str, nullable: bool = False) -> datetime | None:
    if nullable and value is None:
        return None
    if type(value) is not str or _UTC_SECOND.fullmatch(value) is None:
        _fail(path, "must be exact canonical UTC time YYYY-MM-DDTHH:MM:SSZ")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        _fail(path, "must be a valid canonical UTC time")
    if parsed.strftime("%Y-%m-%dT%H:%M:%SZ") != value:
        _fail(path, "must be exact canonical UTC time YYYY-MM-DDTHH:MM:SSZ")
    return parsed


def _unique_scalars(
    value: Any,
    path: str,
    validator: Callable[[Any, str], Any],
    minimum: int = 0,
) -> list[Any]:
    items = _array(value, path, minimum)
    seen: dict[Any, int] = {}
    for index, item in enumerate(items):
        validator(item, f"{path}[{index}]")
        if item in seen:
            _fail(f"{path}[{index}]", f"duplicates item at index {seen[item]}")
        seen[item] = index
    return items


def _unique_objects(
    value: Any,
    path: str,
    id_key: str,
    minimum: int = 0,
) -> tuple[list[Any], dict[str, dict[str, Any]]]:
    items = _array(value, path, minimum)
    by_id: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(items):
        item = _object(raw, f"{path}[{index}]", None)
        identifier = _stable_id(item.get(id_key), f"{path}[{index}].{id_key}")
        assert identifier is not None
        if identifier in by_id:
            _fail(f"{path}[{index}].{id_key}", f"duplicate stable ID {identifier!r}")
        by_id[identifier] = item
    return items, by_id


def _canonical_https_url(value: Any, path: str) -> str:
    url = _non_empty(value, path)
    if not url.startswith("https://") or "?" in url or "#" in url or "\\" in url:
        _fail(path, "must be a canonical HTTPS URL without query, fragment, or backslash")
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        _fail(path, f"invalid URL: {exc}")
    if parsed.scheme != "https" or parsed.hostname is None or not parsed.netloc:
        _fail(path, "must include a canonical HTTPS hostname")
    if parsed.username is not None or parsed.password is not None or port is not None:
        _fail(path, "URL credentials and explicit ports are forbidden")
    if parsed.netloc != parsed.hostname or _HOST.fullmatch(parsed.hostname) is None:
        _fail(path, "hostname must be a lowercase dotted public-style DNS name")
    try:
        ipaddress.ip_address(parsed.hostname)
    except ValueError:
        pass
    else:
        _fail(path, "IP-literal hosts are forbidden")
    if parsed.hostname.endswith((".local", ".localhost", ".internal", ".lan")):
        _fail(path, "local/private hostnames are forbidden")
    if not parsed.path:
        _fail(path, "canonical root URLs must include '/'")
    decoded = unquote(parsed.path)
    if any(part in (".", "..") for part in decoded.split("/")):
        _fail(path, "URL dot segments are forbidden")
    return url


def _validate_authority_false(authority: dict[str, Any], path: str, flags: Iterable[str]) -> None:
    for flag in flags:
        _constant(authority.get(flag), False, f"{path}.{flag}")


def raw_identity_label_sha256(model_raw: str) -> str:
    """Digest an exact raw evaluated-system label without normalization."""

    _non_empty(model_raw, "$.rawObservation.modelRaw")
    return hashlib.sha256(model_raw.encode("utf-8")).hexdigest()


_BENCHMARK_KEYS = {
    "schemaVersion", "policyVersion", "availability",
    "benchmarkDefinitionRevisionId", "benchmarkFamilyId", "benchmarkEditionId",
    "supersedesDefinitionRevisionId", "lifecycleStatus", "effectivePeriod",
    "decisionReference",
    "reasonCode", "authority", "manifest", "owner", "identity", "changeControl",
    "displayContract", "dimensions", "relationships", "sourceContractCompatibility",
    "claimRetention",
}


def benchmark_definition_fingerprint(payload: dict[str, Any]) -> str:
    """Hash benchmark-side display/comparability identity with set-like arrays sorted.

    ``effectivePeriod`` is deliberately excluded: changing when an otherwise
    identical definition is effective changes its self-digest and lifecycle
    state, but not the edition's score-cell identity.
    """

    if type(payload) is not dict:
        _fail("$", "benchmark definition must be an object")
    dimensions = _object(payload.get("dimensions"), "$.dimensions", None)
    display = _object(payload.get("displayContract"), "$.displayContract", None)
    compatibility = _object(
        payload.get("sourceContractCompatibility"),
        "$.sourceContractCompatibility",
        None,
    )

    def projected(key: str, fields: tuple[str, ...], id_key: str) -> list[dict[str, Any]]:
        items = _array(dimensions.get(key), f"$.dimensions.{key}")
        return sorted(
            ({field: item.get(field) for field in fields} for item in items),
            key=lambda item: canonical_json(item.get(id_key)),
        )

    relationships = _array(payload.get("relationships"), "$.relationships")
    material = {
        "benchmarkFamilyId": payload.get("benchmarkFamilyId"),
        "benchmarkEditionId": payload.get("benchmarkEditionId"),
        "displayContract": {
            "identityDimensions": display.get("identityDimensions"),
            "benchmarkId": display.get("benchmarkId"),
            "scoreUnitIsSeparateProvenance": display.get("scoreUnitIsSeparateProvenance"),
            "requiresExactCellIdentity": display.get("requiresExactCellIdentity"),
        },
        "metrics": projected("metrics", ("metricId", "direction", "unitId"), "metricId"),
        "splits": projected("splits", ("splitId",), "splitId"),
        "settings": projected("settings", ("settingId", "description"), "settingId"),
        "evaluationVersions": projected(
            "evaluationVersions",
            ("evaluationVersionId", "evaluatorName", "evaluatorVersionRaw", "harnessVersionRaw"),
            "evaluationVersionId",
        ),
        "units": projected(
            "units", ("unitId", "symbol", "scaleDescription"), "unitId"
        ),
        "comparabilityGroups": projected(
            "comparabilityGroups",
            ("comparabilityGroupId", "statement", "exactDimensionsRequired"),
            "comparabilityGroupId",
        ),
        "comparisonCells": projected(
            "comparisonCells",
            (
                "comparisonCellId", "metricId", "splitId", "settingId",
                "evaluationVersionId", "unitId", "comparabilityGroupId",
            ),
            "comparisonCellId",
        ),
        "relationships": sorted(
            (
                {
                    "relationshipId": item.get("relationshipId"),
                    "relationshipType": item.get("relationshipType"),
                    "relatedBenchmarkEditionId": item.get("relatedBenchmarkEditionId"),
                    "comparabilityEffect": item.get("comparabilityEffect"),
                }
                for item in relationships
            ),
            key=lambda item: canonical_json(item.get("relationshipId")),
        ),
        "sourceContractCompatibility": {
            "requiredPolicyVersion": compatibility.get("requiredPolicyVersion"),
            "requiresExactDefinitionRevisionId": compatibility.get(
                "requiresExactDefinitionRevisionId"
            ),
            "requiresExactMetricSplitSettingEvaluationVersionUnit": compatibility.get(
                "requiresExactMetricSplitSettingEvaluationVersionUnit"
            ),
            "allowedComparisonCellIds": sorted(
                compatibility.get("allowedComparisonCellIds", [])
            ),
            "allowsUnlistedDimensions": compatibility.get("allowsUnlistedDimensions"),
        },
    }
    return hashlib.sha256(canonical_json(material).encode("utf-8")).hexdigest()


def validate_benchmark_definition_revision(payload: dict[str, Any]) -> None:
    """Validate one immutable benchmark definition/edition revision."""

    _walk_json(payload)
    root = _object(payload, "$", _BENCHMARK_KEYS)
    _constant(root["schemaVersion"], "1.0.0", "$.schemaVersion")
    _constant(root["policyVersion"], "benchmark-definition-revision-v1", "$.policyVersion")
    _constant(root["availability"], "definition_only", "$.availability")
    revision_id = _stable_id(
        root["benchmarkDefinitionRevisionId"], "$.benchmarkDefinitionRevisionId"
    )
    family_id = _stable_id(root["benchmarkFamilyId"], "$.benchmarkFamilyId")
    edition_id = _stable_id(root["benchmarkEditionId"], "$.benchmarkEditionId")
    supersedes = _stable_id(
        root["supersedesDefinitionRevisionId"],
        "$.supersedesDefinitionRevisionId",
        nullable=True,
    )
    if revision_id == supersedes:
        _fail("$.supersedesDefinitionRevisionId", "a revision cannot supersede itself")
    lifecycle = _enum(
        root["lifecycleStatus"], {"draft", "approved", "superseded", "retired"},
        "$.lifecycleStatus",
    )
    decision = _stable_id(root["decisionReference"], "$.decisionReference", nullable=True)
    _reason(root["reasonCode"], "$.reasonCode")

    effective_period = _object(
        root["effectivePeriod"],
        "$.effectivePeriod",
        {"status", "effectiveFrom", "effectiveThrough"},
    )
    period_status = _enum(
        effective_period["status"],
        {"not_effective", "effective", "ended"},
        "$.effectivePeriod.status",
    )
    effective_from = _date_only(
        effective_period["effectiveFrom"],
        "$.effectivePeriod.effectiveFrom",
        nullable=True,
    )
    effective_through = _date_only(
        effective_period["effectiveThrough"],
        "$.effectivePeriod.effectiveThrough",
        nullable=True,
    )
    if lifecycle == "draft":
        if period_status != "not_effective" or effective_from is not None or effective_through is not None:
            _fail("$.effectivePeriod", "draft definition must be explicitly not effective with null bounds")
    elif lifecycle == "approved":
        if period_status != "effective" or effective_from is None or effective_through is not None:
            _fail("$.effectivePeriod", "approved definition requires a start date and no end date")
    elif (
        period_status != "ended"
        or effective_from is None
        or effective_through is None
    ):
        _fail("$.effectivePeriod", "superseded/retired definition requires bounded dates")
    elif effective_through < effective_from:
        _fail("$.effectivePeriod.effectiveThrough", "must be on or after effectiveFrom")

    authority = _object(
        root["authority"], "$.authority",
        {
            "classification", "approvalStatus", "certifiesSources", "authorizesCapture",
            "authorizesPublication", "frontendLoadable",
        },
    )
    _constant(
        authority["classification"], "benchmark_definition_only",
        "$.authority.classification",
    )
    approval = _enum(
        authority["approvalStatus"], {"draft_unapproved", "definition_approved"},
        "$.authority.approvalStatus",
    )
    _validate_authority_false(
        authority,
        "$.authority",
        ("certifiesSources", "authorizesCapture", "authorizesPublication", "frontendLoadable"),
    )
    if lifecycle == "draft":
        if decision is not None or approval != "draft_unapproved":
            _fail("$.lifecycleStatus", "draft definition cannot carry approval bindings")
    elif decision is None or approval != "definition_approved":
        _fail("$.lifecycleStatus", "non-draft definition requires an approval decision")

    owner = _object(root["owner"], "$.owner", {"ownerId", "displayName", "officialRootUrls"})
    _stable_id(owner["ownerId"], "$.owner.ownerId")
    _non_empty(owner["displayName"], "$.owner.displayName")
    _unique_scalars(owner["officialRootUrls"], "$.owner.officialRootUrls", _canonical_https_url, 1)

    identity = _object(
        root["identity"], "$.identity",
        {
            "canonicalBenchmarkId", "familyDisplayName", "editionDisplayName",
            "editionVersionRaw", "description",
        },
    )
    canonical_benchmark_id = _stable_id(
        identity["canonicalBenchmarkId"], "$.identity.canonicalBenchmarkId"
    )
    if canonical_benchmark_id != edition_id:
        _fail("$.identity.canonicalBenchmarkId", "must equal benchmarkEditionId")
    for key in ("familyDisplayName", "editionDisplayName", "description"):
        _non_empty(identity[key], f"$.identity.{key}")
    _nullable_string(identity["editionVersionRaw"], "$.identity.editionVersionRaw")

    change = _object(
        root["changeControl"], "$.changeControl",
        {
            "changeType", "identityDisposition", "priorBenchmarkEditionId",
            "compatibilityImpact", "reasonCode",
        },
    )
    change_type = _enum(
        change["changeType"],
        {
            "initial", "display_rename", "definition_correction", "new_edition",
            "metric_change", "split_change", "setting_change",
            "evaluation_version_change", "unit_change", "suite_relationship_change",
        },
        "$.changeControl.changeType",
    )
    disposition = _enum(
        change["identityDisposition"],
        {"preserve_edition_identity", "new_edition_identity"},
        "$.changeControl.identityDisposition",
    )
    prior_edition = _stable_id(
        change["priorBenchmarkEditionId"],
        "$.changeControl.priorBenchmarkEditionId",
        nullable=True,
    )
    impact = _enum(
        change["compatibilityImpact"],
        {"initial_identity", "display_only", "definition_metadata_only", "incompatible_new_identity"},
        "$.changeControl.compatibilityImpact",
    )
    _reason(change["reasonCode"], "$.changeControl.reasonCode")
    incompatible_changes = {
        "new_edition", "metric_change", "split_change", "setting_change",
        "evaluation_version_change", "unit_change", "suite_relationship_change",
    }
    if change_type == "initial":
        if supersedes is not None or prior_edition is not None:
            _fail("$.changeControl", "initial definition cannot supersede a prior revision/edition")
        if disposition != "new_edition_identity" or impact != "initial_identity":
            _fail("$.changeControl", "initial definition must establish a new edition identity")
    elif supersedes is None or prior_edition is None:
        _fail("$.changeControl", "non-initial changes require prior revision and edition references")
    elif change_type in {"display_rename", "definition_correction"}:
        expected_impact = "display_only" if change_type == "display_rename" else "definition_metadata_only"
        if disposition != "preserve_edition_identity" or impact != expected_impact:
            _fail("$.changeControl", "rename/correction must preserve compatible edition identity")
        if prior_edition != edition_id:
            _fail("$.changeControl.priorBenchmarkEditionId", "compatible change must retain edition ID")
    elif change_type in incompatible_changes:
        if disposition != "new_edition_identity" or impact != "incompatible_new_identity":
            _fail("$.changeControl", "dimension/edition changes require a new incompatible identity")
        if prior_edition == edition_id:
            _fail("$.benchmarkEditionId", "incompatible change cannot silently reuse prior edition ID")

    display = _object(
        root["displayContract"], "$.displayContract",
        {"identityDimensions", "benchmarkId", "scoreUnitIsSeparateProvenance", "requiresExactCellIdentity"},
    )
    _constant(display["identityDimensions"], _DISPLAY_DIMENSIONS, "$.displayContract.identityDimensions")
    if _stable_id(display["benchmarkId"], "$.displayContract.benchmarkId") != edition_id:
        _fail("$.displayContract.benchmarkId", "must equal benchmarkEditionId")
    _constant(display["scoreUnitIsSeparateProvenance"], True, "$.displayContract.scoreUnitIsSeparateProvenance")
    _constant(display["requiresExactCellIdentity"], True, "$.displayContract.requiresExactCellIdentity")

    dimensions = _object(
        root["dimensions"], "$.dimensions",
        {"metrics", "splits", "settings", "evaluationVersions", "units", "comparabilityGroups", "comparisonCells"},
    )
    metrics, metric_by_id = _unique_objects(dimensions["metrics"], "$.dimensions.metrics", "metricId", 1)
    splits, split_by_id = _unique_objects(dimensions["splits"], "$.dimensions.splits", "splitId", 1)
    settings, setting_by_id = _unique_objects(dimensions["settings"], "$.dimensions.settings", "settingId", 1)
    versions, version_by_id = _unique_objects(
        dimensions["evaluationVersions"], "$.dimensions.evaluationVersions",
        "evaluationVersionId", 1,
    )
    units, unit_by_id = _unique_objects(dimensions["units"], "$.dimensions.units", "unitId", 1)
    groups, group_by_id = _unique_objects(
        dimensions["comparabilityGroups"], "$.dimensions.comparabilityGroups",
        "comparabilityGroupId", 1,
    )
    cells, cell_by_id = _unique_objects(
        dimensions["comparisonCells"], "$.dimensions.comparisonCells",
        "comparisonCellId", 1,
    )

    for index, metric in enumerate(metrics):
        path = f"$.dimensions.metrics[{index}]"
        _object(metric, path, {"metricId", "displayName", "direction", "unitId"})
        _non_empty(metric["displayName"], f"{path}.displayName")
        _enum(metric["direction"], {"higher_is_better", "lower_is_better", "neither"}, f"{path}.direction")
        unit_id = _stable_id(metric["unitId"], f"{path}.unitId")
        if unit_id not in unit_by_id:
            _fail(f"{path}.unitId", f"unknown unit {unit_id!r}")
    for index, split in enumerate(splits):
        path = f"$.dimensions.splits[{index}]"
        _object(split, path, {"splitId", "displayName"})
        _non_empty(split["displayName"], f"{path}.displayName")
    for index, setting in enumerate(settings):
        path = f"$.dimensions.settings[{index}]"
        _object(setting, path, {"settingId", "displayName", "description"})
        _non_empty(setting["displayName"], f"{path}.displayName")
        _non_empty(setting["description"], f"{path}.description")
    for index, version in enumerate(versions):
        path = f"$.dimensions.evaluationVersions[{index}]"
        _object(version, path, {"evaluationVersionId", "evaluatorName", "evaluatorVersionRaw", "harnessVersionRaw"})
        _non_empty(version["evaluatorName"], f"{path}.evaluatorName")
        _non_empty(version["evaluatorVersionRaw"], f"{path}.evaluatorVersionRaw")
        _nullable_string(version["harnessVersionRaw"], f"{path}.harnessVersionRaw")
    for index, unit in enumerate(units):
        path = f"$.dimensions.units[{index}]"
        _object(unit, path, {"unitId", "displayName", "symbol", "scaleDescription"})
        for key in ("displayName", "symbol", "scaleDescription"):
            _non_empty(unit[key], f"{path}.{key}")
    for index, group in enumerate(groups):
        path = f"$.dimensions.comparabilityGroups[{index}]"
        _object(group, path, {"comparabilityGroupId", "statement", "exactDimensionsRequired"})
        _non_empty(group["statement"], f"{path}.statement")
        _constant(group["exactDimensionsRequired"], True, f"{path}.exactDimensionsRequired")

    cell_keys: set[tuple[Any, ...]] = set()
    for index, cell in enumerate(cells):
        path = f"$.dimensions.comparisonCells[{index}]"
        _object(
            cell, path,
            {
                "comparisonCellId", "metricId", "splitId", "settingId",
                "evaluationVersionId", "unitId", "comparabilityGroupId",
            },
        )
        references = (
            ("metricId", metric_by_id), ("splitId", split_by_id),
            ("settingId", setting_by_id), ("evaluationVersionId", version_by_id),
            ("unitId", unit_by_id), ("comparabilityGroupId", group_by_id),
        )
        for key, registry in references:
            referenced = _stable_id(cell[key], f"{path}.{key}")
            if referenced not in registry:
                _fail(f"{path}.{key}", f"unknown {key} {referenced!r}")
        if metric_by_id[cell["metricId"]]["unitId"] != cell["unitId"]:
            _fail(f"{path}.unitId", "cell unit must match the metric unit")
        identity_key = (
            cell["metricId"], cell["splitId"], cell["settingId"],
            cell["evaluationVersionId"],
        )
        if identity_key in cell_keys:
            _fail(path, "duplicate five-part benchmark-side display identity")
        cell_keys.add(identity_key)

    relationships, relationship_by_id = _unique_objects(
        root["relationships"], "$.relationships", "relationshipId"
    )
    relationship_keys: set[tuple[str, str]] = set()
    for index, relationship in enumerate(relationships):
        path = f"$.relationships[{index}]"
        _object(
            relationship, path,
            {"relationshipId", "relationshipType", "relatedBenchmarkEditionId", "comparabilityEffect", "reasonCode"},
        )
        relationship_type = _enum(
            relationship["relationshipType"],
            {"suite_contains", "subset_of", "task_of", "related_successor"},
            f"{path}.relationshipType",
        )
        related = _stable_id(
            relationship["relatedBenchmarkEditionId"], f"{path}.relatedBenchmarkEditionId"
        )
        if related == edition_id:
            _fail(f"{path}.relatedBenchmarkEditionId", "suite/subset relationship cannot reference itself")
        key = (relationship_type, related)
        if key in relationship_keys:
            _fail(path, "duplicate suite/subset relationship")
        relationship_keys.add(key)
        _constant(
            relationship["comparabilityEffect"],
            "distinct_identity_no_aggregate_substitution",
            f"{path}.comparabilityEffect",
        )
        _reason(relationship["reasonCode"], f"{path}.reasonCode")

    compatibility = _object(
        root["sourceContractCompatibility"], "$.sourceContractCompatibility",
        {
            "requiredPolicyVersion", "requiresExactDefinitionRevisionId",
            "requiresExactMetricSplitSettingEvaluationVersionUnit", "allowedComparisonCellIds",
            "allowsUnlistedDimensions",
        },
    )
    _constant(compatibility["requiredPolicyVersion"], "source-contract-v2", "$.sourceContractCompatibility.requiredPolicyVersion")
    _constant(compatibility["requiresExactDefinitionRevisionId"], True, "$.sourceContractCompatibility.requiresExactDefinitionRevisionId")
    _constant(
        compatibility["requiresExactMetricSplitSettingEvaluationVersionUnit"], True,
        "$.sourceContractCompatibility.requiresExactMetricSplitSettingEvaluationVersionUnit",
    )
    allowed_cells = _unique_scalars(
        compatibility["allowedComparisonCellIds"],
        "$.sourceContractCompatibility.allowedComparisonCellIds",
        _stable_id,
        1,
    )
    if set(allowed_cells) != set(cell_by_id):
        _fail("$.sourceContractCompatibility.allowedComparisonCellIds", "must account for every and only comparison cell")
    _constant(compatibility["allowsUnlistedDimensions"], False, "$.sourceContractCompatibility.allowsUnlistedDimensions")

    retention = _object(
        root["claimRetention"], "$.claimRetention",
        {
            "bindsClaimsToExactDefinitionRevision", "retainsPriorClaimBindings",
            "rewritesExistingClaims", "requiresAppendOnlyCorrection", "allowsIdentityFallback",
        },
    )
    _constant(retention["bindsClaimsToExactDefinitionRevision"], True, "$.claimRetention.bindsClaimsToExactDefinitionRevision")
    _constant(retention["retainsPriorClaimBindings"], True, "$.claimRetention.retainsPriorClaimBindings")
    _constant(retention["rewritesExistingClaims"], False, "$.claimRetention.rewritesExistingClaims")
    _constant(retention["requiresAppendOnlyCorrection"], True, "$.claimRetention.requiresAppendOnlyCorrection")
    _constant(retention["allowsIdentityFallback"], False, "$.claimRetention.allowsIdentityFallback")

    manifest = _object(
        root["manifest"], "$.manifest",
        {
            "algorithm", "contentSha256", "dimensionFingerprintSha256", "metricCount",
            "splitCount", "settingCount", "evaluationVersionCount", "unitCount",
            "comparabilityGroupCount", "comparisonCellCount", "relationshipCount",
        },
    )
    _constant(manifest["algorithm"], _ALGORITHM, "$.manifest.algorithm")
    _sha256(manifest["contentSha256"], "$.manifest.contentSha256")
    counts = {
        "metricCount": len(metric_by_id), "splitCount": len(split_by_id),
        "settingCount": len(setting_by_id), "evaluationVersionCount": len(version_by_id),
        "unitCount": len(unit_by_id), "comparabilityGroupCount": len(group_by_id),
        "comparisonCellCount": len(cell_by_id), "relationshipCount": len(relationship_by_id),
    }
    for key, actual in counts.items():
        declared = _integer(manifest[key], f"$.manifest.{key}")
        if declared != actual:
            _fail(f"$.manifest.{key}", f"declares {declared}, payload contains {actual}")
    declared_fingerprint = _sha256(
        manifest["dimensionFingerprintSha256"],
        "$.manifest.dimensionFingerprintSha256",
    )
    actual_fingerprint = benchmark_definition_fingerprint(root)
    if declared_fingerprint != actual_fingerprint:
        _fail("$.manifest.dimensionFingerprintSha256", "benchmark dimension fingerprint mismatch")
    verify_contract_self_digest(root)


def validate_benchmark_revision_chain(payloads: Iterable[dict[str, Any]]) -> None:
    """Validate a complete, single-leaf benchmark revision lineage per family."""

    revisions = list(payloads)
    if not revisions:
        _fail("$", "benchmark revision chain cannot be empty")
    by_id: dict[str, dict[str, Any]] = {}
    for index, payload in enumerate(revisions):
        validate_benchmark_definition_revision(payload)
        revision_id = payload["benchmarkDefinitionRevisionId"]
        if revision_id in by_id:
            _fail(f"$[{index}].benchmarkDefinitionRevisionId", "duplicate revision ID")
        by_id[revision_id] = payload

    families: dict[str, list[dict[str, Any]]] = {}
    children: dict[str, list[str]] = {revision_id: [] for revision_id in by_id}
    for revision in revisions:
        families.setdefault(revision["benchmarkFamilyId"], []).append(revision)
        prior_id = revision["supersedesDefinitionRevisionId"]
        if prior_id is None:
            continue
        prior = by_id.get(prior_id)
        if prior is None:
            _fail("$.supersedesDefinitionRevisionId", f"stale/missing prior revision {prior_id!r}")
        if prior["benchmarkFamilyId"] != revision["benchmarkFamilyId"]:
            _fail("$.benchmarkFamilyId", "supersession cannot cross benchmark families")
        children[prior_id].append(revision["benchmarkDefinitionRevisionId"])
        if len(children[prior_id]) > 1:
            _fail("$", f"branched benchmark revision leaves from {prior_id!r}")
        if revision["changeControl"]["priorBenchmarkEditionId"] != prior["benchmarkEditionId"]:
            _fail("$.changeControl.priorBenchmarkEditionId", "must equal superseded revision edition")
        same_edition = revision["benchmarkEditionId"] == prior["benchmarkEditionId"]
        same_fingerprint = (
            revision["manifest"]["dimensionFingerprintSha256"]
            == prior["manifest"]["dimensionFingerprintSha256"]
        )
        compatible_change = revision["changeControl"]["changeType"] in {
            "display_rename", "definition_correction"
        }
        if compatible_change and not same_fingerprint:
            _fail(
                "$.changeControl.changeType",
                "compatible rename/correction changed benchmark dimension identity",
            )
        if revision["changeControl"]["identityDisposition"] == "new_edition_identity":
            if same_edition or same_fingerprint:
                _fail("$.changeControl.identityDisposition", "new edition must have new ID and fingerprint")

    for family_id, family_revisions in families.items():
        roots = [item for item in family_revisions if item["supersedesDefinitionRevisionId"] is None]
        leaves = [
            item for item in family_revisions
            if not children[item["benchmarkDefinitionRevisionId"]]
        ]
        if len(roots) != 1 or len(leaves) != 1:
            _fail("$", f"benchmark family {family_id!r} must have one root and one leaf")

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(revision_id: str) -> None:
        if revision_id in visiting:
            _fail("$", "benchmark supersession loop detected")
        if revision_id in visited:
            return
        visiting.add(revision_id)
        prior_id = by_id[revision_id]["supersedesDefinitionRevisionId"]
        if prior_id is not None:
            visit(prior_id)
        visiting.remove(revision_id)
        visited.add(revision_id)

    for revision_id in by_id:
        visit(revision_id)


_SUBJECT_KEYS = {
    "schemaVersion", "policyVersion", "availability", "subjectRevisionId", "subjectId",
    "supersedesSubjectRevisionId", "lifecycleStatus", "decisionReference", "reasonCode",
    "subjectType", "resolutionStatus", "subjectFingerprintSha256",
    "observedCompositionFingerprintSha256", "authority", "manifest",
    "displayIdentity", "rawSourceIdentity", "typeDetails", "components",
    "provenanceReferences", "baseModelMapping", "claimBinding",
}


def evaluation_subject_observed_composition_fingerprint(
    payload: dict[str, Any],
) -> str:
    """Hash only revision-stable observed component-link identity.

    Link ID, role, exact raw label, and ensemble ordinal are observation facts.
    Reviewed subject IDs, resolution/review status, mapping decisions, and
    evidence/provenance references are intentionally excluded so those fields
    can be enriched without redefining the observed evaluated system.
    """

    if type(payload) is not dict:
        _fail("$", "evaluation subject must be an object")
    components = []
    for raw in _array(payload.get("components"), "$.components"):
        component = _object(raw, "$.components[]", None)
        components.append(
            {
                "componentLinkId": component.get("componentLinkId"),
                "role": component.get("role"),
                "componentRaw": component.get("componentRaw"),
                "ordinal": component.get("ordinal"),
            }
        )
    material = {
        "subjectType": payload.get("subjectType"),
        "components": sorted(
            components,
            key=lambda item: canonical_json(item.get("componentLinkId")),
        ),
    }
    return hashlib.sha256(canonical_json(material).encode("utf-8")).hexdigest()


def evaluation_subject_fingerprint(payload: dict[str, Any]) -> str:
    """Hash exact raw identity and typed composition with set-like inputs sorted."""

    if type(payload) is not dict:
        _fail("$", "evaluation subject must be an object")
    raw_identity = deepcopy(_object(payload.get("rawSourceIdentity"), "$.rawSourceIdentity", None))
    raw_identity["evidenceReferenceIds"] = sorted(raw_identity.get("evidenceReferenceIds", []))
    components = []
    for raw in _array(payload.get("components"), "$.components"):
        component = deepcopy(_object(raw, "$.components[]", None))
        component["evidenceReferenceIds"] = sorted(component.get("evidenceReferenceIds", []))
        component.pop("mappingDecisionReference", None)
        components.append(component)
    provenance = [deepcopy(item) for item in _array(payload.get("provenanceReferences"), "$.provenanceReferences")]
    mapping = deepcopy(_object(payload.get("baseModelMapping"), "$.baseModelMapping", None))
    mapping.pop("decisionReference", None)
    material = {
        "subjectType": payload.get("subjectType"),
        "rawSourceIdentity": raw_identity,
        "typeDetails": payload.get("typeDetails"),
        "components": sorted(components, key=lambda item: canonical_json(item.get("componentLinkId"))),
        "provenanceReferences": sorted(
            provenance, key=lambda item: canonical_json(item.get("provenanceId"))
        ),
        "baseModelMapping": mapping,
    }
    return hashlib.sha256(canonical_json(material).encode("utf-8")).hexdigest()


def validate_evaluation_subject(payload: dict[str, Any]) -> None:
    """Validate one typed top-level evaluated-system subject revision."""

    _walk_json(payload)
    root = _object(payload, "$", _SUBJECT_KEYS)
    _constant(root["schemaVersion"], "1.0.0", "$.schemaVersion")
    _constant(root["policyVersion"], "evaluation-subject-v1", "$.policyVersion")
    _constant(root["availability"], "identity_definition_only", "$.availability")
    revision_id = _stable_id(root["subjectRevisionId"], "$.subjectRevisionId")
    subject_id = _stable_id(root["subjectId"], "$.subjectId")
    supersedes = _stable_id(
        root["supersedesSubjectRevisionId"], "$.supersedesSubjectRevisionId", nullable=True
    )
    if revision_id == supersedes:
        _fail("$.supersedesSubjectRevisionId", "a subject revision cannot supersede itself")
    lifecycle = _enum(
        root["lifecycleStatus"], {"draft", "reviewed", "superseded", "retired"},
        "$.lifecycleStatus",
    )
    decision = _stable_id(root["decisionReference"], "$.decisionReference", nullable=True)
    _reason(root["reasonCode"], "$.reasonCode")
    subject_type = _enum(
        root["subjectType"],
        {"base_model", "versioned_endpoint", "agent_model_system", "ensemble", "opaque_submission", "unknown_unresolved"},
        "$.subjectType",
    )
    resolution = _enum(root["resolutionStatus"], {"resolved", "unresolved"}, "$.resolutionStatus")
    declared_fingerprint = _sha256(root["subjectFingerprintSha256"], "$.subjectFingerprintSha256")
    declared_composition_fingerprint = _sha256(
        root["observedCompositionFingerprintSha256"],
        "$.observedCompositionFingerprintSha256",
    )

    authority = _object(
        root["authority"], "$.authority",
        {
            "classification", "reviewStatus", "establishesClaimMapping", "rewritesClaims",
            "promotesValidation", "authorizesPublication", "frontendLoadable",
        },
    )
    _constant(
        authority["classification"], "evaluation_subject_definition_only",
        "$.authority.classification",
    )
    review_status = _enum(
        authority["reviewStatus"], {"draft_unreviewed", "identity_reviewed"},
        "$.authority.reviewStatus",
    )
    _validate_authority_false(
        authority,
        "$.authority",
        (
            "establishesClaimMapping", "rewritesClaims", "promotesValidation",
            "authorizesPublication", "frontendLoadable",
        ),
    )
    if lifecycle == "draft":
        if decision is not None or review_status != "draft_unreviewed":
            _fail("$.lifecycleStatus", "draft subject cannot carry reviewed bindings")
    elif decision is None or review_status != "identity_reviewed":
        _fail("$.lifecycleStatus", "non-draft subject requires an identity review decision")

    display = _object(
        root["displayIdentity"], "$.displayIdentity",
        {"modelEntityId", "displayName", "entityType", "preservesGetValueModelIdentity", "frontendComparable"},
    )
    display_model_id = _stable_id(
        display["modelEntityId"], "$.displayIdentity.modelEntityId", nullable=True
    )
    _non_empty(display["displayName"], "$.displayIdentity.displayName")
    if display["entityType"] != subject_type:
        _fail("$.displayIdentity.entityType", "must match subjectType")
    _constant(display["preservesGetValueModelIdentity"], True, "$.displayIdentity.preservesGetValueModelIdentity")
    _constant(display["frontendComparable"], False, "$.displayIdentity.frontendComparable")
    if resolution == "resolved":
        if subject_type == "unknown_unresolved" or display_model_id != subject_id:
            _fail("$.displayIdentity.modelEntityId", "resolved subject requires its own typed top-level subjectId")
    elif display_model_id is not None:
        _fail("$.displayIdentity.modelEntityId", "unresolved subject must retain a null canonical model identity")
    if subject_type == "unknown_unresolved" and resolution != "unresolved":
        _fail("$.resolutionStatus", "unknown subject must remain explicitly unresolved")

    provenance, provenance_by_id = _unique_objects(
        root["provenanceReferences"], "$.provenanceReferences", "provenanceId", 1
    )
    for index, item in enumerate(provenance):
        path = f"$.provenanceReferences[{index}]"
        _object(
            item, path,
            {"provenanceId", "provenanceType", "referenceId", "contentSha256", "mappingAuthority"},
        )
        _enum(
            item["provenanceType"],
            {"discovery_candidate", "source_snapshot", "manual_official_lead", "first_party_metadata"},
            f"{path}.provenanceType",
        )
        _stable_id(item["referenceId"], f"{path}.referenceId")
        _sha256(item["contentSha256"], f"{path}.contentSha256", nullable=True)
        _constant(
            item["mappingAuthority"], "context_only_not_identity_proof",
            f"{path}.mappingAuthority",
        )

    raw_identity = _object(
        root["rawSourceIdentity"], "$.rawSourceIdentity",
        {
            "modelRaw", "providerRaw", "configurationRaw", "sourceObservationReference",
            "sourceSnapshotReference", "evidenceReferenceIds", "preservedExactly", "normalizationApplied",
        },
    )
    _non_empty(raw_identity["modelRaw"], "$.rawSourceIdentity.modelRaw")
    _nullable_string(raw_identity["providerRaw"], "$.rawSourceIdentity.providerRaw")
    _nullable_string(raw_identity["configurationRaw"], "$.rawSourceIdentity.configurationRaw")
    observation_ref = _stable_id(
        raw_identity["sourceObservationReference"],
        "$.rawSourceIdentity.sourceObservationReference",
        nullable=True,
    )
    snapshot_ref = _stable_id(
        raw_identity["sourceSnapshotReference"],
        "$.rawSourceIdentity.sourceSnapshotReference",
        nullable=True,
    )
    if observation_ref is None and snapshot_ref is None:
        _fail("$.rawSourceIdentity", "requires an observation or immutable snapshot reference")
    raw_evidence = _unique_scalars(
        raw_identity["evidenceReferenceIds"],
        "$.rawSourceIdentity.evidenceReferenceIds",
        _stable_id,
        1,
    )
    if not set(raw_evidence).issubset(provenance_by_id):
        _fail("$.rawSourceIdentity.evidenceReferenceIds", "contains unknown provenance reference")
    _constant(raw_identity["preservedExactly"], True, "$.rawSourceIdentity.preservedExactly")
    _constant(raw_identity["normalizationApplied"], False, "$.rawSourceIdentity.normalizationApplied")

    details = _object(root["typeDetails"], "$.typeDetails", None)
    detail_type = details.get("detailType")
    if detail_type != subject_type:
        _fail("$.typeDetails.detailType", "must match subjectType")
    detail_shapes = {
        "base_model": {"detailType", "modelVersionRaw"},
        "versioned_endpoint": {"detailType", "endpointRaw", "endpointVersionRaw"},
        "agent_model_system": {"detailType", "agentRaw", "systemVersionRaw"},
        "ensemble": {"detailType", "routingRaw"},
        "opaque_submission": {"detailType", "submissionRaw"},
        "unknown_unresolved": {"detailType", "uncertaintyNote"},
    }
    _object(details, "$.typeDetails", detail_shapes[subject_type])
    required_detail_strings = {
        "base_model": ("modelVersionRaw",),
        "versioned_endpoint": ("endpointRaw", "endpointVersionRaw"),
        "agent_model_system": ("agentRaw",),
        "opaque_submission": ("submissionRaw",),
        "unknown_unresolved": ("uncertaintyNote",),
    }
    for key in required_detail_strings.get(subject_type, ()):
        _non_empty(details[key], f"$.typeDetails.{key}")
    if subject_type == "agent_model_system":
        _nullable_string(details["systemVersionRaw"], "$.typeDetails.systemVersionRaw")
    if subject_type == "ensemble":
        _nullable_string(details["routingRaw"], "$.typeDetails.routingRaw")

    components, component_by_id = _unique_objects(
        root["components"], "$.components", "componentLinkId"
    )
    component_identity_keys: set[tuple[str, str]] = set()
    member_ordinals: set[int] = set()
    for index, component in enumerate(components):
        path = f"$.components[{index}]"
        _object(
            component, path,
            {
                "componentLinkId", "role", "componentSubjectId", "componentRaw",
                "resolutionStatus", "reviewStatus", "mappingDecisionReference",
                "evidenceReferenceIds", "ordinal",
            },
        )
        role = _enum(
            component["role"],
            {"base_model", "endpoint", "agent", "harness", "tooling", "router", "member", "other"},
            f"{path}.role",
        )
        component_subject_id = _stable_id(
            component["componentSubjectId"], f"{path}.componentSubjectId", nullable=True
        )
        component_raw = _non_empty(component["componentRaw"], f"{path}.componentRaw")
        component_resolution = _enum(
            component["resolutionStatus"], {"resolved", "unresolved"}, f"{path}.resolutionStatus"
        )
        component_review = _enum(
            component["reviewStatus"], {"proposed", "reviewed"}, f"{path}.reviewStatus"
        )
        component_decision = _stable_id(
            component["mappingDecisionReference"],
            f"{path}.mappingDecisionReference",
            nullable=True,
        )
        if component_subject_id == subject_id:
            _fail(f"{path}.componentSubjectId", "subject cannot contain itself")
        if component_resolution == "resolved":
            if component_subject_id is None or component_review != "reviewed" or component_decision is None:
                _fail(path, "resolved component requires reviewed subject and mapping decision")
            identity_value = component_subject_id
        else:
            if component_subject_id is not None or component_review != "proposed" or component_decision is not None:
                _fail(path, "unresolved component must retain raw label and null reviewed mapping")
            identity_value = component_raw
        identity_key = (role, identity_value)
        if identity_key in component_identity_keys:
            _fail(path, "duplicate semantic component link")
        component_identity_keys.add(identity_key)
        evidence_ids = _unique_scalars(
            component["evidenceReferenceIds"], f"{path}.evidenceReferenceIds", _stable_id, 1
        )
        if not set(evidence_ids).issubset(provenance_by_id):
            _fail(f"{path}.evidenceReferenceIds", "contains unknown provenance reference")
        ordinal = component["ordinal"]
        if ordinal is not None:
            ordinal = _integer(ordinal, f"{path}.ordinal")
        if role == "member":
            if ordinal is None:
                _fail(f"{path}.ordinal", "ensemble members require an ordinal")
            if ordinal in member_ordinals:
                _fail(f"{path}.ordinal", "duplicate ensemble member ordinal")
            member_ordinals.add(ordinal)
        elif ordinal is not None:
            _fail(f"{path}.ordinal", "ordinal is only valid for ensemble members")

    roles = [item["role"] for item in components]
    if subject_type == "base_model" and components:
        _fail("$.components", "base model cannot be collapsed from component subjects")
    if subject_type == "versioned_endpoint":
        if any(role != "base_model" for role in roles) or roles.count("base_model") > 1:
            _fail("$.components", "versioned endpoint permits at most one explicit base-model component")
    if subject_type == "agent_model_system":
        if roles.count("base_model") != 1 or roles.count("harness") != 1:
            _fail("$.components", "agent system requires one base-model and one harness component")
    if subject_type == "ensemble":
        if len(components) < 2 or any(role != "member" for role in roles):
            _fail("$.components", "ensemble requires at least two ordered member components")
    if subject_type in {"opaque_submission", "unknown_unresolved"} and components:
        _fail("$.components", "opaque/unresolved subject cannot fabricate component mappings")

    mapping = _object(
        root["baseModelMapping"], "$.baseModelMapping",
        {"status", "componentLinkId", "decisionReference", "fabricated"},
    )
    mapping_status = _enum(
        mapping["status"], {"not_applicable", "unresolved", "proposed", "reviewed"},
        "$.baseModelMapping.status",
    )
    mapping_link_id = _stable_id(
        mapping["componentLinkId"], "$.baseModelMapping.componentLinkId", nullable=True
    )
    mapping_decision = _stable_id(
        mapping["decisionReference"], "$.baseModelMapping.decisionReference", nullable=True
    )
    _constant(mapping["fabricated"], False, "$.baseModelMapping.fabricated")
    base_components = [item for item in components if item["role"] == "base_model"]
    if subject_type == "base_model":
        if mapping_status != "not_applicable" or mapping_link_id is not None or mapping_decision is not None:
            _fail("$.baseModelMapping", "base model mapping is not applicable to a base-model subject")
    elif not base_components:
        if mapping_status != "unresolved" or mapping_link_id is not None or mapping_decision is not None:
            _fail("$.baseModelMapping", "absent base-model evidence must remain unresolved")
    else:
        base_component = base_components[0]
        if mapping_link_id != base_component["componentLinkId"]:
            _fail("$.baseModelMapping.componentLinkId", "must reference the explicit base-model component")
        if base_component["resolutionStatus"] == "unresolved":
            if mapping_status != "proposed" or mapping_decision is not None:
                _fail("$.baseModelMapping", "unresolved component can only be a decision-free proposal")
        elif mapping_status != "reviewed" or mapping_decision != base_component["mappingDecisionReference"]:
            _fail("$.baseModelMapping", "reviewed mapping must cite the component mapping decision")

    claim_binding = _object(
        root["claimBinding"], "$.claimBinding",
        {
            "mayBindFutureClaims", "requiresIdentityDecision", "rewritesExistingClaims",
            "preservesModelRaw", "promotesValidationOrPublication",
        },
    )
    _constant(claim_binding["mayBindFutureClaims"], False, "$.claimBinding.mayBindFutureClaims")
    _constant(claim_binding["requiresIdentityDecision"], True, "$.claimBinding.requiresIdentityDecision")
    _constant(claim_binding["rewritesExistingClaims"], False, "$.claimBinding.rewritesExistingClaims")
    _constant(claim_binding["preservesModelRaw"], True, "$.claimBinding.preservesModelRaw")
    _constant(claim_binding["promotesValidationOrPublication"], False, "$.claimBinding.promotesValidationOrPublication")

    manifest = _object(
        root["manifest"], "$.manifest",
        {"algorithm", "contentSha256", "componentLinkCount", "provenanceReferenceCount"},
    )
    _constant(manifest["algorithm"], _ALGORITHM, "$.manifest.algorithm")
    _sha256(manifest["contentSha256"], "$.manifest.contentSha256")
    counts = {
        "componentLinkCount": len(component_by_id),
        "provenanceReferenceCount": len(provenance_by_id),
    }
    for key, actual in counts.items():
        declared = _integer(manifest[key], f"$.manifest.{key}")
        if declared != actual:
            _fail(f"$.manifest.{key}", f"declares {declared}, payload contains {actual}")
    actual_fingerprint = evaluation_subject_fingerprint(root)
    if declared_fingerprint != actual_fingerprint:
        _fail("$.subjectFingerprintSha256", "evaluation subject fingerprint mismatch")
    actual_composition_fingerprint = (
        evaluation_subject_observed_composition_fingerprint(root)
    )
    if declared_composition_fingerprint != actual_composition_fingerprint:
        _fail(
            "$.observedCompositionFingerprintSha256",
            "observed composition fingerprint mismatch",
        )
    verify_contract_self_digest(root)


def validate_evaluation_subject_revision_chain(
    payloads: Iterable[dict[str, Any]],
) -> None:
    """Validate complete, linear definition history for each evaluation subject.

    This validates immutable subject-definition supersession.  It is distinct
    from :func:`validate_evaluation_subject_graph`, which validates one selected
    revision per subject and the component references between those selections.
    """

    revisions = list(payloads)
    if not revisions:
        _fail("$", "evaluation subject revision chain cannot be empty")

    by_revision_id: dict[str, dict[str, Any]] = {}
    by_subject_id: dict[str, list[dict[str, Any]]] = {}
    for index, payload in enumerate(revisions):
        validate_evaluation_subject(payload)
        revision_id = payload["subjectRevisionId"]
        if revision_id in by_revision_id:
            _fail(f"$[{index}].subjectRevisionId", "duplicate subject revision ID")
        by_revision_id[revision_id] = payload
        by_subject_id.setdefault(payload["subjectId"], []).append(payload)

    children: dict[str, list[str]] = {
        revision_id: [] for revision_id in by_revision_id
    }
    for revision in revisions:
        prior_id = revision["supersedesSubjectRevisionId"]
        if prior_id is None:
            continue
        prior = by_revision_id.get(prior_id)
        if prior is None:
            _fail(
                "$.supersedesSubjectRevisionId",
                f"stale/missing prior subject revision {prior_id!r}",
            )
        if prior["subjectId"] != revision["subjectId"]:
            _fail("$.subjectId", "subject revision supersession cannot cross subjects")
        if prior["subjectType"] != revision["subjectType"]:
            _fail("$.subjectType", "subjectType cannot change under the same subjectId")
        if (
            prior["observedCompositionFingerprintSha256"]
            != revision["observedCompositionFingerprintSha256"]
        ):
            _fail(
                "$.observedCompositionFingerprintSha256",
                "subject revisions cannot change observed component composition",
            )
        if canonical_json(prior["rawSourceIdentity"]) != canonical_json(
            revision["rawSourceIdentity"]
        ):
            _fail(
                "$.rawSourceIdentity",
                "subject revisions must preserve exact raw source identity",
            )
        prior_model_id = prior["displayIdentity"]["modelEntityId"]
        current_model_id = revision["displayIdentity"]["modelEntityId"]
        if prior_model_id is not None and current_model_id != prior_model_id:
            _fail(
                "$.displayIdentity.modelEntityId",
                "subject revisions cannot collapse or replace top-level model identity",
            )
        children[prior_id].append(revision["subjectRevisionId"])
        if len(children[prior_id]) > 1:
            _fail("$", f"branched subject revision leaves from {prior_id!r}")

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(revision_id: str) -> None:
        if revision_id in visiting:
            _fail("$", "evaluation subject revision cycle detected")
        if revision_id in visited:
            return
        visiting.add(revision_id)
        prior_id = by_revision_id[revision_id]["supersedesSubjectRevisionId"]
        if prior_id is not None:
            visit(prior_id)
        visiting.remove(revision_id)
        visited.add(revision_id)

    for revision_id in by_revision_id:
        visit(revision_id)

    for subject_id, subject_revisions in by_subject_id.items():
        roots = [
            item
            for item in subject_revisions
            if item["supersedesSubjectRevisionId"] is None
        ]
        leaves = [
            item
            for item in subject_revisions
            if not children[item["subjectRevisionId"]]
        ]
        if len(roots) != 1 or len(leaves) != 1:
            _fail(
                "$",
                f"evaluation subject {subject_id!r} must have one root and one leaf",
            )


def validate_evaluation_subject_graph(payloads: Iterable[dict[str, Any]]) -> None:
    """Validate one selected subject revision per ID and reject component cycles.

    This is a selected-definition graph validator, not a revision-lineage
    validator.  Use :func:`validate_evaluation_subject_revision_chain` for
    immutable supersession history.
    """

    subjects = list(payloads)
    if not subjects:
        _fail("$", "evaluation subject graph cannot be empty")
    by_id: dict[str, dict[str, Any]] = {}
    for index, payload in enumerate(subjects):
        validate_evaluation_subject(payload)
        subject_id = payload["subjectId"]
        if subject_id in by_id:
            _fail(f"$[{index}].subjectId", "graph requires one selected revision per subject ID")
        by_id[subject_id] = payload

    edges: dict[str, list[str]] = {subject_id: [] for subject_id in by_id}
    for subject_id, payload in by_id.items():
        for component in payload["components"]:
            target_id = component["componentSubjectId"]
            if component["resolutionStatus"] != "resolved" or target_id not in by_id:
                continue
            if component["role"] == "base_model" and by_id[target_id]["subjectType"] != "base_model":
                _fail("$.components", "reviewed base-model component does not target a base-model subject")
            edges[subject_id].append(target_id)

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(subject_id: str) -> None:
        if subject_id in visiting:
            _fail("$", "evaluation subject component cycle detected")
        if subject_id in visited:
            return
        visiting.add(subject_id)
        for target_id in edges[subject_id]:
            visit(target_id)
        visiting.remove(subject_id)
        visited.add(subject_id)

    for subject_id in by_id:
        visit(subject_id)


_DECISION_KEYS = {
    "schemaVersion", "policyVersion", "availability", "decisionId", "candidateReference",
    "observationReference", "identityItemFingerprintSha256", "expectedPriorDecisionId",
    "decisionSequence", "decisionStatus", "decidedAt", "governanceDecisionReference", "outcome",
    "selectedSubjectId", "supersedingCandidateReference", "reasonCode", "actor",
    "authority", "manifest", "rawObservation", "aliasProposal", "collisionFacts", "effects",
}


def identity_decision_item_fingerprint(payload: dict[str, Any]) -> str:
    """Hash the immutable candidate/raw observation identity shared by its decision chain."""

    if type(payload) is not dict:
        _fail("$", "identity decision must be an object")
    raw = deepcopy(_object(payload.get("rawObservation"), "$.rawObservation", None))
    raw.pop("rawLabelSha256", None)
    raw["sourceEvidenceReferenceIds"] = sorted(raw.get("sourceEvidenceReferenceIds", []))
    material = {
        "candidateReference": payload.get("candidateReference"),
        "observationReference": payload.get("observationReference"),
        "rawObservation": raw,
    }
    return hashlib.sha256(canonical_json(material).encode("utf-8")).hexdigest()


def validate_identity_decision(payload: dict[str, Any]) -> None:
    """Validate one append-only, itemized evaluated-system identity decision."""

    _walk_json(payload)
    root = _object(payload, "$", _DECISION_KEYS)
    _constant(root["schemaVersion"], "1.0.0", "$.schemaVersion")
    _constant(root["policyVersion"], "identity-decision-v1", "$.policyVersion")
    _constant(root["availability"], "identity_decision_only", "$.availability")
    _stable_id(root["decisionId"], "$.decisionId")
    candidate_reference = _stable_id(root["candidateReference"], "$.candidateReference")
    _stable_id(root["observationReference"], "$.observationReference")
    declared_fingerprint = _sha256(
        root["identityItemFingerprintSha256"], "$.identityItemFingerprintSha256"
    )
    prior_decision = _stable_id(
        root["expectedPriorDecisionId"], "$.expectedPriorDecisionId", nullable=True
    )
    sequence = _integer(root["decisionSequence"], "$.decisionSequence", 1)
    if sequence == 1 and prior_decision is not None:
        _fail("$.expectedPriorDecisionId", "first decision must have a null prior decision")
    if sequence > 1 and prior_decision is None:
        _fail("$.expectedPriorDecisionId", "later decision requires the exact prior decision")
    status = _enum(root["decisionStatus"], {"draft", "effective"}, "$.decisionStatus")
    decided_at = _utc_second(root["decidedAt"], "$.decidedAt", nullable=True)
    governance_reference = _stable_id(
        root["governanceDecisionReference"],
        "$.governanceDecisionReference",
        nullable=True,
    )
    outcome = _enum(
        root["outcome"], {"resolved", "unresolved", "rejected", "superseded"},
        "$.outcome",
    )
    selected_subject_id = _stable_id(
        root["selectedSubjectId"], "$.selectedSubjectId", nullable=True
    )
    superseding_candidate = _stable_id(
        root["supersedingCandidateReference"],
        "$.supersedingCandidateReference",
        nullable=True,
    )
    _reason(root["reasonCode"], "$.reasonCode")

    actor = _object(
        root["actor"], "$.actor", {"actorId", "actorType", "role", "authorityReference"}
    )
    _stable_id(actor["actorId"], "$.actor.actorId")
    actor_type = _enum(actor["actorType"], {"human", "service"}, "$.actor.actorType")
    _stable_id(actor["role"], "$.actor.role")
    actor_authority_reference = _stable_id(
        actor["authorityReference"], "$.actor.authorityReference", nullable=True
    )

    authority = _object(
        root["authority"], "$.authority",
        {
            "classification", "approvalStatus", "actorAuthorityVerified",
            "permitsIdentityReadProjection", "rewritesClaims", "promotesCapture",
            "promotesValidation", "authorizesPublication", "frontendLoadable",
        },
    )
    _constant(
        authority["classification"], "itemized_identity_decision_only",
        "$.authority.classification",
    )
    approval = _enum(
        authority["approvalStatus"], {"draft_unapproved", "identity_reviewed"},
        "$.authority.approvalStatus",
    )
    actor_verified = _boolean(authority["actorAuthorityVerified"], "$.authority.actorAuthorityVerified")
    permits_projection = _boolean(
        authority["permitsIdentityReadProjection"],
        "$.authority.permitsIdentityReadProjection",
    )
    _validate_authority_false(
        authority,
        "$.authority",
        ("rewritesClaims", "promotesCapture", "promotesValidation", "authorizesPublication", "frontendLoadable"),
    )
    if status == "draft":
        if (
            governance_reference is not None
            or approval != "draft_unapproved"
            or actor_verified
            or permits_projection
            or outcome != "unresolved"
            or decided_at is not None
        ):
            _fail("$.decisionStatus", "draft decision must remain unapproved, unresolved, and non-binding")
    else:
        if (
            governance_reference is None
            or approval != "identity_reviewed"
            or not actor_verified
            or not permits_projection
            or actor_type != "human"
            or actor_authority_reference is None
            or decided_at is None
        ):
            _fail(
                "$.decisionStatus",
                "effective decision requires canonical decision time and verified human item authority",
            )

    if outcome == "resolved":
        if selected_subject_id is None or superseding_candidate is not None or status != "effective":
            _fail("$.outcome", "resolved outcome requires one reviewed subject and no superseding candidate")
    elif outcome in {"unresolved", "rejected"}:
        if selected_subject_id is not None or superseding_candidate is not None:
            _fail("$.outcome", "unresolved/rejected outcome cannot select or supersede identity")
    elif (
        selected_subject_id is not None
        or superseding_candidate is None
        or superseding_candidate == candidate_reference
        or status != "effective"
    ):
        _fail("$.outcome", "superseded outcome requires a distinct candidate reference")

    raw = _object(
        root["rawObservation"], "$.rawObservation",
        {
            "modelRaw", "providerRaw", "configurationRaw", "rawLabelSha256",
            "sourceEvidenceReferenceIds", "preservedExactly",
        },
    )
    model_raw = _non_empty(raw["modelRaw"], "$.rawObservation.modelRaw")
    _nullable_string(raw["providerRaw"], "$.rawObservation.providerRaw")
    _nullable_string(raw["configurationRaw"], "$.rawObservation.configurationRaw")
    if _sha256(raw["rawLabelSha256"], "$.rawObservation.rawLabelSha256") != raw_identity_label_sha256(model_raw):
        _fail("$.rawObservation.rawLabelSha256", "must hash the exact unnormalized modelRaw string")
    source_evidence = _unique_scalars(
        raw["sourceEvidenceReferenceIds"],
        "$.rawObservation.sourceEvidenceReferenceIds",
        _stable_id,
        1,
    )
    _constant(raw["preservedExactly"], True, "$.rawObservation.preservedExactly")

    alias = _object(
        root["aliasProposal"], "$.aliasProposal",
        {"aliasRaw", "matchMethod", "normalizedAlias", "provenanceReferenceIds", "scope", "proposedAction"},
    )
    alias_raw = _non_empty(alias["aliasRaw"], "$.aliasProposal.aliasRaw")
    if alias_raw != model_raw:
        _fail("$.aliasProposal.aliasRaw", "must preserve exact raw model label")
    match_method = _enum(
        alias["matchMethod"], {"exact", "case_insensitive", "normalized", "manual"},
        "$.aliasProposal.matchMethod",
    )
    normalized_alias = _nullable_string(alias["normalizedAlias"], "$.aliasProposal.normalizedAlias")
    if match_method == "exact" and normalized_alias is not None:
        _fail("$.aliasProposal.normalizedAlias", "exact matching must not add normalized identity")
    if match_method in {"case_insensitive", "normalized"} and normalized_alias is None:
        _fail("$.aliasProposal.normalizedAlias", "non-exact matching requires explicit normalized evidence")
    alias_provenance = _unique_scalars(
        alias["provenanceReferenceIds"],
        "$.aliasProposal.provenanceReferenceIds",
        _stable_id,
        1,
    )
    if not set(alias_provenance).issubset(source_evidence):
        _fail(
            "$.aliasProposal.provenanceReferenceIds",
            "alias provenance must resolve to this raw observation's source evidence",
        )
    proposed_action = _enum(
        alias["proposedAction"], {"add_scoped_alias", "no_alias", "reject_alias"},
        "$.aliasProposal.proposedAction",
    )
    scope = _object(
        alias["scope"], "$.aliasProposal.scope",
        {"scopeType", "ownerId", "benchmarkEditionIds", "sourceRevisionIds"},
    )
    scope_type = _enum(
        scope["scopeType"], {"global", "owner", "benchmark", "source_revision"},
        "$.aliasProposal.scope.scopeType",
    )
    owner_id = _stable_id(scope["ownerId"], "$.aliasProposal.scope.ownerId", nullable=True)
    benchmark_ids = _unique_scalars(
        scope["benchmarkEditionIds"], "$.aliasProposal.scope.benchmarkEditionIds", _stable_id
    )
    source_revision_ids = _unique_scalars(
        scope["sourceRevisionIds"], "$.aliasProposal.scope.sourceRevisionIds", _stable_id
    )
    if scope_type == "global" and (owner_id is not None or benchmark_ids or source_revision_ids):
        _fail("$.aliasProposal.scope", "global scope cannot carry narrower scope IDs")
    if scope_type == "owner" and (owner_id is None or benchmark_ids or source_revision_ids):
        _fail("$.aliasProposal.scope", "owner scope requires only ownerId")
    if scope_type == "benchmark" and (not benchmark_ids or source_revision_ids):
        _fail("$.aliasProposal.scope", "benchmark scope requires benchmark edition IDs only")
    if scope_type == "source_revision" and not source_revision_ids:
        _fail("$.aliasProposal.scope", "source-revision scope requires source revision IDs")

    collision = _object(
        root["collisionFacts"], "$.collisionFacts",
        {"status", "matchingPriority", "conflictingSubjectIds", "reasonCode"},
    )
    collision_status = _enum(
        collision["status"],
        {"none", "exact_collision", "case_insensitive_collision", "normalized_collision"},
        "$.collisionFacts.status",
    )
    matching_priority = _enum(
        collision["matchingPriority"], {"none", "exact", "case_insensitive", "normalized"},
        "$.collisionFacts.matchingPriority",
    )
    conflicting_subjects = _unique_scalars(
        collision["conflictingSubjectIds"],
        "$.collisionFacts.conflictingSubjectIds",
        _stable_id,
    )
    collision_reason = _reason(collision["reasonCode"], "$.collisionFacts.reasonCode", nullable=True)
    expected_priority = {
        "exact_collision": "exact",
        "case_insensitive_collision": "case_insensitive",
        "normalized_collision": "normalized",
    }
    if collision_status == "none":
        if matching_priority != "none" or conflicting_subjects or collision_reason is not None:
            _fail("$.collisionFacts", "no-collision facts must be empty")
    else:
        if (
            matching_priority != expected_priority[collision_status]
            or len(conflicting_subjects) < 2
            or collision_reason is None
            or outcome not in {"unresolved", "rejected"}
            or selected_subject_id is not None
            or proposed_action not in {"no_alias", "reject_alias"}
        ):
            _fail("$.collisionFacts", "collision at first matching priority must fail ambiguous")
    if outcome == "resolved" and proposed_action != "add_scoped_alias":
        _fail("$.aliasProposal.proposedAction", "resolved identity requires one scoped alias action")
    if outcome == "unresolved" and proposed_action != "no_alias":
        _fail("$.aliasProposal.proposedAction", "unresolved identity cannot add or reject an alias")
    if outcome == "rejected" and proposed_action != "reject_alias":
        _fail("$.aliasProposal.proposedAction", "rejected identity must reject the alias")
    if outcome == "superseded" and proposed_action != "no_alias":
        _fail("$.aliasProposal.proposedAction", "superseded item cannot change aliases")

    effects = _object(
        root["effects"], "$.effects",
        {
            "itemized", "identityReadProjectionEffect", "rewritesExistingClaims", "mutatesRawFields",
            "promotesCaptureStatus", "promotesValidationStatus", "authorizesPublication",
        },
    )
    _constant(effects["itemized"], True, "$.effects.itemized")
    projection_effect = _enum(
        effects["identityReadProjectionEffect"],
        {"none", "set_selected_subject", "clear_selected_subject"},
        "$.effects.identityReadProjectionEffect",
    )
    expected_projection_effect = (
        "none"
        if status == "draft"
        else "set_selected_subject"
        if outcome == "resolved"
        else "clear_selected_subject"
    )
    if projection_effect != expected_projection_effect:
        _fail(
            "$.effects.identityReadProjectionEffect",
            f"must equal {expected_projection_effect!r} for {status}/{outcome}",
        )
    _validate_authority_false(
        effects,
        "$.effects",
        (
            "rewritesExistingClaims", "mutatesRawFields", "promotesCaptureStatus",
            "promotesValidationStatus", "authorizesPublication",
        ),
    )

    manifest = _object(
        root["manifest"], "$.manifest",
        {
            "algorithm", "contentSha256", "itemCount", "sourceEvidenceReferenceCount",
            "aliasProvenanceReferenceCount", "collisionSubjectCount",
        },
    )
    _constant(manifest["algorithm"], _ALGORITHM, "$.manifest.algorithm")
    _sha256(manifest["contentSha256"], "$.manifest.contentSha256")
    _constant(manifest["itemCount"], 1, "$.manifest.itemCount")
    counts = {
        "sourceEvidenceReferenceCount": len(source_evidence),
        "aliasProvenanceReferenceCount": len(alias_provenance),
        "collisionSubjectCount": len(conflicting_subjects),
    }
    for key, actual in counts.items():
        declared = _integer(manifest[key], f"$.manifest.{key}")
        if declared != actual:
            _fail(f"$.manifest.{key}", f"declares {declared}, payload contains {actual}")
    actual_fingerprint = identity_decision_item_fingerprint(root)
    if declared_fingerprint != actual_fingerprint:
        _fail("$.identityItemFingerprintSha256", "identity item fingerprint mismatch")
    verify_contract_self_digest(root)


def validate_identity_decision_chain(payloads: Iterable[dict[str, Any]]) -> None:
    """Reject stale, branched, or cyclic append-only identity decision chains."""

    decisions = list(payloads)
    if not decisions:
        _fail("$", "identity decision chain cannot be empty")
    by_id: dict[str, dict[str, Any]] = {}
    by_candidate: dict[str, list[dict[str, Any]]] = {}
    for index, payload in enumerate(decisions):
        validate_identity_decision(payload)
        decision_id = payload["decisionId"]
        if decision_id in by_id:
            _fail(f"$[{index}].decisionId", "duplicate decision ID")
        by_id[decision_id] = payload
        by_candidate.setdefault(payload["candidateReference"], []).append(payload)

    for candidate_reference, candidate_decisions in by_candidate.items():
        observations = {item["observationReference"] for item in candidate_decisions}
        fingerprints = {item["identityItemFingerprintSha256"] for item in candidate_decisions}
        if len(observations) != 1 or len(fingerprints) != 1:
            _fail("$", f"candidate {candidate_reference!r} changed raw observation identity")
        candidate_ids = {item["decisionId"] for item in candidate_decisions}
        roots = [item for item in candidate_decisions if item["expectedPriorDecisionId"] is None]
        children: dict[str, list[str]] = {decision_id: [] for decision_id in candidate_ids}
        for item in candidate_decisions:
            prior_id = item["expectedPriorDecisionId"]
            if prior_id is None:
                continue
            if prior_id not in candidate_ids:
                _fail("$.expectedPriorDecisionId", f"stale/missing prior identity decision {prior_id!r}")
            parent = by_id[prior_id]
            if item["decisionSequence"] != parent["decisionSequence"] + 1:
                _fail("$.decisionSequence", "identity decision sequence is stale or non-contiguous")
            if parent["decisionStatus"] == "effective" and item["decisionStatus"] == "draft":
                _fail("$.decisionStatus", "an effective identity decision cannot have a draft child")
            parent_time = _utc_second(parent["decidedAt"], "$.decidedAt", nullable=True)
            child_time = _utc_second(item["decidedAt"], "$.decidedAt", nullable=True)
            if (
                parent_time is not None
                and child_time is not None
                and child_time <= parent_time
            ):
                _fail("$.decidedAt", "effective decision times must strictly increase")
            children[prior_id].append(item["decisionId"])
            if len(children[prior_id]) > 1:
                _fail("$", f"branched identity decision leaves from {prior_id!r}")
        leaves = [item for item in candidate_decisions if not children[item["decisionId"]]]
        if len(roots) != 1 or len(leaves) != 1 or roots[0]["decisionSequence"] != 1:
            _fail("$", f"candidate {candidate_reference!r} requires one linear root and leaf")

        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(decision_id: str) -> None:
            if decision_id in visiting:
                _fail("$", "identity decision cycle detected")
            if decision_id in visited:
                return
            visiting.add(decision_id)
            prior_id = by_id[decision_id]["expectedPriorDecisionId"]
            if prior_id is not None:
                visit(prior_id)
            visiting.remove(decision_id)
            visited.add(decision_id)

        for decision_id in candidate_ids:
            visit(decision_id)


__all__ = [
    "DomainIdentityContractError",
    "benchmark_definition_fingerprint",
    "canonical_json",
    "contract_self_digest",
    "evaluation_subject_observed_composition_fingerprint",
    "evaluation_subject_fingerprint",
    "identity_decision_item_fingerprint",
    "raw_identity_label_sha256",
    "validate_benchmark_definition_revision",
    "validate_benchmark_revision_chain",
    "validate_evaluation_subject",
    "validate_evaluation_subject_graph",
    "validate_evaluation_subject_revision_chain",
    "validate_identity_decision",
    "validate_identity_decision_chain",
    "verify_contract_self_digest",
]
