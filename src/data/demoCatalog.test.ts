import { describe, expect, it } from "vitest";
import benchmarkData from "./benchmarks.json";
import { getScores } from "./scores";
import {
  normalizeBenchmarkValue,
  parseDemoBenchmarks,
  parseTrackedDemoBenchmarks,
  TRACKED_DEMO_BENCHMARK_COUNT,
} from "./demoCatalog";
import { benchmarks } from "./benchmarks";

describe("tracked Demo benchmark catalog", () => {
  it("ships exactly 26 canonical benchmark columns with complete metadata", () => {
    expect(benchmarks).toHaveLength(TRACKED_DEMO_BENCHMARK_COUNT);
    expect(new Set(benchmarks.map((benchmark) => benchmark.id)).size).toBe(26);
    for (const benchmark of benchmarks) {
      expect(benchmark.fullName.length).toBeGreaterThan(0);
      expect(benchmark.methodology.length).toBeGreaterThan(0);
      expect(benchmark.sourceUrl.length).toBeGreaterThan(0);
      expect(benchmark.normalization).toBeDefined();
    }
  });

  it("repairs BenchLM without creating an Official claim", () => {
    const benchlm = benchmarks.find((benchmark) => benchmark.id === "benchlm-overall");
    expect(benchlm).toMatchObject({
      name: "BenchLM Overall",
      fullName: "BenchLM Overall",
      category: "knowledge",
      sourceUrl: "https://benchlm.ai",
      normalization: { kind: "bounded", min: 0, max: 100 },
    });
    expect(benchlm?.methodology).toContain("not Official claims");
    expect(getScores().some((score) => score.benchmarkId === "benchlm-overall")).toBe(true);
    expect(getScores().find((score) => score.benchmarkId === "benchlm-overall")?.scoreRaw).toBeUndefined();
  });

  it("keeps signed and rating metrics raw-only", () => {
    expect(benchmarks.find((benchmark) => benchmark.id === "omniscience")?.normalization).toEqual({
      kind: "raw_only",
      reason: "signed_metric",
    });
    for (const id of [
      "lmsys_chatbot_arena_text_coding_elo",
      "lmsys_chatbot_arena_text_elo",
      "lmsys_chatbot_arena_text_hard_6_elo",
      "lmsys_chatbot_arena_text_math_elo",
      "lmsys_chatbot_arena_text_rank",
      "lmsys_chatbot_arena_vision_elo",
      "lmsys_mmlu",
    ]) {
      expect(benchmarks.find((benchmark) => benchmark.id === id)?.normalization).toMatchObject({
        kind: "raw_only",
        reason: "rating_metric",
      });
    }
  });

  it("only normalizes finite in-domain bounded values", () => {
    for (const benchmark of benchmarks) {
      const domain = benchmark.normalization;
      if (!domain || domain.kind === "raw_only") {
        expect(normalizeBenchmarkValue(benchmark, 0)).toBeNull();
        continue;
      }
      expect(normalizeBenchmarkValue(benchmark, domain.min)).toBe(0);
      expect(normalizeBenchmarkValue(benchmark, domain.max)).toBe(1);
      expect(normalizeBenchmarkValue(benchmark, domain.max + 1)).toBeNull();
      expect(normalizeBenchmarkValue(benchmark, Number.NaN)).toBeNull();
    }
  });

  it("fails closed for legacy aliases, missing methodology, and duplicates", () => {
    const valid = benchmarkData[0];
    expect(() => parseDemoBenchmarks([{ ...valid, url: valid.sourceUrl }])).toThrow(/unknown field/);
    expect(() => parseDemoBenchmarks([{ ...valid, methodology: undefined }])).toThrow(/methodology/);
    expect(() => parseDemoBenchmarks([valid, valid])).toThrow(/duplicate benchmark id/);
    expect(() => parseTrackedDemoBenchmarks(benchmarkData.slice(0, -1))).toThrow(/count must be 26/);
  });
});
