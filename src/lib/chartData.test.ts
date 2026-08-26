import { describe, it, expect } from "vitest";
import { createDatasetAccess } from "@/data/dataset";
import type { Model, Benchmark, Score } from "@/types";
import {
  buildRadarRows,
  buildCategoryAverageRows,
  buildBenchmarkRows,
  buildFieldAverageByCategory,
  buildCatalogShare,
  buildModelProfileRows,
  buildBenchmarkSpreadRows,
  buildSankeyData,
  buildOverallGauge,
} from "@/lib/chartData";

const model1: Model = {
  id: "m1",
  name: "Model One",
  vendor: "VendorA",
  family: "FamA",
  releaseDate: "2026-01-01",
  contextWindowK: 128,
  paramsB: 7,
  modalities: ["text"],
  openWeights: false,
  priceInPer1M: 2,
  priceOutPer1M: 8,
};

const model2: Model = {
  id: "m2",
  name: "Model Two",
  vendor: "VendorB",
  family: "FamB",
  releaseDate: "2026-02-01",
  contextWindowK: 256,
  paramsB: 70,
  modalities: ["text", "vision"],
  openWeights: true,
  priceInPer1M: 5,
  priceOutPer1M: 15,
};

const bench1: Benchmark = {
  id: "b1",
  name: "Bench1",
  fullName: "Benchmark 1",
  category: "knowledge",
  higherIsBetter: true,
  scaleMax: 100,
  description: "Test bench 1",
  methodology: "Test",
  sourceUrl: "https://example.test/b1",
};

const bench2: Benchmark = {
  id: "b2",
  name: "Bench2",
  fullName: "Benchmark 2",
  category: "coding",
  higherIsBetter: true,
  scaleMax: 100,
  description: "Test bench 2",
  methodology: "Test",
  sourceUrl: "https://example.test/b2",
};

const bench3: Benchmark = {
  id: "b3",
  name: "Bench3",
  fullName: "Benchmark 3",
  category: "math",
  higherIsBetter: true,
  scaleMax: 10,
  description: "Test bench 3",
  methodology: "Test",
  sourceUrl: "https://example.test/b3",
};

const scores: Score[] = [
  { modelId: "m1", benchmarkId: "b1", value: 88.5, date: "2026-01-01" },
  { modelId: "m2", benchmarkId: "b1", value: 95, date: "2026-01-01" },
  { modelId: "m1", benchmarkId: "b2", value: 70, date: "2026-01-01" },
  // m2 has no score for b2 (missing)
  { modelId: "m1", benchmarkId: "b3", value: 9, date: "2026-01-01" },
  { modelId: "m2", benchmarkId: "b3", value: 8.5, date: "2026-01-01" },
];

function makeDataset() {
  return createDatasetAccess({
    models: [model1, model2],
    benchmarks: [bench1, bench2, bench3],
    scores,
  });
}

describe("chartData builders", () => {
  it("null scores → key absent (not 0/null) in radar rows", () => {
    const ds = makeDataset();
    const rows = buildRadarRows([model1, model2], [bench1, bench2, bench3], ds.getValue);

    // 9 categories (CATEGORIES array)
    expect(rows.length).toBe(9);

    // Model 2 has no score for b2 (coding). The coding row should have s0 but NOT s1.
    const codingRow = rows.find((r) => r.category === "coding");
    expect(codingRow).toBeDefined();
    expect((codingRow as Record<string, unknown>)["s0"]).toBe(70);
    expect((codingRow as Record<string, unknown>)["s1"]).toBeUndefined();

    // Knowledge row should have both models
    const knowledgeRow = rows.find((r) => r.category === "knowledge");
    expect(knowledgeRow).toBeDefined();
    expect((knowledgeRow as Record<string, unknown>)["s0"]).toBe(88.5);
    expect((knowledgeRow as Record<string, unknown>)["s1"]).toBe(95);
  });

  it("null scores → key absent in buildCategoryAverageRows (same math)", () => {
    const ds = makeDataset();
    const rows = buildCategoryAverageRows([model1, model2], [bench1, bench2, bench3], ds.getValue);
    const codingRow = rows.find((r) => r.category === "coding");
    expect((codingRow as Record<string, unknown>)["s1"]).toBeUndefined();
  });

  it("all-null benchmark omitted from buildBenchmarkRows", () => {
    const ds = makeDataset();
    // bench2 only has m1, so it's not all-null
    const rows = buildBenchmarkRows([model1, model2], [bench1, bench2, bench3], ds.getValue);
    const ids = rows.map((r) => r.benchmarkId);
    expect(ids).toContain("b1");
    expect(ids).toContain("b2"); // has m1
    expect(ids).toContain("b3");
  });

  it("all-null benchmark omitted when no model has a score", () => {
    const emptyBench: Benchmark = {
      id: "b-empty",
      name: "EmptyBench",
      fullName: "Empty Benchmark",
      category: "agentic",
      higherIsBetter: true,
      scaleMax: 100,
      description: "No scores",
      methodology: "Test",
      sourceUrl: "https://example.test/empty",
    };
    const ds = createDatasetAccess({
      models: [model1, model2],
      benchmarks: [bench1, emptyBench],
      scores: [{ modelId: "m1", benchmarkId: "b1", value: 50, date: "2026-01-01" }],
    });
    const rows = buildBenchmarkRows([model1, model2], [bench1, emptyBench], ds.getValue);
    expect(rows.map((r) => r.benchmarkId)).toEqual(["b1"]);
  });

  it("empty models array → empty rows, no throw", () => {
    const ds = makeDataset();
    expect(() => buildRadarRows([], [bench1], ds.getValue)).not.toThrow();
    expect(() => buildBenchmarkRows([], [bench1], ds.getValue)).not.toThrow();
    expect(() => buildOverallGauge("m1", [], ds.getValue)).not.toThrow();

    expect(buildRadarRows([], [bench1], ds.getValue)).toHaveLength(9);
    expect(buildBenchmarkRows([], [bench1], ds.getValue)).toHaveLength(0);
    const gauge = buildOverallGauge("m1", [], ds.getValue);
    expect(gauge.pct).toBeNull();
    expect(gauge.coveragePct).toBe(0);
  });

  it("sankey node names unique, link indices valid, values >= 1", () => {
    const ds = makeDataset();
    const sankey = buildSankeyData([model1, model2], [bench1, bench2, bench3], ds.getValue);

    const names = sankey.nodes.map((n) => n.name);
    expect(new Set(names).size).toBe(names.length); // unique

    for (const link of sankey.links) {
      expect(link.source).toBeGreaterThanOrEqual(0);
      expect(link.source).toBeLessThan(sankey.nodes.length);
      expect(link.target).toBeGreaterThanOrEqual(0);
      expect(link.target).toBeLessThan(sankey.nodes.length);
      expect(link.value).toBeGreaterThanOrEqual(1);
    }

    // Should have category nodes first
    const catNames = ["Knowledge", "Coding", "Math"];
    catNames.forEach((cn) => {
      expect(names).toContain(cn);
    });
  });

  it("spread rows sorted desc with sequential ranks", () => {
    const ds = makeDataset();
    const rows = buildBenchmarkSpreadRows(bench1, [model1, model2], ds.getValue);
    expect(rows).toHaveLength(2);
    expect(rows[0].rank).toBe(1);
    expect(rows[1].rank).toBe(2);
    expect(rows[0].pct).toBeGreaterThanOrEqual(rows[1].pct);
    // m2 scored 95, m1 scored 88.5
    expect(rows[0].modelName).toBe("Model Two");
    expect(rows[1].modelName).toBe("Model One");
  });

  it("spread rows omit null scores", () => {
    const ds = makeDataset();
    const rows = buildBenchmarkSpreadRows(bench2, [model1, model2], ds.getValue);
    expect(rows).toHaveLength(1);
    expect(rows[0].modelName).toBe("Model One");
  });

  it("catalog share sums to total benchmark count", () => {
    const rows = buildCatalogShare([bench1, bench2, bench3]);
    const total = rows.reduce((sum, r) => sum + r.count, 0);
    expect(total).toBe(3);
    // knowledge=1, coding=1, math=1
    expect(rows.find((r) => r.category === "knowledge")?.count).toBe(1);
    expect(rows.find((r) => r.category === "coding")?.count).toBe(1);
    expect(rows.find((r) => r.category === "math")?.count).toBe(1);
  });

  it("field average by category uses all models", () => {
    const ds = makeDataset();
    const rows = buildFieldAverageByCategory([model1, model2], [bench1, bench2, bench3], ds.getValue);
    // Knowledge: avg of (88.5, 95) = 91.75 → 91.8
    const knowledge = rows.find((r) => r.category === "knowledge");
    expect(knowledge?.fieldPct).toBe(91.8);
  });

  it("model profile rows include fieldAvgPct and modelPct when present", () => {
    const ds = makeDataset();
    const rows = buildModelProfileRows("m1", [model1, model2], [bench1, bench2, bench3], ds.getValue);
    expect(rows).toHaveLength(3);
    const b1Row = rows.find((r) => r.benchmark === "Bench1");
    expect(b1Row?.modelPct).toBe(88.5);
    expect(b1Row?.fieldAvgPct).toBe(91.8); // avg(88.5, 95)
  });

  it("overall gauge computes pct and coveragePct", () => {
    const ds = makeDataset();
    const gauge = buildOverallGauge("m1", [bench1, bench2, bench3], ds.getValue);
    // m1 has scores for all 3 benchmarks
    expect(gauge.coveragePct).toBe(100);
    // pct = avg(88.5, 70, 90) = 82.8...
    // bench3 scaleMax=10, value=9 → 90%
    expect(gauge.pct).toBe(Math.round((88.5 + 70 + 90) / 3 * 10) / 10);
  });

  it("uses a nonzero bounded minimum and lower-is-better direction for chart percentages", () => {
    const lower: Benchmark = {
      ...bench1,
      id: "latency",
      name: "Latency",
      higherIsBetter: false,
      normalization: { kind: "bounded", min: 10, max: 20 },
    };
    const ds = createDatasetAccess({
      models: [model1, model2],
      benchmarks: [lower],
      scores: [
        { modelId: model1.id, benchmarkId: lower.id, value: 12, date: "2026-01-01" },
        { modelId: model2.id, benchmarkId: lower.id, value: 18, date: "2026-01-01" },
      ],
    });

    expect(buildBenchmarkRows([model1, model2], [lower], ds.getValue)).toEqual([
      { benchmarkId: "latency", name: "Latency", category: "knowledge", s0: 80, s1: 20 },
    ]);
    expect(buildBenchmarkSpreadRows(lower, [model1, model2], ds.getValue)).toEqual([
      { rank: 1, modelName: "Model One", pct: 80 },
      { rank: 2, modelName: "Model Two", pct: 20 },
    ]);
    expect(buildOverallGauge(model1.id, [lower], ds.getValue)).toMatchObject({
      pct: 80,
      coveragePct: 100,
    });
  });

  it("omits raw-only and out-of-domain chart points while retaining raw table values", () => {
    const rawOnly: Benchmark = {
      ...bench1,
      id: "rating",
      name: "Rating",
      normalization: { kind: "raw_only", reason: "rating_metric" },
    };
    const bounded: Benchmark = {
      ...bench1,
      id: "bounded",
      name: "Bounded",
      normalization: { kind: "bounded", min: 10, max: 20 },
    };
    const ds = createDatasetAccess({
      models: [model1],
      benchmarks: [rawOnly, bounded],
      scores: [
        { modelId: model1.id, benchmarkId: rawOnly.id, value: 900, date: "2026-01-01" },
        { modelId: model1.id, benchmarkId: bounded.id, value: 25, date: "2026-01-01" },
      ],
    });

    expect(ds.getValue(model1.id, rawOnly.id)).toBe(900);
    expect(buildBenchmarkRows([model1], [rawOnly, bounded], ds.getValue)).toEqual([]);
    expect(buildBenchmarkSpreadRows(rawOnly, [model1], ds.getValue)).toEqual([]);
    expect(buildOverallGauge(model1.id, [rawOnly, bounded], ds.getValue)).toEqual({
      pct: null,
      coveragePct: 0,
    });
    expect(buildFieldAverageByCategory([model1], [rawOnly, bounded], ds.getValue).find(
      (row) => row.category === "knowledge"
    )).toEqual({ category: "knowledge", fieldPct: null });
  });

  it("uses null for empty category, field, profile, and overall aggregates", () => {
    const empty: Benchmark = {
      ...bench1,
      id: "empty",
      name: "Empty",
      normalization: { kind: "raw_only", reason: "uncertain_domain" },
    };
    const ds = createDatasetAccess({ models: [model1], benchmarks: [empty], scores: [] });

    expect(buildRadarRows([model1], [empty], ds.getValue).find((row) => row.category === "knowledge")).toEqual({
      category: "knowledge",
    });
    expect(buildModelProfileRows(model1.id, [model1], [empty], ds.getValue)).toEqual([]);
    expect(buildOverallGauge(model1.id, [empty], ds.getValue)).toEqual({ pct: null, coveragePct: 0 });
  });
});
