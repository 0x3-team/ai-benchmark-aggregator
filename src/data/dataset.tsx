import {
  createContext,
  useContext,
  useMemo,
  type ReactNode,
} from "react";
import type {
  Benchmark,
  Model,
  Modality,
  OfficialReleaseContext,
  OfficialScoreProvenance,
  OfficialSourceManifestEntry,
  Score,
  ScoreEvidence,
} from "../types";

/**
 * A model snapshot as exposed to the React dataset boundary.  The source
 * catalog remains mutable while it is assembled, but consumers only receive
 * frozen records and a frozen modalities list.
 */
export type DatasetModel = Readonly<Omit<Model, "modalities">> & {
  readonly modalities: readonly Modality[];
};

export type DatasetBenchmark = Readonly<Benchmark>;

export type DatasetOfficialRelease = Readonly<
  Omit<OfficialReleaseContext, "sourceManifest">
> & {
  readonly sourceManifest: readonly Readonly<OfficialSourceManifestEntry>[];
};

/**
 * Provenance is deliberately value-free: UI code may inspect evidence and
 * claim identity, but must ask `getValue` for a numeric score.
 */
export type ScoreProvenance = Readonly<
  Omit<Score, "value" | "evidenceLocation">
> & {
  readonly evidenceLocation?: Readonly<ScoreEvidence> | null;
};

export interface DatasetInput {
  readonly models: readonly Model[];
  readonly benchmarks: readonly Benchmark[];
  readonly scores: readonly Score[];
  /** Present only in a validated, governed Official release snapshot. */
  readonly officialRelease?: OfficialReleaseContext;
}

export type GetValue = (modelId: string, benchmarkId: string) => number | null;
export type GetScoreEntry = (modelId: string, benchmarkId: string) => ScoreProvenance | null;

export interface DatasetAccess {
  readonly models: readonly DatasetModel[];
  readonly benchmarks: readonly DatasetBenchmark[];
  /** Release policy/source context; null for Demo and any non-governed data. */
  readonly officialRelease: DatasetOfficialRelease | null;
  readonly getValue: GetValue;
  readonly getScoreEntry: GetScoreEntry;
}

interface ScoreCell {
  readonly score: Readonly<Score>;
  readonly provenance: ScoreProvenance;
}

function immutableModels(models: readonly Model[]): readonly DatasetModel[] {
  return Object.freeze(
    models.map((model): DatasetModel =>
      Object.freeze({
        ...model,
        modalities: Object.freeze([...model.modalities]),
      })
    )
  );
}

function immutableBenchmarks(
  benchmarks: readonly Benchmark[]
): readonly DatasetBenchmark[] {
  return Object.freeze(
    benchmarks.map((benchmark): DatasetBenchmark => Object.freeze({ ...benchmark }))
  );
}

function immutableScores(scores: readonly Score[]): readonly Score[] {
  return scores.map((score) =>
    score.evidenceLocation || score.officialProvenance
      ? Object.freeze({
          ...score,
          evidenceLocation: score.evidenceLocation
            ? Object.freeze({ ...score.evidenceLocation })
            : score.evidenceLocation,
          officialProvenance: immutableOfficialProvenance(score.officialProvenance),
        })
      : score
  );
}

function immutableOfficialProvenance(
  provenance: OfficialScoreProvenance | null | undefined
): OfficialScoreProvenance | null | undefined {
  if (!provenance) return provenance;
  return Object.freeze({
    ...provenance,
    displayIdentity: Object.freeze({ ...provenance.displayIdentity }),
    evidence: Object.freeze({ ...provenance.evidence }),
    source: Object.freeze({ ...provenance.source }),
  });
}

function immutableOfficialRelease(
  release: OfficialReleaseContext | undefined
): DatasetOfficialRelease | null {
  if (!release) return null;
  return Object.freeze({
    artifactId: release.artifactId,
    policyVersion: release.policyVersion,
    releaseApprovalDecisionId: release.releaseApprovalDecisionId,
    releaseApprovedAt: release.releaseApprovedAt,
    sourceManifest: Object.freeze(
      release.sourceManifest.map((source) => Object.freeze({ ...source }))
    ),
  });
}

function provenanceFor(score: Readonly<Score>): ScoreProvenance {
  const { value: _value, evidenceLocation, ...provenance } = score;
  return Object.freeze({
    ...provenance,
    evidenceLocation: evidenceLocation
      ? Object.freeze({ ...evidenceLocation })
      : evidenceLocation,
  });
}

function assertUniqueIds<T extends { readonly id: string }>(
  records: readonly T[],
  label: string
): void {
  const ids = new Set<string>();
  for (const record of records) {
    if (ids.has(record.id)) {
      throw new Error(`Dataset contains a duplicate ${label} id: ${record.id}`);
    }
    ids.add(record.id);
  }
}

/**
 * Build one immutable dataset snapshot and its private score index.
 *
 * The returned `getValue(modelId, benchmarkId)` is the only numeric score
 * accessor exposed to the UI. The index is scoped to this snapshot rather
 * than a module-global active dataset, so two provider renders cannot leak
 * scores or provenance into one another.
 */
export function createDatasetAccess(input: DatasetInput): DatasetAccess {
  const models = immutableModels(input.models);
  const benchmarks = immutableBenchmarks(input.benchmarks);
  const scores = immutableScores(input.scores);
  const officialRelease = immutableOfficialRelease(input.officialRelease);
  assertUniqueIds(models, "model");
  assertUniqueIds(benchmarks, "benchmark");

  const modelIds = new Set(models.map((model) => model.id));
  const benchmarkIds = new Set(benchmarks.map((benchmark) => benchmark.id));
  const scoreIndex = new Map<string, Map<string, ScoreCell>>();
  for (const score of scores) {
    if (!modelIds.has(score.modelId) || !benchmarkIds.has(score.benchmarkId)) {
      throw new Error(
        `Dataset score cell references an unknown model or benchmark: ${score.modelId}/${score.benchmarkId}`
      );
    }
    const cellsForModel = scoreIndex.get(score.modelId) ?? new Map<string, ScoreCell>();
    if (cellsForModel.has(score.benchmarkId)) {
      throw new Error(
        `Dataset contains a duplicate score cell: ${score.modelId}/${score.benchmarkId}`
      );
    }
    cellsForModel.set(score.benchmarkId, {
      score,
      provenance: provenanceFor(score),
    });
    scoreIndex.set(score.modelId, cellsForModel);
  }

  const getScoreEntry: GetScoreEntry = (modelId, benchmarkId) =>
    scoreIndex.get(modelId)?.get(benchmarkId)?.provenance ?? null;
  const getValue: GetValue = (modelId, benchmarkId) =>
    scoreIndex.get(modelId)?.get(benchmarkId)?.score.value ?? null;

  return Object.freeze({ models, benchmarks, officialRelease, getValue, getScoreEntry });
}

const DatasetContext = createContext<DatasetAccess | null>(null);

interface DatasetProviderProps {
  data: DatasetInput;
  children: ReactNode;
}

/**
 * The app's active dataset boundary. A provider receives one immutable
 * snapshot, and every consumer gets the same scoped accessors on its first
 * render. There is intentionally no default/demo fallback outside a provider.
 */
export function DatasetProvider({ data, children }: DatasetProviderProps) {
  const dataset = useMemo(() => createDatasetAccess(data), [data]);
  return <DatasetContext.Provider value={dataset}>{children}</DatasetContext.Provider>;
}

export function useDataset(): DatasetAccess {
  const dataset = useContext(DatasetContext);
  if (dataset === null) {
    throw new Error("useDataset must be used inside DatasetProvider.");
  }
  return dataset;
}
