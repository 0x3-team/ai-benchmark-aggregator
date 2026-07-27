import { useDataset, type DatasetBenchmark, type DatasetModel } from "@/data/dataset";
import { buildModelProfileRows, type ModelProfileRow } from "@/lib/chartData";
import {
  EvilLineChart,
  Line,
  XAxis,
  YAxis,
  Grid,
  Tooltip,
  Legend,
} from "@/components/evilcharts/charts/line-chart";
import type { ChartConfig } from "@/components/evilcharts/ui/chart";

interface ModelScoreProfileLineProps {
  model: DatasetModel;
  allModels: readonly DatasetModel[];
  benchmarks: readonly DatasetBenchmark[];
}

export function ModelScoreProfileLine({
  model,
  allModels,
  benchmarks,
}: ModelScoreProfileLineProps) {
  const { getValue } = useDataset();
  const data = buildModelProfileRows(model.id, allModels, benchmarks, getValue);
  const config: ChartConfig = {
    model: {
      label: model.name,
      colors: { light: ["#60a5fa"], dark: ["#60a5fa"] },
    },
    field: {
      label: "Field average",
      colors: { light: ["#94a3b8"], dark: ["#94a3b8"] },
    },
  };

  const Chart = EvilLineChart<
    ModelProfileRow & Record<string, unknown>,
    Record<string, ChartConfig[string]>
  >;

  return (
    <Chart
      data={data}
      config={config}
      className="h-[280px] w-full"
    >
      <Grid />
      <XAxis dataKey="benchmark" />
      <YAxis domain={[0, 100]} />
      <Tooltip variant="frosted-glass" />
      <Legend />
      <Line dataKey="modelPct" strokeVariant="solid" />
      <Line dataKey="fieldAvgPct" strokeVariant="dashed" />
    </Chart>
  );
}
