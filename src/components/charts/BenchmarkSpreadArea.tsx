import { useDataset, type DatasetBenchmark, type DatasetModel } from "@/data/dataset";
import { buildBenchmarkSpreadRows, type BenchmarkSpreadRow } from "@/lib/chartData";
import { singleSeriesConfig } from "@/components/charts/chart-config";
import {
  EvilAreaChart,
  Area,
  XAxis,
  YAxis,
  Grid,
  Tooltip,
} from "@/components/evilcharts/charts/area-chart";
import type { ChartConfig } from "@/components/evilcharts/ui/chart";

interface BenchmarkSpreadAreaProps {
  benchmark: DatasetBenchmark;
  models: readonly DatasetModel[];
}

export function BenchmarkSpreadArea({ benchmark, models }: BenchmarkSpreadAreaProps) {
  const { getValue } = useDataset();
  const data = buildBenchmarkSpreadRows(benchmark, models, getValue);
  const config = singleSeriesConfig("pct", "Score", "#34d399");

  const Chart = EvilAreaChart<
    BenchmarkSpreadRow & Record<string, unknown>,
    Record<string, ChartConfig[string]>
  >;

  return (
    <Chart
      data={data}
      config={config}
      className="h-[240px] w-full"
    >
      <Grid />
      <XAxis dataKey="rank" type="number" />
      <YAxis domain={[0, 100]} />
      <Tooltip variant="frosted-glass" />
      <Area dataKey="pct" variant="gradient" strokeVariant="solid" />
    </Chart>
  );
}
