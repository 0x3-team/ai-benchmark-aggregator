import { useDataset, type DatasetBenchmark, type DatasetModel } from "@/data/dataset";
import { CATEGORY_LABELS } from "@/types";
import { buildRadarRows, type CategoryRow } from "@/lib/chartData";
import { modelChartConfig, seriesKey } from "@/components/charts/chart-config";
import {
  EvilRadarChart,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
  Tooltip,
  Radar,
} from "@/components/evilcharts/charts/radar-chart";
import type { ChartConfig } from "@/components/evilcharts/ui/chart";

interface CapabilityRadarProps {
  models: readonly DatasetModel[];
  benchmarks: readonly DatasetBenchmark[];
}

export function CapabilityRadar({ models, benchmarks }: CapabilityRadarProps) {
  const { getValue } = useDataset();
  const data = buildRadarRows(models, benchmarks, getValue);
  const config = modelChartConfig(models);

  return (
    <EvilRadarChart<
      CategoryRow & Record<string, unknown>,
      Record<string, ChartConfig[string]>
    >
      data={data}
      config={config}
      className="h-[420px] w-full"
    >
      <PolarGrid />
      <PolarAngleAxis dataKey="category" tickFormatter={(cat: string) => CATEGORY_LABELS[cat as keyof typeof CATEGORY_LABELS] ?? cat} />
      <PolarRadiusAxis domain={[0, 100]} />
      <Tooltip variant="frosted-glass" />
      {models.map((m, i) => (
        <Radar
          key={m.id}
          dataKey={seriesKey(i)}
          variant="filled"
        />
      ))}
    </EvilRadarChart>
  );
}
