"""Deterministic ``discovery-candidate-v1`` assembly from connector specs.

Fixtures and connectors supply only semantic fields; the stable candidate
identity, content fingerprint, manifest counts, and canonical self-digest
are derived here so a hand-written fixture can never drift from the COV-02
rules.  Every assembled candidate is revalidated before it leaves the
connector boundary, and the derived ``candidateId`` makes replayed runs
byte-identical and therefore idempotent.
"""

from __future__ import annotations

from typing import Any, Mapping

from app.schemas.coverage_contracts import (
    CoverageContractError,
    contract_self_digest,
    discovery_candidate_fingerprint,
    validate_discovery_candidate,
)


class CandidateAssemblyError(ValueError):
    """Raised when a connector spec cannot form a valid quarantined candidate."""


_SPEC_KEYS = {
    "candidateType",
    "candidateIdentity",
    "officialUrls",
    "affectedBenchmarkIds",
    "owner",
    "artifactHint",
    "termsHint",
    "reasonCode",
    "evidenceReferences",
}


def assemble_candidate(
    target_revision_id: str, spec: Mapping[str, Any]
) -> dict[str, Any]:
    """Build one fully signed quarantined candidate for a target revision."""

    if type(spec) is not dict or set(spec) != _SPEC_KEYS:
        keys = set(spec) if type(spec) is dict else set()
        raise CandidateAssemblyError(
            "candidate spec keys mismatch: "
            f"missing {sorted(_SPEC_KEYS - keys)}, unexpected {sorted(keys - _SPEC_KEYS)}"
        )
    fingerprint = discovery_candidate_fingerprint(
        {
            "candidateType": spec["candidateType"],
            "targetRevisionId": target_revision_id,
            "candidateIdentity": spec["candidateIdentity"],
            "officialUrls": spec["officialUrls"],
            "affectedBenchmarkIds": spec["affectedBenchmarkIds"],
        }
    )
    official_urls = spec["officialUrls"]
    affected_ids = spec["affectedBenchmarkIds"]
    evidence = spec["evidenceReferences"]
    payload: dict[str, Any] = {
        "schemaVersion": "1.0.0",
        "policyVersion": "discovery-candidate-v1",
        "availability": "candidate_only",
        "candidateId": f"cand-{fingerprint[:40]}",
        "candidateFingerprintSha256": fingerprint,
        "candidateType": spec["candidateType"],
        "state": "observed",
        "stateDecisionReference": None,
        "approvedSourceRevisionReference": None,
        "reasonCode": spec["reasonCode"],
        "targetRevisionId": target_revision_id,
        "authority": {
            "classification": "quarantined_proposal_only",
            "certifiesSources": False,
            "authorizesCapture": False,
            "authorizesPublication": False,
            "frontendLoadable": False,
        },
        "owner": spec["owner"],
        "candidateIdentity": spec["candidateIdentity"],
        "officialUrls": official_urls,
        "affectedBenchmarkIds": affected_ids,
        "artifactHint": spec["artifactHint"],
        "termsHint": spec["termsHint"],
        "evidenceReferences": evidence,
        "manifest": {
            "algorithm": "sha256-canonical-json-v1",
            "contentSha256": None,
            "officialUrlCount": len(official_urls),
            "affectedBenchmarkCount": len(affected_ids),
            "evidenceReferenceCount": len(evidence),
        },
    }
    payload["manifest"]["contentSha256"] = contract_self_digest(payload)
    try:
        validate_discovery_candidate(payload)
    except CoverageContractError as exc:
        raise CandidateAssemblyError(str(exc)) from exc
    return payload


__all__ = ["CandidateAssemblyError", "assemble_candidate"]
