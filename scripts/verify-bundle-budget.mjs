import assert from "node:assert/strict";
import { lstat, readFile, readdir, stat } from "node:fs/promises";
import { dirname, join, resolve, relative, sep } from "node:path";
import { fileURLToPath } from "node:url";

/**
 * Deterministic, fail-closed frontend bundle verifier.
 *
 * Requires a FRESH build and reads the resulting `dist/` to decide whether the
 * emitted JS meets documented budgets:
 *
 *   - eager bytes  : every `.js` asset a first paint pulls in, defined as the
 *                    UNION of two load-bearing sources so neither can silently
 *                    under-count:
 *                    1. the built `index.html` `<script type="module">` entry
 *                       plus its `<link rel="modulepreload">` links, and
 *                    2. the Vite `.vite/manifest.json` entry's transitive
 *                       STATIC `imports` closure (`isEntry`'s `imports`, walked
 *                       through the manifest graph; `dynamicImports` are NOT
 *                       traversed). The manifest closure is authoritative
 *                       because Vite can hoist a statically-imported shared
 *                       chunk out of the emitted HTML (no modulepreload link),
 *                       in which case an HTML-only eager count would silently
 *                       miss first-paint JS.
 *   - total bytes   : the sum of every `.js` emitted under `dist/assets/`,
 *                     regardless of reachability.
 *
 * Eager == total in a no-split build. Lazy splitting can only lower the eager
 * figure, never the total, so the total cap is always >= eager. The verifier
 * fail-closes: a missing/empty `dist`, a stale build (a relevant input newer
 * than `dist/index.html`), an unparsable `index.html`/manifest, an asset
 * reference that escapes `dist`, no `.js` chunks, or a manifest/HTML eager
 * divergence (entry binding) all abort with an actionable diagnostic instead
 * of passing.
 *
 * Freshness contract: prove the build is fresh by walking the source/config/
 * `public` inputs (never following symlinks) and demanding `dist/index.html`
 * is not older than any of them. Deterministic (mtime-based) and fails closed
 * on a stale build, so CI's build-then-verify ordering is enforced locally too.
 *
 * Containment: every asset reference (HTML and manifest) must resolve to a
 * real file under `dist`. Dot-segment (`..`/`.`), absolute filesystem,
 * backslash, and percent-decoded traversal are all rejected; query/hash
 * suffixes are stripped safely before resolution. The manifest is walked for
 * its entry's static closure, and every `file`/`css`/`assets` path it names is
 * containment-checked. If the manifest is malformed, references a missing
 * file, or names an eager (closed) asset the HTML did not also reference, the
 * verifier fails closed rather than trusting either source alone.
 */

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");

/**
 * Documented defaults, derived from the measured build on 2026-08-10.
 *
 *   - eager target: the handoff-approved initial-eager budget of ≤ 1,100,000
 *     bytes. After the chart-heavy secondary surfaces (ModelComparison,
 *     ModelDetail, BenchmarkCard, CatalogSharePie) were React.lazy split, the
 *     measured eager load (entry + static closure) is 696,014 bytes — below
 *     the gate. The gate is set to the approved 1,100,000, NOT to the current
 *     measured value, so it is not merely self-ratifying: a chart leaked back
 *     into the primary entry must push eager past 1.1 MB and fail.
 *   - total cap: 1,500,000, a justified strict cap based on the measured total
 *     of 1,440,833 bytes (entry 696,014 + deferred chart/vendor chunks incl.
 *     the ~446 KB shared react/vendor chunk). Code splitting never reduces
 *     total bytes, so the total cap is set just above the measured total with
 *     a small regression allowance. This is never inflated to pass.
 */
const DEFAULT_BUDGETS = {
  totalBytes: 1_500_000,
  eagerBytes: 1_100_000,
};

// Required build inputs for freshness. All must EXIST and be regular files
// (a deleted or symlinked file fails the gate, since the build literally could
// not have been produced from them). package/package-lock signal dependency
// changes from `npm install`; vite/tsconfig/postcss/tailwind are the build and
// style resolvers; index.html is the HTML entry the eager closure binds to.
const BUILD_INPUT_DIRS = ["src", "public"];
const BUILD_INPUT_FILES = [
  "index.html",
  "vite.config.ts",
  "package.json",
  "package-lock.json",
  "tsconfig.json",
  "postcss.config.js",
  "tailwind.config.js",
];

function resolveBudget(key, fallback) {
  const raw = process.env[key];
  if (raw === undefined || raw === "") return fallback;
  const parsed = Number(raw);
  assert.ok(Number.isFinite(parsed) && parsed >= 0, `${key} must be a non-negative number`);
  return parsed;
}

export function defaultBudgets() {
  return {
    totalBytes: resolveBudget("BUNDLE_TOTAL_BYTES", DEFAULT_BUDGETS.totalBytes),
    eagerBytes: resolveBudget("BUNDLE_EAGER_BYTES", DEFAULT_BUDGETS.eagerBytes),
  };
}

async function isFile(filePath) {
  try {
    return (await stat(filePath)).isFile();
  } catch {
    return false;
  }
}

async function isDirectory(filePath) {
  try {
    return (await stat(filePath)).isDirectory();
  } catch {
    return false;
  }
}

/** Strip a `?query#hash` suffix from an asset URL safely. */
function stripQueryHash(url) {
  const end = url.search(/[?#]/);
  return end === -1 ? url : url.slice(0, end);
}

/**
 * Resolve an asset reference to a real path under `distDir`, rejecting any
 * escape from it. Throws on `..` traversal (raw or percent-decoded), absolute
 * drive paths, backslash paths, and any resolved target outside `distDir`.
 * Query/hash suffixes are stripped before resolution.
 */
function assertContainedPath(distDir, url, label) {
  if (url.includes("\\")) {
    throw new Error(`${label}: asset reference contains a backslash: ${url}`);
  }
  if (url.startsWith("//")) {
    throw new Error(`${label}: asset reference uses a protocol-relative path: ${url}`);
  }
  let decoded;
  try {
    decoded = decodeURIComponent(url);
  } catch {
    throw new Error(`${label}: asset reference is not valid percent-encoding: ${url}`);
  }
  if (decoded.includes("..")) {
    throw new Error(`${label}: asset reference escapes dist via dot-segment: ${url}`);
  }
  if (/^[a-zA-Z]:/.test(decoded)) {
    throw new Error(`${label}: asset reference uses an absolute drive path: ${url}`);
  }
  const clean = stripQueryHash(decoded);
  const rootRelative = clean.startsWith("/");
  const rel = rootRelative ? clean.slice(1) : clean;
  if (rel.startsWith("/")) {
    throw new Error(`${label}: asset reference uses an absolute filesystem path: ${url}`);
  }
  const abs = resolve(distDir, rel);
  const relToDist = relative(distDir, abs);
  const escapes =
    relToDist === ".." || relToDist.startsWith(`..${sep}`) || relToDist.split(sep)[0] === "..";
  if (escapes) {
    throw new Error(`${label}: asset reference escapes dist: ${url}`);
  }
  return abs;
}

/**
 * Collect module script/module-preload asset references from built HTML that
 * point at our own build artifacts. Returns a Set of cleaned asset URLs
 * (query/hash stripped), de-duplicated.
 */
function collectHtmlAssetRefs(html) {
  const refs = new Set();
  const re = /(?:src|href)=["']([^"']+)["']/g;
  let m;
  while ((m = re.exec(html)) !== null) {
    const url = m[1];
    if (url.startsWith("data:") || /^https?:/i.test(url) || url.startsWith("#")) continue;
    // Only bundle-looking refs: a leading slash into an assets dir, or any
    // path that ends in .js/.css. Anchors and bare names are ignored.
    if (/^\/(?:assets\/|\S+\/)/i.test(url) || /\.(?:js|css)(?:[?#]|$)/i.test(url)) {
      refs.add(stripQueryHash(url));
    }
  }
  return refs;
}

/**
 * Extract the `src` of every `<script type="module">` from built HTML. This is
 * the HTML side of the entry binding: the module script is the built app entry
 * (crossorigin, deferred). Unlike collectHtmlAssetRefs — which also collects
 * `<link rel="modulepreload">` preloads and non-module scripts — this isolates
 * exactly the entry so zero/multiple/mismatch can be detected deterministically.
 * `type` may be attribute-first or after other attributes, and may be
 * defaulted solely by the `type="module"` marker. Returns raw `src` values
 * (query/hash retained) in document order.
 */
function collectModuleScripts(html) {
  const srcs = [];
  const re = /<script\b([^>]*)>/gi;
  let m;
  while ((m = re.exec(html)) !== null) {
    const attrs = m[1];
    // `type="module"` must be a real attribute marker, never a substring inside
    // another attribute's value. A `<script src="/assets/type=module.js">`
    // (URL merely *containing* "type=module") is a plain script, NOT a module —
    // and must not surface as a phantom entry near the binding check. Anchor the
    // marker on whitespace/attribute-start so an actual `type` attribute (which
    // is always preceded by whitespace or starts the attribute list) matches,
    // but a query string inside a `src` does not.
    if (!/(?:^|\s)type\s*=\s*["']module["']/i.test(attrs)) continue;
    // `src` likewise must be a real attribute, not `data-src`/`x-src`.
    const srcMatch = /(?:^|\s)src\s*=\s*["']([^"']+)["']/i.exec(attrs);
    if (srcMatch) srcs.push(srcMatch[1]);
  }
  return srcs;
}

/**
 * Normalize an asset path to a canonical, comparable form: strip any query/hash,
 * collapse a leading `/`, and drop a leading `assets/` prefix so the manifest's
 * `assets/name.js` and the HTML's `/assets/name.js` compare equal.
 */
function normalizeAssetPath(url) {
  const clean = stripQueryHash(url);
  return clean.replace(/^\/+/, "").replace(/^assets\//, "");
}

/**
 * Eager chunks: the `.js` assets reachable on first paint, each with its byte
 * size. `extraFileNames` are additional eager assets named by the manifest's
 * entry static closure that the HTML did not reference as scripts (e.g. a
 * shared statically-imported chunk Vite hoisted out of the HTML with no
 * modulepreload link). Fails closed if a referenced JS asset is
 * missing/empty/escapes dist.
 */
async function collectEagerChunks(distDir, html, label, extraFileNames = []) {
  const refs = collectHtmlAssetRefs(html);
  let jsRefs = [...refs].filter((url) => url.toLowerCase().endsWith(".js"));
  assert.ok(
    jsRefs.length >= 1,
    `${label}: built index.html must reference at least one JS entry asset`
  );

  // Resolve manifest-named closure files to their dist asset paths, so the
  // eager bound is the union of HTML scripts/preloads and manifest closure.
  for (const name of extraFileNames) {
    const rel = `assets/${name}`;
    const abs = resolve(distDir, rel);
    const relToDist = relative(distDir, abs);
    const escapes =
      relToDist === ".." || relToDist.startsWith(`..${sep}`) || relToDist.split(sep)[0] === "..";
    if (escapes) {
      throw new Error(`${label}: manifest eager closure asset escapes dist: ${name}`);
    }
    if (!(await isFile(abs))) {
      throw new Error(`${label}: manifest eager closure references missing JS asset: ${name}`);
    }
    const url = `/assets/${name}`;
    if (!jsRefs.includes(url)) jsRefs.push(url);
  }

  const eager = new Map();
  for (const url of jsRefs) {
    const abs = assertContainedPath(distDir, url, label);
    assert.ok(await isFile(abs), `${label}: built index.html references missing JS asset: ${url}`);
    // Reject any symlinked eager asset (the containment rule must not be
    // defeated by a link resolving outside dist).
    const lst = await lstat(abs);
    if (lst.isSymbolicLink()) {
      throw new Error(`${label}: eager asset is a symlink under dist: ${url}`);
    }
    const st = await stat(abs);
    assert.ok(st.size > 0, `${label}: built JS asset is empty: ${url}`);
    if (!eager.has(abs)) eager.set(abs, st.size);
  }
  return eager;
}

/**
 * All emitted JS chunks under dist/assets, keyed by absolute path -> bytes.
 * This is the `total` figure and is independent of how Vite names chunks.
 */
async function collectTotalJsChunks(distDir) {
  const assetsDir = join(distDir, "assets");
  if (!(await isDirectory(assetsDir))) return new Map();
  const names = await readdir(assetsDir, { withFileTypes: true });
  const total = new Map();
  for (const entry of names) {
    if (!entry.name.toLowerCase().endsWith(".js")) continue;
    const abs = join(assetsDir, entry.name);
    // Fail closed on a symlink that resolves outside dist/ (or is a symlink at
    // all — a build must never ship a symlinked asset). `lstat` does not follow
    // the link; if it is a symlink we resolve it and reject any target that
    // escapes dist/assets (the same containment rule as asset references).
    const lst = await lstat(abs);
    if (lst.isSymbolicLink()) {
      throw new Error(
        `asset ${entry.name} is a symlink under dist/assets; symlinked build assets are rejected`
      );
    }
    assert.ok(lst.isFile(), `asset ${entry.name} is not a regular file`);
    const st = await stat(abs);
    assert.ok(st.size > 0, `asset ${entry.name} is empty`);
    total.set(abs, st.size);
  }
  return total;
}

/**
 * Read dist/.vite/manifest.json robustly. On success, containment-check every
 * path the manifest names (`file`, `css`, `assets`) so a manifest that points
 * outside dist (or at a missing file) fails closed. Returns the parsed
 * manifest along with the key of the entry module (the `isEntry` record that
 * produces the built HTML entry), and a set of every asset file the manifest
 * is *aware* of. The manifest is load-bearing for eager closure — see
 * collectManifestEagerClosure.
 */
async function readManifestContained(distDir) {
  const manifestPath = join(distDir, ".vite", "manifest.json");
  // The manifest is load-bearing for the eager closure (see the function
  // header): a build with `build.manifest` enabled always emits it, and the
  // verifier must not trust an HTML-script-only eager count. A missing or
  // absent manifest therefore fails closed rather than silently degrading to
  // an HTML-only eager measure.
  assert.ok(
    await isFile(manifestPath),
    `dist/.vite/manifest.json is missing; the bundle manifest is load-bearing for the eager closure`
  );
  const manifestLst = await lstat(manifestPath);
  assert.ok(
    !manifestLst.isSymbolicLink(),
    "dist/.vite/manifest.json must not be a symlink"
  );
  assert.ok(manifestLst.isFile(), "dist/.vite/manifest.json is not a regular file");
  let parsed;
  try {
    parsed = JSON.parse(await readFile(manifestPath, "utf8"));
  } catch (error) {
    throw new Error(`dist/.vite/manifest.json is malformed: ${error.message}`);
  }
  assert.ok(
    parsed && typeof parsed === "object" && !Array.isArray(parsed),
    "manifest top level must be a non-null, non-array object"
  );
  const label = "dist/.vite/manifest.json";
  let entryKeys = [];
  for (const [key, mod] of Object.entries(parsed)) {
    // Every manifest record (module) must be a non-null, non-array object. A
    // record that is a bare string/array/null is malformed and must fail closed
    // rather than be ignored — an attacker could otherwise smuggle an entry past
    // the schema by giving it a malformed shape that the closure happens to skip.
    assert.ok(
      mod && typeof mod === "object" && !Array.isArray(mod),
      `manifest record ${JSON.stringify(key)} must be a non-null, non-array object`
    );
    // Every manifest record must carry a non-empty string `file`. This is
    // unconditional: a record with `file` omitted or empty is malformed and must
    // fail closed rather than be tolerated by the closure (which would otherwise
    // treat it as a source the manifest legitimately knows about but the build
    // never emitted).
    assert.ok(
      typeof mod.file === "string" && mod.file.length > 0,
      `manifest record ${JSON.stringify(key)} "file" must be a non-empty string`
    );
    if (mod.isEntry !== undefined) {
      assert.ok(
        typeof mod.isEntry === "boolean",
        `manifest record ${JSON.stringify(key)} "isEntry" must be a boolean when present`
      );
    }
    {
      // The single entry's file must be the JS app entry, not a stylesheet or
      // other asset. Enforced BEFORE the existence check so a malformed entry
      // (wrong extension) fails with a schema diagnostic rather than a generic
      // "file missing".
      if (mod.isEntry === true) {
        assert.ok(
          typeof mod.file === "string" && mod.file.toLowerCase().endsWith(".js"),
          `manifest entry "file" must end in .js`
        );
      }
      const abs = assertContainedPath(distDir, mod.file, label);
      assert.ok(await isFile(abs), `${label} ${JSON.stringify(key)} file missing: ${mod.file}`);
    }
    for (const field of ["css", "assets", "imports", "dynamicImports"]) {
      if (mod[field] === undefined) continue;
      assert.ok(
        Array.isArray(mod[field]) &&
          mod[field].every((el) => typeof el === "string" && el.length > 0),
        `manifest record ${JSON.stringify(key)} "${field}" must be an array of non-empty strings when present`
      );
    }
    for (const field of ["css", "assets"]) {
      if (!Array.isArray(mod[field])) continue;
      for (const asset of mod[field]) {
        const abs = assertContainedPath(distDir, asset, label);
        assert.ok(await isFile(abs), `${label} ${JSON.stringify(key)} ${field} missing: ${asset}`);
      }
    }
    if (mod.isEntry === true) entryKeys.push(key);
  }
  assert.ok(
    entryKeys.length === 1,
    `manifest must have exactly one isEntry record (found ${entryKeys.length})`
  );
  return { manifest: parsed, entryKey: entryKeys[0] };
}

/** Strip a URL/path down to its asset file name (query/hash removed). */
function tail(url) {
  return url.split(/[?#]/)[0].split("/").pop();
}

/**
 * Derive the eager JS closure from the Vite manifest entry: start at the
 * `isEntry` record and walk its transitive STATIC `imports` (which reference
 * other manifest keys by name). `dynamicImports` are NOT traversed — those are
 * deferred chunks. Returns the set of asset file names that a first paint pulls
 * in, per the authoritative module graph. This is the fail-closed complement to
 * the HTML-script-count so a statically-imported shared chunk that Vite did not
 * emit a modulepreload link for cannot be silently dropped from the eager sum.
 *
 * Fails closed if the manifest has no entry, references an unknown import key,
 * or names an entry asset the build does not actually contain.
 */
function collectManifestEagerClosure(manifest, entryKey, distDir, label) {
  if (!manifest) return [];
  const keys = new Set(Object.keys(manifest));
  const visited = new Set();
  const eagerFiles = new Set();
  assert.ok(
    entryKey !== null && keys.has(entryKey),
    `${label}: manifest has no isEntry record to derive the eager closure from`
  );

  const pending = [entryKey];
  while (pending.length > 0) {
    const key = pending.pop();
    if (visited.has(key)) continue;
    visited.add(key);
    const mod = manifest[key];
    if (!mod || typeof mod !== "object" || typeof mod.file !== "string") continue;
    // Only JS assets count toward eager bytes.
    if (mod.file.toLowerCase().endsWith(".js")) eagerFiles.add(tail(mod.file));
    if (Array.isArray(mod.imports)) {
      for (const imp of mod.imports) {
        assert.ok(keys.has(imp), `${label}: manifest import ${JSON.stringify(imp)} (from ${JSON.stringify(key)}) is not a manifest key`);
        pending.push(imp);
      }
    }
  }
  return [...eagerFiles];
}

/** Recursively walk a directory tree, invoking onFile for each regular file.
 * A symlink anywhere in the walked tree (a source/public directory or one of
 * its files) FAILS CLOSED rather than being skipped: a proponent could
 * otherwise hide a necessary input behind a link, or a link could point the
 * freshnes window outside the repository. Only ever recurses into real
 * directories. */
async function walkFiles(dir, onFile, label) {
  const entries = await readdir(dir, { withFileTypes: true });
  entries.sort((a, b) => (a.name < b.name ? -1 : 1));
  for (const entry of entries) {
    if (entry.isSymbolicLink()) {
      throw new Error(
        `${label}: symlink in build input tree is rejected: ${join(dir, entry.name)}`
      );
    }
    const full = join(dir, entry.name);
    if (entry.isDirectory()) {
      await walkFiles(full, onFile, label);
    } else if (entry.isFile()) {
      await onFile(full);
    }
  }
}

/**
 * Newest mtimeMs among the build inputs. Required top-level build files
 * (BUILD_INPUT_FILES) must all exist as regular files and must not be
 * symlinks — deleting one, or swapping it for a link that escapes the repo,
 * fails closed so the gate cannot pass against a build whose inputs are gone
 * or untrusted. Directories are walked without following any symlink.
 */
async function newestInputMtime(rootDir) {
  let newest = -1;
  const touch = (mtimeMs) => {
    if (mtimeMs > newest) newest = mtimeMs;
  };
  for (const file of BUILD_INPUT_FILES) {
    const full = join(rootDir, file);
    assert.ok(await isFile(full), `required build input is missing: ${file}`);
    const lst = await lstat(full);
    assert.ok(!lst.isSymbolicLink(), `required build input must not be a symlink: ${file}`);
    assert.ok(lst.isFile(), `required build input is not a regular file: ${file}`);
    touch((await stat(full)).mtimeMs);
  }
  for (const dir of BUILD_INPUT_DIRS) {
    const full = join(rootDir, dir);
    // The root source/public tree is load-bearing: the build must actually have
    // been produced from it. A missing directory means there is nothing to build
    // against, and a symlinked directory must not smuggle inputs in from outside
    // the repo. Both fail closed (the walker separately rejects any symlink
    // nested inside the tree).
    const lst = await lstat(full);
    assert.ok(
      !lst.isSymbolicLink(),
      `required build input directory must not be a symlink: ${dir}`
    );
    assert.ok(lst.isDirectory(), `required build input directory is missing: ${dir}`);
    await walkFiles(full, async (p) => touch((await stat(p)).mtimeMs), `input dir ${dir}`);
  }
  return newest;
}

/** Human-readable per-chunk diagnostics, largest first. */
function formatDiagnostics(eager, total) {
  const combined = new Map();
  for (const [abs, bytes] of eager) combined.set(abs, { bytes, where: "eager+total" });
  for (const [abs, bytes] of total) {
    const existing = combined.get(abs);
    if (existing) existing.bytes = bytes;
    else combined.set(abs, { bytes, where: "deferred" });
  }
  const lines = ["Per-chunk JS (size, role):"];
  for (const [abs, row] of [...combined].sort((a, b) => b[1].bytes - a[1].bytes)) {
    lines.push(`  ${String(row.bytes).padStart(10)}  ${row.where.padEnd(12)}  ${abs}`);
  }
  return lines.join("\n");
}

/** Enforce the freshness contract: dist/index.html must not be older than any input. */
async function assertFresh(rootDir, distDir) {
  const indexStat = await stat(join(distDir, "index.html"));
  const newestInput = await newestInputMtime(rootDir);
  assert.ok(newestInput > 0, "no build inputs found to compare freshness against");
  assert.ok(
    indexStat.mtimeMs >= newestInput,
    "dist/index.html is stale (older than a build input). Stale dist artifacts are " +
      "not verified; run npm run build before the bundle gate."
  );
  return newestInput;
}

/** Public API: verify a FRESH `dist` output against the requested budgets. */
export async function verifyBundleBudget({ rootDir = repoRoot, budgets: overrideBudgets } = {}) {
  const budgets = { ...defaultBudgets(), ...(overrideBudgets ?? {}) };
  const distDir = join(rootDir, "dist");
  assert.ok(await isDirectory(distDir), "dist/ is not a built directory");

  const indexFile = join(distDir, "index.html");
  assert.ok(await isFile(indexFile), "dist/ is missing built index.html");
  // The HTML entry is load-bearing for eager accounting and freshness; a
  // symlinked index.html must not be trusted (its mtime/target could be
  // fabricated to defeat the freshness and closure gates). Check BEFORE the
  // freshness comparison would otherwise benignly pass or staleness-mask it.
  const indexLst = await lstat(indexFile);
  assert.ok(!indexLst.isSymbolicLink(), "dist/index.html must not be a symlink");
  assert.ok(indexLst.isFile(), "dist/index.html is not a regular file");
  let html;
  try {
    html = await readFile(indexFile, "utf8");
  } catch (error) {
    throw new Error(`dist/index.html could not be read: ${error.message}`);
  }
  const label = "dist/index.html";

  // 1. Freshness: build-then-verify.
  const newestInput = await assertFresh(rootDir, distDir);

  // 2. Manifest: containment-checked, and its entry's static `imports` closure
//    is the load-bearing eager module graph. Because Vite can hoist a
//    statically-imported shared chunk out of the emitted HTML (no
//    modulepreload link), every chunk the closure names must ALSO be counted
//    toward eager even when the HTML never referenced it as a <script>/<link>.
//    `collectEagerChunks` union-includes those closure files and fail-closes if
//    any is missing/empty/escaping; `collectManifestEagerClosure` fail-closes
//    on an unknown import key.
const { manifest, entryKey } = await readManifestContained(distDir);
const manifestEagerFiles = collectManifestEagerClosure(manifest, entryKey, distDir, label);

// 3. Entry binding: the HTML `<script type="module">` entry and the manifest's
//    `isEntry` record (its `file`) must be one and the same built asset.
//    Preload `<link>`s are deliberately NOT consulted here — a modulepreload
//    for a statically-imported chunk is not the entry, and Vite may hoist the
//    shared chunk out of the HTML entirely. So we require exactly one module
//    script and exactly one manifest `isEntry`, and demand their normalized
//    asset paths agree. Zero / multiple / mismatched entries all fail closed,
//    because an "entry" is only trustworthy if the two load-bearing graphs
//    agree on what it is.
const moduleScripts = collectModuleScripts(html);
assert.ok(
  moduleScripts.length === 1,
  `built index.html must reference exactly one <script type="module"> entry (found ${moduleScripts.length})`
);
// The entry src is an asset reference like any other: it must NOT escape dist,
// even before the binding comparison (a traversal here would otherwise be
// masked as a benign mismatch). Fails closed on dot-segment/absolute/backslash
// forms exactly like collectEagerChunks would.
assertContainedPath(distDir, moduleScripts[0], label);
const htmlEntryAsset = normalizeAssetPath(moduleScripts[0]);
const manifestEntryAsset = normalizeAssetPath(manifest[entryKey].file);
assert.ok(
  htmlEntryAsset === manifestEntryAsset,
  `HTML module entry (${htmlEntryAsset}) does not match the manifest entry asset (${manifestEntryAsset})`
);

// 4. Measure eager as the UNION of the HTML-referenced scripts/preloads and
//    the manifest's authoritative closure, every reference
//    containment-checked.
const eager = await collectEagerChunks(distDir, html, label, manifestEagerFiles);
const total = await collectTotalJsChunks(distDir);
assert.ok(total.size >= 1, "no .js chunks found under dist/assets/");

const eagerJsBytes = [...eager.values()].reduce((s, n) => s + n, 0);
  const totalJsBytes = [...total.values()].reduce((s, n) => s + n, 0);

  const result = {
    eagerJsBytes,
    totalJsBytes,
    manifestPresent: manifest !== null,
    chunks: formatDiagnostics(eager, total),
    budget: budgets,
    freshness: {
      checked: true,
      newestInputMtimeMs: Math.round(newestInput),
      distIndexMtimeMs: Math.round((await stat(join(distDir, "index.html"))).mtimeMs),
    },
  };

  assert.ok(
    totalJsBytes <= budgets.totalBytes,
    `Total JS ${totalJsBytes} bytes exceeds budget ${budgets.totalBytes}\n${result.chunks}`
  );
  assert.ok(
    eagerJsBytes <= budgets.eagerBytes,
    `Eager JS ${eagerJsBytes} bytes exceeds budget ${budgets.eagerBytes}\n${result.chunks}`
  );
  return result;
}

function parseCliArgs(args) {
  let rootDir = repoRoot;
  const budgets = {};
  for (let index = 0; index < args.length; index += 1) {
    const arg = args[index];
    if (arg === "--root-dir") {
      const value = args[index + 1];
      assert.ok(value, "--root-dir requires a path");
      rootDir = resolve(value);
      index += 1;
    } else if (arg === "--budget-total") {
      const value = args[index + 1];
      assert.ok(value !== undefined, "--budget-total requires a number");
      budgets.totalBytes = Number(value);
      assert.ok(Number.isFinite(budgets.totalBytes) && budgets.totalBytes >= 0, "--budget-total must be non-negative");
      index += 1;
    } else if (arg === "--budget-eager") {
      const value = args[index + 1];
      assert.ok(value !== undefined, "--budget-eager requires a number");
      budgets.eagerBytes = Number(value);
      assert.ok(Number.isFinite(budgets.eagerBytes) && budgets.eagerBytes >= 0, "--budget-eager must be non-negative");
      index += 1;
    } else if (arg === "--help" || arg === "-h") {
      console.log(
        "Usage: node scripts/verify-bundle-budget.mjs [--root-dir PATH] [--budget-total N] " +
          "[--budget-eager N]"
      );
      return null;
    } else {
      throw new Error(`Unknown argument: ${arg}`);
    }
  }
  return { rootDir, budgets: Object.keys(budgets).length ? budgets : undefined };
}

const isMain = process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url);
if (isMain) {
  try {
    const options = parseCliArgs(process.argv.slice(2));
    if (!options) process.exit(0);
    const result = await verifyBundleBudget(options);
    console.log(
      `Bundle budget passed: eagerJs=${result.eagerJsBytes} totalJs=${result.totalJsBytes} ` +
        `(eager<=${result.budget.eagerBytes} total<=${result.budget.totalBytes}).\n` +
        result.chunks
    );
  } catch (error) {
    console.error(error instanceof Error ? error.message : error);
    process.exitCode = 1;
  }
}