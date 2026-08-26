import assert from "node:assert/strict";
import { chmod, mkdtemp, rm, writeFile } from "node:fs/promises";
import { spawnSync } from "node:child_process";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const smokeScript = join(repoRoot, "scripts", "smoke-pages-deployment.sh");

async function createFixtureCurl() {
  const directory = await mkdtemp(join(tmpdir(), "pages-smoke-curl-"));
  const fixture = join(directory, "curl");
  await writeFile(
    fixture,
    `#!/usr/bin/env node
import { writeFile } from "node:fs/promises";
const args = process.argv.slice(2);
const valueAfter = (flag) => args[args.indexOf(flag) + 1];
const bodyPath = valueAfter("--output");
const headersPath = valueAfter("--dump-header");
const url = args.at(-1);
const path = new URL(url).pathname;
const hostname = new URL(url).hostname;
const junk = path.startsWith("/pages-smoke-not-found-");
const status = junk ? Number(process.env.FIXTURE_JUNK_STATUS ?? "404") : 200;
const contentType = path === "/" ? "text/html; charset=utf-8" : path === "/favicon.svg" ? "image/svg+xml" : path === "/social-preview.png" ? "image/png" : "text/plain; charset=utf-8";
const securityHeaders = [
  "x-content-type-options: nosniff",
  "referrer-policy: strict-origin-when-cross-origin",
  "x-frame-options: DENY",
  "permissions-policy: camera=()",
  "content-security-policy-report-only: default-src 'self'",
];
const earlyHints = process.env.FIXTURE_EARLY_HINTS === "1" ? [
  "HTTP/2 103",
  "content-type: text/html; charset=utf-8",
  ...securityHeaders,
].join("\\r\\n") + "\\r\\n\\r\\n" : "";
const finalHeaders = [
  "HTTP/2 " + status,
  "content-type: " + contentType,
  ...(process.env.FIXTURE_FINAL_SECURITY === "missing" ? [] : securityHeaders),
  ...(process.env.FIXTURE_ENFORCING_CSP === "1" && path === "/" ? ["content-security-policy: default-src 'self'"] : []),
  ...(path === "/" && process.env.FIXTURE_ROBOTS_NOINDEX === "1" ? ["x-robots-tag: noindex"] : []),
].join("\\r\\n") + "\\r\\n\\r\\n";
const body = path === "/" ? '<link rel="canonical" href="https://benchmark.0x3.dev/">' : path === "/robots.txt" ? "User-agent: *\\nAllow: /\\n" : path === "/favicon.svg" ? "<svg></svg>" : path === "/social-preview.png" ? Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]) : "not found";
await writeFile(headersPath, earlyHints + finalHeaders);
await writeFile(bodyPath, body);
process.stdout.write(String(status));
`,
  );
  await chmod(fixture, 0o755);
  return { directory, fixture };
}

async function runFixture({
  target = "https://fixture.pages.dev",
  junkStatus = 404,
  earlyHints = false,
  finalSecurity = true,
  enforcingCsp = false,
  robotsNoindex = target.endsWith(".pages.dev"),
} = {}) {
  const { directory, fixture } = await createFixtureCurl();
  try {
    return spawnSync("bash", [smokeScript, target], {
      encoding: "utf8",
      env: {
        ...process.env,
        PATH: `${directory}:${process.env.PATH}`,
        FIXTURE_EARLY_HINTS: earlyHints ? "1" : "0",
        FIXTURE_FINAL_SECURITY: finalSecurity ? "present" : "missing",
        FIXTURE_ENFORCING_CSP: enforcingCsp ? "1" : "0",
        FIXTURE_JUNK_STATUS: String(junkStatus),
        FIXTURE_ROBOTS_NOINDEX: robotsNoindex ? "1" : "0",
      },
    });
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
}

test("smoke accepts a 200 root and a real 404 junk route", async () => {
  const result = await runFixture();
  assert.equal(result.status, 0, `${result.stdout}\n${result.stderr}`);
});

test("smoke rejects a junk route that returns 200", async () => {
  const result = await runFixture({ junkStatus: 200 });
  assert.notEqual(result.status, 0);
  assert.match(`${result.stdout}\n${result.stderr}`, /Unknown route returned HTTP 200/);
});

test("smoke rejects compliant 103 headers when final response headers are missing", async () => {
  const result = await runFixture({ earlyHints: true, finalSecurity: false });
  assert.notEqual(result.status, 0);
  assert.match(`${result.stdout}\n${result.stderr}`, /Missing required header \^x-content-type-options/);
});

test("smoke rejects a Pages preview root response without final noindex", async () => {
  const result = await runFixture({ robotsNoindex: false });
  assert.notEqual(result.status, 0);
  assert.match(`${result.stdout}\n${result.stderr}`, /Missing required header \^x-robots-tag:\.\*noindex/);
});

test("smoke rejects noindex on the canonical root response", async () => {
  const result = await runFixture({ target: "https://benchmark.0x3.dev", robotsNoindex: true });
  assert.notEqual(result.status, 0);
  assert.match(`${result.stdout}\n${result.stderr}`, /Canonical host root response must not be noindexed/);
});

test("smoke rejects enforcing CSP before HOST-03 evidence", async () => {
  const result = await runFixture({ enforcingCsp: true });
  assert.notEqual(result.status, 0);
  assert.match(`${result.stdout}\n${result.stderr}`, /enforcing Content-Security-Policy before HOST-03 evidence/);
});
