# Official-source launch candidate inventory

**Status:** decision-support inventory only. No source in this document is
certified, approved for publication, fetched by the ledger, or available to
the frontend.  
**Reviewed:** 2026-07-15  
**Configuration authority:** [official_sources.yaml](../../ledger/app/registry/official_sources.yaml)

## Bottom line

The registry contains 53 configured routes: 23 have status active and 30 have
status inactive. That status is a configuration state, not an ingestion or
publication approval. As reviewed on 2026-07-15, every active route is rejected
by the Phase-0 admission policy and the ledger has zero certified sources.
There is also no enabled peer-pinning transport for a live source capture.

The recommended technical-preparation path is a small, deliberately diverse,
terms-first cohort:

1. **BigCodeBench official results dataset** — preferred first candidate only
   after result-data authority and reuse approval.
2. **SWE-bench Verified official leaderboard** — second candidate only after
   repository/result-data reuse and display scope approval.
3. **ARC-AGI** — deferred: its current terms block automated collection and
   systematic aggregation without written permission.

This is a recommendation for certification work, not a release approval. Each
source needs its own reviewed immutable source revision, terms/reuse decision,
fixture set, typed evidence contract, certification decision, controlled
capture, validation/review, publication decision, and eventually a governed
release artifact. A group of sources must never be bulk-approved because one
member passes.

## How to read this inventory

| State | Meaning | Current count |
| --- | --- | ---: |
| Configured | Present in the YAML registry. It may be stale, retired, or intentionally unusable. | 53 |
| Active | The source's registry status is active. It is still subject to static policy, immutable source-revision certification, fetch admission, claim admission, review, and publication gates. | 23 |
| Policy-admissible | Clears the static source-class policy. | 0 |
| Certified | Has one effective immutable source-revision decision with outcome certified and a valid source-admission policy. | 0 |
| Publishable | Can contribute to a governed release artifact after all claim/review/publication gates. | 0 |

The executable registry YAML is the authority for this count. The abbreviated
source table in the ledger README had stale status/parser descriptions, so it
now points to this inventory rather than presenting a misleading partial list.

## Recommended certification cohort

| Order | Source | Why it is a useful first cohort member | Required collection method | Important gates before any claim write |
| ---: | --- | --- | --- | --- |
| 1 | BigCodeBench official results dataset | Its reviewed candidate is one compact, revision-pinned Parquet result file rather than a preview response. It is the clearest complete-artifact technical path, not a permission finding. | After written owner approval, capture exactly one pinned full file and use a future Parquet-specific typed locator. The current code deliberately has no enabled Parquet adapter. | Confirm that the result data—not only benchmark code/tasks—is authoritative and reusable; preserve `complete` and `instruct` as distinct source-reported metric dimensions; prove the revision/file completeness, schema, byte bound, and correction route. |
| 2 | SWE-bench Verified official leaderboard | The benchmark-owned website repository publishes the full `data/leaderboards.json`; a commit-pinned copy is a direct structured artifact and avoids HTML scraping. | After approval, retrieve one commit-pinned full JSON file and use `json_path_v1`. The reusable `json_script_path_v1` support is only for an explicitly reviewed historical HTML artifact, not the production source choice. | Confirm CC BY-NC 4.0/result-data reuse and display scope; bind the exact Verified category, agent/setup/release/version semantics, fields, and an 8 MiB source-specific bound for the roughly 6.98 MiB file. |
| 3 | ARC-AGI | ARC Prize terms currently prohibit automated/non-human access and systematic retrieval/aggregation without written permission. The configured web JSON is therefore not a safe first capture candidate. | Do not collect the configured endpoint. ARC-like JSON fixtures may test lexical JSON evidence only; a later source needs written permission or a separately reviewed official artifact and complete manifest. | Obtain written collection and display permission; identify one source-reported aggregate and its dimensions; exclude Community/preview data; review a complete immutable artifact, terms, and a source-specific evidence contract. |

The sources are intentionally varied: abstract reasoning, software-engineering
agents, and code generation. The first public Official release should include
only the members that independently finish certification and the later release
gates; it may be smaller than the cohort.

The supporting research pages are the [BigCodeBench results
dataset](https://huggingface.co/datasets/bigcode/bigcodebench-results), the
[SWE-bench full leaderboard file](https://github.com/SWE-bench/swe-bench.github.io/blob/master/data/leaderboards.json),
and the [ARC Prize terms](https://arcprize.org/terms). These links are research
inputs, not approved fetch endpoints.

## Collection contract for every source

The product does not recalculate a benchmark. It records the narrower claim,
"this approved source revision reported this raw value."

1. A data-governance owner reviews source authority, terms, allowed benchmark
   dimensions, update cadence, correction route, and public-display scope.
2. A reviewed source revision pins the URL or immutable source revision,
   adapter/parser version, allowed final URL, content type/size bounds, raw
   numeric lexeme, and six display dimensions.
3. The isolated private runner makes the bounded request through the
   fail-closed fetch boundary. Public Pages, CI, and browsers never make this
   request and receive no credentials.
4. The original response bytes are snapshotted before extraction; the fetch
   receipt must attest to one verbatim artifact and approved final URL.
5. Extraction preserves raw fields verbatim. Its typed evidence locator must
   re-resolve model and score from the immutable snapshot; it cannot merely
   say that a value appears somewhere in the source.
6. Admission, validation, human review, and append-only publication decisions
   run before a later artifact builder can consider the claim. The candidate
   projection is still not a public artifact.

The currently supported typed locators are json_path_v1, json_script_path_v1,
and csv_cell_v1. Several legacy adapters emit json_path, csv_cell,
json_script_path, or yaml_path instead, which is why a source may look
technically configured while still being impossible to certify today. The
correct repair is to upgrade the source-specific evidence contract, never to
weaken admission.

## Active registry routes and collection readiness

Every entry below is active in configuration but policy-blocked. The policy
reason is the first fail-closed reason; even a route that cleared it would
still need immutable certification and all later gates.

| Registry route(s) | Configured source form | Current practical collection method | Why it is not a launch source today |
| --- | --- | --- | --- |
| swe_bench_verified_official_leaderboard | Configured as official HTML with embedded structured data | A future source revision should instead pin the benchmark-owned full JSON file to one Git commit; HTML script parsing is an explicit historical-artifact option only. | Missing governance; the configured route is not the researched direct JSON candidate; result-data reuse, category/version dimensions, source revision, and certification remain unapproved. |
| mteb_leaderboard | Hugging Face result dataset through a first-rows endpoint | A future full, revision-pinned data-file or explicit shard-manifest ingestion, not a preview page. | Missing governance; dataset card reports 287 MB, beyond the current 5 MiB default fetch boundary; first-rows is incomplete for a full leaderboard; terms and scale design are unresolved. |
| bigcodebench_leaderboard | Hugging Face result dataset through a first-rows endpoint | A future source revision could pin one complete Parquet file at a reviewed dataset revision; parse its native source format with a dedicated typed locator. | The configured preview endpoint is categorically blocked before adapter/fetch; result-data authority/reuse, completeness, Parquet support, source revision, and certification remain unapproved. |
| open_llm_leaderboard_v2; open_llm_leaderboard_v2_gpqa; open_llm_leaderboard_v2_mmlu_pro; open_llm_leaderboard_v2_math; open_llm_leaderboard_v2_bbh | Five logical metrics configured against one Open LLM Leaderboard contents dataset but pointing at a Space blog URL | Replace the blog URL with a reviewed direct, current result artifact; capture one immutable full source and derive no new aggregate. | The configured URL is categorically blocked as a blog/article. It must be a new source revision, with freshness, terms, exact metric semantics, and typed evidence reviewed. |
| arc_agi_official | Configured direct static JSON | No current collection method. The configured endpoint is not a ledger target while ARC Prize terms require written permission for automated collection/systematic aggregation. | Missing governance and legacy json_path evidence, plus a terms/permission blocker. ARC-like fixtures prove only generic parser behavior; they do not approve this source. |
| olympiadbench_readme; frontiercode_benchmarklist; terminal_bench_tbench_leaderboard; browsecomp_llmstats; paperbench_frontier_evals; toolbench_openbmb; mt_bench_lmsys | HTML/README/table pages | None under the current Official policy. | Not structured machine-readable result feeds. Do not scrape the rendered tables into the Official ledger; locate a direct, official structured source instead. |
| mbpp_codesota | Static JSON | Source-authority, terms, and exact JSON/evidence review before any future consideration. | Missing governance and legacy json_path evidence; it is not part of the recommended first cohort. |
| aider_polyglot_yaml | Raw GitHub YAML | Pin a raw file to a reviewed commit and add a typed yaml_path_v1 resolver if the source passes governance. | Missing governance; yaml_path is unsupported by current claim admission; source/metric semantics and display rights need review. |
| gaia_results_public | Hugging Face public results dataset | Same full-artifact/revision method as BigCodeBench; prove it contains source-reported results and not a derived projection. | Missing governance and legacy json_path evidence; source authority, scope, and terms remain unreviewed. |
| webarena_official_sheet; agentbench_official_sheet | Officially labelled Google Sheet CSV exports | Snapshot one direct CSV export, use csv_cell_v1 locators, and certify exact column/dimension semantics. | Missing governance and legacy csv_cell evidence; source ownership, terms, and schema-drift handling need review. They are good later structured-CSV candidates, not substitutes for certification. |
| mmlu_openllm_v2; truthfulqa_openllm_v2 | Hugging Face Open LLM result dataset with dotted nested score fields | Use a full direct artifact and a source-specific nested-field parser/locator. | Missing governance; current adapter reads dotted field names literally, so it does not traverse nested results; the source is large/complex and needs a complete-artifact plan. |

## Inactive and retired registry routes

These 30 routes are intentionally not collection candidates. They are retained
as provenance/configuration history or future investigation notes, not a
backlog to revive because broad coverage is desired.

| Group | Exact registry IDs | Reason to keep inactive |
| --- | --- | --- |
| Synthetic, discovery, fallback, or derived-result retirements | fake_local_fixture; hf_official_benchmark_discovery; livecodebench_official_leaderboard; lmsys_arena_leaderboard; artificial_analysis_leaderboard; livebench_leaderboard; tau_bench_s3 | They are fixtures, discovery metadata, third-party/fallback routes, or adapters that computed their own aggregates instead of capturing a direct source-reported result. |
| Manual-only or no public score feed | manual_hle; manual_arc_agi; manual_frontiermath; manual_usamo; frontiermath_epoch_manual; usamo_matharena; matharena_hf; imo_answerbench_deepmind; imo_answerbench_github; mmmu_hf | The configured material is manual, problem/answer data, or lacks a direct model-result feed. Manual entry is not a shortcut to Official publication. |
| JavaScript-only/stale/unstructured routes | helm_spa_legacy; opencompass_leaderboard; hle_scale; humaneval_evalplus; bfcl_leaderboard_html; apex_agents_mercor; helm_leaderboard; frontiermath_epoch | They have no usable direct structured result source at the configured URL, or the previously configured endpoint is stale. |
| Artificial Analysis metric variants | gpqa_diamond_aa; hle_aa; math500_aa; aime2024_aa; aime2025_aa | These retain the same third-party/API and source-evidence problems as the retired parent route; an API key would not make them official source evidence. |

## What not to do for breadth

- Do not re-enable an inactive source merely because it has a familiar name.
- Do not scrape a rendered HTML table, article, blog, newsletter, or social
  post into the Official ledger.
- Do not collect only an API preview page and call its first rows a complete
  benchmark leaderboard.
- Do not merge source artifacts or calculate an average/aggregate that the
  source did not report.
- Do not treat a data-card license for benchmark tasks as permission to
  republish leaderboard-result data; review the result source itself.
- Do not enable the frontend's Official mode after certification alone. Only
  REL-05 can bind a reviewed release artifact to a frontend build.

## Decision requested

The technical recommendation is to authorize certification planning in this
order: BigCodeBench, then SWE-bench Verified, with ARC-AGI deferred. The
product/data-governance owner still needs to approve one source's result-data
terms, dimensions, correction route, and review authority before CERT-01
begins. If the owner wants a different first source, it must be selected from a
complete direct structured artifact with equivalent evidence and governance
work, not by changing an active flag.
