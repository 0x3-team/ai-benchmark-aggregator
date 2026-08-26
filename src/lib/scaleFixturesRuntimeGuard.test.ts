// @vitest-environment node

import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

/**
 * Static containment guard for all frontend-only fixtures.
 *
 * `src/lib/scaleFixtures.ts` and `src/data/testFixtures.ts` supply tests only.
 * They must never become app or Official input, so this suite proves that:
 *
 * 1. no runtime (non-test) module anywhere under src imports it;
 * 2. the runtime module graph rooted at `src/main.tsx` cannot reach it;
 * 3. removed full-catalog inputs stay absent and the sample artifact remains
 *    unreachable from the production entry.
 */

const SRC_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const FIXTURE_MODULE_NAMES = ["scaleFixtures", "testFixtures"] as const;
const TEST_MODULE_RE = /\.(?:test|testFixtures)\.(ts|tsx)$/;
const RESOLVE_EXTENSIONS = [".ts", ".tsx", ".js", ".jsx", ".mjs", ".json"];

const IMPORT_SPECIFIER_RE =
  /(?:import|export)\s+(?:type\s+)?(?:[^"'();]*?\s+from\s+)?["']([^"']+)["']|import\s*\(\s*["']([^"']+)["']\s*\)/g;

function listSourceFiles(dir: string): string[] {
  const files: string[] = [];
  for (const entry of readdirSync(dir)) {
    const full = path.join(dir, entry);
    if (statSync(full).isDirectory()) {
      files.push(...listSourceFiles(full));
    } else if (/\.(ts|tsx)$/.test(entry)) {
      files.push(full);
    }
  }
  return files;
}

function importSpecifiers(filePath: string): string[] {
  const source = readFileSync(filePath, "utf8");
  const specifiers: string[] = [];
  for (const match of source.matchAll(IMPORT_SPECIFIER_RE)) {
    const specifier = match[1] ?? match[2];
    if (specifier) specifiers.push(specifier);
  }
  return specifiers;
}

function isFixtureSpecifier(specifier: string): boolean {
  return (
    specifier.includes(".testFixtures") ||
    FIXTURE_MODULE_NAMES.some((name) =>
      new RegExp(`(?:^|/)${name}(?:\\.[tj]sx?)?$`).test(specifier)
    )
  );
}

function resolveSpecifier(specifier: string, fromFile: string): string | null {
  let candidate: string;
  if (specifier.startsWith("@/registry/")) {
    candidate = path.join(SRC_ROOT, "components/evilcharts", specifier.slice("@/registry/".length));
  } else if (specifier.startsWith("@/")) {
    candidate = path.join(SRC_ROOT, specifier.slice(2));
  } else if (specifier.startsWith("./") || specifier.startsWith("../")) {
    candidate = path.resolve(path.dirname(fromFile), specifier);
  } else {
    return null; // package or builtin import: outside the src graph.
  }
  const attempts = [
    candidate,
    ...RESOLVE_EXTENSIONS.map((ext) => candidate + ext),
    ...RESOLVE_EXTENSIONS.map((ext) => path.join(candidate, `index${ext}`)),
  ];
  for (const attempt of attempts) {
    try {
      if (statSync(attempt).isFile()) return attempt;
    } catch {
      // keep trying candidates
    }
  }
  return null;
}

/** Every module reachable from the runtime entry, transitive. */
function runtimeModuleGraph(entry: string): Set<string> {
  const visited = new Set<string>();
  const queue = [entry];
  while (queue.length > 0) {
    const current = queue.pop()!;
    if (visited.has(current)) continue;
    visited.add(current);
    if (!/\.(ts|tsx|js|jsx|mjs)$/.test(current)) continue;
    for (const specifier of importSpecifiers(current)) {
      const resolved = resolveSpecifier(specifier, current);
      if (resolved && !visited.has(resolved)) queue.push(resolved);
    }
  }
  return visited;
}

describe("scaleFixtures runtime containment", () => {
  it("is never imported by any runtime (non-test) module under src", () => {
    const offenders: string[] = [];
    for (const file of listSourceFiles(SRC_ROOT)) {
      if (TEST_MODULE_RE.test(file)) continue;
      for (const specifier of importSpecifiers(file)) {
        if (isFixtureSpecifier(specifier)) {
          offenders.push(`${path.relative(SRC_ROOT, file)} imports ${specifier}`);
        }
      }
    }
    expect(offenders).toEqual([]);
  });

  it("is unreachable from the src/main.tsx runtime module graph", () => {
    const graph = runtimeModuleGraph(path.join(SRC_ROOT, "main.tsx"));
    // Sanity: the walk must really have traversed the app, not stalled.
    expect(graph.size).toBeGreaterThan(40);
    const forbiddenFixturePaths = [
      path.join(SRC_ROOT, "lib/scaleFixtures.ts"),
      path.join(SRC_ROOT, "data/testFixtures.ts"),
    ];
    const reachable = [...graph].filter((file) => forbiddenFixturePaths.includes(file));
    expect(reachable).toEqual([]);
  });

  it("detects the real testFixtures import specifier", () => {
    expect(isFixtureSpecifier("./data/testFixtures")).toBe(true);
    expect(isFixtureSpecifier("../data/testFixtures.ts")).toBe(true);
    expect(isFixtureSpecifier("../lib/scaleFixtures")).toBe(true);
    expect(isFixtureSpecifier("./data/dataset")).toBe(false);
  });

  it("keeps removed catalogs absent and the sample artifact outside the runtime graph", () => {
    const graph = runtimeModuleGraph(path.join(SRC_ROOT, "main.tsx"));
    const removed = [
      "data/models.json",
      "data/scores.json",
      "data/benchmarks.json",
      "data/demoCatalog.ts",
      "data/demoCatalog.test.ts",
      "data/demoCatalog.testFixtures.ts",
    ].map((relative) => path.join(SRC_ROOT, relative));

    expect(removed.filter(existsSync)).toEqual([]);
    expect(graph.has(path.join(SRC_ROOT, "data/official/export.sample.json"))).toBe(false);
    expect(graph.has(path.join(SRC_ROOT, "data/official/export.unavailable.json"))).toBe(true);
  });
});
