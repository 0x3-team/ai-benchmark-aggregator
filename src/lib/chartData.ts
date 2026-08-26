import { CATEGORY_LABELS, categoriesForBenchmarks } from "@/types";
import {
  isNormalizableBenchmark,
  normalizeForPresentation,
  radarAverages,
} from "@/lib/aggregate";
import type {
  DatasetModel,
  DatasetBenchmark,
  GetValue,
} from "@/data/dataset";

export type SeriesKey = `s${number}`;

export type CategoryRow = { category: string } & Partial<Record<SeriesKey, number>>;

export type BenchmarkRow = {
  benchmarkId: string;
  name: string;
  category: string;
} & Partial<Record<SeriesKey, number>>;

export type CatalogShareRow = { category: string; count: number };

export type OverallGauge = { pct: number | null; coveragePct: number };

export type ModelProfileRow = {
  benchmark: string;
  modelPct?: number;
  fieldAvgPct: number | null;
};

export type BenchmarkSpreadRow = { rank: number; modelName: string; pct: number };

export type SankeyChartData = {
  nodes: { name: string }[];
  links: { source: number; target: number; value: number }[];
};

const round1 = (v: number): number => Math.round(v * 10) / 10;

function normalizePct(
  benchmark: DatasetBenchmark,
  value: number
): number | null {
  const normalized = normalizeForPresentation(benchmark, value);
  return normalized == null ? null : round1(normalized * 100);
}

function averageNormalizedPct(
  values: readonly (number | null)[],
  benchmark: DatasetBenchmark
): number | null {
  const normalized = values
    .map((value) => (value == null ? null : normalizePct(benchmark, value)))
    .filter((value): value is number => value != null);
  return normalized.length === 0
    ? null
    : round1(normalized.reduce((sum, value) => sum + value, 0) / normalized.length);
}

function setSeries(
  target: Record<string, unknown>,
  index: number,
  value: number
): void {
  target[`s${index}`] = value;
}

function buildCategoryRowAccumulator(
  models: readonly DatasetModel[],
  benchmarks: readonly DatasetBenchmark[],
  getValue: GetValue
): CategoryRow[] {
  return categoriesForBenchmarks(benchmarks).map((cat) => {
    const row: CategoryRow = { category: cat };
    models.forEach((m, i) => {
      const points = radarAverages(m.id, benchmarks, getValue);
      const point = points.find((p) => p.category === cat);
      if (point?.value != null) {
        setSeries(row as Record<string, unknown>, i, round1(point.value * 100));
      }
    });
    return row;
  });
}

export function buildRadarRows(
  models: readonly DatasetModel[],
  benchmarks: readonly DatasetBenchmark[],
  getValue: GetValue
): CategoryRow[] {
  return buildCategoryRowAccumulator(models, benchmarks, getValue);
}

export function buildCategoryAverageRows(
  models: readonly DatasetModel[],
  benchmarks: readonly DatasetBenchmark[],
  getValue: GetValue
): CategoryRow[] {
  return buildCategoryRowAccumulator(models, benchmarks, getValue);
}

export function buildBenchmarkRows(
  models: readonly DatasetModel[],
  benchmarks: readonly DatasetBenchmark[],
  getValue: GetValue
): BenchmarkRow[] {
  const rows: BenchmarkRow[] = [];
  for (const bench of benchmarks) {
    const row: BenchmarkRow = {
      benchmarkId: bench.id,
      name: bench.name,
      category: bench.category,
    };
    let hasValue = false;
    models.forEach((m, i) => {
      const v = getValue(m.id, bench.id);
      if (v != null) {
        const pct = normalizePct(bench, v);
        if (pct == null) return;
        setSeries(row as Record<string, unknown>, i, pct);
        hasValue = true;
      }
    });
    if (hasValue) rows.push(row);
  }
  return rows;
}

export function buildFieldAverageByCategory(
  allModels: readonly DatasetModel[],
  benchmarks: readonly DatasetBenchmark[],
  getValue: GetValue
): { category: string; fieldPct: number | null }[] {
  return categoriesForBenchmarks(benchmarks).map((cat) => {
    const catBenches = benchmarks.filter((b) => b.category === cat);
    if (catBenches.length === 0) return { category: cat, fieldPct: null };
    let sum = 0;
    let count = 0;
    for (const bench of catBenches) {
      const values = allModels.map((m) => getValue(m.id, bench.id));
      const avg = averageNormalizedPct(values, bench);
      if (avg != null) {
        sum += avg;
        count += 1;
      }
    }
    return {
      category: cat,
      fieldPct: count > 0 ? round1(sum / count) : null,
    };
  });
}

export function buildCatalogShare(
  benchmarks: readonly DatasetBenchmark[]
): CatalogShareRow[] {
  return categoriesForBenchmarks(benchmarks).map((cat) => ({
    category: cat,
    count: benchmarks.filter((b) => b.category === cat).length,
  }));
}

export function buildModelProfileRows(
  modelId: string,
  allModels: readonly DatasetModel[],
  benchmarks: readonly DatasetBenchmark[],
  getValue: GetValue
): ModelProfileRow[] {
  return benchmarks.flatMap((bench) => {
    const row: ModelProfileRow = {
      benchmark: bench.name,
      fieldAvgPct: null,
    };
    const v = getValue(modelId, bench.id);
    if (v != null) {
      const modelPct = normalizePct(bench, v);
      if (modelPct != null) row.modelPct = modelPct;
    }
    const values = allModels.map((m) => getValue(m.id, bench.id));
    row.fieldAvgPct = averageNormalizedPct(values, bench);
    return row.modelPct != null || row.fieldAvgPct != null ? [row] : [];
  });
}

export function buildBenchmarkSpreadRows(
  benchmark: DatasetBenchmark,
  models: readonly DatasetModel[],
  getValue: GetValue
): BenchmarkSpreadRow[] {
  const present: { modelName: string; pct: number }[] = [];
  for (const m of models) {
    const v = getValue(m.id, benchmark.id);
    if (v != null) {
      const pct = normalizePct(benchmark, v);
      if (pct != null) present.push({ modelName: m.name, pct });
    }
  }
  present.sort((a, b) => b.pct - a.pct);
  return present.map((p, i) => ({
    rank: i + 1,
    modelName: p.modelName,
    pct: p.pct,
  }));
}

export function buildSankeyData(
  allModels: readonly DatasetModel[],
  benchmarks: readonly DatasetBenchmark[],
  getValue: GetValue
): SankeyChartData {
  // Collect benchmarks with at least one valid normalized point, grouped by category.
  const usedCats = new Set<string>();
  const nonEmptyBenches: DatasetBenchmark[] = [];
  for (const bench of benchmarks) {
    const values = allModels.map((m) => getValue(m.id, bench.id));
    if (values.some((value) => value != null && normalizePct(bench, value) != null)) {
      nonEmptyBenches.push(bench);
      usedCats.add(bench.category);
    }
  }

  // Build nodes: category labels first, then benchmark names
  const usedCategories = categoriesForBenchmarks(benchmarks).filter((c) => usedCats.has(c));
  const catLabels = usedCategories.map((c) => CATEGORY_LABELS[c]);
  const catNodeIndex = new Map<string, number>();
  catLabels.forEach((label, i) => catNodeIndex.set(label, i));

  const benchNames: string[] = [];
  const usedLabels = new Set(catLabels);
  for (const bench of nonEmptyBenches) {
    let name = bench.name;
    if (usedLabels.has(name)) name = `${bench.name} \u00b7`;
    usedLabels.add(name);
    benchNames.push(name);
  }
  const benchNodeIndex = new Map<string, number>();
  benchNames.forEach((name, i) => {
    benchNodeIndex.set(name, usedCategories.length + i);
  });

  const nodes = [
    ...catLabels.map((name) => ({ name })),
    ...benchNames.map((name) => ({ name })),
  ];

  // Build links: category → benchmark, value = SOTA normalized %
  const links: SankeyChartData["links"] = [];
  for (const [benchIndex, bench] of nonEmptyBenches.entries()) {
    const values = allModels.map((m) => getValue(m.id, bench.id));
    const normalized = values
      .map((value) => (value == null ? null : normalizePct(bench, value)))
      .filter((value): value is number => value != null);
    if (normalized.length === 0) continue;
    const catLabel = CATEGORY_LABELS[bench.category];
    const sourceIdx = catNodeIndex.get(catLabel);
    const benchName = benchNames[benchIndex];
    const targetIdx = benchNodeIndex.get(benchName);
    if (sourceIdx == null || targetIdx == null) continue;
    const pct = Math.max(...normalized);
    links.push({
      source: sourceIdx,
      target: targetIdx,
      value: Math.max(pct, 1),
    });
  }

  return { nodes, links };
}

export function buildOverallGauge(
  modelId: string,
  benchmarks: readonly DatasetBenchmark[],
  getValue: GetValue
): OverallGauge {
  let sum = 0;
  let present = 0;
  const normalizableCount = benchmarks.filter(isNormalizableBenchmark).length;
  for (const bench of benchmarks) {
    const v = getValue(modelId, bench.id);
    if (v != null) {
      const pct = normalizePct(bench, v);
      if (pct != null) {
        sum += pct;
        present += 1;
      }
    }
  }
  return {
    pct: present > 0 ? round1(sum / present) : null,
    coveragePct:
      normalizableCount > 0 ? Math.round((present / normalizableCount) * 100) : 0,
  };
}
