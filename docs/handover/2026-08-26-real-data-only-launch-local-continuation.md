# Real-data-only launch: local continuation handoff

**Checkpoint:** 2026-08-26  
**Repository:** `0x3-team/ai-benchmark-aggregator`  
**Main observed at:** `21d24dc8534dfe6b179ec692c7e2dd29bc7ce182`  
**Execution state:** stopped by owner request; continue strictly outside this Capy thread  
**Merge authority:** the owner reviews and merges every pull request

## Executive state

All task agents were stopped before this checkpoint. Every intentional working
tree was committed and pushed to its existing GitHub pull-request branch. No
task-machine-only implementation work remains authoritative. Pull requests with
unfinished review remediation were converted to drafts and use `wip:` commits
so local continuation does not mistake preservation for acceptance.

The production application is **not launched**. No source is certified, no live
source bytes were captured, no Official claim was admitted, no release
authorization instance exists, no governed published artifact exists, and no
Cloudflare deployment or paid operation was performed.

The repository was made public by the owner. This restored GitHub Actions: the
four root PRs reached green Ledger, Frontend, and Clean Archive jobs before
subsequent review-fix pushes. New pushes must be checked again; a historical
green check is not evidence for a newer head.

## GitHub pull-request graph

| PR | Branch / head at checkpoint | Base | State | Local continuation action |
| --- | --- | --- | --- | --- |
| #12 | `capy/harden-static-launch-shell` / `e9e0f18` | `main` | Open; CSP review fix complete and pushed | Wait for the new-head CI/review. The enforcing CSP was removed; report-only remains until HOST-03 live evidence. |
| #13 | `capy/prepare-bounded-source` / `dd60e44` | `main` | Open; locally accepted; root CI was green | Owner review/merge candidate. It certifies nothing. |
| #14 | `capy/remove-synthetic-runtime-data` / `f9366c1` | `main` | **Draft WIP checkpoint** | Finish and rerun the real-only documentation, fixture-import guard, and inventory-generator remediation. |
| #15 | `capy/add-capability-gated-pinned` / `01da914` | `main` | **Draft WIP checkpoint** | Finish and rerun transport remediation for DNS deadline, address retries/classes, complete framing, and truncation. |
| #16 | `capy/add-official-release-authorization` / `8901d7c` | `capy/remove-synthetic-runtime-data` | **Draft WIP checkpoint** | Finish six REL-05 findings, then integrate the final #14 head and rerun wheel, ledger, Node, browser, and build gates. |
| #17 | `capy/add-inactive-source-adapter-candidates` / `ce9bcdd` | `capy/prepare-bounded-source` | Open; locally accepted | After #13 merges, integrate `main`, retarget, and rerun full locked ledger CI. |
| #18 | `capy/add-private-ledger-recheck-final` / `045cda5` | `capy/add-capability-gated-pinned` | **Draft WIP checkpoint** | Finish six containment findings, then integrate the final #15 head and rerun full locked ledger/workflow checks. |
| #19 | `capy/add-sparse-ranking-policy` / `fd65078` | `capy/add-official-release-authorization` | **Draft due to moving base** | Its own two review fixes passed focused/full frontend and rendered mobile checks. Integrate final #16, resolve, then rerun every frontend/verifier gate. |
| #20 | `capy/add-guarded-pages-deployment` / `2c96c7f` | `capy/harden-static-launch-shell` | **Draft WIP checkpoint** | Finish provider/robots/incident/Node remediation and rerun. It already includes #12's report-only CSP base fix. |

No pull request was merged or configured for auto-merge.

## Review remediation preserved on GitHub

### PR #12 — HOST-03 CSP sequencing

The valid review thread was fixed and resolved in `e9e0f18`:

- removed enforcing `Content-Security-Policy`;
- retained the complete `Content-Security-Policy-Report-Only` policy;
- made static verifiers reject enforcing CSP and HSTS before provider/browser
  receipts and CSP report review.

Focused static, build-provenance, frontend, and no-network checks passed locally.

### PR #14 — real-only root, preserved as draft

Checkpoint `f9366c1` contains work for three valid findings:

- release runbook and PR template now describe immutable empty
  awaiting-publication or one governed Official release, never Demo fallback;
- runtime fixture guards recognize the actual `src/data/testFixtures.ts` path;
- model-inventory generation reads and validates the tracked unavailable
  Official artifact instead of deleted `src/data/models.json`, with a new test
  module and deterministic timestamp support.

The first version passed frontend gates and a deterministic inventory rehearsal.
The final digest-hardening edit was checkpointed when work stopped and must be
rerun locally before the PR leaves draft.

Open review comment IDs: `3859922471`, `3859922466`, `3859922462`.

### PR #15 — pinned transport, preserved as draft

Checkpoint `01da914` preserves fixes in progress for all five valid findings:

- accept completed Content-Length, chunked, and connection-close framing while
  rejecting truncated Content-Length;
- reject multicast/reserved/unspecified/non-unicast addresses in both policy
  and transport layers;
- try validated DNS addresses under one shared deadline;
- include bounded DNS resolution in the request budget;
- retain peer pinning, hostname TLS verification, byte caps, and disabled
  default composition.

This checkpoint was intentionally pushed without a final acceptance claim.
Open review comment IDs: `3860012470`, `3860012464`, `3860012461`,
`3860012450`, `3860012445`.

### PR #16 — release boundary, preserved as draft

Checkpoint `8901d7c` preserves partial remediation for six valid findings:

- JavaScript-compatible UTF-16 ordering;
- wheel-packaged v2 schema with docs/package parity;
- credential-free public query URLs;
- durable claim review/publication decision binding;
- browser-compatible timestamp precision;
- deterministic, source-bound public evidence translation.

The edit is incomplete/unaccepted. Do not create an authorization or published
artifact from this branch until built-wheel and cross-runtime tests pass.
Open review comment IDs: `3860212058`, `3860212053`, `3860212043`,
`3860212034`, `3860212029`, `3860212018`.

### PR #18 — private runner, preserved as draft

Checkpoint `045cda5` preserves partial remediation for six valid findings:

- bind snapshot storage below the private data checkout;
- reject a symlinked repository root before resolution;
- reject ignored artifacts and account for every walked artifact;
- prove staged Git blobs equal raw worktree bytes without filters;
- push to a reconstructed expected GitHub destination under sanitized config;
- count only workflow runs that actually executed the private-runner job.

The workflow remains schedule-inert and `H4_BLOCKED`; no credentials or private
data repository were created. Open review comment IDs: `3860288729`,
`3860288726`, `3860288718`, `3860288712`, `3860288706`, `3860288702`.

### PR #19 — sparse ranking remediation complete, base not final

Checkpoint `fd65078` documents the UI-only 60% coverage and
`models.length + 1` missing-cell penalty in README/AGENTS and uses one two-axis
table scrollport so sticky rank/model columns remain pinned. The rendered 390px
test sets `scrollLeft`, proves sticky cells stay fixed, and proves benchmark
headers move. Its review threads `3860248359` and `3860248352` were resolved.

Do not mark it ready until final #16 is integrated and all frontend gates are
rerun against that exact tree.

### PR #20 — deployment candidate, preserved as draft

Checkpoint `2c96c7f` preserves partial remediation for five valid findings:

- use Node 22 for locked Wrangler 4.126;
- require a Cloudflare Direct Upload project with no Git source;
- require plain-text robots and host-specific noindex behavior;
- deduplicate only workflow-owned incident issues;
- require report-only CSP and reject enforcing CSP before HOST-03 evidence.

The workflow remains manual-only and blocked on absent REL-05 composition.
Open review comment IDs: `3860301230`, `3860301223`, `3860301222`,
`3860301216`, `3860301206`.

## Accepted local evidence before the stop

- PR #17 integrated source adapters: 113 focused tests; full locked ledger
  suite **1,604 passed, 11 skipped**.
- PR #16 pre-review version: full frontend **93 passed**, 8 artifact-verifier
  tests, 31 focused ledger tests, build/provenance/static/budget gates.
- PR #19 through `fd65078`: full frontend **98 passed**; rendered 390px
  document `390/390`, table scrollport `737/356`, and sticky-column movement
  assertions passed.
- PR #18 pre-review version: parent focused suite **56 passed**; worker suite
  **136 passed**.
- PR #20 pre-review version: frontend **96 passed**, workflow/URL/smoke suite
  **15 passed**, full ledger retry **1,539 passed, 11 skipped**, zero audit
  vulnerabilities.
- Root PRs #12–#15 all reached green Ledger, Frontend, and Clean Archive jobs
  after repository visibility changed. Later WIP heads require fresh checks.

These receipts are historical proof for the named commit only. They do not
transfer to newer WIP heads or to a final integrated `main`.

## Recommended local continuation order

1. Finish #14 and #15 independently. Run their complete local gates and leave
   every external review thread with a concrete reply before resolving it.
2. Merge only after owner review and fresh remote CI. The owner may merge #13
   separately because its source-candidate work is non-activating.
3. After #14 is final, merge it into #16; finish #16 and rerun built-wheel,
   ledger, Node verifier, browser parser, typecheck, tests, and build gates.
4. Merge final #16 into #19 and rerun the full frontend plus rendered 390px
   suite.
5. After #15 is final, merge it into #18; finish the private-runner adversarial
   suite while keeping H4 blocked.
6. Finish #20 on the latest #12. Do not dispatch it: REL-05 composition,
   GitHub environments, Cloudflare Direct Upload configuration, and release
   authorization do not exist.
7. After #13, integrate #17 and rerun the full locked ledger suite.
8. Revalidate every stack on the eventual merged `main`; stacked PR checks do
   not substitute for final-tree evidence.

Useful commands:

```bash
git fetch origin
gh pr checkout <number>
git status --short
git log --oneline --decorate -5

cd ledger
uv tool run --from 'uv==0.11.18' uv run --locked --extra dev pytest -q
uv tool run --from 'uv==0.11.18' uv run python scripts/verify_ci_lock.py

cd ..
npm ci
npm run typecheck
npm run typecheck:test
npm test
npm run build
npm run verify:official-artifact
npm run verify:build-provenance
npm run verify:pages-static
npm run verify:bundle-budget
```

Run `npm run test:mobile-overflow` on #19 or descendants. Run
`npm run verify:pages-workflows` on #20 or descendants.

## Production blockers that code checkpointing did not solve

- No approved source-revision certification decision exists.
- No live source capture, idempotency, freshness, or evidence-replay receipt
  exists.
- Current-source sufficiency remains unresolved. Research found LMArena and
  MTEB the clearest current permissive structured candidates; MTEB exceeds the
  current resource contract, while AGC-Bench, ELBench, and EvalPlus are dated
  or fixture-only candidates.
- Model identity review and launch coverage gates are incomplete.
- H4 lease-fenced execution, private data repository, and runner credentials
  do not exist.
- No external release signer/authorization, canonical published artifact, or
  atomic runtime composition exists.
- Cloudflare environments, secrets, Direct Upload project confirmation, DNS,
  deployment receipt, live header/browser smoke, rollback receipt, and HSTS/CSP
  promotion evidence do not exist.

Do not substitute public repository visibility, a green fixture test, a source
license, an inactive registry row, or a deployment workflow for any of those
governance and live-operation receipts.

## Preserved supporting artifacts

- Execution plan: `docs/plans/2026-08-26-real-data-only-production-launch-execution-plan.md`
- Routing/acceptance receipts: `docs/audits/2026-08-26-launch-orchestration-receipts.jsonl`
- This handoff is the authoritative checkpoint for moving the remaining work
  to a local environment.
