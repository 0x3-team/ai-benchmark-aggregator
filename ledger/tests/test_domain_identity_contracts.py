from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest

from app.schemas.domain_identity_contracts import (
    DomainIdentityContractError,
    benchmark_definition_fingerprint,
    canonical_json,
    contract_self_digest,
    evaluation_subject_observed_composition_fingerprint,
    evaluation_subject_fingerprint,
    identity_decision_item_fingerprint,
    raw_identity_label_sha256,
    validate_benchmark_definition_revision,
    validate_benchmark_revision_chain,
    validate_evaluation_subject,
    validate_evaluation_subject_graph,
    validate_evaluation_subject_revision_chain,
    validate_identity_decision,
    validate_identity_decision_chain,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = REPO_ROOT / "docs" / "contracts"
EXAMPLES = CONTRACTS / "examples"
MODULE = REPO_ROOT / "ledger" / "app" / "schemas" / "domain_identity_contracts.py"

BENCHMARK_SCHEMA = CONTRACTS / "benchmark-definition-revision-v1.schema.json"
SUBJECT_SCHEMA = CONTRACTS / "evaluation-subject-v1.schema.json"
DECISION_SCHEMA = CONTRACTS / "identity-decision-v1.schema.json"
BENCHMARK_EXAMPLE = EXAMPLES / "benchmark-definition-revision-v1.valid.json"
SUBJECT_EXAMPLE = EXAMPLES / "evaluation-subject-v1.valid.json"
DECISION_EXAMPLE = EXAMPLES / "identity-decision-v1.valid.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _benchmark() -> dict:
    return _load(BENCHMARK_EXAMPLE)


def _subject() -> dict:
    return _load(SUBJECT_EXAMPLE)


def _decision() -> dict:
    return _load(DECISION_EXAMPLE)


def _self_resign(payload: dict) -> dict:
    payload["manifest"]["contentSha256"] = contract_self_digest(payload)
    return payload


def _resign_benchmark(payload: dict) -> dict:
    payload["manifest"]["dimensionFingerprintSha256"] = benchmark_definition_fingerprint(payload)
    return _self_resign(payload)


def _resign_subject(payload: dict) -> dict:
    payload["observedCompositionFingerprintSha256"] = (
        evaluation_subject_observed_composition_fingerprint(payload)
    )
    payload["subjectFingerprintSha256"] = evaluation_subject_fingerprint(payload)
    return _self_resign(payload)


def _resign_decision(payload: dict, *, raw_label: bool = False) -> dict:
    if raw_label:
        payload["rawObservation"]["rawLabelSha256"] = raw_identity_label_sha256(
            payload["rawObservation"]["modelRaw"]
        )
    payload["identityItemFingerprintSha256"] = identity_decision_item_fingerprint(payload)
    return _self_resign(payload)


def _rename_revision(parent: dict, revision_id: str, name: str = "Renamed Example") -> dict:
    child = deepcopy(parent)
    child["benchmarkDefinitionRevisionId"] = revision_id
    child["supersedesDefinitionRevisionId"] = parent["benchmarkDefinitionRevisionId"]
    child["identity"]["editionDisplayName"] = name
    child["changeControl"] = {
        "changeType": "display_rename",
        "identityDisposition": "preserve_edition_identity",
        "priorBenchmarkEditionId": parent["benchmarkEditionId"],
        "compatibilityImpact": "display_only",
        "reasonCode": "DISPLAY_NAME_REVIEWED_SEPARATELY",
    }
    return _resign_benchmark(child)


def _new_edition_revision(parent: dict) -> dict:
    child = deepcopy(parent)
    child["benchmarkDefinitionRevisionId"] = "example-benchmark-definition-v2"
    child["supersedesDefinitionRevisionId"] = parent["benchmarkDefinitionRevisionId"]
    child["benchmarkEditionId"] = "example-benchmark-edition-v2"
    child["identity"]["canonicalBenchmarkId"] = "example-benchmark-edition-v2"
    child["identity"]["editionDisplayName"] = "Example Benchmark 2027"
    child["identity"]["editionVersionRaw"] = "2027"
    child["displayContract"]["benchmarkId"] = "example-benchmark-edition-v2"
    child["changeControl"] = {
        "changeType": "new_edition",
        "identityDisposition": "new_edition_identity",
        "priorBenchmarkEditionId": parent["benchmarkEditionId"],
        "compatibilityImpact": "incompatible_new_identity",
        "reasonCode": "NEW_OWNER_DEFINED_EDITION",
    }
    return _resign_benchmark(child)


def _approved_benchmark() -> dict:
    payload = _benchmark()
    payload["lifecycleStatus"] = "approved"
    payload["decisionReference"] = "benchmark-definition-approval-v1"
    payload["authority"]["approvalStatus"] = "definition_approved"
    payload["effectivePeriod"] = {
        "status": "effective",
        "effectiveFrom": "2026-07-15",
        "effectiveThrough": None,
    }
    return _self_resign(payload)


def _proposed_component(
    link_id: str,
    role: str,
    raw: str,
    *,
    ordinal: int | None = None,
) -> dict:
    return {
        "componentLinkId": link_id,
        "role": role,
        "componentSubjectId": None,
        "componentRaw": raw,
        "resolutionStatus": "unresolved",
        "reviewStatus": "proposed",
        "mappingDecisionReference": None,
        "evidenceReferenceIds": ["example-submission-observation"],
        "ordinal": ordinal,
    }


def _reviewed_subject(subject_type: str, subject_id: str | None = None) -> dict:
    payload = _subject()
    subject_id = subject_id or f"example-{subject_type.replace('_', '-')}-subject"
    payload["subjectRevisionId"] = f"{subject_id}-revision-v1"
    payload["subjectId"] = subject_id
    payload["lifecycleStatus"] = "reviewed"
    payload["decisionReference"] = f"{subject_id}-review-decision"
    payload["reasonCode"] = "TYPE_IDENTITY_REVIEWED"
    payload["subjectType"] = subject_type
    payload["resolutionStatus"] = "resolved"
    payload["authority"]["reviewStatus"] = "identity_reviewed"
    payload["displayIdentity"]["modelEntityId"] = subject_id
    payload["displayIdentity"]["entityType"] = subject_type
    payload["displayIdentity"]["displayName"] = f"Reviewed {subject_type}"
    payload["components"] = []
    payload["baseModelMapping"] = {
        "status": "unresolved",
        "componentLinkId": None,
        "decisionReference": None,
        "fabricated": False,
    }
    if subject_type == "base_model":
        payload["typeDetails"] = {
            "detailType": "base_model",
            "modelVersionRaw": "model-version-1",
        }
        payload["baseModelMapping"]["status"] = "not_applicable"
    elif subject_type == "versioned_endpoint":
        payload["typeDetails"] = {
            "detailType": "versioned_endpoint",
            "endpointRaw": "example-endpoint",
            "endpointVersionRaw": "2026-07-15",
        }
    elif subject_type == "agent_model_system":
        payload["typeDetails"] = {
            "detailType": "agent_model_system",
            "agentRaw": "Example Agent",
            "systemVersionRaw": "system-v1",
        }
        payload["components"] = [
            _proposed_component("agent-base-model", "base_model", "Undisclosed Model"),
            _proposed_component("agent-harness", "harness", "Example Harness 1.0"),
        ]
        payload["baseModelMapping"] = {
            "status": "proposed",
            "componentLinkId": "agent-base-model",
            "decisionReference": None,
            "fabricated": False,
        }
    elif subject_type == "ensemble":
        payload["typeDetails"] = {"detailType": "ensemble", "routingRaw": "majority vote"}
        payload["components"] = [
            _proposed_component("ensemble-member-a", "member", "Member A", ordinal=0),
            _proposed_component("ensemble-member-b", "member", "Member B", ordinal=1),
        ]
    elif subject_type == "opaque_submission":
        payload["typeDetails"] = {
            "detailType": "opaque_submission",
            "submissionRaw": "Opaque Team Submission",
        }
    else:
        raise AssertionError(f"unsupported reviewed subject type {subject_type}")
    payload["manifest"]["componentLinkCount"] = len(payload["components"])
    return _resign_subject(payload)


def _unresolved_unknown_subject() -> dict:
    payload = _subject()
    payload["subjectRevisionId"] = "example-unknown-subject-revision-v1"
    payload["subjectId"] = "example-unknown-subject"
    payload["subjectType"] = "unknown_unresolved"
    payload["resolutionStatus"] = "unresolved"
    payload["displayIdentity"]["modelEntityId"] = None
    payload["displayIdentity"]["entityType"] = "unknown_unresolved"
    payload["displayIdentity"]["displayName"] = "Unmatched exact raw label"
    payload["typeDetails"] = {
        "detailType": "unknown_unresolved",
        "uncertaintyNote": "No unique exact, case-insensitive, or normalized match.",
    }
    payload["components"] = []
    payload["manifest"]["componentLinkCount"] = 0
    return _resign_subject(payload)


def _subject_revision(parent: dict, revision_id: str) -> dict:
    child = deepcopy(parent)
    child["subjectRevisionId"] = revision_id
    child["supersedesSubjectRevisionId"] = parent["subjectRevisionId"]
    return _resign_subject(child)


def _effective_decision(
    root: dict | None = None,
    *,
    decision_id: str = "example-identity-decision-effective-v1",
    outcome: str = "unresolved",
    selected_subject_id: str | None = None,
    decided_at: str = "2026-07-15T12:00:00Z",
) -> dict:
    payload = deepcopy(root) if root is not None else _decision()
    payload["decisionId"] = decision_id
    payload["decisionStatus"] = "effective"
    payload["decidedAt"] = decided_at
    payload["governanceDecisionReference"] = f"{decision_id}-governance"
    payload["outcome"] = outcome
    payload["selectedSubjectId"] = selected_subject_id
    payload["supersedingCandidateReference"] = None
    payload["reasonCode"] = "ITEMIZED_IDENTITY_REVIEW_COMPLETE"
    payload["actor"] = {
        "actorId": "identity-reviewer",
        "actorType": "human",
        "role": "model-registry-steward",
        "authorityReference": "identity-review-charter-v1",
    }
    payload["authority"]["approvalStatus"] = "identity_reviewed"
    payload["authority"]["actorAuthorityVerified"] = True
    payload["authority"]["permitsIdentityReadProjection"] = True
    payload["aliasProposal"]["proposedAction"] = (
        "add_scoped_alias" if outcome == "resolved" else "no_alias"
    )
    if outcome == "rejected":
        payload["aliasProposal"]["proposedAction"] = "reject_alias"
    if outcome == "superseded":
        payload["supersedingCandidateReference"] = "replacement-candidate-v1"
    payload["effects"]["identityReadProjectionEffect"] = (
        "set_selected_subject" if outcome == "resolved" else "clear_selected_subject"
    )
    return _resign_decision(payload)


def _decision_child(
    parent: dict,
    decision_id: str,
    *,
    decided_at: str = "2026-07-15T12:00:00Z",
) -> dict:
    child = _effective_decision(
        parent,
        decision_id=decision_id,
        outcome="unresolved",
        decided_at=decided_at,
    )
    child["expectedPriorDecisionId"] = parent["decisionId"]
    child["decisionSequence"] = parent["decisionSequence"] + 1
    return _resign_decision(child)


def _collision_decision(kind: str) -> dict:
    payload = _effective_decision(outcome="unresolved")
    status, priority, method = {
        "exact": ("exact_collision", "exact", "exact"),
        "case": ("case_insensitive_collision", "case_insensitive", "case_insensitive"),
        "normalized": ("normalized_collision", "normalized", "normalized"),
    }[kind]
    payload["aliasProposal"]["matchMethod"] = method
    payload["aliasProposal"]["normalizedAlias"] = (
        None if kind == "exact" else "team example submission 17"
    )
    payload["collisionFacts"] = {
        "status": status,
        "matchingPriority": priority,
        "conflictingSubjectIds": ["subject-collision-a", "subject-collision-b"],
        "reasonCode": "ALIAS_MATCH_COLLISION",
    }
    payload["manifest"]["collisionSubjectCount"] = 2
    return _resign_decision(payload)


@pytest.mark.parametrize(
    ("schema_path", "policy"),
    [
        (BENCHMARK_SCHEMA, "benchmark-definition-revision-v1"),
        (SUBJECT_SCHEMA, "evaluation-subject-v1"),
        (DECISION_SCHEMA, "identity-decision-v1"),
    ],
)
def test_contract_schemas_are_draft_2020_12_json_with_resolvable_local_refs(
    schema_path: Path, policy: str
) -> None:
    schema = _load(schema_path)
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["properties"]["policyVersion"]["const"] == policy

    def walk(value):
        if isinstance(value, dict):
            reference = value.get("$ref")
            if isinstance(reference, str) and reference.startswith("#/$defs/"):
                assert reference.removeprefix("#/$defs/") in schema["$defs"]
            for nested in value.values():
                walk(nested)
        elif isinstance(value, list):
            for nested in value:
                walk(nested)

    walk(schema)


@pytest.mark.parametrize(
    ("path", "validator"),
    [
        (BENCHMARK_EXAMPLE, validate_benchmark_definition_revision),
        (SUBJECT_EXAMPLE, validate_evaluation_subject),
        (DECISION_EXAMPLE, validate_identity_decision),
    ],
)
def test_valid_draft_local_examples_pass(path: Path, validator) -> None:
    payload = _load(path)
    validator(payload)
    assert payload["manifest"]["contentSha256"] == contract_self_digest(payload)


def test_examples_confer_no_activation_review_publication_or_frontend_authority() -> None:
    benchmark = _benchmark()
    subject = _subject()
    decision = _decision()

    assert benchmark["lifecycleStatus"] == "draft"
    assert benchmark["authority"]["approvalStatus"] == "draft_unapproved"
    assert subject["lifecycleStatus"] == "draft"
    assert subject["authority"]["reviewStatus"] == "draft_unreviewed"
    assert decision["decisionStatus"] == "draft"
    assert decision["authority"]["permitsIdentityReadProjection"] is False
    assert decision["decidedAt"] is None
    assert decision["effects"]["identityReadProjectionEffect"] == "none"
    assert all(
        payload["authority"][key] is False
        for payload, keys in [
            (benchmark, ["certifiesSources", "authorizesCapture", "authorizesPublication", "frontendLoadable"]),
            (subject, ["establishesClaimMapping", "rewritesClaims", "promotesValidation", "authorizesPublication", "frontendLoadable"]),
            (decision, ["rewritesClaims", "promotesCapture", "promotesValidation", "authorizesPublication", "frontendLoadable"]),
        ]
        for key in keys
    )


def test_benchmark_contract_pins_exact_six_display_dimensions_and_separate_score_unit() -> None:
    payload = _benchmark()
    assert payload["displayContract"]["identityDimensions"] == [
        "modelId", "benchmarkId", "metric", "split", "setting", "evaluationVersion"
    ]
    assert payload["displayContract"]["scoreUnitIsSeparateProvenance"] is True
    assert payload["displayContract"]["benchmarkId"] == payload["benchmarkEditionId"]


def test_benchmark_rejects_mutated_display_dimension_contract() -> None:
    payload = _benchmark()
    payload["displayContract"]["identityDimensions"][-1] = "scoreUnit"
    _resign_benchmark(payload)

    with pytest.raises(DomainIdentityContractError, match="identityDimensions"):
        validate_benchmark_definition_revision(payload)


def test_benchmark_draft_cannot_carry_approval_decision() -> None:
    payload = _benchmark()
    payload["decisionReference"] = "definition-approval-decision"
    _self_resign(payload)

    with pytest.raises(DomainIdentityContractError, match="draft definition"):
        validate_benchmark_definition_revision(payload)


def test_benchmark_effective_period_is_explicit_and_clock_free() -> None:
    draft = _benchmark()
    approved = _approved_benchmark()

    validate_benchmark_definition_revision(draft)
    validate_benchmark_definition_revision(approved)

    assert draft["effectivePeriod"] == {
        "status": "not_effective",
        "effectiveFrom": None,
        "effectiveThrough": None,
    }
    assert approved["effectivePeriod"] == {
        "status": "effective",
        "effectiveFrom": "2026-07-15",
        "effectiveThrough": None,
    }


def test_benchmark_draft_cannot_claim_an_effective_date() -> None:
    payload = _benchmark()
    payload["effectivePeriod"] = {
        "status": "effective",
        "effectiveFrom": "2026-07-15",
        "effectiveThrough": None,
    }
    _self_resign(payload)

    with pytest.raises(DomainIdentityContractError, match="explicitly not effective"):
        validate_benchmark_definition_revision(payload)


@pytest.mark.parametrize(
    "effective_from",
    ["2026-7-15", "2026-02-30", "2026-07-15T00:00:00Z"],
)
def test_benchmark_effective_start_requires_canonical_valid_iso_date(
    effective_from: str,
) -> None:
    payload = _approved_benchmark()
    payload["effectivePeriod"]["effectiveFrom"] = effective_from
    _self_resign(payload)

    with pytest.raises(DomainIdentityContractError, match="canonical ISO date"):
        validate_benchmark_definition_revision(payload)


@pytest.mark.parametrize("lifecycle", ["superseded", "retired"])
def test_ended_benchmark_definition_requires_ordered_bounded_period(
    lifecycle: str,
) -> None:
    payload = _approved_benchmark()
    payload["lifecycleStatus"] = lifecycle
    payload["effectivePeriod"] = {
        "status": "ended",
        "effectiveFrom": "2026-07-15",
        "effectiveThrough": "2026-07-14",
    }
    _self_resign(payload)

    with pytest.raises(DomainIdentityContractError, match="on or after"):
        validate_benchmark_definition_revision(payload)


def test_effective_period_changes_self_digest_but_not_dimension_identity() -> None:
    first = _approved_benchmark()
    second = deepcopy(first)
    second["effectivePeriod"]["effectiveFrom"] = "2026-07-16"
    _self_resign(second)

    validate_benchmark_definition_revision(first)
    validate_benchmark_definition_revision(second)

    assert benchmark_definition_fingerprint(first) == benchmark_definition_fingerprint(second)
    assert first["manifest"]["contentSha256"] != second["manifest"]["contentSha256"]


def test_display_rename_preserves_edition_and_dimension_fingerprint() -> None:
    parent = _benchmark()
    child = _rename_revision(parent, "example-benchmark-definition-v1-rename")

    validate_benchmark_revision_chain([parent, child])

    assert child["benchmarkEditionId"] == parent["benchmarkEditionId"]
    assert child["manifest"]["dimensionFingerprintSha256"] == parent["manifest"]["dimensionFingerprintSha256"]


def test_new_edition_requires_new_identity_and_fingerprint() -> None:
    parent = _benchmark()
    child = _new_edition_revision(parent)

    validate_benchmark_revision_chain([parent, child])

    assert child["benchmarkEditionId"] != parent["benchmarkEditionId"]
    assert child["manifest"]["dimensionFingerprintSha256"] != parent["manifest"]["dimensionFingerprintSha256"]


@pytest.mark.parametrize("change", ["metric", "split", "setting", "evaluation_version", "unit"])
def test_benchmark_side_dimension_change_cannot_hide_as_rename(change: str) -> None:
    parent = _benchmark()
    child = _rename_revision(parent, f"example-{change}-silent-change")
    if change == "metric":
        child["dimensions"]["metrics"][0]["direction"] = "lower_is_better"
    elif change == "split":
        child["dimensions"]["splits"][0]["splitId"] = "private-test"
        child["dimensions"]["comparisonCells"][0]["splitId"] = "private-test"
    elif change == "setting":
        child["dimensions"]["settings"][0]["settingId"] = "tool-enabled"
        child["dimensions"]["comparisonCells"][0]["settingId"] = "tool-enabled"
    elif change == "evaluation_version":
        child["dimensions"]["evaluationVersions"][0]["evaluatorVersionRaw"] = "2.0"
    else:
        child["dimensions"]["units"][0]["scaleDescription"] = "Fraction from zero to one."
    _resign_benchmark(child)

    validate_benchmark_definition_revision(child)
    with pytest.raises(DomainIdentityContractError, match="rename/correction changed"):
        validate_benchmark_revision_chain([parent, child])


def test_definition_correction_cannot_hide_metric_semantics_change() -> None:
    parent = _benchmark()
    child = _rename_revision(parent, "example-correction-with-metric-change")
    child["changeControl"].update(
        {
            "changeType": "definition_correction",
            "compatibilityImpact": "definition_metadata_only",
            "reasonCode": "CLAIMED_METADATA_ONLY_CORRECTION",
        }
    )
    child["dimensions"]["metrics"][0]["direction"] = "lower_is_better"
    _resign_benchmark(child)

    with pytest.raises(DomainIdentityContractError, match="rename/correction changed"):
        validate_benchmark_revision_chain([parent, child])


def test_incompatible_change_cannot_reuse_prior_edition_id() -> None:
    payload = _rename_revision(_benchmark(), "metric-change-same-edition")
    payload["changeControl"].update(
        {
            "changeType": "metric_change",
            "identityDisposition": "new_edition_identity",
            "compatibilityImpact": "incompatible_new_identity",
        }
    )
    _resign_benchmark(payload)

    with pytest.raises(DomainIdentityContractError, match="cannot silently reuse"):
        validate_benchmark_definition_revision(payload)


def test_suite_subset_relationship_remains_distinct_and_cannot_self_reference() -> None:
    payload = _benchmark()
    assert payload["relationships"][0]["relationshipType"] == "subset_of"
    payload["relationships"][0]["relatedBenchmarkEditionId"] = payload["benchmarkEditionId"]
    _resign_benchmark(payload)

    with pytest.raises(DomainIdentityContractError, match="cannot reference itself"):
        validate_benchmark_definition_revision(payload)


def test_semantically_duplicate_suite_relationship_is_rejected() -> None:
    payload = _benchmark()
    duplicate = deepcopy(payload["relationships"][0])
    duplicate["relationshipId"] = "different-link-id"
    payload["relationships"].append(duplicate)
    payload["manifest"]["relationshipCount"] = 2
    _resign_benchmark(payload)

    with pytest.raises(DomainIdentityContractError, match="duplicate suite/subset"):
        validate_benchmark_definition_revision(payload)


def test_duplicate_benchmark_side_display_cell_is_rejected_even_with_new_cell_id() -> None:
    payload = _benchmark()
    duplicate = deepcopy(payload["dimensions"]["comparisonCells"][0])
    duplicate["comparisonCellId"] = "different-id-same-display-cell"
    payload["dimensions"]["comparisonCells"].append(duplicate)
    payload["sourceContractCompatibility"]["allowedComparisonCellIds"].append(
        "different-id-same-display-cell"
    )
    payload["manifest"]["comparisonCellCount"] = 2
    _resign_benchmark(payload)

    with pytest.raises(DomainIdentityContractError, match="duplicate five-part"):
        validate_benchmark_definition_revision(payload)


def test_source_compatibility_must_account_for_every_exact_comparison_cell() -> None:
    payload = _benchmark()
    payload["sourceContractCompatibility"]["allowedComparisonCellIds"] = ["unknown-cell"]
    _resign_benchmark(payload)

    with pytest.raises(DomainIdentityContractError, match="every and only"):
        validate_benchmark_definition_revision(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("bindsClaimsToExactDefinitionRevision", False),
        ("retainsPriorClaimBindings", False),
        ("rewritesExistingClaims", True),
        ("requiresAppendOnlyCorrection", False),
        ("allowsIdentityFallback", True),
    ],
)
def test_benchmark_old_claim_retention_cannot_be_weakened(field: str, value: bool) -> None:
    payload = _benchmark()
    payload["claimRetention"][field] = value
    _self_resign(payload)

    with pytest.raises(DomainIdentityContractError, match=field):
        validate_benchmark_definition_revision(payload)


def test_benchmark_supersession_branch_is_rejected() -> None:
    parent = _benchmark()
    first = _rename_revision(parent, "rename-branch-a", "Rename A")
    second = _rename_revision(parent, "rename-branch-b", "Rename B")

    with pytest.raises(DomainIdentityContractError, match="branched"):
        validate_benchmark_revision_chain([parent, first, second])


def test_benchmark_supersession_loop_is_rejected() -> None:
    parent = _benchmark()
    first = _rename_revision(parent, "rename-loop-a")
    second = _rename_revision(parent, "rename-loop-b")
    first["supersedesDefinitionRevisionId"] = second["benchmarkDefinitionRevisionId"]
    second["supersedesDefinitionRevisionId"] = first["benchmarkDefinitionRevisionId"]
    _self_resign(first)
    _self_resign(second)

    with pytest.raises(DomainIdentityContractError, match="root|loop"):
        validate_benchmark_revision_chain([first, second])


def test_benchmark_fingerprint_is_stable_under_set_like_reordering() -> None:
    left = _benchmark()
    left["dimensions"]["splits"].append({"splitId": "validation", "displayName": "Validation"})
    left["dimensions"]["comparisonCells"].append(
        {
            **deepcopy(left["dimensions"]["comparisonCells"][0]),
            "comparisonCellId": "accuracy-validation-standard-v1",
            "splitId": "validation",
        }
    )
    left["sourceContractCompatibility"]["allowedComparisonCellIds"].append(
        "accuracy-validation-standard-v1"
    )
    left["manifest"]["splitCount"] = 2
    left["manifest"]["comparisonCellCount"] = 2
    _resign_benchmark(left)
    right = deepcopy(left)
    right["dimensions"]["splits"].reverse()
    right["dimensions"]["comparisonCells"].reverse()
    right["sourceContractCompatibility"]["allowedComparisonCellIds"].reverse()
    _resign_benchmark(right)

    assert benchmark_definition_fingerprint(left) == benchmark_definition_fingerprint(right)
    validate_benchmark_definition_revision(left)
    validate_benchmark_definition_revision(right)


@pytest.mark.parametrize("subject_type", ["base_model", "versioned_endpoint", "agent_model_system", "ensemble", "opaque_submission"])
def test_typed_top_level_evaluation_subject_variants_pass(subject_type: str) -> None:
    payload = _reviewed_subject(subject_type)

    validate_evaluation_subject(payload)

    assert payload["displayIdentity"]["modelEntityId"] == payload["subjectId"]
    assert payload["displayIdentity"]["entityType"] == subject_type


def test_unmatched_subject_preserves_raw_label_and_null_model_identity() -> None:
    payload = _unresolved_unknown_subject()
    original_raw = payload["rawSourceIdentity"]["modelRaw"]

    validate_evaluation_subject(payload)

    assert payload["rawSourceIdentity"]["modelRaw"] == original_raw
    assert payload["displayIdentity"]["modelEntityId"] is None
    assert payload["resolutionStatus"] == "unresolved"


def test_unresolved_subject_cannot_expose_canonical_model_id() -> None:
    payload = _unresolved_unknown_subject()
    payload["displayIdentity"]["modelEntityId"] = payload["subjectId"]
    _self_resign(payload)

    with pytest.raises(DomainIdentityContractError, match="null canonical"):
        validate_evaluation_subject(payload)


def test_subject_type_and_type_details_cannot_disagree() -> None:
    payload = _subject()
    payload["subjectType"] = "base_model"
    payload["displayIdentity"]["entityType"] = "base_model"
    _resign_subject(payload)

    with pytest.raises(DomainIdentityContractError, match="must match subjectType"):
        validate_evaluation_subject(payload)


def test_subject_raw_identity_cannot_claim_normalization() -> None:
    payload = _subject()
    payload["rawSourceIdentity"]["normalizationApplied"] = True
    _self_resign(payload)

    with pytest.raises(DomainIdentityContractError, match="normalizationApplied"):
        validate_evaluation_subject(payload)


def test_agent_retains_model_and_harness_as_components_not_top_level_model() -> None:
    payload = _reviewed_subject("agent_model_system", "example-agent-system")
    validate_evaluation_subject(payload)

    assert payload["displayIdentity"]["modelEntityId"] == "example-agent-system"
    assert {component["role"] for component in payload["components"]} == {"base_model", "harness"}
    assert all(component["componentSubjectId"] is None for component in payload["components"])


def test_agent_can_reference_reviewed_base_model_without_collapsing_top_level_identity() -> None:
    base_model = _reviewed_subject("base_model", "reviewed-base-model")
    agent = _reviewed_subject("agent_model_system", "reviewed-agent-system")
    component = agent["components"][0]
    component.update(
        {
            "componentSubjectId": "reviewed-base-model",
            "resolutionStatus": "resolved",
            "reviewStatus": "reviewed",
            "mappingDecisionReference": "agent-base-component-decision",
        }
    )
    agent["baseModelMapping"].update(
        {
            "status": "reviewed",
            "decisionReference": "agent-base-component-decision",
        }
    )
    _resign_subject(agent)

    validate_evaluation_subject_graph([base_model, agent])

    assert agent["displayIdentity"]["modelEntityId"] == "reviewed-agent-system"
    assert component["componentSubjectId"] == "reviewed-base-model"


def test_subject_revision_chain_allows_reviewed_component_resolution_enrichment() -> None:
    parent = _reviewed_subject("agent_model_system", "reviewed-agent-system")
    child = _subject_revision(parent, "reviewed-agent-system-revision-v2")
    child["components"][0].update(
        {
            "componentSubjectId": "reviewed-base-model",
            "resolutionStatus": "resolved",
            "reviewStatus": "reviewed",
            "mappingDecisionReference": "agent-base-component-decision",
        }
    )
    child["baseModelMapping"].update(
        {
            "status": "reviewed",
            "decisionReference": "agent-base-component-decision",
        }
    )
    child["provenanceReferences"].append(
        {
            "provenanceId": "agent-component-review-evidence",
            "provenanceType": "first_party_metadata",
            "referenceId": "agent-component-review-record",
            "contentSha256": None,
            "mappingAuthority": "context_only_not_identity_proof",
        }
    )
    child["components"][0]["evidenceReferenceIds"].append(
        "agent-component-review-evidence"
    )
    child["manifest"]["provenanceReferenceCount"] = 2
    _resign_subject(child)

    validate_evaluation_subject_revision_chain([parent, child])

    assert child["subjectId"] == parent["subjectId"]
    assert child["subjectType"] == parent["subjectType"]
    assert child["displayIdentity"]["modelEntityId"] == parent["displayIdentity"]["modelEntityId"]
    assert child["rawSourceIdentity"] == parent["rawSourceIdentity"]
    assert (
        child["observedCompositionFingerprintSha256"]
        == parent["observedCompositionFingerprintSha256"]
    )
    assert child["subjectFingerprintSha256"] != parent["subjectFingerprintSha256"]


@pytest.mark.parametrize(
    "composition_change",
    ["add", "remove", "role", "raw", "link"],
)
def test_subject_revision_chain_rejects_observed_component_composition_change(
    composition_change: str,
) -> None:
    parent = _reviewed_subject("agent_model_system", "reviewed-agent-system")
    if composition_change in {"remove", "role"}:
        parent["components"].append(
            _proposed_component(
                "agent-observed-tooling",
                "tooling",
                "Observed Tooling 1.0",
            )
        )
        parent["manifest"]["componentLinkCount"] = len(parent["components"])
        _resign_subject(parent)

    child = _subject_revision(parent, "reviewed-agent-system-revision-v2")
    if composition_change == "add":
        child["components"].append(
            _proposed_component(
                "agent-observed-tooling",
                "tooling",
                "Observed Tooling 1.0",
            )
        )
    elif composition_change == "remove":
        child["components"].pop()
    elif composition_change == "role":
        child["components"][-1]["role"] = "router"
    elif composition_change == "raw":
        child["components"][1]["componentRaw"] = "Substituted Harness 2.0"
    else:
        child["components"][1]["componentLinkId"] = "substituted-harness-link"
    child["manifest"]["componentLinkCount"] = len(child["components"])
    _resign_subject(child)

    validate_evaluation_subject(parent)
    validate_evaluation_subject(child)
    with pytest.raises(DomainIdentityContractError, match="observed component composition"):
        validate_evaluation_subject_revision_chain([parent, child])


def test_subject_rejects_false_observed_composition_fingerprint() -> None:
    payload = _reviewed_subject("agent_model_system", "reviewed-agent-system")
    payload["observedCompositionFingerprintSha256"] = "0" * 64
    _self_resign(payload)

    with pytest.raises(DomainIdentityContractError, match="observed composition fingerprint"):
        validate_evaluation_subject(payload)


def test_subject_revision_chain_rejects_duplicate_revision_id() -> None:
    parent = _reviewed_subject("base_model", "reviewed-base-model")

    with pytest.raises(DomainIdentityContractError, match="duplicate subject revision"):
        validate_evaluation_subject_revision_chain([parent, deepcopy(parent)])


def test_subject_revision_chain_rejects_missing_prior_revision() -> None:
    parent = _reviewed_subject("base_model", "reviewed-base-model")
    child = _subject_revision(parent, "reviewed-base-model-revision-v2")

    with pytest.raises(DomainIdentityContractError, match="stale/missing prior"):
        validate_evaluation_subject_revision_chain([child])


def test_subject_revision_chain_rejects_cross_subject_supersession() -> None:
    parent = _reviewed_subject("base_model", "reviewed-base-model-a")
    child = _reviewed_subject("base_model", "reviewed-base-model-b")
    child["subjectRevisionId"] = "reviewed-base-model-b-revision-v2"
    child["supersedesSubjectRevisionId"] = parent["subjectRevisionId"]
    _resign_subject(child)

    with pytest.raises(DomainIdentityContractError, match="cannot cross subjects"):
        validate_evaluation_subject_revision_chain([parent, child])


def test_subject_revision_chain_rejects_branches() -> None:
    parent = _reviewed_subject("base_model", "reviewed-base-model")
    first = _subject_revision(parent, "reviewed-base-model-revision-v2-a")
    second = _subject_revision(parent, "reviewed-base-model-revision-v2-b")

    with pytest.raises(DomainIdentityContractError, match="branched"):
        validate_evaluation_subject_revision_chain([parent, first, second])


def test_subject_revision_chain_rejects_cycles() -> None:
    parent = _reviewed_subject("base_model", "reviewed-base-model")
    child = _subject_revision(parent, "reviewed-base-model-revision-v2")
    parent["supersedesSubjectRevisionId"] = child["subjectRevisionId"]
    _resign_subject(parent)

    with pytest.raises(DomainIdentityContractError, match="revision cycle"):
        validate_evaluation_subject_revision_chain([parent, child])


def test_subject_revision_chain_requires_one_root_and_leaf() -> None:
    first = _reviewed_subject("base_model", "reviewed-base-model")
    second = _subject_revision(first, "reviewed-base-model-revision-v2")
    second["supersedesSubjectRevisionId"] = None
    _resign_subject(second)

    with pytest.raises(DomainIdentityContractError, match="one root and one leaf"):
        validate_evaluation_subject_revision_chain([first, second])


def test_subject_revision_chain_rejects_subject_type_change() -> None:
    parent = _reviewed_subject("agent_model_system", "reviewed-system")
    child = _reviewed_subject("ensemble", "reviewed-system")
    child["subjectRevisionId"] = "reviewed-system-revision-v2"
    child["supersedesSubjectRevisionId"] = parent["subjectRevisionId"]
    _resign_subject(child)

    with pytest.raises(DomainIdentityContractError, match="subjectType cannot change"):
        validate_evaluation_subject_revision_chain([parent, child])


def test_subject_revision_chain_preserves_exact_raw_source_identity() -> None:
    parent = _reviewed_subject("base_model", "reviewed-base-model")
    child = _subject_revision(parent, "reviewed-base-model-revision-v2")
    child["rawSourceIdentity"]["configurationRaw"] = "Different exact source configuration"
    _resign_subject(child)

    with pytest.raises(DomainIdentityContractError, match="preserve exact raw"):
        validate_evaluation_subject_revision_chain([parent, child])


def test_fabricated_base_model_mapping_is_rejected() -> None:
    payload = _reviewed_subject("agent_model_system")
    payload["baseModelMapping"]["fabricated"] = True
    _self_resign(payload)

    with pytest.raises(DomainIdentityContractError, match="fabricated"):
        validate_evaluation_subject(payload)


def test_component_cannot_claim_resolved_mapping_without_decision() -> None:
    payload = _reviewed_subject("agent_model_system")
    component = payload["components"][0]
    component["resolutionStatus"] = "resolved"
    component["componentSubjectId"] = "reviewed-base-model"
    component["reviewStatus"] = "reviewed"
    component["mappingDecisionReference"] = None
    _resign_subject(payload)

    with pytest.raises(DomainIdentityContractError, match="mapping decision"):
        validate_evaluation_subject(payload)


def test_semantically_duplicate_component_links_are_rejected() -> None:
    payload = _reviewed_subject("agent_model_system")
    duplicate = deepcopy(payload["components"][0])
    duplicate["componentLinkId"] = "second-link-same-model"
    payload["components"].append(duplicate)
    payload["manifest"]["componentLinkCount"] += 1
    _resign_subject(payload)

    with pytest.raises(DomainIdentityContractError, match="duplicate semantic component"):
        validate_evaluation_subject(payload)


def test_subject_component_cannot_self_reference() -> None:
    payload = _reviewed_subject("agent_model_system")
    component = payload["components"][0]
    component.update(
        {
            "componentSubjectId": payload["subjectId"],
            "resolutionStatus": "resolved",
            "reviewStatus": "reviewed",
            "mappingDecisionReference": "self-component-decision",
        }
    )
    _resign_subject(payload)

    with pytest.raises(DomainIdentityContractError, match="cannot contain itself"):
        validate_evaluation_subject(payload)


def test_evaluation_subject_component_cycle_is_rejected() -> None:
    first = _reviewed_subject("ensemble", "ensemble-a")
    second = _reviewed_subject("ensemble", "ensemble-b")
    for payload, target in ((first, "ensemble-b"), (second, "ensemble-a")):
        component = payload["components"][0]
        component["componentSubjectId"] = target
        component["resolutionStatus"] = "resolved"
        component["reviewStatus"] = "reviewed"
        component["mappingDecisionReference"] = f"mapping-{payload['subjectId']}-to-{target}"
        _resign_subject(payload)

    with pytest.raises(DomainIdentityContractError, match="component cycle"):
        validate_evaluation_subject_graph([first, second])


def test_evaluation_subject_fingerprint_is_stable_under_component_reordering() -> None:
    left = _reviewed_subject("agent_model_system")
    right = deepcopy(left)
    right["components"].reverse()
    _resign_subject(right)

    assert evaluation_subject_fingerprint(left) == evaluation_subject_fingerprint(right)
    assert evaluation_subject_observed_composition_fingerprint(
        left
    ) == evaluation_subject_observed_composition_fingerprint(right)
    validate_evaluation_subject(right)


@pytest.mark.parametrize("kind", ["exact", "case", "normalized"])
def test_alias_collision_at_first_matching_priority_remains_ambiguous(kind: str) -> None:
    payload = _collision_decision(kind)

    validate_identity_decision(payload)

    assert payload["outcome"] == "unresolved"
    assert payload["selectedSubjectId"] is None


def test_collision_cannot_be_resolved_by_order() -> None:
    payload = _collision_decision("exact")
    payload["outcome"] = "resolved"
    payload["selectedSubjectId"] = payload["collisionFacts"]["conflictingSubjectIds"][0]
    payload["aliasProposal"]["proposedAction"] = "add_scoped_alias"
    _self_resign(payload)

    with pytest.raises(DomainIdentityContractError, match="collision at first"):
        validate_identity_decision(payload)


@pytest.mark.parametrize(
    ("outcome", "selected"),
    [
        ("resolved", "example-reviewed-subject"),
        ("unresolved", None),
        ("rejected", None),
        ("superseded", None),
    ],
)
def test_itemized_effective_identity_outcomes_pass(outcome: str, selected: str | None) -> None:
    payload = _effective_decision(outcome=outcome, selected_subject_id=selected)
    validate_identity_decision(payload)
    assert payload["effects"]["identityReadProjectionEffect"] == (
        "set_selected_subject" if outcome == "resolved" else "clear_selected_subject"
    )


@pytest.mark.parametrize(
    "decided_at",
    [
        "2026-07-15T12:00:00+00:00",
        "2026-07-15T12:00:00.000Z",
        "2026-07-15 12:00:00Z",
        "2026-02-30T12:00:00Z",
        "2026-07-15T12:00:00",
    ],
)
def test_effective_identity_decision_requires_exact_canonical_utc_second(
    decided_at: str,
) -> None:
    payload = _effective_decision(decided_at=decided_at)

    with pytest.raises(DomainIdentityContractError, match="canonical UTC"):
        validate_identity_decision(payload)


def test_decision_time_changes_self_digest_but_not_identity_item_fingerprint() -> None:
    first = _effective_decision(decided_at="2026-07-15T12:00:00Z")
    second = deepcopy(first)
    second["decidedAt"] = "2026-07-15T12:00:01Z"
    _resign_decision(second)

    validate_identity_decision(first)
    validate_identity_decision(second)

    assert identity_decision_item_fingerprint(first) == identity_decision_item_fingerprint(second)
    assert first["manifest"]["contentSha256"] != second["manifest"]["contentSha256"]


def test_identity_read_projection_effect_cannot_disagree_with_status_or_outcome() -> None:
    payload = _effective_decision(
        outcome="resolved",
        selected_subject_id="example-reviewed-subject",
    )
    payload["effects"]["identityReadProjectionEffect"] = "clear_selected_subject"
    _self_resign(payload)

    with pytest.raises(DomainIdentityContractError, match="set_selected_subject"):
        validate_identity_decision(payload)


def test_effective_identity_projection_preserves_captured_raw_and_claim_statuses() -> None:
    payload = _effective_decision(
        outcome="resolved",
        selected_subject_id="example-reviewed-subject",
    )

    validate_identity_decision(payload)

    assert payload["observationReference"] == "example-submission-observation"
    assert payload["effects"]["identityReadProjectionEffect"] == "set_selected_subject"
    assert payload["rawObservation"] == _decision()["rawObservation"]
    assert all(
        payload["effects"][field] is False
        for field in (
            "rewritesExistingClaims",
            "mutatesRawFields",
            "promotesCaptureStatus",
            "promotesValidationStatus",
            "authorizesPublication",
        )
    )


def test_stale_identity_decision_prior_reference_is_rejected() -> None:
    root = _decision()
    child = _decision_child(root, "identity-decision-child")
    child["expectedPriorDecisionId"] = "missing-prior-decision"
    _self_resign(child)

    with pytest.raises(DomainIdentityContractError, match="stale/missing"):
        validate_identity_decision_chain([root, child])


def test_branched_identity_decision_leaves_are_rejected() -> None:
    root = _decision()
    first = _decision_child(root, "identity-decision-child-a")
    second = _decision_child(root, "identity-decision-child-b")

    with pytest.raises(DomainIdentityContractError, match="branched"):
        validate_identity_decision_chain([root, first, second])


def test_linear_identity_decision_chain_passes_without_rewriting_raw_observation() -> None:
    root = _decision()
    child = _decision_child(root, "identity-decision-child")

    validate_identity_decision_chain([root, child])

    assert child["rawObservation"] == root["rawObservation"]
    assert child["identityItemFingerprintSha256"] == root["identityItemFingerprintSha256"]


@pytest.mark.parametrize(
    "child_time",
    ["2026-07-15T12:00:00Z", "2026-07-15T11:59:59Z"],
)
def test_effective_identity_decision_chain_times_strictly_increase(
    child_time: str,
) -> None:
    root = _effective_decision(decided_at="2026-07-15T12:00:00Z")
    child = _decision_child(root, "identity-decision-child", decided_at=child_time)

    with pytest.raises(DomainIdentityContractError, match="strictly increase"):
        validate_identity_decision_chain([root, child])


def test_effective_identity_decision_cannot_regress_to_draft_child() -> None:
    root = _effective_decision(decided_at="2026-07-15T12:00:00Z")
    child = deepcopy(root)
    child["decisionId"] = "identity-decision-draft-child"
    child["expectedPriorDecisionId"] = root["decisionId"]
    child["decisionSequence"] = root["decisionSequence"] + 1
    child["decisionStatus"] = "draft"
    child["decidedAt"] = None
    child["governanceDecisionReference"] = None
    child["actor"] = {
        "actorId": "local-contract-fixture",
        "actorType": "service",
        "role": "contract-fixture-generator",
        "authorityReference": None,
    }
    child["authority"]["approvalStatus"] = "draft_unapproved"
    child["authority"]["actorAuthorityVerified"] = False
    child["authority"]["permitsIdentityReadProjection"] = False
    child["effects"]["identityReadProjectionEffect"] = "none"
    _resign_decision(child)

    with pytest.raises(DomainIdentityContractError, match="cannot have a draft child"):
        validate_identity_decision_chain([root, child])


def test_identity_chain_rejects_changed_raw_observation_fingerprint() -> None:
    root = _decision()
    child = _decision_child(root, "identity-decision-changed-item")
    child["rawObservation"]["configurationRaw"] = "Changed configuration"
    _resign_decision(child)

    with pytest.raises(DomainIdentityContractError, match="changed raw observation"):
        validate_identity_decision_chain([root, child])


def test_effective_identity_decision_requires_verified_human_actor() -> None:
    payload = _effective_decision()
    payload["actor"]["actorType"] = "service"
    _self_resign(payload)

    with pytest.raises(DomainIdentityContractError, match="verified human"):
        validate_identity_decision(payload)


def test_identity_item_fingerprint_changes_when_exact_raw_label_changes() -> None:
    payload = _decision()
    original = payload["identityItemFingerprintSha256"]
    payload["rawObservation"]["modelRaw"] += " "
    payload["aliasProposal"]["aliasRaw"] += " "
    _resign_decision(payload, raw_label=True)

    assert payload["identityItemFingerprintSha256"] != original


def test_alias_provenance_is_required() -> None:
    payload = _decision()
    payload["aliasProposal"]["provenanceReferenceIds"] = []
    payload["manifest"]["aliasProvenanceReferenceCount"] = 0
    _resign_decision(payload)

    with pytest.raises(DomainIdentityContractError, match="at least 1"):
        validate_identity_decision(payload)


def test_alias_provenance_must_resolve_to_raw_source_evidence() -> None:
    payload = _decision()
    payload["aliasProposal"]["provenanceReferenceIds"] = ["unrelated-provenance"]
    _resign_decision(payload)

    with pytest.raises(DomainIdentityContractError, match="must resolve"):
        validate_identity_decision(payload)


def test_alias_scope_requires_typed_scope_identifiers() -> None:
    payload = _decision()
    payload["aliasProposal"]["scope"]["sourceRevisionIds"] = []
    _resign_decision(payload)

    with pytest.raises(DomainIdentityContractError, match="requires source revision"):
        validate_identity_decision(payload)


def test_identity_fingerprint_is_stable_under_source_evidence_reordering() -> None:
    left = _decision()
    left["rawObservation"]["sourceEvidenceReferenceIds"].append("second-observation-evidence")
    left["manifest"]["sourceEvidenceReferenceCount"] = 2
    _resign_decision(left)
    right = deepcopy(left)
    right["rawObservation"]["sourceEvidenceReferenceIds"].reverse()
    _resign_decision(right)

    assert identity_decision_item_fingerprint(left) == identity_decision_item_fingerprint(right)
    validate_identity_decision(left)
    validate_identity_decision(right)


@pytest.mark.parametrize(
    ("factory", "validator", "field"),
    [
        (_benchmark, validate_benchmark_definition_revision, "metricCount"),
        (_subject, validate_evaluation_subject, "componentLinkCount"),
        (_decision, validate_identity_decision, "collisionSubjectCount"),
    ],
)
def test_manifest_count_mismatch_is_rejected(factory, validator, field: str) -> None:
    payload = factory()
    payload["manifest"][field] += 1
    _self_resign(payload)

    with pytest.raises(DomainIdentityContractError, match="payload contains"):
        validator(payload)


@pytest.mark.parametrize(
    ("factory", "validator", "field"),
    [
        (_benchmark, validate_benchmark_definition_revision, "authorizesPublication"),
        (_subject, validate_evaluation_subject, "establishesClaimMapping"),
        (_subject, validate_evaluation_subject, "promotesValidation"),
        (_decision, validate_identity_decision, "rewritesClaims"),
        (_decision, validate_identity_decision, "promotesCapture"),
        (_decision, validate_identity_decision, "promotesValidation"),
        (_decision, validate_identity_decision, "authorizesPublication"),
    ],
)
def test_authority_escalation_is_rejected(factory, validator, field: str) -> None:
    payload = factory()
    payload["authority"][field] = True
    _self_resign(payload)

    with pytest.raises(DomainIdentityContractError, match=field):
        validator(payload)


@pytest.mark.parametrize(
    ("factory", "validator"),
    [
        (_benchmark, validate_benchmark_definition_revision),
        (_subject, validate_evaluation_subject),
        (_decision, validate_identity_decision),
    ],
)
def test_mutable_timestamp_fields_are_rejected(factory, validator) -> None:
    payload = factory()
    payload["generatedAt"] = "2026-07-15T00:00:00Z"

    with pytest.raises(DomainIdentityContractError, match="mutable timestamps"):
        validator(payload)


@pytest.mark.parametrize(
    ("factory", "validator", "mutate"),
    [
        (_benchmark, validate_benchmark_definition_revision, lambda p: p["manifest"].__setitem__("metricCount", float("inf"))),
        (_subject, validate_evaluation_subject, lambda p: p["manifest"].__setitem__("componentLinkCount", float("nan"))),
        (_decision, validate_identity_decision, lambda p: p.__setitem__("decisionSequence", float("-inf"))),
    ],
)
def test_nonfinite_fields_are_rejected(factory, validator, mutate) -> None:
    payload = factory()
    mutate(payload)

    with pytest.raises(DomainIdentityContractError, match="non-finite"):
        validator(payload)


@pytest.mark.parametrize(
    ("factory", "validator", "fingerprint_path"),
    [
        (_benchmark, validate_benchmark_definition_revision, ("manifest", "dimensionFingerprintSha256")),
        (_subject, validate_evaluation_subject, ("subjectFingerprintSha256",)),
        (_decision, validate_identity_decision, ("identityItemFingerprintSha256",)),
    ],
)
def test_bad_semantic_fingerprint_is_rejected_after_valid_self_signing(
    factory, validator, fingerprint_path: tuple[str, ...]
) -> None:
    payload = factory()
    target = payload
    for key in fingerprint_path[:-1]:
        target = target[key]
    target[fingerprint_path[-1]] = "0" * 64
    _self_resign(payload)

    with pytest.raises(DomainIdentityContractError, match="fingerprint mismatch"):
        validator(payload)


@pytest.mark.parametrize(
    ("factory", "validator"),
    [
        (_benchmark, validate_benchmark_definition_revision),
        (_subject, validate_evaluation_subject),
        (_decision, validate_identity_decision),
    ],
)
def test_bad_self_digest_is_rejected(factory, validator) -> None:
    payload = factory()
    payload["reasonCode"] = "TAMPERED_AFTER_SELF_SIGNING"

    with pytest.raises(DomainIdentityContractError, match="self-digest mismatch"):
        validator(payload)


def test_identity_decision_effects_never_rewrite_or_promote_claims() -> None:
    payload = _decision()
    for field in (
        "rewritesExistingClaims", "mutatesRawFields", "promotesCaptureStatus",
        "promotesValidationStatus", "authorizesPublication",
    ):
        mutated = deepcopy(payload)
        mutated["effects"][field] = True
        _self_resign(mutated)
        with pytest.raises(DomainIdentityContractError, match=field):
            validate_identity_decision(mutated)


def test_canonical_json_is_mapping_order_deterministic_and_ascii_escaped() -> None:
    assert canonical_json({"z": "café", "a": {"y": 2, "x": 1}}) == (
        '{"a":{"x":1,"y":2},"z":"caf\\u00e9"}'
    )


def test_validator_module_imports_only_python_standard_library() -> None:
    import ast

    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    imported_roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".")[0])

    assert imported_roots <= sys.stdlib_module_names | {"__future__"}
    assert imported_roots.isdisjoint({"jsonschema", "sqlalchemy", "pydantic", "httpx"})
