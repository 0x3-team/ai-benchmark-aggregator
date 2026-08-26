"""Pure candidate builder for canonical Official release artifact v2 bytes.

This module creates no database row, file, approval, authorization, or
publication. It only bridges a validated LDR-08 eligible-feed document to the
existing v2 wire contract when a caller supplies the public metadata that the
candidate feed deliberately does not own.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
from importlib.resources import files
import json
import math
import re
from typing import Any, Mapping, Sequence
from urllib.parse import parse_qsl, urlsplit

from jsonschema import Draft202012Validator, FormatChecker
from sqlalchemy import inspect as sqlalchemy_inspect

from app.db import models as db_models
from app.export.official_json import (
    CANONICAL_JSON_ALGORITHM,
    validate_official_feed,
)
from app.ingestion.json_lexemes import parse_json_path


OFFICIAL_RELEASE_SCHEMA_VERSION = "2.0.0"
OFFICIAL_RELEASE_POLICY_VERSION = "official-release-artifact-v2"
OFFICIAL_RELEASE_ARTIFACT_KIND = "official-release-artifact"
OFFICIAL_RELEASE_AVAILABILITY = "published"

_MODEL_KEYS = frozenset(
    {
        "id",
        "name",
        "vendor",
        "family",
        "releaseDate",
        "contextWindowK",
        "paramsB",
        "modalities",
        "openWeights",
        "priceInPer1M",
        "priceOutPer1M",
    }
)
_BENCHMARK_KEYS = frozenset(
    {
        "id",
        "name",
        "fullName",
        "category",
        "higherIsBetter",
        "scaleMax",
        "description",
        "methodology",
        "sourceUrl",
    }
)
_RELEASE_APPROVAL_KEYS = frozenset({"decisionId", "policyVersion", "approvedAt"})
_MAX_SAFE_JSON_INTEGER = 9_007_199_254_740_991
_CANDIDATE_UTC_TIMESTAMP = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}\Z"
)
_CREDENTIAL_QUERY_KEYS = frozenset(
    {
        "access_token",
        "api_key",
        "apikey",
        "credential",
        "password",
        "secret",
        "signature",
        "token",
        "x-amz-credential",
        "x-amz-signature",
        "x-goog-credential",
        "x-goog-signature",
    }
)
_V2_SCHEMA_RESOURCE = "official-release-artifact-v2.schema.json"


class OfficialReleaseBuildError(ValueError):
    """The candidate cannot be represented by the existing v2 contract."""


def _require_mapping(value: object, keys: frozenset[str], label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise OfficialReleaseBuildError(f"{label} has an invalid contract shape.")
    return deepcopy(dict(value))


def _require_identifier(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise OfficialReleaseBuildError(f"{label} must be a non-empty stable identifier.")
    return value


def _require_nonempty_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OfficialReleaseBuildError(f"{label} must be a non-empty string.")
    return value


def js_utf16_sort_key(value: str) -> tuple[int, ...]:
    """Return JavaScript's lexicographic UTF-16 code-unit ordering key."""
    encoded = value.encode("utf-16-be", errors="surrogatepass")
    return tuple(
        int.from_bytes(encoded[index : index + 2], "big")
        for index in range(0, len(encoded), 2)
    )


def _rows_by_id(
    rows: Sequence[Mapping[str, Any]], keys: frozenset[str], label: str
) -> dict[str, dict[str, Any]]:
    parsed: dict[str, dict[str, Any]] = {}
    ordered_ids: list[str] = []
    for value in rows:
        row = _require_mapping(value, keys, f"{label} entry")
        row_id = _require_identifier(row.get("id"), f"{label} id")
        if row_id in parsed:
            raise OfficialReleaseBuildError(f"{label} contains a duplicate id.")
        parsed[row_id] = row
        ordered_ids.append(row_id)
    if ordered_ids != sorted(ordered_ids, key=js_utf16_sort_key):
        raise OfficialReleaseBuildError(f"{label} must be sorted by id.")
    return parsed


def _validate_release_approval(value: Mapping[str, Any]) -> dict[str, Any]:
    approval = _require_mapping(value, _RELEASE_APPROVAL_KEYS, "Release approval reference")
    _require_identifier(approval.get("decisionId"), "Release approval decisionId")
    if approval.get("policyVersion") != OFFICIAL_RELEASE_POLICY_VERSION:
        raise OfficialReleaseBuildError("Release approval has an unsupported policy version.")
    _require_nonempty_string(approval.get("approvedAt"), "Release approval approvedAt")
    return approval


def _json_pointer(tokens: Sequence[str | int]) -> str:
    return "".join(
        f"/{str(token).replace('~', '~0').replace('/', '~1')}" for token in tokens
    )


def _derive_public_evidence(locator: object, *, claim_id: str) -> dict[str, str]:
    if not isinstance(locator, Mapping) or locator.get("type") != "json_path_v1":
        raise OfficialReleaseBuildError(
            f"Release claim {claim_id} uses an unsupported evidence locator type."
        )
    record_tokens = parse_json_path(locator.get("record_path"))
    fields = locator.get("fields")
    if record_tokens is None or not isinstance(fields, Mapping):
        raise OfficialReleaseBuildError(
            f"Release claim {claim_id} has an invalid json_path_v1 evidence locator."
        )
    required_fields = ("model_raw", "benchmark_raw", "score_raw")
    if any(not isinstance(fields.get(field), str) or not fields[field] for field in required_fields):
        raise OfficialReleaseBuildError(
            f"Release claim {claim_id} evidence cannot resolve every required raw field."
        )
    record_pointer = _json_pointer(record_tokens)
    return {
        "type": "json_pointer",
        "locator": record_pointer or "/",
        "modelLocator": _json_pointer([*record_tokens, fields["model_raw"]]),
        "benchmarkLocator": _json_pointer([*record_tokens, fields["benchmark_raw"]]),
        "scoreLocator": _json_pointer([*record_tokens, fields["score_raw"]]),
    }


def _require_public_https_url(value: object, label: str) -> None:
    if not isinstance(value, str):
        raise OfficialReleaseBuildError(f"{label} must be a public HTTPS URL.")
    try:
        parsed = urlsplit(value)
        valid = (
            parsed.scheme == "https"
            and bool(parsed.hostname)
            and parsed.username is None
            and parsed.password is None
            and not parsed.fragment
            and "#" not in value
            and not any(ord(character) < 0x20 or ord(character) == 0x7F for character in value)
            and not any(
                key.casefold() in _CREDENTIAL_QUERY_KEYS
                for key, _query_value in parse_qsl(parsed.query, keep_blank_values=True)
            )
        )
    except ValueError:
        valid = False
    if not valid:
        raise OfficialReleaseBuildError(f"{label} must be a credential-free canonical HTTPS URL.")


def _require_portable_json_numbers(value: object, label: str = "Official release artifact") -> None:
    if isinstance(value, bool) or value is None:
        return
    if isinstance(value, int):
        if abs(value) > _MAX_SAFE_JSON_INTEGER:
            raise OfficialReleaseBuildError(
                f"{label} contains an integer outside the cross-runtime canonical range."
            )
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise OfficialReleaseBuildError(f"{label} contains a non-finite number.")
        if value.is_integer() and abs(value) > _MAX_SAFE_JSON_INTEGER:
            raise OfficialReleaseBuildError(
                f"{label} contains an integer outside the cross-runtime canonical range."
            )
        if not value.is_integer() and "e" in json.dumps(value).lower():
            raise OfficialReleaseBuildError(
                f"{label} contains a number outside the cross-runtime canonical range."
            )
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _require_portable_json_numbers(item, f"{label}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            _require_portable_json_numbers(item, f"{label}.{key}")


def _normalize_release_numbers(value: Any) -> Any:
    if isinstance(value, float) and math.isfinite(value) and value.is_integer():
        return int(value)
    if isinstance(value, list):
        return [_normalize_release_numbers(item) for item in value]
    if isinstance(value, dict):
        return {key: _normalize_release_numbers(item) for key, item in value.items()}
    return value


def _canonical_release_json(value: Mapping[str, Any]) -> str:
    """Match the pre-existing v2 browser canonicalizer without changing v1."""
    return json.dumps(
        _normalize_release_numbers(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _snapshot_timestamp_for_release(value: object) -> object:
    # Candidate v1 deliberately preserves its historical timezone-free UTC
    # serialization. The release view makes that internal UTC fact explicit;
    # raw source-reported dates are never passed through this function.
    if isinstance(value, str) and _CANDIDATE_UTC_TIMESTAMP.fullmatch(value):
        return f"{value}Z"
    return value


def _schema_location(path: Sequence[object]) -> str:
    location = "$"
    for item in path:
        location += f"[{item}]" if isinstance(item, int) else f".{item}"
    return location


def _validate_v2_schema(artifact: Mapping[str, Any]) -> None:
    try:
        schema = json.loads(
            files("app.export").joinpath(_V2_SCHEMA_RESOURCE).read_text(encoding="utf-8")
        )
        validator = Draft202012Validator(schema, format_checker=FormatChecker())
        errors = sorted(
            validator.iter_errors(artifact),
            key=lambda error: (_schema_location(error.absolute_path), str(error.validator)),
        )
    except (OSError, json.JSONDecodeError) as error:
        raise OfficialReleaseBuildError(
            "Official release artifact v2 schema could not be loaded."
        ) from error
    if errors:
        error = errors[0]
        raise OfficialReleaseBuildError(
            "Official release artifact violates v2 schema at "
            f"{_schema_location(error.absolute_path)} ({error.validator})."
        )


def official_release_artifact_digest(payload: Mapping[str, Any]) -> str:
    """Return the existing canonical self-digest for a v2 artifact."""
    digest_input = deepcopy(dict(payload))
    manifest = digest_input.get("manifest")
    if isinstance(manifest, dict):
        manifest["contentSha256"] = None
    return hashlib.sha256(_canonical_release_json(digest_input).encode("utf-8")).hexdigest()


def canonical_official_release_artifact_json(payload: Mapping[str, Any]) -> str:
    """Return the exact canonical bytes representation accepted by REL-05."""
    return _canonical_release_json(payload)


def _published_score_sort_key(score: Mapping[str, Any]) -> tuple[object, ...]:
    cell = score["cell"]

    def nullable(value: str | None) -> tuple[int, tuple[int, ...]]:
        return (0, ()) if value is None else (1, js_utf16_sort_key(value))

    return (
        js_utf16_sort_key(cell["modelId"]),
        js_utf16_sort_key(cell["benchmarkId"]),
        nullable(cell["metric"]),
        nullable(cell["split"]),
        nullable(cell["setting"]),
        nullable(cell["evaluationVersion"]),
    )


def build_official_release_artifact(
    candidate_feed: Mapping[str, Any],
    *,
    artifact_id: str,
    release_approval: Mapping[str, Any],
    models: Sequence[Mapping[str, Any]],
    benchmarks: Sequence[Mapping[str, Any]],
    claims_by_id: Mapping[str, db_models.ResultClaim],
    review_decisions_by_id: Mapping[str, db_models.ClaimReviewDecision],
    publication_decisions_by_id: Mapping[str, db_models.ClaimPublicationDecision],
) -> dict[str, Any]:
    """Build one deterministic v2 document from an eligible candidate feed.

    The supplied model and benchmark rows are the complete public v2 metadata
    rows. Their identities and owned names must match the candidate projection.
    Exact ResultClaim rows supply raw model/benchmark names and the source's
    report time because candidate v1 does not contain those v2-only fields.
    Exact persisted review and publication decisions must match every
    provenance reference. The public evidence envelope is derived only from a
    representable captured locator. No raw value, selected numeric value,
    identity, provenance field, or public evidence path can be overridden.
    """

    candidate = validate_official_feed(candidate_feed)
    release_id = _require_identifier(artifact_id, "Official release artifactId")
    approval = _validate_release_approval(release_approval)

    if not candidate["scores"]:
        raise OfficialReleaseBuildError("A v2 release artifact must contain an eligible score.")

    public_models = _rows_by_id(models, _MODEL_KEYS, "Release models")
    public_benchmarks = _rows_by_id(benchmarks, _BENCHMARK_KEYS, "Release benchmarks")
    candidate_models = {row["id"]: row for row in candidate["models"]}
    candidate_benchmarks = {row["id"]: row for row in candidate["benchmarks"]}
    if set(public_models) != set(candidate_models):
        raise OfficialReleaseBuildError("Release model identities do not match the eligible feed.")
    if set(public_benchmarks) != set(candidate_benchmarks):
        raise OfficialReleaseBuildError("Release benchmark identities do not match the eligible feed.")

    for row_id, row in public_models.items():
        candidate_row = candidate_models[row_id]
        if (
            row["name"] != candidate_row["displayName"]
            or row["vendor"] != candidate_row["provider"]
            or row["family"] != candidate_row["modelFamily"]
        ):
            raise OfficialReleaseBuildError(
                "Release model names, vendor, and family must match the eligible feed."
            )
    for row_id, row in public_benchmarks.items():
        candidate_row = candidate_benchmarks[row_id]
        if (
            row["name"] != candidate_row["displayName"]
            or row["fullName"] != candidate_row["canonicalName"]
        ):
            raise OfficialReleaseBuildError(
                "Release benchmark names must match the eligible feed."
            )
        _require_public_https_url(row["sourceUrl"], "Release benchmark sourceUrl")

    source_manifest = sorted(
        deepcopy(candidate["sourceManifest"]),
        key=lambda source: js_utf16_sort_key(source["sourceManifestKey"]),
    )
    for source in source_manifest:
        _require_public_https_url(source["sourceUrl"], "Release source manifest sourceUrl")
        source["snapshotCapturedAt"] = _snapshot_timestamp_for_release(
            source["snapshotCapturedAt"]
        )
    release_source_by_key = {
        source["sourceManifestKey"]: source for source in source_manifest
    }

    claim_ids = [row["claimId"] for row in candidate["scores"]]
    if set(claims_by_id) != set(claim_ids):
        raise OfficialReleaseBuildError(
            "Release claim rows must account for exactly every eligible claim."
        )
    review_ids = {
        row["provenance"]["claimReviewDecisionId"] for row in candidate["scores"]
    }
    publication_ids = {
        row["provenance"]["claimPublicationDecisionId"]
        for row in candidate["scores"]
    }
    if set(review_decisions_by_id) != review_ids:
        raise OfficialReleaseBuildError(
            "Release review decisions must account for exactly every eligible provenance reference."
        )
    if set(publication_decisions_by_id) != publication_ids:
        raise OfficialReleaseBuildError(
            "Release publication decisions must account for exactly every eligible provenance reference."
        )

    scores: list[dict[str, Any]] = []
    display_pairs: set[tuple[str, str]] = set()
    for candidate_score in candidate["scores"]:
        claim_id = candidate_score["claimId"]
        claim = claims_by_id[claim_id]
        if not isinstance(claim, db_models.ResultClaim) or claim.id != claim_id:
            raise OfficialReleaseBuildError("Release claim input contains an invalid claim row.")
        if (
            claim.score_raw != candidate_score["scoreRaw"]
            or claim.score_numeric != candidate_score["value"]
            or claim.official_source_id
            != candidate_score["provenance"]["officialSourceId"]
            or claim.source_snapshot_id
            != candidate_score["provenance"]["sourceSnapshotId"]
            or claim.source_revision_decision_id
            != candidate_score["provenance"]["sourceRevisionDecisionId"]
            or claim.evidence_location != candidate_score["evidenceLocation"]
        ):
            raise OfficialReleaseBuildError(
                "Release claim rows do not exactly match the eligible feed."
            )
        model_raw = _require_nonempty_string(
            claim.model_raw, f"Release claim {claim_id} modelRaw"
        )
        benchmark_raw = _require_nonempty_string(
            claim.benchmark_raw, f"Release claim {claim_id} benchmarkRaw"
        )
        reported_at = _require_nonempty_string(
            claim.date_raw, f"Release claim {claim_id} reportedAt"
        )
        review_id = candidate_score["provenance"]["claimReviewDecisionId"]
        publication_id = candidate_score["provenance"]["claimPublicationDecisionId"]
        review = review_decisions_by_id[review_id]
        publication = publication_decisions_by_id[publication_id]
        if (
            not isinstance(review, db_models.ClaimReviewDecision)
            or not sqlalchemy_inspect(review).persistent
            or review.id != review_id
            or review.result_claim_id != claim_id
            or review.outcome != "validation_reviewed"
        ):
            raise OfficialReleaseBuildError(
                f"Release claim {claim_id} does not bind its effective validation review decision."
            )
        if (
            not isinstance(publication, db_models.ClaimPublicationDecision)
            or not sqlalchemy_inspect(publication).persistent
            or publication.id != publication_id
            or publication.result_claim_id != claim_id
            or publication.claim_review_decision_id != review.id
            or publication.outcome != "approved"
        ):
            raise OfficialReleaseBuildError(
                f"Release claim {claim_id} does not bind its effective approved publication decision."
            )
        evidence = _derive_public_evidence(
            claim.evidence_location,
            claim_id=claim_id,
        )
        cell = deepcopy(candidate_score["cell"])
        pair = (cell["modelId"], cell["benchmarkId"])
        if pair in display_pairs:
            raise OfficialReleaseBuildError(
                "The v2 UI contract permits only one score per model/benchmark pair."
            )
        display_pairs.add(pair)
        provenance = deepcopy(candidate_score["provenance"])
        release_source = release_source_by_key[provenance["sourceManifestKey"]]
        for key, value in release_source.items():
            provenance[key] = value
        scores.append(
            {
                "cell": cell,
                "claimId": claim_id,
                "value": candidate_score["value"],
                "modelRaw": model_raw,
                "benchmarkRaw": benchmark_raw,
                "scoreRaw": candidate_score["scoreRaw"],
                "scoreUnit": candidate_score["scoreUnit"],
                "reportedAt": reported_at,
                "evidenceText": candidate_score["evidenceText"],
                "evidence": evidence,
                "provenance": provenance,
            }
        )

    scores.sort(key=_published_score_sort_key)

    artifact: dict[str, Any] = {
        "schemaVersion": OFFICIAL_RELEASE_SCHEMA_VERSION,
        "artifactKind": OFFICIAL_RELEASE_ARTIFACT_KIND,
        "artifactId": release_id,
        "availability": OFFICIAL_RELEASE_AVAILABILITY,
        "policyVersion": OFFICIAL_RELEASE_POLICY_VERSION,
        "releaseApproval": approval,
        "manifest": {
            "algorithm": CANONICAL_JSON_ALGORITHM,
            "contentSha256": None,
            "modelCount": len(public_models),
            "benchmarkCount": len(public_benchmarks),
            "sourceSnapshotCount": len(source_manifest),
            "scoreCount": len(scores),
        },
        "models": [
            public_models[key]
            for key in sorted(public_models, key=js_utf16_sort_key)
        ],
        "benchmarks": [
            public_benchmarks[key]
            for key in sorted(public_benchmarks, key=js_utf16_sort_key)
        ],
        "sourceManifest": source_manifest,
        "scores": scores,
    }
    _require_portable_json_numbers(artifact)
    artifact["manifest"]["contentSha256"] = official_release_artifact_digest(artifact)
    _validate_v2_schema(artifact)
    return artifact
