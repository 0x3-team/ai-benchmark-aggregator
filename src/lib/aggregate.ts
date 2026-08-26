import type { BenchmarkCategory } from "../types";
import type {
  DatasetBenchmark,
  DatasetModel,
  GetValue,
} from "../data/dataset";
import { normalizeBenchmarkValue } from "../data/demoCatalog";
import { CATEGORIES } from "../types";

export interface RankRow {
  model: DatasetModel;
  /** Competition rank, or null when the model lacks a score for the cohort. */
  rank: number | null;
  /** Average of per-benchmark competition ranks; never shown as a score. */
  avgRank: number | null;
  firsts: number;
  coverage: number;
  covered: number;
  total: number;
  unrankedReason: "incomplete_coverage" | "no_benchmarks" | null;
}

function compareModels(a: DatasetModel, b: DatasetModel): number {
  return a.name.localeCompare(b.name) || a.id.localeCompare(b.id);
}

function compareRankNumbers(a: number, b: number): number {
  const difference = a - b;
  return Math.abs(difference) < Number.EPSILON ? 0 : difference;
}

/**
 * Convert one raw score to a comparable 0..1 presentation value.
 *
 * Tracked Demo benchmarks carry an explicit bounded domain (or are raw-only),
 * so those values are always delegated to the catalog normalizer. The legacy
 * test/fixture shape has no normalization metadata; its historical 0..scaleMax
 * contract remains a compatibility fallback until those callers migrate.
 */
export function normalizeForPresentation(
  benchmark: DatasetBenchmark,
  value: number
): number | null {
  const normalized = normalizeBenchmarkValue(benchmark, value);
  if (normalized != null) {
    return benchmark.higherIsBetter ? normalized : 1 - normalized;
  }
  if (benchmark.normalization) return null;
  if (!Number.isFinite(value) || benchmark.scaleMax <= 0 || value < 0 || value > benchmark.scaleMax) {
    return null;
  }
  const fallback = value / benchmark.scaleMax;
  return benchmark.higherIsBetter ? fallback : 1 - fallback;
}

/** Raw-only catalog metrics are not eligible for normalized aggregates. */
export function isNormalizableBenchmark(benchmark: DatasetBenchmark): boolean {
  return benchmark.normalization?.kind !== "raw_only";
}

// Rank a list of models for a single benchmark (best first; missing last).
export function rankForBenchmark(
  models: readonly DatasetModel[],
  benchmark: DatasetBenchmark,
  getValue: GetValue
): { model: DatasetModel; value: number | null; rank: number | null }[] {
  const present = models
    .map((m) => ({ model: m, value: getValue(m.id, benchmark.id) }))
    .filter((r) => r.value != null) as { model: DatasetModel; value: number }[];

  present.sort((a, b) => {
    const valueOrder = benchmark.higherIsBetter
      ? b.value - a.value
      : a.value - b.value;
    return valueOrder || compareModels(a.model, b.model);
  });
  const rankById = new Map<string, number>();
  let previousValue: number | null = null;
  let competitionRank = 0;
  present.forEach((r, i) => {
    if (previousValue === null || r.value !== previousValue) {
      competitionRank = i + 1;
      previousValue = r.value;
    }
    rankById.set(r.model.id, competitionRank);
  });

  return models.map((m) => ({
    model: m,
    value: getValue(m.id, benchmark.id),
    rank: rankById.get(m.id) ?? null,
  }));
}

// Presentation ranks are calculated over one fixed cohort. A model must have a
// score for every cohort benchmark to receive an ordinal rank; filters only
// change which rows are visible, not which scores count. Per-benchmark ties
// use competition ranks (1, 1, 3) and otherwise sort by name/id for stable UI
// order. This is presentation data only, never a ledger claim.
export function computeRanking(
  models: readonly DatasetModel[],
  visible: readonly DatasetBenchmark[],
  getValue: GetValue
): RankRow[] {
  const n = visible.length;

  if (n === 0) {
    return [...models]
      .sort(compareModels)
      .map((model) => ({
        model,
        rank: null,
        avgRank: null,
        firsts: 0,
        coverage: 0,
        covered: 0,
        total: 0,
        unrankedReason: "no_benchmarks" as const,
      }));
  }

  // Precompute: Map<benchmarkId, Map<modelId, rank>>
  const rankCache = new Map<string, Map<string, number>>();
  for (const bench of visible) {
    const ranked = rankForBenchmark(models, bench, getValue);
    const benchRanks = new Map<string, number>();
    for (const r of ranked) {
      if (r.rank != null) benchRanks.set(r.model.id, r.rank);
    }
    rankCache.set(bench.id, benchRanks);
  }

  const rows: RankRow[] = models.map((model) => {
    let sum = 0;
    let count = 0;
    let firsts = 0;
    for (const bench of visible) {
      const rank = rankCache.get(bench.id)?.get(model.id);
      if (rank != null) {
        sum += rank;
        count += 1;
        if (rank === 1) firsts += 1;
      }
    }
    return {
      model,
      rank: null,
      avgRank: count > 0 ? sum / count : null,
      firsts,
      coverage: n > 0 ? count / n : 0,
      covered: count,
      total: n,
      unrankedReason: count === n ? null : "incomplete_coverage",
    };
  });

  const ranked = rows
    .filter((row) => row.unrankedReason === null)
    .sort((a, b) => {
      const averageOrder = compareRankNumbers(a.avgRank!, b.avgRank!);
      if (averageOrder !== 0) return averageOrder;
      const firstOrder = b.firsts - a.firsts;
      return firstOrder || compareModels(a.model, b.model);
    });

  let previous: RankRow | null = null;
  ranked.forEach((row, index) => {
    const sameRank =
      previous !== null &&
      compareRankNumbers(row.avgRank!, previous.avgRank!) === 0 &&
      row.firsts === previous.firsts;
    row.rank = sameRank ? previous!.rank : index + 1;
    previous = row;
  });

  const unranked = rows
    .filter((row) => row.unrankedReason !== null)
    .sort((a, b) => {
      const coverageOrder = b.covered - a.covered;
      return coverageOrder || compareModels(a.model, b.model);
    });

  return [...ranked, ...unranked];
}

export interface RadarPoint {
  category: BenchmarkCategory;
  value: number | null; // 0..1, normalized by scaleMax
}

// Average normalized score per category for one model (one radar axis each).
export function radarAverages(
  modelId: string,
  benchmarks: readonly DatasetBenchmark[],
  getValue: GetValue
): RadarPoint[] {
  const byCat = new Map<BenchmarkCategory, number[]>();
  for (const bench of benchmarks) {
    const v = getValue(modelId, bench.id);
    if (v == null) continue;
    const norm = normalizeForPresentation(bench, v);
    if (norm == null) continue;
    const arr = byCat.get(bench.category) ?? [];
    arr.push(norm);
    byCat.set(bench.category, arr);
  }
  return (Object.keys(CATEGORY_ORDER) as BenchmarkCategory[]).map((category) => {
    const arr = byCat.get(category);
    if (!arr || arr.length === 0) return { category, value: null };
    return { category, value: arr.reduce((s, x) => s + x, 0) / arr.length };
  });
}

const CATEGORY_ORDER: Record<BenchmarkCategory, number> = {
  knowledge: 0,
  reasoning: 1,
  math: 2,
  coding: 3,
  agentic: 4,
  instruction: 5,
  chat: 6,
  vision: 7,
  other: 8,
};

export function sortModels(
  models: readonly DatasetModel[],
  sort: { benchmarkId: string | null; dir: "asc" | "desc" } | null,
  visible: readonly DatasetBenchmark[],
  benchmarks: readonly DatasetBenchmark[],
  getValue: GetValue,
  presentationRanking?: readonly RankRow[]
): DatasetModel[] {
  const list = [...models];
  if (!sort || !sort.benchmarkId) {
    const ranking = presentationRanking ?? computeRanking(models, visible, getValue);
    const rankById = new Map(ranking.map((row) => [row.model.id, row]));
    list.sort((a, b) => {
      const aRow = rankById.get(a.id);
      const bRow = rankById.get(b.id);
      if (!aRow || !bRow) return compareModels(a, b);
      if (aRow.rank !== null && bRow.rank !== null) {
        const rankOrder = aRow.rank - bRow.rank;
        if (rankOrder !== 0) return rankOrder;
      } else if (aRow.rank !== null) {
        return -1;
      } else if (bRow.rank !== null) {
        return 1;
      }
      const coverageOrder = bRow.covered - aRow.covered;
      return coverageOrder || compareModels(a, b);
    });
    return list;
  }
  const bench = benchmarks.find((b) => b.id === sort.benchmarkId);
  if (!bench) return list;
  list.sort((a, b) => {
    const av = getValue(a.id, bench.id);
    const bv = getValue(b.id, bench.id);
    if (av == null && bv == null) return compareModels(a, b);
    if (av == null) return 1;
    if (bv == null) return -1;
    const cmp = av - bv;
    return (sort.dir === "asc" ? cmp : -cmp) || compareModels(a, b);
  });
  return list;
}

export interface CategoryAvg {
  modelId: string;
  avg: number; // normalized 0..1 (value / scaleMax, averaged)
  n: number; // number of benchmarks counted; equal to total for eligible rows
  total: number;
}

// Normalized (value / scaleMax) averaged per category over *visible* benchmarks.
export function categoryAverages(
  models: readonly DatasetModel[],
  visible: readonly DatasetBenchmark[],
  getValue: GetValue
): Record<BenchmarkCategory, CategoryAvg[]> {
  const result = {} as Record<BenchmarkCategory, CategoryAvg[]>;
  for (const cat of CATEGORIES) result[cat] = [];

  for (const cat of CATEGORIES) {
    const catBenches = visible.filter(
      (b) => b.category === cat && isNormalizableBenchmark(b)
    );
    if (catBenches.length === 0) continue;
    for (const m of models) {
      let sum = 0;
      let n = 0;
      for (const b of catBenches) {
        const v = getValue(m.id, b.id);
        if (v == null) continue;
        const normalized = normalizeForPresentation(b, v);
        if (normalized == null) continue;
        sum += normalized;
        n += 1;
      }
      if (n !== catBenches.length) continue;
      result[cat].push({ modelId: m.id, avg: sum / n, n, total: catBenches.length });
    }
    result[cat].sort((a, b) => {
      const averageOrder = b.avg - a.avg;
      if (averageOrder !== 0) return averageOrder;
      return a.modelId.localeCompare(b.modelId);
    });
  }
  return result;
}

export interface CategoryLeaderRow {
  category: BenchmarkCategory;
  modelId: string | null;
  avg: number | null;
  n: number;
  total: number;
}

// Top fully-covered model per category from `categoryAverages`. Categories
// with no fully-covered model retain a display row so callers can say why a
// leader is absent instead of silently selecting a partial average.
export function categoryLeader(
  models: readonly DatasetModel[],
  visible: readonly DatasetBenchmark[],
  getValue: GetValue
): CategoryLeaderRow[] {
  const avgs = categoryAverages(models, visible, getValue);
  return (Object.keys(avgs) as BenchmarkCategory[])
    .map((cat) => {
      const top = avgs[cat][0];
      const total = visible.filter(
        (benchmark) => benchmark.category === cat && isNormalizableBenchmark(benchmark)
      ).length;
      if (!top) return { category: cat, modelId: null, avg: null, n: 0, total };
      return {
        category: cat,
        modelId: top.modelId,
        avg: top.avg,
        n: top.n,
        total: top.total,
      };
    })
    .filter((row) => row.total > 0);
}

// The model that holds `stats.best` for a benchmark (first on ties).
export function bestModelId(
  benchmarkId: string,
  models: readonly DatasetModel[],
  benchmarks: readonly DatasetBenchmark[],
  getValue: GetValue
): string | null {
  const bench = benchmarks.find((b) => b.id === benchmarkId);
  if (!bench) return null;
  const ranked = rankForBenchmark(models, bench, getValue);
  const top = ranked.find((r) => r.rank === 1);
  return top?.model.id ?? null;
}
