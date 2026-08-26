import { describe, expect, it } from "vitest";
import { createDatasetAccess } from "../data/dataset";
import { categoryLeader, computeRanking, modelsForComparisonClass } from "./aggregate";
import { benchmarksForComparisonClass } from "./categories";
import { buildRadarRows } from "./chartData";
import { categoriesForBenchmarks } from "../types";

function model(id: string) {
  return {
    id,
    name: id,
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

function benchmark(id: string, category: "reasoning" | "embedding") {
  return {
    id,
    name: id,
    fullName: id,
    category,
    higherIsBetter: true,
    scaleMax: 100,
    description: "Fixture only.",
    methodology: "Fixture only.",
    sourceUrl: "https://example.invalid/fixture",
  };
}

describe("comparison class isolation", () => {
  it("returns only applicable ordered chart categories for an active class", () => {
    expect(categoriesForBenchmarks([{ category: "embedding" }])).toEqual(["embedding"]);
    expect(categoriesForBenchmarks([{ category: "reasoning" }, { category: "embedding" }])).toHaveLength(10);
    expect(categoriesForBenchmarks([{ category: "reasoning" }])).toContain("reasoning");
  });

  it("uses independent benchmark and model cohorts for general and embedding ranks", () => {
    const generalOnly = model("general-only");
    const embeddingOnly = model("embedding-only");
    const dual = model("dual");
    const g1 = benchmark("general-1", "reasoning");
    const g2 = benchmark("general-2", "reasoning");
    const e1 = benchmark("embedding-1", "embedding");
    const e2 = benchmark("embedding-2", "embedding");
    const data = createDatasetAccess({
      models: [generalOnly, embeddingOnly, dual],
      benchmarks: [g1, g2, e1, e2],
      scores: [
        { modelId: generalOnly.id, benchmarkId: g1.id, value: 70, date: "2026-01-01" },
        { modelId: generalOnly.id, benchmarkId: g2.id, value: 70, date: "2026-01-01" },
        { modelId: dual.id, benchmarkId: g1.id, value: 60, date: "2026-01-01" },
        { modelId: dual.id, benchmarkId: g2.id, value: 60, date: "2026-01-01" },
        { modelId: embeddingOnly.id, benchmarkId: e1.id, value: 100, date: "2026-01-01" },
        { modelId: embeddingOnly.id, benchmarkId: e2.id, value: 100, date: "2026-01-01" },
        { modelId: dual.id, benchmarkId: e1.id, value: 50, date: "2026-01-01" },
        { modelId: dual.id, benchmarkId: e2.id, value: 50, date: "2026-01-01" },
      ],
    });
    const general = benchmarksForComparisonClass(data.benchmarks, "general");
    const embeddings = benchmarksForComparisonClass(data.benchmarks, "embedding");
    const generalModels = modelsForComparisonClass(data.models, data.benchmarks, data.getValue, "general");
    const embeddingModels = modelsForComparisonClass(data.models, data.benchmarks, data.getValue, "embedding");

    expect(general.map((item) => item.id)).toEqual(["general-1", "general-2"]);
    expect(embeddings.map((item) => item.id)).toEqual(["embedding-1", "embedding-2"]);
    expect(generalModels.map((item) => item.id)).toEqual(["general-only", "dual"]);
    expect(embeddingModels.map((item) => item.id)).toEqual(["embedding-only", "dual"]);
    expect(computeRanking(generalModels, general, data.getValue, general).map((row) => row.model.id)).toEqual([
      "general-only",
      "dual",
    ]);
    expect(computeRanking(embeddingModels, embeddings, data.getValue, embeddings).map((row) => row.model.id)).toEqual([
      "embedding-only",
      "dual",
    ]);
    expect(categoryLeader(embeddingModels, embeddings, data.getValue)).toEqual([
      { category: "embedding", modelId: "embedding-only", avg: 1, n: 2, total: 2 },
    ]);
    expect(buildRadarRows(embeddingModels, embeddings, data.getValue).map((row) => row.category)).toContain(
      "embedding"
    );
  });

  it("keeps empty and below-threshold rows out of the class model cohort", () => {
    const complete = model("complete");
    const threshold = model("threshold");
    const below = model("below");
    const empty = model("empty");
    const benches = [1, 2, 3, 4, 5].map((id) => benchmark(`g-${id}`, "reasoning"));
    const data = createDatasetAccess({
      models: [complete, threshold, below, empty],
      benchmarks: benches,
      scores: [
        ...benches.map((b) => ({ modelId: complete.id, benchmarkId: b.id, value: 50, date: "2026-01-01" })),
        ...benches.slice(0, 3).map((b) => ({ modelId: threshold.id, benchmarkId: b.id, value: 60, date: "2026-01-01" })),
        ...benches.slice(0, 2).map((b) => ({ modelId: below.id, benchmarkId: b.id, value: 100, date: "2026-01-01" })),
      ],
    });
    const cohort = modelsForComparisonClass(data.models, data.benchmarks, data.getValue, "general");
    const ranking = computeRanking(cohort, benches, data.getValue, benches);
    expect(cohort.map((item) => item.id)).toEqual(["complete", "threshold", "below"]);
    expect(ranking.find((row) => row.model.id === "threshold")).toMatchObject({
      coverage: 0.6,
      rank: 2,
    });
    expect(ranking.find((row) => row.model.id === "below")?.unrankedReason).toBe(
      "incomplete_coverage"
    );
    expect(ranking.some((row) => row.model.id === "empty")).toBe(false);
  });
});
