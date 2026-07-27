import type { ChartConfig } from "@/components/evilcharts/ui/chart";
import type { DatasetModel } from "@/data/dataset";
import type { BenchmarkCategory } from "@/types";
import { CATEGORY_LABELS } from "@/types";
import { CATEGORY_COLORS } from "@/lib/categories";
import { modelColor } from "@/lib/palette";
import type { SeriesKey } from "@/lib/chartData";

export function seriesKey(i: number): SeriesKey {
  return `s${i}`;
}

export function modelChartConfig(models: readonly DatasetModel[]): ChartConfig {
  const config: ChartConfig = {};
  models.forEach((m, i) => {
    const hex = modelColor(i);
    config[seriesKey(i)] = {
      label: m.name,
      colors: { light: [hex], dark: [hex] },
    };
  });
  return config;
}

export function categoryChartConfig(): ChartConfig {
  const config: ChartConfig = {};
  for (const [cat, label] of Object.entries(CATEGORY_LABELS)) {
    const hex = CATEGORY_COLORS[cat as BenchmarkCategory];
    config[cat] = {
      label,
      colors: { light: [hex], dark: [hex] },
    };
  }
  return config;
}

export function singleSeriesConfig(key: string, label: string, hex: string): ChartConfig {
  return {
    [key]: {
      label,
      colors: { light: [hex], dark: [hex] },
    },
  };
}
