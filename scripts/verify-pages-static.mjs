import assert from "node:assert/strict";
import { readFile, stat } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const requiredFiles = ["404.html", "robots.txt", "_headers"];

async function isFile(filePath) {
  try {
    return (await stat(filePath)).isFile();
  } catch {
    return false;
  }
}

async function isDirectory(directoryPath) {
  try {
    return (await stat(directoryPath)).isDirectory();
  } catch {
    return false;
  }
}

async function readRequiredFiles(directory, label) {
  const contents = new Map();
  for (const file of requiredFiles) {
    const filePath = join(directory, file);
    assert.ok(await isFile(filePath), `${label} is missing required ${file}`);
    contents.set(file, await readFile(filePath, "utf8"));
  }
  return contents;
}

function assertRobots(robots, label) {
  assert.doesNotMatch(robots, /<\/?(?:!doctype|html|head|body)\b/i, `${label} must be plain text`);
  assert.match(robots, /^User-agent:\s*\*\s*$/m, `${label} needs User-agent`);
  assert.match(robots, /^Allow:\s*\/\s*$/m, `${label} needs Allow`);
  assert.doesNotMatch(robots, /^Sitemap:\s*$/im, `${label} has an empty Sitemap`);
  assert.ok(!robots.includes("\0"), `${label} must not contain NUL bytes`);
}

function assertNotFound(notFound, label) {
  assert.match(notFound, /^<!doctype html>/i, `${label} must be HTML`);
  assert.match(notFound, /<html\s+lang=["']en["']/i, `${label} needs lang=en`);
  assert.match(notFound, /<title>[^<]*Page not found/i, `${label} needs a not-found title`);
  assert.match(notFound, /\b404\b/, `${label} needs a 404 marker`);
  assert.match(notFound, /href=["']\/["']/, `${label} needs a root link`);
  assert.doesNotMatch(notFound, /id=["']root["']/i, `${label} must not be the SPA shell`);
}

function assertHeaders(headers, label) {
  for (const expected of [
    "X-Content-Type-Options: nosniff",
    "Referrer-Policy: strict-origin-when-cross-origin",
    "X-Frame-Options: DENY",
    "Permissions-Policy:",
    "Content-Security-Policy-Report-Only:",
    "https://:project.pages.dev/*",
    "https://:version.:project.pages.dev/*",
    "X-Robots-Tag: noindex",
  ]) {
    assert.ok(headers.includes(expected), `${label} is missing ${expected}`);
  }
  assert.doesNotMatch(headers, /^\s*Strict-Transport-Security:/im, `${label} must not add HSTS`);
  assert.doesNotMatch(
    headers,
    /^\s*Content-Security-Policy:/im,
    `${label} must keep CSP report-only`,
  );
  assert.doesNotMatch(headers, /_worker\.js|functions\//i, `${label} must not add a Worker`);
}

function assertCanonical(index, label) {
  const canonical = index.match(/<link\s+rel=["']canonical["']\s+href=["']([^"']+)["']/i);
  assert.ok(canonical, `${label} must declare rel=canonical`);
  assert.equal(canonical[1], "https://benchmark.0x3.dev/", `${label} has the wrong canonical`);
  assert.doesNotMatch(canonical[1], /\.pages\.dev\//i, `${label} must not canonicalize a preview host`);
  assert.match(
    index,
    /<meta\s+name=["']robots["']\s+content=["']index,\s*follow["']/i,
    `${label} needs index/follow metadata`,
  );
}

/**
 * Validate source Pages controls and, when requested/present, their built copy.
 * Unit tests can omit `requireDist`; the public CLI/package command passes
 * `--require-dist`, so a missing or stale dist is always fatal in CI.
 */
export async function verifyPagesStatic({ rootDir = repoRoot, requireDist = false } = {}) {
  const publicDir = join(rootDir, "public");
  const source = await readRequiredFiles(publicDir, "public/");
  assertNotFound(source.get("404.html"), "public/404.html");
  assertRobots(source.get("robots.txt"), "public/robots.txt");
  assertHeaders(source.get("_headers"), "public/_headers");
  assertCanonical(await readFile(join(rootDir, "index.html"), "utf8"), "index.html");

  const distDir = join(rootDir, "dist");
  const distPresent = await isDirectory(distDir);
  if (requireDist || distPresent) {
    assert.ok(await isFile(join(distDir, "index.html")), "dist/ is missing built index.html");
    const built = await readRequiredFiles(distDir, "dist/");
    for (const file of requiredFiles) {
      assert.equal(built.get(file), source.get(file), `dist/${file} is missing or stale`);
    }
    assertCanonical(await readFile(join(distDir, "index.html"), "utf8"), "dist/index.html");
  }

  return { sourceChecked: true, distChecked: requireDist || distPresent };
}

function parseCliArgs(args) {
  let rootDir = repoRoot;
  let requireDist = false;
  for (let index = 0; index < args.length; index += 1) {
    const arg = args[index];
    if (arg === "--require-dist") {
      requireDist = true;
    } else if (arg === "--root-dir") {
      const value = args[index + 1];
      assert.ok(value, "--root-dir requires a path");
      rootDir = resolve(value);
      index += 1;
    } else if (arg === "--help" || arg === "-h") {
      console.log("Usage: node scripts/verify-pages-static.mjs [--require-dist] [--root-dir PATH]");
      return null;
    } else {
      throw new Error(`Unknown argument: ${arg}`);
    }
  }
  return { rootDir, requireDist };
}

const isMain = process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url);
if (isMain) {
  try {
    const options = parseCliArgs(process.argv.slice(2));
    if (!options) process.exit(0);
    const result = await verifyPagesStatic(options);
    console.log(`Pages static verification passed (source${result.distChecked ? " + dist" : ""}).`);
  } catch (error) {
    console.error(error instanceof Error ? error.message : error);
    process.exitCode = 1;
  }
}
