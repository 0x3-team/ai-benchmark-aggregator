import { useDataset, type DatasetBenchmark, type DatasetModel } from "@/data/dataset";
import { CATEGORY_LABELS } from "@/types";
import { buildCategoryAverageRows, buildFieldAverageByCategory, type CategoryRow } from "@/lib/chartData";
import { modelChartConfig, seriesKey } from "@/components/charts/chart-config";
import {
  EvilComposedChart,
  Bar,
  Line,
  XAxis,
  YAxis,
  Grid,
  Tooltip,
  Legend,
} from "@/components/evilcharts/charts/composed-chart";
import type { ChartConfig } from "@/components/evilcharts/ui/chart";

interface CategoryVsFieldComposedProps {
  models: readonly DatasetModel[];
  benchmarks: readonly DatasetBenchmark[];
  allModels: readonly DatasetModel[];
}

export function CategoryVsFieldComposed({
  models,
  benchmarks,
  allModels,
}: CategoryVsFieldComposedProps) {
  const { getValue } = useDataset();
  const categoryRows = buildCategoryAverageRows(models, benchmarks, getValue);
  const fieldRows = buildFieldAverageByCategory(allModels, benchmarks, getValue);
  const fieldByCat = new Map(fieldRows.map((r) => [r.category, r.fieldPct]));
  const data = categoryRows.map((row) => ({
    ...row,
    fieldPct: fieldByCat.get(row.category) ?? 0,
  }));

  const config = modelChartConfig(models);
  (config as ChartConfig)["field"] = {
    label: "Field average",
    colors: { light: ["#94a3b8"], dark: ["#94a3b8"] },
  };

  return (
    <EvilComposedChart<
      CategoryRow & { fieldPct: number } & Record<string, unknown>,
      Record<string, ChartConfig[string]>
    >
      data={data}
      config={config}
      className="h-[420px] w-full"
    >
      <Grid />
      <XAxis
        dataKey="category"
        tickFormatter={(cat: string) =>
          CATEGORY_LABELS[cat as keyof typeof CATEGORY_LABELS] ?? cat
        }
      />
      <YAxis domain={[0, 100]} />
      <Tooltip variant="frosted-glass" />
      <Legend isClickable />
      {models.map((m, i) => (
        <Bar key={m.id} dataKey={seriesKey(i)} variant="duotone" />
      ))}
      <Line dataKey="fieldPct" strokeVariant="animated-dashed" />
    </EvilComposedChart>
  );
}
