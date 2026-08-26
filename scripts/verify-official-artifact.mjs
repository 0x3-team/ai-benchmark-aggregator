#!/usr/bin/env node
/**
 * Offline verifier for the tracked FEED-01 containment artifact and an
 * explicitly supplied v2 artifact/authorization pair.
 *
 * The no-argument path remains fixed to the tracked unavailable artifact. The
 * v2 path is verification-only: it accepts canonical artifact bytes plus a
 * separate authorization record, writes nothing, and cannot create or approve
 * a release.
 */

import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { fileURLToPath, pathToFileURL } from "node:url";
import path from "node:path";

export const OFFICIAL_RELEASE_ARTIFACT_SCHEMA_VERSION = "1.0.0";
export const OFFICIAL_RELEASE_ARTIFACT_POLICY_VERSION = "official-release-artifact-v1";
export const OFFICIAL_RELEASE_ARTIFACT_KIND = "official-release-artifact";
export const OFFICIAL_RELEASE_ARTIFACT_AVAILABILITY = "unavailable";
export const CANONICAL_JSON_ALGORITHM = "sha256-canonical-json-v1";
export const OFFICIAL_RELEASE_ARTIFACT_SCHEMA_ID =
  "https://ai-benchmark-platform.local/contracts/official-release-artifact-v1.schema.json";
export const PUBLISHED_OFFICIAL_RELEASE_ARTIFACT_SCHEMA_VERSION = "2.0.0";
export const PUBLISHED_OFFICIAL_RELEASE_ARTIFACT_POLICY_VERSION = "official-release-artifact-v2";
export const PUBLISHED_OFFICIAL_RELEASE_ARTIFACT_AVAILABILITY = "published";
export const PUBLISHED_OFFICIAL_RELEASE_ARTIFACT_SCHEMA_ID =
  "https://ai-benchmark-platform.local/contracts/official-release-artifact-v2.schema.json";
export const OFFICIAL_RELEASE_AUTHORIZATION_SCHEMA_ID =
  "https://ai-benchmark-platform.local/contracts/official-release-authorization-v1.schema.json";
export const JSON_SCHEMA_DRAFT_2020_12 = "https://json-schema.org/draft/2020-12/schema";

const HERE = path.dirname(fileURLToPath(import.meta.url));
export const REPOSITORY_ROOT = path.resolve(HERE, "..");
export const TRACKED_OFFICIAL_ARTIFACT_PATH = path.join(
  REPOSITORY_ROOT,
  "src",
  "data",
  "official",
  "export.unavailable.json"
);
export const TRACKED_OFFICIAL_ARTIFACT_CONTRACT_PATH = path.join(
  REPOSITORY_ROOT,
  "docs",
  "contracts",
  "official-release-artifact-v1.schema.json"
);
export const PUBLISHED_OFFICIAL_ARTIFACT_CONTRACT_PATH = path.join(
  REPOSITORY_ROOT,
  "docs",
  "contracts",
  "official-release-artifact-v2.schema.json"
);
export const OFFICIAL_RELEASE_AUTHORIZATION_CONTRACT_PATH = path.join(
  REPOSITORY_ROOT,
  "docs",
  "contracts",
  "official-release-authorization-v1.schema.json"
);

const TOP_LEVEL_KEYS = new Set([
  "schemaVersion",
  "artifactKind",
  "artifactId",
  "availability",
  "policyVersion",
  "manifest",
  "reason",
  "models",
  "benchmarks",
  "sourceManifest",
  "scores",
]);
const MANIFEST_KEYS = new Set([
  "algorithm",
  "contentSha256",
  "modelCount",
  "benchmarkCount",
  "sourceSnapshotCount",
  "scoreCount",
]);
const PUBLISHED_TOP_LEVEL_KEYS = new Set([
  "schemaVersion",
  "artifactKind",
  "artifactId",
  "availability",
  "policyVersion",
  "releaseApproval",
  "manifest",
  "models",
  "benchmarks",
  "sourceManifest",
  "scores",
]);
const RELEASE_APPROVAL_KEYS = new Set(["decisionId", "policyVersion", "approvedAt"]);
const RELEASE_AUTHORIZATION_KEYS = new Set([
  "artifactId",
  "contentSha256",
  "releaseApprovalDecisionId",
  "policyVersion",
]);
const HEX_SHA256 = /^[0-9a-f]{64}$/;
const RFC3339_TIMESTAMP =
  /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$/;
const CREDENTIAL_QUERY_KEYS = new Set([
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
]);

export class OfficialArtifactValidationError extends Error {
  constructor(message) {
    super(message);
    this.name = "OfficialArtifactValidationError";
  }
}

function isRecord(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function requireRecord(value, label) {
  if (!isRecord(value)) {
    throw new OfficialArtifactValidationError(`${label} must be an object.`);
  }
  return value;
}

function requireExactKeys(value, expected, label) {
  const record = requireRecord(value, label);
  const keys = Object.keys(record);
  if (keys.length !== expected.size || keys.some((key) => !expected.has(key))) {
    throw new OfficialArtifactValidationError(`${label} has an invalid contract shape.`);
  }
  return record;
}

function requireNonemptyString(value, label) {
  if (typeof value !== "string" || value.trim().length === 0) {
    throw new OfficialArtifactValidationError(`${label} must be a non-empty string.`);
  }
  return value;
}

function requireNonnegativeInteger(value, label) {
  if (!Number.isInteger(value) || value < 0) {
    throw new OfficialArtifactValidationError(`${label} must be a non-negative integer.`);
  }
  return value;
}

function requireExactStringSet(value, expected, label) {
  if (!Array.isArray(value) || value.length !== expected.size || value.some((item) => typeof item !== "string")) {
    throw new OfficialArtifactValidationError(`${label} must list the expected string keys.`);
  }
  const actual = new Set(value);
  if (actual.size !== expected.size || [...actual].some((key) => !expected.has(key))) {
    throw new OfficialArtifactValidationError(`${label} does not match the executable artifact contract.`);
  }
  return value;
}

function requireSchemaConst(schema, expected, label) {
  const record = requireRecord(schema, label);
  if (record.const !== expected) {
    throw new OfficialArtifactValidationError(`${label} does not match the executable artifact contract.`);
  }
}

function requireZeroLengthArraySchema(schema, label) {
  const record = requireRecord(schema, label);
  if (record.type !== "array" || record.maxItems !== 0) {
    throw new OfficialArtifactValidationError(`${label} does not enforce the containment data boundary.`);
  }
}

function resolveLocalSchemaReference(rootSchema, reference) {
  if (typeof reference !== "string" || !reference.startsWith("#/")) {
    throw new OfficialArtifactValidationError(
      `Official artifact schema uses unsupported reference ${String(reference)}.`
    );
  }
  return reference
    .slice(2)
    .split("/")
    .map((part) => part.replaceAll("~1", "/").replaceAll("~0", "~"))
    .reduce((value, part) => requireRecord(value, `Schema reference ${reference}`)[part], rootSchema);
}

function schemaTypeMatches(value, type) {
  if (type === "null") return value === null;
  if (type === "object") return isRecord(value);
  if (type === "array") return Array.isArray(value);
  if (type === "integer") return typeof value === "number" && Number.isInteger(value);
  if (type === "number") return typeof value === "number" && Number.isFinite(value);
  return typeof value === type;
}

function validateSchemaFormat(value, format, label) {
  if (format === "date") {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) {
      throw new OfficialArtifactValidationError(`${label} is not an RFC 3339 date.`);
    }
    const parsed = new Date(`${value}T00:00:00.000Z`);
    if (Number.isNaN(parsed.valueOf()) || parsed.toISOString().slice(0, 10) !== value) {
      throw new OfficialArtifactValidationError(`${label} is not a real calendar date.`);
    }
    return;
  }
  if (format === "date-time") {
    if (
      !RFC3339_TIMESTAMP.test(value) ||
      Number.isNaN(new Date(value).valueOf())
    ) {
      throw new OfficialArtifactValidationError(`${label} is not an RFC 3339 date-time.`);
    }
    return;
  }
  if (format === "uri") {
    try {
      const parsed = new URL(value);
      if (!parsed.protocol) throw new Error("missing scheme");
    } catch {
      throw new OfficialArtifactValidationError(`${label} is not an absolute URI.`);
    }
  }
}

function validateJsonValueAgainstSchema(value, schemaInput, rootSchema, label) {
  let schema = requireRecord(schemaInput, `${label} schema`);
  if (schema.$ref !== undefined) {
    schema = requireRecord(resolveLocalSchemaReference(rootSchema, schema.$ref), `${label} referenced schema`);
  }
  if (Object.hasOwn(schema, "const") && value !== schema.const) {
    throw new OfficialArtifactValidationError(`${label} does not match its schema constant.`);
  }
  if (Array.isArray(schema.enum) && !schema.enum.some((candidate) => candidate === value)) {
    throw new OfficialArtifactValidationError(`${label} is outside its schema enum.`);
  }
  if (schema.type !== undefined) {
    const allowedTypes = Array.isArray(schema.type) ? schema.type : [schema.type];
    if (!allowedTypes.some((type) => schemaTypeMatches(value, type))) {
      throw new OfficialArtifactValidationError(`${label} has the wrong schema type.`);
    }
  }
  if (typeof value === "string") {
    if (Number.isInteger(schema.minLength) && value.length < schema.minLength) {
      throw new OfficialArtifactValidationError(`${label} is shorter than its schema minimum.`);
    }
    if (typeof schema.pattern === "string" && !new RegExp(schema.pattern).test(value)) {
      throw new OfficialArtifactValidationError(`${label} does not match its schema pattern.`);
    }
    if (typeof schema.format === "string") validateSchemaFormat(value, schema.format, label);
  }
  if (typeof value === "number") {
    if (!Number.isFinite(value)) {
      throw new OfficialArtifactValidationError(`${label} must be finite.`);
    }
    if (typeof schema.minimum === "number" && value < schema.minimum) {
      throw new OfficialArtifactValidationError(`${label} is below its schema minimum.`);
    }
    if (typeof schema.exclusiveMinimum === "number" && value <= schema.exclusiveMinimum) {
      throw new OfficialArtifactValidationError(`${label} is below its exclusive schema minimum.`);
    }
  }
  if (Array.isArray(value)) {
    if (Number.isInteger(schema.minItems) && value.length < schema.minItems) {
      throw new OfficialArtifactValidationError(`${label} has too few items.`);
    }
    if (Number.isInteger(schema.maxItems) && value.length > schema.maxItems) {
      throw new OfficialArtifactValidationError(`${label} has too many items.`);
    }
    if (schema.uniqueItems === true) {
      const canonicalItems = value.map((item) => canonicalOfficialArtifactJson(item));
      if (new Set(canonicalItems).size !== canonicalItems.length) {
        throw new OfficialArtifactValidationError(`${label} must contain unique items.`);
      }
    }
    if (schema.items !== undefined) {
      value.forEach((item, index) =>
        validateJsonValueAgainstSchema(item, schema.items, rootSchema, `${label}[${index}]`)
      );
    }
  }
  if (isRecord(value)) {
    const properties = isRecord(schema.properties) ? schema.properties : {};
    if (Array.isArray(schema.required)) {
      for (const key of schema.required) {
        if (typeof key !== "string" || !Object.hasOwn(value, key)) {
          throw new OfficialArtifactValidationError(`${label} is missing required field ${String(key)}.`);
        }
      }
    }
    if (schema.additionalProperties === false) {
      for (const key of Object.keys(value)) {
        if (!Object.hasOwn(properties, key)) {
          throw new OfficialArtifactValidationError(`${label} has unsupported field ${key}.`);
        }
      }
    }
    for (const [key, propertySchema] of Object.entries(properties)) {
      if (Object.hasOwn(value, key)) {
        validateJsonValueAgainstSchema(value[key], propertySchema, rootSchema, `${label}.${key}`);
      }
    }
  }
}

export function validateJsonDocumentAgainstSchema(value, schema, label = "JSON document") {
  validateJsonValueAgainstSchema(value, schema, schema, label);
  return value;
}

/**
 * Check that the tracked documentation schema cannot silently drift from the
 * executable containment contract. This is a parity check; the semantic
 * artifact validator below remains the runtime/CI authority because it also
 * verifies the self-digest, which JSON Schema alone cannot express.
 */
export function validateOfficialArtifactContractSchema(input) {
  const schema = requireRecord(input, "Official release artifact schema");
  if (schema.$schema !== JSON_SCHEMA_DRAFT_2020_12 || schema.$id !== OFFICIAL_RELEASE_ARTIFACT_SCHEMA_ID) {
    throw new OfficialArtifactValidationError("Official release artifact schema has an unexpected identity.");
  }
  if (schema.type !== "object" || schema.additionalProperties !== false) {
    throw new OfficialArtifactValidationError("Official release artifact schema does not fail closed.");
  }
  requireExactStringSet(schema.required, TOP_LEVEL_KEYS, "Official release artifact schema required keys");

  const properties = requireRecord(schema.properties, "Official release artifact schema properties");
  requireSchemaConst(properties.schemaVersion, OFFICIAL_RELEASE_ARTIFACT_SCHEMA_VERSION, "schemaVersion schema");
  requireSchemaConst(properties.artifactKind, OFFICIAL_RELEASE_ARTIFACT_KIND, "artifactKind schema");
  requireSchemaConst(properties.availability, OFFICIAL_RELEASE_ARTIFACT_AVAILABILITY, "availability schema");
  requireSchemaConst(properties.policyVersion, OFFICIAL_RELEASE_ARTIFACT_POLICY_VERSION, "policyVersion schema");

  const artifactId = requireRecord(properties.artifactId, "artifactId schema");
  const reason = requireRecord(properties.reason, "reason schema");
  if (artifactId.type !== "string" || artifactId.minLength !== 1 || reason.type !== "string" || reason.minLength !== 1) {
    throw new OfficialArtifactValidationError("Official release artifact schema has an invalid identity or reason contract.");
  }

  const manifest = requireRecord(properties.manifest, "Official release artifact manifest schema");
  if (manifest.type !== "object" || manifest.additionalProperties !== false) {
    throw new OfficialArtifactValidationError("Official release artifact manifest schema does not fail closed.");
  }
  requireExactStringSet(manifest.required, MANIFEST_KEYS, "Official release artifact manifest schema required keys");
  const manifestProperties = requireRecord(manifest.properties, "Official release artifact manifest schema properties");
  requireSchemaConst(manifestProperties.algorithm, CANONICAL_JSON_ALGORITHM, "manifest algorithm schema");
  for (const key of ["modelCount", "benchmarkCount", "sourceSnapshotCount", "scoreCount"]) {
    requireSchemaConst(manifestProperties[key], 0, `manifest ${key} schema`);
  }
  const digest = requireRecord(manifestProperties.contentSha256, "manifest digest schema");
  if (digest.type !== "string" || digest.pattern !== "^[0-9a-f]{64}$") {
    throw new OfficialArtifactValidationError("Official release artifact schema has an invalid digest contract.");
  }

  for (const key of ["models", "benchmarks", "sourceManifest", "scores"]) {
    requireZeroLengthArraySchema(properties[key], `${key} schema`);
  }
  return schema;
}

export function validatePublishedOfficialArtifactContractSchema(input) {
  const schema = requireRecord(input, "Published Official release artifact schema");
  if (
    schema.$schema !== JSON_SCHEMA_DRAFT_2020_12 ||
    schema.$id !== PUBLISHED_OFFICIAL_RELEASE_ARTIFACT_SCHEMA_ID
  ) {
    throw new OfficialArtifactValidationError(
      "Published Official release artifact schema has an unexpected identity."
    );
  }
  if (schema.type !== "object" || schema.additionalProperties !== false) {
    throw new OfficialArtifactValidationError(
      "Published Official release artifact schema does not fail closed."
    );
  }
  requireExactStringSet(
    schema.required,
    PUBLISHED_TOP_LEVEL_KEYS,
    "Published Official release artifact schema required keys"
  );
  const properties = requireRecord(
    schema.properties,
    "Published Official release artifact schema properties"
  );
  requireSchemaConst(
    properties.schemaVersion,
    PUBLISHED_OFFICIAL_RELEASE_ARTIFACT_SCHEMA_VERSION,
    "published schemaVersion schema"
  );
  requireSchemaConst(properties.artifactKind, OFFICIAL_RELEASE_ARTIFACT_KIND, "published artifactKind schema");
  requireSchemaConst(
    properties.availability,
    PUBLISHED_OFFICIAL_RELEASE_ARTIFACT_AVAILABILITY,
    "published availability schema"
  );
  requireSchemaConst(
    properties.policyVersion,
    PUBLISHED_OFFICIAL_RELEASE_ARTIFACT_POLICY_VERSION,
    "published policyVersion schema"
  );
  for (const key of ["models", "benchmarks", "sourceManifest", "scores"]) {
    const arraySchema = requireRecord(properties[key], `published ${key} schema`);
    if (arraySchema.type !== "array" || arraySchema.minItems !== 1) {
      throw new OfficialArtifactValidationError(
        `Published Official release artifact ${key} schema must require data.`
      );
    }
  }
  return schema;
}

export function validateOfficialReleaseAuthorizationContractSchema(input) {
  const schema = requireRecord(input, "Official release authorization schema");
  if (
    schema.$schema !== JSON_SCHEMA_DRAFT_2020_12 ||
    schema.$id !== OFFICIAL_RELEASE_AUTHORIZATION_SCHEMA_ID
  ) {
    throw new OfficialArtifactValidationError(
      "Official release authorization schema has an unexpected identity."
    );
  }
  if (schema.type !== "object" || schema.additionalProperties !== false) {
    throw new OfficialArtifactValidationError(
      "Official release authorization schema does not fail closed."
    );
  }
  requireExactStringSet(
    schema.required,
    RELEASE_AUTHORIZATION_KEYS,
    "Official release authorization schema required keys"
  );
  const properties = requireRecord(schema.properties, "Official release authorization schema properties");
  requireSchemaConst(
    properties.policyVersion,
    PUBLISHED_OFFICIAL_RELEASE_ARTIFACT_POLICY_VERSION,
    "authorization policyVersion schema"
  );
  return schema;
}

/** Return a recursively key-sorted JSON-compatible representation. */
export function canonicalizeJson(value) {
  if (value === null || typeof value === "string" || typeof value === "boolean") {
    return value;
  }
  if (typeof value === "number") {
    if (!Number.isFinite(value)) {
      throw new OfficialArtifactValidationError("Canonical JSON cannot contain a non-finite number.");
    }
    return value;
  }
  if (Array.isArray(value)) {
    return value.map((entry) => canonicalizeJson(entry));
  }
  if (isRecord(value)) {
    return Object.fromEntries(
      Object.keys(value)
        .sort()
        .map((key) => [key, canonicalizeJson(value[key])])
    );
  }
  throw new OfficialArtifactValidationError("Canonical JSON contains an unsupported value.");
}

export function canonicalOfficialArtifactJson(payload) {
  return JSON.stringify(canonicalizeJson(payload));
}

export function officialArtifactDigest(payload) {
  const document = canonicalizeJson(payload);
  if (!isRecord(document) || !isRecord(document.manifest)) {
    throw new OfficialArtifactValidationError("Official artifact cannot be hashed without a manifest.");
  }
  const digestInput = {
    ...document,
    manifest: { ...document.manifest, contentSha256: null },
  };
  return createHash("sha256").update(canonicalOfficialArtifactJson(digestInput)).digest("hex");
}

export function validateOfficialReleaseAuthorization(input) {
  const authorization = requireExactKeys(
    input,
    RELEASE_AUTHORIZATION_KEYS,
    "Official release authorization"
  );
  requireNonemptyString(authorization.artifactId, "Official release authorization artifactId");
  requireNonemptyString(
    authorization.releaseApprovalDecisionId,
    "Official release authorization releaseApprovalDecisionId"
  );
  if (authorization.policyVersion !== PUBLISHED_OFFICIAL_RELEASE_ARTIFACT_POLICY_VERSION) {
    throw new OfficialArtifactValidationError(
      "Official release authorization has an unsupported policy version."
    );
  }
  if (typeof authorization.contentSha256 !== "string" || !HEX_SHA256.test(authorization.contentSha256)) {
    throw new OfficialArtifactValidationError(
      "Official release authorization has an invalid content digest."
    );
  }
  return authorization;
}

function compareStrings(left, right) {
  return left === right ? 0 : left < right ? -1 : 1;
}

function compareNullableStrings(left, right) {
  if (left === right) return 0;
  if (left === null) return -1;
  if (right === null) return 1;
  return compareStrings(left, right);
}

function comparePublishedCells(left, right) {
  for (const key of ["modelId", "benchmarkId"]) {
    const comparison = compareStrings(left[key], right[key]);
    if (comparison !== 0) return comparison;
  }
  for (const key of ["metric", "split", "setting", "evaluationVersion"]) {
    const comparison = compareNullableStrings(left[key], right[key]);
    if (comparison !== 0) return comparison;
  }
  return 0;
}

function assertSortedUniqueIdentifiers(rows, key, label) {
  let previous = null;
  for (const row of rows) {
    const current = row[key];
    if (previous !== null && compareStrings(previous, current) >= 0) {
      throw new OfficialArtifactValidationError(`${label} must be sorted with unique identifiers.`);
    }
    previous = current;
  }
}

function requirePublicHttpsUrl(value, label) {
  try {
    const parsed = new URL(value);
    if (
      parsed.protocol !== "https:" ||
      !parsed.hostname ||
      parsed.username ||
      parsed.password ||
      parsed.hash ||
      [...value].some((character) => {
        const codePoint = character.codePointAt(0);
        return codePoint < 0x20 || codePoint === 0x7f;
      }) ||
      [...parsed.searchParams.keys()].some((key) =>
        CREDENTIAL_QUERY_KEYS.has(key.toLowerCase())
      )
    ) {
      throw new Error("unsafe URL");
    }
  } catch {
    throw new OfficialArtifactValidationError(`${label} must be a credential-free canonical HTTPS URL.`);
  }
}

function requireTimestamp(value, label) {
  if (
    typeof value !== "string" ||
    !RFC3339_TIMESTAMP.test(value) ||
    Number.isNaN(new Date(value).valueOf())
  ) {
    throw new OfficialArtifactValidationError(
      `${label} must be an RFC 3339 timestamp with at most six fractional digits.`
    );
  }
}

function validatePublishedArtifactRelationships(artifact) {
  assertSortedUniqueIdentifiers(artifact.models, "id", "Published Official release models");
  assertSortedUniqueIdentifiers(
    artifact.benchmarks,
    "id",
    "Published Official release benchmarks"
  );
  assertSortedUniqueIdentifiers(
    artifact.sourceManifest,
    "sourceManifestKey",
    "Published Official release source manifest"
  );

  const modelIds = new Set(artifact.models.map((model) => model.id));
  const benchmarkIds = new Set(artifact.benchmarks.map((benchmark) => benchmark.id));
  const sourceByKey = new Map(
    artifact.sourceManifest.map((source) => [source.sourceManifestKey, source])
  );
  const snapshotIds = artifact.sourceManifest.map((source) => source.sourceSnapshotId);
  if (new Set(snapshotIds).size !== snapshotIds.length) {
    throw new OfficialArtifactValidationError(
      "Published Official release source manifest repeats a source snapshot."
    );
  }
  for (const benchmark of artifact.benchmarks) {
    requirePublicHttpsUrl(benchmark.sourceUrl, "Published Official release benchmark sourceUrl");
  }
  for (const source of artifact.sourceManifest) {
    requirePublicHttpsUrl(source.sourceUrl, "Published Official release source manifest URL");
    requireTimestamp(
      source.snapshotCapturedAt,
      "Published Official release source manifest snapshotCapturedAt"
    );
  }

  const claimIds = new Set();
  const displayPairs = new Set();
  const referencedModels = new Set();
  const referencedBenchmarks = new Set();
  const referencedSources = new Set();
  let previousCell = null;
  const sourceFields = [
    "sourceManifestKey",
    "officialSourceId",
    "sourceRevisionId",
    "sourceRevisionDecisionId",
    "sourceName",
    "sourceUrl",
    "sourceType",
    "sourceRevisionDefinitionSha256",
    "sourceSnapshotId",
    "snapshotContentSha256",
    "snapshotCapturedAt",
  ];
  for (const score of artifact.scores) {
    requireTimestamp(score.reportedAt, "Published Official release score reportedAt");
    if (claimIds.has(score.claimId)) {
      throw new OfficialArtifactValidationError(
        "Published Official release artifact repeats a claim ID."
      );
    }
    claimIds.add(score.claimId);
    const cell = score.cell;
    if (!modelIds.has(cell.modelId) || !benchmarkIds.has(cell.benchmarkId)) {
      throw new OfficialArtifactValidationError(
        "Published Official release score references unknown display metadata."
      );
    }
    const pair = JSON.stringify([cell.modelId, cell.benchmarkId]);
    if (displayPairs.has(pair)) {
      throw new OfficialArtifactValidationError(
        "Published Official release artifact has multiple variants for one UI cell."
      );
    }
    displayPairs.add(pair);
    if (previousCell !== null && comparePublishedCells(previousCell, cell) >= 0) {
      throw new OfficialArtifactValidationError(
        "Published Official release scores must be sorted by unique display identity."
      );
    }
    previousCell = cell;

    const source = sourceByKey.get(score.provenance.sourceManifestKey);
    if (!source) {
      throw new OfficialArtifactValidationError(
        "Published Official release score references an unknown source manifest entry."
      );
    }
    for (const key of sourceFields) {
      if (score.provenance[key] !== source[key]) {
        throw new OfficialArtifactValidationError(
          "Published Official release score provenance does not match its source manifest entry."
        );
      }
    }
    referencedModels.add(cell.modelId);
    referencedBenchmarks.add(cell.benchmarkId);
    referencedSources.add(source.sourceManifestKey);
  }
  if (
    referencedModels.size !== modelIds.size ||
    referencedBenchmarks.size !== benchmarkIds.size ||
    referencedSources.size !== sourceByKey.size
  ) {
    throw new OfficialArtifactValidationError(
      "Published Official release artifact contains unreferenced display or source metadata."
    );
  }
}

export function validatePublishedOfficialReleaseArtifact(input, authorizationInput) {
  const artifact = requireExactKeys(
    input,
    PUBLISHED_TOP_LEVEL_KEYS,
    "Published Official release artifact"
  );
  if (artifact.schemaVersion !== PUBLISHED_OFFICIAL_RELEASE_ARTIFACT_SCHEMA_VERSION) {
    throw new OfficialArtifactValidationError(
      "Published Official release artifact has an unsupported schema version."
    );
  }
  if (artifact.artifactKind !== OFFICIAL_RELEASE_ARTIFACT_KIND) {
    throw new OfficialArtifactValidationError(
      "Published Official release artifact has an unsupported artifact kind."
    );
  }
  requireNonemptyString(artifact.artifactId, "Published Official release artifact artifactId");
  if (artifact.availability !== PUBLISHED_OFFICIAL_RELEASE_ARTIFACT_AVAILABILITY) {
    throw new OfficialArtifactValidationError(
      "Published Official release artifact is not marked published."
    );
  }
  if (artifact.policyVersion !== PUBLISHED_OFFICIAL_RELEASE_ARTIFACT_POLICY_VERSION) {
    throw new OfficialArtifactValidationError(
      "Published Official release artifact has an unsupported policy version."
    );
  }

  const approval = requireExactKeys(
    artifact.releaseApproval,
    RELEASE_APPROVAL_KEYS,
    "Published Official release approval"
  );
  requireNonemptyString(approval.decisionId, "Published Official release approval decisionId");
  requireNonemptyString(approval.approvedAt, "Published Official release approval approvedAt");
  requireTimestamp(approval.approvedAt, "Published Official release approval approvedAt");
  if (approval.policyVersion !== artifact.policyVersion) {
    throw new OfficialArtifactValidationError(
      "Published Official release approval policy does not match the artifact."
    );
  }

  const manifest = requireExactKeys(
    artifact.manifest,
    MANIFEST_KEYS,
    "Published Official release artifact manifest"
  );
  if (manifest.algorithm !== CANONICAL_JSON_ALGORITHM) {
    throw new OfficialArtifactValidationError(
      "Published Official release artifact uses an unsupported digest algorithm."
    );
  }
  if (typeof manifest.contentSha256 !== "string" || !HEX_SHA256.test(manifest.contentSha256)) {
    throw new OfficialArtifactValidationError(
      "Published Official release artifact has an invalid content digest."
    );
  }
  const arrays = ["models", "benchmarks", "sourceManifest", "scores"];
  for (const key of arrays) {
    if (!Array.isArray(artifact[key]) || artifact[key].length === 0) {
      throw new OfficialArtifactValidationError(
        `Published Official release artifact ${key} must contain data.`
      );
    }
  }
  const expectedCounts = {
    modelCount: artifact.models.length,
    benchmarkCount: artifact.benchmarks.length,
    sourceSnapshotCount: artifact.sourceManifest.length,
    scoreCount: artifact.scores.length,
  };
  for (const [key, expected] of Object.entries(expectedCounts)) {
    requireNonnegativeInteger(manifest[key], `Published Official release artifact manifest ${key}`);
    if (manifest[key] !== expected) {
      throw new OfficialArtifactValidationError(
        "Published Official release artifact manifest counts do not match its content."
      );
    }
  }
  const digest = officialArtifactDigest(artifact);
  if (manifest.contentSha256 !== digest) {
    throw new OfficialArtifactValidationError(
      "Published Official release artifact manifest digest does not match canonical content."
    );
  }
  validatePublishedArtifactRelationships(artifact);

  const authorization = validateOfficialReleaseAuthorization(authorizationInput);
  if (
    authorization.artifactId !== artifact.artifactId ||
    authorization.contentSha256 !== digest ||
    authorization.releaseApprovalDecisionId !== approval.decisionId ||
    authorization.policyVersion !== artifact.policyVersion
  ) {
    throw new OfficialArtifactValidationError(
      "Published Official release artifact does not exactly match its external authorization."
    );
  }
  return artifact;
}

export function verifyPublishedOfficialArtifactBytes(raw, authorizationInput) {
  let parsed;
  try {
    parsed = JSON.parse(raw);
  } catch (error) {
    throw new OfficialArtifactValidationError(
      `Published Official release artifact is not valid JSON: ${error instanceof Error ? error.message : String(error)}`
    );
  }
  if (raw !== canonicalOfficialArtifactJson(parsed)) {
    throw new OfficialArtifactValidationError(
      "Published Official release artifact bytes are not the canonical JSON representation."
    );
  }
  return validatePublishedOfficialReleaseArtifact(parsed, authorizationInput);
}

/**
 * Validate the containment artifact. It intentionally permits no published
 * availability and no score/source data in FEED-01.
 */
export function validateOfficialReleaseArtifact(input) {
  const artifact = requireExactKeys(input, TOP_LEVEL_KEYS, "Official release artifact");
  if (artifact.schemaVersion !== OFFICIAL_RELEASE_ARTIFACT_SCHEMA_VERSION) {
    throw new OfficialArtifactValidationError("Official release artifact has an unsupported schema version.");
  }
  if (artifact.artifactKind !== OFFICIAL_RELEASE_ARTIFACT_KIND) {
    throw new OfficialArtifactValidationError("Official release artifact has an unsupported artifact kind.");
  }
  requireNonemptyString(artifact.artifactId, "Official release artifact artifactId");
  if (artifact.availability !== OFFICIAL_RELEASE_ARTIFACT_AVAILABILITY) {
    throw new OfficialArtifactValidationError(
      "Official release artifact cannot claim published availability during containment."
    );
  }
  if (artifact.policyVersion !== OFFICIAL_RELEASE_ARTIFACT_POLICY_VERSION) {
    throw new OfficialArtifactValidationError("Official release artifact has an unsupported policy version.");
  }
  requireNonemptyString(artifact.reason, "Official release artifact reason");

  const manifest = requireExactKeys(artifact.manifest, MANIFEST_KEYS, "Official release artifact manifest");
  if (manifest.algorithm !== CANONICAL_JSON_ALGORITHM) {
    throw new OfficialArtifactValidationError("Official release artifact has an unsupported digest algorithm.");
  }
  if (typeof manifest.contentSha256 !== "string" || !HEX_SHA256.test(manifest.contentSha256)) {
    throw new OfficialArtifactValidationError("Official release artifact has an invalid content digest.");
  }
  for (const key of ["modelCount", "benchmarkCount", "sourceSnapshotCount", "scoreCount"]) {
    requireNonnegativeInteger(manifest[key], `Official release artifact manifest ${key}`);
  }

  for (const key of ["models", "benchmarks", "sourceManifest", "scores"]) {
    if (!Array.isArray(artifact[key]) || artifact[key].length !== 0) {
      throw new OfficialArtifactValidationError(
        "An unavailable Official release artifact must not contain claim, display, or source data."
      );
    }
  }
  if (
    manifest.modelCount !== 0 ||
    manifest.benchmarkCount !== 0 ||
    manifest.sourceSnapshotCount !== 0 ||
    manifest.scoreCount !== 0
  ) {
    throw new OfficialArtifactValidationError(
      "An unavailable Official release artifact manifest must contain only zero data counts."
    );
  }
  if (manifest.contentSha256 !== officialArtifactDigest(artifact)) {
    throw new OfficialArtifactValidationError(
      "Official release artifact manifest digest does not match canonical content."
    );
  }
  return artifact;
}

export async function verifyTrackedOfficialArtifact() {
  let raw;
  try {
    raw = await readFile(TRACKED_OFFICIAL_ARTIFACT_PATH, "utf8");
  } catch (error) {
    throw new OfficialArtifactValidationError(
      `Tracked Official artifact cannot be read: ${error instanceof Error ? error.message : String(error)}`
    );
  }
  let parsed;
  try {
    parsed = JSON.parse(raw);
  } catch (error) {
    throw new OfficialArtifactValidationError(
      `Tracked Official artifact is not valid JSON: ${error instanceof Error ? error.message : String(error)}`
    );
  }
  return validateOfficialReleaseArtifact(parsed);
}

export async function verifyTrackedOfficialArtifactContract() {
  let raw;
  try {
    raw = await readFile(TRACKED_OFFICIAL_ARTIFACT_CONTRACT_PATH, "utf8");
  } catch (error) {
    throw new OfficialArtifactValidationError(
      `Tracked Official artifact schema cannot be read: ${error instanceof Error ? error.message : String(error)}`
    );
  }
  let parsed;
  try {
    parsed = JSON.parse(raw);
  } catch (error) {
    throw new OfficialArtifactValidationError(
      `Tracked Official artifact schema is not valid JSON: ${error instanceof Error ? error.message : String(error)}`
    );
  }
  return validateOfficialArtifactContractSchema(parsed);
}

async function readJsonDocument(documentPath, label) {
  let raw;
  try {
    raw = await readFile(documentPath, "utf8");
  } catch (error) {
    throw new OfficialArtifactValidationError(
      `${label} cannot be read: ${error instanceof Error ? error.message : String(error)}`
    );
  }
  try {
    return JSON.parse(raw);
  } catch (error) {
    throw new OfficialArtifactValidationError(
      `${label} is not valid JSON: ${error instanceof Error ? error.message : String(error)}`
    );
  }
}

export async function verifyPublishedOfficialArtifactFiles(artifactPath, authorizationPath) {
  const [artifactRaw, authorization, artifactContract, authorizationContract] = await Promise.all([
    readFile(artifactPath, "utf8").catch((error) => {
      throw new OfficialArtifactValidationError(
        `Published Official release artifact cannot be read: ${error instanceof Error ? error.message : String(error)}`
      );
    }),
    readJsonDocument(authorizationPath, "Official release authorization"),
    readJsonDocument(PUBLISHED_OFFICIAL_ARTIFACT_CONTRACT_PATH, "Published Official release artifact schema"),
    readJsonDocument(
      OFFICIAL_RELEASE_AUTHORIZATION_CONTRACT_PATH,
      "Official release authorization schema"
    ),
  ]);
  validatePublishedOfficialArtifactContractSchema(artifactContract);
  validateOfficialReleaseAuthorizationContractSchema(authorizationContract);
  let schemaArtifact;
  try {
    schemaArtifact = JSON.parse(artifactRaw);
  } catch {
    return verifyPublishedOfficialArtifactBytes(artifactRaw, authorization);
  }
  validateJsonDocumentAgainstSchema(
    schemaArtifact,
    artifactContract,
    "Published Official release artifact"
  );
  validateJsonDocumentAgainstSchema(
    authorization,
    authorizationContract,
    "Official release authorization"
  );
  return verifyPublishedOfficialArtifactBytes(artifactRaw, authorization);
}

async function main() {
  const args = process.argv.slice(2);
  let artifact;
  if (args.length === 0) {
    [artifact] = await Promise.all([
      verifyTrackedOfficialArtifact(),
      verifyTrackedOfficialArtifactContract(),
    ]);
  } else if (
    args.length === 4 &&
    args[0] === "--published-artifact" &&
    args[2] === "--authorization"
  ) {
    artifact = await verifyPublishedOfficialArtifactFiles(args[1], args[3]);
  } else {
    throw new OfficialArtifactValidationError(
      "verify-official-artifact accepts either no arguments or --published-artifact PATH --authorization PATH."
    );
  }
  process.stdout.write(
    `${JSON.stringify({
      status: "valid",
      artifactId: artifact.artifactId,
      availability: artifact.availability,
      schemaVersion: artifact.schemaVersion,
      checks: {
        contractSchema: "valid",
        digest: {
          algorithm: artifact.manifest.algorithm,
          contentSha256: artifact.manifest.contentSha256,
          status: "valid",
        },
        provenance: {
          sourceManifestEntries: artifact.sourceManifest.length,
          sourceSnapshotCount: artifact.manifest.sourceSnapshotCount,
          status:
            artifact.availability === OFFICIAL_RELEASE_ARTIFACT_AVAILABILITY
              ? "valid-empty-containment-manifest"
              : "valid-published-manifest",
        },
      },
    })}\n`
  );
}

const invokedPath = process.argv[1] ? pathToFileURL(path.resolve(process.argv[1])).href : null;
if (invokedPath === import.meta.url) {
  main().catch((error) => {
    const message = error instanceof Error ? error.message : String(error);
    process.stderr.write(`Official artifact validation failed: ${message}\n`);
    process.exitCode = 2;
  });
}
