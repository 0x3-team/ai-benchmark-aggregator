import assert from "node:assert/strict";
import { mkdir, mkdtemp, rm, stat, utimes, writeFile } from "node:fs/promises";
import { spawnSync } from "node:child_process";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";
import { verifyBundleBudget } from "./verify-bundle-budget.mjs";

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");

/**
 * Build a minimal, deterministic fixture with a controllable dist/index.html
 * and JS assets, so eager/total accounting and each fail-closed/containment/
 * freshness path is reproducible without a real Vite build.
 *
 * Parametrised over the exact <script>/<link modulepreload> tags emitted into
 * dist/index.html and the JS assets that exist under dist/assets/. The build is
 * made to look fresh by default (dist output mtime set after the inputs);
 * `staleSource` re-touches a source input so the freshness gate fires.
 */
async function createDistFixture({
  entryScriptUrls = ["/assets/index-AAAAAAAA.js"],
  preloadUrls = [],
  assets = {}, // { "name.js": bytes }
  withoutIndexHtml = false,
  noJsEntry = false,
  withoutEntryAsset = false,
  withoutRequiredInput = null,
  withoutManifest = false,
  malformedManifest = false,
  manifestNull = false,
  manifestEntries = null,
  staleSource = false,
  extraBodyHtml = "",
} = {}) {
  const root = await mkdtemp(join(tmpdir(), "ai-benchmark-bundle-fixture-"));
  const dist = join(root, "dist");
  await mkdir(join(dist, "assets"), { recursive: true });
  await mkdir(join(root, "src"), { recursive: true });
  await mkdir(join(root, "public"), { recursive: true });

  // Source/inputs so freshness has something to compare against.
  await writeFile(join(root, "src", "entry.ts"), "export const x = 1;\n");
  await writeFile(join(root, "public", "robots.txt"), "User-agent: *\nAllow: /\n");
  await writeFile(join(root, "index.html"), "<!doctype html><html lang='en'></html>\n");

  // The required top-level build inputs the gate treats as load-bearing:
  // deleting any of them must fail closed. Provide them by default so every
  // other fixture stays referentially valid; `withoutRequiredInput` omits one
  // to exercise the deletion path in isolation.
  if (!withoutRequiredInput) {
    await writeFile(join(root, "package.json"), "{\"name\":\"t\",\"private\":true}\n");
    await writeFile(join(root, "package-lock.json"), "{\"lockfileVersion\":3}\n");
    await writeFile(join(root, "vite.config.ts"), "export default {};\n");
    await writeFile(join(root, "postcss.config.js"), "module.exports = {};\n");
    await writeFile(join(root, "tailwind.config.js"), "module.exports = {};\n");
    await writeFile(join(root, "tsconfig.json"), "{}");
  } else if (
    withoutRequiredInput === "vite.config.ts" ||
    withoutRequiredInput === "postcss.config.js" ||
    withoutRequiredInput === "tailwind.config.js" ||
    withoutRequiredInput === "tsconfig.json"
  ) {
    await writeFile(join(root, "package.json"), "{\"name\":\"t\",\"private\":true}\n");
    await writeFile(join(root, "package-lock.json"), "{\"lockfileVersion\":3}\n");
    await writeFile(join(root, "vite.config.ts"), "export default {};\n");
    await writeFile(join(root, "postcss.config.js"), "module.exports = {};\n");
    await writeFile(join(root, "tailwind.config.js"), "module.exports = {};\n");
    await writeFile(join(root, "tsconfig.json"), "{}");
    await rm(join(root, withoutRequiredInput));
  } else {
    await writeFile(join(root, "package.json"), "{\"name\":\"t\",\"private\":true}\n");
    await writeFile(join(root, "package-lock.json"), "{\"lockfileVersion\":3}\n");
    await writeFile(join(root, "vite.config.ts"), "export default {};\n");
    await writeFile(join(root, "postcss.config.js"), "module.exports = {};\n");
    await writeFile(join(root, "tailwind.config.js"), "module.exports = {};\n");
    await writeFile(join(root, "tsconfig.json"), "{}");
  }

  // Emit the asset files first (their mtime becomes the baseline for freshness).
  const written = new Set();
  const writeAsset = (name, bytes) => {
    if (written.has(name)) return name;
    written.add(name);
    const abs = join(dist, "assets", name);
    writeFile(abs, "//" + "x".repeat(Math.max(0, bytes - 2)));
    return name;
  };

  // `assets` takes precedence; entry/preload defaults only fill gaps. The
  // referenced entry asset is skipped when `withoutEntryAsset` so the HTML
  // points at something that does not exist.
  for (const [name, bytes] of Object.entries(assets)) writeAsset(name, bytes);
  for (const url of (withoutEntryAsset ? [] : entryScriptUrls)) writeAsset(tail(url), 1_000);
  for (const url of preloadUrls) writeAsset(tail(url), 1_000);

  if (!withoutIndexHtml) {
    const scripts = (noJsEntry ? [] : entryScriptUrls)
      .map((u) => `<script type="module" crossorigin src="${u}"></script>`)
      .join("");
    const preloads = preloadUrls
      .map((u) => `<link rel="modulepreload" href="${u}">`)
      .join("");
    await writeFile(
      join(dist, "index.html"),
      `<!doctype html><html lang="en"><head>${scripts}${preloads}</head><body>${extraBodyHtml}</body></html>`
    );
  }

  await mkdir(join(dist, ".vite"), { recursive: true });
  if (withoutManifest) {
    // leave dist/.vite/ empty — the load-bearing manifest is absent
  } else if (malformedManifest) {
    await writeFile(join(dist, ".vite", "manifest.json"), "{ definitely not json");
  } else {
    // A real Vite manifest only ever names assets the build actually emitted.
    // When the HTML deliberately references a missing entry asset, the
    // manifest still names a real emitted file so the two fail-closed paths
    // are exercised independently (manifest containment vs HTML-missing).
    const emittedEntry =
      entryScriptUrls[0] ? tail(entryScriptUrls[0]) : "index-AAAAAAAA.js";
    // Emit the asset the manifest names unless the HTML deliberately references
    // a missing entry asset: in that case the manifest and HTML both point at
    // the same (absent) entry so the missing-file fail-closed path fires.
    if (entryScriptUrls[0] && !withoutEntryAsset) writeAsset(emittedEntry, 1_000);
    if (!entryScriptUrls[0] && !withoutEntryAsset && !manifestEntries) {
      writeAsset(emittedEntry, 1_000);
    }
    const realManifest =
      manifestNull ? null
        : manifestEntries !== null
        ? manifestEntries
        : {
            "src/entry.ts": {
              file: `assets/${emittedEntry}`,
              isEntry: true,
              imports: [],
            },
          };
    await writeFile(join(dist, ".vite", "manifest.json"), JSON.stringify(realManifest));
  }

  // Make the build look fresh by default: dist/index.html mtime well after the
  // inputs. Actual app of-dist freshness for the source input is handled by
  // bumping dist output far future, and staleSource re-touches src.
  const indexPath = join(dist, "index.html");
  if (!withoutIndexHtml) {
    const future = new Date(Date.now() + 3600_000);
    await utimes(indexPath, future, future);
  }
  if (staleSource) {
    const srcPath = join(root, "src", "entry.ts");
    const future = new Date(Date.now() + 7200_000);
    await utimes(srcPath, future, future);
  }
  return root;
}

/** Derive the asset file name from a URL, stripping any query/hash suffix. */
function tail(url) {
  const clean = url.split(/[?#]/)[0];
  return clean.split("/").pop();
}

function cleanup(root) {
  return rm(root, { recursive: true, force: true });
}

const PASS_BUDGETS = { totalBytes: 50_000, eagerBytes: 50_000 };

test("passes exact accounting on an uncoded-split build (eager == total)", async () => {
  const root = await createDistFixture({
    entryScriptUrls: ["/assets/index-AAAAAAAA.js"],
    assets: { "index-AAAAAAAA.js": 1_433_793 },
  });
  try {
    const result = await verifyBundleBudget({
      rootDir: root,
      budgets: { totalBytes: 2_000_000, eagerBytes: 2_000_000 },
    });
    assert.equal(result.eagerJsBytes, 1_433_793);
    assert.equal(result.totalJsBytes, 1_433_793);
    assert.equal(result.manifestPresent, true);
  } finally {
    await cleanup(root);
  }
});

test("modulepreload/static chunks are eager; a deferred dynamic chunk counts only toward total", async () => {
  const root = await createDistFixture({
    entryScriptUrls: ["/assets/index-AAAAAAAA.js"],
    preloadUrls: ["/assets/preload-STATIC.js"],
    assets: {
      "index-AAAAAAAA.js": 2_000,
      "preload-STATIC.js": 3_000,
      "deferred-DYNAMIC.js": 5_000,
    },
  });
  try {
    const result = await verifyBundleBudget({
      rootDir: root,
      budgets: { totalBytes: 50_000, eagerBytes: 50_000 },
    });
    // Eager = entry (2000) + modulepreload (3000) = 5000. The dynamic chunk is
    // NOT in the HTML, so it contributes only to total (2000+3000+5000=10000).
    assert.equal(result.eagerJsBytes, 2_000 + 3_000);
    assert.equal(result.totalJsBytes, 2_000 + 3_000 + 5_000);
  } finally {
    await cleanup(root);
  }
});

test("total-JS budget failure", async () => {
  const root = await createDistFixture({
    entryScriptUrls: ["/assets/index-AAAAAAAA.js"],
    assets: { "index-AAAAAAAA.js": 60_000 },
  });
  try {
    await assert.rejects(
      verifyBundleBudget({ rootDir: root, budgets: PASS_BUDGETS }),
      /Total JS \d+ bytes exceeds budget 50000/
    );
  } finally {
    await cleanup(root);
  }
});

test("eager-JS budget failure", async () => {
  const root = await createDistFixture({
    entryScriptUrls: ["/assets/index-AAAAAAAA.js"],
    assets: { "index-AAAAAAAA.js": 60_000 },
  });
  try {
    await assert.rejects(
      verifyBundleBudget({
        rootDir: root,
        budgets: { totalBytes: 100_000, eagerBytes: 5_000 },
      }),
      /Eager JS \d+ bytes exceeds budget 5000/
    );
  } finally {
    await cleanup(root);
  }
});

test("fail-closed: missing dist", async () => {
  const root = await createDistFixture();
  try {
    await rm(join(root, "dist"), { recursive: true, force: true });
    await assert.rejects(
      verifyBundleBudget({ rootDir: root }),
      /dist\/ is not a built directory/
    );
  } finally {
    await cleanup(root);
  }
});

test("fail-closed: missing built index.html", async () => {
  const root = await createDistFixture({ withoutIndexHtml: true });
  try {
    await assert.rejects(
      verifyBundleBudget({ rootDir: root }),
      /dist\/ is missing built index\.html/
    );
  } finally {
    await cleanup(root);
  }
});

test("fail-closed: index.html references a JS asset that does not exist", async () => {
  const root = await createDistFixture({
    entryScriptUrls: ["/assets/missing-ENTRY.js"],
    withoutEntryAsset: true,
  });
  try {
    // The missing entry asset bites the load-bearing manifest containment first
    // (its `isEntry.file` names the same absent file): a missing entry must fail
    // closed regardless of which load-bearing source reports it.
    await assert.rejects(
      verifyBundleBudget({ rootDir: root }),
      /(?:references missing JS asset|file missing)/
    );
  } finally {
    await cleanup(root);
  }
});

test("fail-closed: index.html has no JS entry asset", async () => {
  const root = await createDistFixture({
    entryScriptUrls: [],
    noJsEntry: true,
    preloadUrls: [],
  });
  try {
    await assert.rejects(
      verifyBundleBudget({ rootDir: root }),
      /exactly one <script type="module"> entry/
    );
  } finally {
    await cleanup(root);
  }
});

test("fail-closed: missing vite manifest", async () => {
  const root = await createDistFixture({ withoutManifest: true });
  try {
    await assert.rejects(
      verifyBundleBudget({ rootDir: root }),
      /manifest\.json is missing/
    );
  } finally {
    await cleanup(root);
  }
});

test("fail-closed: built index.html has zero module scripts", async () => {
  const root = await createDistFixture({ noJsEntry: true, preloadUrls: [] });
  try {
    await assert.rejects(
      verifyBundleBudget({ rootDir: root }),
      /exactly one <script type="module"> entry/
    );
  } finally {
    await cleanup(root);
  }
});

test("fail-closed: built index.html has multiple module scripts", async () => {
  const root = await createDistFixture({
    entryScriptUrls: ["/assets/a-AAAA.js", "/assets/b-BBBB.js"],
    assets: { "a-AAAA.js": 1_000, "b-BBBB.js": 2_000 },
  });
  try {
    await assert.rejects(
      verifyBundleBudget({ rootDir: root }),
      /exactly one <script type="module"> entry/
    );
  } finally {
    await cleanup(root);
  }
});

test("fail-closed: manifest has no isEntry record", async () => {
  const root = await createDistFixture({
    entryScriptUrls: ["/assets/index-AAAAAAAA.js"],
    assets: { "index-AAAAAAAA.js": 1_000 },
    manifestEntries: {
      "src/entry.ts": { file: "assets/index-AAAAAAAA.js", isEntry: false, imports: [] },
    },
  });
  try {
    await assert.rejects(
      verifyBundleBudget({ rootDir: root, budgets: { totalBytes: 50_000, eagerBytes: 50_000 } }),
      /exactly one isEntry record/
    );
  } finally {
    await cleanup(root);
  }
});

test("fail-closed: multiple isEntry records are rejected", async () => {
  const root = await createDistFixture({
    entryScriptUrls: ["/assets/index-AAAAAAAA.js"],
    assets: { "index-AAAAAAAA.js": 1_000 },
    manifestEntries: {
      "index.html": { file: "assets/index-AAAAAAAA.js", isEntry: true, imports: [] },
      "other.html": { file: "assets/index-AAAAAAAA.js", isEntry: true, imports: [] },
    },
  });
  try {
    await assert.rejects(
      verifyBundleBudget({ rootDir: root, budgets: { totalBytes: 50_000, eagerBytes: 50_000 } }),
      /exactly one isEntry record/
    );
  } finally {
    await cleanup(root);
  }
});

test("fail-closed: HTML module entry does not match the manifest entry asset", async () => {
  const root = await createDistFixture({
    entryScriptUrls: ["/assets/index-AAAAAAAA.js"],
    assets: {
      "index-AAAAAAAA.js": 1_000,
      "other-ENTRY.js": 1_000,
    },
    manifestEntries: {
      "src/entry.ts": { file: "assets/other-ENTRY.js", isEntry: true, imports: [] },
    },
  });
  try {
    await assert.rejects(
      verifyBundleBudget({ rootDir: root, budgets: { totalBytes: 50_000, eagerBytes: 50_000 } }),
      /does not match the manifest entry asset/
    );
  } finally {
    await cleanup(root);
  }
});

test("fail-closed: symlinked vite manifest is rejected", async () => {
  const root = await createDistFixture({
    entryScriptUrls: ["/assets/index-AAAAAAAA.js"],
    assets: { "index-AAAAAAAA.js": 1_000 },
  });
  try {
    const { rm, symlink } = await import("node:fs/promises");
    await rm(join(root, "dist", ".vite", "manifest.json"));
    await symlink("/etc/hosts", join(root, "dist", ".vite", "manifest.json"));
    await assert.rejects(
      verifyBundleBudget({ rootDir: root, budgets: { totalBytes: 50_000, eagerBytes: 50_000 } }),
      /must not be a symlink/
    );
  } finally {
    await cleanup(root);
  }
});

test("fail-closed: symlinked dist/index.html is rejected", async () => {
  const root = await createDistFixture({
    entryScriptUrls: ["/assets/index-AAAAAAAA.js"],
    assets: { "index-AAAAAAAA.js": 1_000 },
  });
  try {
    const { rm, symlink } = await import("node:fs/promises");
    await rm(join(root, "dist", "index.html"));
    await symlink("/etc/hosts", join(root, "dist", "index.html"));
    await assert.rejects(
      verifyBundleBudget({ rootDir: root, budgets: { totalBytes: 50_000, eagerBytes: 50_000 } }),
      /must not be a symlink|not a regular file/
    );
  } finally {
    await cleanup(root);
  }
});

test("fail-closed: symlinked required build input directory is rejected", async () => {
  const root = await createDistFixture({
    entryScriptUrls: ["/assets/index-AAAAAAAA.js"],
    assets: { "index-AAAAAAAA.js": 1_000 },
  });
  try {
    const { rm, symlink } = await import("node:fs/promises");
    await rm(join(root, "src"), { recursive: true, force: true });
    await symlink("/etc", join(root, "src"));
    await assert.rejects(
      verifyBundleBudget({ rootDir: root, budgets: { totalBytes: 50_000, eagerBytes: 50_000 } }),
      /must not be a symlink.*src/
    );
  } finally {
    await cleanup(root);
  }
});

test("fail-closed: deletion of a required build input is rejected even when dist is otherwise fresh", async () => {
  const root = await createDistFixture({
    entryScriptUrls: ["/assets/index-AAAAAAAA.js"],
    assets: { "index-AAAAAAAA.js": 1_000 },
    withoutRequiredInput: "vite.config.ts",
  });
  try {
    await assert.rejects(
      verifyBundleBudget({ rootDir: root, budgets: { totalBytes: 50_000, eagerBytes: 50_000 } }),
      /required build input is missing.*vite\.config\.ts/
    );
  } finally {
    await cleanup(root);
  }
});

test("fail-closed: a required build input that is a symlink is rejected (never skipped)", async () => {
  const root = await createDistFixture({
    entryScriptUrls: ["/assets/index-AAAAAAAA.js"],
    assets: { "index-AAAAAAAA.js": 1_000 },
  });
  try {
    const { rm, symlink } = await import("node:fs/promises");
    await rm(join(root, "tailwind.config.js"));
    await symlink("/etc/hosts", join(root, "tailwind.config.js"));
    await assert.rejects(
      verifyBundleBudget({ rootDir: root, budgets: { totalBytes: 50_000, eagerBytes: 50_000 } }),
      /must not be a symlink.*tailwind\.config\.js/
    );
  } finally {
    await cleanup(root);
  }
});

test("fail-closed: malformed vite manifest", async () => {
  const root = await createDistFixture({ malformedManifest: true });
  try {
    await assert.rejects(
      verifyBundleBudget({ rootDir: root }),
      /malformed/
    );
  } finally {
    await cleanup(root);
  }
});

test("fail-closed: stale build (a source input newer than dist/index is rejected)", async () => {
  const root = await createDistFixture({ staleSource: true });
  try {
    await assert.rejects(
      verifyBundleBudget({ rootDir: root }),
      /dist\/index\.html is stale/
    );
  } finally {
    await cleanup(root);
  }
});

test("passes a fresh build (inputs older than the output)", async () => {
  const root = await createDistFixture({
    entryScriptUrls: ["/assets/index-AAAAAAAA.js"],
    assets: { "index-AAAAAAAA.js": 1_000 },
  });
  try {
    const result = await verifyBundleBudget({
      rootDir: root,
      budgets: { totalBytes: 50_000, eagerBytes: 50_000 },
    });
    assert.equal(result.freshness.checked, true);
    assert.equal(result.eagerJsBytes, 1_000);
  } finally {
    await cleanup(root);
  }
});

test("dot-segment traversal is rejected", async () => {
  const root = await createDistFixture({
    entryScriptUrls: ["/assets/../../etc/passwd.js"],
  });
  try {
    await assert.rejects(
      verifyBundleBudget({ rootDir: root }),
      /dot-segment|escapes dist/
    );
  } finally {
    await cleanup(root);
  }
});

test("percent-decoded dot-segment traversal is rejected", async () => {
  const root = await createDistFixture({
    entryScriptUrls: ["/assets/%2e%2e/etc/passwd.js"],
  });
  try {
    await assert.rejects(
      verifyBundleBudget({ rootDir: root }),
      /dot-segment/
    );
  } finally {
    await cleanup(root);
  }
});

test("absolute filesystem path in an asset reference is rejected", async () => {
  const root = await createDistFixture({
    entryScriptUrls: ["/etc/hostname.js"],
  });
  try {
    await assert.rejects(
      verifyBundleBudget({ rootDir: root }),
      // A bare root-relative `/etc/...` maps under dist and is therefore
      // contained-but-missing; an actual absolute filesystem escape is caught
      // by the drive-path / dot-segment / backslash guards. Either way the
      // reference fails closed.
      /(?:missing JS asset|absolute filesystem|escapes dist|does not match the manifest entry asset)/
    );
  } finally {
    await cleanup(root);
  }
});

test("backslash Windows-style traversal is rejected", async () => {
  const root = await createDistFixture({
    entryScriptUrls: ["/assets/..\\..\\etc\\passwd.js"],
  });
  try {
    await assert.rejects(
      verifyBundleBudget({ rootDir: root }),
      /backslash|dot-segment|escapes dist/
    );
  } finally {
    await cleanup(root);
  }
});

test("symlinked build asset is rejected (no symlink escape into eager/total)", async () => {
  const root = await createDistFixture({
    entryScriptUrls: ["/assets/index-AAAAAAAA.js"],
    assets: { "index-AAAAAAAA.js": 1_000 },
  });
  try {
    const { symlink } = await import("node:fs/promises");
    // A malicious symlink under dist/assets pointing outside dist (e.g. into
    // /etc). The verifier must fail closed rather than follow the link.
    await symlink("/etc/hosts", join(root, "dist", "assets", "evil-LINK.js"));
    await assert.rejects(
      verifyBundleBudget({ rootDir: root, budgets: { totalBytes: 50_000, eagerBytes: 50_000 } }),
      /symlink under dist/
    );
  } finally {
    await cleanup(root);
  }
});

test("query/hash suffixes on asset refs are handled safely", async () => {
  const root = await createDistFixture({
    entryScriptUrls: ["/assets/index-AAAAAAAA.js?v=1#cache"],
    assets: { "index-AAAAAAAA.js": 1_000 },
  });
  try {
    const result = await verifyBundleBudget({
      rootDir: root,
      budgets: { totalBytes: 50_000, eagerBytes: 50_000 },
    });
    assert.equal(result.eagerJsBytes, 1_000);
  } finally {
    await cleanup(root);
  }
});

test("manifest reachability is not claimed: a manifest entry for a deferred chunk adds no eager bytes", async () => {
  const root = await createDistFixture({
    entryScriptUrls: ["/assets/index-AAAAAAAA.js"],
    assets: {
      "index-AAAAAAAA.js": 1_000,
      "deferred-DYNAMIC.js": 4_000,
    },
    manifestEntries: {
      "src/entry.ts": { file: "assets/index-AAAAAAAA.js", isEntry: true, imports: [] },
      "src/deferred.ts": {
        file: "assets/deferred-DYNAMIC.js",
        isEntry: false,
        imports: ["src/entry.ts"],
      },
    },
  });
  try {
    const result = await verifyBundleBudget({
      rootDir: root,
      budgets: { totalBytes: 50_000, eagerBytes: 10_000 },
    });
    // The manifest lists deferred-DYNAMIC.js, but it is not in the HTML, so it
    // must NOT count toward eager.
    assert.equal(result.eagerJsBytes, 1_000);
    assert.equal(result.totalJsBytes, 1_000 + 4_000);
    assert.equal(result.manifestPresent, true);
  } finally {
    await cleanup(root);
  }
});

test("CLI passes within budget and fails fail-closed over budget", async () => {
  const within = await createDistFixture({
    entryScriptUrls: ["/assets/index-AAAAAAAA.js"],
    assets: { "index-AAAAAAAA.js": 1_000 },
  });
  try {
    const ok = spawnSync(
      process.execPath,
      [
        join(repoRoot, "scripts", "verify-bundle-budget.mjs"),
        "--root-dir", within,
        "--budget-total", "5000",
        "--budget-eager", "5000",
      ],
      { encoding: "utf8" }
    );
    assert.equal(ok.status, 0, ok.stderr);
    assert.match(ok.stdout, /Bundle budget passed/);
  } finally {
    await cleanup(within);
  }

  const over = await createDistFixture({
    entryScriptUrls: ["/assets/index-AAAAAAAA.js"],
    assets: { "index-AAAAAAAA.js": 6_000 },
  });
  try {
    const bad = spawnSync(
      process.execPath,
      [
        join(repoRoot, "scripts", "verify-bundle-budget.mjs"),
        "--root-dir", over,
        "--budget-total", "5000",
      ],
      { encoding: "utf8" }
    );
    assert.notEqual(bad.status, 0);
    assert.match(`${bad.stdout}\n${bad.stderr}`, /Total JS/);
    assert.match(`${bad.stdout}\n${bad.stderr}`, /Per-chunk JS/);
  } finally {
    await cleanup(over);
  }
});

test("manifest eager closure is load-bearing: a statically-imported chunk the HTML never references still counts toward eager", async () => {
  // Vite can hoist a statically-imported shared chunk out of the emitted HTML
  // (no <script>/<link modulepreload>), so the HTML alone would under-count
  // first-paint JS. The verifier must count the entry manifest closure into
  // eager, fail-closing on a missing closure asset — HTML tags are not the
  // only source of truth.
  const root = await createDistFixture({
    entryScriptUrls: ["/assets/index-AAAAAAAA.js"],
    assets: {
      "index-AAAAAAAA.js": 1_000,
      "shared-HOISTED.js": 2_000, // in the entry's closure, NOT referenced by HTML
    },
    manifestEntries: {
      "index.html": { file: "assets/index-AAAAAAAA.js", isEntry: true, imports: ["_shared-CHUNK.js"] },
      "_shared-CHUNK.js": { file: "assets/shared-HOISTED.js", isEntry: false, imports: [] },
    },
  });
  try {
    const result = await verifyBundleBudget({
      rootDir: root,
      budgets: { totalBytes: 50_000, eagerBytes: 50_000 },
    });
    // Eager = entry + statically-imported shared chunk (even though the HTML
    // has no link for it). Total unchanged.
    assert.equal(result.eagerJsBytes, 1_000 + 2_000);
    assert.equal(result.totalJsBytes, 1_000 + 2_000);
    assert.equal(result.manifestPresent, true);
  } finally {
    await cleanup(root);
  }
});

test("explicit: manifest entry dynamicImports contribute to total ONLY, never eager", async () => {
  // The entry's `dynamicImports` are deferred chunks: they must not add a single
  // eager byte, though Vite still lists them in the manifest. The static
  // `imports` closure is the only eager module graph; a lazy import appears only
  // under dynamicImports and must stay out of eager.
  const root = await createDistFixture({
    entryScriptUrls: ["/assets/index-AAAAAAAA.js"],
    assets: {
      "index-AAAAAAAA.js": 1_000,
      "deferred-VENDOR.js": 8_000, // under the entry's dynamicImports, missing from HTML
    },
    manifestEntries: {
      "index.html": {
        file: "assets/index-AAAAAAAA.js",
        isEntry: true,
        imports: [],
        dynamicImports: ["lazy-VENDOR.js"],
      },
      "lazy-VENDOR.js": { file: "assets/deferred-VENDOR.js", isEntry: false, imports: [] },
    },
  });
  try {
    const result = await verifyBundleBudget({
      rootDir: root,
      budgets: { totalBytes: 50_000, eagerBytes: 10_000 },
    });
    // 1000 eager (entry only); 1000+8000 total. The 8 KB lazy/vendor chunk must
    // never leak into eager.
    assert.equal(result.eagerJsBytes, 1_000);
    assert.equal(result.totalJsBytes, 1_000 + 8_000);
  } finally {
    await cleanup(root);
  }
});

test("fail-closed: manifest entry closure references an unknown import key", async () => {
  const root = await createDistFixture({
    entryScriptUrls: ["/assets/index-AAAAAAAA.js"],
    assets: { "index-AAAAAAAA.js": 1_000 },
    manifestEntries: {
      "index.html": { file: "assets/index-AAAAAAAA.js", isEntry: true, imports: ["_missing-CHUNK.js"] },
    },
  });
  try {
    await assert.rejects(
      verifyBundleBudget({ rootDir: root, budgets: { totalBytes: 50_000, eagerBytes: 50_000 } }),
      /is not a manifest key/
    );
  } finally {
    await cleanup(root);
  }
});

test("fail-closed: manifest eager closure names a JS asset that does not exist on disk", async () => {
  const root = await createDistFixture({
    entryScriptUrls: ["/assets/index-AAAAAAAA.js"],
    assets: { "index-AAAAAAAA.js": 1_000 }, // shared-HOISTED.js is missing on disk
    manifestEntries: {
      "index.html": { file: "assets/index-AAAAAAAA.js", isEntry: true, imports: ["_shared-CHUNK.js"] },
      "_shared-CHUNK.js": { file: "assets/shared-HOISTED.js", isEntry: false, imports: [] },
    },
  });
  try {
    await assert.rejects(
      verifyBundleBudget({ rootDir: root, budgets: { totalBytes: 50_000, eagerBytes: 50_000 } }),
      /(missing JS asset|file missing)/
    );
  } finally {
    await cleanup(root);
  }
});

// --- Schema-strictness negatives (bare shapes / wrong element types) ---
// Each malformed manifest shape must fail closed with a schema diagnostic, not
// be silently tolerated by the closure or the entry counter.

test("fail-closed: manifest top level is an array", async () => {
  const root = await createDistFixture({
    entryScriptUrls: ["/assets/index-AAAAAAAA.js"],
    assets: { "index-AAAAAAAA.js": 1_000 },
    manifestEntries: [],
  });
  try {
    await assert.rejects(
      verifyBundleBudget({ rootDir: root, budgets: { totalBytes: 50_000, eagerBytes: 50_000 } }),
      /top level must be a non-null, non-array object/
    );
  } finally {
    await cleanup(root);
  }
});

test("fail-closed: manifest top level is null", async () => {
  const root = await createDistFixture({
    entryScriptUrls: ["/assets/index-AAAAAAAA.js"],
    assets: { "index-AAAAAAAA.js": 1_000 },
    manifestNull: true,
  });
  try {
    await assert.rejects(
      verifyBundleBudget({ rootDir: root, budgets: { totalBytes: 50_000, eagerBytes: 50_000 } }),
      /manifest must be an object|top level must be a non-null, non-array object/
    );
  } finally {
    await cleanup(root);
  }
});

test("fail-closed: manifest top level is a primitive string (exercises the non-object branch)", async () => {
  const root = await createDistFixture({
    entryScriptUrls: ["/assets/index-AAAAAAAA.js"],
    assets: { "index-AAAAAAAA.js": 1_000 },
    manifestEntries: "not-an-object",
  });
  try {
    await assert.rejects(
      verifyBundleBudget({ rootDir: root, budgets: { totalBytes: 50_000, eagerBytes: 50_000 } }),
      /top level must be a non-null, non-array object|manifest must be an object/
    );
  } finally {
    await cleanup(root);
  }
});

test("fail-closed: a manifest record is null", async () => {
  const root = await createDistFixture({
    entryScriptUrls: ["/assets/index-AAAAAAAA.js"],
    assets: { "index-AAAAAAAA.js": 1_000 },
    manifestEntries: {
      "src/entry.ts": null,
    },
  });
  try {
    await assert.rejects(
      verifyBundleBudget({ rootDir: root, budgets: { totalBytes: 50_000, eagerBytes: 50_000 } }),
      /must be a non-null, non-array object/
    );
  } finally {
    await cleanup(root);
  }
});

test("fail-closed: a manifest record omits its file entirely", async () => {
  const root = await createDistFixture({
    entryScriptUrls: ["/assets/index-AAAAAAAA.js"],
    assets: { "index-AAAAAAAA.js": 1_000 },
    manifestEntries: {
      "src/entry.ts": { isEntry: true, imports: [] },
    },
  });
  try {
    await assert.rejects(
      verifyBundleBudget({ rootDir: root, budgets: { totalBytes: 50_000, eagerBytes: 50_000 } }),
      /"file" must be a non-empty string/
    );
  } finally {
    await cleanup(root);
  }
});

test("fail-closed: a manifest record is a bare array", async () => {
  const root = await createDistFixture({
    entryScriptUrls: ["/assets/index-AAAAAAAA.js"],
    assets: { "index-AAAAAAAA.js": 1_000 },
    manifestEntries: {
      "src/entry.ts": ["assets/index-AAAAAAAA.js"],
    },
  });
  try {
    await assert.rejects(
      verifyBundleBudget({ rootDir: root, budgets: { totalBytes: 50_000, eagerBytes: 50_000 } }),
      /must be a non-null, non-array object/
    );
  } finally {
    await cleanup(root);
  }
});

test("fail-closed: a manifest record is a bare string", async () => {
  const root = await createDistFixture({
    entryScriptUrls: ["/assets/index-AAAAAAAA.js"],
    assets: { "index-AAAAAAAA.js": 1_000 },
    manifestEntries: { "src/entry.ts": "assets/index-AAAAAAAA.js" },
  });
  try {
    await assert.rejects(
      verifyBundleBudget({ rootDir: root, budgets: { totalBytes: 50_000, eagerBytes: 50_000 } }),
      /must be a non-null, non-array object/
    );
  } finally {
    await cleanup(root);
  }
});

test("fail-closed: record file is an empty string", async () => {
  const root = await createDistFixture({
    entryScriptUrls: ["/assets/index-AAAAAAAA.js"],
    assets: { "index-AAAAAAAA.js": 1_000 },
    manifestEntries: { "src/entry.ts": { file: "", isEntry: true, imports: [] } },
  });
  try {
    await assert.rejects(
      verifyBundleBudget({ rootDir: root, budgets: { totalBytes: 50_000, eagerBytes: 50_000 } }),
      /"file" must be a non-empty string/
    );
  } finally {
    await cleanup(root);
  }
});

test("fail-closed: record file is not a string", async () => {
  const root = await createDistFixture({
    entryScriptUrls: ["/assets/index-AAAAAAAA.js"],
    assets: { "index-AAAAAAAA.js": 1_000 },
    manifestEntries: { "src/entry.ts": { file: 123, isEntry: true, imports: [] } },
  });
  try {
    await assert.rejects(
      verifyBundleBudget({ rootDir: root, budgets: { totalBytes: 50_000, eagerBytes: 50_000 } }),
      /"file" must be a non-empty string|could not be read/
    );
  } finally {
    await cleanup(root);
  }
});

test("fail-closed: isEntry is a truthy string, not a boolean", async () => {
  const root = await createDistFixture({
    entryScriptUrls: ["/assets/index-AAAAAAAA.js"],
    assets: { "index-AAAAAAAA.js": 1_000 },
    manifestEntries: { "src/entry.ts": { file: "assets/index-AAAAAAAA.js", isEntry: "yes", imports: [] } },
  });
  try {
    await assert.rejects(
      verifyBundleBudget({ rootDir: root, budgets: { totalBytes: 50_000, eagerBytes: 50_000 } }),
      /"isEntry" must be a boolean when present/
    );
  } finally {
    await cleanup(root);
  }
});

test("fail-closed: isEntry is a number", async () => {
  const root = await createDistFixture({
    entryScriptUrls: ["/assets/index-AAAAAAAA.js"],
    assets: { "index-AAAAAAAA.js": 1_000 },
    manifestEntries: { "src/entry.ts": { file: "assets/index-AAAAAAAA.js", isEntry: 1, imports: [] } },
  });
  try {
    await assert.rejects(
      verifyBundleBudget({ rootDir: root, budgets: { totalBytes: 50_000, eagerBytes: 50_000 } }),
      /"isEntry" must be a boolean when present/
    );
  } finally {
    await cleanup(root);
  }
});

test("fail-closed: imports contains a non-string element", async () => {
  const root = await createDistFixture({
    entryScriptUrls: ["/assets/index-AAAAAAAA.js"],
    assets: { "index-AAAAAAAA.js": 1_000 },
    manifestEntries: {
      "src/entry.ts": { file: "assets/index-AAAAAAAA.js", isEntry: true, imports: [42] },
    },
  });
  try {
    await assert.rejects(
      verifyBundleBudget({ rootDir: root, budgets: { totalBytes: 50_000, eagerBytes: 50_000 } }),
      /"imports" must be an array of non-empty strings/
    );
  } finally {
    await cleanup(root);
  }
});

test("fail-closed: imports contains an empty-string element", async () => {
  const root = await createDistFixture({
    entryScriptUrls: ["/assets/index-AAAAAAAA.js"],
    assets: { "index-AAAAAAAA.js": 1_000 },
    manifestEntries: {
      "src/entry.ts": { file: "assets/index-AAAAAAAA.js", isEntry: true, imports: [""] },
    },
  });
  try {
    await assert.rejects(
      verifyBundleBudget({ rootDir: root, budgets: { totalBytes: 50_000, eagerBytes: 50_000 } }),
      /"imports" must be an array of non-empty strings/
    );
  } finally {
    await cleanup(root);
  }
});

test("fail-closed: dynamicImports contains a non-string element", async () => {
  const root = await createDistFixture({
    entryScriptUrls: ["/assets/index-AAAAAAAA.js"],
    assets: { "index-AAAAAAAA.js": 1_000 },
    manifestEntries: {
      "src/entry.ts": { file: "assets/index-AAAAAAAA.js", isEntry: true, imports: [], dynamicImports: [null] },
    },
  });
  try {
    await assert.rejects(
      verifyBundleBudget({ rootDir: root, budgets: { totalBytes: 50_000, eagerBytes: 50_000 } }),
      /"dynamicImports" must be an array of non-empty strings/
    );
  } finally {
    await cleanup(root);
  }
});

test("fail-closed: css contains a non-string element", async () => {
  const root = await createDistFixture({
    entryScriptUrls: ["/assets/index-AAAAAAAA.js"],
    assets: { "index-AAAAAAAA.js": 1_000 },
    manifestEntries: {
      "src/entry.ts": { file: "assets/index-AAAAAAAA.js", isEntry: true, imports: [], css: [7] },
    },
  });
  try {
    await assert.rejects(
      verifyBundleBudget({ rootDir: root, budgets: { totalBytes: 50_000, eagerBytes: 50_000 } }),
      /"css" must be an array of non-empty strings/
    );
  } finally {
    await cleanup(root);
  }
});

test("fail-closed: assets contains a non-string element", async () => {
  const root = await createDistFixture({
    entryScriptUrls: ["/assets/index-AAAAAAAA.js"],
    assets: { "index-AAAAAAAA.js": 1_000 },
    manifestEntries: {
      "src/entry.ts": { file: "assets/index-AAAAAAAA.js", isEntry: true, imports: [], assets: [false] },
    },
  });
  try {
    await assert.rejects(
      verifyBundleBudget({ rootDir: root, budgets: { totalBytes: 50_000, eagerBytes: 50_000 } }),
      /"assets" must be an array of non-empty strings/
    );
  } finally {
    await cleanup(root);
  }
});

// --- Entry-binding schema ---

test("fail-closed: manifest entry file does not end in .js", async () => {
  const root = await createDistFixture({
    entryScriptUrls: ["/assets/index-AAAAAAAA.js"],
    assets: { "index-AAAAAAAA.js": 1_000 },
    manifestEntries: {
      "src/entry.ts": { file: "assets/index-AAAAAAAA.css", isEntry: true, imports: [] },
    },
  });
  try {
    await assert.rejects(
      verifyBundleBudget({ rootDir: root, budgets: { totalBytes: 50_000, eagerBytes: 50_000 } }),
      /entry "file" must end in \.js/
    );
  } finally {
    await cleanup(root);
  }
});

test("fail-closed: a plain script carrying data-note='type=\"module\"' is NOT misclassified as a module entry", async () => {
  // This is the DISTINGUISHING parser negative. A plain (non-module) script
  // legitimately carries an unrelated attribute whose value *happens to contain*
  // `type="module"` — here data-note points that substring into the tag-body:
  //   <script data-note='type="module"' src="/assets/plain.js"> ...
  //
  // The OLD boundary-less regex (/\btype\s*=\s*["']module["']/) matched the
  // `type="module"` substring INSIDE the data-note VALUE and misclassified this
  // plain script as a module entry. The NEW whitespace/start-anchored
  // marker ((?:^|\s)type\s*=\s*["']module["']) requires `type` to be its own
  // attribute (preceded by whitespace or the start of the tag), so `type` buried
  // inside another attribute's quoted value does not match. The result: this
  // fake is NOT an entry, the binding sees zero module scripts, and the gate
  // fails closed on "exactly one" — proving the parser no longer mistakes
  // attribute-impersonation for a real module entry.
  const root = await createDistFixture({
    entryScriptUrls: ["/assets/index-AAAAAAAA.js"],
    assets: { "index-AAAAAAAA.js": 1_000 },
  });
  try {
    await import("node:fs/promises").then(async ({ writeFile, utimes }) => {
      const idx = join(root, "dist", "index.html");
      await writeFile(
        idx,
        `<!doctype html><html lang="en"><head><script data-note='type="module"' src="/assets/plain.js"></script></head></html>`
      );
      const future = new Date(Date.now() + 3600_000);
      await utimes(idx, future, future);
    });
    await assert.rejects(
      verifyBundleBudget({ rootDir: root, budgets: { totalBytes: 50_000, eagerBytes: 50_000 } }),
      /exactly one <script type="module"> entry/
    );
  } finally {
    await cleanup(root);
  }
});