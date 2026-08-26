import type { Benchmark } from "../types";

/** Return a [0, 1] value only when a benchmark declares a valid bounded domain. */
export function normalizeBenchmarkValue(
  benchmark: Benchmark,
  value: number
): number | null {
  const normalization = benchmark.normalization;
  if (!normalization || normalization.kind === "raw_only" || !Number.isFinite(value)) {
    return null;
  }
  if (value < normalization.min || value > normalization.max) return null;
  return (value - normalization.min) / (normalization.max - normalization.min);
}
