import type { Benchmark, Model, Score } from "../types";
import { models as demoModels } from "./models";
import { benchmarks as demoBenchmarks } from "./benchmarks";
import { getScores } from "./scores";

// Dual-mode data registry (ADR-003). The SPA can run on demo synthetic data or
// on official ledger-backed claims, but never both at once. App.tsx publishes the
// selected dataset here via setActiveData(); every consumer reads through the
// getters below so the call sites never branch on trust level.
//
// getValue(modelId, benchmarkId) stays the SINGLE score accessor used by the
// table / compare / detail components — it simply reads the active index.

let activeModels: Model[] = demoModels;
let activeBenchmarks: Benchmark[] = demoBenchmarks;

// The demo score index is built lazily (never at module load) to avoid a
// TDZ on the shared score holder during the registry<->scores init cycle.
// The first getValue()/getScoreEntry() call builds it.
let activeScoreIndex: Map<string, Score> | null = null;
function ensureIndex(): Map<string, Score> {
  if (activeScoreIndex === null) {
    activeScoreIndex = buildIndex(getScores());
  }
  return activeScoreIndex;
}

function buildIndex(scores: Score[]): Map<string, Score> {
  const index = new Map<string, Score>();
  for (const s of scores) index.set(s.modelId + ":" + s.benchmarkId, s);
  return index;
}

export interface ActiveData {
  models: Model[];
  benchmarks: Benchmark[];
  scores: Score[];
}

// Publish the active dataset. Called from App.tsx when dataMode changes.
// Idempotent for the same input, so React StrictMode double-invocation is safe.
export function setActiveData(data: ActiveData): void {
  activeModels = data.models;
  activeBenchmarks = data.benchmarks;
  activeScoreIndex = buildIndex(data.scores);
}

export function getModels(): Model[] {
  return activeModels;
}

export function getBenchmarks(): Benchmark[] {
  return activeBenchmarks;
}

// SOLE score accessor (ADR-003). Returns null for missing cells so the UI can
// render them as no-data without special-casing the trust mode.
export function getValue(modelId: string, benchmarkId: string): number | null {
  return ensureIndex().get(modelId + ":" + benchmarkId)?.value ?? null;
}

// Provenance lookup for official claims. Demo scores carry no provenance, so the
// returned entry's officialSourceId / scoreRaw / captureStatus are undefined in
// demo mode — callers use that to decide whether to show a provenance note.
export function getScoreEntry(
  modelId: string,
  benchmarkId: string
): Score | null {
  return ensureIndex().get(modelId + ":" + benchmarkId) ?? null;
}
