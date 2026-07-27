import { useDataset, type DatasetBenchmark } from "@/data/dataset";
import { buildOverallGauge } from "@/lib/chartData";
import { singleSeriesConfig } from "@/components/charts/chart-config";
import {
  EvilRadialChart,
  RadialBar,
  Tooltip,
} from "@/components/evilcharts/charts/radial-chart";

interface ModelScoreRadialProps {
  modelId: string;
  benchmarks: readonly DatasetBenchmark[];
}

export function ModelScoreRadial({ modelId, benchmarks }: ModelScoreRadialProps) {
  const { getValue } = useDataset();
  const gauge = buildOverallGauge(modelId, benchmarks, getValue);
  const data = [{ name: "overall", value: gauge.pct }];
  const config = singleSeriesConfig("overall", "Overall average", "#8b5cf6");

  return (
    <div className="relative">
      <EvilRadialChart
        data={data}
        config={config}
        nameKey="name"
        variant="semi"
        className="h-[220px] w-full"
      >
        <RadialBar dataKey="value" />
        <Tooltip variant="frosted-glass" />
      </EvilRadialChart>
      <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-end pb-8">
        <span className="text-2xl font-bold">{gauge.pct.toFixed(0)}%</span>
        <span className="text-[10px] text-muted-foreground">
          coverage {gauge.coveragePct.toFixed(0)}%
        </span>
      </div>
    </div>
  );
}
