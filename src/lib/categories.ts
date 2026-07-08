import type { BenchmarkCategory } from "../types";

// Eight distinct hues that remain legible on dark glass. Used for the category
// group-header tint, the Category Leaders strip, and the compare legend.
export const CATEGORY_COLORS: Record<BenchmarkCategory, string> = {
  knowledge: "#38bdf8", // sky
  reasoning: "#a78bfa", // violet
  math: "#f472b6", // pink
  coding: "#34d399", // emerald
  agentic: "#fbbf24", // amber
  instruction: "#22d3ee", // cyan
  chat: "#fb7185", // rose
  vision: "#f59e0b", // orange
};

export function hexToRgba(hex: string, alpha: number): string {
  const h = hex.replace("#", "");
  const r = parseInt(h.substring(0, 2), 16);
  const g = parseInt(h.substring(2, 4), 16);
  const b = parseInt(h.substring(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

export function categoryDotColor(cat: BenchmarkCategory): string {
  return CATEGORY_COLORS[cat];
}

// Low-alpha fill used to tint group headers and chips.
export function categoryTint(cat: BenchmarkCategory, alpha: number): string {
  return hexToRgba(CATEGORY_COLORS[cat], alpha);
}
