import type { BenchmarkCategory } from "../types";
import { CATEGORIES } from "../types";

export interface PermalinkSort {
  benchmarkId: string;
  dir: "asc" | "desc";
}

export interface PermalinkState {
  view: "table" | "compare";
  q: string;
  vendor: string[];
  category: BenchmarkCategory | null;
  open: boolean;
  sort: PermalinkSort | null;
  compare: string[];
  model: string | null;
  benchmark: string | null;
  all: boolean;
  zero: boolean;
}

export const DEFAULT_PERMALINK_STATE: PermalinkState = {
  view: "table",
  q: "",
  vendor: [],
  category: null,
  open: false,
  sort: null,
  compare: [],
  model: null,
  benchmark: null,
  all: false,
  zero: false,
};

export const PERMALINK_MAX_COMPARE = 6;
export const PERMALINK_MAX_VALUE_LENGTH = 256;

const VERSION = "1";
const MAX_QUERY_LENGTH = 4096;

const VIEWS: PermalinkState["view"][] = ["table", "compare"];
const DIRS: PermalinkSort["dir"][] = ["asc", "desc"];
const CATEGORY_SET = new Set<string>(CATEGORIES);
const SINGLETON_PARAMS = new Set([
  "v",
  "view",
  "q",
  "category",
  "open",
  "sort",
  "dir",
  "model",
  "benchmark",
  "all",
  "zero",
]);

function isControlChar(code: number): boolean {
  return code <= 0x1f || code === 0x7f;
}

function hasControlChar(s: string): boolean {
  for (let i = 0; i < s.length; i++) {
    if (isControlChar(s.charCodeAt(i))) return true;
  }
  return false;
}

function isHex(ch: string): boolean {
  const c = ch.charCodeAt(0);
  return (
    (c >= 0x30 && c <= 0x39) ||
    (c >= 0x41 && c <= 0x46) ||
    (c >= 0x61 && c <= 0x66)
  );
}

function hasInvalidPercentSequence(s: string): boolean {
  for (let i = 0; i < s.length; i++) {
    if (s[i] !== "%") continue;
    if (i + 2 >= s.length || !isHex(s[i + 1]) || !isHex(s[i + 2])) {
      return true;
    }
    i += 2;
  }
  return false;
}

function isValidScalar(value: string): boolean {
  if (value.length === 0) return false;
  if (value.length > PERMALINK_MAX_VALUE_LENGTH) return false;
  if (hasControlChar(value)) return false;
  return true;
}

function isValidSearch(value: string): boolean {
  if (value.length > PERMALINK_MAX_VALUE_LENGTH) return false;
  if (hasControlChar(value)) return false;
  return true;
}

function isValidBooleanToken(value: string): boolean {
  return value === "1";
}

export function createDefaultPermalinkState(): PermalinkState {
  return {
    ...DEFAULT_PERMALINK_STATE,
    vendor: [],
    compare: [],
  };
}

function failClosed(): PermalinkState {
  return createDefaultPermalinkState();
}

function rawFromInput(input: string | URLSearchParams): string {
  if (typeof input === "string") return input;
  return input.toString();
}

/**
 * Encode a `PermalinkState` into a deterministic, canonical v=1 query string.
 *
 * Defaults are omitted. Repeated values preserve order. The output is prefixed
 * with `?` so it can be assigned directly to `location.search`.
 *
 * The codec stays pure: it touches no React, router, storage, network, data, or
 * scores. Dataset IDs are opaque here; App code validates them against the
 * active dataset.
 */
export function encodePermalink(state: PermalinkState): string {
  const parts: string[] = [`v=${VERSION}`];

  const push = (key: string, value: string) => {
    parts.push(`${key}=${encodeURIComponent(value)}`);
  };

  if (state.view !== "table") push("view", state.view);
  if (state.q !== "") push("q", state.q);
  for (const vendor of state.vendor) push("vendor", vendor);
  if (state.category !== null) push("category", state.category);
  if (state.open) parts.push("open=1");
  if (state.sort !== null) {
    push("sort", state.sort.benchmarkId);
    push("dir", state.sort.dir);
  }
  for (const modelId of state.compare) push("compare", modelId);
  if (state.model !== null) push("model", state.model);
  if (state.benchmark !== null) push("benchmark", state.benchmark);
  if (state.all) parts.push("all=1");
  if (state.zero) parts.push("zero=1");

  return `?${parts.join("&")}`;
}

/**
 * Decode a v=1 query string (or URLSearchParams) into a `PermalinkState`.
 *
 * Fail-closed: any malformed, overlong, unknown-version, or invalid input
 * returns `DEFAULT_PERMALINK_STATE`.
 */
export function decodePermalink(input: string | URLSearchParams): PermalinkState {
  let raw = rawFromInput(input);
  if (raw.startsWith("?")) raw = raw.slice(1);

  if (raw.length > MAX_QUERY_LENGTH) return failClosed();
  if (hasControlChar(raw)) return failClosed();
  if (hasInvalidPercentSequence(raw)) return failClosed();

  let params: URLSearchParams;
  try {
    params = new URLSearchParams(raw);
  } catch {
    return failClosed();
  }

  for (const [name, value] of params) {
    if (hasControlChar(name) || hasControlChar(value)) return failClosed();
  }

  const versions = params.getAll("v");
  if (versions.length !== 1 || versions[0] !== VERSION) {
    return failClosed();
  }

  for (const name of SINGLETON_PARAMS) {
    if (params.getAll(name).length > 1) return failClosed();
  }

  const state = createDefaultPermalinkState();

  const view = params.get("view");
  if (view !== null) {
    if (!isValidScalar(view)) return failClosed();
    if (!VIEWS.includes(view as PermalinkState["view"])) return failClosed();
    state.view = view as PermalinkState["view"];
  }

  const q = params.get("q");
  if (q !== null) {
    if (!isValidSearch(q)) return failClosed();
    state.q = q;
  }

  const seenVendors = new Set<string>();
  for (const vendor of params.getAll("vendor")) {
    if (!isValidScalar(vendor)) return failClosed();
    if (seenVendors.has(vendor)) continue;
    seenVendors.add(vendor);
    state.vendor.push(vendor);
  }

  const category = params.get("category");
  if (category !== null) {
    if (!isValidScalar(category)) return failClosed();
    if (!CATEGORY_SET.has(category)) return failClosed();
    state.category = category as BenchmarkCategory;
  }

  const open = params.get("open");
  if (open !== null) {
    if (!isValidScalar(open)) return failClosed();
    if (!isValidBooleanToken(open)) return failClosed();
    state.open = true;
  }

  const sort = params.get("sort");
  const dir = params.get("dir");
  if (sort !== null && dir !== null) {
    if (!isValidScalar(sort)) return failClosed();
    if (!isValidScalar(dir)) return failClosed();
    if (!DIRS.includes(dir as PermalinkSort["dir"])) return failClosed();
    state.sort = { benchmarkId: sort, dir: dir as PermalinkSort["dir"] };
  } else if (sort !== null || dir !== null) {
    return failClosed();
  }

  const seenCompare = new Set<string>();
  for (const modelId of params.getAll("compare")) {
    if (!isValidScalar(modelId)) return failClosed();
    if (seenCompare.has(modelId)) continue;
    seenCompare.add(modelId);
    if (state.compare.length < PERMALINK_MAX_COMPARE) {
      state.compare.push(modelId);
    }
  }

  const model = params.get("model");
  const benchmark = params.get("benchmark");
  if (model !== null && benchmark !== null) return failClosed();

  if (model !== null) {
    if (!isValidScalar(model)) return failClosed();
    state.model = model;
  }

  if (benchmark !== null) {
    if (!isValidScalar(benchmark)) return failClosed();
    state.benchmark = benchmark;
  }

  const all = params.get("all");
  if (all !== null) {
    if (!isValidScalar(all)) return failClosed();
    if (!isValidBooleanToken(all)) return failClosed();
    state.all = true;
  }

  const zero = params.get("zero");
  if (zero !== null) {
    if (!isValidScalar(zero)) return failClosed();
    if (!isValidBooleanToken(zero)) return failClosed();
    state.zero = true;
  }

  return state;
}
