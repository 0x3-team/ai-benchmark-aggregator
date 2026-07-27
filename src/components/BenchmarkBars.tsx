import { useMemo } from "react";
import { useDataset, type DatasetBenchmark, type DatasetModel } from "../data/dataset";
import { CATEGORIES, CATEGORY_LABELS } from "../types";
import { CATEGORY_COLORS, categoryTint } from "../lib/categories";
import { buildBenchmarkRows, type BenchmarkRow } from "@/lib/chartData";
import { modelChartConfig, seriesKey } from "@/components/charts/chart-config";
import {
  EvilBarChart,
  Bar,
  XAxis,
  YAxis,
  Grid,
  Tooltip,
} from "@/components/evilcharts/charts/bar-chart";
import type { ChartConfig } from "@/components/evilcharts/ui/chart";

interface BenchmarkBarsProps {
  models: readonly DatasetModel[];
  benchmarks: readonly DatasetBenchmark[];
  onOpenModel: (modelId: string) => void;
}

export function BenchmarkBars({ models, benchmarks, onOpenModel }: BenchmarkBarsProps) {
  const { getValue } = useDataset();

  const groups = useMemo(
    () =>
      CATEGORIES.map((cat) => ({
        cat,
        items: benchmarks.filter((b) => b.category === cat),
      })).filter((g) => g.items.length > 0),
    [benchmarks]
  );

  const rowsByCategory = useMemo(() => {
    const rows = buildBenchmarkRows(models, benchmarks, getValue);
    const map = new Map<string, BenchmarkRow[]>();
    for (const row of rows) {
      const arr = map.get(row.category) ?? [];
      arr.push(row);
      map.set(row.category, arr);
    }
    return map;
  }, [models, benchmarks, getValue]);

  const config = modelChartConfig(models);

  return (
    <div className="glass-strong overflow-hidden rounded-xl">
      <div className="flex flex-col divide-y divide-white/5">
        {groups.map((g) => {
          const catRows = rowsByCategory.get(g.cat) ?? [];
          if (catRows.length === 0) return null;
          return (
            <div key={g.cat} className="px-4 py-3">
              <div
                className="mb-2 flex items-center gap-2 rounded-md px-2 py-1 text-[11px] font-semibold uppercase tracking-wide"
                style={{
                  background: categoryTint(g.cat, 0.12),
                  color: CATEGORY_COLORS[g.cat],
                }}
              >
                <span
                  className="h-2 w-2 rounded-full"
                  style={{
                    background: CATEGORY_COLORS[g.cat],
                    boxShadow: `0 0 6px ${CATEGORY_COLORS[g.cat]}`,
                  }}
                />
                {CATEGORY_LABELS[g.cat]}
              </div>
              <div style={{ height: catRows.length * 34 + 110 }}>
                <EvilBarChart<
                  BenchmarkRow & Record<string, unknown>,
                  Record<string, ChartConfig[string]>
                >
                  layout="horizontal"
                  data={catRows}
                  config={config}
                  className="h-full w-full"
                >
                  <Grid />
                  <YAxis dataKey="name" type="category" width={140} />
                  <XAxis type="number" domain={[0, 100]} />
                  <Tooltip variant="frosted-glass" />
                  {models.map((m, i) => (
                    <Bar
                      key={m.id}
                      dataKey={seriesKey(i)}
                      variant="default"
                      barProps={{ onClick: () => onOpenModel(m.id) }}
                    />
                  ))}
                </EvilBarChart>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
