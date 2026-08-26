export type BenchmarkCategory =
  | "knowledge"
  | "reasoning"
  | "math"
  | "coding"
  | "agentic"
  | "instruction"
  | "chat"
  | "vision"
  | "embedding"
  | "other";

export type Modality = "text" | "vision" | "audio";

/**
 * The domain contract used by presentation calculations.  Raw-only metrics
 * remain available as raw table values, but must never be turned into a
 * comparable percentage without an approved domain.
 */
export type BenchmarkNormalization =
  | {
      kind: "bounded";
      min: number;
      max: number;
    }
  | {
      kind: "raw_only";
      reason: "signed_metric" | "rating_metric" | "uncertain_domain";
    };

export interface Model {
  id: string;
  name: string;
  vendor: string;
  family: string;
  releaseDate: string;
  /** Null means the selected dataset did not supply this metadata. */
  contextWindowK: number | null;
  paramsB: number | null;
  modalities: readonly Modality[];
  /** Null means the selected dataset did not supply this metadata. */
  openWeights: boolean | null;
  priceInPer1M: number | null;
  priceOutPer1M: number | null;
}

export interface Benchmark {
  id: string;
  name: string;
  fullName: string;
  category: BenchmarkCategory;
  higherIsBetter: boolean;
  scaleMax: number;
  description: string;
  methodology: string;
  sourceUrl: string;
  /** Optional bounded-domain metadata used by presentation-only aggregates. */
  normalization?: BenchmarkNormalization;
}

export interface ScoreEvidence {
  type: string;
  path: string | null;
  modelPath: string | null;
}

/**
 * The display identity that an Official release explicitly selected.  The
 * React grid currently has one cell per model/benchmark pair, but retaining
 * all six dimensions here prevents a later feed adapter from silently hiding
 * the metric, split, setting, or evaluation-version decision behind a number.
 */
export interface OfficialDisplayIdentity {
  modelId: string;
  benchmarkId: string;
  metric: string | null;
  split: string | null;
  setting: string | null;
  evaluationVersion: string | null;
}

/** A closed evidence envelope used only by the governed release contract. */
export interface OfficialEvidenceLocation {
  type: "json_pointer" | "html_selector" | "text_span";
  locator: string;
  modelLocator: string;
  benchmarkLocator: string;
  scoreLocator: string;
}

/** One immutable source/snapshot row from a governed release manifest. */
export interface OfficialSourceManifestEntry {
  sourceManifestKey: string;
  officialSourceId: string;
  sourceRevisionId: string;
  sourceRevisionDecisionId: string;
  sourceName: string;
  sourceUrl: string;
  sourceType: string;
  sourceRevisionDefinitionSha256: string;
  sourceSnapshotId: string;
  snapshotContentSha256: string;
  snapshotCapturedAt: string;
}

/**
 * Immutable release-level context carried alongside a published dataset.
 * It deliberately contains no score value: score cells remain reachable only
 * through `getValue`, while evidence UI can use the policy and source manifest
 * that governed the selected release.
 */
export interface OfficialReleaseContext {
  artifactId: string;
  policyVersion: string;
  releaseApprovalDecisionId: string;
  releaseApprovedAt: string;
  sourceManifest: readonly OfficialSourceManifestEntry[];
}

/**
 * Provenance preserved from a governed published artifact.  This is separate
 * from the legacy loose `ScoreEvidence` fields so test fixtures remain simple
 * while Official data retains all release-critical raw fields.
 */
export interface OfficialScoreProvenance {
  displayIdentity: OfficialDisplayIdentity;
  modelRaw: string;
  benchmarkRaw: string;
  scoreRaw: string;
  scoreUnit: string | null;
  evidenceText: string | null;
  evidence: OfficialEvidenceLocation;
  source: OfficialSourceManifestEntry;
  claimReviewDecisionId: string;
  claimPublicationDecisionId: string;
  captureMethod: string;
}

export interface Score {
  modelId: string;
  benchmarkId: string;
  value: number;
  date: string;
  note?: string;
  // Provenance — present only for official ledger claims (ADR-003). Legacy
  // test fixtures omit these fields, so they remain optional at this boundary.
  scoreRaw?: string | null;
  captureStatus?: string | null;
  officialSourceId?: string | null;
  sourceSnapshotId?: string | null;
  evidenceLocation?: ScoreEvidence | null;
  claimId?: string | null;
  officialProvenance?: OfficialScoreProvenance | null;
}

export const CATEGORY_LABELS: Record<BenchmarkCategory, string> = {
  knowledge: "Knowledge",
  reasoning: "Reasoning",
  math: "Math",
  coding: "Coding",
  agentic: "Agentic",
  instruction: "Instruction",
  chat: "Chat",
  vision: "Vision",
  embedding: "Embeddings",
  other: "Other",
};

export const CATEGORIES: BenchmarkCategory[] = [
  "knowledge",
  "reasoning",
  "math",
  "coding",
  "agentic",
  "instruction",
  "chat",
  "vision",
  "other",
];

/** Complete governed category list, including the separate embedding class. */
export const ALL_CATEGORIES: BenchmarkCategory[] = [...CATEGORIES, "embedding"];

export function categoriesForBenchmarks(
  benchmarks: readonly Pick<Benchmark, "category">[]
): readonly BenchmarkCategory[] {
  const hasEmbedding = benchmarks.some((benchmark) => benchmark.category === "embedding");
  const hasGeneral = benchmarks.some((benchmark) => benchmark.category !== "embedding");
  if (hasEmbedding && !hasGeneral) return ["embedding"];
  return hasEmbedding ? ALL_CATEGORIES : CATEGORIES;
}
