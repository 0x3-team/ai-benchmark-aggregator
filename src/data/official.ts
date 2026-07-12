import type { Benchmark, BenchmarkCategory, Model, Score } from "../types";
import { CATEGORIES } from "../types";
import ledgerExport from "./official/export.from-ledger.json";
import sampleExport from "./official/export.sample.json";

// Official ledger export shape (schemaVersion 0.1.0). Provenance fields are
// optional because the committed sample is a trimmed version of the real
// `export.from-ledger.json` produced by `benchmark-ledger export-official-json`.

interface OfficialEvidenceRaw {
  type?: string;
  path?: string;
  model_path?: string;
}

interface OfficialScoreRaw {
  modelId: string;
  benchmarkId: string;
  value: number;
  scoreRaw?: string | null;
  date?: string | null;
  captureStatus?: string | null;
  officialSourceId?: string | null;
  sourceSnapshotId?: string | null;
  evidenceLocation?: OfficialEvidenceRaw | null;
  claimId?: string | null;
}

interface OfficialBenchmarkRaw {
  id: string;
  name: string;
  fullName: string;
  category: string;
  higherIsBetter: boolean;
  scaleMax: number;
  primaryMetric?: string;
}

interface OfficialModelRaw {
  id: string;
  name: string;
  vendor: string;
  family?: string | null;
  raw_name?: string;
}

interface OfficialExport {
  schemaVersion: string;
  trustLevel?: string;
  models: OfficialModelRaw[];
  benchmarks: OfficialBenchmarkRaw[];
  scores: OfficialScoreRaw[];
  note?: string;
}

const KNOWN_CATEGORIES = new Set<string>(CATEGORIES);

// Official benchmark categories (e.g. "meta_registry") do not always map onto the
// demo capability taxonomy. Anything unknown is bucketed as "other" so it still
// renders instead of being dropped or crashing the category Records.
function normalizeCategory(raw: string): BenchmarkCategory {
  return (KNOWN_CATEGORIES.has(raw) ? raw : "other") as BenchmarkCategory;
}

// Ledger models only carry identity + vendor. Fill the missing demo-only spec
// fields with neutral defaults so the Model shape stays consistent.
function toModels(raw: OfficialModelRaw[]): Model[] {
  return raw.map((m) => ({
    id: m.id,
    name: m.name,
    vendor: m.vendor,
    family: m.family ?? "unknown",
    releaseDate: "",
    contextWindowK: 0,
    paramsB: null,
    modalities: ["text"] as Model["modalities"],
    openWeights: false,
    priceInPer1M: null,
    priceOutPer1M: null,
  }));
}

function toBenchmarks(raw: OfficialBenchmarkRaw[]): Benchmark[] {
  return raw.map((b) => ({
    id: b.id,
    name: b.name,
    fullName: b.fullName,
    category: normalizeCategory(b.category),
    higherIsBetter: b.higherIsBetter,
    scaleMax: b.scaleMax,
    // The ledger export does not carry descriptive prose; leave blanks rather
    // than inventing methodology text for source-backed claims.
    description: "",
    methodology: "",
    sourceUrl: "",
  }));
}

// Preserve raw source values exactly (scoreRaw) and carry the full provenance
// chain so the UI can surface it without recalculating anything.
function toScores(raw: OfficialScoreRaw[]): Score[] {
  return raw.map((s) => ({
    modelId: s.modelId,
    benchmarkId: s.benchmarkId,
    value: s.value,
    date: s.date ?? "",
    scoreRaw: s.scoreRaw ?? null,
    captureStatus: s.captureStatus ?? null,
    officialSourceId: s.officialSourceId ?? null,
    sourceSnapshotId: s.sourceSnapshotId ?? null,
    evidenceLocation: s.evidenceLocation
      ? {
          type: s.evidenceLocation.type ?? "",
          path: s.evidenceLocation.path ?? null,
          modelPath: s.evidenceLocation.model_path ?? null,
        }
      : null,
    claimId: s.claimId ?? null,
  }));
}

// Prefer the real ledger export; fall back to the committed sample only if the
// ledger export is empty/missing models (ADR-003).
function selectExport(): OfficialExport {
  const ledger = ledgerExport as unknown as OfficialExport;
  if (ledger.models.length > 0 && ledger.scores.length > 0) return ledger;
  return sampleExport as unknown as OfficialExport;
}

export interface OfficialDataset {
  models: Model[];
  benchmarks: Benchmark[];
  scores: Score[];
  note: string;
}

export function loadOfficialData(): OfficialDataset {
  const exp = selectExport();
  return {
    models: toModels(exp.models),
    benchmarks: toBenchmarks(exp.benchmarks),
    scores: toScores(exp.scores),
    note:
      exp.note ??
      "Values are source-backed claims, not independently recalculated scores.",
  };
}
