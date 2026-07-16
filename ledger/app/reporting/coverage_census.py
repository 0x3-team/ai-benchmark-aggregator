"""Deterministic, read-only census of coverage and quarantined legacy data.

The census is an operator report.  It does not certify a source, assess claim
publication decisions, repair registry rows, initialize or migrate a database,
or produce a frontend artifact.  Registry YAML input identity ignores
formatting, comments, mapping-key order, top-level row order, and alias order;
other arrays keep their configured order.  A legacy SQLite file remains bound
by its raw byte digest and is opened only with ``mode=ro``.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
from datetime import date
import hashlib
import html
import json
import math
from pathlib import Path
import re
import sqlite3
from typing import Any, Mapping, Sequence
from urllib.parse import quote, unquote

import yaml

from app.db.migrate import DatabaseMigrationError, inspect_database
from app.schemas.coverage_contracts import (
    CoverageContractError,
    validate_coverage_universe,
)


COVERAGE_CENSUS_SCHEMA_VERSION = "1.0.0"
COVERAGE_CENSUS_POLICY_VERSION = "coverage-census-v1"
COVERAGE_CENSUS_AVAILABILITY = "report_only"
CANONICAL_JSON_ALGORITHM = "sha256-canonical-json-v1"

_TOP_LEVEL_KEYS = frozenset(
    {
        "schemaVersion",
        "policyVersion",
        "availability",
        "readiness",
        "manifest",
        "universe",
        "inputs",
        "summary",
        "benchmarks",
        "sources",
        "models",
        "legacyDatabase",
        "issues",
    }
)
_DENOMINATOR_KEYS = frozenset(
    {
        "universeBenchmarkIdCount",
        "benchmarkRowCount",
        "benchmarkUniqueIdCount",
        "sourceRowCount",
        "sourceUniqueIdCount",
        "modelRowCount",
        "modelUniqueIdCount",
        "registryAliasRowCount",
        "legacyTableCount",
        "issueCount",
    }
)
_INPUT_KEYS = frozenset(
    {
        "inputId",
        "inputType",
        "relativePath",
        "contentSha256",
        "rowCount",
        "inspectionStatus",
        "reasonCode",
    }
)
_COMMON_ROW_KEYS = frozenset(
    {
        "rowKey",
        "inputId",
        "rowIndex",
        "stableId",
        "registryStatus",
        "coverageStatus",
        "reportDisposition",
        "reasonCode",
        "aliases",
    }
)
_ALIAS_ROW_KEYS = frozenset(
    {"rowKey", "aliasIndex", "aliasText", "reportDisposition", "reasonCode"}
)
_ISSUE_KEYS = frozenset(
    {
        "issueKey",
        "issueType",
        "entityType",
        "stableId",
        "matchKind",
        "matchKey",
        "entityIds",
        "rowKeys",
        "reasonCode",
        "blocking",
    }
)
_LEGACY_KEYS = frozenset(
    {
        "status",
        "kind",
        "path",
        "contentSha256",
        "schemaSha256",
        "reasonCode",
        "integrityOk",
        "foreignKeyViolationCount",
        "orphanedReferenceCount",
        "resultClaimQuarantineCount",
        "revision",
        "tableCounts",
        "sourceIds",
        "registrySourceIdsMissingFromDatabase",
        "databaseSourceIdsMissingFromRegistry",
        "aliasCollisions",
    }
)
_LEGACY_COLLISION_KEYS = frozenset(
    {"entityType", "matchKind", "matchKey", "entityIds", "reasonCode"}
)
_SUMMARY_KEYS = frozenset(
    {
        "reasonCounts",
        "statusCounts",
        "configuredActiveSourceCount",
        "certificationAssessmentStatus",
        "certifiedSourceCount",
        "publishedSourceCount",
        "universeSourceRouteCount",
        "resultClaimQuarantineCount",
    }
)
_COVERAGE_STATUS_KEYS = (
    "known",
    "watched",
    "candidate",
    "contract_ready",
    "certified",
    "captured",
    "reviewed",
    "published",
    "deferred",
    "terms_blocked",
    "unsupported",
)
_INPUT_TYPES = frozenset(
    {
        "coverage_universe",
        "benchmark_registry",
        "model_registry",
        "source_registry",
        "legacy_database",
    }
)
_INPUT_STATUSES = frozenset(
    {"loaded", "not_configured", "absent", "read_only", "blocked", "unsupported"}
)
_ROW_DISPOSITIONS = frozenset(
    {"configured", "omitted", "catalogued", "outside_universe", "conflicted", "invalid"}
)
_ALIAS_DISPOSITIONS = frozenset({"accounted", "invalid"})
_ISSUE_TYPES = frozenset(
    {
        "invalid_registry_row",
        "duplicate_registry_id",
        "registry_alias_collision",
        "universe_gap",
        "legacy_database",
        "legacy_alias_collision",
        "registry_database_divergence",
    }
)
_ENTITY_TYPES = frozenset({"benchmark", "model", "source", "database", "universe"})
_LEGACY_STATUSES = frozenset(
    {
        "absent",
        "current_read_only",
        "quarantined_read_only",
        "quarantined_invalid",
        "unavailable",
    }
)
_LEGACY_KINDS = frozenset(
    {
        "not_configured",
        "absent",
        "empty",
        "versioned",
        "legacy_unversioned",
        "unknown_schema",
        "invalid",
        "unsupported_url",
    }
)
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_STABLE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_REASON_RE = re.compile(r"^[A-Z][A-Z0-9_]{2,127}$")
_DURATION_RE = re.compile(
    r"^P(?!$)(?:[0-9]+D)?(?:T(?=[0-9])(?:[0-9]+H)?(?:[0-9]+M)?(?:[0-9]+S)?)?$"
)


class CoverageCensusError(ValueError):
    """The census input or report cannot be accounted for faithfully."""


class _UniqueKeyLoader(yaml.SafeLoader):
    """Safe YAML loader that refuses duplicate mapping keys."""


def _construct_unique_mapping(
    loader: _UniqueKeyLoader, node: yaml.nodes.MappingNode, deep: bool = False
) -> dict[object, object]:
    loader.flatten_mapping(node)
    result: dict[object, object] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in result
        except TypeError as exc:
            raise CoverageCensusError("YAML mapping keys must be scalar and hashable.") from exc
        if duplicate:
            raise CoverageCensusError(f"YAML contains a duplicate mapping key: {key!r}.")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_unique_mapping
)


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise CoverageCensusError(f"Value is not canonical JSON data: {exc}") from exc


def canonical_coverage_json(payload: Mapping[str, Any]) -> str:
    """Return the stable JSON representation used by the report digest."""
    return _canonical_json(payload)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalize_yaml_value(value: Any) -> Any:
    """Validate YAML as JSON-compatible data without changing array order."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise CoverageCensusError("YAML inputs cannot contain non-finite numbers.")
        return value
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise CoverageCensusError("YAML input mapping keys must be strings.")
            normalized[key] = _normalize_yaml_value(item)
        return normalized
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_normalize_yaml_value(item) for item in value]
    raise CoverageCensusError(f"YAML input contains an unsupported value type: {type(value).__name__}.")


def _registry_row_normalize(value: Any) -> Any:
    """Normalize one registry row, treating only its aliases as unordered."""
    normalized = _normalize_yaml_value(value)
    if isinstance(normalized, dict) and isinstance(normalized.get("aliases"), list):
        normalized["aliases"] = sorted(normalized["aliases"], key=_canonical_json)
    return normalized


def _registry_semantic_document(document: Mapping[str, Any], row_key: str) -> dict[str, Any]:
    """Return the contract-defined semantic representation of a registry file."""
    normalized = _normalize_yaml_value(document)
    if set(normalized) != {row_key}:
        raise CoverageCensusError(
            f"Registry input contains unexpected top-level fields; expected only {row_key}."
        )
    rows = normalized.get(row_key)
    if not isinstance(rows, list):
        raise CoverageCensusError(f"Registry input must contain a non-null {row_key} array.")
    semantic_rows = [_registry_row_normalize(row) for row in rows]

    def row_sort_key(row: Any) -> tuple[str, str]:
        stable_id = row.get("id") if isinstance(row, Mapping) else None
        return (_nonempty_exact_string(stable_id) or "", _canonical_json(row))

    normalized[row_key] = sorted(semantic_rows, key=row_sort_key)
    return normalized


def _registry_semantic_digest(document: Mapping[str, Any], row_key: str) -> str:
    semantic = _registry_semantic_document(document, row_key)
    return _sha256_text(_canonical_json(semantic[row_key]))


def _registry_rows_digest(rows: Sequence[Any]) -> str:
    semantic_rows = [_registry_row_normalize(row) for row in rows]

    def row_sort_key(row: Any) -> tuple[str, str]:
        stable_id = row.get("id") if isinstance(row, Mapping) else None
        return (_nonempty_exact_string(stable_id) or "", _canonical_json(row))

    return _sha256_text(_canonical_json(sorted(semantic_rows, key=row_sort_key)))


def _self_digest(document: Mapping[str, Any]) -> str:
    digest_input = deepcopy(dict(document))
    manifest = digest_input.get("manifest")
    if not isinstance(manifest, dict) or "contentSha256" not in manifest:
        raise CoverageCensusError("A self-digested document needs manifest.contentSha256.")
    manifest["contentSha256"] = None
    return _sha256_text(_canonical_json(_normalize_yaml_value(digest_input)))


def coverage_census_digest(payload: Mapping[str, Any]) -> str:
    """Compute the census self-digest, excluding only its digest slot."""
    digest_input = deepcopy(dict(payload))
    manifest = digest_input.get("manifest")
    if not isinstance(manifest, dict) or "contentSha256" not in manifest:
        raise CoverageCensusError("Coverage census needs manifest.contentSha256.")
    manifest["contentSha256"] = None
    return _sha256_text(_canonical_json(digest_input))


def _read_yaml(path: Path) -> Mapping[str, Any]:
    if not path.is_file():
        raise CoverageCensusError(f"Required YAML input is missing: {path.name}.")
    try:
        with path.open("r", encoding="utf-8") as stream:
            document = yaml.load(stream, Loader=_UniqueKeyLoader)
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise CoverageCensusError(f"Could not parse {path.name}: {exc}") from exc
    if not isinstance(document, Mapping):
        raise CoverageCensusError(f"{path.name} must contain a top-level mapping.")
    _normalize_yaml_value(document)
    return document


def _require_array(document: Mapping[str, Any], key: str, label: str) -> list[Any]:
    value = document.get(key)
    if not isinstance(value, list):
        raise CoverageCensusError(f"{label} must contain a non-null {key} array.")
    return value


def _nonempty_exact_string(value: object) -> str | None:
    if isinstance(value, str) and value and value == value.strip():
        return value
    return None


def _stable_id(value: object) -> str | None:
    exact = _nonempty_exact_string(value)
    return exact if exact is not None and _STABLE_ID_RE.fullmatch(exact) else None


def _normalize_alias_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _canonical_rows(rows: list[Any]) -> list[Any]:
    normalized = [_registry_row_normalize(row) for row in rows]

    def key(row: Any) -> tuple[str, str]:
        stable_id = row.get("id") if isinstance(row, Mapping) else None
        return (_nonempty_exact_string(stable_id) or "", _canonical_json(row))

    return sorted(normalized, key=key)


def _input_record(
    *,
    input_id: str,
    input_type: str,
    relative_path: str | None,
    content_sha256: str | None,
    row_count: int,
    inspection_status: str,
    reason_code: str,
) -> dict[str, Any]:
    return {
        "inputId": input_id,
        "inputType": input_type,
        "relativePath": relative_path,
        "contentSha256": content_sha256,
        "rowCount": row_count,
        "inspectionStatus": inspection_status,
        "reasonCode": reason_code,
    }


def _issue(
    issue_type: str,
    entity_type: str,
    reason_code: str,
    *,
    stable_id: str | None = None,
    match_kind: str | None = None,
    match_key: str | None = None,
    entity_ids: Sequence[str] = (),
    row_keys: Sequence[str] = (),
    blocking: bool = True,
) -> dict[str, Any]:
    core = {
        "issueType": issue_type,
        "entityType": entity_type,
        "stableId": stable_id,
        "matchKind": match_kind,
        "matchKey": match_key,
        "entityIds": sorted(set(entity_ids)),
        "rowKeys": sorted(set(row_keys)),
        "reasonCode": reason_code,
        "blocking": blocking,
    }
    return {"issueKey": _sha256_text(_canonical_json(core)), **core}


def _alias_rows(
    raw_aliases: object,
    *,
    row_key: str,
    entity_type: str,
    issues: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], bool]:
    if raw_aliases is None:
        return [], True
    if not isinstance(raw_aliases, list):
        issues.append(
            _issue(
                "invalid_registry_row",
                entity_type,
                "REGISTRY_ALIASES_NOT_ARRAY",
                row_keys=[row_key],
            )
        )
        return [], False
    aliases = sorted((_normalize_yaml_value(alias) for alias in raw_aliases), key=_canonical_json)
    records: list[dict[str, Any]] = []
    valid = True
    for alias_index, alias in enumerate(aliases):
        alias_key = f"{row_key}:alias:{alias_index}"
        alias_text = _nonempty_exact_string(alias)
        normalized = _normalize_alias_key(alias_text) if alias_text is not None else ""
        if alias_text is None or not normalized:
            valid = False
            records.append(
                {
                    "rowKey": alias_key,
                    "aliasIndex": alias_index,
                    "aliasText": None,
                    "reportDisposition": "invalid",
                    "reasonCode": "INVALID_REGISTRY_ALIAS",
                }
            )
            issues.append(
                _issue(
                    "invalid_registry_row",
                    entity_type,
                    "INVALID_REGISTRY_ALIAS",
                    row_keys=[alias_key],
                )
            )
        else:
            records.append(
                {
                    "rowKey": alias_key,
                    "aliasIndex": alias_index,
                    "aliasText": alias_text,
                    "reportDisposition": "accounted",
                    "reasonCode": "REGISTRY_ALIAS_ACCOUNTED",
                }
            )
    return records, valid


def _registry_rows(
    *,
    input_id: str,
    entity_type: str,
    rows: list[Any],
    issues: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for row_index, raw_row in enumerate(_canonical_rows(rows)):
        row_key = f"{input_id}:row:{row_index}"
        mapping = raw_row if isinstance(raw_row, Mapping) else None
        stable_id = _nonempty_exact_string(mapping.get("id")) if mapping is not None else None
        registry_status = (
            _nonempty_exact_string(mapping.get("status")) if mapping is not None else None
        )
        alias_records, aliases_valid = _alias_rows(
            mapping.get("aliases") if mapping is not None else None,
            row_key=row_key,
            entity_type=entity_type,
            issues=issues,
        )
        typed_stable_id = stable_id if entity_type == "model" else _stable_id(stable_id)
        valid = mapping is not None and typed_stable_id is not None and registry_status is not None
        reason_code = "REGISTRY_ROW_PENDING_COVERAGE_RECONCILIATION"
        disposition = "catalogued" if entity_type == "model" else "configured"
        if not valid or not aliases_valid:
            disposition = "invalid"
            if mapping is None:
                reason_code = "REGISTRY_ROW_NOT_MAPPING"
            elif typed_stable_id is None:
                reason_code = "INVALID_REGISTRY_ID"
            elif registry_status is None:
                reason_code = "INVALID_REGISTRY_STATUS"
            else:
                reason_code = "INVALID_REGISTRY_ALIASES"
            issues.append(
                _issue(
                    "invalid_registry_row",
                    entity_type,
                    reason_code,
                    stable_id=stable_id,
                    row_keys=[row_key],
                )
            )

        common = {
            "rowKey": row_key,
            "inputId": input_id,
            "rowIndex": row_index,
            "stableId": stable_id,
            "registryStatus": registry_status,
            "coverageStatus": None,
            "reportDisposition": disposition,
            "reasonCode": reason_code,
            "aliases": alias_records,
        }
        if entity_type == "benchmark":
            common["benchmarkId"] = typed_stable_id
        elif entity_type == "model":
            common["modelId"] = typed_stable_id
        else:
            benchmark_id = (
                _stable_id(mapping.get("benchmark_id")) if mapping is not None else None
            )
            common["sourceRouteId"] = typed_stable_id
            common["benchmarkId"] = benchmark_id
            if benchmark_id is None and disposition != "invalid":
                common["reportDisposition"] = "invalid"
                common["reasonCode"] = "INVALID_SOURCE_BENCHMARK_ID"
                issues.append(
                    _issue(
                        "invalid_registry_row",
                        "source",
                        "INVALID_SOURCE_BENCHMARK_ID",
                        stable_id=stable_id,
                        row_keys=[row_key],
                    )
                )
        records.append(common)
    return records


def _mark_duplicate_ids(
    rows: list[dict[str, Any]], entity_type: str, issues: list[dict[str, Any]]
) -> dict[str, list[dict[str, Any]]]:
    by_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        stable_id = row["stableId"]
        if stable_id is not None:
            by_id[stable_id].append(row)
    for stable_id, duplicate_rows in sorted(by_id.items()):
        if len(duplicate_rows) < 2:
            continue
        row_keys = [row["rowKey"] for row in duplicate_rows]
        issues.append(
            _issue(
                "duplicate_registry_id",
                entity_type,
                "DUPLICATE_REGISTRY_ID",
                stable_id=stable_id,
                entity_ids=[stable_id],
                row_keys=row_keys,
            )
        )
        for row in duplicate_rows:
            row["coverageStatus"] = None
            row["reportDisposition"] = "conflicted"
            row["reasonCode"] = "DUPLICATE_REGISTRY_ID"
    return by_id


def _alias_collision_records(
    rows: Sequence[Mapping[str, Any]], *, entity_type: str, issue_type: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    exact: dict[str, set[str]] = defaultdict(set)
    normalized: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        stable_id = row.get("stableId")
        if not isinstance(stable_id, str):
            continue
        for alias in row.get("aliases", []):
            if not isinstance(alias, Mapping) or alias.get("reportDisposition") != "accounted":
                continue
            alias_text = alias.get("aliasText")
            if not isinstance(alias_text, str):
                continue
            exact[alias_text].add(stable_id)
            normalized[_normalize_alias_key(alias_text)].add(stable_id)
    collisions: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    for match_kind, groups in (("exact", exact), ("normalized", normalized)):
        for match_key, entity_ids in sorted(groups.items()):
            if len(entity_ids) < 2:
                continue
            record = {
                "entityType": entity_type,
                "matchKind": match_kind,
                "matchKey": match_key,
                "entityIds": sorted(entity_ids),
                "reasonCode": "REGISTRY_ALIAS_COLLISION"
                if issue_type == "registry_alias_collision"
                else "LEGACY_ALIAS_COLLISION",
            }
            collisions.append(record)
            issues.append(
                _issue(
                    issue_type,
                    entity_type,
                    record["reasonCode"],
                    match_kind=match_kind,
                    match_key=match_key,
                    entity_ids=record["entityIds"],
                )
            )
    collisions.sort(key=lambda row: (row["entityType"], row["matchKind"], row["matchKey"]))
    return collisions, issues


def _load_universe(
    universe_path: Path,
) -> tuple[Mapping[str, Any], dict[str, Any], dict[str, list[Mapping[str, Any]]]]:
    document = _read_yaml(universe_path)
    try:
        validate_coverage_universe(document)
    except CoverageContractError as exc:
        raise CoverageCensusError(f"Coverage Universe semantic validation failed: {exc}") from exc
    required_top_level = {
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
    if set(document) != required_top_level:
        raise CoverageCensusError("Coverage Universe top-level fields do not match v1.")
    if (
        document.get("schemaVersion") != "1.0.0"
        or document.get("policyVersion") != "coverage-universe-v1"
        or document.get("availability") != "coverage_definition_only"
    ):
        raise CoverageCensusError("Coverage Universe v1 identity is invalid.")
    revision_id = _stable_id(document.get("universeRevisionId"))
    if revision_id is None:
        raise CoverageCensusError("Coverage Universe needs a stable universeRevisionId.")
    manifest = document.get("manifest")
    if not isinstance(manifest, Mapping):
        raise CoverageCensusError("Coverage Universe needs a manifest mapping.")
    content_sha256 = manifest.get("contentSha256")
    if not isinstance(content_sha256, str) or not _DIGEST_RE.fullmatch(content_sha256):
        raise CoverageCensusError("Coverage Universe manifest digest is missing or malformed.")
    if _self_digest(document) != content_sha256:
        raise CoverageCensusError("Coverage Universe manifest digest does not match its content.")

    def exact_fields(value: object, fields: set[str], label: str) -> Mapping[str, Any]:
        if not isinstance(value, Mapping) or set(value) != fields:
            raise CoverageCensusError(f"Coverage Universe {label} fields are invalid.")
        return value

    def exact_text(value: object, label: str) -> str:
        text = _nonempty_exact_string(value)
        if text is None:
            raise CoverageCensusError(f"Coverage Universe {label} must be a nonempty exact string.")
        return text

    def exact_date(value: object, label: str) -> str:
        text = exact_text(value, label)
        try:
            parsed = date.fromisoformat(text)
        except ValueError as exc:
            raise CoverageCensusError(f"Coverage Universe {label} must be an ISO date.") from exc
        if parsed.isoformat() != text:
            raise CoverageCensusError(f"Coverage Universe {label} must be a canonical ISO date.")
        return text

    authority = document.get("authority")
    required_authority = {
        "classification",
        "approvalStatus",
        "certifiesSources",
        "authorizesCapture",
        "authorizesPublication",
        "frontendLoadable",
    }
    authority = exact_fields(authority, required_authority, "authority")
    if authority.get("classification") != "coverage_definition_only" or any(
        authority.get(key) is not False
        for key in (
            "certifiesSources",
            "authorizesCapture",
            "authorizesPublication",
            "frontendLoadable",
        )
    ):
        raise CoverageCensusError("Coverage Universe cannot grant source or publication authority.")
    approval_status = authority.get("approvalStatus")
    if approval_status == "draft_unapproved":
        if document.get("effectiveOn") is not None or document.get("decisionReference") is not None:
            raise CoverageCensusError("Draft Coverage Universe cannot bind an effective decision.")
    elif approval_status == "owner_approved":
        exact_date(document.get("effectiveOn"), "effectiveOn")
        if _stable_id(document.get("decisionReference")) is None:
            raise CoverageCensusError("Owner-approved Coverage Universe needs a decision reference.")
    else:
        raise CoverageCensusError("Coverage Universe approvalStatus is invalid.")

    supersedes = document.get("supersedesUniverseRevisionId")
    if supersedes is not None and _stable_id(supersedes) is None:
        raise CoverageCensusError("Coverage Universe supersedes reference is invalid.")

    manifest = exact_fields(
        manifest,
        {
            "algorithm",
            "contentSha256",
            "benchmarkCount",
            "configuredSourceRouteCount",
            "sourceClassCount",
            "exclusionCount",
        },
        "manifest",
    )
    scope = exact_fields(
        document.get("scope"),
        {"name", "boundedStatement", "internetComplete", "registryInputs"},
        "scope",
    )
    exact_text(scope.get("name"), "scope.name")
    exact_text(scope.get("boundedStatement"), "scope.boundedStatement")
    if scope.get("internetComplete") is not False:
        raise CoverageCensusError("Coverage Universe must remain explicitly bounded.")
    registry_pins = scope.get("registryInputs")
    if not isinstance(registry_pins, list) or not registry_pins:
        raise CoverageCensusError("Coverage Universe registryInputs are invalid.")
    pin_identities: set[str] = set()
    for pin in registry_pins:
        pin = exact_fields(
            pin,
            {"inputPath", "recordType", "selectionRule", "expectedUniqueCount", "semanticSha256"},
            "registry input",
        )
        input_path = exact_text(pin.get("inputPath"), "registry inputPath")
        record_type = pin.get("recordType")
        if record_type not in {"benchmark", "configured_source_route"}:
            raise CoverageCensusError("Coverage Universe registry recordType is invalid.")
        if pin.get("selectionRule") != "all_unique_stable_ids":
            raise CoverageCensusError("Coverage Universe registry selectionRule is invalid.")
        expected_count = pin.get("expectedUniqueCount")
        if not isinstance(expected_count, int) or isinstance(expected_count, bool) or expected_count < 0:
            raise CoverageCensusError("Coverage Universe registry expectedUniqueCount is invalid.")
        semantic_digest = pin.get("semanticSha256")
        if not isinstance(semantic_digest, str) or not _DIGEST_RE.fullmatch(semantic_digest):
            raise CoverageCensusError("Coverage Universe registry semanticSha256 is invalid.")
        pin_identity = f"{record_type}\0{input_path}"
        if pin_identity in pin_identities:
            raise CoverageCensusError("Coverage Universe registry inputs must be unique.")
        pin_identities.add(pin_identity)

    benchmarks = _require_array(document, "benchmarks", "Coverage Universe")
    source_routes = _require_array(
        document, "configuredSourceRoutes", "Coverage Universe"
    )
    cohorts = _require_array(document, "cohorts", "Coverage Universe")
    source_classes = _require_array(document, "sourceClasses", "Coverage Universe")
    exclusions = _require_array(document, "exclusions", "Coverage Universe")
    parsed: dict[str, list[Mapping[str, Any]]] = {"benchmarks": [], "sources": []}
    benchmark_ids: list[str] = []
    for item in benchmarks:
        item = exact_fields(
            item,
            {"benchmarkId", "coverageStatus", "reasonCode", "cohortIds"},
            "benchmark",
        )
        if _stable_id(item.get("benchmarkId")) is None:
            raise CoverageCensusError("Coverage Universe benchmark entries need benchmarkId.")
        if item.get("coverageStatus") not in {"configured", "omitted"}:
            raise CoverageCensusError("Coverage Universe benchmark has invalid coverageStatus.")
        if not isinstance(item.get("reasonCode"), str) or not _REASON_RE.fullmatch(item["reasonCode"]):
            raise CoverageCensusError("Coverage Universe benchmark needs reasonCode.")
        cohort_ids = item.get("cohortIds")
        if (
            not isinstance(cohort_ids, list)
            or not cohort_ids
            or any(_stable_id(value) is None for value in cohort_ids)
            or len(set(cohort_ids)) != len(cohort_ids)
        ):
            raise CoverageCensusError("Coverage Universe benchmark cohortIds are invalid.")
        benchmark_ids.append(str(item["benchmarkId"]))
        parsed["benchmarks"].append(item)
    if len(set(benchmark_ids)) != len(benchmark_ids):
        raise CoverageCensusError("Coverage Universe benchmark IDs must be unique.")

    cohort_members: dict[str, set[str]] = {}
    for item in cohorts:
        item = exact_fields(
            item,
            {"cohortId", "name", "purpose", "memberBenchmarkIds"},
            "cohort",
        )
        if _stable_id(item.get("cohortId")) is None:
            raise CoverageCensusError("Coverage Universe cohort entries are invalid.")
        exact_text(item.get("name"), "cohort.name")
        exact_text(item.get("purpose"), "cohort.purpose")
        cohort_id = str(item["cohortId"])
        member_ids = item.get("memberBenchmarkIds")
        if (
            not isinstance(member_ids, list)
            or not member_ids
            or any(_stable_id(value) is None for value in member_ids)
            or len(set(member_ids)) != len(member_ids)
        ):
            raise CoverageCensusError("Coverage Universe cohort members are invalid.")
        if cohort_id in cohort_members:
            raise CoverageCensusError("Coverage Universe cohort IDs must be unique.")
        cohort_members[cohort_id] = set(member_ids)
    benchmark_id_set = set(benchmark_ids)
    if any(not members <= benchmark_id_set for members in cohort_members.values()):
        raise CoverageCensusError("Coverage Universe cohort references an unknown benchmark.")
    for benchmark in benchmarks:
        benchmark_id = str(benchmark["benchmarkId"])
        declared_cohorts = set(benchmark["cohortIds"])
        if not declared_cohorts <= set(cohort_members):
            raise CoverageCensusError("Coverage Universe benchmark references an unknown cohort.")
        actual_cohorts = {
            cohort_id for cohort_id, members in cohort_members.items() if benchmark_id in members
        }
        if declared_cohorts != actual_cohorts:
            raise CoverageCensusError("Coverage Universe cohort membership must be bidirectional.")

    source_ids: list[str] = []
    for item in source_routes:
        item = exact_fields(
            item,
            {"sourceRouteId", "benchmarkId", "registryStatus", "coverageStatus", "reasonCode"},
            "source route",
        )
        if any(
            (_stable_id(item.get(key)) if key in {"sourceRouteId", "benchmarkId"} else _nonempty_exact_string(item.get(key))) is None
            for key in ("sourceRouteId", "benchmarkId", "registryStatus", "reasonCode")
        ):
            raise CoverageCensusError("Coverage Universe source entries need stable references.")
        if item.get("coverageStatus") not in {"configured", "omitted"}:
            raise CoverageCensusError("Coverage Universe source has invalid coverageStatus.")
        if not isinstance(item.get("reasonCode"), str) or not _REASON_RE.fullmatch(item["reasonCode"]):
            raise CoverageCensusError("Coverage Universe source needs reasonCode.")
        if item["benchmarkId"] not in benchmark_id_set:
            raise CoverageCensusError("Coverage Universe source references an unknown benchmark.")
        source_ids.append(str(item["sourceRouteId"]))
        parsed["sources"].append(item)
    if len(set(source_ids)) != len(source_ids):
        raise CoverageCensusError("Coverage Universe source route IDs must be unique.")

    source_class_ids: list[str] = []
    priorities: list[int] = []
    for item in source_classes:
        item = exact_fields(
            item,
            {
                "sourceClassId",
                "priority",
                "methodFamily",
                "candidateUse",
                "discoveryOnly",
                "captureRequiresSeparateCertification",
                "publicationRequiresSeparateDecision",
            },
            "source class",
        )
        if _stable_id(item.get("sourceClassId")) is None:
            raise CoverageCensusError("Coverage Universe source class entries are invalid.")
        exact_text(item.get("methodFamily"), "sourceClass.methodFamily")
        exact_text(item.get("candidateUse"), "sourceClass.candidateUse")
        if not isinstance(item.get("discoveryOnly"), bool):
            raise CoverageCensusError("Coverage Universe sourceClass.discoveryOnly is invalid.")
        priority = item.get("priority")
        if not isinstance(priority, int) or isinstance(priority, bool) or priority < 1:
            raise CoverageCensusError("Coverage Universe source class priority is invalid.")
        if (
            item.get("captureRequiresSeparateCertification") is not True
            or item.get("publicationRequiresSeparateDecision") is not True
        ):
            raise CoverageCensusError("Coverage Universe source classes cannot bypass governance.")
        source_class_ids.append(str(item["sourceClassId"]))
        priorities.append(priority)
    if len(set(source_class_ids)) != len(source_class_ids):
        raise CoverageCensusError("Coverage Universe source class IDs must be unique.")
    if sorted(priorities) != list(range(1, len(priorities) + 1)):
        raise CoverageCensusError("Coverage Universe source class priorities must be contiguous.")

    exclusion_ids: list[str] = []
    for item in exclusions:
        item = exact_fields(
            item,
            {
                "exclusionId",
                "excludedClass",
                "reasonCode",
                "rationale",
                "reconsiderationPolicy",
                "ownerRole",
                "reviewDueOn",
            },
            "exclusion",
        )
        if _stable_id(item.get("exclusionId")) is None:
            raise CoverageCensusError("Coverage Universe exclusion entries are invalid.")
        if _stable_id(item.get("excludedClass")) is None or _stable_id(item.get("ownerRole")) is None:
            raise CoverageCensusError("Coverage Universe exclusion classifications are invalid.")
        if not isinstance(item.get("reasonCode"), str) or not _REASON_RE.fullmatch(item["reasonCode"]):
            raise CoverageCensusError("Coverage Universe exclusion needs reasonCode.")
        exact_text(item.get("rationale"), "exclusion.rationale")
        exact_text(item.get("reconsiderationPolicy"), "exclusion.reconsiderationPolicy")
        exact_date(item.get("reviewDueOn"), "exclusion.reviewDueOn")
        exclusion_ids.append(str(item["exclusionId"]))
    if len(set(exclusion_ids)) != len(exclusion_ids):
        raise CoverageCensusError("Coverage Universe exclusion IDs must be unique.")

    expected_manifest_counts = {
        "benchmarkCount": len(benchmarks),
        "configuredSourceRouteCount": len(source_routes),
        "sourceClassCount": len(source_classes),
        "exclusionCount": len(exclusions),
    }
    if manifest.get("algorithm") != CANONICAL_JSON_ALGORITHM or any(
        manifest.get(key) != value for key, value in expected_manifest_counts.items()
    ):
        raise CoverageCensusError("Coverage Universe manifest counts do not reconcile.")

    refresh = exact_fields(
        document.get("refreshPolicy"),
        {
            "discoveryPlanningCadence",
            "registryReconciliationCadence",
            "coverageOwnerReviewCadence",
            "stalenessThreshold",
            "termsReviewPolicy",
            "sourceRecheckAuthority",
        },
        "refreshPolicy",
    )
    for field in (
        "discoveryPlanningCadence",
        "registryReconciliationCadence",
        "coverageOwnerReviewCadence",
        "stalenessThreshold",
    ):
        value = refresh.get(field)
        if not isinstance(value, str) or not _DURATION_RE.fullmatch(value):
            raise CoverageCensusError(f"Coverage Universe refreshPolicy.{field} is invalid.")
    exact_text(refresh.get("termsReviewPolicy"), "refreshPolicy.termsReviewPolicy")
    if refresh.get("sourceRecheckAuthority") != "separate_certified_source_contract_only":
        raise CoverageCensusError("Coverage Universe source recheck authority is invalid.")

    public_wording = exact_fields(
        document.get("publicWording"),
        {"coverageLabel", "scopeStatement", "requiredDisclaimer", "forbiddenClaims"},
        "publicWording",
    )
    for field in ("coverageLabel", "scopeStatement", "requiredDisclaimer"):
        exact_text(public_wording.get(field), f"publicWording.{field}")
    forbidden_claims = public_wording.get("forbiddenClaims")
    if (
        not isinstance(forbidden_claims, list)
        or not forbidden_claims
        or any(_nonempty_exact_string(value) is None for value in forbidden_claims)
        or len(set(forbidden_claims)) != len(forbidden_claims)
    ):
        raise CoverageCensusError("Coverage Universe forbiddenClaims are invalid.")

    input_record = _input_record(
        input_id="coverage_universe",
        input_type="coverage_universe",
        relative_path=universe_path.name,
        content_sha256=content_sha256,
        row_count=len(benchmarks) + len(source_routes),
        inspection_status="loaded",
        reason_code="SEMANTIC_INPUT_LOADED",
    )
    return document, input_record, parsed


def _reconcile_universe(
    *,
    universe_items: dict[str, list[Mapping[str, Any]]],
    benchmark_rows: list[dict[str, Any]],
    source_rows: list[dict[str, Any]],
    benchmark_by_id: dict[str, list[dict[str, Any]]],
    source_by_id: dict[str, list[dict[str, Any]]],
    issues: list[dict[str, Any]],
) -> tuple[int, int]:
    universe_benchmarks: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    universe_sources: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for item in universe_items["benchmarks"]:
        universe_benchmarks[str(item["benchmarkId"])].append(item)
    for item in universe_items["sources"]:
        universe_sources[str(item["sourceRouteId"])].append(item)

    for entity_type, groups in (("benchmark", universe_benchmarks), ("source", universe_sources)):
        for stable_id, items in sorted(groups.items()):
            if len(items) > 1:
                issues.append(
                    _issue(
                        "universe_gap",
                        "universe",
                        "DUPLICATE_UNIVERSE_ID",
                        stable_id=stable_id,
                        entity_ids=[stable_id],
                    )
                )

    for row in benchmark_rows:
        stable_id = row["stableId"]
        if row["reportDisposition"] in {"invalid", "conflicted"} or stable_id is None:
            continue
        items = universe_benchmarks.get(stable_id, [])
        if not items:
            row["reportDisposition"] = "outside_universe"
            row["reasonCode"] = "REGISTRY_BENCHMARK_OUTSIDE_UNIVERSE"
            issues.append(
                _issue(
                    "universe_gap",
                    "benchmark",
                    row["reasonCode"],
                    stable_id=stable_id,
                    row_keys=[row["rowKey"]],
                )
            )
        elif len(items) == 1:
            row["coverageStatus"] = items[0]["coverageStatus"]
            row["reportDisposition"] = items[0]["coverageStatus"]
            row["reasonCode"] = items[0]["reasonCode"]
        else:
            row["reportDisposition"] = "conflicted"
            row["reasonCode"] = "DUPLICATE_UNIVERSE_ID"

    valid_benchmark_ids = {
        stable_id
        for stable_id, registry_rows in benchmark_by_id.items()
        if len(registry_rows) == 1
        and registry_rows[0]["reportDisposition"] not in {"invalid", "conflicted"}
        and len(universe_benchmarks.get(stable_id, [])) == 1
    }
    for row in source_rows:
        stable_id = row["stableId"]
        benchmark_id = row["benchmarkId"]
        if row["reportDisposition"] in {"invalid", "conflicted"} or stable_id is None:
            continue
        if benchmark_id not in valid_benchmark_ids:
            row["reportDisposition"] = "conflicted"
            row["reasonCode"] = (
                "SOURCE_REFERENCES_BENCHMARK_OUTSIDE_UNIVERSE"
                if benchmark_id in benchmark_by_id
                else "SOURCE_REFERENCES_UNKNOWN_BENCHMARK"
            )
            issues.append(
                _issue(
                    "universe_gap",
                    "source",
                    row["reasonCode"],
                    stable_id=stable_id,
                    row_keys=[row["rowKey"]],
                )
            )
            continue
        items = universe_sources.get(stable_id, [])
        if not items:
            row["reportDisposition"] = "outside_universe"
            row["reasonCode"] = "REGISTRY_SOURCE_OUTSIDE_UNIVERSE"
            issues.append(
                _issue(
                    "universe_gap",
                    "source",
                    row["reasonCode"],
                    stable_id=stable_id,
                    row_keys=[row["rowKey"]],
                )
            )
        elif len(items) == 1:
            item = items[0]
            if item["benchmarkId"] != benchmark_id:
                row["reportDisposition"] = "conflicted"
                row["reasonCode"] = "SOURCE_BENCHMARK_REFERENCE_MISMATCH"
                issues.append(
                    _issue(
                        "universe_gap",
                        "source",
                        row["reasonCode"],
                        stable_id=stable_id,
                        row_keys=[row["rowKey"]],
                    )
                )
            elif item["registryStatus"] != row["registryStatus"]:
                row["reportDisposition"] = "conflicted"
                row["reasonCode"] = "SOURCE_REGISTRY_STATUS_MISMATCH"
                issues.append(
                    _issue(
                        "universe_gap",
                        "source",
                        row["reasonCode"],
                        stable_id=stable_id,
                        row_keys=[row["rowKey"]],
                    )
                )
            else:
                row["coverageStatus"] = item["coverageStatus"]
                row["reportDisposition"] = item["coverageStatus"]
                row["reasonCode"] = item["reasonCode"]
        else:
            row["reportDisposition"] = "conflicted"
            row["reasonCode"] = "DUPLICATE_UNIVERSE_ID"

    for stable_id in sorted(universe_benchmarks):
        if stable_id not in benchmark_by_id:
            issues.append(
                _issue(
                    "universe_gap",
                    "benchmark",
                    "UNIVERSE_BENCHMARK_MISSING_REGISTRY_ROW",
                    stable_id=stable_id,
                )
            )
    for stable_id in sorted(universe_sources):
        if stable_id not in source_by_id:
            issues.append(
                _issue(
                    "universe_gap",
                    "source",
                    "UNIVERSE_SOURCE_MISSING_REGISTRY_ROW",
                    stable_id=stable_id,
                )
            )
    return len(universe_benchmarks), len(universe_sources)


def _sqlite_path(database_url: str) -> Path:
    if database_url == "sqlite:///:memory:" or database_url.endswith(":memory:"):
        raise CoverageCensusError("In-memory SQLite cannot be inspected as durable legacy evidence.")
    if not database_url.startswith("sqlite:///"):
        raise CoverageCensusError("Only a file-backed SQLite URL can be inspected read-only.")
    raw_path = unquote(database_url[len("sqlite:///") :].split("?", 1)[0])
    if not raw_path:
        raise CoverageCensusError("SQLite database URL does not contain a file path.")
    return Path(raw_path).expanduser().resolve()


def _quoted_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _legacy_shape(
    *,
    status: str,
    kind: str,
    path: str,
    content_sha256: str | None,
    schema_sha256: str | None = None,
    reason_code: str,
    integrity_ok: bool | None = None,
    foreign_key_violation_count: int = 0,
    orphaned_reference_count: int = 0,
    result_claim_quarantine_count: int = 0,
    revision: str | None = None,
    table_counts: Mapping[str, int] | None = None,
    source_ids: Sequence[str] = (),
    registry_missing: Sequence[str] = (),
    database_missing: Sequence[str] = (),
    alias_collisions: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    return {
        "status": status,
        "kind": kind,
        "path": path,
        "contentSha256": content_sha256,
        "schemaSha256": schema_sha256,
        "reasonCode": reason_code,
        "integrityOk": integrity_ok,
        "foreignKeyViolationCount": foreign_key_violation_count,
        "orphanedReferenceCount": orphaned_reference_count,
        "resultClaimQuarantineCount": result_claim_quarantine_count,
        "revision": revision,
        "tableCounts": dict(sorted((table_counts or {}).items())),
        "sourceIds": sorted(set(source_ids)),
        "registrySourceIdsMissingFromDatabase": sorted(set(registry_missing)),
        "databaseSourceIdsMissingFromRegistry": sorted(set(database_missing)),
        "aliasCollisions": sorted(
            (dict(row) for row in alias_collisions),
            key=lambda row: (row["entityType"], row["matchKind"], row["matchKey"]),
        ),
    }


def _legacy_alias_collisions(
    connection: sqlite3.Connection,
    tables: set[str],
    issues: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if "aliases" not in tables:
        return []
    columns = {
        str(row[1])
        for row in connection.execute(f"PRAGMA table_info({_quoted_identifier('aliases')})")
    }
    required = {"entity_type", "entity_id", "alias_text"}
    if not required <= columns:
        issues.append(
            _issue(
                "legacy_database",
                "database",
                "LEGACY_ALIAS_TABLE_UNSUPPORTED",
            )
        )
        return []

    exact: dict[tuple[str, str], set[str]] = defaultdict(set)
    normalized: dict[tuple[str, str], set[str]] = defaultdict(set)
    invalid_count = 0
    entity_type_map = {
        "benchmark": "benchmark",
        "model": "model",
        "model_entity": "model",
        "source": "source",
        "official_source": "source",
    }
    query = (
        f"SELECT entity_type, entity_id, alias_text FROM {_quoted_identifier('aliases')} "
        "ORDER BY entity_type, entity_id, alias_text"
    )
    for raw_entity_type, raw_entity_id, raw_alias in connection.execute(query):
        entity_type = entity_type_map.get(raw_entity_type) if isinstance(raw_entity_type, str) else None
        entity_id = _nonempty_exact_string(raw_entity_id)
        alias_text = _nonempty_exact_string(raw_alias)
        normalized_alias = _normalize_alias_key(alias_text) if alias_text is not None else ""
        if entity_type is None or entity_id is None or alias_text is None or not normalized_alias:
            invalid_count += 1
            continue
        exact[(entity_type, alias_text)].add(entity_id)
        normalized[(entity_type, normalized_alias)].add(entity_id)
    if invalid_count:
        issues.append(
            _issue(
                "legacy_database",
                "database",
                "LEGACY_ALIAS_ROWS_INVALID",
            )
        )

    collisions: list[dict[str, Any]] = []
    for match_kind, groups in (("exact", exact), ("normalized", normalized)):
        for (entity_type, match_key), entity_ids in sorted(groups.items()):
            if len(entity_ids) < 2:
                continue
            record = {
                "entityType": entity_type,
                "matchKind": match_kind,
                "matchKey": match_key,
                "entityIds": sorted(entity_ids),
                "reasonCode": "LEGACY_ALIAS_COLLISION",
            }
            collisions.append(record)
            issues.append(
                _issue(
                    "legacy_alias_collision",
                    entity_type,
                    "LEGACY_ALIAS_COLLISION",
                    match_kind=match_kind,
                    match_key=match_key,
                    entity_ids=record["entityIds"],
                )
            )
    return collisions


def _inspect_legacy_database(
    database_url: str | None,
    *,
    registry_source_ids: set[str],
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    issues: list[dict[str, Any]] = []
    if database_url is None or not database_url.strip():
        legacy = _legacy_shape(
            status="absent",
            kind="not_configured",
            path="not-configured",
            content_sha256=None,
            reason_code="LEGACY_DATABASE_NOT_CONFIGURED",
        )
        return legacy, _input_record(
            input_id="legacy_database",
            input_type="legacy_database",
            relative_path="not-configured",
            content_sha256=None,
            row_count=0,
            inspection_status="not_configured",
            reason_code="LEGACY_DATABASE_NOT_CONFIGURED",
        ), issues

    try:
        path = _sqlite_path(database_url)
    except CoverageCensusError:
        reason = "LEGACY_DATABASE_URL_UNSUPPORTED"
        legacy = _legacy_shape(
            status="unavailable",
            kind="unsupported_url",
            path="unsupported-database-url",
            content_sha256=None,
            reason_code=reason,
        )
        issues.append(_issue("legacy_database", "database", reason))
        return legacy, _input_record(
            input_id="legacy_database",
            input_type="legacy_database",
            relative_path="unsupported-database-url",
            content_sha256=None,
            row_count=0,
            inspection_status="unsupported",
            reason_code=reason,
        ), issues

    report_path = path.name or "legacy-database.sqlite"
    if not path.exists():
        reason = "LEGACY_DATABASE_ABSENT"
        legacy = _legacy_shape(
            status="absent",
            kind="absent",
            path=report_path,
            content_sha256=None,
            reason_code=reason,
        )
        issues.append(_issue("legacy_database", "database", reason))
        return legacy, _input_record(
            input_id="legacy_database",
            input_type="legacy_database",
            relative_path=report_path,
            content_sha256=None,
            row_count=0,
            inspection_status="blocked",
            reason_code=reason,
        ), issues
    if not path.is_file():
        reason = "LEGACY_DATABASE_NOT_A_FILE"
        legacy = _legacy_shape(
            status="unavailable",
            kind="invalid",
            path=report_path,
            content_sha256=None,
            reason_code=reason,
        )
        issues.append(_issue("legacy_database", "database", reason))
        return legacy, _input_record(
            input_id="legacy_database",
            input_type="legacy_database",
            relative_path=report_path,
            content_sha256=None,
            row_count=0,
            inspection_status="blocked",
            reason_code=reason,
        ), issues

    try:
        raw_digest = _sha256_file(path)
    except OSError:
        reason = "LEGACY_DATABASE_UNREADABLE"
        legacy = _legacy_shape(
            status="unavailable",
            kind="invalid",
            path=report_path,
            content_sha256=None,
            reason_code=reason,
        )
        issues.append(_issue("legacy_database", "database", reason))
        return legacy, _input_record(
            input_id="legacy_database",
            input_type="legacy_database",
            relative_path=report_path,
            content_sha256=None,
            row_count=0,
            inspection_status="blocked",
            reason_code=reason,
        ), issues

    sidecars = [Path(f"{path}{suffix}") for suffix in ("-wal", "-shm", "-journal")]
    if any(sidecar.exists() for sidecar in sidecars):
        reason = "LEGACY_DATABASE_SIDECAR_STATE_UNSUPPORTED"
        legacy = _legacy_shape(
            status="quarantined_invalid",
            kind="invalid",
            path=report_path,
            content_sha256=raw_digest,
            reason_code=reason,
        )
        issues.append(_issue("legacy_database", "database", reason))
        return legacy, _input_record(
            input_id="legacy_database",
            input_type="legacy_database",
            relative_path=report_path,
            content_sha256=raw_digest,
            row_count=0,
            inspection_status="blocked",
            reason_code=reason,
        ), issues

    try:
        before_stat = path.stat()
    except OSError:
        reason = "LEGACY_DATABASE_UNREADABLE"
        legacy = _legacy_shape(
            status="unavailable",
            kind="invalid",
            path=report_path,
            content_sha256=None,
            reason_code=reason,
        )
        issues.append(_issue("legacy_database", "database", reason))
        return legacy, _input_record(
            input_id="legacy_database",
            input_type="legacy_database",
            relative_path=report_path,
            content_sha256=None,
            row_count=0,
            inspection_status="blocked",
            reason_code=reason,
        ), issues
    before_identity = (
        before_stat.st_dev,
        before_stat.st_ino,
        before_stat.st_size,
        before_stat.st_mtime_ns,
    )
    try:
        migration_status = inspect_database(database_url)
    except (DatabaseMigrationError, OSError, ValueError):
        reason = "LEGACY_DATABASE_PREFLIGHT_UNAVAILABLE"
        issues.append(_issue("legacy_database", "database", reason))
        legacy = _legacy_shape(
            status="quarantined_invalid",
            kind="invalid",
            path=report_path,
            content_sha256=raw_digest,
            reason_code=reason,
        )
        return legacy, _input_record(
            input_id="legacy_database",
            input_type="legacy_database",
            relative_path=report_path,
            content_sha256=raw_digest,
            row_count=0,
            inspection_status="blocked",
            reason_code=reason,
        ), issues
    migration_kind_map = {
        "empty": "empty",
        "current": "versioned",
        "versioned_but_not_head": "versioned",
        "legacy_unversioned": "legacy_unversioned",
        "unsupported": "unknown_schema",
        "invalid": "invalid",
    }
    migration_kind = migration_kind_map.get(migration_status.kind, "invalid")

    table_counts: dict[str, int] = {}
    source_ids: list[str] = []
    alias_collisions: list[dict[str, Any]] = []
    revision: str | None = None
    integrity_ok: bool | None = None
    foreign_key_violations: list[tuple[Any, ...]] = []
    kind = migration_kind
    reason = "LEGACY_DATABASE_INVALID"
    schema_digest: str | None = None
    claim_count = 0
    orphaned_reference_count = 0
    try:
        uri = f"file:{quote(str(path))}?mode=ro"
        with sqlite3.connect(uri, uri=True) as connection:
            connection.execute("PRAGMA query_only=ON")
            schema_rows = connection.execute(
                """
                SELECT type, name, tbl_name, sql
                FROM sqlite_master
                WHERE name NOT LIKE 'sqlite_%'
                ORDER BY type, name
                """
            ).fetchall()
            schema_record = [
                {"type": row[0], "name": row[1], "tableName": row[2], "sql": row[3]}
                for row in schema_rows
            ]
            schema_digest = _sha256_text(_canonical_json(schema_record))
            tables = {
                str(row[1]) for row in schema_rows if row[0] == "table" and isinstance(row[1], str)
            }
            for table in sorted(tables):
                count = connection.execute(
                    f"SELECT COUNT(*) FROM {_quoted_identifier(table)}"
                ).fetchone()
                if count is None or not isinstance(count[0], int) or count[0] < 0:
                    raise sqlite3.DatabaseError("invalid table row count")
                table_counts[table] = count[0]

            integrity_rows = connection.execute("PRAGMA integrity_check").fetchall()
            integrity_ok = integrity_rows == [("ok",)]
            foreign_key_violations = connection.execute("PRAGMA foreign_key_check").fetchall()

            if "alembic_version" in tables:
                revision_rows = connection.execute(
                    f"SELECT version_num FROM {_quoted_identifier('alembic_version')}"
                ).fetchall()
                if len(revision_rows) == 1 and _nonempty_exact_string(revision_rows[0][0]):
                    revision = revision_rows[0][0]

            if "official_sources" in tables:
                columns = {
                    str(row[1])
                    for row in connection.execute(
                        f"PRAGMA table_info({_quoted_identifier('official_sources')})"
                    )
                }
                if "id" not in columns:
                    issues.append(
                        _issue(
                            "legacy_database",
                            "database",
                            "LEGACY_SOURCE_TABLE_UNSUPPORTED",
                        )
                    )
                else:
                    invalid_source_ids = False
                    for (value,) in connection.execute(
                        f"SELECT id FROM {_quoted_identifier('official_sources')} ORDER BY id"
                    ):
                        source_id = _nonempty_exact_string(value)
                        if source_id is None:
                            invalid_source_ids = True
                        else:
                            source_ids.append(source_id)
                    if invalid_source_ids:
                        issues.append(
                            _issue(
                                "legacy_database",
                                "database",
                                "LEGACY_SOURCE_IDS_INVALID",
                            )
                        )

            if "result_claims" in tables:
                claim_count = table_counts["result_claims"]
            if {"claim_validations", "result_claims"} <= tables:
                validation_columns = {
                    str(row[1])
                    for row in connection.execute(
                        f"PRAGMA table_info({_quoted_identifier('claim_validations')})"
                    )
                }
                claim_columns = {
                    str(row[1])
                    for row in connection.execute(
                        f"PRAGMA table_info({_quoted_identifier('result_claims')})"
                    )
                }
                if "result_claim_id" in validation_columns and "id" in claim_columns:
                    orphan_row = connection.execute(
                        """
                        SELECT COUNT(*)
                        FROM claim_validations AS validation
                        LEFT JOIN result_claims AS claim
                          ON claim.id = validation.result_claim_id
                        WHERE validation.result_claim_id IS NOT NULL
                          AND claim.id IS NULL
                        """
                    ).fetchone()
                    if orphan_row is None or not isinstance(orphan_row[0], int):
                        raise sqlite3.DatabaseError("invalid orphan row count")
                    orphaned_reference_count = orphan_row[0]
            alias_collisions = _legacy_alias_collisions(connection, tables, issues)
    except (OSError, sqlite3.DatabaseError, UnicodeError):
        reason = "LEGACY_DATABASE_INVALID"
        issues.append(_issue("legacy_database", "database", reason))
        legacy = _legacy_shape(
            status="quarantined_invalid",
            kind="invalid",
            path=report_path,
            content_sha256=raw_digest,
            schema_sha256=schema_digest,
            reason_code=reason,
            integrity_ok=integrity_ok,
            table_counts=table_counts,
        )
        return legacy, _input_record(
            input_id="legacy_database",
            input_type="legacy_database",
            relative_path=report_path,
            content_sha256=raw_digest,
            row_count=sum(table_counts.values()),
            inspection_status="blocked",
            reason_code=reason,
        ), issues

    try:
        after_stat = path.stat()
        after_identity = (
            after_stat.st_dev,
            after_stat.st_ino,
            after_stat.st_size,
            after_stat.st_mtime_ns,
        )
        after_digest = _sha256_file(path)
    except OSError:
        after_identity = None
        after_digest = None
    if (
        after_identity != before_identity
        or after_digest != raw_digest
        or any(sidecar.exists() for sidecar in sidecars)
    ):
        reason = "LEGACY_DATABASE_CHANGED_DURING_INSPECTION"
        issues.append(_issue("legacy_database", "database", reason))
        legacy = _legacy_shape(
            status="quarantined_invalid",
            kind="invalid",
            path=report_path,
            content_sha256=None,
            reason_code=reason,
        )
        return legacy, _input_record(
            input_id="legacy_database",
            input_type="legacy_database",
            relative_path=report_path,
            content_sha256=None,
            row_count=0,
            inspection_status="blocked",
            reason_code=reason,
        ), issues

    registry_missing = sorted(registry_source_ids - set(source_ids)) if "official_sources" in table_counts else []
    database_missing = sorted(set(source_ids) - registry_source_ids) if "official_sources" in table_counts else []
    if registry_missing:
        issues.append(
            _issue(
                "registry_database_divergence",
                "source",
                "REGISTRY_SOURCES_MISSING_FROM_DATABASE",
                entity_ids=registry_missing,
            )
        )
    if database_missing:
        issues.append(
            _issue(
                "registry_database_divergence",
                "source",
                "DATABASE_SOURCES_MISSING_FROM_REGISTRY",
                entity_ids=database_missing,
            )
        )
    if claim_count:
        issues.append(
            _issue(
                "legacy_database",
                "database",
                "LEGACY_RESULT_CLAIMS_QUARANTINED",
            )
        )
    if not integrity_ok:
        reason = "LEGACY_DATABASE_INTEGRITY_FAILED"
        issues.append(_issue("legacy_database", "database", reason))
    elif foreign_key_violations:
        reason = "LEGACY_DATABASE_FOREIGN_KEY_VIOLATIONS"
        issues.append(_issue("legacy_database", "database", reason))
    elif kind == "empty":
        reason = "LEGACY_DATABASE_EMPTY"
        issues.append(_issue("legacy_database", "database", reason))
    elif kind == "unknown_schema":
        reason = "LEGACY_DATABASE_SCHEMA_UNKNOWN"
        issues.append(_issue("legacy_database", "database", reason))
    elif migration_status.kind in {"legacy_unversioned", "versioned_but_not_head"}:
        reason = "LEGACY_DATABASE_REQUIRES_MIGRATION"
        issues.append(_issue("legacy_database", "database", reason))
    elif migration_status.kind != "current":
        reason = "LEGACY_DATABASE_INVALID"
        issues.append(_issue("legacy_database", "database", reason))
    else:
        reason = "LEGACY_DATABASE_READ_ONLY_INVENTORY"

    blocking_database = (
        not integrity_ok
        or bool(foreign_key_violations)
        or migration_status.kind != "current"
    )
    legacy_status = "current_read_only"
    if migration_status.kind in {"legacy_unversioned", "versioned_but_not_head"} and integrity_ok and not foreign_key_violations:
        legacy_status = "quarantined_read_only"
    elif blocking_database:
        legacy_status = "quarantined_invalid"
    legacy = _legacy_shape(
        status=legacy_status,
        kind=kind,
        path=report_path,
        content_sha256=raw_digest,
        schema_sha256=schema_digest,
        reason_code=reason,
        integrity_ok=integrity_ok,
        foreign_key_violation_count=len(foreign_key_violations),
        orphaned_reference_count=orphaned_reference_count,
        result_claim_quarantine_count=claim_count,
        revision=revision,
        table_counts=table_counts,
        source_ids=source_ids,
        registry_missing=registry_missing,
        database_missing=database_missing,
        alias_collisions=alias_collisions,
    )
    return legacy, _input_record(
        input_id="legacy_database",
        input_type="legacy_database",
        relative_path=report_path,
        content_sha256=raw_digest,
        row_count=sum(table_counts.values()),
        inspection_status="blocked" if blocking_database else "read_only",
        reason_code=reason,
    ), issues


def _registry_documents(
    *,
    registry_dir: Path,
    pattern: str,
    row_key: str,
    input_type: str,
    entity_type: str,
    issues: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[Any]]:
    paths = sorted(registry_dir.glob(pattern), key=lambda path: path.name)
    if not paths:
        raise CoverageCensusError(f"No {pattern} registry inputs were found.")
    inputs: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    combined_raw_rows: list[Any] = []
    for path in paths:
        if not path.is_file():
            raise CoverageCensusError(f"Registry input is not a regular file: {path.name}.")
        document = _read_yaml(path)
        raw_rows = _require_array(document, row_key, path.name)
        input_id = f"{input_type}:{path.name}"
        inputs.append(
            _input_record(
                input_id=input_id,
                input_type=input_type,
                relative_path=path.name,
                content_sha256=_registry_semantic_digest(document, row_key),
                row_count=len(raw_rows),
                inspection_status="loaded",
                reason_code="SEMANTIC_INPUT_LOADED",
            )
        )
        records.extend(
            _registry_rows(
                input_id=input_id,
                entity_type=entity_type,
                rows=raw_rows,
                issues=issues,
            )
        )
        combined_raw_rows.extend(raw_rows)
    return inputs, records, combined_raw_rows


def _check_universe_registry_pins(
    *,
    universe_document: Mapping[str, Any],
    benchmark_raw_rows: list[Any],
    source_raw_rows: list[Any],
    issues: list[dict[str, Any]],
) -> None:
    scope = universe_document.get("scope")
    if not isinstance(scope, Mapping):
        raise CoverageCensusError("Coverage Universe needs a scope mapping.")
    registry_inputs = scope.get("registryInputs")
    if not isinstance(registry_inputs, list):
        raise CoverageCensusError("Coverage Universe scope needs registryInputs.")
    by_type: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in registry_inputs:
        if not isinstance(row, Mapping):
            raise CoverageCensusError("Coverage Universe registryInputs must be mappings.")
        record_type = row.get("recordType")
        if record_type in {"benchmark", "configured_source_route"}:
            by_type[str(record_type)].append(row)
    expected_inputs = {
        "benchmark": benchmark_raw_rows,
        "configured_source_route": source_raw_rows,
    }
    for record_type, raw_rows in expected_inputs.items():
        pins = by_type.get(record_type, [])
        if len(pins) != 1:
            raise CoverageCensusError(
                f"Coverage Universe needs exactly one {record_type} registry input pin."
            )
        pin = pins[0]
        expected_count = pin.get("expectedUniqueCount")
        expected_digest = pin.get("semanticSha256")
        if not isinstance(expected_count, int) or isinstance(expected_count, bool) or expected_count < 0:
            raise CoverageCensusError("Coverage Universe registry input count is invalid.")
        if not isinstance(expected_digest, str) or not _DIGEST_RE.fullmatch(expected_digest):
            raise CoverageCensusError("Coverage Universe registry input digest is invalid.")
        exact_ids = {
            raw_id
            for row in raw_rows
            if isinstance(row, Mapping)
            for raw_id in [_nonempty_exact_string(row.get("id"))]
            if raw_id is not None
        }
        if len(exact_ids) != expected_count:
            issues.append(
                _issue(
                    "universe_gap",
                    "universe",
                    "UNIVERSE_REGISTRY_DENOMINATOR_MISMATCH",
                )
            )
        if _registry_rows_digest(raw_rows) != expected_digest:
            issues.append(
                _issue(
                    "universe_gap",
                    "universe",
                    "UNIVERSE_REGISTRY_DIGEST_MISMATCH",
                )
            )


def build_coverage_census(
    *,
    registry_dir: Path,
    universe_path: Path,
    database_url: str | None,
) -> dict[str, Any]:
    """Build the deterministic report without mutating registries or ledger state."""
    registry_dir = Path(registry_dir)
    universe_path = Path(universe_path)
    if not registry_dir.is_dir():
        raise CoverageCensusError("Registry directory is missing or is not a directory.")

    issues: list[dict[str, Any]] = []
    universe_document, universe_input, universe_items = _load_universe(universe_path)
    if universe_document["authority"]["approvalStatus"] != "owner_approved":
        issues.append(
            _issue(
                "universe_gap",
                "universe",
                "UNIVERSE_REVISION_UNAPPROVED",
            )
        )
    benchmark_inputs, benchmarks, benchmark_raw_rows = _registry_documents(
        registry_dir=registry_dir,
        pattern="benchmarks*.yaml",
        row_key="benchmarks",
        input_type="benchmark_registry",
        entity_type="benchmark",
        issues=issues,
    )
    model_inputs, models, _model_raw_rows = _registry_documents(
        registry_dir=registry_dir,
        pattern="models*.yaml",
        row_key="models",
        input_type="model_registry",
        entity_type="model",
        issues=issues,
    )
    source_inputs, sources, source_raw_rows = _registry_documents(
        registry_dir=registry_dir,
        pattern="official_sources.yaml",
        row_key="sources",
        input_type="source_registry",
        entity_type="source",
        issues=issues,
    )
    _check_universe_registry_pins(
        universe_document=universe_document,
        benchmark_raw_rows=benchmark_raw_rows,
        source_raw_rows=source_raw_rows,
        issues=issues,
    )

    benchmark_by_id = _mark_duplicate_ids(benchmarks, "benchmark", issues)
    model_by_id = _mark_duplicate_ids(models, "model", issues)
    source_by_id = _mark_duplicate_ids(sources, "source", issues)
    universe_benchmark_count, universe_source_count = _reconcile_universe(
        universe_items=universe_items,
        benchmark_rows=benchmarks,
        source_rows=sources,
        benchmark_by_id=benchmark_by_id,
        source_by_id=source_by_id,
        issues=issues,
    )
    for row in models:
        if row["reportDisposition"] == "catalogued":
            row["reasonCode"] = "REGISTRY_MODEL_CATALOGUED"

    for entity_type, rows in (
        ("benchmark", benchmarks),
        ("model", models),
        ("source", sources),
    ):
        _collisions, collision_issues = _alias_collision_records(
            rows,
            entity_type=entity_type,
            issue_type="registry_alias_collision",
        )
        issues.extend(collision_issues)

    registry_source_ids = {
        row["stableId"] for row in sources if isinstance(row["stableId"], str)
    }
    legacy, legacy_input, legacy_issues = _inspect_legacy_database(
        database_url,
        registry_source_ids=registry_source_ids,
    )
    issues.extend(legacy_issues)
    issues = sorted(
        {issue["issueKey"]: issue for issue in issues}.values(),
        key=lambda issue: issue["issueKey"],
    )
    benchmarks.sort(key=lambda row: (row["inputId"], row["rowIndex"], row["rowKey"]))
    sources.sort(key=lambda row: (row["inputId"], row["rowIndex"], row["rowKey"]))
    models.sort(key=lambda row: (row["inputId"], row["rowIndex"], row["rowKey"]))
    inputs = sorted(
        [universe_input, *benchmark_inputs, *source_inputs, *model_inputs, legacy_input],
        key=lambda row: row["inputId"],
    )

    registry_alias_count = sum(
        len(row["aliases"]) for row in [*benchmarks, *sources, *models]
    )
    reason_counts = dict(sorted(Counter(issue["reasonCode"] for issue in issues).items()))
    # This ladder is source-route scoped.  In the baseline slice, a unique
    # route reconciled to the bounded universe is only "known"; no discovery,
    # certification, capture, review, or publication state is assessed here.
    known_source_route_count = sum(
        isinstance(row["stableId"], str)
        and len(source_by_id[row["stableId"]]) == 1
        and row["reportDisposition"] in {"configured", "omitted"}
        for row in sources
    )
    status_counts = {
        status: known_source_route_count if status == "known" else 0
        for status in _COVERAGE_STATUS_KEYS
    }
    manifest = universe_document["manifest"]
    payload: dict[str, Any] = {
        "schemaVersion": COVERAGE_CENSUS_SCHEMA_VERSION,
        "policyVersion": COVERAGE_CENSUS_POLICY_VERSION,
        "availability": COVERAGE_CENSUS_AVAILABILITY,
        "readiness": "blocked" if any(issue["blocking"] for issue in issues) else "ready",
        "manifest": {
            "algorithm": CANONICAL_JSON_ALGORITHM,
            "contentSha256": None,
            "denominators": {
                "universeBenchmarkIdCount": universe_benchmark_count,
                "benchmarkRowCount": len(benchmarks),
                "benchmarkUniqueIdCount": len(benchmark_by_id),
                "sourceRowCount": len(sources),
                "sourceUniqueIdCount": len(source_by_id),
                "modelRowCount": len(models),
                "modelUniqueIdCount": len(model_by_id),
                "registryAliasRowCount": registry_alias_count,
                "legacyTableCount": len(legacy["tableCounts"]),
                "issueCount": len(issues),
            },
        },
        "universe": {
            "universeRevisionId": universe_document["universeRevisionId"],
            "contentSha256": manifest["contentSha256"],
            "approvalStatus": universe_document["authority"]["approvalStatus"],
            "effectiveOn": universe_document["effectiveOn"],
            "decisionReference": universe_document["decisionReference"],
            "benchmarkIdCount": universe_benchmark_count,
            "configuredSourceRouteIdCount": universe_source_count,
        },
        "inputs": inputs,
        "summary": {
            "reasonCounts": reason_counts,
            "statusCounts": status_counts,
            "configuredActiveSourceCount": sum(
                row["registryStatus"] == "active"
                and row["reportDisposition"] == "configured"
                for row in sources
            ),
            "certificationAssessmentStatus": "not_assessed",
            "certifiedSourceCount": None,
            "publishedSourceCount": None,
            "universeSourceRouteCount": universe_source_count,
            "resultClaimQuarantineCount": legacy["resultClaimQuarantineCount"],
        },
        "benchmarks": benchmarks,
        "sources": sources,
        "models": models,
        "legacyDatabase": legacy,
        "issues": issues,
    }
    payload["manifest"]["contentSha256"] = coverage_census_digest(payload)
    validate_coverage_census(payload)
    return payload


def _require_keys(value: object, expected: frozenset[str] | set[str], label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != set(expected):
        raise CoverageCensusError(f"{label} fields do not match the coverage-census contract.")
    return value


def _require_count(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise CoverageCensusError(f"{label} must be a nonnegative integer.")
    return value


def _require_reason(value: object, label: str) -> str:
    if not isinstance(value, str) or not _REASON_RE.fullmatch(value):
        raise CoverageCensusError(f"{label} must be a stable reason code.")
    return value


def _require_digest(value: object, label: str, *, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or not _DIGEST_RE.fullmatch(value):
        raise CoverageCensusError(f"{label} must be a SHA-256 digest.")
    return value


def _require_relative_path(value: object, label: str) -> str:
    text = _nonempty_exact_string(value)
    if text is None or text.startswith("/") or ".." in Path(text).parts:
        raise CoverageCensusError(f"{label} must be a safe relative path.")
    return text


def validate_coverage_census(payload: Mapping[str, Any]) -> None:
    """Fail closed when a census cannot be reconciled to every denominator."""
    report = _require_keys(payload, _TOP_LEVEL_KEYS, "Coverage census")
    _canonical_json(report)
    if (
        report.get("schemaVersion") != COVERAGE_CENSUS_SCHEMA_VERSION
        or report.get("policyVersion") != COVERAGE_CENSUS_POLICY_VERSION
        or report.get("availability") != COVERAGE_CENSUS_AVAILABILITY
    ):
        raise CoverageCensusError("Coverage census identity or availability is invalid.")
    if report.get("readiness") not in {"ready", "blocked"}:
        raise CoverageCensusError("Coverage census readiness is invalid.")

    manifest = _require_keys(
        report.get("manifest"),
        {"algorithm", "contentSha256", "denominators"},
        "Coverage census manifest",
    )
    if manifest.get("algorithm") != CANONICAL_JSON_ALGORITHM:
        raise CoverageCensusError("Coverage census canonical algorithm is invalid.")
    _require_digest(manifest.get("contentSha256"), "Coverage census digest")
    denominators = _require_keys(
        manifest.get("denominators"), _DENOMINATOR_KEYS, "Coverage census denominators"
    )
    for key, value in denominators.items():
        _require_count(value, f"Coverage census denominator {key}")

    universe = _require_keys(
        report.get("universe"),
        {
            "universeRevisionId",
            "contentSha256",
            "approvalStatus",
            "effectiveOn",
            "decisionReference",
            "benchmarkIdCount",
            "configuredSourceRouteIdCount",
        },
        "Coverage census universe",
    )
    if _stable_id(universe.get("universeRevisionId")) is None:
        raise CoverageCensusError("Coverage census universeRevisionId is invalid.")
    _require_digest(universe.get("contentSha256"), "Coverage census universe digest")
    universe_approval = universe.get("approvalStatus")
    if universe_approval == "draft_unapproved":
        if universe.get("effectiveOn") is not None or universe.get("decisionReference") is not None:
            raise CoverageCensusError("Draft census universe cannot bind an effective decision.")
    elif universe_approval == "owner_approved":
        effective_on = universe.get("effectiveOn")
        if not isinstance(effective_on, str):
            raise CoverageCensusError("Approved census universe needs an effective date.")
        try:
            parsed_effective_on = date.fromisoformat(effective_on)
        except ValueError as exc:
            raise CoverageCensusError("Approved census universe effective date is invalid.") from exc
        if parsed_effective_on.isoformat() != effective_on or _stable_id(universe.get("decisionReference")) is None:
            raise CoverageCensusError("Approved census universe decision binding is invalid.")
    else:
        raise CoverageCensusError("Coverage census universe approval status is invalid.")
    universe_benchmark_count = _require_count(
        universe.get("benchmarkIdCount"), "Coverage census universe benchmark count"
    )
    universe_source_count = _require_count(
        universe.get("configuredSourceRouteIdCount"),
        "Coverage census universe source-route count",
    )

    inputs = report.get("inputs")
    if not isinstance(inputs, list) or not inputs:
        raise CoverageCensusError("Coverage census inputs must be a nonempty array.")
    if inputs != sorted(inputs, key=lambda row: row.get("inputId", "") if isinstance(row, Mapping) else ""):
        raise CoverageCensusError("Coverage census inputs are not canonically ordered.")
    input_by_id: dict[str, Mapping[str, Any]] = {}
    for raw_input in inputs:
        input_row = _require_keys(raw_input, _INPUT_KEYS, "Coverage census input")
        input_id = _nonempty_exact_string(input_row.get("inputId"))
        if input_id is None or input_id in input_by_id:
            raise CoverageCensusError("Coverage census input IDs must be unique nonempty strings.")
        if input_row.get("inputType") not in _INPUT_TYPES:
            raise CoverageCensusError("Coverage census input type is invalid.")
        _require_relative_path(input_row.get("relativePath"), "Coverage census input path")
        digest = _require_digest(
            input_row.get("contentSha256"), "Coverage census input digest", nullable=True
        )
        inspection_status = input_row.get("inspectionStatus")
        if inspection_status not in _INPUT_STATUSES:
            raise CoverageCensusError("Coverage census input inspection status is invalid.")
        if inspection_status in {"loaded", "read_only"} and digest is None:
            raise CoverageCensusError("A loaded/read-only census input needs a digest.")
        _require_count(input_row.get("rowCount"), "Coverage census input rowCount")
        _require_reason(input_row.get("reasonCode"), "Coverage census input reasonCode")
        input_by_id[input_id] = input_row
    if "coverage_universe" not in input_by_id or "legacy_database" not in input_by_id:
        raise CoverageCensusError("Coverage census is missing its universe or legacy input.")
    universe_input = input_by_id["coverage_universe"]
    if (
        universe_input["inputType"] != "coverage_universe"
        or universe_input["inspectionStatus"] != "loaded"
        or universe_input["contentSha256"] != universe["contentSha256"]
    ):
        raise CoverageCensusError("Coverage census universe input does not bind its projection.")

    collection_specs = (
        ("benchmarks", "benchmark", "benchmarkId", "benchmark_registry"),
        ("sources", "source", "sourceRouteId", "source_registry"),
        ("models", "model", "modelId", "model_registry"),
    )
    all_rows: list[Mapping[str, Any]] = []
    all_row_keys: set[str] = set()
    row_counts_by_input: Counter[str] = Counter()
    typed_rows: dict[str, list[Mapping[str, Any]]] = {}
    for collection_name, entity_type, typed_key, input_type in collection_specs:
        raw_rows = report.get(collection_name)
        if not isinstance(raw_rows, list):
            raise CoverageCensusError(f"Coverage census {collection_name} must be an array.")
        expected_order = sorted(
            raw_rows,
            key=lambda row: (
                row.get("inputId", "") if isinstance(row, Mapping) else "",
                row.get("rowIndex", -1) if isinstance(row, Mapping) else -1,
                row.get("rowKey", "") if isinstance(row, Mapping) else "",
            ),
        )
        if raw_rows != expected_order:
            raise CoverageCensusError(f"Coverage census {collection_name} are not canonically ordered.")
        typed_rows[entity_type] = raw_rows
        indices_by_input: dict[str, list[int]] = defaultdict(list)
        for raw_row in raw_rows:
            expected_keys = set(_COMMON_ROW_KEYS) | {typed_key}
            if entity_type == "source":
                expected_keys.add("benchmarkId")
            row = _require_keys(raw_row, expected_keys, f"Coverage census {entity_type} row")
            row_key = _nonempty_exact_string(row.get("rowKey"))
            input_id = _nonempty_exact_string(row.get("inputId"))
            row_index = row.get("rowIndex")
            if row_key is None or row_key in all_row_keys:
                raise CoverageCensusError("Coverage census registry row keys must be unique.")
            if input_id is None or input_id not in input_by_id:
                raise CoverageCensusError("Coverage census registry row references an unknown input.")
            if input_by_id[input_id]["inputType"] != input_type:
                raise CoverageCensusError("Coverage census registry row references the wrong input type.")
            if not isinstance(row_index, int) or isinstance(row_index, bool) or row_index < 0:
                raise CoverageCensusError("Coverage census rowIndex is invalid.")
            if row_key != f"{input_id}:row:{row_index}":
                raise CoverageCensusError("Coverage census rowKey does not bind its canonical index.")
            indices_by_input[input_id].append(row_index)
            all_row_keys.add(row_key)
            row_counts_by_input[input_id] += 1

            stable_id = row.get("stableId")
            if stable_id is not None and _nonempty_exact_string(stable_id) is None:
                raise CoverageCensusError("Coverage census stableId is not an exact registry identity.")
            typed_id = row.get(typed_key)
            if entity_type in {"benchmark", "source"}:
                if typed_id is not None and _stable_id(typed_id) is None:
                    raise CoverageCensusError("Coverage census typed registry ID is invalid.")
            elif typed_id is not None and _nonempty_exact_string(typed_id) is None:
                raise CoverageCensusError("Coverage census modelId is invalid.")
            if typed_id is not None and stable_id != typed_id:
                raise CoverageCensusError("Coverage census typed registry ID differs from stableId.")
            disposition = row.get("reportDisposition")
            if disposition not in _ROW_DISPOSITIONS:
                raise CoverageCensusError("Coverage census row disposition is invalid.")
            if disposition != "invalid" and (stable_id is None or typed_id is None):
                raise CoverageCensusError("A non-invalid census row needs its exact typed identity.")
            registry_status = row.get("registryStatus")
            if registry_status is not None and _nonempty_exact_string(registry_status) is None:
                raise CoverageCensusError("Coverage census registryStatus is invalid.")
            coverage_status = row.get("coverageStatus")
            if coverage_status not in {None, "configured", "omitted"}:
                raise CoverageCensusError("Coverage census row coverageStatus is invalid.")
            if entity_type in {"benchmark", "source"}:
                if disposition in {"configured", "omitted"}:
                    if coverage_status != disposition:
                        raise CoverageCensusError(
                            "Configured/omitted census disposition must equal coverageStatus."
                        )
                elif coverage_status is not None:
                    raise CoverageCensusError(
                        "Rejected/catalogued source or benchmark rows cannot retain coverageStatus."
                    )
            elif disposition not in {"catalogued", "conflicted", "invalid"}:
                raise CoverageCensusError("Model census row disposition is invalid.")
            _require_reason(row.get("reasonCode"), "Coverage census row reasonCode")
            if entity_type == "source":
                benchmark_id = row.get("benchmarkId")
                if benchmark_id is not None and _stable_id(benchmark_id) is None:
                    raise CoverageCensusError("Coverage census source benchmarkId is invalid.")
                if disposition != "invalid" and benchmark_id is None:
                    raise CoverageCensusError("A non-invalid source row needs benchmarkId.")

            aliases = row.get("aliases")
            if not isinstance(aliases, list):
                raise CoverageCensusError("Coverage census aliases must be an array.")
            for alias_index, raw_alias in enumerate(aliases):
                alias = _require_keys(raw_alias, _ALIAS_ROW_KEYS, "Coverage census alias row")
                alias_row_key = f"{row_key}:alias:{alias_index}"
                if alias.get("rowKey") != alias_row_key or alias_row_key in all_row_keys:
                    raise CoverageCensusError("Coverage census alias rowKey is invalid or duplicated.")
                if alias.get("aliasIndex") != alias_index:
                    raise CoverageCensusError("Coverage census aliasIndex is not contiguous.")
                alias_disposition = alias.get("reportDisposition")
                if alias_disposition not in _ALIAS_DISPOSITIONS:
                    raise CoverageCensusError("Coverage census alias disposition is invalid.")
                alias_text = alias.get("aliasText")
                if alias_disposition == "accounted":
                    if _nonempty_exact_string(alias_text) is None or not _normalize_alias_key(alias_text):
                        raise CoverageCensusError("An accounted census alias must be usable.")
                elif alias_text is not None:
                    raise CoverageCensusError("An invalid census alias must not invent normalized text.")
                _require_reason(alias.get("reasonCode"), "Coverage census alias reasonCode")
                all_row_keys.add(alias_row_key)
            all_rows.append(row)
        for input_id, indices in indices_by_input.items():
            if indices != list(range(len(indices))):
                raise CoverageCensusError("Coverage census rowIndex values are not contiguous per input.")

    for input_id, input_row in input_by_id.items():
        input_type = input_row["inputType"]
        if input_type in {"benchmark_registry", "model_registry", "source_registry"}:
            expected_row_count = row_counts_by_input[input_id]
        elif input_type == "coverage_universe":
            expected_row_count = universe_benchmark_count + universe_source_count
        elif input_type == "legacy_database":
            # Reconciled after legacyDatabase has passed structural validation.
            continue
        else:  # pragma: no cover - input enum above makes this unreachable
            expected_row_count = 0
        if input_row["rowCount"] != expected_row_count:
            raise CoverageCensusError("Coverage census input rowCount does not reconcile.")

    issues = report.get("issues")
    if not isinstance(issues, list):
        raise CoverageCensusError("Coverage census issues must be an array.")
    if issues != sorted(issues, key=lambda issue: issue.get("issueKey", "") if isinstance(issue, Mapping) else ""):
        raise CoverageCensusError("Coverage census issues are not canonically ordered.")
    issue_keys: set[str] = set()
    for raw_issue in issues:
        issue = _require_keys(raw_issue, _ISSUE_KEYS, "Coverage census issue")
        issue_key = _nonempty_exact_string(issue.get("issueKey"))
        if issue_key is None or issue_key in issue_keys:
            raise CoverageCensusError("Coverage census issue keys must be unique.")
        if issue.get("issueType") not in _ISSUE_TYPES:
            raise CoverageCensusError("Coverage census issue type is invalid.")
        if issue.get("entityType") not in _ENTITY_TYPES | {None}:
            raise CoverageCensusError("Coverage census issue entityType is invalid.")
        stable_id = issue.get("stableId")
        if stable_id is not None and _nonempty_exact_string(stable_id) is None:
            raise CoverageCensusError("Coverage census issue stableId is invalid.")
        match_kind = issue.get("matchKind")
        match_key = issue.get("matchKey")
        if match_kind is None:
            if match_key is not None:
                raise CoverageCensusError("Coverage census issue match fields are inconsistent.")
        elif match_kind not in {"exact", "normalized"} or _nonempty_exact_string(match_key) is None:
            raise CoverageCensusError("Coverage census issue match fields are invalid.")
        for field in ("entityIds", "rowKeys"):
            values = issue.get(field)
            if (
                not isinstance(values, list)
                or values != sorted(set(values))
                or any(_nonempty_exact_string(value) is None for value in values)
            ):
                raise CoverageCensusError(f"Coverage census issue {field} is invalid.")
        if any(row_key not in all_row_keys for row_key in issue["rowKeys"]):
            raise CoverageCensusError("Coverage census issue references an unknown rowKey.")
        _require_reason(issue.get("reasonCode"), "Coverage census issue reasonCode")
        if not isinstance(issue.get("blocking"), bool):
            raise CoverageCensusError("Coverage census issue blocking flag is invalid.")
        expected_issue = _issue(
            issue["issueType"],
            issue["entityType"],
            issue["reasonCode"],
            stable_id=issue["stableId"],
            match_kind=issue["matchKind"],
            match_key=issue["matchKey"],
            entity_ids=issue["entityIds"],
            row_keys=issue["rowKeys"],
            blocking=issue["blocking"],
        )
        if expected_issue["issueKey"] != issue_key:
            raise CoverageCensusError("Coverage census issueKey does not bind its content.")
        issue_keys.add(issue_key)

    unapproved_issue = _issue(
        "universe_gap",
        "universe",
        "UNIVERSE_REVISION_UNAPPROVED",
    )
    if universe_approval == "draft_unapproved" and unapproved_issue["issueKey"] not in issue_keys:
        raise CoverageCensusError("Draft census universe is missing its blocking approval issue.")
    if universe_approval == "owner_approved" and unapproved_issue["issueKey"] in issue_keys:
        raise CoverageCensusError("Approved census universe retains a contradictory approval issue.")

    def has_bound_blocking_issue(
        *, entity_type: str, row_key: str, reason_code: str
    ) -> bool:
        return any(
            issue["blocking"]
            and issue["entityType"] == entity_type
            and issue["reasonCode"] == reason_code
            and row_key in issue["rowKeys"]
            for issue in issues
        )

    for entity_type, rows in typed_rows.items():
        for row in rows:
            if entity_type == "model" and row["coverageStatus"] is not None:
                raise CoverageCensusError("Model census rows cannot claim source-route coverage status.")
            if row["reportDisposition"] in {"invalid", "outside_universe", "conflicted"}:
                if not has_bound_blocking_issue(
                    entity_type=entity_type,
                    row_key=row["rowKey"],
                    reason_code=row["reasonCode"],
                ):
                    raise CoverageCensusError(
                        "A rejected/conflicted census row lacks its matching blocking issue."
                    )
            for alias in row["aliases"]:
                if alias["reportDisposition"] == "invalid" and not has_bound_blocking_issue(
                    entity_type=entity_type,
                    row_key=alias["rowKey"],
                    reason_code=alias["reasonCode"],
                ):
                    raise CoverageCensusError("An invalid census alias lacks its blocking issue.")

    eligible_benchmarks: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in typed_rows["benchmark"]:
        if (
            isinstance(row["benchmarkId"], str)
            and row["reportDisposition"] in {"configured", "omitted"}
        ):
            eligible_benchmarks[row["benchmarkId"]].append(row)
    for row in typed_rows["source"]:
        if row["reportDisposition"] in {"configured", "omitted"}:
            if len(eligible_benchmarks.get(row["benchmarkId"], [])) != 1:
                raise CoverageCensusError(
                    "A configured/omitted source does not resolve to one eligible benchmark."
                )

    for entity_type in ("benchmark", "model", "source"):
        rows = typed_rows[entity_type]
        by_id: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
        for row in rows:
            if isinstance(row["stableId"], str):
                by_id[row["stableId"]].append(row)
        for stable_id, duplicates in by_id.items():
            if len(duplicates) > 1:
                if any(
                    row["reportDisposition"] != "conflicted"
                    or row["coverageStatus"] is not None
                    or row["reasonCode"] != "DUPLICATE_REGISTRY_ID"
                    for row in duplicates
                ):
                    raise CoverageCensusError(
                        "Duplicate registry IDs must leave every duplicate row conflicted."
                    )
                expected = _issue(
                    "duplicate_registry_id",
                    entity_type,
                    "DUPLICATE_REGISTRY_ID",
                    stable_id=stable_id,
                    entity_ids=[stable_id],
                    row_keys=[row["rowKey"] for row in duplicates],
                )
                if expected["issueKey"] not in issue_keys:
                    raise CoverageCensusError("Coverage census omits a duplicate registry-ID issue.")
        _unused_collisions, expected_collision_issues = _alias_collision_records(
            rows,
            entity_type=entity_type,
            issue_type="registry_alias_collision",
        )
        if any(issue["issueKey"] not in issue_keys for issue in expected_collision_issues):
            raise CoverageCensusError("Coverage census omits a registry alias collision.")

    legacy = _require_keys(report.get("legacyDatabase"), _LEGACY_KEYS, "Coverage census legacy database")
    if legacy.get("status") not in _LEGACY_STATUSES or legacy.get("kind") not in _LEGACY_KINDS:
        raise CoverageCensusError("Coverage census legacy database status/kind is invalid.")
    _require_relative_path(legacy.get("path"), "Coverage census legacy database path")
    _require_digest(legacy.get("contentSha256"), "Coverage census legacy content digest", nullable=True)
    _require_digest(legacy.get("schemaSha256"), "Coverage census legacy schema digest", nullable=True)
    _require_reason(legacy.get("reasonCode"), "Coverage census legacy reasonCode")
    if legacy.get("integrityOk") not in {None, True, False}:
        raise CoverageCensusError("Coverage census legacy integrity state is invalid.")
    for field in (
        "foreignKeyViolationCount",
        "orphanedReferenceCount",
        "resultClaimQuarantineCount",
    ):
        _require_count(legacy.get(field), f"Coverage census legacy {field}")
    if legacy["orphanedReferenceCount"] > legacy["foreignKeyViolationCount"]:
        raise CoverageCensusError("Legacy orphan count cannot exceed all FK violations.")
    if legacy.get("revision") is not None and _nonempty_exact_string(legacy["revision"]) is None:
        raise CoverageCensusError("Coverage census legacy revision is invalid.")
    table_counts = legacy.get("tableCounts")
    if not isinstance(table_counts, Mapping) or list(table_counts) != sorted(table_counts):
        raise CoverageCensusError("Coverage census legacy tableCounts are not canonical.")
    for table_name, count in table_counts.items():
        if _nonempty_exact_string(table_name) is None:
            raise CoverageCensusError("Coverage census legacy table name is invalid.")
        _require_count(count, "Coverage census legacy table count")
    if input_by_id["legacy_database"]["rowCount"] != sum(table_counts.values()):
        raise CoverageCensusError("Coverage census legacy input rowCount does not reconcile.")
    for field in (
        "sourceIds",
        "registrySourceIdsMissingFromDatabase",
        "databaseSourceIdsMissingFromRegistry",
    ):
        values = legacy.get(field)
        if (
            not isinstance(values, list)
            or values != sorted(set(values))
            or any(_nonempty_exact_string(value) is None for value in values)
        ):
            raise CoverageCensusError(f"Coverage census legacy {field} is invalid.")
    collisions = legacy.get("aliasCollisions")
    if not isinstance(collisions, list):
        raise CoverageCensusError("Coverage census legacy aliasCollisions must be an array.")
    collision_order = sorted(
        collisions,
        key=lambda row: (
            row.get("entityType", "") if isinstance(row, Mapping) else "",
            row.get("matchKind", "") if isinstance(row, Mapping) else "",
            row.get("matchKey", "") if isinstance(row, Mapping) else "",
        ),
    )
    if collisions != collision_order:
        raise CoverageCensusError("Coverage census legacy collisions are not canonical.")
    for raw_collision in collisions:
        collision = _require_keys(raw_collision, _LEGACY_COLLISION_KEYS, "Legacy alias collision")
        if collision.get("entityType") not in {"benchmark", "model", "source"}:
            raise CoverageCensusError("Legacy alias collision entityType is invalid.")
        if collision.get("matchKind") not in {"exact", "normalized"}:
            raise CoverageCensusError("Legacy alias collision matchKind is invalid.")
        if _nonempty_exact_string(collision.get("matchKey")) is None:
            raise CoverageCensusError("Legacy alias collision matchKey is invalid.")
        entity_ids = collision.get("entityIds")
        if (
            not isinstance(entity_ids, list)
            or len(entity_ids) < 2
            or entity_ids != sorted(set(entity_ids))
            or any(_nonempty_exact_string(value) is None for value in entity_ids)
        ):
            raise CoverageCensusError("Legacy alias collision entityIds are invalid.")
        _require_reason(collision.get("reasonCode"), "Legacy alias collision reasonCode")
        expected = _issue(
            "legacy_alias_collision",
            collision["entityType"],
            collision["reasonCode"],
            match_kind=collision["matchKind"],
            match_key=collision["matchKey"],
            entity_ids=collision["entityIds"],
        )
        if expected["issueKey"] not in issue_keys:
            raise CoverageCensusError("Coverage census legacy collision lacks its issue.")

    legacy_input = input_by_id["legacy_database"]
    if (
        legacy_input["contentSha256"] != legacy["contentSha256"]
        or legacy_input["reasonCode"] != legacy["reasonCode"]
        or legacy_input["relativePath"] != legacy["path"]
    ):
        raise CoverageCensusError("Coverage census legacy input does not bind its projection.")
    legacy_status = legacy["status"]
    if legacy_status == "current_read_only":
        if (
            legacy["kind"] != "versioned"
            or legacy["integrityOk"] is not True
            or legacy["foreignKeyViolationCount"] != 0
            or legacy["contentSha256"] is None
            or legacy["schemaSha256"] is None
            or legacy["revision"] is None
            or legacy_input["inspectionStatus"] != "read_only"
        ):
            raise CoverageCensusError("current_read_only legacy status is not an exact clean head state.")
    elif legacy_status == "quarantined_read_only":
        if (
            legacy["kind"] not in {"legacy_unversioned", "versioned"}
            or legacy["integrityOk"] is not True
            or legacy["foreignKeyViolationCount"] != 0
            or legacy["contentSha256"] is None
            or legacy["schemaSha256"] is None
            or legacy_input["inspectionStatus"] != "blocked"
        ):
            raise CoverageCensusError("quarantined_read_only legacy status is inconsistent.")
    elif legacy_status == "quarantined_invalid":
        if legacy_input["inspectionStatus"] != "blocked":
            raise CoverageCensusError("quarantined_invalid legacy input must remain blocked.")
    elif legacy_status == "absent":
        if legacy["kind"] == "not_configured":
            if legacy_input["inspectionStatus"] != "not_configured":
                raise CoverageCensusError("Unconfigured legacy state is inconsistent.")
        elif legacy["kind"] == "absent":
            if legacy_input["inspectionStatus"] != "blocked":
                raise CoverageCensusError("Configured absent legacy database must remain blocked.")
        else:
            raise CoverageCensusError("Absent legacy database kind is invalid.")
    elif legacy_status == "unavailable" and legacy_input["inspectionStatus"] not in {
        "blocked",
        "unsupported",
    }:
        raise CoverageCensusError("Unavailable legacy database input status is invalid.")

    def has_legacy_issue(reason_code: str, issue_type: str = "legacy_database") -> bool:
        return any(
            issue["blocking"]
            and issue["issueType"] == issue_type
            and issue["reasonCode"] == reason_code
            for issue in issues
        )

    if legacy_status == "quarantined_read_only" and not has_legacy_issue(
        "LEGACY_DATABASE_REQUIRES_MIGRATION"
    ):
        raise CoverageCensusError("Quarantined read-only legacy evidence lacks its migration issue.")
    if legacy_status in {"quarantined_invalid", "unavailable"} and not any(
        issue["blocking"] and issue["issueType"] == "legacy_database" for issue in issues
    ):
        raise CoverageCensusError("Unavailable/invalid legacy state lacks a blocking database issue.")

    if legacy["foreignKeyViolationCount"] and not has_legacy_issue(
        "LEGACY_DATABASE_FOREIGN_KEY_VIOLATIONS"
    ):
        raise CoverageCensusError("Legacy FK violations lack their blocking issue.")
    if legacy["integrityOk"] is False and not has_legacy_issue(
        "LEGACY_DATABASE_INTEGRITY_FAILED"
    ):
        raise CoverageCensusError("Legacy integrity failure lacks its blocking issue.")
    if legacy["resultClaimQuarantineCount"] and not has_legacy_issue(
        "LEGACY_RESULT_CLAIMS_QUARANTINED"
    ):
        raise CoverageCensusError("Quarantined legacy claims lack their blocking issue.")
    if legacy["kind"] == "absent" and not has_legacy_issue("LEGACY_DATABASE_ABSENT"):
        raise CoverageCensusError("Configured absent legacy database lacks its blocking issue.")
    if legacy["registrySourceIdsMissingFromDatabase"] and not has_legacy_issue(
        "REGISTRY_SOURCES_MISSING_FROM_DATABASE", "registry_database_divergence"
    ):
        raise CoverageCensusError("Registry/database source divergence lacks its issue.")
    if legacy["databaseSourceIdsMissingFromRegistry"] and not has_legacy_issue(
        "DATABASE_SOURCES_MISSING_FROM_REGISTRY", "registry_database_divergence"
    ):
        raise CoverageCensusError("Database/registry source divergence lacks its issue.")
    registry_source_ids = {
        row["stableId"] for row in typed_rows["source"] if isinstance(row["stableId"], str)
    }
    if "official_sources" in table_counts:
        if legacy["registrySourceIdsMissingFromDatabase"] != sorted(
            registry_source_ids - set(legacy["sourceIds"])
        ) or legacy["databaseSourceIdsMissingFromRegistry"] != sorted(
            set(legacy["sourceIds"]) - registry_source_ids
        ):
            raise CoverageCensusError("Legacy source divergence arrays do not reconcile.")
    elif (
        legacy["sourceIds"]
        or legacy["registrySourceIdsMissingFromDatabase"]
        or legacy["databaseSourceIdsMissingFromRegistry"]
    ):
        raise CoverageCensusError("Legacy source IDs exist without an inspected source table.")

    summary = _require_keys(report.get("summary"), _SUMMARY_KEYS, "Coverage census summary")
    reason_counts = summary.get("reasonCounts")
    expected_reasons = dict(sorted(Counter(issue["reasonCode"] for issue in issues).items()))
    if reason_counts != expected_reasons:
        raise CoverageCensusError("Coverage census summary reasonCounts do not reconcile.")
    status_counts = _require_keys(
        summary.get("statusCounts"), set(_COVERAGE_STATUS_KEYS), "Coverage census statusCounts"
    )
    for status, count in status_counts.items():
        _require_count(count, f"Coverage census status count {status}")
    source_by_stable_id: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in typed_rows["source"]:
        if isinstance(row["stableId"], str):
            source_by_stable_id[row["stableId"]].append(row)
    expected_known = sum(
        len(source_by_stable_id[row["stableId"]]) == 1
        and row["reportDisposition"] in {"configured", "omitted"}
        for row in typed_rows["source"]
        if isinstance(row["stableId"], str)
    )
    if status_counts["known"] != expected_known or any(
        status_counts[status] != 0 for status in _COVERAGE_STATUS_KEYS if status != "known"
    ):
        raise CoverageCensusError("Coverage census source-route status ladder is invalid.")
    expected_active = sum(
        row["registryStatus"] == "active" and row["reportDisposition"] == "configured"
        for row in typed_rows["source"]
    )
    if summary.get("configuredActiveSourceCount") != expected_active:
        raise CoverageCensusError("Coverage census configuredActiveSourceCount is invalid.")
    if (
        summary.get("certificationAssessmentStatus") != "not_assessed"
        or summary.get("certifiedSourceCount") is not None
        or summary.get("publishedSourceCount") is not None
    ):
        raise CoverageCensusError("Coverage census must not infer certification/publication counts.")
    if summary.get("universeSourceRouteCount") != universe_source_count:
        raise CoverageCensusError("Coverage census universe source-route count does not reconcile.")
    if summary.get("resultClaimQuarantineCount") != legacy["resultClaimQuarantineCount"]:
        raise CoverageCensusError("Coverage census result-claim quarantine count does not reconcile.")

    stable_sets = {
        "benchmark": {row["stableId"] for row in typed_rows["benchmark"] if row["stableId"] is not None},
        "source": {row["stableId"] for row in typed_rows["source"] if row["stableId"] is not None},
        "model": {row["stableId"] for row in typed_rows["model"] if row["stableId"] is not None},
    }
    expected_denominators = {
        "universeBenchmarkIdCount": universe_benchmark_count,
        "benchmarkRowCount": len(typed_rows["benchmark"]),
        "benchmarkUniqueIdCount": len(stable_sets["benchmark"]),
        "sourceRowCount": len(typed_rows["source"]),
        "sourceUniqueIdCount": len(stable_sets["source"]),
        "modelRowCount": len(typed_rows["model"]),
        "modelUniqueIdCount": len(stable_sets["model"]),
        "registryAliasRowCount": sum(len(row["aliases"]) for row in all_rows),
        "legacyTableCount": len(table_counts),
        "issueCount": len(issues),
    }
    if dict(denominators) != expected_denominators:
        raise CoverageCensusError("Coverage census manifest denominators do not reconcile.")
    has_blocking_issue = any(issue["blocking"] for issue in issues)
    if report["readiness"] != ("blocked" if has_blocking_issue else "ready"):
        raise CoverageCensusError("Coverage census readiness disagrees with its blocking issues.")
    if coverage_census_digest(report) != manifest["contentSha256"]:
        raise CoverageCensusError("Coverage census content digest does not match its report.")


def _markdown_cell(value: object) -> str:
    if value is None:
        return "—"
    rendered = html.escape(str(value), quote=True).replace("\r", " ").replace("\n", " ")
    rendered = rendered.replace("\\", "\\\\")
    for control in ("`", "*", "_", "[", "]", "(", ")", "#", "!", "|"):
        rendered = rendered.replace(control, f"\\{control}")
    return rendered


def render_coverage_markdown(payload: Mapping[str, Any]) -> str:
    """Render a deterministic operator projection of a validated census."""
    validate_coverage_census(payload)
    manifest = payload["manifest"]
    denominators = manifest["denominators"]
    summary = payload["summary"]
    legacy = payload["legacyDatabase"]
    lines = [
        "# Coverage census",
        "",
        f"- Availability: `{payload['availability']}`",
        f"- Readiness: `{payload['readiness']}`",
        f"- Universe revision: `{payload['universe']['universeRevisionId']}`",
        f"- Universe approval: `{payload['universe']['approvalStatus']}`",
        f"- Report SHA-256: `{manifest['contentSha256']}`",
        "- Trust boundary: inventory only; not certification or publication authorization",
        "- Coverage freshness: `not_assessed` (requires a separate time-bound scheduled-cycle receipt)",
        "- Certification assessment: `not_assessed` (certified/published counts are intentionally unknown)",
        "",
        "## Bounded registry census",
        "",
        "| Measure | Count |",
        "| --- | ---: |",
        f"| Universe benchmark IDs | {denominators['universeBenchmarkIdCount']} |",
        f"| Registry benchmark rows | {denominators['benchmarkRowCount']} |",
        f"| Registry source-route rows | {denominators['sourceRowCount']} |",
        f"| Known bounded source routes | {summary['statusCounts']['known']} |",
        f"| Registry model rows | {denominators['modelRowCount']} |",
        f"| Registry alias rows | {denominators['registryAliasRowCount']} |",
        f"| Blocking/report issues | {denominators['issueCount']} |",
        f"| Quarantined legacy claims | {summary['resultClaimQuarantineCount']} |",
        "",
        "## Legacy database (read-only)",
        "",
        f"- Status: `{legacy['status']}`",
        f"- Kind: `{legacy['kind']}`",
        f"- Reason: `{legacy['reasonCode']}`",
        f"- Foreign-key violations: {legacy['foreignKeyViolationCount']}",
        f"- Orphaned claim-validation references: {legacy['orphanedReferenceCount']}",
        "",
        "## Issues",
        "",
    ]
    if not payload["issues"]:
        lines.append("No issues reported.")
    else:
        lines.extend(
            [
                "| Issue | Entity | Stable ID / match | Reason | Blocking |",
                "| --- | --- | --- | --- | --- |",
            ]
        )
        for issue in payload["issues"]:
            identity = issue["stableId"] or issue["matchKey"] or ", ".join(issue["entityIds"])
            lines.append(
                "| "
                + " | ".join(
                    _markdown_cell(value)
                    for value in (
                        issue["issueKey"],
                        issue["entityType"],
                        identity,
                        issue["reasonCode"],
                        "yes" if issue["blocking"] else "no",
                    )
                )
                + " |"
            )
    return "\n".join(lines) + "\n"
