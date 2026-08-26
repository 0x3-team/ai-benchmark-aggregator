import { describe, expect, it } from "vitest";
import type { Benchmark } from "../types";
import { normalizeBenchmarkValue } from "./benchmarkNormalization";

const boundedFixture: Benchmark = {
  id: "fictional-bounded-benchmark",
  name: "Fictional Bounded Benchmark",
  fullName: "Fictional Bounded Benchmark",
  category: "reasoning",
  higherIsBetter: true,
  scaleMax: 50,
  description: "Small fictional test fixture.",
  methodology: "Test-only bounded-domain fixture.",
  sourceUrl: "https://example.test/fictional-bounded-benchmark",
  normalization: { kind: "bounded", min: -10, max: 40 },
};

describe("normalizeBenchmarkValue", () => {
  it("normalizes finite values within an explicitly bounded domain", () => {
    expect(normalizeBenchmarkValue(boundedFixture, -10)).toBe(0);
    expect(normalizeBenchmarkValue(boundedFixture, 15)).toBe(0.5);
    expect(normalizeBenchmarkValue(boundedFixture, 40)).toBe(1);
  });

  it("rejects out-of-domain, non-finite, raw-only, and unspecified values", () => {
    expect(normalizeBenchmarkValue(boundedFixture, -11)).toBeNull();
    expect(normalizeBenchmarkValue(boundedFixture, 41)).toBeNull();
    expect(normalizeBenchmarkValue(boundedFixture, Number.NaN)).toBeNull();
    expect(
      normalizeBenchmarkValue(
        {
          ...boundedFixture,
          id: "fictional-raw-only-benchmark",
          normalization: { kind: "raw_only", reason: "uncertain_domain" },
        },
        15
      )
    ).toBeNull();
    expect(
      normalizeBenchmarkValue(
        { ...boundedFixture, id: "fictional-unspecified-benchmark", normalization: undefined },
        15
      )
    ).toBeNull();
  });
});
