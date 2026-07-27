import { useDataset, type DatasetBenchmark, type DatasetModel } from "@/data/dataset";
import { CATEGORY_LABELS } from "@/types";
import { buildCategoryAverageRows, type CategoryRow } from "@/lib/chartData";
import { modelChartConfig, seriesKey } from "@/components/charts/chart-config";
import {
  EvilBarChart,
  Bar,
  XAxis,
  YAxis,
  Grid,
  Tooltip,
  Legend,
} from "@/components/evilcharts/charts/bar-chart";
import type { ChartConfig } from "@/components/evilcharts/ui/chart";

interface CategoryAverageBarsProps {
  models: readonly DatasetModel[];
  benchmarks: readonly DatasetBenchmark[];
}

export function CategoryAverageBars({ models, benchmarks }: CategoryAverageBarsProps) {
  const { getValue } = useDataset();
  const data = buildCategoryAverageRows(models, benchmarks, getValue);
  const config = modelChartConfig(models);

  return (
    <EvilBarChart<
      CategoryRow & Record<string, unknown>,
      Record<string, ChartConfig[string]>
    >
      layout="horizontal"
      data={data}
      config={config}
      className="h-[520px] w-full"
    >
      <Grid />
      <YAxis
        dataKey="category"
        type="category"
        width={110}
        tickFormatter={(cat: string) =>
          CATEGORY_LABELS[cat as keyof typeof CATEGORY_LABELS] ?? cat
        }
      />
      <XAxis type="number" domain={[0, 100]} />
      <Tooltip variant="frosted-glass" />
      <Legend isClickable />
      {models.map((m, i) => (
        <Bar key={m.id} dataKey={seriesKey(i)} variant="gradient" />
      ))}
    </EvilBarChart>
  );
}
