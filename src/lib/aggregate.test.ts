import { describe, expect, it } from "vitest";
import { createDatasetAccess, type GetValue } from "../data/dataset";
import {
  bestModelId,
  categoryLeader,
  computeRanking,
  sortModels,
} from "./aggregate";

const dataset = createDatasetAccess({
  models: [
    {
      id: "alpha",
      name: "Alpha",
      vendor: "Fixture",
      family: "Fixture",
      releaseDate: "2026-01-01",
      contextWindowK: 1,
      paramsB: null,
      modalities: ["text"],
      openWeights: false,
      priceInPer1M: null,
      priceOutPer1M: null,
    },
    {
      id: "beta",
      name: "Beta",
      vendor: "Fixture",
      family: "Fixture",
      releaseDate: "2026-01-01",
      contextWindowK: 1,
      paramsB: null,
      modalities: ["text"],
      openWeights: false,
      priceInPer1M: null,
      priceOutPer1M: null,
    },
  ],
  benchmarks: [
    {
      id: "accuracy",
      name: "Accuracy",
      fullName: "Fixture accuracy",
      category: "reasoning",
      higherIsBetter: true,
      scaleMax: 100,
      description: "Fixture only.",
      methodology: "Fixture only.",
      sourceUrl: "https://example.invalid/fixture",
    },
  ],
  scores: [
    { modelId: "alpha", benchmarkId: "accuracy", value: 10, date: "2026-01-01" },
    { modelId: "beta", benchmarkId: "accuracy", value: 20, date: "2026-01-01" },
  ],
});

describe("aggregate dataset injection", () => {
  it("uses the explicit getValue snapshot rather than hidden module-global state", () => {
    const inverse: GetValue = (modelId, benchmarkId) => {
      if (benchmarkId !== "accuracy") return null;
      return modelId === "alpha" ? 20 : modelId === "beta" ? 10 : null;
    };

    expect(
      computeRanking(dataset.models, dataset.benchmarks, dataset.getValue).map(
        (row) => row.model.id
      )
    ).toEqual(["beta", "alpha"]);
    expect(
      computeRanking(dataset.models, dataset.benchmarks, inverse).map((row) => row.model.id)
    ).toEqual(["alpha", "beta"]);
    expect(
      bestModelId("accuracy", dataset.models, dataset.benchmarks, dataset.getValue)
    ).toBe("beta");
    expect(bestModelId("accuracy", dataset.models, dataset.benchmarks, inverse)).toBe("alpha");
  });

  it("leaves model order intact when a selected benchmark is absent from the active snapshot", () => {
    const result = sortModels(
      dataset.models,
      { benchmarkId: "removed-benchmark", dir: "desc" },
      dataset.benchmarks,
      dataset.benchmarks,
      dataset.getValue
    );

    expect(result.map((model) => model.id)).toEqual(["alpha", "beta"]);
  });
});

function fixtureModel(id: string, name: string) {
  return {
    id,
    name,
    vendor: "Fixture",
    family: "Fixture",
    releaseDate: "2026-01-01",
    contextWindowK: 1,
    paramsB: null,
    modalities: ["text"] as const,
    openWeights: false,
    priceInPer1M: null,
    priceOutPer1M: null,
  };
}

function fixtureBenchmark(id: string, category: "reasoning" | "math") {
  return {
    id,
    name: id,
    fullName: `Fixture ${id}`,
    category,
    higherIsBetter: true,
    scaleMax: 100,
    description: "Fixture only.",
    methodology: "Fixture only.",
    sourceUrl: "https://example.invalid/fixture",
  };
}

describe("coverage-aware presentation ranking", () => {
  it("does not rank a partial model ahead of models with complete cohort coverage", () => {
    const complete = fixtureModel("complete", "Complete");
    const partial = fixtureModel("partial", "Partial");
    const trailing = fixtureModel("trailing", "Trailing");
    const first = fixtureBenchmark("first", "reasoning");
    const second = fixtureBenchmark("second", "reasoning");
    const fixture = createDatasetAccess({
      models: [complete, partial, trailing],
      benchmarks: [first, second],
      scores: [
        { modelId: complete.id, benchmarkId: first.id, value: 80, date: "2026-01-01" },
        { modelId: complete.id, benchmarkId: second.id, value: 80, date: "2026-01-01" },
        { modelId: partial.id, benchmarkId: first.id, value: 100, date: "2026-01-01" },
        { modelId: trailing.id, benchmarkId: first.id, value: 20, date: "2026-01-01" },
        { modelId: trailing.id, benchmarkId: second.id, value: 20, date: "2026-01-01" },
      ],
    });

    const ranking = computeRanking(fixture.models, fixture.benchmarks, fixture.getValue);
    const byId = new Map(ranking.map((row) => [row.model.id, row]));

    expect(ranking.map((row) => row.model.id)).toEqual(["complete", "trailing", "partial"]);
    expect(byId.get("complete")).toMatchObject({ rank: 1, covered: 2, total: 2 });
    expect(byId.get("trailing")).toMatchObject({ rank: 2, covered: 2, total: 2 });
    expect(byId.get("partial")).toMatchObject({
      rank: null,
      covered: 1,
      total: 2,
      unrankedReason: "incomplete_coverage",
    });

    expect(
      sortModels(
        [partial, trailing, complete],
        null,
        fixture.benchmarks,
        fixture.benchmarks,
        fixture.getValue,
        ranking
      ).map((model) => model.id)
    ).toEqual(["complete", "trailing", "partial"]);

    expect(categoryLeader(fixture.models, fixture.benchmarks, fixture.getValue)).toEqual([
      {
        category: "reasoning",
        modelId: "complete",
        avg: 0.8,
        n: 2,
        total: 2,
      },
    ]);
  });

  it("uses competition ranks for score ties and a stable model-id order for display", () => {
    const alpha = fixtureModel("alpha", "Alpha");
    const beta = fixtureModel("beta", "Beta");
    const gamma = fixtureModel("gamma", "Gamma");
    const benchmark = fixtureBenchmark("tied", "reasoning");
    const fixture = createDatasetAccess({
      models: [gamma, beta, alpha],
      benchmarks: [benchmark],
      scores: [
        { modelId: alpha.id, benchmarkId: benchmark.id, value: 50, date: "2026-01-01" },
        { modelId: beta.id, benchmarkId: benchmark.id, value: 50, date: "2026-01-01" },
        { modelId: gamma.id, benchmarkId: benchmark.id, value: 10, date: "2026-01-01" },
      ],
    });

    const ranking = computeRanking(fixture.models, fixture.benchmarks, fixture.getValue);

    expect(ranking.map((row) => [row.model.id, row.rank, row.firsts])).toEqual([
      ["alpha", 1, 1],
      ["beta", 1, 1],
      ["gamma", 3, 0],
    ]);

    expect(
      sortModels(
        [gamma, beta, alpha],
        { benchmarkId: benchmark.id, dir: "desc" },
        fixture.benchmarks,
        fixture.benchmarks,
        fixture.getValue
      ).map((model) => model.id)
    ).toEqual(["alpha", "beta", "gamma"]);
  });

  it("labels all-missing and no-benchmark cohorts as unranked rather than assigning an ordinal", () => {
    const alpha = fixtureModel("alpha", "Alpha");
    const beta = fixtureModel("beta", "Beta");
    const benchmark = fixtureBenchmark("missing", "math");
    const fixture = createDatasetAccess({
      models: [beta, alpha],
      benchmarks: [benchmark],
      scores: [],
    });

    expect(
      computeRanking(fixture.models, fixture.benchmarks, fixture.getValue).map((row) => ({
        id: row.model.id,
        rank: row.rank,
        coverage: row.coverage,
        reason: row.unrankedReason,
      }))
    ).toEqual([
      { id: "alpha", rank: null, coverage: 0, reason: "incomplete_coverage" },
      { id: "beta", rank: null, coverage: 0, reason: "incomplete_coverage" },
    ]);
    expect(categoryLeader(fixture.models, fixture.benchmarks, fixture.getValue)).toEqual([
      { category: "math", modelId: null, avg: null, n: 0, total: 1 },
    ]);

    expect(computeRanking(fixture.models, [], fixture.getValue)).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ rank: null, total: 0, unrankedReason: "no_benchmarks" }),
      ])
    );
  });
});
