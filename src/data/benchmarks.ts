import type { Benchmark } from "../types";
import benchmarkData from "./benchmarks.json";

/**
 * Production benchmark catalog from multiple leaderboard sources.
 */
export const benchmarks: Benchmark[] = benchmarkData as Benchmark[];
