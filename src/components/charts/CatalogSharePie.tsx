import type { DatasetBenchmark } from "@/data/dataset";
import { buildCatalogShare, type CatalogShareRow } from "@/lib/chartData";
import { categoryChartConfig } from "@/components/charts/chart-config";
import {
  EvilPieChart,
  Pie,
  Tooltip,
  Legend,
} from "@/components/evilcharts/charts/pie-chart";

interface CatalogSharePieProps {
  benchmarks: readonly DatasetBenchmark[];
}

export function CatalogSharePie({ benchmarks }: CatalogSharePieProps) {
  const data = buildCatalogShare(benchmarks);
  const config = categoryChartConfig();

  return (
    <EvilPieChart<CatalogShareRow & Record<string, unknown>>
      data={data}
      config={config}
      dataKey="count"
      nameKey="category"
      className="h-[300px] w-full"
    >
      <Tooltip variant="frosted-glass" />
      <Legend />
      <Pie variant="gradient" />
    </EvilPieChart>
  );
}
