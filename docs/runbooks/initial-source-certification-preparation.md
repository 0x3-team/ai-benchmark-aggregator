# Initial source certification preparation

**Status:** preparation only, as of 2026-07-15. No source below is certified,
captured by the ledger, approved for publication, or available in Official mode.
This runbook records candidate artifacts and blocking decisions; it is not an
authorization to fetch them.

## Boundary

- The public frontend remains static on Cloudflare Pages and consumes only the
  existing unavailable Official artifact.
- The default ledger transport refuses outbound traffic. A future fetch needs an
  approved private runner with peer-pinning and egress controls.
- Before H4 activation, repository owners must configure the
  `private-ledger-production` GitHub environment with required reviewers. The
  manual private-runner workflow admits only `refs/heads/main`; its fine-grained
  cross-repository data token is released after that environment gate and is
  scoped to the private data checkout and artifact push path.
- Source admission policy version source-admission-v2 binds the exact source
  revision, final URLs, one bounded fetch size, dimensions, numeric semantics,
  and an immutable typed-evidence contract.
- A passing fixture proves local parser behavior only. It does not prove source
  authority, terms, complete coverage, runner safety, certification, review,
  publication, or release eligibility.

## Candidate sequence

The reviewed technical sequence is BigCodeBench, then SWE-bench Verified, with
ARC-AGI deferred. Each step is conditional on a named data-governance owner and
written terms/reuse approval. Sources must not be bulk certified.

| Candidate | Full artifact under review | Evidence shape to prepare | Required decision before any fetch |
| --- | --- | --- | --- |
| BigCodeBench | One revision-pinned Parquet file: https://huggingface.co/datasets/bigcode/bigcodebench-results/resolve/08ceb6b15ecd9c0f7c82932e4e248208ffeeb9b4/data/train-00000-of-00001.parquet | A future Parquet-specific locator must bind each exact row and raw model/score columns. The current code has no enabled Parquet adapter. | Confirm result-data authority and reuse permission. The task-dataset Apache license is not evidence that result data may be republished. |
| SWE-bench Verified | One commit-pinned full JSON file: https://raw.githubusercontent.com/SWE-bench/swe-bench.github.io/7c4289f30aa1a1c63c2e2a25aae30c16d92b5114/data/leaderboards.json | Direct JSON uses json_path_v1. Historical embedded JSON uses json_script_path_v1 with one exact script id, type, category assertion, record path, and field map. | Confirm repository/result-data terms and display scope, then certify a source revision with an 8 MiB max-byte bound for the roughly 6.98 MiB file. |
| ARC-AGI | No automated artifact is approved. The configured arcprize.org JSON is deliberately not a collection target. | ARC-like JSON fixtures exercise numeric-lexeme and json_path_v1 behavior only. They do not define an ARC source contract. | Obtain written permission or a separately reviewed official artifact whose terms expressly permit this collection and display. |

External browser research is not ledger collection. It created no source snapshot,
claim, source decision, or publication record.

## Source-specific dimension rules

### BigCodeBench

- Treat complete and instruct as distinct source-reported metric dimensions.
  Do not average, choose by row order, or use type as a substitute score.
- Preserve the source model value exactly. Uncertain identity remains unresolved.
- The candidate must prove that its one pinned file is complete for the claimed
  source revision before extraction begins.
- The source owner, permitted public fields, split/setting/evaluation-version
  mapping, correction route, and retention obligations are UNASSIGNED.

### SWE-bench Verified

- Select exactly the Verified category; do not mix Community, preview, or other
  categories into a Verified claim.
- Preserve the reported resolved value as its raw lexical source value. The
  JSON path or named-script locator must re-resolve the same model and score.
- Review agent, setup, release/version, and leaderboard category semantics
  before declaring display dimensions. They must not be collapsed merely to
  simplify a UI cell.
- The source owner, terms/reuse approver, and certification reviewer are
  UNASSIGNED.

### ARC-AGI

- The ARC Prize terms page currently prohibits automated/non-human access and
  systematic retrieval/collection without written permission. Do not direct
  the ledger, CI, or a browser automation harness at the configured endpoint.
- Do not derive an aggregate from individual run data. Community reporting and
  verified reporting must remain distinct if an approved source is later found.
- The source owner, written-permission record, dimensions, and reviewer are
  UNASSIGNED.

## Required immutable contract before a controlled dry run

1. An accountable data-governance owner records source authority, terms,
   permitted reuse/display, dimensions, update cadence, correction route, and
   review authority.
2. A new source revision pins an exact immutable URL or revision, parser
   version, approved final URLs, content type, max bytes, and one source
   artifact. A preview endpoint or assembled response is not sufficient.
3. The policy binds a locator template and exact field map. A claim cannot
   substitute another path, field, script id, script type, assertion, or
   row-index spelling.
4. Fixture tests prove raw lexical preservation, duplicate-key rejection,
   non-string rejection, exact evidence re-resolution, and drift failures.
5. Only an approved private runner may perform a dry run. It snapshots raw
   bytes before extraction and leaves the browser, CI, frontend, and public
   host outside the data plane.
6. Certification, validation review, publication approval, artifact building,
   and REL-05 remain separate append-only gates.

## Explicit stop conditions

Stop and leave the source unavailable if any of these are unresolved:

- source owner, terms/reuse, or review authority;
- complete immutable artifact and content-size bound;
- direct source-reported score semantics and all display dimensions;
- source-specific parser and exact evidence resolver;
- private runner, database/object store, retention, recovery, and withdrawal
  authority;
- certification, review, publication, release-artifact, or REL-05 decision.

No configuration flag, candidate projection, successful fixture, or source
research result overrides these stop conditions.
