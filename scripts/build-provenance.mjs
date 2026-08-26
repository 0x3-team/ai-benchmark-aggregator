// build-provenance.mjs
//
// Local source-to-dist digest manifest. F13A.
//
// Builds a content-addressed manifest (dist/build-provenance.json) recording a
// SHA-256 "tree" digest over the source set (src/, public/, mandatory root
// files) and the artifact set (everything under dist/ except the manifest
// itself). The manifest is a faithful, deterministic fingerprint of "this
// source produced this dist" with no embedded absolute paths, timestamps,
// environment, branch, commit, secrets, or signature/signing claims.
//
// Algorithm: sha256-length-framed-tree-v1.
//   treeDigest = H(fixedDomainMarker
//                 || for each (path, bytes) sorted by UTF-8 byte order:
//                     u32BE pathByteLen || pathBytes
//                     || u64BE fileByteLen || fileBytes)
//
// Node ESM, Node built-ins only. No dependency on the host environment except
// an existing directory tree to walk.

import { constants } from "node:fs";
import { open, lstat, mkdir, readFile, readdir, rename, rm, writeFile } from "node:fs/promises";
import { createHash, randomBytes, timingSafeEqual } from "node:crypto";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const SCHEMA_VERSION = "ai-benchmark-build-provenance-v1";
const ALGORITHM = "sha256-length-framed-tree-v1";
const MANIFEST_FILE = "build-provenance.json";
const SCHEMA_DOMAIN = "ai-benchmark-sha256-length-framed-tree-v1";

// Root files required to be present in the source set. The two tsconfig project
// files are only included from the root when they exist.
const REQUIRED_ROOT_FILES = [
  "index.html",
  "vite.config.ts",
  "package.json",
  "package-lock.json",
  "tsconfig.json",
  "postcss.config.js",
  "tailwind.config.js",
];
const OPTIONAL_ROOT_FILES = ["tsconfig.app.json", "tsconfig.node.json"];

const DEFAULT_ROOT_DIR = resolve(dirname(fileURLToPath(import.meta.url)), "..");

const HEX_64 = /^[0-9a-f]{64}$/;
// Only used for reading through a file descriptor when O_NOFOLLOW exists.
const O_NOFOLLOW = typeof constants.O_NOFOLLOW === "number" ? constants.O_NOFOLLOW : 0;
const O_RDONLY = typeof constants.O_RDONLY === "number" ? constants.O_RDONLY : 0;

// ---------------------------------------------------------------------------
// Path helpers
// ---------------------------------------------------------------------------

// Sort root-relative POSIX paths by UTF-8 byte order, deterministically.
function comparePosixUtf8(a, b) {
  const ba = Buffer.from(a, "utf8");
  const bb = Buffer.from(b, "utf8");
  const len = Math.min(ba.length, bb.length);
  for (let i = 0; i < len; i++) {
    if (ba[i] !== bb[i]) return ba[i] - bb[i];
  }
  return ba.length - bb.length;
}

// ---------------------------------------------------------------------------
// Tree walking (rejects symlinks and non-regular entries, never follows them)
// ---------------------------------------------------------------------------

// Reject rootDir itself if it is a symlink or not a real directory.
async function assertRootDir(rootDir) {
  let st;
  try {
    st = await lstat(rootDir);
  } catch (err) {
    if (err && err.code === "ENOENT") {
      throw new Error(`root directory is missing: ${rootDir}`);
    }
    throw err;
  }
  if (st.isSymbolicLink()) {
    throw new Error(`symlink not permitted as root directory: ${rootDir}`);
  }
  if (!st.isDirectory()) {
    throw new Error(`root path is not a directory: ${rootDir}`);
  }
}

// Reject the exact path (via lstat: no follow) if it is a symlink or not a
// real directory. This is required before every readdir so a symlinked src/,
// public/, dist/, or recursive subdirectory is never followed.
async function assertRealDirectory(rootDir, relDir) {
  const abs = join(rootDir, relDir);
  let st;
  try {
    st = await lstat(abs);
  } catch (err) {
    if (err && err.code === "ENOENT") {
      throw new Error(`required directory is missing: ${relDir}`);
    }
    throw err;
  }
  if (st.isSymbolicLink()) {
    throw new Error(`symlink not permitted in directory: ${relDir}`);
  }
  if (!st.isDirectory()) {
    throw new Error(`non-directory not permitted: ${relDir}`);
  }
}

async function assertRegularFile(rootDir, relPath, context) {
  let st;
  try {
    st = await lstat(join(rootDir, relPath));
  } catch (err) {
    if (err && err.code === "ENOENT") {
      throw new Error(`required ${context} file is missing: ${relPath}`);
    }
    throw err;
  }
  if (st.isSymbolicLink()) {
    throw new Error(`symlink not permitted in ${context}: ${relPath}`);
  }
  if (!st.isFile()) {
    throw new Error(`non-regular file not permitted in ${context}: ${relPath}`);
  }
}

// Collect every recursive regular file under rootDir/relDir as POSIX paths.
async function walkRegularFiles(rootDir, relDir, context) {
  await assertRealDirectory(rootDir, relDir);
  const abs = join(rootDir, relDir);
  let entries;
  try {
    entries = await readdir(abs, { withFileTypes: true });
  } catch (err) {
    if (err && err.code === "ENOENT") {
      throw new Error(`required directory is missing: ${relDir}`);
    }
    throw err;
  }
  const found = [];
  for (const entry of entries) {
    const rel = relDir === "" ? entry.name : `${relDir}/${entry.name}`;
    if (entry.isSymbolicLink()) {
      throw new Error(`symlink not permitted in ${context}: ${rel}`);
    }
    if (entry.isDirectory()) {
      found.push(...(await walkRegularFiles(rootDir, rel, context)));
    } else if (entry.isFile()) {
      found.push(rel);
    } else {
      throw new Error(`non-regular entry not permitted in ${context}: ${rel}`);
    }
  }
  return found;
}

async function computeSourceSet(rootDir) {
  const paths = [];
  for (const dir of ["src", "public"]) {
    paths.push(...(await walkRegularFiles(rootDir, dir, "source tree")));
  }
  for (const file of REQUIRED_ROOT_FILES) {
    await assertRegularFile(rootDir, file, "source root");
    paths.push(file);
  }
  for (const file of OPTIONAL_ROOT_FILES) {
    let st;
    try {
      st = await lstat(join(rootDir, file));
    } catch (err) {
      if (err && err.code === "ENOENT") continue; // optional, absent
      throw err;
    }
    if (st.isSymbolicLink()) {
      throw new Error(`symlink not permitted in source root: ${file}`);
    }
    if (!st.isFile()) {
      throw new Error(`non-regular file not permitted in source root: ${file}`);
    }
    paths.push(file);
  }
  return paths.sort(comparePosixUtf8);
}

async function computeArtifactSet(rootDir) {
  const paths = (await walkRegularFiles(rootDir, "dist", "artifact tree")).filter(
    (rel) => rel !== `dist/${MANIFEST_FILE}`,
  );
  return paths.sort(comparePosixUtf8);
}

// ---------------------------------------------------------------------------
// File reads (O_NOFOLLOW where available, then fstat + read from the fd)
// ---------------------------------------------------------------------------

// Read a file's bytes for hashing, refusing to follow a final-component
// symlink. On platforms providing O_NOFOLLOW the file is opened through a
// descriptor with that flag, fstat'ed to confirm it is a regular file, and
// read from the descriptor, so a symlink substituted between enumeration and
// read is rejected. This is defense-in-depth against TOCTOU substitution; it
// does not claim immunity to concurrent renames of whole directories.
async function readRegularFileBytes(rootDir, relPath) {
  const abs = join(rootDir, relPath);
  if (O_NOFOLLOW !== 0) {
    let handle;
    try {
      handle = await open(abs, O_RDONLY | O_NOFOLLOW);
      const st = await handle.stat();
      if (!st.isFile()) {
        throw new Error(`non-regular file not permitted: ${relPath}`);
      }
      return await handle.readFile();
    } catch (err) {
      if (err && (err.code === "ELOOP" || err.code === "EMLOOP")) {
        throw new Error(`symlink not permitted: ${relPath}`);
      }
      throw err;
    } finally {
      if (handle) {
        await handle.close().catch(() => {});
      }
    }
  }
  // Fallback for platforms without O_NOFOLLOW: the walker already lstat-rejects
  // symlink entries before we reach here.
  return await readFile(abs);
}

// ---------------------------------------------------------------------------
// Tree hashing
// ---------------------------------------------------------------------------

async function hashTree(rootDir, relPaths) {
  const hash = createHash("sha256");
  hash.update(SCHEMA_DOMAIN, "utf8");
  for (const rel of relPaths) {
    const pathBytes = Buffer.from(rel, "utf8");
    const pathLen = Buffer.allocUnsafe(4);
    pathLen.writeUInt32BE(pathBytes.length, 0);
    hash.update(pathLen);
    hash.update(pathBytes);

    const fileBytes = await readRegularFileBytes(rootDir, rel);
    const fileLen = Buffer.allocUnsafe(8);
    fileLen.writeBigUInt64BE(BigInt(fileBytes.length), 0);
    hash.update(fileLen);
    hash.update(fileBytes);
  }
  return hash.digest("hex");
}

// ---------------------------------------------------------------------------
// Manifest creation
// ---------------------------------------------------------------------------

function buildManifest(sourceDigest, sourceFileCount, artifactDigest, artifactFileCount) {
  return Buffer.from(canonicalManifestString({
    schemaVersion: SCHEMA_VERSION,
    algorithm: ALGORITHM,
    source: { digestSha256: sourceDigest, fileCount: sourceFileCount },
    artifact: { digestSha256: artifactDigest, fileCount: artifactFileCount },
  }), "utf8");
}

async function atomicWrite(distDir, bytes) {
  await mkdir(distDir, { recursive: true });
  const target = join(distDir, MANIFEST_FILE);
  const tmp = join(
    distDir,
    `${MANIFEST_FILE}.tmp.${process.pid}.${randomBytes(4).toString("hex")}`,
  );
  try {
    await writeFile(tmp, bytes, { flag: "wx" });
    await rename(tmp, target);
  } catch (err) {
    await rm(tmp, { force: true }).catch(() => {});
    throw err;
  }
}

export async function createBuildProvenance({ rootDir }) {
  const base = resolve(rootDir);
  await assertRootDir(base);
  const sourcePaths = await computeSourceSet(base);
  const artifactPaths = await computeArtifactSet(base);
  if (artifactPaths.length === 0) {
    throw new Error("artifact set is empty: dist has no files to fingerprint");
  }

  const sourceDigest = await hashTree(base, sourcePaths);
  const artifactDigest = await hashTree(base, artifactPaths);

  const manifest = buildManifest(
    sourceDigest,
    sourcePaths.length,
    artifactDigest,
    artifactPaths.length,
  );
  await atomicWrite(join(base, "dist"), manifest);
  return {
    schemaVersion: SCHEMA_VERSION,
    algorithm: ALGORITHM,
    source: { digestSha256: sourceDigest, fileCount: sourcePaths.length },
    artifact: { digestSha256: artifactDigest, fileCount: artifactPaths.length },
  };
}

// ---------------------------------------------------------------------------
// Manifest parsing / validation
// ---------------------------------------------------------------------------

function hasExactKeys(object, keys) {
  const own = Object.keys(object);
  if (own.length !== keys.length) return false;
  return keys.every((k) => Object.prototype.hasOwnProperty.call(object, k));
}

// Serialize in the exact fixed schema order shared by the creation serializer.
function canonicalManifestString(parsed) {
  const ordered = {
    schemaVersion: parsed.schemaVersion,
    algorithm: parsed.algorithm,
    source: {
      digestSha256: parsed.source.digestSha256,
      fileCount: parsed.source.fileCount,
    },
    artifact: {
      digestSha256: parsed.artifact.digestSha256,
      fileCount: parsed.artifact.fileCount,
    },
  };
  return `${JSON.stringify(ordered, null, 2)}\n`;
}

const TOP_KEYS = Object.freeze(["schemaVersion", "algorithm", "source", "artifact"]);
const NODE_KEYS = Object.freeze(["digestSha256", "fileCount"]);

function parseAndValidateManifest(rawBytes) {
  const rawString = Buffer.isBuffer(rawBytes) || rawBytes instanceof Uint8Array
    ? Buffer.from(rawBytes).toString("utf8")
    : rawBytes;

  let parsed;
  try {
    parsed = JSON.parse(rawString);
  } catch {
    throw new Error("manifest is not valid JSON");
  }
  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
    throw new Error("manifest root must be a JSON object");
  }

  // Validate exact keys and types FIRST (set membership, not order).
  if (!hasExactKeys(parsed, TOP_KEYS, "topLevel")) {
    throw new Error("manifest has missing or unexpected top-level keys");
  }
  if (parsed.schemaVersion !== SCHEMA_VERSION || typeof parsed.schemaVersion !== "string") {
    throw new Error("manifest schemaVersion is wrong or mistyped");
  }
  if (parsed.algorithm !== ALGORITHM || typeof parsed.algorithm !== "string") {
    throw new Error("manifest algorithm is wrong or mistyped");
  }
  for (const key of ["source", "artifact"]) {
    const node = parsed[key];
    if (typeof node !== "object" || node === null || Array.isArray(node)) {
      throw new Error(`manifest.${key} must be an object`);
    }
    if (!hasExactKeys(node, NODE_KEYS, key)) {
      throw new Error(`manifest.${key} has missing or unexpected keys`);
    }
    if (typeof node.digestSha256 !== "string" || !HEX_64.test(node.digestSha256)) {
      throw new Error(`manifest.${key}.digestSha256 must be 64 lowercase hex`);
    }
    if (
      typeof node.fileCount !== "number" ||
      !Number.isSafeInteger(node.fileCount) ||
      node.fileCount <= 0
    ) {
      throw new Error(`manifest.${key}.fileCount must be a positive integer`);
    }
  }

  // Canonical-bytes requirement: the serialized bytes must be exactly the
  // pretty-printed fixed-order form (ignoring handed-in key insertion order).
  if (rawString !== canonicalManifestString(parsed)) {
    throw new Error("manifest bytes are not the canonical serialization");
  }
  return parsed;
}

function constantTimeEqualHex(a, b) {
  if (typeof a !== "string" || typeof b !== "string" || a.length !== 64 || b.length !== 64) {
    return false;
  }
  try {
    return timingSafeEqual(Buffer.from(a, "hex"), Buffer.from(b, "hex"));
  } catch {
    return false;
  }
}

// ---------------------------------------------------------------------------
// Verification
// ---------------------------------------------------------------------------

export async function verifyBuildProvenance({ rootDir }) {
  const base = resolve(rootDir);
  await assertRootDir(base);
  const manifestPath = join(base, "dist", MANIFEST_FILE);
  let rawBytes;
  try {
    rawBytes = await readFile(manifestPath);
  } catch (err) {
    if (err && err.code === "ENOENT") {
      throw new Error(`manifest not found: ${manifestPath}`);
    }
    throw err;
  }

  const manifest = parseAndValidateManifest(rawBytes);

  const sourcePaths = await computeSourceSet(base);
  const artifactPaths = await computeArtifactSet(base);
  if (artifactPaths.length === 0) {
    throw new Error("artifact set is empty: dist has no files to fingerprint");
  }

  const sourceDigest = await hashTree(base, sourcePaths);
  const artifactDigest = await hashTree(base, artifactPaths);
  if (!constantTimeEqualHex(manifest.source.digestSha256, sourceDigest)) {
    throw new Error("source digest does not match manifest");
  }
  if (manifest.source.fileCount !== sourcePaths.length) {
    throw new Error(`source file count ${sourcePaths.length} does not match manifest ${manifest.source.fileCount}`);
  }
  if (!constantTimeEqualHex(manifest.artifact.digestSha256, artifactDigest)) {
    throw new Error("artifact digest does not match manifest");
  }
  if (manifest.artifact.fileCount !== artifactPaths.length) {
    throw new Error(`artifact file count ${artifactPaths.length} does not match manifest ${manifest.artifact.fileCount}`);
  }
  return {
    schemaVersion: manifest.schemaVersion,
    algorithm: manifest.algorithm,
    source: { digestSha256: manifest.source.digestSha256, fileCount: manifest.source.fileCount },
    artifact: { digestSha256: manifest.artifact.digestSha256, fileCount: manifest.artifact.fileCount },
  };
}

// ---------------------------------------------------------------------------
// CLI
// ---------------------------------------------------------------------------

function printError(message) {
  process.stderr.write(`build-provenance: error: ${message}\n`);
}

function spawnRootDir(argv) {
  let rootDir = DEFAULT_ROOT_DIR;
  let command = null;
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === "--root-dir") {
      if (i + 1 >= argv.length) {
        printError("--root-dir requires a value");
        return { error: true };
      }
      rootDir = resolve(argv[++i]);
    } else if (arg.startsWith("--root-dir=")) {
      const value = arg.slice("--root-dir=".length);
      if (value === "") {
        printError("--root-dir requires a non-empty value");
        return { error: true };
      }
      rootDir = resolve(value);
    } else if (arg.startsWith("-")) {
      printError(`unknown argument: ${arg}`);
      return { error: true };
    } else if (command === null) {
      command = arg;
    } else {
      printError(`unexpected argument: ${arg}`);
      return { error: true };
    }
  }
  if (command === null) {
    printError("missing command: expected 'create' or 'verify'");
    return { error: true };
  }
  return { rootDir, command, error: false };
}

async function main(argv) {
  const parsed = spawnRootDir(argv);
  if (parsed.error) return 2;

  try {
    if (parsed.command === "create") {
      const manifest = await createBuildProvenance({ rootDir: parsed.rootDir });
      process.stdout.write(
        `build-provenance: created ${MANIFEST_FILE}: ` +
          `source ${manifest.source.digestSha256} (${manifest.source.fileCount} files), ` +
          `artifact ${manifest.artifact.digestSha256} (${manifest.artifact.fileCount} files)\n`,
      );
      return 0;
    }
    if (parsed.command === "verify") {
      const manifest = await verifyBuildProvenance({ rootDir: parsed.rootDir });
      process.stdout.write(
        `build-provenance: verified ${MANIFEST_FILE}: ` +
          `source ${manifest.source.digestSha256} (${manifest.source.fileCount} files), ` +
          `artifact ${manifest.artifact.digestSha256} (${manifest.artifact.fileCount} files)\n`,
      );
      return 0;
    }
    printError(`unknown command: ${parsed.command}`);
    return 1;
  } catch (err) {
    printError(err && err.message ? err.message : String(err));
    return 1;
  }
}

// Only run the CLI when this module is the entry point.
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  process.exitCode = await main(process.argv.slice(2));
}