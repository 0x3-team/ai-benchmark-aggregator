// @vitest-environment node

import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

/**
 * Static containment guard for the UI-07 scale fixture.
 *
 * `src/lib/scaleFixtures.ts` builds large synthetic datasets for tests only.
 * It must never become app or Official input, so this suite proves that:
 *
 * 1. no runtime (non-test) module anywhere under src imports it;
 * 2. the runtime module graph rooted at `src/main.tsx` cannot reach it;
 * 3. the Demo catalog modules keep their pinned provenance: `scores.ts`,
 *    `models.ts`, and `benchmarks.ts` import only their tracked JSON, types,
 *    and the fail-closed Demo benchmark parser — they can never swap in
 *    generated rows.
 */

const SRC_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const FIXTURE_MODULE_NAME = "scaleFixtures";
const TEST_FILE_RE = /\.test\.(ts|tsx)$/;
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
      if (TEST_FILE_RE.test(file)) continue;
      for (const specifier of importSpecifiers(file)) {
        if (specifier.includes(FIXTURE_MODULE_NAME)) {
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
    const reachable = [...graph].filter((file) => file.includes(FIXTURE_MODULE_NAME));
    expect(reachable).toEqual([]);
  });

  it("pins Demo catalog provenance to the tracked JSON modules only", () => {
    const provenance: Record<string, readonly string[]> = {
      "data/scores.ts": ["../types", "./scores.json"],
      "data/models.ts": ["../types", "./models.json"],
      "data/benchmarks.ts": ["../types", "./benchmarks.json", "./demoCatalog"],
    };
    for (const [relativeFile, allowed] of Object.entries(provenance)) {
      const specifiers = importSpecifiers(path.join(SRC_ROOT, relativeFile));
      expect(specifiers.length).toBeGreaterThan(0);
      for (const specifier of specifiers) {
        expect(
          allowed.includes(specifier),
          `${relativeFile} must only import ${allowed.join(", ")}; found ${specifier}`
        ).toBe(true);
      }
    }
  });
});
