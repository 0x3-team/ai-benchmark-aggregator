import { describe, expect, it } from "vitest";
import { columnStats, heatmapColor } from "./color";
import type { Benchmark } from "../types";

const higher: Benchmark = {
  id: "h",
  name: "H",
  fullName: "Higher",
  category: "math",
  higherIsBetter: true,
  scaleMax: 100,
  description: "",
  methodology: "",
  sourceUrl: "",
};

const lower: Benchmark = { ...higher, id: "l", higherIsBetter: false };

describe("columnStats higherIsBetter", () => {
  it("picks max as best when higher is better", () => {
    const s = columnStats([1, 5, 3, null], higher);
    expect(s.best).toBe(5);
    expect(s.worst).toBe(1);
  });

  it("picks min as best when lower is better", () => {
    const s = columnStats([10, 2, 7, null], lower);
    expect(s.best).toBe(2);
    expect(s.worst).toBe(10);
  });
});

describe("heatmapColor lowerIsBetter", () => {
  it("colors lower values greener when lower is better", () => {
    const stats = columnStats([1, 10], lower);
    const low = heatmapColor(1, stats, lower);
    const high = heatmapColor(10, stats, lower);
    // greener => higher green channel in rgba string
    const gLow = Number(low.match(/rgba\((\d+),\s*(\d+)/)?.[2]);
    const gHigh = Number(high.match(/rgba\((\d+),\s*(\d+)/)?.[2]);
    expect(gLow).toBeGreaterThan(gHigh);
  });
});

describe("no-data column statistics", () => {
  it("keeps an empty column absent instead of inventing zero-valued extrema", () => {
    const stats = columnStats([null, null], higher);
    expect(stats).toEqual({
      min: null,
      max: null,
      best: null,
      worst: null,
      avg: null,
      count: 0,
    });
    expect(heatmapColor(null, stats, higher)).toBe("transparent");
  });
});
