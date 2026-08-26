import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const workflowsDir = resolve(repoRoot, ".github", "workflows");
const actionShaPattern = /uses:\s*[^@\s]+@[0-9a-f]{40}(?:\s|#|$)/;

async function workflow(name) {
  return readFile(resolve(workflowsDir, name), "utf8");
}

function assertPinnedActions(contents, label) {
  const uses = contents.match(/^\s*-\s*uses:\s*.+$/gm) ?? [];
  assert.ok(uses.length > 0, `${label} must use only pinned actions`);
  for (const entry of uses) {
    assert.match(entry, actionShaPattern, `${label} has an unpinned action: ${entry.trim()}`);
  }
}

export async function verifyPagesWorkflows() {
  const [deploy, monitor, smoke, verify, packageJson, packageLock] = await Promise.all([
    workflow("deploy-cloudflare-pages.yml"),
    workflow("manual-pages-smoke.yml"),
    readFile(resolve(repoRoot, "scripts", "smoke-pages-deployment.sh"), "utf8"),
    workflow("verify.yml"),
    readFile(resolve(repoRoot, "package.json"), "utf8"),
    readFile(resolve(repoRoot, "package-lock.json"), "utf8"),
  ]);

  assert.match(deploy, /^\s*workflow_dispatch:\s*$/m);
  assert.doesNotMatch(deploy, /^\s*workflow_run:\s*$/m);
  assert.doesNotMatch(deploy, /^\s*schedule:\s*$/m);
  assert.match(deploy, /commit_sha:/);
  assert.match(deploy, /confirm_deploy/);
  assert.match(deploy, /inputs\.confirm_deploy == 'DEPLOY'/);
  assert.match(deploy, /^permissions:\n\s+actions: read\n\s+contents: read$/m);
  assert.match(deploy, /No successful Verify push run exists for the requested main SHA/);
  assert.match(deploy, /actions\/workflows\/verify\.yml\/runs\?head_sha=\$COMMIT_SHA&event=push&status=completed/);
  assert.match(deploy, /\.path == "\.github\/workflows\/verify\.yml"/);
  assert.match(deploy, /\.name == "Verify"/);
  assert.match(deploy, /\.conclusion == "success"/);
  assert.match(deploy, /\.head_branch == "main"/);
  assert.match(deploy, /Require REL-05 governed release composition/);
  assert.match(deploy, /src\/data\/official\/release-artifact\.json/);
  assert.match(deploy, /src\/data\/official\/release-authorization\.json/);
  assert.match(deploy, /scripts\/verify-governed-release-composition\.mjs/);
  assert.match(deploy, /name: Set up Node[\s\S]*node-version: '22'/);
  assert.match(verify, /node-version: '20'/);
  assert.doesNotMatch(deploy, /^\s*pull_request:\s*$/m);
  assert.match(deploy, /name: cloudflare-pages-production/);
  assert.match(deploy, /CLOUDFLARE_API_TOKEN: \$\{\{ secrets\.CLOUDFLARE_API_TOKEN \}\}/);
  assert.match(deploy, /CLOUDFLARE_ACCOUNT_ID: \$\{\{ secrets\.CLOUDFLARE_ACCOUNT_ID \}\}/);
  assert.match(deploy, /CLOUDFLARE_PAGES_PROJECT: \$\{\{ secrets\.CLOUDFLARE_PAGES_PROJECT \}\}/);
  assert.match(packageJson, /"wrangler": "4\.126\.0"/);
  const lock = JSON.parse(packageLock);
  assert.equal(lock.packages[""].devDependencies.wrangler, "4.126.0");
  assert.equal(lock.packages["node_modules/wrangler"].version, "4.126.0");
  assert.match(deploy, /npx --no-install wrangler pages deploy dist/);
  assert.doesNotMatch(deploy, /npx --yes|wrangler@/);
  assert.match(deploy, /--commit-hash "\$COMMIT_SHA"/);
  assert.match(deploy, /Cloudflare Pages project must be a Direct Upload project without a Git source/);
  assert.match(deploy, /https:\/\/api\.cloudflare\.com\/client\/v4\/accounts\/\$CLOUDFLARE_ACCOUNT_ID\/pages\/projects\/\$CLOUDFLARE_PAGES_PROJECT/);
  assert.match(deploy, /\.result\.source\? == null/);
  assert.doesNotMatch(deploy, /echo[^\n]*project_json/);
  assert.match(deploy, /deployment_url=/);
  assert.match(deploy, /smoke-pages-deployment\.sh/);
  for (const command of [
    "verify:official-artifact",
    "typecheck",
    "typecheck:test",
    "npm test",
    "npm run build",
    "verify:build-provenance",
    "verify:pages-static",
    "verify:bundle-budget",
  ]) {
    assert.ok(deploy.includes(command), `deployment candidate must run ${command}`);
  }
  assert.doesNotMatch(deploy, /_worker\.js|functions\/|analytics|Strict-Transport-Security/i);
  assertPinnedActions(deploy, "deploy-cloudflare-pages.yml");

  assert.match(monitor, /^\s*workflow_dispatch:\s*$/m);
  assert.doesNotMatch(monitor, /^\s*schedule:\s*$/m);
  assert.doesNotMatch(monitor, /^\s*pull_request:\s*$/m);
  assert.match(monitor, /confirm_smoke/);
  assert.match(monitor, /inputs\.confirm_smoke == 'SMOKE'/);
  assert.match(monitor, /^\s+issues: write$/m);
  assert.match(monitor, /name: cloudflare-pages-monitoring/);
  assert.match(monitor, /if: failure\(\)/);
  assert.match(monitor, /\[pages-smoke\] deployment smoke failure/);
  assert.match(monitor, /--request PATCH/);
  assert.match(monitor, /--request POST/);
  assert.match(monitor, /\.title == \$title/);
  assert.match(monitor, /github-actions\[bot\]/);
  assert.match(monitor, /pages-smoke-workflow-owned/);
  assert.match(monitor, /contains\(\$marker\)/);
  assert.match(monitor, /gh api --paginate/);
  assert.match(monitor, /printf -v body '%s\\n\\n- Run: %s\\n- Target: %s\\n- Commit: %s\\n\\n%s\\n%s'/);
  assert.doesNotMatch(monitor, /body="\$\(cat <<EOF/);
  assert.doesNotMatch(monitor, /\n[ \t]+- (Run|Target|Commit):/);
  assert.doesNotMatch(monitor, /labels=|labels:/);
  assert.match(monitor, /safe_target=/);
  assert.doesNotMatch(monitor, /CLOUDFLARE_API_TOKEN|CLOUDFLARE_ACCOUNT_ID|CLOUDFLARE_PAGES_PROJECT/);
  assertPinnedActions(monitor, "manual-pages-smoke.yml");

  assert.match(smoke, /pages-smoke-url\.mjs/);
  assert.match(smoke, /--proto '=https'/);
  assert.doesNotMatch(smoke, /--location|--fail-with-body/);
  assert.match(smoke, /final_headers/);
  assert.match(smoke, /Root response has enforcing Content-Security-Policy before HOST-03 evidence/);
  for (const requiredCheck of [
    "request /",
    "pages-smoke-not-found",
    "request /robots.txt",
    "canonical",
    "x-content-type-options",
    "referrer-policy",
    "x-frame-options",
    "permissions-policy",
    "content-security-policy",
    "content-security-policy-report-only",
    "content-type:[[:space:]]*text\/html",
    "request /favicon.svg",
    "image\/svg\\\+xml",
    "request /social-preview.png",
    "image\/png",
    "89504e470d0a1a0a",
    "text/plain",
    "x-robots-tag:.*noindex",
    "Canonical host root response must not be noindexed",
  ]) {
    assert.ok(smoke.includes(requiredCheck), `post-deploy smoke script must check ${requiredCheck}`);
  }

  return { deploy: "deploy-cloudflare-pages.yml", monitor: "manual-pages-smoke.yml" };
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  verifyPagesWorkflows()
    .then(() => console.log("Pages workflow verification passed."))
    .catch((error) => {
      console.error(error instanceof Error ? error.message : error);
      process.exitCode = 1;
    });
}
