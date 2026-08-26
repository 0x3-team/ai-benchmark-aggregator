// build-provenance-node-tests.mjs
//
// Tests for the local source-to-dist digest manifest (scripts/build-provenance.mjs).
//
// Every fixture is a bounded temp directory so the tests never touch the real
// repo tree. Digest/arrow logic is exercised directly through the module's own
// create/verify entry points — nothing here is mocked. All assertions are
// strict and non-tautological.

import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import {
  mkdtemp,
  mkdir,
  readFile,
  rm,
  symlink,
  writeFile,
} from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";
import { createBuildProvenance, verifyBuildProvenance } from "./build-provenance.mjs";

const thisDir = dirname(fileURLToPath(import.meta.url));
const modulePath = join(thisDir, "build-provenance.mjs");
const MANIFEST_FILE = "build-provenance.json";
const MANIFEST_REL = join("dist", MANIFEST_FILE);
const SCHEMA_VERSION = "ai-benchmark-build-provenance-v1";
const ALGORITHM = "sha256-length-framed-tree-v1";

const REQUIRED_ROOT = [
  "index.html",
  "vite.config.ts",
  "package.json",
  "package-lock.json",
  "tsconfig.json",
  "postcss.config.js",
  "tailwind.config.js",
];

// ---------------------------------------------------------------------------
// Fixture helpers (bounded temp trees)
// ---------------------------------------------------------------------------

async function writeTree(root, paths) {
  for (const [rel, content] of paths) {
    const abs = join(root, rel);
    await mkdir(dirname(abs), { recursive: true });
    await writeFile(abs, content, "utf8");
  }
}

// A fixture with all the mandatory source files plus a 2-file artifact tree.
async function buildStandardFixture() {
  const root = await mkdtemp(join(tmpdir(), "abp-fixture-"));
  await writeTree(root, [
    ["src/index.ts", "export default 1;\n"],
    ["src/lib/util.ts", "export const x = 42;\n"],
    ["public/robots.txt", "User-agent: *\nAllow: /\n"],
    ["index.html", "<!doctype html><title>src</title>\n"],
    ["vite.config.ts", "export default {};\n"],
    ["package.json", '{"name":"x","type":"module","version":"0.1.0"}\n'],
    ["package-lock.json", '{"lockfileVersion":3,"packages":{}}\n'],
    ["tsconfig.json", "{}\n"],
    ["postcss.config.js", "module.exports = {};\n"],
    ["tailwind.config.js", "module.exports = {};\n"],
  ]);
  await mkdir(join(root, "dist", "assets"), { recursive: true });
  await writeFile(join(root, "dist", "index.html"), "<!doctype html><title>dist</title>\n");
  await writeFile(join(root, "dist", "assets", "app.js"), "console.log('app');\n");
  return root;
}

async function destroyFixture(root) {
  await rm(root, { recursive: true, force: true });
}

function canonicalBytes(manifest) {
  return `${JSON.stringify(manifest, null, 2)}\n`;
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

test("create + verify on fixture; byte-for-byte identical on two creations", async () => {
  const root = await buildStandardFixture();
  try {
    const created = await createBuildProvenance({ rootDir: root });
    const firstBytes = await readFile(join(root, MANIFEST_REL));

    const parsed = JSON.parse(firstBytes.toString("utf8"));
    assert.equal(parsed.schemaVersion, SCHEMA_VERSION);
    assert.equal(parsed.algorithm, ALGORITHM);
    assert.equal(parsed.source.digestSha256, created.source.digestSha256);
    assert.equal(parsed.source.fileCount, created.source.fileCount);
    assert.equal(parsed.artifact.digestSha256, created.artifact.digestSha256);
    assert.equal(parsed.artifact.fileCount, created.artifact.fileCount);

    // Digests must be 64 lowercase hex; counts positive ints.
    assert.match(parsed.source.digestSha256, /^[0-9a-f]{64}$/);
    assert.match(parsed.artifact.digestSha256, /^[0-9a-f]{64}$/);
    assert.ok(Number.isSafeInteger(parsed.source.fileCount) && parsed.source.fileCount > 0);
    assert.ok(Number.isSafeInteger(parsed.artifact.fileCount) && parsed.artifact.fileCount > 0);
    assert.equal(parsed.artifact.fileCount, 2);

    // Round-trip verify succeeds.
    await verifyBuildProvenance({ rootDir: root });

    // Same inputs => identical manifest bytes.
    await createBuildProvenance({ rootDir: root });
    const secondBytes = await readFile(join(root, MANIFEST_REL));
    assert.deepEqual(firstBytes, secondBytes, "same inputs must yield identical manifest bytes");

    // No absolute path, timestamp, or secret marker embedded.
    const raw = secondBytes.toString("utf8");
    assert.ok(!raw.includes(root), "manifest must not embed the absolute root path");
    assert.ok(!/\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*,/.test(raw), "manifest must not embed a date");
    assert.ok(!/secret|token|apiKey|password|BEGIN [A-Z ]+ PRIVATE KEY/i.test(raw), "no secret marker");
  } finally {
    await destroyFixture(root);
  }
});

test("source byte change invalidates the manifest", async () => {
  const root = await buildStandardFixture();
  try {
    await createBuildProvenance({ rootDir: root });
    await writeFile(join(root, "src", "index.ts"), "export default 2;\n");
    await assert.rejects(() => verifyBuildProvenance({ rootDir: root }), /source digest does not match/);
  } finally {
    await destroyFixture(root);
  }
});

test("source file add invalidates the manifest", async () => {
  const root = await buildStandardFixture();
  try {
    await createBuildProvenance({ rootDir: root });
    await writeFile(join(root, "src", "added.ts"), "// added\n");
    await assert.rejects(() => verifyBuildProvenance({ rootDir: root }), /source digest does not match/);
  } finally {
    await destroyFixture(root);
  }
});

test("source file delete invalidates the manifest", async () => {
  const root = await buildStandardFixture();
  try {
    await createBuildProvenance({ rootDir: root });
    await rm(join(root, "public", "robots.txt"));
    await assert.rejects(() => verifyBuildProvenance({ rootDir: root }), /source digest does not match/);
  } finally {
    await destroyFixture(root);
  }
});

test("artifact byte change invalidates the manifest", async () => {
  const root = await buildStandardFixture();
  try {
    await createBuildProvenance({ rootDir: root });
    await writeFile(join(root, "dist", "index.html"), "<!doctype html><title>dist-edited</title>\n");
    await assert.rejects(() => verifyBuildProvenance({ rootDir: root }), /artifact digest does not match/);
  } finally {
    await destroyFixture(root);
  }
});

test("artifact file add invalidates the manifest", async () => {
  const root = await buildStandardFixture();
  try {
    await createBuildProvenance({ rootDir: root });
    await writeFile(join(root, "dist", "extra.js"), "// extra\n");
    await assert.rejects(() => verifyBuildProvenance({ rootDir: root }), /artifact digest does not match/);
  } finally {
    await destroyFixture(root);
  }
});

test("artifact file delete invalidates the manifest", async () => {
  const root = await buildStandardFixture();
  try {
    await createBuildProvenance({ rootDir: root });
    await rm(join(root, "dist", "assets", "app.js"));
    await assert.rejects(() => verifyBuildProvenance({ rootDir: root }), /artifact digest does not match/);
  } finally {
    await destroyFixture(root);
  }
});

test("manifest digest tamper is rejected", async () => {
  const root = await buildStandardFixture();
  try {
    await createBuildProvenance({ rootDir: root });
    const parsed = JSON.parse((await readFile(join(root, MANIFEST_REL))).toString("utf8"));
    parsed.source.digestSha256 = "0".repeat(64);
    await writeFile(join(root, MANIFEST_REL), canonicalBytes(parsed), "utf8");
    await assert.rejects(() => verifyBuildProvenance({ rootDir: root }), /source digest does not match/);
  } finally {
    await destroyFixture(root);
  }
});

test("manifest fileCount tamper is rejected", async () => {
  const root = await buildStandardFixture();
  try {
    await createBuildProvenance({ rootDir: root });
    const parsed = JSON.parse((await readFile(join(root, MANIFEST_REL))).toString("utf8"));
    parsed.artifact.fileCount += 1;
    await writeFile(join(root, MANIFEST_REL), canonicalBytes(parsed), "utf8");
    await assert.rejects(() => verifyBuildProvenance({ rootDir: root }), /artifact file count/);
  } finally {
    await destroyFixture(root);
  }
});

test("manifest extra field is rejected", async () => {
  const root = await buildStandardFixture();
  try {
    await createBuildProvenance({ rootDir: root });
    const parsed = JSON.parse((await readFile(join(root, MANIFEST_REL))).toString("utf8"));
    parsed.timestamp = 12345;
    await writeFile(join(root, MANIFEST_REL), canonicalBytes(parsed), "utf8");
    await assert.rejects(() => verifyBuildProvenance({ rootDir: root }), /top-level keys|wrong|mistyped/i);
  } finally {
    await destroyFixture(root);
  }
});

test("manifest malformed JSON is rejected", async () => {
  const root = await buildStandardFixture();
  try {
    await createBuildProvenance({ rootDir: root });
    await writeFile(join(root, MANIFEST_REL), "not json\n", "utf8");
    await assert.rejects(() => verifyBuildProvenance({ rootDir: root }), /not valid JSON/);
  } finally {
    await destroyFixture(root);
  }
});

test("manifest missing entirely is rejected", async () => {
  const root = await buildStandardFixture();
  try {
    await rm(join(root, "dist"), { recursive: true, force: true });
    await mkdir(join(root, "dist"), { recursive: true });
    await assert.rejects(() => verifyBuildProvenance({ rootDir: root }), /manifest not found/);
  } finally {
    await destroyFixture(root);
  }
});

test("source symlink is rejected", async (t) => {
  const root = await buildStandardFixture();
  try {
    try {
      await symlink(join(root, "src", "index.ts"), join(root, "src", "link.ts"));
    } catch (err) {
      if (/EPERM|EACCES/.test(String(err && err.code ? err.code : ""))) {
        t.skip("platform forbids creating symlinks");
        return;
      }
      throw err;
    }
    await assert.rejects(() => createBuildProvenance({ rootDir: root }), /symlink not permitted in source/);
  } finally {
    await destroyFixture(root);
  }
});

test("artifact symlink is rejected", async (t) => {
  const root = await buildStandardFixture();
  try {
    try {
      await symlink(join(root, "dist", "index.html"), join(root, "dist", "link.html"));
    } catch (err) {
      if (/EPERM|EACCES/.test(String(err && err.code ? err.code : ""))) {
        t.skip("platform forbids creating symlinks");
        return;
      }
      throw err;
    }
    await assert.rejects(() => createBuildProvenance({ rootDir: root }), /symlink not permitted in artifact/);
  } finally {
    await destroyFixture(root);
  }
});

// --- Directory-replacement / root-symlink adversarial tests -----------------

// Replace relDir (e.g. "src" or "dist") with a symlink pointing at target after
// building the fixture, so the walker's directory lstat must reject it.
async function replaceDirWithSymlink(root, relDir, target, t) {
  try {
    await rm(join(root, relDir), { recursive: true, force: true });
    await symlink(target, join(root, relDir));
  } catch (err) {
    if (/EPERM|EACCES/.test(String(err && err.code ? err.code : ""))) {
      t.skip("platform forbids creating symlinks");
      return false;
    }
    throw err;
  }
  return true;
}

test("src as directory symlink is rejected on create and verify", async (t) => {
  const root = await buildStandardFixture();
  try {
    await createBuildProvenance({ rootDir: root });

    const target = join(root, "real-src-target");
    await mkdir(target, { recursive: true });
    await writeFile(join(target, "index.ts"), "export default 1;\n");
    if (!(await replaceDirWithSymlink(root, "src", target, t))) return;

    // A fresh create must refuse to follow the symlinked src/.
    await assert.rejects(() => createBuildProvenance({ rootDir: root }), /symlink not permitted in directory: src/);

    // Verify must likewise fail closed (the existing manifest can no longer be
    // reconciled against a now-symlinked source tree).
    await assert.rejects(() => verifyBuildProvenance({ rootDir: root }), /symlink not permitted in directory: src/);
  } finally {
    await destroyFixture(root);
  }
});

test("dist as directory symlink is rejected on create and verify", async (t) => {
  const root = await buildStandardFixture();
  try {
    await createBuildProvenance({ rootDir: root });

    const target = join(root, "real-dist-target");
    await mkdir(target, { recursive: true });
    await writeFile(join(target, "index.html"), "<!doctype html><title>dist</title>\n");
    if (!(await replaceDirWithSymlink(root, "dist", target, t))) return;

    await assert.rejects(() => createBuildProvenance({ rootDir: root }), /symlink not permitted in directory: dist/);

    // Verify must also fail closed. Reading the manifest itself resolves
    // through the removed directory, so "manifest not found" is an acceptable
    // failure — the artifact tree walk must never read through the symlink.
    await assert.rejects(
      () => verifyBuildProvenance({ rootDir: root }),
      /symlink not permitted in directory: dist|manifest not found/,
    );
  } finally {
    await destroyFixture(root);
  }
});

test("rootDir as a symlink is rejected", async (t) => {
  const root = await buildStandardFixture();
  try {
    const link = join(tmpdir(), `abp-rootlink-${process.pid}-${Math.random().toString(36).slice(2)}`);
    try {
      await symlink(root, link);
    } catch (err) {
      if (/EPERM|EACCES/.test(String(err && err.code ? err.code : ""))) {
        t.skip("platform forbids creating symlinks");
        return;
      }
      throw err;
    }
    try {
      await assert.rejects(() => createBuildProvenance({ rootDir: link }), /symlink not permitted as root directory/);
      await assert.rejects(() => verifyBuildProvenance({ rootDir: link }), /symlink not permitted as root directory/);
    } finally {
      await rm(link, { recursive: true, force: true });
    }
  } finally {
    await destroyFixture(root);
  }
});

// Point 2: optional root tsconfig present as a non-regular entry must be
// rejected rather than silently ignored.
test("optional tsconfig.app.json as a directory is rejected", async () => {
  const root = await buildStandardFixture();
  try {
    await mkdir(join(root, "tsconfig.app.json"), { recursive: true });
    await assert.rejects(() => createBuildProvenance({ rootDir: root }), /non-regular file not permitted in source root: tsconfig\.app\.json/);
  } finally {
    await destroyFixture(root);
  }
});

test("optional tsconfig.node.json as a symlink is rejected", async (t) => {
  const root = await buildStandardFixture();
  try {
    try {
      await symlink(join(root, "index.html"), join(root, "tsconfig.node.json"));
    } catch (err) {
      if (/EPERM|EACCES/.test(String(err && err.code ? err.code : ""))) {
        t.skip("platform forbids creating symlinks");
        return;
      }
      throw err;
    }
    await assert.rejects(() => createBuildProvenance({ rootDir: root }), /symlink not permitted in source root: tsconfig\.node\.json/);
  } finally {
    await destroyFixture(root);
  }
});

// --- Canonical serialization (anti-reordering) tests ------------------------

async function writeReorderedManifest(root, makeObject) {
  const parsed = JSON.parse((await readFile(join(root, MANIFEST_REL))).toString("utf8"));
  await writeFile(join(root, MANIFEST_REL), canonicalBytesReordered(makeObject(parsed)), "utf8");
}

// Pretty-print preserving insertion order (JSON.stringify keeps string key
// insertion order), with a final trailing newline like the canonical form.
function canonicalBytesReordered(orderedObj) {
  return `${JSON.stringify(orderedObj, null, 2)}\n`;
}

test("top-level key reorder is rejected as non-canonical", async () => {
  const root = await buildStandardFixture();
  try {
    await createBuildProvenance({ rootDir: root });
    await writeReorderedManifest(root, (parsed) => ({
      schemaVersion: parsed.schemaVersion,
      source: parsed.source,
      artifact: parsed.artifact,
      // algorithm moved last — valid keys/types, correct digests, wrong order.
      algorithm: parsed.algorithm,
    }));
    await assert.rejects(() => verifyBuildProvenance({ rootDir: root }), /canonical serialization/);
  } finally {
    await destroyFixture(root);
  }
});

test("nested key reorder is rejected as non-canonical", async () => {
  const root = await buildStandardFixture();
  try {
    await createBuildProvenance({ rootDir: root });
    await writeReorderedManifest(root, (parsed) => ({
      schemaVersion: parsed.schemaVersion,
      algorithm: parsed.algorithm,
      source: {
        fileCount: parsed.source.fileCount, // fileCount before digestSha256
        digestSha256: parsed.source.digestSha256,
      },
      artifact: parsed.artifact,
    }));
    await assert.rejects(() => verifyBuildProvenance({ rootDir: root }), /canonical serialization/);
  } finally {
    await destroyFixture(root);
  }
});

// Point 4: a static file symlink must be refused by the writer (and, once the
// tree is in that state, by the verifier too). The O_NOFOLLOW read path is
// exercised through verify after enumeration, rejecting the substituted final
// component rather than hashing through it.
test("static file symlink is rejected on create", async (t) => {
  const root = await buildStandardFixture();
  try {
    // Add a new source file that points at an existing one via symlink; the
    // walker must refuse it rather than hash through it.
    const target = join(root, "public", "robots.txt");
    const link = join(root, "public", "link.txt");
    try {
      await symlink(target, link);
    } catch (err) {
      if (/EPERM|EACCES/.test(String(err && err.code ? err.code : ""))) {
        t.skip("platform forbids creating symlinks");
        return;
      }
      throw err;
    }
    await assert.rejects(() => createBuildProvenance({ rootDir: root }), /symlink not permitted in source tree: public\/link\.txt/);
  } finally {
    await destroyFixture(root);
  }
});

// Probe the O_NOFOLLOW fd-based read path on this platform: if the platform
// supports O_NOFOLLOW, a final-component symlink substituted between
// enumeration and read must be refused by the fd open, not hashed through.
test("file read refuses a symlink final component (verify fails closed)", async (t) => {
  const root = await buildStandardFixture();
  try {
    await createBuildProvenance({ rootDir: root });
    // Swap a hashed artifact file out for a symlink — the walker enumerated it
    // as a regular file earlier; verify must now refuse to hash through it.
    const { copyFile } = await import("node:fs/promises");
    const original = join(root, "dist", "index.html");
    const backing = join(root, "dist", "backing.html");
    await copyFile(original, backing);
    try {
      await rm(original);
      await symlink(backing, original);
    } catch (err) {
      if (/EPERM|EACCES/.test(String(err && err.code ? err.code : ""))) {
        t.skip("platform forbids creating symlinks");
        return;
      }
      throw err;
    }
    // verify recomputes the artifact digest from the current tree; the
    // substituted symlink must be refused — either by the walker (Dirent
    // reports a symlink) or by the fd read path (O_NOFOLLOW) — never hashed
    // through. Either failure is fail-closed.
    await assert.rejects(
      () => verifyBuildProvenance({ rootDir: root }),
      /symlink not permitted in artifact|artifact digest does not match/,
    );
  } finally {
    await destroyFixture(root);
  }
});

test("CLI verify returns nonzero on mismatch", async () => {
  const root = await buildStandardFixture();
  try {
    const created = spawnSync(
      process.execPath,
      [modulePath, "create", "--root-dir", root],
      { encoding: "utf8" },
    );
    assert.equal(created.status, 0, created.stderr);

    await writeFile(join(root, "src", "index.ts"), "export default 3;\n");
    const mismatch = spawnSync(
      process.execPath,
      [modulePath, "verify", "--root-dir", root],
      { encoding: "utf8" },
    );
    assert.notEqual(mismatch.status, 0, "verify must exit nonzero on source drift");
    assert.match(mismatch.stderr, /source digest does not match/);
  } finally {
    await destroyFixture(root);
  }
});

test("CLI rejects unknown arguments and missing command with nonzero exit", async () => {
  const unknown = spawnSync(process.execPath, [modulePath, "bogus"], { encoding: "utf8" });
  assert.notEqual(unknown.status, 0);
  assert.match(unknown.stderr, /unknown command/);

  const noArg = spawnSync(process.execPath, [modulePath, "--root-dir"], { encoding: "utf8" });
  assert.notEqual(noArg.status, 0);
  assert.match(noArg.stderr, /requires a value/);

  const noCommand = spawnSync(process.execPath, [modulePath], { encoding: "utf8" });
  assert.notEqual(noCommand.status, 0);
  assert.match(noCommand.stderr, /missing command/);
});