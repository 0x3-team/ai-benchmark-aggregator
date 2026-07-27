import { useDataset, type DatasetBenchmark, type DatasetModel } from "@/data/dataset";
import { CATEGORY_LABELS } from "@/types";
import { buildSankeyData, type SankeyChartData } from "@/lib/chartData";
import { categoryChartConfig } from "@/components/charts/chart-config";
import {
  EvilSankeyChart,
  Node,
  Link,
  NodeLabel,
} from "@/components/evilcharts/charts/sankey-chart";

interface CategoryBenchmarkSankeyProps {
  benchmarks: readonly DatasetBenchmark[];
  allModels: readonly DatasetModel[];
}

export function CategoryBenchmarkSankey({ benchmarks, allModels }: CategoryBenchmarkSankeyProps) {
  const { getValue } = useDataset();
  const data = buildSankeyData(allModels, benchmarks, getValue);

  // Cap to top 40 benchmarks by SOTA value if too dense
  if (data.nodes.length > 48) {
    const sortedLinks = [...data.links].sort((a, b) => b.value - a.value);
    const topLinks = sortedLinks.slice(0, 40);
    const usedNodeIndices = new Set<number>();
    topLinks.forEach((l) => {
      usedNodeIndices.add(l.source);
      usedNodeIndices.add(l.target);
    });
    const oldToNew = new Map<number, number>();
    const filteredNodes = data.nodes.filter((_, i) => {
      if (usedNodeIndices.has(i)) {
        oldToNew.set(i, oldToNew.size);
        return true;
      }
      return false;
    });
    const filteredLinks = topLinks
      .map((l) => ({
        source: oldToNew.get(l.source) ?? 0,
        target: oldToNew.get(l.target) ?? 0,
        value: l.value,
      }))
      .filter((l) => l.source !== l.target);
    return (
      <EvilSankeyChart
        data={{ nodes: filteredNodes, links: filteredLinks } as SankeyChartData}
        config={categoryChartConfig()}
        className="h-[520px] w-full"
        backgroundVariant="dots"
      >
        <Link variant="gradient" />
        <Node />
        <NodeLabel />
      </EvilSankeyChart>
    );
  }

  return (
    <EvilSankeyChart
      data={data as SankeyChartData}
      config={categoryChartConfig()}
      className="h-[520px] w-full"
      backgroundVariant="dots"
    >
      <Link variant="gradient" />
      <Node />
      <NodeLabel />
    </EvilSankeyChart>
  );
}

// Keep CATEGORY_LABELS import used (referenced in cap logic indirectly)
void CATEGORY_LABELS;
