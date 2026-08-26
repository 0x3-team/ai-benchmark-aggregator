# P4 source-certification candidate packages

**Status:** bounded decision support prepared on 2026-08-26 from repository
base `3bffe66c97beddaae71d5c4947cfc6145592848a`. Every source in this
document is **candidate / not certified / capture ineligible / publication
ineligible**. This document is not a source-revision decision, live receipt,
authorization to fetch, claim, snapshot, schedule, transport, publication, or
REL-05 artifact input.

Research used publisher pages, repository APIs, immutable commit pages, and
response headers read-only. It ran no ingestion and retained no source body as
a ledger snapshot. Header observations below are research notes, not safe-fetch
or connected-peer receipts. Expiring Hugging Face Xet redirect URLs are
deliberately omitted.

Use the [source-revision decision-package template](../runbooks/source-revision-decision-package-template.md)
for any later owner review.

## Bounded verdict

| Candidate | Verdict | Central reason |
| --- | --- | --- |
| BigCodeBench | **STOP — candidate only** | The results dataset has no result-data license; actual null `instruct` cells and the one-field-map admission contract conflict with the two-dimension adapter; Hugging Face final redirects are expiring. |
| SWE-bench Verified | **STOP — candidate only** | CC BY-NC 4.0 permits sharing only for NonCommercial purposes, which has no owner-approved fit for a future public product release; the raw endpoint's `text/plain` media type is not admitted; rows identify evaluated agent systems, not reliably one model. |
| MTEB | **GO for further governance/engineering review only; still not certified** | The first-party result repository expressly uses CC0, but the current flattened Hugging Face candidate is four shards totaling 298,363,656 bytes and 8.4M+ rows, beyond current fetch and Parquet resource contracts, with no complete-manifest adapter or approved dimension mapping. |
| LMArena first-party leaderboard dataset | **Prepared replacement candidate; not certified** | First-party immutable Parquet and CC BY 4.0 evidence are materially better than the retired scraper/fallback route. A fixture-only adapter candidate now rehearses the pinned shape, but no category inventory, stable final-URL policy, attribution decision, or certification exists. |

“GO” above means only that evidence supports spending review effort. It does not
mean source admission, capture, claim, publication, or release approval.

## BigCodeBench

### Candidate record

- **Primary publisher/owner:** the BigCodeBench project (`bigcode-project` on
  GitHub and `bigcode` on Hugging Face). The project README calls the linked
  page “our leaderboard” and directs result submissions to the project
  maintainer. The GitHub repository is now archived, so an accountable active
  owner and correction SLA remain unassigned.
- **Immutable artifact candidate:** Hugging Face dataset revision
  `08ceb6b15ecd9c0f7c82932e4e248208ffeeb9b4`, file
  `data/train-00000-of-00001.parquet`:
  `https://huggingface.co/datasets/bigcode/bigcodebench-results/resolve/08ceb6b15ecd9c0f7c82932e4e248208ffeeb9b4/data/train-00000-of-00001.parquet`.
  The verified commit records one LFS object,
  SHA-256 `b2aa99eff40dd1c62d5038a85e90f473c01405cd34dfd9fb0d645fe107feb647`,
  at exactly 12,503 bytes. The dataset API reports 202 rows and one data file.
- **Terms/reuse evidence:** the benchmark code repository's Apache-2.0
  license says, “each Contributor hereby grants to You a perpetual, worldwide,
  non-exclusive, no-charge, royalty-free, irrevocable copyright license to
  reproduce, prepare Derivative Works of, publicly display, publicly perform,
  sublicense, and distribute the Work.”
  ([repository LICENSE](https://raw.githubusercontent.com/bigcode-project/bigcodebench/main/LICENSE),
  retrieved 2026-08-26). The separate results dataset card has no license tag.
  The code/task grant therefore does **not** establish that the result Parquet
  is licensed for capture or republication. Terms status remains `unknown` and
  is a STOP.
- **Candidate dimensions, not approved:** the artifact directly reports
  `model`, `complete`, `instruct`, `type`, `date`, and `prefill`. Only
  `complete` and non-null `instruct` are candidate score fields. The owner must
  decide whether these are settings under a `pass@1` metric or metrics in their
  own right, bind Full versus Hard scope, identify the evaluation dataset and
  evaluator version, and define the meaning of icon-valued `type` and
  `prefill`. No inference from row order or averaging is permitted.
- **Bound/media evidence:** exact file metadata supports a candidate
  `maxBytes` of 16,384. A read-only HEAD on the immutable resolve URL returned
  a redirect followed by `application/octet-stream` and `Content-Length:
  12503`; this media type is accepted by `bigcodebench_parquet`. The redirect
  target is an expiring signed Xet URL, so the exact-final-URL contract cannot
  yet bind a stable final URL.
- **Typed locator:** `parquet_cell_v1` with row group, row index, and field map
  `{model_raw: model, score_raw: complete}` or `{model_raw: model,
  score_raw: instruct}`. The resolver is fixture verified and preserves floats
  through deterministic shortest-round-trip lexical rendering.
- **Freshness:** the dataset API reports revision `08ceb6b…` last modified
  2025-04-17; the commit history is the only identified revision signal. The
  result repository has not changed since then and the code repository is
  archived, so current-maintenance and cadence claims are unresolved.
- **Correction/withdrawal route:** the README says, “You can file an issue …
  to remind us if we do not respond to your email within 3 days”
  ([project README, Result Submission](https://github.com/bigcode-project/bigcodebench#-result-submission),
  retrieved 2026-08-26). Because the repository is archived and the primary
  route is email rather than the HTTPS route required by `source-contract-v2`,
  no currently verified correction/withdrawal route is contract-ready.

### Fixture and admission gaps

- The adapter fixtures cover lexical strings, malformed/empty Parquet,
  duplicates, non-finite values, missing cells, evidence replay, and bounded
  resolver lifecycle. A new rehearsal now covers source-shaped float columns.
- Read-only source preview rows show null `instruct` values for base models.
  Current complete-artifact logic requires every declared dimension on every
  row, so the real candidate would stop with `PARQUET_COLUMN_MISSING` rather
  than emit partial claims. An owner-reviewed exclusion or row/dimension
  accounting model does not exist.
- `source-admission-v2` allows one evidence field map for each locator type.
  One revision therefore cannot admit both `{score_raw: complete}` and
  `{score_raw: instruct}` locators even though the adapter emits both. Do not
  split the artifact into two sources merely to evade this contract decision.
- The fixture has no digest bound by a candidate source contract, no exact
  source schema fingerprint, no accepted constant dimension set, and no live
  complete-artifact receipt.

### Exact blockers

1. Written result-dataset reuse/display authority, accountable owner, reviewer,
   attribution/retention obligations, and terms review expiry are absent.
2. Null `instruct` accounting and the two-score-column admission-contract
   mismatch are unresolved.
3. Full/Hard, metric/setting, evaluator/dataset version, and icon semantics are
   unapproved.
4. Hugging Face's expiring redirect cannot satisfy the current exact final-URL
   contract, and no connected-peer transport exists.
5. No immutable source-revision decision, fixture digest, controlled receipt,
   claim review, publication decision, or release authorization exists.

## SWE-bench Verified

### Candidate record

- **Primary publisher/owner:** the `SWE-bench` GitHub organization. Its website
  repository describes itself as the codebase that “showcases leaderboards for
  the SWE-bench benchmark” and states that all leaderboard data is stored in
  `data/leaderboards.json`.
- **Immutable artifact candidate:** current reviewed commit
  `f42505b21a0eb31a9cc1204caafcbe0da6c1a259`, direct file
  `https://raw.githubusercontent.com/SWE-bench/swe-bench.github.io/f42505b21a0eb31a9cc1204caafcbe0da6c1a259/data/leaderboards.json`.
  GitHub reports blob `24f5c9370d10a9de8ad70d3adcf1f6fc83d303a8`
  and exactly 7,270,245 bytes. This supersedes the older `7c4289f…`
  preparation candidate; a later decision must still choose whether to certify
  a historical or then-current revision.
- **Terms/reuse evidence:** the repository license grants the right to
  “reproduce and Share the Licensed Material, in whole or in part, for
  NonCommercial purposes only” and the same limitation for adapted material
  ([CC BY-NC 4.0 LICENSE at the candidate repository](https://raw.githubusercontent.com/SWE-bench/swe-bench.github.io/f42505b21a0eb31a9cc1204caafcbe0da6c1a259/LICENSE),
  retrieved 2026-08-26). Public-product capture and display has no owner-approved
  NonCommercial determination or attribution plan. Terms status is
  `blocked_terms`; this is a STOP for commercial public release.
- **Candidate dimensions, not approved:** `benchmark_raw=swe_bench_verified`,
  `metric_raw=% Resolved`, and category `Verified` are directly supportable.
  The evaluated row `name` is an agent/system label; fields such as
  `mini-swe-agent_version`, `folder`, model/scaffold metadata, date, and tags
  vary by row and revision. `split_raw`, `setting_raw`, and
  `evaluation_version_raw` need an owner-approved exact mapping. Do not coerce
  agent systems into base-model identities.
- **Bound/media evidence:** the exact size supports the existing source-specific
  8 MiB candidate cap. A read-only HEAD returned `text/plain; charset=utf-8`
  and `Content-Length: 7270245`. The direct-JSON adapter and source-contract
  MIME allowlist do not currently accept `text/plain`, so the observed endpoint
  is fail-closed despite containing JSON.
- **Typed locator:** direct JSON can use `json_path_v1` with
  `leaderboards_path=$.leaderboards`, exactly one category whose `name` is
  `Verified`, record template
  `$.leaderboards[{verified_category_index}].results[{row_index}]`, and fields
  `{model_raw: name, score_raw: resolved}`. The category assertion must be
  represented by the immutable parser/config decision; selecting the first
  array or all categories is forbidden.
- **Freshness:** commits that modify `data/leaderboards.json` are the identified
  signal. Candidate commit `f42505b…` modified that file on 2026-08-10. A later
  mutable-head check may propose a new revision but cannot mutate this one.
- **Correction/withdrawal route:** the active benchmark-owned repository's
  [issue tracker](https://github.com/SWE-bench/swe-bench.github.io/issues)
  is the candidate intake route. Governance still needs a named owner, response
  expectation, and append-only withdrawal procedure.

### Fixture and admission gaps

- Existing fixtures cover historical embedded JSON and direct list-root JSON.
  A new fixture covers the actual object root and `$.leaderboards` path.
- No fixture represents the current 7.27 MB file's complete six-board
  accounting, duplicate category rejection at full scale, expanded agent/system
  fields, or 180+ Verified entries.
- The adapter emits the source row's system label as `model_raw`; central model
  matching will correctly quarantine unresolved labels, but no approved
  evaluated-system identity path promotes them as model claims.
- The observed raw media type is unsupported, and no fixture or admission
  decision may paper over that header mismatch.

### Exact blockers

1. CC BY-NC 4.0 reuse is not approved for the product's intended public scope;
   attribution, modification notice, and noncommercial conditions are unbound.
2. The raw endpoint media type is not accepted by current adapter/contract
   allowlists.
3. Agent/system identity, scaffold/model separation, and per-row version
   dimensions are unresolved.
4. No named owner/reviewer, exact current-revision choice, complete-artifact
   fixture/schema fingerprint, connected-peer transport, or correction SLA is
   approved.
5. No certification, capture receipt, claim review, publication, or release
   decision exists.

## MTEB

### Candidate record

- **Primary publisher/owner:** the `embeddings-benchmark` organization. Its
  MTEB documentation calls `embeddings-benchmark/results` the “official results
  repository,” and the repository README says it contains results evaluated
  using the `mteb` package.
- **Primary immutable authority candidate:** GitHub results repository commit
  `e82ef8dbb1c046d3977d321e6e3bcdc37a4e5f57` (2026-08-19). It is the clearer
  authority/terms root but is a large multi-file tree, not a bounded
  single-artifact ingestion contract.
- **Flattened file-manifest candidate:** Hugging Face revision
  `fbfca6f624278ab416ede77e17cd91466113178c`, four exact Parquet URLs under
  `https://huggingface.co/datasets/mteb/results/resolve/fbfca6f624278ab416ede77e17cd91466113178c/data/`:
  `train-00000-of-00004.parquet` (74,341,292 bytes),
  `train-00001-of-00004.parquet` (74,466,313),
  `train-00002-of-00004.parquet` (74,807,013), and
  `train-00003-of-00004.parquet` (74,749,038). The exact denominator is four
  shards and 298,363,656 bytes. The dataset API reported 8,439,206 rows and
  1,665,131,169 uncompressed bytes on 2026-08-26.
- **Terms/reuse evidence:** the first-party results README states, “The
  repository is licensed under CC0 and is free to redistribute, modify and
  adapt”
  ([README at `e82ef8d…`](https://raw.githubusercontent.com/embeddings-benchmark/results/e82ef8dbb1c046d3977d321e6e3bcdc37a4e5f57/README.md),
  retrieved 2026-08-26). The same commit includes a CC0 1.0 LICENSE. This is the
  strongest reuse evidence in this cohort, but governance must confirm that the
  flattened Hugging Face shards are an authorized projection of that CC0 work
  and define attribution/provenance expectations.
- **Candidate dimensions, not approved:** the Parquet schema reports
  `model_name`, `model_revision`, `task_name`, `split`, `language`, `subset`,
  `score`, `is_public`, and `trained_on`. At minimum identity must include model
  name plus revision; task, split, language, and subset are result dimensions.
  `is_public` and `trained_on` are eligibility/context flags, not scores.
  Current five-dimension contracts cannot silently discard or concatenate
  these fields, and no owner-approved mapping to one UI MTEB cell exists.
- **Bound/media evidence:** an immutable shard HEAD returned a redirect then
  `application/octet-stream` and the exact 74,341,292-byte length. Every shard
  exceeds the 64 MiB certified fetch ceiling; the four-shard aggregate and
  uncompressed size are much larger. Hugging Face again uses expiring signed
  Xet final URLs.
- **Typed locator:** a future full-shard adapter could use
  `parquet_cell_v1`, but the evidence field map must include model revision and
  every approved task/split/language/subset dimension. The existing
  `hf_datasets_server` adapter handles preview JSON and cannot parse or account
  for this manifest.
- **Freshness:** the Hugging Face API reports revision `fbfca6f…` last modified
  2026-08-25; reviewed GitHub PR merges and commit IDs are the primary result
  history. Governance must bind how/when a GitHub revision produces the HF
  projection and avoid treating upload time as benchmark evaluation time.
- **Correction/withdrawal route:** MTEB documentation directs questions and
  bugs to the active
  [MTEB issue tracker](https://github.com/embeddings-benchmark/mteb/issues),
  while result corrections are reviewed as pull requests to the official
  results repository. A named ledger owner and withdrawal SLA remain absent.

### Fixture and admission gaps

- The only MTEB-named fixture is a two-row Hugging Face `first-rows` response.
  It proves JSON-path lexical extraction only and is categorically incomplete.
- There is no four-shard manifest fixture, MTEB Parquet adapter, model-revision
  locator, task/language/subset mapping, shard-level duplicate detection, or
  complete aggregate accounting receipt.
- Each shard alone exceeds `MAX_CERTIFIED_FETCH_BYTES=64 MiB`. Approximate
  per-shard rows also exceed the fixed Parquet resolver's 100,000-row and
  500,000-cell caps by more than an order of magnitude. Raising safety caps
  without a bounded streaming design is not acceptable.
- The registry still points at a preview `first-rows` endpoint and is rejected
  before adapter execution.

### Exact blockers

1. An owner decision must bind the CC0 GitHub authority to the generated HF
   projection and select an exact complete source revision.
2. Four-shard manifest acquisition, aggregate atomicity, resource-bounded
   streaming, snapshot-before-extraction, and typed cross-shard evidence are
   unimplemented.
3. Every shard exceeds the fetch ceiling and the decoded dataset exceeds
   Parquet row/cell/decompressed caps.
4. Model revision plus task/split/language/subset semantics and the intended
   presentation score are unapproved; the ledger must not calculate an MTEB
   average as an Official claim.
5. Stable final URLs, fixture/schema digests, connected-peer transport,
   certification, review, publication, and release authorization are absent.

## LMArena first-party replacement candidate

This is a **new logical source proposal**, not a revival of
`lmsys_arena_leaderboard`. The retired route and `lmsys_arena_api` fallback
parser remain inactive and quarantined. Never scrape `arena.ai`.

### Candidate record

- **Primary publisher/owner:** Arena (`lmarena-ai` Hugging Face organization).
  Arena's official announcement says, “we're releasing the full history of
  published leaderboards” and identifies the Hugging Face dataset as the
  release location
  ([Arena announcement](https://arena.ai/blog/arena-leaderboard-dataset/),
  retrieved 2026-08-26).
- **Immutable artifact candidate:** verified dataset commit
  `952c8f01f0c60d7762daab67639afec1722e6c2b`, exact `text_style_control`
  latest file:
  `https://huggingface.co/datasets/lmarena-ai/leaderboard-dataset/resolve/952c8f01f0c60d7762daab67639afec1722e6c2b/text_style_control/latest-00000-of-00001.parquet`.
  Publisher metadata reports one file, 559,144 bytes, object ID
  `51bdc93320f8d24520929ad33df2f8f90d6eaf44`. This candidate deliberately
  selects the source-published `latest` split, not HTML and not a recomputation
  from raw votes.
- **Terms/reuse evidence:** the immutable dataset README declares
  `license: cc-by-4.0`. In the first-party dataset discussion, the Arena org
  states, “This dataset is under cc-by-4.0 license”
  ([discussion #2](https://huggingface.co/datasets/lmarena-ai/leaderboard-dataset/discussions/2),
  retrieved 2026-08-26). Governance still must record attribution, license
  notice, modification indication, and downstream display requirements; this
  evidence is not a self-executing approval.
- **Candidate dimensions, not approved:** for `text_style_control/latest`,
  source fields include `model_name`, `rating`, `rating_lower`, `rating_upper`,
  `variance`, `vote_count`, `rank`, `category`, and
  `leaderboard_publish_date`. Only `rating` is the candidate reported score.
  A plausible review mapping is `benchmark_raw=chatbot_arena`,
  `metric_raw=Arena Score`, `split_raw=category` (evidence field),
  `setting_raw=text_style_control`, and
  `evaluation_version_raw=leaderboard_publish_date` (evidence field). The
  complete category allowlist must come from an immutable fixture and owner
  decision. Confidence bounds, variance, vote count, and rank are context, not
  replacement scores.
- **Bound/media evidence:** exact size supports a candidate 1 MiB cap. A
  read-only HEAD returned a redirect followed by `application/octet-stream`
  and `Content-Length: 559144`. The file is below current Parquet byte, row,
  cell, and decoded-size ceilings according to publisher metadata, but only a
  fixture rehearsal can verify its exact footer shape. The expiring Xet final
  URL remains a blocker under current exact-final-URL rules.
- **Typed locator:** `parquet_cell_v1` with fields at least
  `{model_raw: model_name, score_raw: rating, split_raw: category,
  evaluation_version_raw: leaderboard_publish_date}` and revision constants
  for benchmark, metric, and setting.
- **Freshness:** immutable commits updating the `text_style_control` files and
  the source `leaderboard_publish_date` field are separate signals. Commit
  `952c8f0…` identifies an update for the 2026-08-03 leaderboard. Future checks
  may propose a new revision; `latest` in an immutable commit is not mutable.
- **Correction/withdrawal route:** the first-party dataset's
  [community discussions](https://huggingface.co/datasets/lmarena-ai/leaderboard-dataset/discussions)
  are the prepared HTTPS intake route. A named owner, correction SLA, terms
  review date, and ledger withdrawal procedure remain required.

### Fixture and admission gaps

- A source-specific fixture-only Parquet adapter is pinned to the immutable
  `text_style_control/latest` candidate. Generated source-shaped fixtures prove
  duplicate `(model, category, publish-date)` rejection, float lexical replay,
  complete fixture accounting, typed rank retention, unsupported context
  omission, resource ceilings, and unresolved model identity. The retired
  LMSYS adapter is not reused.
- Fixtures do not establish the live artifact's complete category inventory,
  source schema fingerprint, row denominator, or footer receipt. Those remain
  owner-review inputs rather than facts inferred from synthetic rows.
- The benchmark registry still names LMSYS, Elo, and the retired website route;
  owner/rebranding and Bradley-Terry/Arena Score semantics need a new immutable
  benchmark/source revision rather than in-place reinterpretation.
- The source contract supports the locator family, but no exact policy,
  definition digest, fixture digest, stable redirect/final URL, or external
  decision exists.

### Exact blockers

1. Named owner/reviewer and a CC BY 4.0 attribution/display decision are absent.
2. Benchmark naming, Arena Score semantics, category allowlist, and exact raw
   dimension mapping are unapproved.
3. A live immutable-fixture digest, complete category inventory, exact source
   schema fingerprint, and controlled full-artifact receipt are missing; the
   implemented adapter and generated fixtures remain candidate-only.
4. Hugging Face's expiring final redirect and the absent connected-peer
   transport prevent capture.
5. No append-only source revision/certification, check receipt, claim review,
   publication decision, or REL-05 release authorization exists.

## Repository containment proof

The follow-up implementation adds one inactive/not-certified registry candidate
and a fixture-only adapter registration. It changes no transport, database,
migration, claim, snapshot, publication, release artifact, or frontend file.
Tests keep the three original registry routes rejected and the retired LMSYS
route inactive while rehearsing source-shaped local fixture structures for the
candidate adapters.
