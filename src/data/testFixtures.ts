import type { Model, Benchmark, Score } from "../types";

/**
 * Self-contained test fixtures that do not depend on the production data
 * catalog. The production arrays (models, benchmarks, scores) are empty
 * until governed Official release artifacts supply real data.
 */

export const fixtureModel: Model = {
  id: "fixture-model-1",
  name: "Fixture Model 1",
  vendor: "TestVendor",
  family: "TestFamily",
  releaseDate: "2026-01-01",
  contextWindowK: 128,
  paramsB: null,
  modalities: ["text", "vision"],
  openWeights: false,
  priceInPer1M: 2.5,
  priceOutPer1M: 10,
};

export const fixtureBenchmark: Benchmark = {
  id: "fixture-bench-1",
  name: "Fixture Bench 1",
  fullName: "Fixture Benchmark 1",
  category: "knowledge",
  higherIsBetter: true,
  scaleMax: 100,
  description: "Test fixture benchmark.",
  methodology: "Test methodology.",
  sourceUrl: "https://example.test/bench",
};

export const fixtureScore: Score = {
  modelId: fixtureModel.id,
  benchmarkId: fixtureBenchmark.id,
  value: 88.5,
  date: "2026-01-01",
};

export function fixtureDataset() {
  return {
    models: [fixtureModel],
    benchmarks: [fixtureBenchmark],
    scores: [fixtureScore],
  };
}
