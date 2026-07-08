// Shared palette for coloring selected models across the comparison views
// (radar, per-category bars, per-benchmark bars). Index is the selection order.
export const MODEL_PALETTE = [
  "#3b82f6",
  "#22c55e",
  "#f59e0b",
  "#ec4899",
  "#a855f7",
  "#14b8a6",
];

export function modelColor(index: number): string {
  return MODEL_PALETTE[index % MODEL_PALETTE.length];
}
