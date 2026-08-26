import { describe, expect, it } from "vitest";
import { createDatasetAccess } from "../data/dataset";
import {
  SCALE_BENCHMARK_COUNT,
  SCALE_FIXTURE_SEED,
  SCALE_MODEL_COUNT,
  buildScaleDataset,
  expectedScaleValue,
  scaleBenchmarkId,
  scaleModelId,
} from "./scaleFixtures";

// Golden coordinates captured from the deterministic generator. If these
// change, the generator seed or hash drifted and every scale receipt must
// be regenerated and re-recorded in the runbook.
const GOLDEN_VALUES: ReadonlyArray<readonly [number, number, number | null]> = [
  [7, 3, 64.47],
  [42, 23, 64.46],
  [123, 7, 92.27],
  [499, 41, 31.34],
  [0, 0, null],
  [1, 0, null],
  [25, 0, null],
  [100, 13, null],
  [200, 29, null],
];

describe("scaleFixtures builder", () => {
  it("is deterministic across builds and defaults to the pinned seed", () => {
    const first = buildScaleDataset();
    const second = buildScaleDataset();
    const explicitSeed = buildScaleDataset({ seed: SCALE_FIXTURE_SEED });
    expect(JSON.stringify(first)).toBe(JSON.stringify(second));
    expect(JSON.stringify(first)).toBe(JSON.stringify(explicitSeed));
  });

  it("matches the documented 500 x 42 baseline shape", () => {
    const dataset = buildScaleDataset();
    expect(dataset.models).toHaveLength(SCALE_MODEL_COUNT);
    expect(dataset.benchmarks).toHaveLength(SCALE_BENCHMARK_COUNT);
    expect(SCALE_MODEL_COUNT).toBe(500);
    expect(SCALE_BENCHMARK_COUNT).toBe(42);
    expect(dataset.scores).toHaveLength(13253);
    // 7747 cells stay empty so no-data rendering is exercised at scale.
    expect(SCALE_MODEL_COUNT * SCALE_BENCHMARK_COUNT - dataset.scores.length).toBe(7747);
  });

  it("references only known ids and keeps values inside each column scale", () => {
    const dataset = buildScaleDataset();
    const scaleByBenchmark = new Map(
      dataset.benchmarks.map((benchmark) => [benchmark.id, benchmark.scaleMax])
    );
    const modelIds = new Set(dataset.models.map((model) => model.id));
    expect(modelIds.size).toBe(dataset.models.length);
    const invalidScores: string[] = [];
    for (const score of dataset.scores) {
      const scaleMax = scaleByBenchmark.get(score.benchmarkId);
      if (scaleMax === undefined) invalidScores.push(`${score.modelId}/${score.benchmarkId}: unknown benchmark`);
      if (!modelIds.has(score.modelId)) invalidScores.push(`${score.modelId}/${score.benchmarkId}: unknown model`);
      if (
        !Number.isFinite(score.value) ||
        score.value < 0 ||
        score.value > (scaleMax ?? 0)
      ) {
        invalidScores.push(`${score.modelId}/${score.benchmarkId}: out-of-range value ${score.value}`);
      }
    }
    expect(invalidScores).toEqual([]);
  });

  it("pins golden cell values so generator drift fails loudly", () => {
    for (const [modelIndex, benchmarkIndex, expected] of GOLDEN_VALUES) {
      expect(expectedScaleValue(modelIndex, benchmarkIndex)).toBe(expected);
    }
  });

  it("keeps the documented coverage classes (empty rows, full rows, sparse rows)", () => {
    const dataset = buildScaleDataset();
    const counts = new Map<string, number>();
    for (const score of dataset.scores) {
      counts.set(score.modelId, (counts.get(score.modelId) ?? 0) + 1);
    }
    let empty = 0;
    let full = 0;
    for (const model of dataset.models) {
      const covered = counts.get(model.id) ?? 0;
      if (covered === 0) empty += 1;
      if (covered === SCALE_BENCHMARK_COUNT) full += 1;
    }
    expect(empty).toBe(20);
    expect(full).toBe(69);
  });

  it("is accepted by the immutable dataset boundary and answers through getValue", () => {
    const access = createDatasetAccess(buildScaleDataset());
    expect(access.models).toHaveLength(SCALE_MODEL_COUNT);
    expect(access.officialRelease).toBeNull();
    // Sweep a strided set of coordinates plus every golden coordinate.
    for (let i = 0; i < SCALE_MODEL_COUNT; i += 37) {
      for (let j = 0; j < SCALE_BENCHMARK_COUNT; j += 5) {
        expect(access.getValue(scaleModelId(i), scaleBenchmarkId(j))).toBe(
          expectedScaleValue(i, j)
        );
      }
    }
    for (const [modelIndex, benchmarkIndex, expected] of GOLDEN_VALUES) {
      expect(access.getValue(scaleModelId(modelIndex), scaleBenchmarkId(benchmarkIndex))).toBe(
        expected
      );
    }
    // Provenance stays value-free: entries must not leak numeric scores.
    const entry = access.getScoreEntry(scaleModelId(7), scaleBenchmarkId(3));
    expect(entry).not.toBeNull();
    expect(JSON.stringify(entry)).not.toContain("64.47");
  });
});
