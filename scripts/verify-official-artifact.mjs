#!/usr/bin/env node
/**
 * Offline verifier for the only FEED-01 artifact legal during containment.
 *
 * It deliberately owns no output path and accepts no input override: a local
 * candidate projection, legacy report, or generated export must not be
 * repackaged into a frontend release artifact by accident. A later approved
 * release gate may introduce a distinct preparation command and published
 * contract; this verifier remains a safe check for the tracked baseline.
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
const HEX_SHA256 = /^[0-9a-f]{64}$/;

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

async function main() {
  if (process.argv.length !== 2) {
    throw new OfficialArtifactValidationError(
      "verify-official-artifact accepts no path or output arguments during containment."
    );
  }
  const [artifact] = await Promise.all([
    verifyTrackedOfficialArtifact(),
    verifyTrackedOfficialArtifactContract(),
  ]);
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
          status: "valid-empty-containment-manifest",
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
