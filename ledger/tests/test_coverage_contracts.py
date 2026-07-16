from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest
import yaml

from app.schemas.coverage_contracts import (
    CoverageContractError,
    canonical_json,
    contract_self_digest,
    discovery_candidate_fingerprint,
    validate_coverage_universe,
    validate_discovery_candidate,
    validate_discovery_target,
    verify_contract_self_digest,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = REPO_ROOT / "docs" / "contracts" / "examples"
UNIVERSE_EXAMPLE = EXAMPLES / "coverage-universe-v1.valid.json"
TARGET_EXAMPLE = EXAMPLES / "discovery-target-v1.valid.json"
CANDIDATE_EXAMPLE = EXAMPLES / "discovery-candidate-v1.valid.json"
REAL_UNIVERSE = REPO_ROOT / "ledger" / "app" / "registry" / "coverage_universe.yaml"
MODULE = REPO_ROOT / "ledger" / "app" / "schemas" / "coverage_contracts.py"


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _universe() -> dict:
    return _json(UNIVERSE_EXAMPLE)


def _target() -> dict:
    return _json(TARGET_EXAMPLE)


def _candidate() -> dict:
    return _json(CANDIDATE_EXAMPLE)


def _resign(payload: dict, *, fingerprint: bool = False) -> dict:
    if fingerprint:
        payload["candidateFingerprintSha256"] = discovery_candidate_fingerprint(payload)
    payload["manifest"]["contentSha256"] = contract_self_digest(payload)
    return payload


def _configured_target() -> dict:
    payload = _target()
    payload["configurationStatus"] = "configured"
    payload["decisionReference"] = "target-decision-example-v1"
    payload["reasonCode"] = "EXAMPLE_RECONNAISSANCE_APPROVED"
    payload["authority"]["approvalStatus"] = "reconnaissance_approved"
    payload["authority"]["permitsCandidateReconnaissance"] = True
    payload["termsReview"]["status"] = "reviewed_for_reconnaissance"
    payload["termsReview"]["reasonCode"] = "EXAMPLE_TERMS_REVIEWED"
    return _resign(payload)


@pytest.mark.parametrize(
    ("path", "validator"),
    [
        (UNIVERSE_EXAMPLE, validate_coverage_universe),
        (TARGET_EXAMPLE, validate_discovery_target),
        (CANDIDATE_EXAMPLE, validate_discovery_candidate),
    ],
)
def test_valid_contract_examples_pass(path: Path, validator) -> None:
    payload = _json(path)
    validator(payload)
    verify_contract_self_digest(payload)


def test_real_coverage_universe_passes_semantic_validation() -> None:
    payload = yaml.safe_load(REAL_UNIVERSE.read_text(encoding="utf-8"))

    validate_coverage_universe(payload)

    assert payload["manifest"]["benchmarkCount"] == 42
    assert payload["manifest"]["configuredSourceRouteCount"] == 53


def test_known_canonical_digests_and_candidate_fingerprint_match_examples() -> None:
    universe = _universe()
    target = _target()
    candidate = _candidate()

    assert contract_self_digest(universe) == universe["manifest"]["contentSha256"]
    assert contract_self_digest(target) == target["manifest"]["contentSha256"]
    assert contract_self_digest(candidate) == candidate["manifest"]["contentSha256"]
    assert discovery_candidate_fingerprint(candidate) == candidate["candidateFingerprintSha256"]


def test_canonical_json_sorts_mapping_keys_and_uses_ascii_compact_form() -> None:
    left = {"z": "café", "a": {"y": 2, "x": 1}}
    right = {"a": {"x": 1, "y": 2}, "z": "café"}

    assert canonical_json(left) == canonical_json(right)
    assert canonical_json(left) == '{"a":{"x":1,"y":2},"z":"caf\\u00e9"}'


def test_candidate_fingerprint_sorts_only_its_set_like_arrays() -> None:
    left = _candidate()
    left["officialUrls"].append("https://huggingface.co/datasets/bigcode/another-result")
    left["affectedBenchmarkIds"].append("another-benchmark")
    right = deepcopy(left)
    right["officialUrls"].reverse()
    right["affectedBenchmarkIds"].reverse()

    assert discovery_candidate_fingerprint(left) == discovery_candidate_fingerprint(right)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_numbers_are_rejected_before_digest_validation(value: float) -> None:
    payload = _target()
    payload["budgets"]["maxBytesPerResponse"] = value

    with pytest.raises(CoverageContractError, match="non-finite"):
        validate_discovery_target(payload)


@pytest.mark.parametrize("field", ["generatedAt", "lastModified", "sourceMtime"])
def test_mutable_timestamp_and_mtime_fields_are_rejected(field: str) -> None:
    payload = _universe()
    payload[field] = "2026-07-15T00:00:00Z"

    with pytest.raises(CoverageContractError, match="timestamps/mtimes"):
        validate_coverage_universe(payload)


@pytest.mark.parametrize(
    "input_path",
    [
        "/srv/hermes/registry.yaml",
        "C:\\registry\\benchmarks.yaml",
        "../registry/benchmarks.yaml",
        "file:///tmp/benchmarks.yaml",
    ],
)
def test_universe_registry_inputs_reject_absolute_or_unsafe_paths(input_path: str) -> None:
    payload = _universe()
    payload["scope"]["registryInputs"][0]["inputPath"] = input_path

    with pytest.raises(CoverageContractError, match="path|Path|relative"):
        validate_coverage_universe(payload)


@pytest.mark.parametrize(
    ("collection", "id_field", "change"),
    [
        ("cohorts", "cohortId", ("name", "Different cohort object")),
        ("benchmarks", "benchmarkId", ("reasonCode", "DIFFERENT_BENCHMARK_REASON")),
        ("configuredSourceRoutes", "sourceRouteId", ("reasonCode", "DIFFERENT_ROUTE_REASON")),
        ("sourceClasses", "sourceClassId", ("methodFamily", "Different source class object")),
        ("exclusions", "exclusionId", ("rationale", "Different exclusion object")),
    ],
)
def test_universe_rejects_duplicate_stable_ids_even_when_objects_differ(
    collection: str,
    id_field: str,
    change: tuple[str, str],
) -> None:
    payload = _universe()
    duplicate = deepcopy(payload[collection][0])
    duplicate[change[0]] = change[1]
    assert duplicate[id_field] == payload[collection][0][id_field]
    payload[collection].append(duplicate)
    count_key = {
        "benchmarks": "benchmarkCount",
        "configuredSourceRoutes": "configuredSourceRouteCount",
        "sourceClasses": "sourceClassCount",
        "exclusions": "exclusionCount",
    }.get(collection)
    if count_key is not None:
        payload["manifest"][count_key] += 1
    _resign(payload)

    with pytest.raises(CoverageContractError, match="duplicate stable ID"):
        validate_coverage_universe(payload)


@pytest.mark.parametrize(
    ("key", "delta"),
    [
        ("benchmarkCount", 1),
        ("configuredSourceRouteCount", 1),
        ("sourceClassCount", 1),
        ("exclusionCount", 1),
    ],
)
def test_universe_rejects_manifest_count_mismatches(key: str, delta: int) -> None:
    payload = _universe()
    payload["manifest"][key] += delta
    _resign(payload)

    with pytest.raises(CoverageContractError, match="payload contains"):
        validate_coverage_universe(payload)


def test_universe_rejects_missing_registry_input_denominator() -> None:
    payload = _universe()
    del payload["scope"]["registryInputs"][0]["expectedUniqueCount"]
    _resign(payload)

    with pytest.raises(CoverageContractError, match="missing keys.*expectedUniqueCount"):
        validate_coverage_universe(payload)


def test_universe_allows_registry_denominator_to_exceed_bounded_projection() -> None:
    payload = _universe()
    payload["scope"]["registryInputs"][0]["expectedUniqueCount"] = 2
    _resign(payload)

    validate_coverage_universe(payload)


def test_universe_rejects_omission_without_reason() -> None:
    payload = _universe()
    payload["benchmarks"][0]["coverageStatus"] = "omitted"
    del payload["benchmarks"][0]["reasonCode"]
    _resign(payload)

    with pytest.raises(CoverageContractError, match="missing keys.*reasonCode"):
        validate_coverage_universe(payload)


def test_universe_rejects_non_bidirectional_cohort_membership() -> None:
    payload = _universe()
    payload["cohorts"].append(
        {
            "cohortId": "second-cohort",
            "name": "Second",
            "purpose": "Adversarial membership",
            "memberBenchmarkIds": ["example_benchmark"],
        }
    )
    _resign(payload)

    with pytest.raises(CoverageContractError, match="not bidirectional"):
        validate_coverage_universe(payload)


def test_universe_rejects_route_to_missing_benchmark() -> None:
    payload = _universe()
    payload["configuredSourceRoutes"][0]["benchmarkId"] = "absent_benchmark"
    _resign(payload)

    with pytest.raises(CoverageContractError, match="unknown benchmark"):
        validate_coverage_universe(payload)


def test_universe_rejects_configured_benchmark_without_any_route_record() -> None:
    payload = _universe()
    payload["configuredSourceRoutes"] = []
    payload["manifest"]["configuredSourceRouteCount"] = 0
    _resign(payload)

    with pytest.raises(CoverageContractError, match="requires a configured or reasoned-omitted route"):
        validate_coverage_universe(payload)


def test_universe_accepts_reasoned_omitted_route_for_configured_benchmark() -> None:
    payload = _universe()
    payload["configuredSourceRoutes"][0]["coverageStatus"] = "omitted"
    payload["configuredSourceRoutes"][0]["reasonCode"] = "ROUTE_EXPLICITLY_OMITTED"
    _resign(payload)

    validate_coverage_universe(payload)


def test_universe_rejects_configured_route_to_omitted_benchmark() -> None:
    payload = _universe()
    payload["benchmarks"][0]["coverageStatus"] = "omitted"
    payload["benchmarks"][0]["reasonCode"] = "BENCHMARK_EXPLICITLY_OMITTED"
    _resign(payload)

    with pytest.raises(CoverageContractError, match="cannot target an omitted benchmark"):
        validate_coverage_universe(payload)


def test_universe_rejects_self_superseding_revision() -> None:
    payload = _universe()
    payload["supersedesUniverseRevisionId"] = payload["universeRevisionId"]
    _resign(payload)

    with pytest.raises(CoverageContractError, match="cannot supersede itself"):
        validate_coverage_universe(payload)


def test_universe_rejects_zero_duration_cadence() -> None:
    payload = _universe()
    payload["refreshPolicy"]["discoveryPlanningCadence"] = "PT0H"
    _resign(payload)

    with pytest.raises(CoverageContractError, match="greater than zero"):
        validate_coverage_universe(payload)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: payload.__setitem__("effectiveOn", "2026-07-15"),
        lambda payload: payload.__setitem__("decisionReference", "unapproved-decision"),
        lambda payload: payload["authority"].__setitem__("approvalStatus", "owner_approved"),
    ],
)
def test_universe_rejects_draft_approval_binding_contradictions(mutation) -> None:
    payload = _universe()
    mutation(payload)
    _resign(payload)

    with pytest.raises(CoverageContractError, match="draft|approved"):
        validate_coverage_universe(payload)


@pytest.mark.parametrize(
    "flag",
    ["certifiesSources", "authorizesCapture", "authorizesPublication", "frontendLoadable"],
)
@pytest.mark.parametrize(
    ("factory", "validator"),
    [
        (_universe, validate_coverage_universe),
        (_target, validate_discovery_target),
        (_candidate, validate_discovery_candidate),
    ],
)
def test_contracts_reject_authority_escalation_booleans(flag, factory, validator) -> None:
    payload = factory()
    payload["authority"][flag] = True
    _resign(payload)

    with pytest.raises(CoverageContractError, match=flag):
        validator(payload)


def test_target_valid_configured_binding_passes() -> None:
    validate_discovery_target(_configured_target())


@pytest.mark.parametrize(
    "url",
    [
        "http://benchmarks.example.org/example/",
        "https://user:secret@benchmarks.example.org/example/",
        "https://benchmarks.example.org/example/?page=1",
        "https://benchmarks.example.org/example/#result",
        "https://localhost/example/",
        "https://127.0.0.1/example/",
        "https://benchmarks.example.org:8443/example/",
        "https://benchmarks.example.org/%2e%2e/private/",
        "https://metadata/example/",
        "https://instance-data/example/",
        "https://2130706433/example/",
        "https://0x7f000001/example/",
        "https://127.1/example/",
        "https://0177.0000.0000.0001/example/",
        "https://0x7f.0x0.0x0.0x1/example/",
    ],
)
def test_target_rejects_unsafe_official_origin_urls(url: str) -> None:
    payload = _target()
    payload["officialOrigin"] = url
    _resign(payload)

    with pytest.raises(CoverageContractError):
        validate_discovery_target(payload)


@pytest.mark.parametrize(
    "host",
    [
        "metadata",
        "instance-data",
        "2130706433",
        "0x7f000001",
        "127.1",
        "0177.0000.0000.0001",
        "0x7f.0x0.0x0.0x1",
    ],
)
def test_target_rejects_single_label_and_legacy_numeric_allowed_hosts(host: str) -> None:
    payload = _target()
    payload["urlPolicy"]["allowedHosts"] = [host]
    _resign(payload)

    with pytest.raises(CoverageContractError, match="public-style|numeric/hex"):
        validate_discovery_target(payload)


def test_target_allows_reserved_dotted_invalid_hostname_for_offline_fixtures() -> None:
    payload = _target()
    payload["urlPolicy"]["allowedHosts"] = ["benchmarks.invalid"]
    payload["urlPolicy"]["allowedFinalUrlPatterns"] = ["https://benchmarks.invalid/example/"]
    payload["officialOrigin"] = "https://benchmarks.invalid/example/"
    _resign(payload)

    validate_discovery_target(payload)


def test_target_rejects_official_origin_host_mismatch() -> None:
    payload = _target()
    payload["officialOrigin"] = "https://other.example.org/example/"
    _resign(payload)

    with pytest.raises(CoverageContractError, match="absent from allowedHosts"):
        validate_discovery_target(payload)


def test_target_rejects_allowed_final_pattern_host_mismatch() -> None:
    payload = _target()
    payload["urlPolicy"]["allowedFinalUrlPatterns"][0] = "https://other.example.org/example/"
    _resign(payload)

    with pytest.raises(CoverageContractError, match="absent from allowedHosts"):
        validate_discovery_target(payload)


@pytest.mark.parametrize("collection", ["allowedHosts", "allowedFinalUrlPatterns"])
def test_target_rejects_duplicate_url_policy_entries(collection: str) -> None:
    payload = _target()
    payload["urlPolicy"][collection].append(payload["urlPolicy"][collection][0])
    manifest_key = "allowedHostCount" if collection == "allowedHosts" else "allowedFinalPatternCount"
    payload["manifest"][manifest_key] += 1
    _resign(payload)

    with pytest.raises(CoverageContractError, match="duplicates item"):
        validate_discovery_target(payload)


@pytest.mark.parametrize(
    "alias",
    [
        "https://BENCHMARKS.EXAMPLE.ORG/example/",
        "https://benchmarks.example.org:443/example/",
    ],
)
def test_target_rejects_noncanonical_alias_of_allowed_final_pattern(alias: str) -> None:
    payload = _target()
    payload["urlPolicy"]["allowedFinalUrlPatterns"].append(alias)
    payload["manifest"]["allowedFinalPatternCount"] += 1
    _resign(payload)

    with pytest.raises(CoverageContractError, match="canonical lowercase|explicit URL ports"):
        validate_discovery_target(payload)


def test_target_requires_explicit_root_path_for_canonical_url_spelling() -> None:
    payload = _target()
    payload["owner"]["officialRootUrl"] = "https://benchmarks.example.org"
    _resign(payload)

    with pytest.raises(CoverageContractError, match="explicit path"):
        validate_discovery_target(payload)


def test_target_rejects_duplicate_affected_benchmark_ids() -> None:
    payload = _target()
    payload["affectedBenchmarkIds"].append(payload["affectedBenchmarkIds"][0])
    payload["manifest"]["affectedBenchmarkCount"] += 1
    _resign(payload)

    with pytest.raises(CoverageContractError, match="duplicates item"):
        validate_discovery_target(payload)


@pytest.mark.parametrize(
    ("manifest_key", "value"),
    [
        ("affectedBenchmarkCount", 2),
        ("allowedHostCount", 2),
        ("allowedFinalPatternCount", 2),
    ],
)
def test_target_rejects_manifest_count_mismatches(manifest_key: str, value: int) -> None:
    payload = _target()
    payload["manifest"][manifest_key] = value
    _resign(payload)

    with pytest.raises(CoverageContractError, match="payload contains"):
        validate_discovery_target(payload)


def test_target_rejects_enabled_target_missing_decision() -> None:
    payload = _configured_target()
    payload["decisionReference"] = None
    _resign(payload)

    with pytest.raises(CoverageContractError, match="decision"):
        validate_discovery_target(payload)


def test_target_rejects_draft_with_approved_authority() -> None:
    payload = _target()
    payload["authority"]["approvalStatus"] = "reconnaissance_approved"
    payload["decisionReference"] = "target-decision-example-v1"
    _resign(payload)

    with pytest.raises(CoverageContractError, match="draft targets"):
        validate_discovery_target(payload)


def test_target_rejects_enabled_target_with_unreviewed_terms() -> None:
    payload = _configured_target()
    payload["termsReview"]["status"] = "review_required"
    payload["termsReview"]["reasonCode"] = "TERMS_REVIEW_REQUIRED"
    _resign(payload)

    with pytest.raises(CoverageContractError, match="reviewed terms"):
        validate_discovery_target(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("maxRequestsPerRun", 0),
        ("maxBytesPerResponse", 0),
        ("maxRedirects", -1),
        ("timeoutSeconds", 0),
        ("maxConcurrency", 0),
    ],
)
def test_target_rejects_nonpositive_or_invalid_budgets(field: str, value: int) -> None:
    payload = _configured_target()
    payload["budgets"][field] = value
    _resign(payload)

    with pytest.raises(CoverageContractError, match=field):
        validate_discovery_target(payload)


def test_target_rejects_concurrency_greater_than_request_budget() -> None:
    payload = _configured_target()
    payload["budgets"]["maxRequestsPerRun"] = 1
    payload["budgets"]["maxConcurrency"] = 2
    _resign(payload)

    with pytest.raises(CoverageContractError, match="cannot exceed"):
        validate_discovery_target(payload)


def test_candidate_rejects_candidate_type_identity_mismatch() -> None:
    payload = _candidate()
    payload["candidateType"] = "model_metadata"
    _resign(payload, fingerprint=True)

    with pytest.raises(CoverageContractError, match="must match candidateType"):
        validate_discovery_candidate(payload)


def test_candidate_rejects_fingerprint_mismatch_even_with_valid_self_digest() -> None:
    payload = _candidate()
    payload["candidateFingerprintSha256"] = "0" * 64
    _resign(payload)

    with pytest.raises(CoverageContractError, match="fingerprint mismatch"):
        validate_discovery_candidate(payload)


def test_candidate_rejects_duplicate_official_urls() -> None:
    payload = _candidate()
    payload["officialUrls"].append(payload["officialUrls"][0])
    payload["manifest"]["officialUrlCount"] += 1
    _resign(payload, fingerprint=True)

    with pytest.raises(CoverageContractError, match="duplicates item"):
        validate_discovery_candidate(payload)


@pytest.mark.parametrize(
    "alias",
    [
        "https://HUGGINGFACE.CO/datasets/bigcode/bigcodebench-results",
        "https://huggingface.co:443/datasets/bigcode/bigcodebench-results",
    ],
)
def test_candidate_rejects_noncanonical_alias_of_official_url(alias: str) -> None:
    payload = _candidate()
    payload["officialUrls"].append(alias)
    payload["manifest"]["officialUrlCount"] += 1
    _resign(payload, fingerprint=True)

    with pytest.raises(CoverageContractError, match="canonical lowercase|explicit URL ports"):
        validate_discovery_candidate(payload)


def test_candidate_rejects_duplicate_affected_benchmark_ids() -> None:
    payload = _candidate()
    payload["affectedBenchmarkIds"].append(payload["affectedBenchmarkIds"][0])
    payload["manifest"]["affectedBenchmarkCount"] += 1
    _resign(payload, fingerprint=True)

    with pytest.raises(CoverageContractError, match="duplicates item"):
        validate_discovery_candidate(payload)


def test_candidate_rejects_duplicate_evidence_ids_even_when_objects_differ() -> None:
    payload = _candidate()
    duplicate = deepcopy(payload["evidenceReferences"][0])
    duplicate["evidenceType"] = "official_metadata"
    payload["evidenceReferences"].append(duplicate)
    payload["manifest"]["evidenceReferenceCount"] += 1
    _resign(payload)

    with pytest.raises(CoverageContractError, match="duplicate stable ID"):
        validate_discovery_candidate(payload)


@pytest.mark.parametrize(
    ("manifest_key", "value"),
    [
        ("officialUrlCount", 2),
        ("affectedBenchmarkCount", 2),
        ("evidenceReferenceCount", 2),
    ],
)
def test_candidate_rejects_manifest_count_mismatches(manifest_key: str, value: int) -> None:
    payload = _candidate()
    payload["manifest"][manifest_key] = value
    _resign(payload)

    with pytest.raises(CoverageContractError, match="payload contains"):
        validate_discovery_candidate(payload)


def test_candidate_rejects_observed_state_with_decision_reference() -> None:
    payload = _candidate()
    payload["state"] = "observed"
    _resign(payload)

    with pytest.raises(CoverageContractError, match="observed candidates"):
        validate_discovery_candidate(payload)


def test_candidate_rejects_post_observation_state_without_decision() -> None:
    payload = _candidate()
    payload["stateDecisionReference"] = None
    _resign(payload)

    with pytest.raises(CoverageContractError, match="post-observation"):
        validate_discovery_candidate(payload)


def test_candidate_rejects_approved_state_without_source_revision_reference() -> None:
    payload = _candidate()
    payload["state"] = "approved_as_source_revision"
    _resign(payload)

    with pytest.raises(CoverageContractError, match="approved source revision"):
        validate_discovery_candidate(payload)


def test_candidate_rejects_approval_reference_outside_final_state() -> None:
    payload = _candidate()
    payload["approvedSourceRevisionReference"] = "official-source-revision-v2"
    _resign(payload)

    with pytest.raises(CoverageContractError, match="forbidden outside"):
        validate_discovery_candidate(payload)


def test_candidate_accepts_fully_bound_approved_source_state() -> None:
    payload = _candidate()
    payload["state"] = "approved_as_source_revision"
    payload["approvedSourceRevisionReference"] = "official-source-revision-v2"
    payload["reasonCode"] = "SOURCE_REVISION_APPROVED"
    _resign(payload)

    validate_discovery_candidate(payload)


def test_candidate_rejects_source_identity_benchmark_outside_affected_ids() -> None:
    payload = _candidate()
    payload["candidateIdentity"]["benchmarkId"] = "different-benchmark"
    _resign(payload, fingerprint=True)

    with pytest.raises(CoverageContractError, match="must appear"):
        validate_discovery_candidate(payload)


def test_self_digest_mismatch_is_rejected_after_semantic_validation() -> None:
    payload = _target()
    payload["owner"]["displayName"] = "Tampered after signing"

    with pytest.raises(CoverageContractError, match="self-digest mismatch"):
        validate_discovery_target(payload)


def test_validator_module_imports_only_python_standard_library() -> None:
    # Keep this implementation deployable in the CLI without jsonschema or a
    # new runtime dependency.  Relative/package imports would also fail here.
    import ast

    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    imported_roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".")[0])

    assert imported_roots <= sys.stdlib_module_names | {"__future__"}
    assert "jsonschema" not in imported_roots
