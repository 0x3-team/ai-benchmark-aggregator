export type BenchmarkCategory =
  | "knowledge"
  | "reasoning"
  | "math"
  | "coding"
  | "agentic"
  | "instruction"
  | "chat"
  | "vision";

export type Modality = "text" | "vision" | "audio";

export interface Model {
  id: string;
  name: string;
  vendor: string;
  family: string;
  releaseDate: string;
  contextWindowK: number;
  paramsB: number | null;
  modalities: Modality[];
  openWeights: boolean;
  priceInPer1M: number | null;
  priceOutPer1M: number | null;
}

export interface Benchmark {
  id: string;
  name: string;
  fullName: string;
  category: BenchmarkCategory;
  higherIsBetter: boolean;
  scaleMax: number;
  description: string;
  methodology: string;
  sourceUrl: string;
}

export interface Score {
  modelId: string;
  benchmarkId: string;
  value: number;
  date: string;
  note?: string;
}

export const CATEGORY_LABELS: Record<BenchmarkCategory, string> = {
  knowledge: "Knowledge",
  reasoning: "Reasoning",
  math: "Math",
  coding: "Coding",
  agentic: "Agentic",
  instruction: "Instruction",
  chat: "Chat",
  vision: "Vision",
};

export const CATEGORIES: BenchmarkCategory[] = [
  "knowledge",
  "reasoning",
  "math",
  "coding",
  "agentic",
  "instruction",
  "chat",
  "vision",
];
