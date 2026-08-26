# Real-data-only launch: final local integration handoff

**Checkpoint:** 2026-08-26
**Repository:** `0x3-team/ai-benchmark-aggregator`
**Visibility:** public
**Integrated code baseline:** `08b2916813baf698ff4f7d58bb142c3337d7c339` on `main`
**Closing lane:** PR #21 originally added the preserved plan, local routing
receipts, and this final handoff to that baseline. The local routing receipts
were later removed from the public tree as a security remediation.

## Outcome

The scoped repository implementation is integrated. PRs #12 through #20 and
the TypeScript 7 dependency PR #6 were reviewed, repaired where required,
validated on their exact final heads, and merged into `main`. No implementation
or dependency PR remains for this checkpoint.

The application now has the intended code boundaries:

- runtime synthetic benchmark data is removed;
- the frontend stays in an awaiting-publication state until one governed
  Official release is supplied;
- official-source candidates remain inactive and certify nothing;
- source fetching is capability-gated and fail-closed;
- publication requires the external release-authorization contract;
- sparse rankings use the documented coverage and missing-cell policy;
- private recheck and Cloudflare Pages workflows are guarded candidates, not
  active production operations;
- TypeScript 7.0.2 is integrated with explicit Vite and Node ambient types.

The repository was verified public during closeout and must remain public so
GitHub Actions can run under the intended public-repository policy.

## Merged pull requests

| PR | Result | Merge commit |
| --- | --- | --- |
| #12 | Static launch shell and repository hygiene merged | `d4aa4a36eb4d67f4c8779d0dcd53964ff4a4187d` |
| #13 | Bounded source-certification candidates merged | `dda5e62145b8b542d8509781b2f28d0e0ec98528` |
| #14 | Synthetic runtime data removal merged | `149eb7c7de64da18a1478ea2de9e5db5ff4c7a4a` |
| #15 | Capability-gated pinned HTTPS transport merged | `6475af188788383e30b4b736cc6610622981c1b1` |
| #16 | Governed Official release-authorization boundary merged | `372f98f6ee8a911323d8550c43ad5820d1e61cbf` |
| #17 | Inactive source-adapter candidates merged | `5a27291a27a8a694e996d2875a27e4d3075e2918` |
| #18 | Inert private-recheck candidate merged | `472e782212c3c28442fa95a10816a2af6ea9bc0a` |
| #19 | Conservative sparse-ranking policy merged | `184fd05ac904f795720a088d50fb651f6b0da841` |
| #20 | Guarded Pages deployment candidate merged | `58f731cff8403aa29ac72ef7d499398fbd151f31` |
| #6 | TypeScript 7.0.2 upgrade and config migration merged | `08b2916813baf698ff4f7d58bb142c3337d7c339` |

PR #21 was the closing documentation lane. Its merge placed this handoff and
the preserved execution baseline on `main`; it did not activate a source,
publish data, or deploy the site.

## Accepted verification

The following checks passed on the final integrated code tree before PR #21 was
closed:

- locked local ledger suite: **1,672 passed, 14 skipped**;
- frontend unit suite: **20 files, 99 tests passed**;
- app typecheck and test typecheck with TypeScript 7.0.2;
- production frontend build;
- Official artifact contract verifier;
- build-provenance create and verify checks;
- Pages static and workflow control suites;
- bundle budget: eager JavaScript 492,897 bytes and total JavaScript 1,223,017
  bytes, within the 1,100,000 and 1,500,000 byte limits;
- headless 390 px overflow gate: document width 390/390 and table scroll width
  750/356;
- `npm audit`: zero vulnerabilities.

The exact final heads of PR #19 and PR #6 also passed GitHub's Frontend, Ledger,
and Clean Archive jobs before merge. PR #21 must pass those jobs on its final
documentation head before it is merged. Historical green results were not used
as evidence for newer heads.

## Production state

Code integration is complete for this checkpoint. Production launch is still
not authorized or performed. This is an external governance and operations
boundary, not an unmerged code lane.

No operation in this checkpoint did any of the following:

- certify an official source revision;
- capture live source bytes;
- admit or publish an Official result claim;
- create a release authorization or signed release artifact;
- create private-runner credentials or a private data repository;
- configure a Cloudflare Direct Upload project, environment, secret, or DNS;
- deploy, run a live production smoke test, promote HSTS/CSP, or perform a paid
  operation.

The remaining production gates are:

- an approved source-revision certification decision;
- live capture, idempotency, freshness, and evidence-replay receipts;
- model identity review and launch-coverage acceptance;
- H4 lease-fenced runner infrastructure and private-data controls;
- an external release signer/authorization and one canonical governed artifact;
- Cloudflare account configuration, release composition, DNS, deployment,
  live header/browser evidence, and rollback evidence.

Do not treat public repository visibility, green fixture tests, inactive source
rows, the private-recheck workflow, or the Pages workflow as proof that any of
these production gates passed.

## Local continuation

After PR #21 is merged, the canonical checkout sequence is:

```bash
git fetch --all --prune
git switch main
git pull --ff-only
```

The normal verification commands are:

```bash
cd ledger
uv tool run --from 'uv==0.11.18' uv run --locked --extra dev pytest -q

cd ..
npm ci
npm run typecheck
npm run typecheck:test
npm test
npm run build
npm run verify:official-artifact
npm run verify:build-provenance
npm run verify:pages-static
npm run verify:pages-workflows
npm run verify:bundle-budget
npm run test:mobile-overflow
```

## Preserved public record

- Execution baseline: `docs/plans/2026-08-26-real-data-only-production-launch-execution-plan.md`

Local provider, model, permission, authentication, catalog, task, terminal, and
cost-routing evidence is intentionally not tracked in this public repository.
This handoff is the current public status record for the integrated checkpoint.
