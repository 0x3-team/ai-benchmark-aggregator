import type { Benchmark } from "../types";

// Interpolate between two rgb triplets, t in [0,1], with a fixed alpha.
function lerpRgba(
  a: [number, number, number],
  b: [number, number, number],
  t: number,
  alpha: number
): string {
  const r = Math.round(a[0] + (b[0] - a[0]) * t);
  const g = Math.round(a[1] + (b[1] - a[1]) * t);
  const bl = Math.round(a[2] + (b[2] - a[2]) * t);
  return `rgba(${r}, ${g}, ${bl}, ${alpha})`;
}

// Glass-friendly stops: cool blue (low) → green (high).
const LOW_RGB: [number, number, number] = [59, 130, 246];
const HIGH_RGB: [number, number, number] = [34, 197, 94];

export interface ColumnStats {
  min: number;
  max: number;
  best: number;
  worst: number;
  avg: number;
  count: number;
}

// Returns normalized stats for a benchmark column using only present values.
export function columnStats(
  values: (number | null)[],
  benchmark: Benchmark
): ColumnStats {
  const present = values.filter((v): v is number => v != null);
  if (present.length === 0) {
    return { min: 0, max: 0, best: 0, worst: 0, avg: 0, count: 0 };
  }
  const sorted = [...present].sort((a, b) => a - b);
  const best = benchmark.higherIsBetter ? sorted[sorted.length - 1] : sorted[0];
  const worst = benchmark.higherIsBetter ? sorted[0] : sorted[sorted.length - 1];
  const sum = present.reduce((s, v) => s + v, 0);
  return {
    min: Math.min(...present),
    max: Math.max(...present),
    best,
    worst,
    avg: sum / present.length,
    count: present.length,
  };
}

// Maps a value to a translucent heatmap color relative to the column min/max.
// Stops are glass-friendly: low scores read as a cool blue, high as green, and
// the fill stays semi-transparent so the liquid-glass surface reads through.
export function heatmapColor(
  value: number | null,
  stats: ColumnStats,
  benchmark: Benchmark
): string {
  if (value == null || stats.max === stats.min) {
    return "transparent";
  }
  const span = (value - stats.min) / (stats.max - stats.min);
  const t = benchmark.higherIsBetter ? span : 1 - span;
  // Alpha scales from faint (low) to fairly saturated (high) for legibility.
  const alpha = 0.24 + t * 0.58;
  return lerpRgba(LOW_RGB, HIGH_RGB, t, alpha);
}
