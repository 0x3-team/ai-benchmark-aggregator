import type { Model } from "../types";
import modelData from "./models.json";

/**
 * Production model catalog from OpenEvals, HuggingFace OLL, Artificial Analysis, LMSYS, and more.
 */
export const models: Model[] = modelData as Model[];
