import type { Benchmark } from "../types";
import benchmarkData from "./benchmarks.json";
import { parseTrackedDemoBenchmarks } from "./demoCatalog";

/**
 * Production benchmark catalog from multiple leaderboard sources.
 */
export const benchmarks: Benchmark[] = parseTrackedDemoBenchmarks(benchmarkData);
