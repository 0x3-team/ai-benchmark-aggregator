import type { Benchmark, BenchmarkCategory, Model } from "../types";
import { benchmarks } from "../data/benchmarks";
import { getValue } from "../data/scores";
import { CATEGORIES } from "../types";

export interface RankRow {
  model: Model;
  avgRank: number;
  firsts: number;
  coverage: number; // fraction of visible benchmarks with a value
}

// Rank a list of models for a single benchmark (best first; missing last).
export function rankForBenchmark(
  models: Model[],
  benchmark: Benchmark
): { model: Model; value: number | null; rank: number | null }[] {
  const present = models
    .map((m) => ({ model: m, value: getValue(m.id, benchmark.id) }))
    .filter((r) => r.value != null) as { model: Model; value: number }[];

  present.sort((a, b) =>
    benchmark.higherIsBetter ? b.value - a.value : a.value - b.value
  );
  const rankById = new Map<string, number>();
  present.forEach((r, i) => rankById.set(r.model.id, i + 1));

  return models.map((m) => ({
    model: m,
    value: getValue(m.id, benchmark.id),
    rank: rankById.get(m.id) ?? null,
  }));
}

// Average rank across several benchmarks; missing scores are excluded from the
// average rather than penalized. Precomputes per-benchmark ranks in a single
// pass (O(models × benchmarks)) instead of re-ranking per model per benchmark.
export function computeRanking(models: Model[], visible: Benchmark[]): RankRow[] {
  const n = visible.length;

  // Precompute: Map<benchmarkId, Map<modelId, rank>>
  const rankCache = new Map<string, Map<string, number>>();
  for (const bench of visible) {
    const ranked = rankForBenchmark(models, bench);
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
      avgRank: count > 0 ? sum / count : n + 1,
      firsts,
      coverage: n > 0 ? count / n : 0,
    };
  });

  rows.sort((a, b) => a.avgRank - b.avgRank);
  return rows;
}

export interface RadarPoint {
  category: BenchmarkCategory;
  value: number | null; // 0..1, normalized by scaleMax
}

// Average normalized score per category for one model (one radar axis each).
export function radarAverages(modelId: string): RadarPoint[] {
  const byCat = new Map<BenchmarkCategory, number[]>();
  for (const bench of benchmarks) {
    const v = getValue(modelId, bench.id);
    if (v == null) continue;
    const norm = bench.scaleMax > 0 ? v / bench.scaleMax : 0;
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
};

export function sortModels(
  models: Model[],
  sort: { benchmarkId: string | null; dir: "asc" | "desc" } | null,
  visible: Benchmark[]
): Model[] {
  const list = [...models];
  if (!sort || !sort.benchmarkId) {
    const ranking = computeRanking(models, visible);
    const rankById = new Map(ranking.map((r, i) => [r.model.id, i]));
    list.sort((a, b) => (rankById.get(a.id)! - rankById.get(b.id)!));
    return list;
  }
  const bench = benchmarks.find((b) => b.id === sort.benchmarkId)!;
  list.sort((a, b) => {
    const av = getValue(a.id, bench.id);
    const bv = getValue(b.id, bench.id);
    if (av == null && bv == null) return 0;
    if (av == null) return 1;
    if (bv == null) return -1;
    const cmp = av - bv;
    return sort.dir === "asc" ? cmp : -cmp;
  });
  return list;
}

export interface CategoryAvg {
  modelId: string;
  avg: number; // normalized 0..1 (value / scaleMax, averaged)
  n: number; // number of benchmarks counted
}

// Normalized (value / scaleMax) averaged per category over *visible* benchmarks.
export function categoryAverages(
  models: Model[],
  visible: Benchmark[]
): Record<BenchmarkCategory, CategoryAvg[]> {
  const result = {} as Record<BenchmarkCategory, CategoryAvg[]>;
  for (const cat of CATEGORIES) result[cat] = [];

  for (const cat of CATEGORIES) {
    const catBenches = visible.filter((b) => b.category === cat);
    if (catBenches.length === 0) continue;
    for (const m of models) {
      let sum = 0;
      let n = 0;
      for (const b of catBenches) {
        const v = getValue(m.id, b.id);
        if (v == null) continue;
        sum += b.scaleMax > 0 ? v / b.scaleMax : 0;
        n += 1;
      }
      if (n === 0) continue;
      result[cat].push({ modelId: m.id, avg: sum / n, n });
    }
    result[cat].sort((a, b) => b.avg - a.avg);
  }
  return result;
}

export interface CategoryLeaderRow {
  category: BenchmarkCategory;
  modelId: string;
  avg: number;
  n: number;
}

// Top model per category from `categoryAverages`. When `visible` is filtered to
// a single category, only that category is returned.
export function categoryLeader(
  models: Model[],
  visible: Benchmark[]
): CategoryLeaderRow[] {
  const avgs = categoryAverages(models, visible);
  return (Object.keys(avgs) as BenchmarkCategory[])
    .filter((cat) => avgs[cat].length > 0)
    .map((cat) => {
      const top = avgs[cat][0];
      return { category: cat, modelId: top.modelId, avg: top.avg, n: top.n };
    });
}

// The model that holds `stats.best` for a benchmark (first on ties).
export function bestModelId(benchmarkId: string, models: Model[]): string | null {
  const bench = benchmarks.find((b) => b.id === benchmarkId);
  if (!bench) return null;
  const ranked = rankForBenchmark(models, bench);
  const top = ranked.find((r) => r.rank === 1);
  return top?.model.id ?? null;
}
