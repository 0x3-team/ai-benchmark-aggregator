import type { Benchmark, Model, Score } from "../types";
import type { DatasetInput } from "../data/dataset";
import { CATEGORIES, type Modality } from "../types";

/**
 * Test-only large-dataset builder for the UI-07 scale budget.
 *
 * This module exists so regression tests can exercise the virtualized
 * ScoreTable, sort, and filter paths over a dataset far larger than the
 * shipped Demo catalog. It is NEVER a runtime input:
 *
 * - it must not be imported by `src/data/scores.ts`, the Demo catalog
 *   modules, or any module reachable from `src/main.tsx`;
 * - that boundary is enforced statically by
 *   `src/lib/scaleFixturesRuntimeGuard.test.ts`;
 * - generated rows are synthetic and carry no provenance, so they could
 *   never satisfy the Official release contract anyway.
 *
 * Every value is a pure function of (seed, modelIndex, benchmarkIndex), so
 * the dataset is deterministic across runs and machines without any
 * randomness, clock, or iteration-order dependence.
 */

export const SCALE_FIXTURE_SEED = 0x5ca1e5;
export const SCALE_MODEL_COUNT = 500;
export const SCALE_BENCHMARK_COUNT = 42;

/** splitmix32-style integer finalizer: deterministic 32-bit mixing. */
function mix32(value: number): number {
  let z = value >>> 0;
  z = (z + 0x9e3779b9) >>> 0;
  z = Math.imul(z ^ (z >>> 16), 0x21f0aaad) >>> 0;
  z = Math.imul(z ^ (z >>> 15), 0x735a2d97) >>> 0;
  return (z ^ (z >>> 15)) >>> 0;
}

/** Hash three coordinates into one 32-bit value, order-sensitive. */
function coordinateHash(a: number, b: number, c: number): number {
  return mix32(mix32(a ^ mix32(b)) ^ mix32(c));
}

/** Deterministic pseudo-random in [0, 1) for one (seed, i, j) coordinate. */
function unitInterval(a: number, b: number, c: number): number {
  return coordinateHash(a, b, c) / 0x100000000;
}

function round2(value: number): number {
  return Math.round(value * 100) / 100;
}

function pad(value: number, width: number): string {
  return String(value).padStart(width, "0");
}

export function scaleModelId(index: number): string {
  return `scale-model-${pad(index, 3)}`;
}

export function scaleBenchmarkId(index: number): string {
  return `scale-bench-${pad(index, 2)}`;
}

const SCALE_VENDORS = ["A", "B", "C", "D", "E", "F", "G", "H"] as const;

/** Deterministic model row; metadata nulls are spread on purpose. */
export function buildScaleModel(index: number): Model {
  const modalities: Modality[] = ["text"];
  if (index % 4 === 0) modalities.push("vision");
  if (index % 17 === 0) modalities.push("audio");
  const priceIn =
    index % 5 === 0 ? null : round2(((index % 40) + 1) * 0.25);
  return {
    id: scaleModelId(index),
    name: `Scale Model ${pad(index, 3)}`,
    vendor: `Vendor-${SCALE_VENDORS[index % SCALE_VENDORS.length]}`,
    family: `Family-${index % 12}`,
    releaseDate: `${2023 + (index % 3)}-${pad((index % 12) + 1, 2)}-${pad(
      (index % 27) + 1,
      2
    )}`,
    contextWindowK: index % 5 === 0 ? null : [32, 64, 128, 256][index % 4],
    paramsB: index % 3 === 0 ? null : ((index * 7) % 180) + 1,
    modalities,
    openWeights: index % 3 === 0 ? null : index % 2 === 0,
    priceInPer1M: priceIn,
    priceOutPer1M: priceIn === null ? null : round2(priceIn * 4),
  };
}

/**
 * Benchmarks cycle through every category; two columns use a /10 scale and
 * two are lower-is-better so formatting and direction paths stay exercised.
 */
export function buildScaleBenchmark(index: number): Benchmark {
  const id = scaleBenchmarkId(index);
  return {
    id,
    name: `ScaleBench ${pad(index, 2)}`,
    fullName: `Scale Benchmark ${pad(index, 2)}`,
    category: CATEGORIES[index % CATEGORIES.length],
    higherIsBetter: index !== 7 && index !== 23,
    scaleMax: index === 13 || index === 29 ? 10 : 100,
    description: `Synthetic scale-fixture benchmark ${index}.`,
    methodology: "Deterministic test fixture; no real evaluation exists.",
    sourceUrl: `https://example.test/${id}`,
  };
}


type CoverageClass = "none" | "full" | "sparse";

function coverageClass(modelIndex: number): CoverageClass {
  if (modelIndex % 25 === 0) return "none";
  if (modelIndex % 7 === 0) return "full";
  return "sparse";
}

function hasScore(seed: number, modelIndex: number, benchmarkIndex: number): boolean {
  const coverage = coverageClass(modelIndex);
  if (coverage === "none") return false;
  if (coverage === "full") return true;
  return unitInterval(seed, modelIndex, benchmarkIndex) < 0.6;
}

function scoreValue(
  seed: number,
  modelIndex: number,
  benchmarkIndex: number,
  scaleMax: number
): number {
  return round2(unitInterval(seed ^ 0x5eed, modelIndex, benchmarkIndex) * scaleMax);
}

/**
 * The exact value the builder places at one coordinate (null = no-data cell).
 * Tests use this to verify the dataset and the rendered grid independently
 * of the builder's internal assembly order.
 */
export function expectedScaleValue(
  modelIndex: number,
  benchmarkIndex: number,
  seed: number = SCALE_FIXTURE_SEED
): number | null {
  if (!hasScore(seed, modelIndex, benchmarkIndex)) return null;
  return scoreValue(seed, modelIndex, benchmarkIndex, buildScaleBenchmark(benchmarkIndex).scaleMax);
}

export interface ScaleDatasetOptions {
  readonly modelCount?: number;
  readonly benchmarkCount?: number;
  readonly seed?: number;
}

/**
 * Build the deterministic large dataset (default 500 models x 42
 * benchmarks, matching the documented UI-07 baseline). The result is a
 * plain `DatasetInput` for `DatasetProvider`; it is not frozen because the
 * provider performs the immutable snapshot step, exactly like app data.
 */
export function buildScaleDataset(options: ScaleDatasetOptions = {}): DatasetInput {
  const modelCount = options.modelCount ?? SCALE_MODEL_COUNT;
  const benchmarkCount = options.benchmarkCount ?? SCALE_BENCHMARK_COUNT;
  const seed = options.seed ?? SCALE_FIXTURE_SEED;

  const models: Model[] = [];
  for (let i = 0; i < modelCount; i += 1) models.push(buildScaleModel(i));

  const benchmarks: Benchmark[] = [];
  for (let j = 0; j < benchmarkCount; j += 1) benchmarks.push(buildScaleBenchmark(j));

  const scores: Score[] = [];
  for (let i = 0; i < modelCount; i += 1) {
    for (let j = 0; j < benchmarkCount; j += 1) {
      if (!hasScore(seed, i, j)) continue;
      scores.push({
        modelId: scaleModelId(i),
        benchmarkId: scaleBenchmarkId(j),
        value: scoreValue(seed, i, j, benchmarks[j].scaleMax),
        date: `2025-${pad((j % 12) + 1, 2)}-${pad((i % 27) + 1, 2)}`,
      });
    }
  }

  return { models, benchmarks, scores };
}
