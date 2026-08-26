# P5 Certification-B containment audit (candidate)

**Status:** bounded candidate-only containment audit prepared on 2026-08-26
from repository base `220ce272467ee99b1cb02a319a3c8277951c2f3c` (`origin/main`,
branch `feat/p5-certification-b-containment`). Every route listed in this
document is **candidate-only / not certified / capture-ineligible /
publication-ineligible**. This document is not a source-revision decision,
certification, capture authorization, snapshot, claim, publication, release,
REL-05 artifact input, or deployment decision. It supplies no terms,
freshness, completeness, source-authority, certification, capture,
publication, release, or deployment claim.

This audit uses only repository-proved blockers visible at the anchored base.
It does not re-fetch any source, read live source bytes, consult current
external facts, or assert anything about present publisher state. Where
reconsideration is described, the listed evidence is the exact human/external
input an owner would still need to supply; this document does not pre-decide
that evidence.

Use the [source-revision decision-package template](../runbooks/source-revision-decision-package-template.md)
for any later owner review. Reactivation of any route below requires a **new
immutable source definition** (pinned exact revision, typed
`evidence_location` admitted by `source-contract-v2`, governance declaration,
owner/approved terms, complete-manifest contract where applicable) **plus a
separate owner-reviewed certification decision** recorded as an append-only
source-revision decision. A route is never reactivated by a silent status
flip, an in-place registry edit that reinterprets an existing revision, or a
governance flag added without the underlying contract.

Configured coverage membership is preserved while execution is denied: every
route below remains a `coverageStatus: configured` member of
`baseline-configured-benchmarks` in `ledger/app/registry/coverage_universe.yaml`
with `registryStatus: inactive`. Containment denies ingestion/capture, not
cohort membership.

The bounded denominator remains intentionally unresolved: the universe keeps
53 configured source-route members while `official_sources.yaml` contains 54
source rows, including the pre-existing
`lmarena_first_party_leaderboard_candidate` outside the universe. The census
surfaces this as `UNIVERSE_REGISTRY_DENOMINATOR_MISMATCH` and
`REGISTRY_SOURCE_OUTSIDE_UNIVERSE`; P5a does not add, remove, or reclassify
that route, and does not fix P6 coverage approval. The production registry
pin is aligned to the complete 54-row input, so this slice does not leave a
`UNIVERSE_REGISTRY_DIGEST_MISMATCH`, but the denominator and outside-universe
blockers remain. `authority.approvalStatus` remains `draft_unapproved` and
the candidate-only authority ceiling is unchanged.

## Bounded verdict

| Route ID | Benchmark | Verdict | Repository-proved central reason |
| --- | --- | --- | --- |
| `aider_polyglot_yaml` | `aider_polyglot` | **STOP — candidate only** | Mutable raw-`main` YAML URL with no pinned immutable revision; `github_yaml` adapter emits `evidence_location.type=yaml_path`, which is not in `_LOCATOR_TYPES`; substring `validate_claim` is not an exact-lexeme re-resolution contract; no `governance` declaration (`missing governance declaration`). |
| `gaia_results_public` | `gaia` | **STOP — candidate only** | `source_url` ends in `/first-rows`; policy returns `preview first-rows endpoint is not a complete source artifact`. No complete-manifest artifact is registered. |
| `terminal_bench_tbench_leaderboard` | `terminal_bench` | **STOP — candidate only** | `source_type: html_table` is in `BLOCKED_SOURCE_TYPES`; policy returns `source type 'html_table' is quarantined`. No approved structured artifact exists for this benchmark. |
| `open_llm_leaderboard_v2` | `hf_official_benchmarks` | **STOP — candidate only** | `source_url` contains `/blog`; policy returns `blog/article sources are not result sources`. A blog/article URL is not a result artifact. |
| `open_llm_leaderboard_v2_gpqa` | `gpqa_diamond` | **STOP — candidate only** | Same `/blog` `source_url`; `blog/article sources are not result sources`. |
| `open_llm_leaderboard_v2_mmlu_pro` | `mmlu_pro` | **STOP — candidate only** | Same `/blog` `source_url`; `blog/article sources are not result sources`. |
| `open_llm_leaderboard_v2_math` | `math` | **STOP — candidate only** | Same `/blog` `source_url`; `blog/article sources are not result sources`. |
| `open_llm_leaderboard_v2_bbh` | `bbh` | **STOP — candidate only** | Same `/blog` `source_url`; `blog/article sources are not result sources`. |
| `mmlu_openllm_v2` | `mmlu` | **STOP — candidate only** | `source_url` ends in `/first-rows` (`preview first-rows endpoint is not a complete source artifact`); `score_field: "results.mmlu.acc,none"` is a nested/dotted key the `hf_datasets_server` adapter resolves with a flat `row_data.get(score_field)`, so no nested-field evidence contract exists; no complete-manifest contract is registered. |
| `truthfulqa_openllm_v2` | `truthfulqa` | **STOP — candidate only** | `source_url` ends in `/first-rows` (`preview first-rows endpoint is not a complete source artifact`); `score_field: "results.truthfulqa.mc2"` is a nested/dotted key with no nested-field evidence contract; no complete-manifest contract is registered. |

"STOP — candidate only" above means the route is contained at the static
Phase-0 admission boundary and is not eligible for capture, claim,
publication, or release. It is not a terms decision, a certification
rejection of a source revision, or a permanent retirement; it is a
fail-closed hold pending the owner evidence listed per route below.

## Aider Polyglot — `aider_polyglot_yaml`

### Repository-proved record

- **Registry entry:** `aider_polyglot_yaml`, `benchmark_id: aider_polyglot`,
  `source_url: https://raw.githubusercontent.com/Aider-AI/aider/main/aider/website/_data/polyglot_leaderboard.yml`,
  `source_type: github_yaml`, `parser_name: github_yaml`, `status: active`.
- **Mutable raw-`main` URL:** the URL pins the `main` branch, not an
  immutable commit SHA. The ledger rule that a logical source is not its
  mutable configuration requires an immutable source revision; `main` is a
  moving head, so no `source_snapshot_id` can bind to an exact revision
  through this URL.
- **Unsupported `yaml_path` evidence locator:** `GitHubYAMLAdapter.extract_claims`
  emits `evidence_location={"type": "yaml_path", "path": …, "model_path": …}`.
  `source-contract-v2` admits `_LOCATOR_TYPES = {csv_cell_v1, json_path_v1,
  json_script_path_v1, parquet_cell_v1}` only. `yaml_path` is not admitted,
  so no typed `evidence_location` can re-resolve the raw values in an
  immutable snapshot under the current contract.
- **No exact-lexeme evidence contract:** `GitHubYAMLAdapter.validate_claim`
  tests `claim.score_raw in text` (a substring check over the decoded bytes),
  not a deterministic re-resolution of the exact source lexeme at a typed
  locator. This does not satisfy the exact-lexeme re-resolution requirement.
- **Absent governance:** `parser_config` has no `governance` mapping, so
  `source_admission_reason` returns `missing governance declaration` before
  any fetch.

### Exact blockers

1. No pinned immutable source revision; the URL is a mutable `main` head.
2. `yaml_path` is not an admitted `evidence_location` locator type; no typed
   evidence contract can re-resolve raw values.
3. The adapter's substring validation is not an exact-lexeme re-resolution
   contract.
4. No `governance` declaration (`production_eligible`, `result_kind`,
   `direct_source_only`) is present.
5. No owner-reviewed terms, attribution, correction/withdrawal route, or
   certification decision exists.

### Evidence needed before reconsideration

- An exact immutable Aider-AI/aider commit SHA (or other immutable artifact
  revision) plus a stable final URL bound to that revision.
- An owner decision adding an admitted YAML locator type to
  `source-contract-v2` (with exact-lexeme re-resolution semantics) **or** a
  decision to source the same results through an already-admitted locator
  family (e.g. `json_path_v1` over a structured projection).
- A `governance` declaration meeting `REQUIRED_GOVERNANCE` and an owner
  terms/attribution decision for the Aider Polyglot leaderboard data.
- A named owner/reviewer and a correction/withdrawal route.

## GAIA — `gaia_results_public`

### Repository-proved record

- **Registry entry:** `gaia_results_public`, `benchmark_id: gaia`,
  `source_url: https://datasets-server.huggingface.co/first-rows?dataset=gaia-benchmark/results_public&config=2023&split=validation`,
  `source_type: hf_datasets_server`, `parser_name: hf_datasets_server`,
  `status: active`.
- **`first-rows` preview:** `_is_preview_first_rows_endpoint` returns true
  because the URL path ends in `/first-rows`; `source_admission_reason`
  returns `preview first-rows endpoint is not a complete source artifact`.
  The Hugging Face datasets-server `first-rows` endpoint is a bounded preview,
  not a complete result manifest.
- **No complete-manifest artifact:** no GAIA source route in
  `official_sources.yaml` points at a complete artifact (full split / full
  Parquet manifest) for this benchmark.

### Exact blockers

1. The route is a `first-rows` preview, not a complete artifact; admission
   fails closed at `preview first-rows endpoint is not a complete source
   artifact`.
2. No complete-manifest GAIA artifact route is registered.
3. No immutable revision, typed evidence locator, governance declaration,
   terms decision, or certification exists for a complete GAIA result
   artifact.

### Evidence needed before reconsideration

- A complete GAIA results artifact (full split / full Parquet manifest) at an
  exact immutable revision with a stable final URL.
- An admitted `evidence_location` locator (e.g. `parquet_cell_v1` or
  `json_path_v1`) with an exact field map and complete-manifest accounting.
- Owner terms/attribution, governance declaration, named reviewer, and a
  correction/withdrawal route.

## Terminal-Bench — `terminal_bench_tbench_leaderboard`

### Repository-proved record

- **Registry entry:** `terminal_bench_tbench_leaderboard`,
  `benchmark_id: terminal_bench`,
  `source_url: https://www.tbench.ai/leaderboard/terminal-bench/2.1`,
  `source_type: html_table`, `parser_name: generic_html_table`,
  `status: active`.
- **`html_table` quarantined:** `html_table` is in `BLOCKED_SOURCE_TYPES`, so
  `source_admission_reason` returns `source type 'html_table' is quarantined`
  regardless of any governance flag. This is a static containment control that
  cannot be bypassed by adding optimistic metadata to the registry entry.
- **No approved structured artifact:** no Terminal-Bench route in
  `official_sources.yaml` points at an approved structured (JSON/CSV/Parquet)
  result artifact; the only registered route is the quarantined HTML table.

### Exact blockers

1. `source_type: html_table` is quarantined at the admission boundary.
2. No approved structured Terminal-Bench result artifact is registered.
3. No immutable revision, typed evidence locator, governance declaration,
   terms decision, or certification exists for a structured Terminal-Bench
   artifact.

### Evidence needed before reconsideration

- A first-party structured Terminal-Bench result artifact (JSON/CSV/Parquet)
  at an exact immutable revision with a stable final URL, **not** an HTML
  table.
- An admitted `evidence_location` locator and exact field map.
- Owner terms/attribution, governance declaration, named reviewer, and a
  correction/withdrawal route.

## Open LLM Leaderboard v2 — blog/article routes

The five routes below share the same `source_url`,
`https://huggingface.co/spaces/open-llm-leaderboard/blog`, which contains the
`/blog` path segment. `BLOCKED_ARTICLE_PATH_SEGMENTS` includes `/blog`, so
`source_admission_reason` returns `blog/article sources are not result
sources` for each. A blog/article URL is not a result artifact, and the
AGENTS ledger rule forbids ingesting articles, vendor blogs, newsletters, or
social posts into the official result ledger (O0).

| Route ID | Benchmark ID | Score field |
| --- | --- | --- |
| `open_llm_leaderboard_v2` | `hf_official_benchmarks` | `Average ⬆️` |
| `open_llm_leaderboard_v2_gpqa` | `gpqa_diamond` | `GPQA` |
| `open_llm_leaderboard_v2_mmlu_pro` | `mmlu_pro` | `MMLU-PRO` |
| `open_llm_leaderboard_v2_math` | `math` | `MATH Lvl 5` |
| `open_llm_leaderboard_v2_bbh` | `bbh` | `BBH` |

### Exact blockers (all five)

1. The `source_url` is a blog/article URL; admission fails closed at
   `blog/article sources are not result sources`.
2. No structured result artifact (Parquet/JSON manifest) at an immutable
   revision is registered for any of these five benchmarks.
3. No admitted `evidence_location` locator, governance declaration, terms
   decision, or certification exists for a structured Open LLM Leaderboard v2
   artifact for these benchmarks.

### Evidence needed before reconsideration (all five)

- A first-party structured Open LLM Leaderboard v2 results artifact (e.g. the
  complete `open-llm-leaderboard/contents` or `open-llm-leaderboard/results`
  manifest) at an exact immutable revision with a stable final URL, **not** a
  blog/article URL.
- Per-benchmark admitted `evidence_location` locator and exact field map
  (including the exact score column for `Average`, `GPQA`, `MMLU-PRO`,
  `MATH Lvl 5`, and `BBH`).
- Owner terms/attribution, governance declaration, named reviewer, and a
  correction/withdrawal route.

## Open LLM Leaderboard v2 — `first-rows` preview routes

The two routes below use a Hugging Face datasets-server `first-rows` preview
URL (`.../first-rows?dataset=open-llm-leaderboard/results&config=default&split=train`).
`_is_preview_first_rows_endpoint` returns true, so `source_admission_reason`
returns `preview first-rows endpoint is not a complete source artifact` for
each. In addition, each route's `score_field` is a nested/dotted key
(`results.mmlu.acc,none` and `results.truthfulqa.mc2`) that the
`hf_datasets_server` adapter resolves with a flat
`row_data.get(score_field)` lookup; a flat `.get()` on the literal dotted
string does not traverse nested fields, so no nested-field evidence contract
exists. No complete-manifest route is registered for either benchmark.

| Route ID | Benchmark ID | Score field |
| --- | --- | --- |
| `mmlu_openllm_v2` | `mmlu` | `results.mmlu.acc,none` |
| `truthfulqa_openllm_v2` | `truthfulqa` | `results.truthfulqa.mc2` |

### Exact blockers (both)

1. The route is a `first-rows` preview, not a complete artifact; admission
   fails closed at `preview first-rows endpoint is not a complete source
   artifact`.
2. The `score_field` is a nested/dotted key; the `hf_datasets_server` adapter
   performs a flat `row_data.get(score_field)` and does not traverse nested
   fields, so no nested-field evidence contract exists.
3. No complete-manifest Open LLM Leaderboard v2 artifact route is registered
   for `mmlu` or `truthfulqa`.
4. No immutable revision, admitted typed locator, governance declaration,
   terms decision, or certification exists for a complete artifact.

### Evidence needed before reconsideration (both)

- A complete Open LLM Leaderboard v2 results manifest at an exact immutable
  revision with a stable final URL, **not** a `first-rows` preview.
- An admitted `evidence_location` locator with a nested-field resolution
  contract (or a flattened projection with a flat field map) and exact field
  map for `results.mmlu.acc,none` / `results.truthfulqa.mc2`.
- Owner terms/attribution, governance declaration, named reviewer, and a
  correction/withdrawal route.

## Reactivation rule

Reactivation of any route above is a two-step owner action, never a silent
status flip:

1. **New immutable source definition.** A new registry source entry (or a new
   immutable revision of an existing one) that pins an exact immutable
   revision, binds a stable final URL, declares an admitted typed
   `evidence_location` locator with an exact field map, includes a
   `governance` declaration meeting `REQUIRED_GOVERNANCE`, and records
   owner-approved terms/attribution. A logical source is not its mutable
   configuration; an in-place edit that reinterprets an existing revision or
   flips `status` does not satisfy this step.
2. **Separate owner-reviewed certification decision.** An append-only
   source-revision decision (per the
   [source-revision decision-package template](../runbooks/source-revision-decision-package-template.md))
   that records the certification outcome, claim-review path, and publication
   decision. Capture, validation, capture-status, and publication are not
   promoted by the new definition alone.

Legacy evidence stays quarantined until a new decision path approves it; a
reconsideration of any route does not revive retired routes such as
`lmsys_arena_leaderboard`, `livebench_leaderboard`, `livecodebench_official_leaderboard`,
`artificial_analysis_leaderboard`, `tau_bench_s3`, or `hf_official_benchmark_discovery`.

## Local containment verification

The local verification that will prove containment, run after this audit is
in place, is the existing static-admission gate plus the registry/coverage
invariants:

- `cd ledger && pytest -q` — including `test_p4_candidate_containment.py` and
  the `source_admission_reason` checks in `test_policy.py`, which assert that
  `first-rows`, `html_table`, `/blog`, and missing-governance routes fail
  closed.
- A registry/coverage consistency check that every route listed above remains
  `registryStatus: inactive` while its benchmark keeps
  `coverageStatus: configured` in `coverage_universe.yaml` (membership
  preserved, execution denied).

This audit does not claim those tests have passed. It identifies the
verification that will prove containment once run; the owner (Luna High)
records the acceptance receipt only after validation.
