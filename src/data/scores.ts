import type { Score } from "../types";
import scoreData from "./scores.json";

/**
 * Production scores from OpenEvals, HF OLL, Artificial Analysis, LMSYS, SWE-bench, and more.
 */
export function getScores(): Score[] {
  return scoreData as Score[];
}
