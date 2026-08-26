import assert from "node:assert/strict";
import { cp, mkdtemp, readFile, readdir, rm, stat, writeFile } from "node:fs/promises";
import { spawnSync } from "node:child_process";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";
import { verifyPagesStatic } from "./verify-pages-static.mjs";

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const publicDir = join(repoRoot, "public");
const requiredFiles = ["404.html", "_headers", "robots.txt"];

async function textFile(relativePath) {
  return readFile(join(repoRoot, relativePath), "utf8");
}

test("Pages source assets exist and are copyable without mutation", async () => {
  const stagingDir = await mkdtemp(join(tmpdir(), "ai-benchmark-pages-"));
  try {
    for (const file of requiredFiles) {
      const sourcePath = join(publicDir, file);
      const sourceStat = await stat(sourcePath);
      assert.ok(sourceStat.isFile(), `${file} must be a regular file`);
      await cp(sourcePath, join(stagingDir, file));
      assert.equal(await readFile(join(stagingDir, file), "utf8"), await readFile(sourcePath, "utf8"));
    }
  } finally {
    await rm(stagingDir, { recursive: true, force: true });
  }
});

test("robots.txt is plain text with valid minimal directives", async () => {
  const robots = await textFile("public/robots.txt");
  assert.doesNotMatch(robots, /<\/?(?:!doctype|html|head|body)\b/i);
  assert.match(robots, /^User-agent:\s*\*\s*$/m);
  assert.match(robots, /^Allow:\s*\/\s*$/m);
  assert.doesNotMatch(robots, /^Sitemap:\s*$/im);
  assert.ok(!robots.includes("\0"), "robots.txt must not contain NUL bytes");
});

test("404.html is a real Pages not-found document", async () => {
  const notFound = await textFile("public/404.html");
  assert.match(notFound, /^<!doctype html>/i);
  assert.match(notFound, /<html\s+lang=["']en["']/i);
  assert.match(notFound, /<title>[^<]*Page not found/i);
  assert.match(notFound, /\b404\b/);
  assert.match(notFound, /href=["']\/["']/);
  assert.doesNotMatch(notFound, /id=["']root["']/i, "404 must not be the SPA shell");
});

test("index.html declares a custom-domain canonical URL", async () => {
  const index = await textFile("index.html");
  const canonical = index.match(/<link\s+rel=["']canonical["']\s+href=["']([^"']+)["']/i);
  assert.ok(canonical, "index.html must declare rel=canonical");
  assert.equal(canonical[1], "https://benchmark.0x3.dev/");
  assert.doesNotMatch(canonical[1], /\.pages\.dev\//i, "canonical must not target a preview host");
  assert.match(index, /<meta\s+name=["']robots["']\s+content=["']index,\s*follow["']/i);
});

test("_headers contains conservative static security and preview directives", async () => {
  const headers = await textFile("public/_headers");
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
    assert.ok(headers.includes(expected), `_headers is missing ${expected}`);
  }
  assert.doesNotMatch(headers, /^\s*Strict-Transport-Security:/im, "HSTS needs domain/deployment proof");
  assert.doesNotMatch(headers, /^\s*Content-Security-Policy:/im, "CSP must remain report-only until verified");
  assert.doesNotMatch(headers, /_worker\.js|functions\//i, "static Pages lane must not add a Worker");
});

test("public contains only source-only static controls for this lane", async () => {
  const entries = await readdir(publicDir);
  assert.ok(entries.includes("404.html"));
  assert.ok(entries.includes("robots.txt"));
  assert.ok(entries.includes("_headers"));
  assert.ok(!entries.some((entry) => entry === "_worker.js" || entry === "functions"));
});

async function createFixture({ withDist = false } = {}) {
  const fixtureRoot = await mkdtemp(join(tmpdir(), "ai-benchmark-pages-fixture-"));
  await cp(join(repoRoot, "public"), join(fixtureRoot, "public"), { recursive: true });
  await cp(join(repoRoot, "index.html"), join(fixtureRoot, "index.html"));
  if (withDist) {
    await cp(join(fixtureRoot, "public"), join(fixtureRoot, "dist"), { recursive: true });
    await cp(join(fixtureRoot, "index.html"), join(fixtureRoot, "dist", "index.html"));
  }
  return fixtureRoot;
}

test("source-only verification passes before a build", async () => {
  const fixtureRoot = await createFixture();
  try {
    await verifyPagesStatic({ rootDir: fixtureRoot });
  } finally {
    await rm(fixtureRoot, { recursive: true, force: true });
  }
});

test("required dist output is rejected when missing", async () => {
  const fixtureRoot = await createFixture({ withDist: true });
  try {
    await rm(join(fixtureRoot, "dist", "404.html"));
    await assert.rejects(
      verifyPagesStatic({ rootDir: fixtureRoot, requireDist: true }),
      /dist\/ is missing required 404\.html/,
    );
  } finally {
    await rm(fixtureRoot, { recursive: true, force: true });
  }
});

test("stale dist output is rejected", async () => {
  const fixtureRoot = await createFixture({ withDist: true });
  try {
    await writeFile(join(fixtureRoot, "dist", "robots.txt"), "User-agent: *\nDisallow: /stale\n");
    await assert.rejects(
      verifyPagesStatic({ rootDir: fixtureRoot, requireDist: true }),
      /dist\/robots\.txt is missing or stale/,
    );
  } finally {
    await rm(fixtureRoot, { recursive: true, force: true });
  }
});

test("public CLI contract rejects a fixture with no dist", async () => {
  const fixtureRoot = await createFixture();
  try {
    const result = spawnSync(
      process.execPath,
      [join(repoRoot, "scripts", "verify-pages-static.mjs"), "--root-dir", fixtureRoot, "--require-dist"],
      { encoding: "utf8" },
    );
    assert.notEqual(result.status, 0, "--require-dist must fail when dist is absent");
    assert.match(`${result.stdout}\n${result.stderr}`, /dist\/ is missing built index\.html/);
  } finally {
    await rm(fixtureRoot, { recursive: true, force: true });
  }
});
