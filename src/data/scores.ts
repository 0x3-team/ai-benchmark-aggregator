import type { Score, BenchmarkCategory } from "../types";
import { benchmarks } from "./benchmarks";
import { models } from "./models";

const BASE_POWER: Record<string, number> = {
  "gpt-4o": 0.92,
  "gpt-4o-mini": 0.78,
  "o1": 0.9,
  "o1-mini": 0.84,
  "o3-mini": 0.88,
  "gpt-4-turbo": 0.88,
  "claude-3-5-sonnet": 0.91,
  "claude-3-5-haiku": 0.8,
  "claude-3-opus": 0.89,
  "gemini-1-5-pro": 0.88,
  "gemini-1-5-flash": 0.8,
  "gemini-2-0-flash": 0.86,
  "llama-3-1-405b": 0.87,
  "llama-3-1-70b": 0.82,
  "llama-3-1-8b": 0.7,
  "mistral-large": 0.83,
  "mixtral-8x22b": 0.79,
  "deepseek-v3": 0.88,
  "deepseek-r1": 0.9,
  "qwen-2-5-72b": 0.83,
  "command-r-plus": 0.81,
  "grok-2": 0.86,
  "phi-3-5": 0.68,
};

// Additive category deltas for specific models (strengths/weaknesses).
const OVERRIDES: Record<string, Partial<Record<BenchmarkCategory, number>>> = {
  "o1": { reasoning: 0.08, math: 0.1 },
  "o3-mini": { math: 0.12, reasoning: 0.1, coding: 0.04 },
  "deepseek-r1": { math: 0.13, reasoning: 0.11, coding: 0.06 },
  "deepseek-v3": { coding: 0.06, math: 0.08 },
  "claude-3-5-sonnet": { vision: 0.05, agentic: 0.04, instruction: 0.03 },
  "command-r-plus": { instruction: 0.06, agentic: 0.07 },
  "gpt-4o": { vision: 0.04, instruction: 0.02 },
  "gemini-1-5-pro": { vision: 0.03, knowledge: 0.02 },
  "gemini-2-0-flash": { vision: 0.03 },
  "llama-3-1-8b": { knowledge: -0.04, reasoning: -0.04, math: -0.05 },
  "phi-3-5": { reasoning: -0.03, math: -0.04 },
  "gpt-4o-mini": { reasoning: -0.02, math: -0.02 },
};

// Hard benchmarks get dropped entirely for weak models to exercise missing cells.
const WEAK_MISSING: Record<string, string[]> = {
  "llama-3-1-8b": ["arc-agi", "swebench", "mmmu"],
  "phi-3-5": ["arc-agi", "swebench", "aime2024", "mmmu"],
  "gpt-4o-mini": ["arc-agi", "swebench"],
  "mixtral-8x22b": ["arc-agi", "swebench"],
};

const CAT_BASE: Record<BenchmarkCategory, number> = {
  knowledge: 0.0,
  reasoning: -0.04,
  math: -0.06,
  coding: -0.05,
  agentic: -0.03,
  instruction: 0.01,
  chat: 0.0,
  vision: 0.0,
  other: 0.0,
};

function hashSeed(s: string): number {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

function mulberry32(seed: number): () => number {
  let a = seed;
  return function () {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function effectivePower(modelId: string, category: BenchmarkCategory): number {
  const base = BASE_POWER[modelId] ?? 0.75;
  const catShift = CAT_BASE[category] * (1.3 - base);
  const override = OVERRIDES[modelId]?.[category] ?? 0;
  return base + catShift + override;
}

function noteFor(modelId: string, benchmarkId: string): string | undefined {
  if (benchmarkId === "math500" || benchmarkId === "aime2024" || benchmarkId === "gsm8k") {
    if ((OVERRIDES[modelId]?.math ?? 0) > 0) return "CoT";
    return undefined;
  }
  if (benchmarkId === "mmmu") return "vision eval";
  if (benchmarkId === "swebench") return "agentic";
  if (benchmarkId === "bbh" || benchmarkId === "arc-agi") return "CoT";
  return undefined;
}

function generateScores(): Score[] {
  const out: Score[] = [];
  for (const model of models) {
    const missing = new Set(WEAK_MISSING[model.id] ?? []);
    for (const bench of benchmarks) {
      if (bench.category === "vision" && !model.modalities.includes("vision")) {
        continue;
      }
      if (missing.has(bench.id)) continue;

      const power = effectivePower(model.id, bench.category);
      const clamped = Math.max(0, Math.min(1, power));
      const rng = mulberry32(hashSeed(model.id + ":" + bench.id));
      const noiseAmp = bench.scaleMax * 0.04;
      const noise = (rng() * 2 - 1) * noiseAmp;
      let value = clamped * bench.scaleMax + noise;
      value = Math.max(0, Math.min(bench.scaleMax, value));
      value = Math.round(value * 10) / 10;

      out.push({
        modelId: model.id,
        benchmarkId: bench.id,
        value,
        date: model.releaseDate,
        note: noteFor(model.id, bench.id),
      });
    }
  }
  return out;
}

// Lazily initialize deterministic Demo scores after the static model and
// benchmark catalogs have loaded. This avoids allocating the full synthetic
// matrix merely by importing the module and leaves the React DatasetProvider
// as the UI's sole active-data boundary.
let _scores: Score[] | null = null;
export function getScores(): Score[] {
  if (_scores === null) _scores = generateScores();
  return _scores;
}

// Do not add score accessors here. UI consumers must obtain numeric values
// through DatasetProvider's `getValue(modelId, benchmarkId)` and provenance
// through its value-free `getScoreEntry`, never from a raw score array.
