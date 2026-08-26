# Cloudflare Pages deployment candidate

This is a deployment candidate, not evidence that Cloudflare Pages, a custom
domain, DNS, TLS, or the repository's GitHub environments are configured. It
never runs for pull requests, pushes, schedules, or `workflow_run` events. An
owner must manually dispatch it with a full immutable commit SHA and type
`DEPLOY`.

ND4 blocks every public deployment today: the repository has neither the
REL-05 governed artifact and authorization paths nor their composition verifier.
The workflow fails before installation or deployment unless the requested SHA
contains `src/data/official/release-artifact.json`,
`src/data/official/release-authorization.json`, and
`scripts/verify-governed-release-composition.mjs`. Those paths and their exact
composition must land together in an approved REL-05 change. Automatic
promotion remains blocked until then; this workflow must not be changed to add
an automatic trigger as a substitute for the governed release boundary.

## Owner setup before the first deployment

1. Create the `cloudflare-pages-production` GitHub environment. Assign required
   reviewers and restrict it to `main` according to the repository's release
   policy. Add only the environment secrets `CLOUDFLARE_API_TOKEN`,
   `CLOUDFLARE_ACCOUNT_ID`, and `CLOUDFLARE_PAGES_PROJECT`; do not put their
   values in source, logs, issue bodies, or repository variables.
2. Limit the Cloudflare token to the intended account and Pages project with
   only the permission needed to deploy Pages. Confirm the account and project
   outside this repository before granting the environment access. The Pages
   project must be a Direct Upload project with no Git source or automatic
   integration. The workflow queries its project metadata immediately before
   deployment and fails closed when `result.source` is present.
3. In GitHub Actions settings, keep workflow permissions at their restrictive
   default. The manual smoke workflow needs `issues: write` only when an owner
   explicitly permits it. Create `cloudflare-pages-monitoring` with required
   reviewers before using that workflow.
4. Do not add a schedule until an owner has separately approved unattended
   monitoring, the environment protections, and the `issues: write` permission.
   The repository ships only the `workflow_dispatch` smoke workflow, so it is
   inert until an owner starts and approves it.

## What a deployment run does

Before checkout, the workflow queries GitHub Actions with its read-only
`actions: read` token and requires a successful `Verify` **push** run for the
exact SHA on `main`. It then requires the REL-05 composition described above.
Only after those gates does it install dependencies, run every frontend offline
verifier, build `dist/`, verify provenance and Pages controls, and use the
lockfile-resolved local `wrangler@4.126.0` to deploy that `dist/` directory. It
records the Verify run, checked-out commit, and Wrangler-reported deployment URL
in the job summary. The workflow then checks the direct deployment URL for a
root `200`, a real junk-route `404`, `robots.txt`, the expected canonical URL,
required headers and content types, favicon content type, and social-preview
PNG content type and magic bytes. It does not follow redirects.

The final `robots.txt` response must be `text/plain`. For a Pages preview host,
the final root response must carry `X-Robots-Tag: noindex`; on
`benchmark.0x3.dev`, that same root noindex value is rejected. The final root
response must retain
`Content-Security-Policy-Report-Only` and must not contain enforcing
`Content-Security-Policy` until HOST-03 provides the required live evidence.

No auto-rollback exists. A failed deployment or smoke check must be investigated
before another production action. The manual smoke workflow repeats the same
checks against an owner-supplied allowed HTTPS origin. On failure it creates or
updates only the one open Pages-smoke issue with the exact title, the
`github-actions[bot]` author, and its hidden workflow-owned marker. A
same-title user issue is never overwritten; no pre-existing label is required,
and no unvalidated URL reaches the issue body. It neither deploys nor rolls
back anything.

## Manual rollback to a prior green commit

1. After REL-05 has supplied the required governed release composition, identify
   a prior successful `Verify` push run and its full 40-character commit SHA,
   plus its successful Pages deployment and smoke receipts. Do not use a branch
   name, abbreviated SHA, or a commit without a green verification record.
2. In GitHub Actions, select **Deploy Cloudflare Pages**, choose **Run
   workflow**, enter that full SHA as `commit_sha`, type `DEPLOY`, and request
   the production environment approval. This follows the same GitHub Verify,
   REL-05 composition, offline verification, exact-`dist/` deployment, and
   smoke path as a forward deployment.
3. Record the rollback run URL, prior green commit SHA, new Pages deployment
   URL, and post-deploy smoke result in the release record. If any verification
   or smoke step fails, stop; there is deliberately no automatic fallback.

This candidate does not configure a Worker, Functions, DNS, HSTS, analytics,
or a Cloudflare project. Those changes need their own owner-approved decision
and evidence.
