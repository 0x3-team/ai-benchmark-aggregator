import unavailableArtifact from "./official/export.unavailable.json";
import type {
  Benchmark,
  BenchmarkCategory,
  Model,
  Modality,
  OfficialDisplayIdentity,
  OfficialEvidenceLocation,
  OfficialReleaseContext,
  OfficialScoreProvenance,
  OfficialSourceManifestEntry,
  Score,
} from "../types";
import type { DatasetInput } from "./dataset";

export interface OfficialUnavailableResult {
  readonly availability: "unavailable";
  readonly reason: string;
  readonly artifactId?: string;
}

export interface OfficialReleaseApproval {
  readonly decisionId: string;
  readonly policyVersion: string;
  readonly approvedAt: string;
}

export interface PublishedArtifactManifest {
  readonly algorithm: string;
  readonly contentSha256: string;
  readonly modelCount: number;
  readonly benchmarkCount: number;
  readonly sourceSnapshotCount: number;
  readonly scoreCount: number;
}

export interface PublishedArtifactMetadata {
  readonly artifactId: string;
  readonly policyVersion: string;
  readonly releaseApproval: OfficialReleaseApproval;
  readonly manifest: PublishedArtifactManifest;
  readonly sourceManifest: readonly OfficialSourceManifestEntry[];
}

export interface OfficialPublishedResult {
  readonly availability: "published";
  readonly artifact: PublishedArtifactMetadata;
  readonly data: DatasetInput;
}

export type OfficialLoadResult = OfficialUnavailableResult | OfficialPublishedResult;

/**
 * A release gate pins the exact approved artifact digest outside that artifact.
 * A v2 document is never sufficient by itself: a future REL-05 implementation
 * must obtain this authorization from its governed release process before it
 * calls the dormant parser below.
 */
export interface OfficialReleaseAuthorization {
  readonly artifactId: string;
  readonly releaseApprovalDecisionId: string;
  readonly policyVersion: string;
  readonly contentSha256: string;
}

const UNAVAILABLE_SCHEMA_VERSION = "1.0.0";
const UNAVAILABLE_POLICY_VERSION = "official-release-artifact-v1";
const PUBLISHED_SCHEMA_VERSION = "2.0.0";
const PUBLISHED_POLICY_VERSION = "official-release-artifact-v2";
const OFFICIAL_ARTIFACT_KIND = "official-release-artifact";
const CANONICAL_JSON_ALGORITHM = "sha256-canonical-json-v1";
const SHA256_HEX = /^[0-9a-f]{64}$/;
const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;
const ISO_TIMESTAMP =
  /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$/;

const UNAVAILABLE_ARTIFACT_KEYS = new Set([
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
const PUBLISHED_ARTIFACT_KEYS = new Set([
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
const MANIFEST_KEYS = new Set([
  "algorithm",
  "contentSha256",
  "modelCount",
  "benchmarkCount",
  "sourceSnapshotCount",
  "scoreCount",
]);
const RELEASE_APPROVAL_KEYS = new Set(["decisionId", "policyVersion", "approvedAt"]);
const MODEL_KEYS = new Set([
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
]);
const BENCHMARK_KEYS = new Set([
  "id",
  "name",
  "fullName",
  "category",
  "higherIsBetter",
  "scaleMax",
  "description",
  "methodology",
  "sourceUrl",
]);
const SOURCE_MANIFEST_KEYS = new Set([
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
]);
const CELL_KEYS = new Set([
  "modelId",
  "benchmarkId",
  "metric",
  "split",
  "setting",
  "evaluationVersion",
]);
const EVIDENCE_KEYS = new Set([
  "type",
  "locator",
  "modelLocator",
  "benchmarkLocator",
  "scoreLocator",
]);
const SCORE_KEYS = new Set([
  "cell",
  "claimId",
  "value",
  "modelRaw",
  "benchmarkRaw",
  "scoreRaw",
  "scoreUnit",
  "reportedAt",
  "evidenceText",
  "evidence",
  "provenance",
]);
const SCORE_PROVENANCE_KEYS = new Set([
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
  "claimReviewDecisionId",
  "claimPublicationDecisionId",
  "captureMethod",
]);
const MODALITIES = new Set<Modality>(["text", "vision", "audio"]);
const BENCHMARK_CATEGORIES = new Set<BenchmarkCategory>([
  "knowledge",
  "reasoning",
  "math",
  "coding",
  "agentic",
  "instruction",
  "chat",
  "vision",
  "other",
]);
const EVIDENCE_TYPES = new Set<OfficialEvidenceLocation["type"]>([
  "json_pointer",
  "html_selector",
  "text_span",
]);

class PublishedArtifactParseError extends Error {}

function unavailable(reason: string, artifactId?: string): OfficialUnavailableResult {
  return Object.freeze({
    availability: "unavailable" as const,
    reason,
    ...(artifactId ? { artifactId } : {}),
  });
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function hasExactKeys(value: Record<string, unknown>, expected: Set<string>): boolean {
  const keys = Object.keys(value);
  return keys.length === expected.size && keys.every((key) => expected.has(key));
}

function hasNonemptyString(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

function hasIdentifier(value: unknown): value is string {
  return hasNonemptyString(value) && value === value.trim();
}

function isNullableString(value: unknown): value is string | null {
  return value === null || hasNonemptyString(value);
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function isNonnegativeFiniteNumber(value: unknown): value is number {
  return isFiniteNumber(value) && value >= 0;
}

function isPositiveFiniteNumber(value: unknown): value is number {
  return isFiniteNumber(value) && value > 0;
}

function isPositiveInteger(value: unknown): value is number {
  return Number.isInteger(value) && typeof value === "number" && value > 0;
}

function isNullableNonnegativeFiniteNumber(value: unknown): value is number | null {
  return value === null || isNonnegativeFiniteNumber(value);
}

function isSha256(value: unknown): value is string {
  return typeof value === "string" && SHA256_HEX.test(value);
}

function isIsoDate(value: unknown): value is string {
  if (typeof value !== "string" || !ISO_DATE.test(value)) return false;
  const parsed = new Date(`${value}T00:00:00.000Z`);
  return !Number.isNaN(parsed.valueOf()) && parsed.toISOString().slice(0, 10) === value;
}

function isIsoTimestamp(value: unknown): value is string {
  return (
    typeof value === "string" &&
    ISO_TIMESTAMP.test(value) &&
    !Number.isNaN(new Date(value).valueOf())
  );
}

function isSafeHttpsUrl(value: unknown): value is string {
  if (!hasNonemptyString(value)) return false;
  try {
    const url = new URL(value);
    return (
      url.protocol === "https:" &&
      url.hostname.length > 0 &&
      !url.username &&
      !url.password &&
      !url.search &&
      !url.hash &&
      !/[?#]/.test(value)
    );
  } catch {
    return false;
  }
}

function isZeroCount(value: unknown): boolean {
  return value === 0;
}

function parseError(message: string): never {
  throw new PublishedArtifactParseError(message);
}

function requireRecord(value: unknown, keys: Set<string>, label: string): Record<string, unknown> {
  if (!isRecord(value) || !hasExactKeys(value, keys)) {
    parseError(`${label} has an invalid contract shape.`);
  }
  return value;
}

function requireIdentifier(value: unknown, label: string): string {
  if (!hasIdentifier(value)) parseError(`${label} must be a non-empty stable identifier.`);
  return value;
}

function requireNonemptyRaw(value: unknown, label: string): string {
  if (!hasNonemptyString(value)) parseError(`${label} must preserve a non-empty raw value.`);
  return value;
}

function requireNullableString(value: unknown, label: string): string | null {
  if (!isNullableString(value)) parseError(`${label} must be a non-empty string or null.`);
  return value;
}

function requireTimestamp(value: unknown, label: string): string {
  if (!isIsoTimestamp(value)) parseError(`${label} must be an ISO-8601 timestamp.`);
  return value;
}

function requireSha256(value: unknown, label: string): string {
  if (!isSha256(value)) parseError(`${label} must be a lowercase SHA-256 digest.`);
  return value;
}

function assertSortedUnique(values: readonly string[], label: string): void {
  for (let index = 0; index < values.length; index += 1) {
    if (index > 0 && values[index - 1] >= values[index]) {
      parseError(`${label} must be sorted with unique identifiers.`);
    }
  }
}

function compareNullableStrings(left: string | null, right: string | null): number {
  if (left === right) return 0;
  if (left === null) return -1;
  if (right === null) return 1;
  return left < right ? -1 : 1;
}

function compareCells(left: OfficialDisplayIdentity, right: OfficialDisplayIdentity): number {
  const keys: (keyof OfficialDisplayIdentity)[] = [
    "modelId",
    "benchmarkId",
    "metric",
    "split",
    "setting",
    "evaluationVersion",
  ];
  for (const key of keys) {
    const a = left[key];
    const b = right[key];
    const comparison =
      typeof a === "string" && typeof b === "string"
        ? a === b
          ? 0
          : a < b
            ? -1
            : 1
        : compareNullableStrings(a, b);
    if (comparison !== 0) return comparison;
  }
  return 0;
}

function cellKey(cell: OfficialDisplayIdentity): string {
  return JSON.stringify([
    cell.modelId,
    cell.benchmarkId,
    cell.metric,
    cell.split,
    cell.setting,
    cell.evaluationVersion,
  ]);
}

function pairKey(modelId: string, benchmarkId: string): string {
  return JSON.stringify([modelId, benchmarkId]);
}

function parsePublishedManifest(value: unknown): PublishedArtifactManifest {
  const manifest = requireRecord(value, MANIFEST_KEYS, "Official published artifact manifest");
  if (manifest.algorithm !== CANONICAL_JSON_ALGORITHM) {
    parseError("Official published artifact uses an unsupported integrity algorithm.");
  }
  const contentSha256 = requireSha256(
    manifest.contentSha256,
    "Official published artifact manifest contentSha256"
  );
  const countKeys = [
    "modelCount",
    "benchmarkCount",
    "sourceSnapshotCount",
    "scoreCount",
  ] as const;
  for (const key of countKeys) {
    if (!Number.isInteger(manifest[key]) || (manifest[key] as number) < 0) {
      parseError(`Official published artifact manifest ${key} must be a non-negative integer.`);
    }
  }
  return Object.freeze({
    algorithm: CANONICAL_JSON_ALGORITHM,
    contentSha256,
    modelCount: manifest.modelCount as number,
    benchmarkCount: manifest.benchmarkCount as number,
    sourceSnapshotCount: manifest.sourceSnapshotCount as number,
    scoreCount: manifest.scoreCount as number,
  });
}

function parseReleaseApproval(value: unknown): OfficialReleaseApproval {
  const approval = requireRecord(value, RELEASE_APPROVAL_KEYS, "Official release approval");
  const decisionId = requireIdentifier(approval.decisionId, "Official release approval decisionId");
  if (approval.policyVersion !== PUBLISHED_POLICY_VERSION) {
    parseError("Official release approval has an unsupported policy version.");
  }
  return Object.freeze({
    decisionId,
    policyVersion: PUBLISHED_POLICY_VERSION,
    approvedAt: requireTimestamp(approval.approvedAt, "Official release approval approvedAt"),
  });
}

function parseModel(value: unknown): Model {
  const model = requireRecord(value, MODEL_KEYS, "Official published model");
  const id = requireIdentifier(model.id, "Official published model id");
  const stringKeys = ["name", "vendor", "family"] as const;
  for (const key of stringKeys) {
    if (!hasNonemptyString(model[key])) parseError(`Official published model ${key} is incomplete.`);
  }
  if (!isIsoDate(model.releaseDate)) {
    parseError("Official published model releaseDate must be an ISO calendar date.");
  }
  if (model.contextWindowK !== null && !isPositiveInteger(model.contextWindowK)) {
    parseError("Official published model contextWindowK must be a positive integer or null.");
  }
  if (!isNullableNonnegativeFiniteNumber(model.paramsB)) {
    parseError("Official published model paramsB must be finite, non-negative, or null.");
  }
  if (!Array.isArray(model.modalities) || model.modalities.length === 0) {
    parseError("Official published model modalities must be a non-empty array.");
  }
  const modalities: Modality[] = [];
  for (const modality of model.modalities) {
    if (typeof modality !== "string" || !MODALITIES.has(modality as Modality)) {
      parseError("Official published model contains an unsupported modality.");
    }
    if (modalities.includes(modality as Modality)) {
      parseError("Official published model modalities must be unique.");
    }
    modalities.push(modality as Modality);
  }
  if (model.openWeights !== null && typeof model.openWeights !== "boolean") {
    parseError("Official published model openWeights must be a boolean or null.");
  }
  for (const key of ["priceInPer1M", "priceOutPer1M"] as const) {
    if (!isNullableNonnegativeFiniteNumber(model[key])) {
      parseError(`Official published model ${key} must be finite, non-negative, or null.`);
    }
  }
  return Object.freeze({
    id,
    name: model.name as string,
    vendor: model.vendor as string,
    family: model.family as string,
    releaseDate: model.releaseDate,
    contextWindowK: model.contextWindowK as number | null,
    paramsB: model.paramsB,
    modalities: Object.freeze(modalities),
    openWeights: model.openWeights as boolean | null,
    priceInPer1M: model.priceInPer1M as number | null,
    priceOutPer1M: model.priceOutPer1M as number | null,
  });
}

function parseBenchmark(value: unknown): Benchmark {
  const benchmark = requireRecord(value, BENCHMARK_KEYS, "Official published benchmark");
  const id = requireIdentifier(benchmark.id, "Official published benchmark id");
  for (const key of ["name", "fullName", "description", "methodology"] as const) {
    if (!hasNonemptyString(benchmark[key])) {
      parseError(`Official published benchmark ${key} is incomplete.`);
    }
  }
  if (
    typeof benchmark.category !== "string" ||
    !BENCHMARK_CATEGORIES.has(benchmark.category as BenchmarkCategory)
  ) {
    parseError("Official published benchmark has an unsupported category.");
  }
  if (typeof benchmark.higherIsBetter !== "boolean") {
    parseError("Official published benchmark higherIsBetter must be explicit.");
  }
  if (!isPositiveFiniteNumber(benchmark.scaleMax)) {
    parseError("Official published benchmark scaleMax must be finite and positive.");
  }
  if (!isSafeHttpsUrl(benchmark.sourceUrl)) {
    parseError("Official published benchmark sourceUrl must be a credential-free HTTPS URL.");
  }
  return Object.freeze({
    id,
    name: benchmark.name as string,
    fullName: benchmark.fullName as string,
    category: benchmark.category as BenchmarkCategory,
    higherIsBetter: benchmark.higherIsBetter,
    scaleMax: benchmark.scaleMax,
    description: benchmark.description as string,
    methodology: benchmark.methodology as string,
    sourceUrl: benchmark.sourceUrl,
  });
}

function parseSourceManifestEntry(value: unknown): OfficialSourceManifestEntry {
  const source = requireRecord(value, SOURCE_MANIFEST_KEYS, "Official source manifest entry");
  const idKeys = [
    "sourceManifestKey",
    "officialSourceId",
    "sourceRevisionId",
    "sourceRevisionDecisionId",
    "sourceSnapshotId",
  ] as const;
  for (const key of idKeys) requireIdentifier(source[key], `Official source manifest ${key}`);
  for (const key of ["sourceName", "sourceType"] as const) {
    if (!hasNonemptyString(source[key])) parseError(`Official source manifest ${key} is incomplete.`);
  }
  if (!isSafeHttpsUrl(source.sourceUrl)) {
    parseError("Official source manifest sourceUrl must be a credential-free HTTPS URL.");
  }
  return Object.freeze({
    sourceManifestKey: source.sourceManifestKey as string,
    officialSourceId: source.officialSourceId as string,
    sourceRevisionId: source.sourceRevisionId as string,
    sourceRevisionDecisionId: source.sourceRevisionDecisionId as string,
    sourceName: source.sourceName as string,
    sourceUrl: source.sourceUrl,
    sourceType: source.sourceType as string,
    sourceRevisionDefinitionSha256: requireSha256(
      source.sourceRevisionDefinitionSha256,
      "Official source manifest sourceRevisionDefinitionSha256"
    ),
    sourceSnapshotId: source.sourceSnapshotId as string,
    snapshotContentSha256: requireSha256(
      source.snapshotContentSha256,
      "Official source manifest snapshotContentSha256"
    ),
    snapshotCapturedAt: requireTimestamp(
      source.snapshotCapturedAt,
      "Official source manifest snapshotCapturedAt"
    ),
  });
}

function parseCell(value: unknown): OfficialDisplayIdentity {
  const cell = requireRecord(value, CELL_KEYS, "Official published score cell");
  const modelId = requireIdentifier(cell.modelId, "Official published score cell modelId");
  const benchmarkId = requireIdentifier(cell.benchmarkId, "Official published score cell benchmarkId");
  const optionalKeys = ["metric", "split", "setting", "evaluationVersion"] as const;
  for (const key of optionalKeys) requireNullableString(cell[key], `Official published score cell ${key}`);
  return Object.freeze({
    modelId,
    benchmarkId,
    metric: cell.metric as string | null,
    split: cell.split as string | null,
    setting: cell.setting as string | null,
    evaluationVersion: cell.evaluationVersion as string | null,
  });
}

function parseEvidence(value: unknown): OfficialEvidenceLocation {
  const evidence = requireRecord(value, EVIDENCE_KEYS, "Official score evidence");
  if (typeof evidence.type !== "string" || !EVIDENCE_TYPES.has(evidence.type as OfficialEvidenceLocation["type"])) {
    parseError("Official score evidence has an unsupported evidence type.");
  }
  for (const key of ["locator", "modelLocator", "benchmarkLocator", "scoreLocator"] as const) {
    if (!hasNonemptyString(evidence[key])) parseError(`Official score evidence ${key} is incomplete.`);
  }
  return Object.freeze({
    type: evidence.type as OfficialEvidenceLocation["type"],
    locator: evidence.locator as string,
    modelLocator: evidence.modelLocator as string,
    benchmarkLocator: evidence.benchmarkLocator as string,
    scoreLocator: evidence.scoreLocator as string,
  });
}

function parseScoreProvenance(
  value: unknown,
  sourceByKey: ReadonlyMap<string, OfficialSourceManifestEntry>
): {
  readonly source: OfficialSourceManifestEntry;
  readonly claimReviewDecisionId: string;
  readonly claimPublicationDecisionId: string;
  readonly captureMethod: string;
} {
  const provenance = requireRecord(value, SCORE_PROVENANCE_KEYS, "Official score provenance");
  const sourceManifestKey = requireIdentifier(
    provenance.sourceManifestKey,
    "Official score provenance sourceManifestKey"
  );
  const source = sourceByKey.get(sourceManifestKey);
  if (!source) parseError("Official score provenance references an unknown source manifest entry.");
  const sharedKeys = [
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
  ] as const;
  for (const key of sharedKeys) {
    if (provenance[key] !== source[key]) {
      parseError("Official score provenance does not exactly match its source manifest entry.");
    }
  }
  return Object.freeze({
    source,
    claimReviewDecisionId: requireIdentifier(
      provenance.claimReviewDecisionId,
      "Official score provenance claimReviewDecisionId"
    ),
    claimPublicationDecisionId: requireIdentifier(
      provenance.claimPublicationDecisionId,
      "Official score provenance claimPublicationDecisionId"
    ),
    captureMethod: requireNonemptyRaw(
      provenance.captureMethod,
      "Official score provenance captureMethod"
    ),
  });
}

function parseScore(
  value: unknown,
  modelIds: ReadonlySet<string>,
  benchmarkIds: ReadonlySet<string>,
  sourceByKey: ReadonlyMap<string, OfficialSourceManifestEntry>
): Score {
  const score = requireRecord(value, SCORE_KEYS, "Official published score");
  const displayIdentity = parseCell(score.cell);
  if (!modelIds.has(displayIdentity.modelId) || !benchmarkIds.has(displayIdentity.benchmarkId)) {
    parseError("Official published score references an unknown model or benchmark.");
  }
  if (!isFiniteNumber(score.value)) {
    parseError("Official published score value must be a finite number.");
  }
  const claimId = requireIdentifier(score.claimId, "Official published score claimId");
  const modelRaw = requireNonemptyRaw(score.modelRaw, "Official published score modelRaw");
  const benchmarkRaw = requireNonemptyRaw(score.benchmarkRaw, "Official published score benchmarkRaw");
  const scoreRaw = requireNonemptyRaw(score.scoreRaw, "Official published score scoreRaw");
  const scoreUnit = requireNullableString(score.scoreUnit, "Official published score scoreUnit");
  const reportedAt = requireTimestamp(score.reportedAt, "Official published score reportedAt");
  const evidenceText = requireNullableString(score.evidenceText, "Official published score evidenceText");
  const evidence = parseEvidence(score.evidence);
  const parsedProvenance = parseScoreProvenance(score.provenance, sourceByKey);
  const officialProvenance: OfficialScoreProvenance = Object.freeze({
    displayIdentity,
    modelRaw,
    benchmarkRaw,
    scoreRaw,
    scoreUnit,
    evidenceText,
    evidence,
    source: parsedProvenance.source,
    claimReviewDecisionId: parsedProvenance.claimReviewDecisionId,
    claimPublicationDecisionId: parsedProvenance.claimPublicationDecisionId,
    captureMethod: parsedProvenance.captureMethod,
  });
  return Object.freeze({
    modelId: displayIdentity.modelId,
    benchmarkId: displayIdentity.benchmarkId,
    value: score.value,
    date: reportedAt,
    scoreRaw,
    captureStatus: "published",
    officialSourceId: parsedProvenance.source.officialSourceId,
    sourceSnapshotId: parsedProvenance.source.sourceSnapshotId,
    evidenceLocation: Object.freeze({
      type: evidence.type,
      path: evidence.scoreLocator,
      modelPath: evidence.modelLocator,
    }),
    claimId,
    officialProvenance,
  });
}

function parsePublishedArtifact(input: unknown): {
  readonly artifactId: string;
  readonly releaseApproval: OfficialReleaseApproval;
  readonly manifest: PublishedArtifactManifest;
  readonly sourceManifest: readonly OfficialSourceManifestEntry[];
  readonly data: DatasetInput;
} {
  const artifact = requireRecord(input, PUBLISHED_ARTIFACT_KEYS, "Official published artifact");
  if (artifact.schemaVersion !== PUBLISHED_SCHEMA_VERSION) {
    parseError("Official published artifact has an unsupported schema version.");
  }
  if (artifact.artifactKind !== OFFICIAL_ARTIFACT_KIND) {
    parseError("Official published artifact has an unsupported artifact kind.");
  }
  const artifactId = requireIdentifier(artifact.artifactId, "Official published artifact artifactId");
  if (artifact.availability !== "published") {
    parseError("Official published artifact is not marked published.");
  }
  if (artifact.policyVersion !== PUBLISHED_POLICY_VERSION) {
    parseError("Official published artifact has an unsupported release policy.");
  }
  const releaseApproval = parseReleaseApproval(artifact.releaseApproval);
  const manifest = parsePublishedManifest(artifact.manifest);
  if (!Array.isArray(artifact.models) || !Array.isArray(artifact.benchmarks)) {
    parseError("Official published artifact models and benchmarks must be arrays.");
  }
  const models = artifact.models.map(parseModel);
  const benchmarks = artifact.benchmarks.map(parseBenchmark);
  assertSortedUnique(
    models.map((model) => model.id),
    "Official published artifact models"
  );
  assertSortedUnique(
    benchmarks.map((benchmark) => benchmark.id),
    "Official published artifact benchmarks"
  );
  if (!Array.isArray(artifact.sourceManifest)) {
    parseError("Official published artifact sourceManifest must be an array.");
  }
  const sourceManifest = artifact.sourceManifest.map(parseSourceManifestEntry);
  assertSortedUnique(
    sourceManifest.map((source) => source.sourceManifestKey),
    "Official published artifact sourceManifest"
  );
  const snapshotIds = sourceManifest.map((source) => source.sourceSnapshotId);
  if (new Set(snapshotIds).size !== snapshotIds.length) {
    parseError("Official published artifact sourceManifest cannot repeat a source snapshot.");
  }
  const sourceByKey = new Map(sourceManifest.map((source) => [source.sourceManifestKey, source]));
  if (!Array.isArray(artifact.scores)) {
    parseError("Official published artifact scores must be an array.");
  }
  const modelIds = new Set(models.map((model) => model.id));
  const benchmarkIds = new Set(benchmarks.map((benchmark) => benchmark.id));
  const scores = artifact.scores.map((score) =>
    parseScore(score, modelIds, benchmarkIds, sourceByKey)
  );
  if (scores.length === 0) {
    parseError("A published Official artifact must contain at least one score.");
  }
  const claimIds = new Set<string>();
  const cells = new Set<string>();
  const pairs = new Set<string>();
  const referencedModels = new Set<string>();
  const referencedBenchmarks = new Set<string>();
  const referencedSources = new Set<string>();
  let previousCell: OfficialDisplayIdentity | null = null;
  for (const score of scores) {
    const provenance = score.officialProvenance;
    if (!provenance) parseError("Official published score lost its required provenance.");
    if (claimIds.has(score.claimId!)) parseError("Official published artifact contains a duplicate claimId.");
    claimIds.add(score.claimId!);
    const cell = provenance.displayIdentity;
    const fullCellKey = cellKey(cell);
    if (cells.has(fullCellKey)) parseError("Official published artifact contains a duplicate display cell.");
    cells.add(fullCellKey);
    const displayPair = pairKey(cell.modelId, cell.benchmarkId);
    if (pairs.has(displayPair)) {
      parseError(
        "Official published artifact has multiple metric variants for one UI score cell."
      );
    }
    pairs.add(displayPair);
    if (previousCell && compareCells(previousCell, cell) >= 0) {
      parseError("Official published artifact scores must be sorted by display identity.");
    }
    previousCell = cell;
    referencedModels.add(cell.modelId);
    referencedBenchmarks.add(cell.benchmarkId);
    referencedSources.add(provenance.source.sourceManifestKey);
  }
  if (referencedModels.size !== models.length || referencedBenchmarks.size !== benchmarks.length) {
    parseError("Official published artifact contains unreferenced display metadata.");
  }
  if (referencedSources.size !== sourceManifest.length) {
    parseError("Official published artifact contains an unreferenced source manifest entry.");
  }
  if (
    manifest.modelCount !== models.length ||
    manifest.benchmarkCount !== benchmarks.length ||
    manifest.sourceSnapshotCount !== sourceManifest.length ||
    manifest.scoreCount !== scores.length
  ) {
    parseError("Official published artifact manifest counts do not match its content.");
  }
  const officialRelease: OfficialReleaseContext = Object.freeze({
    artifactId,
    policyVersion: PUBLISHED_POLICY_VERSION,
    releaseApprovalDecisionId: releaseApproval.decisionId,
    releaseApprovedAt: releaseApproval.approvedAt,
    sourceManifest: Object.freeze(sourceManifest),
  });
  return Object.freeze({
    artifactId,
    releaseApproval,
    manifest,
    sourceManifest: Object.freeze(sourceManifest),
    data: Object.freeze({
      models: Object.freeze(models),
      benchmarks: Object.freeze(benchmarks),
      scores: Object.freeze(scores),
      officialRelease,
    }),
  });
}

/** Return a recursively key-sorted JSON-compatible value. */
function canonicalizeJson(value: unknown): unknown {
  if (value === null || typeof value === "string" || typeof value === "boolean") return value;
  if (typeof value === "number") {
    if (!Number.isFinite(value)) throw new PublishedArtifactParseError("Canonical JSON contains a non-finite number.");
    return value;
  }
  if (Array.isArray(value)) return value.map((entry) => canonicalizeJson(entry));
  if (isRecord(value)) {
    return Object.fromEntries(
      Object.keys(value)
        .sort()
        .map((key) => [key, canonicalizeJson(value[key])])
    );
  }
  throw new PublishedArtifactParseError("Canonical JSON contains an unsupported value.");
}

/**
 * Canonical digest used by the future v2 contract. It is intentionally public
 * for offline release tooling and test fixtures, not an authorization API.
 */
export async function publishedArtifactDigest(payload: unknown): Promise<string> {
  const document = canonicalizeJson(payload);
  if (!isRecord(document) || !isRecord(document.manifest)) {
    throw new PublishedArtifactParseError("Official published artifact cannot be hashed without a manifest.");
  }
  const digestInput = {
    ...document,
    manifest: { ...document.manifest, contentSha256: null },
  };
  const subtle = globalThis.crypto?.subtle;
  if (!subtle) {
    throw new PublishedArtifactParseError("Web Crypto digest verification is unavailable.");
  }
  const digest = await subtle.digest(
    "SHA-256",
    new TextEncoder().encode(JSON.stringify(canonicalizeJson(digestInput)))
  );
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

function authorizationMatches(
  authorization: OfficialReleaseAuthorization,
  artifactId: string,
  approval: OfficialReleaseApproval,
  digest: string
): boolean {
  return (
    isRecord(authorization) &&
    authorization.artifactId === artifactId &&
    authorization.releaseApprovalDecisionId === approval.decisionId &&
    authorization.policyVersion === PUBLISHED_POLICY_VERSION &&
    authorization.contentSha256 === digest &&
    isSha256(authorization.contentSha256)
  );
}

/**
 * Parse a separately supplied, release-authorized v2 artifact. This function
 * is deliberately dormant during containment: `loadOfficialData()` never
 * calls it and the repository contains no v2 artifact or authorization.
 */
export async function parsePublishedOfficialArtifact(
  input: unknown,
  authorization: OfficialReleaseAuthorization
): Promise<OfficialLoadResult> {
  let artifactId: string | undefined;
  try {
    const parsed = parsePublishedArtifact(input);
    artifactId = parsed.artifactId;
    const digest = await publishedArtifactDigest(input);
    if (digest !== parsed.manifest.contentSha256) {
      return unavailable("The Official artifact integrity digest does not match its content.", artifactId);
    }
    if (!authorizationMatches(authorization, parsed.artifactId, parsed.releaseApproval, digest)) {
      return unavailable(
        "The Official artifact is not authorized by the governed release gate for this build.",
        artifactId
      );
    }
    return Object.freeze({
      availability: "published" as const,
      artifact: Object.freeze({
        artifactId: parsed.artifactId,
        policyVersion: PUBLISHED_POLICY_VERSION,
        releaseApproval: parsed.releaseApproval,
        manifest: parsed.manifest,
        sourceManifest: parsed.sourceManifest,
      }),
      data: parsed.data,
    });
  } catch (error) {
    const reason =
      error instanceof PublishedArtifactParseError
        ? error.message
        : "The Official artifact could not be verified safely.";
    return unavailable(reason, artifactId);
  }
}

/**
 * Parse the only artifact state that is legal during the containment phase.
 * The current runtime accepts no candidate, report, sample, local export, or
 * published v2 document. The separate v2 parser above remains dormant until
 * REL-05 supplies an approved immutable artifact and authorization pin.
 */
export function parseOfficialArtifact(input: unknown): OfficialLoadResult {
  if (!isRecord(input)) {
    return unavailable("The bundled Official artifact is malformed.");
  }

  const artifact = input;
  if (!hasExactKeys(artifact, UNAVAILABLE_ARTIFACT_KEYS)) {
    return unavailable("The bundled Official artifact has an invalid containment shape.");
  }
  if (artifact.schemaVersion !== UNAVAILABLE_SCHEMA_VERSION) {
    return unavailable("The bundled Official artifact has an unsupported schema version.");
  }
  if (artifact.artifactKind !== OFFICIAL_ARTIFACT_KIND) {
    return unavailable("The bundled Official artifact has an unsupported artifact kind.");
  }
  if (!hasNonemptyString(artifact.artifactId)) {
    return unavailable("The bundled Official artifact has no immutable artifact identity.");
  }
  if (artifact.availability !== "unavailable") {
    return unavailable("Official publication is not enabled for this build.", artifact.artifactId);
  }
  if (artifact.policyVersion !== UNAVAILABLE_POLICY_VERSION) {
    return unavailable("The bundled Official artifact has an unsupported release policy.", artifact.artifactId);
  }
  if (!hasNonemptyString(artifact.reason)) {
    return unavailable(
      "The bundled Official artifact does not explain its availability state.",
      artifact.artifactId
    );
  }
  if (!isRecord(artifact.manifest) || !hasExactKeys(artifact.manifest, MANIFEST_KEYS)) {
    return unavailable("The bundled Official artifact has an invalid immutable manifest.", artifact.artifactId);
  }
  if (
    artifact.manifest.algorithm !== CANONICAL_JSON_ALGORITHM ||
    !hasNonemptyString(artifact.manifest.contentSha256) ||
    !SHA256_HEX.test(artifact.manifest.contentSha256) ||
    !isZeroCount(artifact.manifest.modelCount) ||
    !isZeroCount(artifact.manifest.benchmarkCount) ||
    !isZeroCount(artifact.manifest.sourceSnapshotCount) ||
    !isZeroCount(artifact.manifest.scoreCount)
  ) {
    return unavailable("The bundled Official artifact has an invalid containment manifest.", artifact.artifactId);
  }
  if (
    !Array.isArray(artifact.models) ||
    !Array.isArray(artifact.benchmarks) ||
    !Array.isArray(artifact.sourceManifest) ||
    !Array.isArray(artifact.scores) ||
    artifact.models.length !== 0 ||
    artifact.benchmarks.length !== 0 ||
    artifact.sourceManifest.length !== 0 ||
    artifact.scores.length !== 0
  ) {
    return unavailable("An unavailable Official artifact must not contain claim data.", artifact.artifactId);
  }

  return unavailable(artifact.reason, artifact.artifactId);
}

/** The runtime containment loader has exactly one tracked input. */
export function loadOfficialData(): OfficialLoadResult {
  return parseOfficialArtifact(unavailableArtifact);
}
