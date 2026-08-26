import type {
  Benchmark,
  BenchmarkCategory,
  BenchmarkNormalization,
} from "../types";

type RawOnlyReason = Extract<BenchmarkNormalization, { kind: "raw_only" }>["reason"];

export const TRACKED_DEMO_BENCHMARK_COUNT = 26;

const BENCHMARK_KEYS = new Set([
  "id",
  "name",
  "fullName",
  "category",
  "higherIsBetter",
  "scaleMax",
  "description",
  "methodology",
  "sourceUrl",
  "normalization",
]);
const NORMALIZATION_KEYS = new Set(["kind", "min", "max", "reason"]);
const CATEGORIES = new Set<BenchmarkCategory>([
  "knowledge",
  "reasoning",
  "math",
  "coding",
  "agentic",
  "instruction",
  "chat",
  "vision",
  "other",
]);
const RAW_ONLY_REASONS = new Set<RawOnlyReason>([
  "signed_metric",
  "rating_metric",
  "uncertain_domain",
]);

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function assertExactKeys(value: Record<string, unknown>, keys: Set<string>, label: string): void {
  for (const key of Object.keys(value)) {
    if (!keys.has(key)) throw new Error(`Demo benchmark ${label} contains unknown field: ${key}`);
  }
}

function requiredString(value: Record<string, unknown>, key: string): string {
  const candidate = value[key];
  if (typeof candidate !== "string" || candidate.trim().length === 0) {
    throw new Error(`Demo benchmark field ${key} must be a non-empty string.`);
  }
  return candidate;
}

function finiteNumber(value: Record<string, unknown>, key: string): number {
  const candidate = value[key];
  if (typeof candidate !== "number" || !Number.isFinite(candidate)) {
    throw new Error(`Demo benchmark field ${key} must be a finite number.`);
  }
  return candidate;
}

function parseNormalization(value: unknown): BenchmarkNormalization {
  if (!isRecord(value)) throw new Error("Demo benchmark normalization is required.");
  assertExactKeys(value, NORMALIZATION_KEYS, "normalization");
  if (value.kind === "bounded") {
    const min = finiteNumber(value, "min");
    const max = finiteNumber(value, "max");
    if (!(min < max)) throw new Error("Demo benchmark bounded normalization requires min < max.");
    if ("reason" in value) throw new Error("Bounded normalization cannot include a raw-only reason.");
    return { kind: "bounded", min, max };
  }
  if (value.kind === "raw_only") {
    if ("min" in value || "max" in value) {
      throw new Error("Raw-only normalization cannot include a numeric domain.");
    }
    if (typeof value.reason !== "string" || !RAW_ONLY_REASONS.has(value.reason as RawOnlyReason)) {
      throw new Error("Raw-only normalization requires a recognized reason.");
    }
    return { kind: "raw_only", reason: value.reason as RawOnlyReason };
  }
  throw new Error("Demo benchmark normalization kind must be bounded or raw_only.");
}

function parseBenchmark(value: unknown): Benchmark {
  if (!isRecord(value)) throw new Error("Demo benchmark entry must be an object.");
  assertExactKeys(value, BENCHMARK_KEYS, "entry");
  const category = requiredString(value, "category");
  if (!CATEGORIES.has(category as BenchmarkCategory)) {
    throw new Error(`Demo benchmark category is not canonical: ${category}`);
  }
  if (typeof value.higherIsBetter !== "boolean") {
    throw new Error("Demo benchmark higherIsBetter must be boolean.");
  }
  const benchmark: Benchmark = {
    id: requiredString(value, "id"),
    name: requiredString(value, "name"),
    fullName: requiredString(value, "fullName"),
    category: category as BenchmarkCategory,
    higherIsBetter: value.higherIsBetter,
    scaleMax: finiteNumber(value, "scaleMax"),
    description: requiredString(value, "description"),
    methodology: requiredString(value, "methodology"),
    sourceUrl: requiredString(value, "sourceUrl"),
    normalization: parseNormalization(value.normalization),
  };
  if (benchmark.scaleMax <= 0) throw new Error("Demo benchmark scaleMax must be positive.");
  return benchmark;
}

/** Parse a catalog-shaped value without accepting legacy aliases or defaults. */
export function parseDemoBenchmarks(value: unknown): Benchmark[] {
  if (!Array.isArray(value)) throw new Error("Tracked Demo benchmarks must be an array.");
  const ids = new Set<string>();
  const parsed = value.map(parseBenchmark);
  for (const benchmark of parsed) {
    if (ids.has(benchmark.id)) throw new Error(`Tracked Demo contains duplicate benchmark id: ${benchmark.id}`);
    ids.add(benchmark.id);
  }
  return parsed;
}

/** Parse the shipped catalog and enforce its tracked 26-column contract. */
export function parseTrackedDemoBenchmarks(value: unknown): Benchmark[] {
  const parsed = parseDemoBenchmarks(value);
  if (parsed.length !== TRACKED_DEMO_BENCHMARK_COUNT) {
    throw new Error(
      `Tracked Demo benchmark count must be ${TRACKED_DEMO_BENCHMARK_COUNT}; received ${parsed.length}.`
    );
  }
  return parsed;
}

/** Return a [0, 1] value only when this metric has a valid bounded domain. */
export function normalizeBenchmarkValue(benchmark: Benchmark, value: number): number | null {
  const normalization = benchmark.normalization;
  if (!normalization || normalization.kind === "raw_only" || !Number.isFinite(value)) return null;
  if (value < normalization.min || value > normalization.max) return null;
  return (value - normalization.min) / (normalization.max - normalization.min);
}
