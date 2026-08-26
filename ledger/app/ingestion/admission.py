"""Central, fail-closed source and claim admission for the official ledger.

Adapters may extract observations, but they do not authorize a result claim.
This module resolves immutable source certification, fetch provenance, typed
evidence, dimensions, numeric semantics, and identity certainty before the
runner can persist a new claim.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
import io
import math
import re
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models
from app.ingestion.json_lexemes import (
    JsonLexemeError,
    decode_exact_json_script,
    decode_json_bytes,
    parse_json_path,
    resolve_json_path,
    source_score_lexeme,
    source_text,
)
from app.ingestion.parquet_cells import (
    ParquetEvidenceResolver,
    read_parquet_record,
)
from app.ingestion.policy import source_admission_reason
from app.matching.aliases import MatchResolution
from app.schemas.boundary import OfficialSource, ResultClaimInput, SourceFetchResult, SourceSnapshotInput


ADMISSION_POLICY_SCHEMA = "source-admission-v2"
CERTIFIED_SOURCE_OUTCOME = "certified"
SUPPORTED_LOCATOR_TYPES = frozenset({"json_path_v1", "json_script_path_v1", "csv_cell_v1", "parquet_cell_v1"})
MAX_CERTIFIED_FETCH_BYTES = 64 * 1024 * 1024
_DECIMAL_RE = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?\Z")


@dataclass(frozen=True)
class AdmissionVerdict:
    disposition: Literal["admit", "quarantine", "reject"]
    reason_code: str | None = None
    detail: str | None = None

    @property
    def accepted(self) -> bool:
        return self.disposition in {"admit", "quarantine"}


@dataclass(frozen=True)
class SourceAdmission:
    verdict: AdmissionVerdict
    source_revision_id: str | None = None
    source_revision_decision_id: str | None = None
    policy: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ClaimAdmission:
    verdict: AdmissionVerdict
    score_numeric: float | None = None
    score_unit: str | None = None


def _source_reject(code: str, detail: str) -> SourceAdmission:
    return SourceAdmission(AdmissionVerdict("reject", code, detail))


def _claim_reject(code: str, detail: str) -> ClaimAdmission:
    return ClaimAdmission(AdmissionVerdict("reject", code, detail))


def _claim_quarantine(code: str, detail: str, *, score_numeric: float, score_unit: str | None) -> ClaimAdmission:
    return ClaimAdmission(
        AdmissionVerdict("quarantine", code, detail), score_numeric=score_numeric, score_unit=score_unit
    )


def _active_source_decision(
    session: Session, source_revision_id: str
) -> tuple[models.SourceRevisionDecision | None, str | None]:
    decisions = list(
        session.scalars(
            select(models.SourceRevisionDecision).where(
                models.SourceRevisionDecision.source_revision_id == source_revision_id
            )
        )
    )
    if not decisions:
        return None, "SRC_DECISION_MISSING"

    by_id = {decision.id: decision for decision in decisions}
    superseded: set[str] = set()
    for decision in decisions:
        parent_id = decision.supersedes_decision_id
        if parent_id is None:
            continue
        parent = by_id.get(parent_id)
        if parent is None:
            return None, "SRC_DECISION_CHAIN_INVALID"
        if parent.source_revision_id != decision.source_revision_id:
            return None, "SRC_DECISION_CHAIN_INVALID"
        superseded.add(parent_id)

    leaves = [decision for decision in decisions if decision.id not in superseded]
    if len(leaves) != 1:
        return None, "SRC_DECISION_AMBIGUOUS"

    leaf = leaves[0]
    visited: set[str] = set()
    current: models.SourceRevisionDecision | None = leaf
    while current is not None:
        if current.id in visited:
            return None, "SRC_DECISION_CHAIN_CYCLE"
        visited.add(current.id)
        current = by_id.get(current.supersedes_decision_id) if current.supersedes_decision_id else None
    return leaf, None


def _is_string_list(value: object) -> bool:
    return isinstance(value, list) and bool(value) and all(isinstance(item, str) and item for item in value)


_EVIDENCE_FIELD_NAMES = frozenset(
    {
        "model_raw",
        "score_raw",
        "benchmark_raw",
        "metric_raw",
        "split_raw",
        "setting_raw",
        "evaluation_version_raw",
        "rank_raw",
    }
)


def _is_evidence_field_map(value: object) -> bool:
    return (
        isinstance(value, dict)
        and {"model_raw", "score_raw"}.issubset(value)
        and all(
            isinstance(field_name, str)
            and field_name in _EVIDENCE_FIELD_NAMES
            and isinstance(source_field, str)
            and source_field
            for field_name, source_field in value.items()
        )
    )


def _is_indexed_path_template(value: object) -> bool:
    if not isinstance(value, str) or value.count("{row_index}") != 1:
        return False
    candidate = value.replace("{row_index}", "0")
    return "{" not in candidate and "}" not in candidate and parse_json_path(candidate) is not None


def _is_script_assertion_list(value: object) -> bool:
    if not isinstance(value, list):
        return False
    paths: set[str] = set()
    for assertion in value:
        if not isinstance(assertion, dict) or set(assertion) != {"path", "equals"}:
            return False
        path = assertion.get("path")
        expected = assertion.get("equals")
        if not isinstance(path, str) or parse_json_path(path) is None or not isinstance(expected, str):
            return False
        if path in paths:
            return False
        paths.add(path)
    return True


def _evidence_contract_is_well_formed(locator_type: str, contract: object) -> tuple[bool, str]:
    if not isinstance(contract, dict):
        return False, f"evidence contract for {locator_type!r} is missing"
    fields = contract.get("fields")
    if not _is_evidence_field_map(fields):
        return False, f"evidence contract for {locator_type!r} has invalid field bindings"
    if locator_type == "json_path_v1":
        if set(contract) != {"record_path_template", "fields"}:
            return False, "json_path_v1 contract has unsupported keys"
        if not _is_indexed_path_template(contract.get("record_path_template")):
            return False, "json_path_v1 contract has an invalid indexed record path"
        return True, ""
    if locator_type == "json_script_path_v1":
        if set(contract) != {
            "script_id",
            "script_type",
            "record_path_template",
            "fields",
            "assertions",
        }:
            return False, "json_script_path_v1 contract has unsupported keys"
        if not isinstance(contract.get("script_id"), str) or not contract["script_id"]:
            return False, "json_script_path_v1 contract lacks a script id"
        if contract.get("script_type") is not None and not isinstance(contract.get("script_type"), str):
            return False, "json_script_path_v1 contract has an invalid script type"
        if not _is_indexed_path_template(contract.get("record_path_template")):
            return False, "json_script_path_v1 contract has an invalid indexed record path"
        if not _is_script_assertion_list(contract.get("assertions")):
            return False, "json_script_path_v1 contract has invalid assertions"
        return True, ""
    if locator_type == "csv_cell_v1":
        if set(contract) != {"fields"}:
            return False, "csv_cell_v1 contract has unsupported keys"
        return True, ""
    if locator_type == "parquet_cell_v1":
        if set(contract) != {"fields"}:
            return False, "parquet_cell_v1 contract has unsupported keys"
        return True, ""
    return False, f"evidence locator {locator_type!r} is unsupported"


def _policy_is_well_formed(
    policy: dict[str, Any], *, source: OfficialSource, revision: models.OfficialSourceRevision
) -> tuple[bool, str]:
    if policy.get("schema") != ADMISSION_POLICY_SCHEMA:
        return False, f"source_admission.schema must be {ADMISSION_POLICY_SCHEMA}"
    if policy.get("definition_hash") != revision.definition_hash:
        return False, "source admission decision does not bind this immutable definition hash"
    if policy.get("source_kind") != "official_reported_result":
        return False, "source admission must classify the source as an official reported result"

    adapter = policy.get("adapter")
    if not isinstance(adapter, dict):
        return False, "source admission adapter binding is missing"
    if adapter.get("parser_name") != source.parser_name or adapter.get("parser_version") != source.parser_version:
        return False, "source admission adapter binding does not match the current revision"

    if not _is_string_list(policy.get("approved_source_urls")) or source.source_url not in policy["approved_source_urls"]:
        return False, "source URL is not explicitly approved by this revision decision"
    if not _is_string_list(policy.get("approved_final_urls")):
        return False, "approved final URLs are missing"

    locator_types = policy.get("locator_types")
    if not _is_string_list(locator_types) or not set(locator_types).issubset(SUPPORTED_LOCATOR_TYPES):
        return False, "source admission must list supported typed evidence locators"
    evidence_contracts = policy.get("evidence_contracts")
    if not isinstance(evidence_contracts, dict) or set(evidence_contracts) != set(locator_types):
        return False, "source admission must bind exactly one evidence contract for every locator type"
    for locator_type in locator_types:
        contracts_ok, contract_detail = _evidence_contract_is_well_formed(
            locator_type, evidence_contracts.get(locator_type)
        )
        if not contracts_ok:
            return False, contract_detail

    dimensions = policy.get("dimensions")
    if not isinstance(dimensions, dict):
        return False, "source admission dimensions are missing"
    for field_name in ("benchmark_raw", "metric_raw", "split_raw", "setting_raw", "evaluation_version_raw"):
        dimension = dimensions.get(field_name)
        if not isinstance(dimension, dict) or dimension.get("mode") not in {
            "revision_constant",
            "evidence_field",
        }:
            return False, f"source admission dimension {field_name!r} is not declared"
        if dimension.get("mode") == "revision_constant" and "value" not in dimension:
            return False, f"source admission dimension {field_name!r} lacks a constant value"
        allowed_values = dimension.get("allowed_values")
        if not isinstance(allowed_values, list):
            return False, f"source admission dimension {field_name!r} lacks allowed values"
        if dimension.get("mode") == "evidence_field":
            for contract in evidence_contracts.values():
                fields = contract.get("fields") if isinstance(contract, dict) else None
                if not isinstance(fields, dict) or field_name not in fields:
                    return False, (
                        f"source admission evidence dimension {field_name!r} lacks a typed field binding"
                    )

    numeric = policy.get("numeric")
    if not isinstance(numeric, dict):
        return False, "source admission numeric policy is missing"
    if numeric.get("lexeme") not in {"decimal", "decimal_percent"}:
        return False, "source admission numeric lexeme is unsupported"
    if "score_unit" not in numeric or numeric["score_unit"] not in {None, "percent"}:
        return False, "source admission numeric score unit is unsupported"
    if numeric["lexeme"] == "decimal_percent" and numeric["score_unit"] != "percent":
        return False, "decimal_percent requires score_unit=percent"

    fetch = policy.get("fetch")
    if not isinstance(fetch, dict) or set(fetch) != {"max_bytes"}:
        return False, "source admission fetch policy is missing or has unsupported keys"
    max_bytes = fetch.get("max_bytes")
    if type(max_bytes) is not int or not 1 <= max_bytes <= MAX_CERTIFIED_FETCH_BYTES:
        return False, "source admission fetch.max_bytes is outside the certified bounds"
    return True, ""


def resolve_source_admission(
    session: Session,
    *,
    source: OfficialSource,
    source_revision: models.OfficialSourceRevision,
) -> SourceAdmission:
    """Approve only the exact current revision with one certified decision."""
    static_reason = source_admission_reason(source)
    if static_reason:
        return _source_reject("SRC_SOURCE_CLASS_FORBIDDEN", static_reason)
    source_row = session.get(models.OfficialSourceRow, source.id)
    if source_row is None or source_row.current_revision_id != source_revision.id:
        return _source_reject("SRC_CURRENT_REVISION_MISMATCH", "source does not point at this revision")
    if source_revision.official_source_id != source.id or source_revision.status != "active":
        return _source_reject("SRC_REVISION_NOT_ACTIVE", "source revision is not active for this source")
    revision_definition = source_revision.definition_json if isinstance(source_revision.definition_json, dict) else {}
    if revision_definition.get("benchmark_id") != source.benchmark_id:
        return _source_reject("SRC_REVISION_PROJECTION_MISMATCH", "source benchmark differs from its revision")
    for field_name in (
        "source_name",
        "source_url",
        "source_type",
        "officialness_level",
        "machine_readable",
        "requires_auth",
        "supports_history",
        "update_cadence",
        "parser_name",
        "parser_version",
        "parser_config",
        "status",
        "notes",
    ):
        if getattr(source_revision, field_name) != getattr(source, field_name):
            return _source_reject(
                "SRC_REVISION_PROJECTION_MISMATCH", f"source field {field_name!r} differs from its revision"
            )

    decision, decision_error = _active_source_decision(session, source_revision.id)
    if decision_error:
        return _source_reject(decision_error, "source revision has no single valid effective decision")
    assert decision is not None
    if decision.outcome != CERTIFIED_SOURCE_OUTCOME:
        return _source_reject("SRC_DECISION_NOT_CERTIFIED", f"effective decision outcome is {decision.outcome!r}")
    basis = decision.basis_json if isinstance(decision.basis_json, dict) else {}
    policy = basis.get("source_admission")
    if not isinstance(policy, dict):
        return _source_reject("SRC_POLICY_MISSING", "certified decision has no source-admission policy")
    well_formed, detail = _policy_is_well_formed(policy, source=source, revision=source_revision)
    if not well_formed:
        return _source_reject("SRC_POLICY_INVALID", detail)
    return SourceAdmission(
        AdmissionVerdict("admit"),
        source_revision_id=source_revision.id,
        source_revision_decision_id=decision.id,
        policy=policy,
    )


def resolve_fetch_admission(
    *,
    source_admission: SourceAdmission,
    source: OfficialSource,
    fetch_result: SourceFetchResult,
    snapshot_input: SourceSnapshotInput,
) -> AdmissionVerdict:
    """Require a certified single, verbatim source artifact before storage."""
    if not source_admission.verdict.accepted:
        return AdmissionVerdict("reject", "SRC_NOT_ADMITTED", "source revision was not admitted")
    approved_final_urls = source_admission.policy.get("approved_final_urls")
    if not _is_string_list(approved_final_urls):
        return AdmissionVerdict(
            "reject", "SRC_ADMISSION_CONTEXT_INVALID", "source admission has no valid final URL policy"
        )
    fetch_policy = source_admission.policy.get("fetch")
    max_bytes = fetch_policy.get("max_bytes") if isinstance(fetch_policy, dict) else None
    if type(max_bytes) is not int or not 1 <= max_bytes <= MAX_CERTIFIED_FETCH_BYTES:
        return AdmissionVerdict(
            "reject", "SRC_ADMISSION_CONTEXT_INVALID", "source admission has no valid fetch byte limit"
        )
    if len(fetch_result.raw_bytes) > max_bytes:
        return AdmissionVerdict(
            "reject", "FETCH_BODY_TOO_LARGE", "fetch artifact exceeds its certified byte limit"
        )
    if fetch_result.http_status is None or not 200 <= fetch_result.http_status < 300:
        return AdmissionVerdict("reject", "FETCH_HTTP_STATUS_INVALID", "fetch did not return a successful status")
    if fetch_result.final_url not in approved_final_urls:
        return AdmissionVerdict("reject", "FETCH_FINAL_URL_NOT_APPROVED", "final URL is not explicitly certified")
    metadata = fetch_result.metadata or {}
    if metadata.get("verbatim") is not True or metadata.get("artifact_count") != 1:
        return AdmissionVerdict(
            "reject", "FETCH_NON_VERBATIM_OR_MULTI_ARTIFACT", "fetch must attest to one verbatim artifact"
        )
    for marker in ("mock_used", "fallback_used", "derived", "transformed", "assembled"):
        if metadata.get(marker) is True:
            return AdmissionVerdict("reject", "FETCH_FALLBACK_OR_MOCK", f"fetch metadata marks {marker}")
    if snapshot_input.official_source_id != source.id or snapshot_input.raw_bytes != fetch_result.raw_bytes:
        return AdmissionVerdict(
            "reject", "FETCH_SNAPSHOT_NOT_VERBATIM", "snapshot input differs from the certified fetch artifact"
        )
    if snapshot_input.http_status != fetch_result.http_status:
        return AdmissionVerdict(
            "reject", "FETCH_SNAPSHOT_METADATA_MISMATCH", "snapshot status differs from the fetch receipt"
        )
    snapshot_metadata = snapshot_input.fetch_metadata or {}
    if snapshot_metadata.get("final_url") != fetch_result.final_url:
        return AdmissionVerdict(
            "reject", "FETCH_SNAPSHOT_METADATA_MISMATCH", "snapshot final URL differs from the fetch receipt"
        )
    for key in ("verbatim", "artifact_count", "mock_used", "fallback_used", "derived", "transformed", "assembled"):
        if snapshot_metadata.get(key) != metadata.get(key):
            return AdmissionVerdict(
                "reject",
                "FETCH_SNAPSHOT_METADATA_MISMATCH",
                f"snapshot {key!r} differs from the fetch receipt",
            )
    return AdmissionVerdict("admit")


def _path_matches_index_template(path: object, template: object) -> bool:
    if not isinstance(path, str) or not isinstance(template, str) or template.count("{row_index}") != 1:
        return False
    prefix, suffix = template.split("{row_index}")
    if not path.startswith(prefix) or not path.endswith(suffix):
        return False
    end = len(path) - len(suffix) if suffix else len(path)
    index_text = path[len(prefix) : end]
    if not index_text.isdigit() or (len(index_text) > 1 and index_text.startswith("0")):
        return False
    return path == template.replace("{row_index}", index_text) and parse_json_path(path) is not None


def _locator_matches_contract(locator: object, policy: dict[str, Any]) -> bool:
    if not isinstance(locator, dict):
        return False
    locator_type = locator.get("type")
    contracts = policy.get("evidence_contracts")
    contract = contracts.get(locator_type) if isinstance(contracts, dict) and isinstance(locator_type, str) else None
    if not isinstance(contract, dict):
        return False
    fields = contract.get("fields")
    if locator_type == "json_path_v1":
        return (
            set(locator) == {"type", "record_path", "fields"}
            and locator.get("fields") == fields
            and _path_matches_index_template(locator.get("record_path"), contract.get("record_path_template"))
        )
    if locator_type == "json_script_path_v1":
        return (
            set(locator) == {
                "type",
                "script_id",
                "script_type",
                "record_path",
                "fields",
                "assertions",
            }
            and locator.get("script_id") == contract.get("script_id")
            and locator.get("script_type") == contract.get("script_type")
            and locator.get("fields") == fields
            and locator.get("assertions") == contract.get("assertions")
            and _path_matches_index_template(locator.get("record_path"), contract.get("record_path_template"))
        )
    if locator_type == "csv_cell_v1":
        row_index = locator.get("row_index")
        return (
            set(locator) == {"type", "row_index", "fields"}
            and type(row_index) is int
            and row_index >= 0
            and locator.get("fields") == fields
        )
    if locator_type == "parquet_cell_v1":
        row_group = locator.get("row_group")
        row_index = locator.get("row_index")
        return (
            set(locator) == {"type", "row_group", "row_index", "fields"}
            and type(row_group) is int
            and row_group >= 0
            and type(row_index) is int
            and row_index >= 0
            and locator.get("fields") == fields
        )
    return False


def _json_record(raw_bytes: bytes, locator: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    try:
        data = decode_json_bytes(raw_bytes)
    except JsonLexemeError:
        return None, "EVIDENCE_LOCATOR_INVALID"
    value, error = resolve_json_path(data, locator.get("record_path"))
    if error:
        return None, error
    return (value, None) if isinstance(value, dict) else (None, "EVIDENCE_RECORD_INVALID")


def _json_script_record(
    raw_bytes: bytes, locator: dict[str, Any]
) -> tuple[dict[str, Any] | None, str | None]:
    data, script_error = decode_exact_json_script(
        raw_bytes,
        script_id=locator.get("script_id"),
        script_type=locator.get("script_type"),
    )
    if script_error:
        return None, script_error
    assertions = locator.get("assertions")
    if not isinstance(assertions, list):
        return None, "EVIDENCE_LOCATOR_INVALID"
    for assertion in assertions:
        if not isinstance(assertion, dict):
            return None, "EVIDENCE_LOCATOR_INVALID"
        value, error = resolve_json_path(data, assertion.get("path"))
        if error or source_text(value) != assertion.get("equals"):
            return None, "EVIDENCE_ASSERTION_FAILED"
    value, error = resolve_json_path(data, locator.get("record_path"))
    if error:
        return None, error
    return (value, None) if isinstance(value, dict) else (None, "EVIDENCE_RECORD_INVALID")


def _csv_record(raw_bytes: bytes, locator: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    row_index = locator.get("row_index")
    if not isinstance(row_index, int) or row_index < 0:
        return None, "EVIDENCE_LOCATOR_INVALID"
    try:
        rows = list(csv.DictReader(io.StringIO(raw_bytes.decode("utf-8"))))
    except UnicodeDecodeError:
        return None, "EVIDENCE_LOCATOR_INVALID"
    if row_index >= len(rows):
        return None, "EVIDENCE_NOT_FOUND"
    return rows[row_index], None


def _evidence_record(
    raw_bytes: bytes,
    locator: object,
    *,
    parquet_resolver: ParquetEvidenceResolver | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(locator, dict):
        return None, "EVIDENCE_LOCATOR_INVALID"
    locator_type = locator.get("type")
    if locator_type == "json_path_v1":
        return _json_record(raw_bytes, locator)
    if locator_type == "json_script_path_v1":
        return _json_script_record(raw_bytes, locator)
    if locator_type == "csv_cell_v1":
        return _csv_record(raw_bytes, locator)
    if locator_type == "parquet_cell_v1":
        return read_parquet_record(
            raw_bytes,
            row_group=locator.get("row_group"),
            row_index=locator.get("row_index"),
            resolver=parquet_resolver,
        )
    return None, "EVIDENCE_LOCATOR_UNSUPPORTED"


def _field_value(
    record: dict[str, Any], locator: dict[str, Any], field_name: str
) -> tuple[str | None, str | None]:
    fields = locator.get("fields")
    field = fields.get(field_name) if isinstance(fields, dict) else None
    if not isinstance(field, str) or not field:
        return None, "EVIDENCE_FIELD_NOT_DECLARED"
    value = record.get(field)
    evidence_value = source_score_lexeme(value) if field_name == "score_raw" else source_text(value)
    if evidence_value is None:
        return None, "EVIDENCE_VALUE_NOT_VERBATIM"
    return evidence_value, None


def _dimension_matches(
    *,
    field_name: str,
    claim_value: str | None,
    policy: dict[str, Any],
    record: dict[str, Any],
    locator: dict[str, Any],
) -> str | None:
    config = policy["dimensions"][field_name]
    mode = config["mode"]
    if mode == "revision_constant":
        expected = config["value"]
        if claim_value != expected:
            return "DIMENSION_VALUE_MISMATCH"
    else:
        value, error = _field_value(record, locator, field_name)
        if error:
            return error
        if claim_value != value:
            return "DIMENSION_VALUE_MISMATCH"
    if claim_value not in config["allowed_values"]:
        return "DIMENSION_VALUE_NOT_ALLOWED"
    return None


def _strict_numeric(score_raw: str, numeric_policy: dict[str, Any]) -> tuple[float | None, str | None]:
    lexeme = numeric_policy["lexeme"]
    raw_number = score_raw
    if lexeme == "decimal_percent":
        if not raw_number.endswith("%"):
            return None, "SCORE_UNIT_UNDECLARED"
        raw_number = raw_number[:-1]
    elif raw_number.endswith("%"):
        return None, "SCORE_UNIT_UNDECLARED"
    if not _DECIMAL_RE.fullmatch(raw_number):
        return None, "SCORE_NOT_NUMERIC"
    try:
        decimal = Decimal(raw_number)
    except InvalidOperation:
        return None, "SCORE_NOT_NUMERIC"
    if not decimal.is_finite():
        return None, "SCORE_NOT_FINITE"
    value = float(decimal)
    if not math.isfinite(value):
        return None, "SCORE_NOT_FINITE"
    if decimal != 0 and value == 0.0:
        return None, "SCORE_NOT_REPRESENTABLE"
    return value, None


def resolve_claim_admission(
    *,
    source_admission: SourceAdmission,
    source: OfficialSource,
    claim: ResultClaimInput,
    raw_bytes: bytes,
    model_match: MatchResolution,
    benchmark_match: MatchResolution,
    parquet_resolver: ParquetEvidenceResolver | None = None,
) -> ClaimAdmission:
    """Resolve a candidate claim without mutating its raw source fields."""
    if not source_admission.verdict.accepted:
        return _claim_reject("SRC_NOT_ADMITTED", "source revision was not admitted")
    if not source_admission.source_revision_decision_id:
        return _claim_reject(
            "SRC_ADMISSION_CONTEXT_INVALID", "source admission is missing its immutable decision id"
        )
    if str(claim.source_revision_decision_id) != str(source_admission.source_revision_decision_id):
        return _claim_reject(
            "CLAIM_SOURCE_DECISION_MISMATCH",
            "claim is not bound to the exact source-revision decision that admitted it",
        )
    policy = source_admission.policy
    if (
        not isinstance(policy.get("locator_types"), list)
        or not isinstance(policy.get("evidence_contracts"), dict)
        or not isinstance(policy.get("dimensions"), dict)
    ):
        return _claim_reject("SRC_ADMISSION_CONTEXT_INVALID", "source admission policy is incomplete")
    if claim.official_source_id != source.id:
        return _claim_reject("CLAIM_SOURCE_MISMATCH", "claim source differs from the admitted source")
    if not claim.model_raw.strip() or not claim.benchmark_raw.strip() or not claim.score_raw:
        return _claim_reject("CLAIM_REQUIRED_RAW_FIELD_MISSING", "model, benchmark, and score raw fields are required")
    if source.benchmark_id is None or benchmark_match.status != "matched":
        return _claim_reject("BENCHMARK_UNRESOLVED", "benchmark must resolve through the admitted source")
    if benchmark_match.entity_id != source.benchmark_id or claim.benchmark_id != source.benchmark_id:
        return _claim_reject("BENCHMARK_SOURCE_MISMATCH", "claim benchmark differs from the admitted source")

    locator = claim.evidence_location
    if not isinstance(locator, dict) or locator.get("type") not in policy["locator_types"]:
        return _claim_reject("EVIDENCE_LOCATOR_UNSUPPORTED", "claim locator is not approved for this source revision")
    if not _locator_matches_contract(locator, policy):
        return _claim_reject(
            "EVIDENCE_LOCATOR_CONTRACT_MISMATCH",
            "claim locator does not match the exact source-revision evidence contract",
        )
    record, record_error = _evidence_record(raw_bytes, locator, parquet_resolver=parquet_resolver)
    if record_error:
        return _claim_reject(record_error, "claim evidence locator could not resolve one source record")
    assert record is not None
    for field_name, claim_value in (("model_raw", claim.model_raw), ("score_raw", claim.score_raw)):
        evidence_value, evidence_error = _field_value(record, locator, field_name)
        if evidence_error:
            return _claim_reject(evidence_error, f"{field_name} is not a typed source field")
        if evidence_value != claim_value:
            return _claim_reject("EVIDENCE_VALUE_MISMATCH", f"{field_name} differs from the located source record")

    for field_name, claim_value in (
        ("benchmark_raw", claim.benchmark_raw),
        ("metric_raw", claim.metric_raw),
        ("split_raw", claim.split_raw),
        ("setting_raw", claim.setting_raw),
        ("evaluation_version_raw", claim.evaluation_version_raw),
    ):
        dimension_error = _dimension_matches(
            field_name=field_name,
            claim_value=claim_value,
            policy=policy,
            record=record,
            locator=locator,
        )
        if dimension_error:
            return _claim_reject(dimension_error, f"{field_name} is not permitted by the source revision")

    numeric_policy = policy.get("numeric")
    if not isinstance(numeric_policy, dict):
        return _claim_reject("SRC_ADMISSION_CONTEXT_INVALID", "source admission numeric policy is missing")
    numeric_value, numeric_error = _strict_numeric(claim.score_raw, numeric_policy)
    if numeric_error:
        return _claim_reject(numeric_error, "score_raw is not a permitted finite source numeric value")
    assert numeric_value is not None
    if claim.score_unit != numeric_policy.get("score_unit"):
        return _claim_reject("SCORE_UNIT_UNDECLARED", "claim score unit differs from the admitted numeric policy")
    if claim.score_numeric is not None and not math.isclose(claim.score_numeric, numeric_value, rel_tol=0.0, abs_tol=0.0):
        return _claim_reject("SCORE_NUMERIC_MISMATCH", "adapter score_numeric differs from the exact raw numeric value")

    if model_match.status == "ambiguous":
        return _claim_quarantine(
            "MODEL_AMBIGUOUS",
            "model alias resolves to multiple entities; raw identity is retained without an entity id",
            score_numeric=numeric_value,
            score_unit=claim.score_unit,
        )
    if model_match.status != "matched":
        return _claim_quarantine(
            "MODEL_UNRESOLVED",
            "model identity is not registered; raw identity is retained without an entity id",
            score_numeric=numeric_value,
            score_unit=claim.score_unit,
        )
    if claim.model_entity_id != model_match.entity_id:
        return _claim_reject("MODEL_MAPPING_MISMATCH", "claim model entity does not match the unique resolver result")
    return ClaimAdmission(AdmissionVerdict("admit"), score_numeric=numeric_value, score_unit=claim.score_unit)
