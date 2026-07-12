# Benchmark Ledger: Codex Implementation Handoff

**Document purpose:** This is a handoff package for building a simple, robust, reproducible system that captures official benchmark results into a database.

**Date:** 2026-07-08  
**Primary goal:** Create a reliable official-source-backed benchmark result ledger.  
**Non-goal:** Do not run benchmarks or recalculate model scores.

---

## Executive Summary

Build a system that captures benchmark results from official benchmark websites, official benchmark APIs, official benchmark repositories, official benchmark datasets, or official evaluation-framework leaderboards.

The system should not treat benchmark results as floating truth. Every result should be stored as an immutable source-backed claim:

> Official source X reported that model/system Y achieved raw score Z on benchmark B under setting S at capture time T.

The system is built around ledgers:

```text
Benchmark Ledger
Model/System Ledger
Alias Ledger
Official Source Ledger
Source Snapshot Ledger
Result Claim Ledger
Validation Ledger
Relationship Ledger
Ingestion Run Ledger
```

The first working version should be CLI-first, Python-based, database-backed, test-heavy, and simple enough for Codex to implement incrementally.

Recommended MVP stack:

```text
Language: Python
Primary database: Postgres-compatible schema
Local development database: SQLite acceptable if implemented behind a clean abstraction
Snapshot storage: local filesystem first, object storage later
Interface: CLI first
Scheduler: cron or GitHub Actions later
UI: not in MVP
```

---

## Important External References

These are useful implementation references for Codex or the developer working on this project.

- OpenAI Codex CLI: https://developers.openai.com/codex/cli
- OpenAI Codex quickstart: https://developers.openai.com/codex/quickstart
- OpenAI Codex best practices and AGENTS.md guidance: https://developers.openai.com/codex/learn/best-practices
- OpenAI Codex MCP configuration: https://developers.openai.com/codex/mcp
- Hugging Face evaluation results: https://huggingface.co/docs/hub/eval-results
- Hugging Face leaderboard data guide: https://huggingface.co/docs/hub/leaderboard-data-guide
- Hugging Face model cards: https://huggingface.co/docs/hub/model-cards
- Hugging Face user access tokens: https://huggingface.co/docs/hub/security-tokens

Relevant facts from those references:

- Codex CLI can read, change, and run code in a selected local repository.
- Codex supports repo-level guidance through `AGENTS.md`.
- Hugging Face benchmark datasets can host leaderboards.
- Hugging Face model repositories can store evaluation scores in `.eval_results/`.
- Hugging Face supports programmatic official benchmark discovery through `api.list_datasets(benchmark=True)` and REST discovery via `GET https://huggingface.co/api/datasets?filter=benchmark:official`.
- Hugging Face supports programmatic leaderboard retrieval through `api.get_dataset_leaderboard(<dataset_id>)` and REST leaderboard data endpoints.

---

# Part 1: Product Definition

## 1. Implementation Strategy

Build a ledger system, not a benchmark runner.

The product is an **official benchmark result capture database**.

It should:

1. Maintain a ledger of benchmarks.
2. Maintain a ledger of models and benchmarked systems.
3. Maintain a registry of official result sources.
4. Snapshot those sources on a schedule.
5. Extract official result claims exactly as reported.
6. Preserve raw scores without modification.
7. Validate that the stored score matches the official source.
8. Track source changes over time.

It should not:

1. Run model evaluations.
2. Recalculate benchmark scores.
3. Average scores across benchmarks.
4. Use articles or vendor marketing posts as trusted result sources.
5. Overwrite historical values when a leaderboard changes.
6. Normalize away raw score text.
7. Trust unverified extraction without evidence pointers.

The key invariant:

> Every stored benchmark number must be traceable to a saved source snapshot and a precise evidence location.

---

## 2. Recommended Simple Stack

Use a stack Codex can implement quickly and maintainably:

```text
Python package
CLI-first workflow
Postgres-compatible database schema
SQLite allowed for local MVP if the repository abstraction is clean
Local filesystem snapshot storage first
Object storage abstraction for S3/R2/GCS later
Typed schemas for all adapter inputs and outputs
Adapter interface for all official source ingestion
Fixture-based tests for every parser
```

Recommended Python components are intentionally not locked down. Let Codex choose reasonable libraries after inspecting the repo and task. General constraints:

```text
- Prefer stable, common libraries.
- Prefer official APIs and structured data.
- Use HTML scraping only when structured data is not available.
- Use browser rendering only when static extraction fails.
- Do not use OCR unless there is no structured or visual DOM source available.
```

Do not start with a web UI. The first version should be a reliable command-line ingestion engine.

---

## 3. MVP Scope

MVP v0.1 should include:

```text
- Benchmark Ledger
- Model/System Ledger
- Alias Ledger
- Official Source Ledger
- Source Snapshot Ledger
- Result Claim Ledger
- Validation Ledger
- Relationship Ledger
- Ingestion Run Ledger
- CLI ingestion commands
- Local snapshot storage
- Adapter interface
- Fake adapter for tests
- Hugging Face official benchmark API adapter
- Generic JSON adapter
- Generic CSV adapter
- Generic static HTML-table adapter
- Registry seed loader
- Unit tests and fixture tests
```

MVP v0.1 should not include:

```text
- Full web dashboard
- Complex human review UI
- Scheduled cloud deployment
- Paid cloud resources
- Broad crawling of articles or vendor blogs
- LLM-based extraction from arbitrary pages
- Benchmark execution or score recalculation
```

---

## 4. Repository Structure

Target repository structure:

```text
benchmark-ledger/
  README.md
  AGENTS.md
  pyproject.toml
  .env.example
  docker-compose.yml

  app/
    __init__.py

    config.py

    db/
      __init__.py
      engine.py
      models.py
      migrations/
      repositories.py

    schemas/
      __init__.py
      benchmark.py
      model_entity.py
      alias.py
      source.py
      snapshot.py
      result_claim.py
      validation.py
      ingestion_run.py

    registry/
      benchmarks.yaml
      models.yaml
      official_sources.yaml
      seed_loader.py

    storage/
      __init__.py
      base.py
      local.py

    ingestion/
      __init__.py
      runner.py
      adapters/
        __init__.py
        base.py
        fake.py
        hf_benchmark_api.py
        generic_json.py
        generic_csv.py
        generic_html_table.py
      extractors/
        __init__.py
        evidence.py
        validators.py
        normalize.py

    matching/
      __init__.py
      aliases.py
      canonicalize.py

    review/
      __init__.py
      queue.py

    cli.py

  tests/
    fixtures/
      fake_source.json
      hf_leaderboard_sample.json
      html_table_sample.html
      csv_sample.csv
      json_sample.json

    test_config.py
    test_schema.py
    test_snapshot_storage.py
    test_fake_adapter.py
    test_hf_adapter.py
    test_generic_json_adapter.py
    test_generic_csv_adapter.py
    test_generic_html_table_adapter.py
    test_result_claims.py
    test_idempotency.py
    test_review_queue.py
```

Rationale:

```text
db/          database tables and persistence
schemas/     typed contracts
registry/    hand-curated benchmark/model/source seed files
storage/     immutable source snapshot storage
ingestion/   source adapters and ingestion runner
matching/    raw name → canonical entity mapping
review/      CLI review workflow
cli.py       command-line interface
tests/       fixtures and validation
```

---

## 5. Core Product Requirements

### Product goal

Build a reliable system that captures official benchmark results from official benchmark-controlled or official evaluation-framework-controlled sources, stores them as immutable result claims, and preserves enough evidence to prove that each stored value matches the source.

### Primary users

```text
- Internal AI benchmarking/research team
- Model intelligence team
- Product/research analysts
- Automated agents that need trusted benchmark result data
```

### Main user stories

```text
As a user, I want to see all official results captured for a benchmark.
As a user, I want to see all official benchmark results captured for a model/system.
As a user, I want to click a result and see where it came from.
As a user, I want to know whether a result was parser-verified or needs review.
As a user, I want to rerun ingestion without duplicating rows.
As a user, I want to see when an official leaderboard changed.
As a user, I want raw source values preserved exactly.
```

### Non-goals

The system should not:

```text
- Run evaluations.
- Recalculate scores.
- Decide which model is best.
- Average incompatible metrics.
- Treat unverified extraction as trusted.
- Treat articles as official sources.
- Overwrite historical claims.
```

### Core invariant

Every result claim must answer:

```text
Who reported this?
Where was it reported?
When did we capture it?
What exact raw value did the source show?
Where exactly in the source was the value found?
Did our stored value match the captured source?
```

---

# Part 2: Ledger and Database Design

## 6. Database Design Overview

Use append-only ledgers. The core tables are:

```text
benchmarks
model_entities
aliases
official_sources
source_snapshots
result_claims
claim_validations
claim_relationships
ingestion_runs
```

The result table is deliberately called `result_claims`, not `results`, because every row means:

> This source claimed this result.

It does not mean:

> This is scientifically true or independently reproduced.

---

## 6.1 Benchmark Ledger

Stores canonical benchmark identity and official benchmark resources.

```sql
CREATE TABLE benchmarks (
  id TEXT PRIMARY KEY,

  canonical_name TEXT NOT NULL,
  display_name TEXT NOT NULL,
  benchmark_family TEXT,
  description TEXT,

  owner_name TEXT,
  owner_type TEXT,

  official_home_url TEXT,
  official_repo_url TEXT,
  official_dataset_url TEXT,
  official_leaderboard_url TEXT,
  official_docs_url TEXT,

  has_official_leaderboard BOOLEAN DEFAULT false,
  has_official_result_api BOOLEAN DEFAULT false,
  has_official_result_files BOOLEAN DEFAULT false,
  has_private_test_set BOOLEAN DEFAULT false,

  primary_metric TEXT,
  known_metrics JSONB DEFAULT '[]',
  known_splits JSONB DEFAULT '[]',
  known_settings JSONB DEFAULT '[]',

  status TEXT DEFAULT 'active',
  superseded_by_benchmark_id TEXT REFERENCES benchmarks(id),

  created_at TIMESTAMP DEFAULT now(),
  updated_at TIMESTAMP DEFAULT now()
);
```

Example:

```json
{
  "id": "swe_bench_verified",
  "canonical_name": "SWE-bench Verified",
  "display_name": "SWE-bench Verified",
  "benchmark_family": "software_engineering",
  "owner_name": "SWE-bench",
  "official_home_url": "https://www.swebench.com/",
  "official_leaderboard_url": "https://www.swebench.com/",
  "has_official_leaderboard": true,
  "primary_metric": "% Resolved",
  "known_splits": ["Verified"],
  "status": "active"
}
```

Important design rule:

> A benchmark can exist in the benchmark ledger even if it has no official result source.

For example, original MMLU may have an official benchmark repository but not a maintained official leaderboard. That distinction should be explicitly represented.

---

## 6.2 Model/System Ledger

Use one table for both models and benchmarked systems because many leaderboard entries are not pure models.

Examples of pure models:

```text
GPT-4.1
Claude 3.5 Sonnet
Llama 3.1 405B Instruct
DeepSeek-R1
Qwen3
Gemini 2.5 Pro
```

Examples of systems:

```text
SWE-agent + Claude
Agentless + GPT-4o
OpenHands + Claude
Tool-augmented GPT-4.1
Ensemble of multiple models
```

Schema:

```sql
CREATE TABLE model_entities (
  id TEXT PRIMARY KEY,

  canonical_name TEXT NOT NULL,
  display_name TEXT NOT NULL,

  entity_type TEXT NOT NULL,
  -- base_model, instruct_model, chat_model, reasoning_model,
  -- embedding_model, reranker, agent_system, scaffolded_system,
  -- tool_augmented_system, ensemble, unknown

  provider TEXT,
  developer TEXT,
  model_family TEXT,

  access_type TEXT,
  -- open_weights, gated_weights, api, private, unknown

  official_model_url TEXT,
  official_docs_url TEXT,
  official_card_url TEXT,
  official_repo_url TEXT,
  official_hf_repo TEXT,

  api_model_id TEXT,
  api_version TEXT,
  endpoint_fingerprint TEXT,

  artifact_hash TEXT,
  weights_revision TEXT,
  tokenizer_revision TEXT,

  base_model_entity_id TEXT REFERENCES model_entities(id),

  release_date DATE,
  deprecation_date DATE,
  status TEXT DEFAULT 'active',

  context_window INTEGER,
  modalities JSONB DEFAULT '[]',
  license TEXT,

  created_at TIMESTAMP DEFAULT now(),
  updated_at TIMESTAMP DEFAULT now()
);
```

Critical distinction:

```text
model_entities.entity_type = "chat_model"
```

versus:

```text
model_entities.entity_type = "agent_system"
```

This prevents false statements like:

> Claude scored 70% on SWE-bench.

when the source actually reported:

> Agent system X using Claude scored 70% on SWE-bench.

---

## 6.3 Alias Ledger

Raw names from official sources must be preserved. Canonical mapping should be additive and non-destructive.

```sql
CREATE TABLE aliases (
  id UUID PRIMARY KEY,

  entity_type TEXT NOT NULL,
  -- benchmark or model_entity

  entity_id TEXT NOT NULL,
  alias_text TEXT NOT NULL,

  alias_source TEXT,
  source_url TEXT,

  confidence FLOAT DEFAULT 1.0,
  is_official_alias BOOLEAN DEFAULT false,

  created_at TIMESTAMP DEFAULT now(),

  UNIQUE(entity_type, entity_id, alias_text)
);
```

Example:

```json
{
  "entity_type": "model_entity",
  "entity_id": "anthropic_claude_3_5_sonnet_20240620",
  "alias_text": "Claude-3.5-Sonnet",
  "is_official_alias": true
}
```

Every result claim keeps both:

```text
model_raw = exact source wording
model_entity_id = canonical match, nullable
```

---

## 6.4 Official Source Ledger

Controls what the system is allowed to ingest.

```sql
CREATE TABLE official_sources (
  id UUID PRIMARY KEY,

  benchmark_id TEXT REFERENCES benchmarks(id),

  source_name TEXT NOT NULL,
  source_url TEXT NOT NULL,

  source_type TEXT NOT NULL,
  -- hf_benchmark_api, api, github_json, github_csv, github_markdown,
  -- static_json, static_csv, html_table, dynamic_page, gradio_space,
  -- challenge_platform, manual_file

  officialness_level TEXT NOT NULL,
  -- O5 benchmark-owner structured source
  -- O4 benchmark-owner official leaderboard
  -- O3 benchmark-owner result file or repo table
  -- O2 benchmark-owner dataset/eval repo only
  -- O1 official framework leaderboard
  -- O0 non-official source; exclude from trusted ingestion

  machine_readable BOOLEAN DEFAULT false,
  requires_auth BOOLEAN DEFAULT false,
  supports_history BOOLEAN DEFAULT false,

  update_cadence TEXT,
  parser_name TEXT,
  parser_version TEXT,

  parser_config JSONB DEFAULT '{}',

  status TEXT DEFAULT 'active',
  notes TEXT,

  created_at TIMESTAMP DEFAULT now(),
  updated_at TIMESTAMP DEFAULT now(),

  UNIQUE(benchmark_id, source_url)
);
```

Officialness levels:

```text
O5: Benchmark-owner official structured source/API/file
O4: Benchmark-owner official leaderboard
O3: Benchmark-owner official result table/file in official repo
O2: Benchmark-owner official dataset/eval repo only; not necessarily a result source
O1: Official framework leaderboard
O0: Non-official source; do not ingest into trusted result ledger
```

---

## 6.5 Source Snapshot Ledger

Every source fetch is snapshotted before extraction.

```sql
CREATE TABLE source_snapshots (
  id UUID PRIMARY KEY,

  official_source_id UUID REFERENCES official_sources(id),

  captured_at TIMESTAMP DEFAULT now(),

  raw_content_uri TEXT NOT NULL,
  rendered_screenshot_uri TEXT,

  content_hash TEXT NOT NULL,
  content_type TEXT,

  http_status INTEGER,
  etag TEXT,
  last_modified_header TEXT,

  fetch_metadata JSONB DEFAULT '{}',
  parser_version TEXT,

  created_at TIMESTAMP DEFAULT now(),

  UNIQUE(official_source_id, content_hash)
);
```

Local storage path convention:

```text
data/snapshots/{official_source_id}/{timestamp}_{hash}.json
data/snapshots/{official_source_id}/{timestamp}_{hash}.html
data/snapshots/{official_source_id}/{timestamp}_{hash}.csv
data/snapshots/{official_source_id}/{timestamp}_{hash}.txt
```

Later object storage path convention:

```text
s3://benchmark-ledger/snapshots/{official_source_id}/{timestamp}_{hash}.{ext}
```

---

## 6.6 Result Claim Ledger

The core table.

```sql
CREATE TABLE result_claims (
  id UUID PRIMARY KEY,

  source_snapshot_id UUID REFERENCES source_snapshots(id),
  official_source_id UUID REFERENCES official_sources(id),

  benchmark_id TEXT REFERENCES benchmarks(id),
  model_entity_id TEXT REFERENCES model_entities(id),

  model_raw TEXT NOT NULL,
  benchmark_raw TEXT NOT NULL,
  score_raw TEXT NOT NULL,

  metric_raw TEXT,
  split_raw TEXT,
  setting_raw TEXT,
  rank_raw TEXT,
  date_raw TEXT,

  score_numeric DOUBLE PRECISION,
  score_unit TEXT,

  evidence_text TEXT,
  evidence_location JSONB DEFAULT '{}',

  capture_method TEXT NOT NULL,
  -- hf_api, json_parser, csv_parser, html_table_parser,
  -- dynamic_page_parser, manual_review

  capture_confidence FLOAT DEFAULT 0.0,

  capture_status TEXT DEFAULT 'unreviewed',
  -- unreviewed, parser_verified, double_verified,
  -- human_verified, needs_review, disputed, deprecated

  scientific_status TEXT DEFAULT 'unknown',
  -- unknown, setup_described, artifacts_available,
  -- independently_reproducible

  officialness_level TEXT,

  claim_fingerprint TEXT NOT NULL,

  created_at TIMESTAMP DEFAULT now(),

  UNIQUE(source_snapshot_id, claim_fingerprint)
);
```

The raw fields are authoritative:

```text
model_raw
benchmark_raw
score_raw
metric_raw
split_raw
setting_raw
rank_raw
date_raw
```

Derived fields are optional and secondary:

```text
model_entity_id
benchmark_id
score_numeric
score_unit
```

Do not let normalization destroy the source values.

---

## 6.7 Validation Ledger

Tracks whether the system correctly copied the result from the source.

```sql
CREATE TABLE claim_validations (
  id UUID PRIMARY KEY,

  result_claim_id UUID REFERENCES result_claims(id),

  validation_type TEXT NOT NULL,
  -- schema_validation, source_contains_value, row_column_match,
  -- json_path_match, double_extraction, human_review

  outcome TEXT NOT NULL,
  -- pass, fail, uncertain

  validator TEXT,
  notes TEXT,

  validated_at TIMESTAMP DEFAULT now()
);
```

Capture correctness is different from scientific correctness.

Capture correctness means:

> Did we accurately copy what the source said?

Scientific correctness means:

> Is the benchmark result valid, fair, reproducible, and comparable?

MVP focuses on capture correctness.

---

## 6.8 Claim Relationship Ledger

Tracks duplicates, conflicts, and changes.

```sql
CREATE TABLE claim_relationships (
  id UUID PRIMARY KEY,

  claim_id UUID REFERENCES result_claims(id),
  related_claim_id UUID REFERENCES result_claims(id),

  relationship_type TEXT NOT NULL,
  -- duplicate, confirms, conflicts_with, supersedes,
  -- same_source_update, same_model_uncertain, same_benchmark_uncertain

  notes TEXT,

  created_at TIMESTAMP DEFAULT now(),

  UNIQUE(claim_id, related_claim_id, relationship_type)
);
```

Do not overwrite changed values.

Instead:

```text
Old snapshot → old claim
New snapshot → new claim
Relationship: new claim supersedes old claim
```

---

## 6.9 Ingestion Run Ledger

Tracks every job.

```sql
CREATE TABLE ingestion_runs (
  id UUID PRIMARY KEY,

  started_at TIMESTAMP DEFAULT now(),
  finished_at TIMESTAMP,

  run_type TEXT NOT NULL,
  -- full, source, benchmark, dry_run

  status TEXT DEFAULT 'running',
  -- running, completed, failed, partial

  official_source_id UUID REFERENCES official_sources(id),

  sources_checked INTEGER DEFAULT 0,
  snapshots_created INTEGER DEFAULT 0,
  snapshots_reused INTEGER DEFAULT 0,
  claims_extracted INTEGER DEFAULT 0,
  claims_inserted INTEGER DEFAULT 0,
  claims_unchanged INTEGER DEFAULT 0,
  claims_needing_review INTEGER DEFAULT 0,

  error_message TEXT,
  metadata JSONB DEFAULT '{}'
);
```

---

# Part 3: Data Contracts

## 7. Data Contracts

Codex should implement typed schemas for all adapter and database boundary objects.

### Benchmark registry item

```yaml
id: swe_bench_verified
canonical_name: SWE-bench Verified
display_name: SWE-bench Verified
benchmark_family: software_engineering
owner_name: SWE-bench
official_home_url: https://www.swebench.com/
official_leaderboard_url: https://www.swebench.com/
has_official_leaderboard: true
has_official_result_api: false
has_official_result_files: false
primary_metric: "% Resolved"
known_splits:
  - Verified
known_metrics:
  - "% Resolved"
status: active
```

### Model registry item

```yaml
id: anthropic_claude_3_5_sonnet_20240620
canonical_name: Claude 3.5 Sonnet 20240620
display_name: Claude 3.5 Sonnet
entity_type: chat_model
provider: Anthropic
model_family: Claude
access_type: api
api_model_id: claude-3-5-sonnet-20240620
status: active
aliases:
  - Claude 3.5 Sonnet
  - Claude-3.5-Sonnet
  - claude-3-5-sonnet-20240620
```

### Official source registry item

```yaml
id: hf_official_benchmark_discovery
benchmark_id: hf_official_benchmarks
source_name: Hugging Face official benchmark discovery API
source_url: https://huggingface.co/api/datasets?filter=benchmark:official
source_type: hf_benchmark_api
officialness_level: O5
machine_readable: true
requires_auth: false
supports_history: false
update_cadence: daily
parser_name: hf_benchmark_api
status: active
```

### Result claim input

```yaml
model_raw: Claude-3.5-Sonnet
benchmark_raw: SWE-bench Verified
score_raw: "50.80"
metric_raw: "% Resolved"
split_raw: Verified
setting_raw: null
rank_raw: "7"
date_raw: null
model_entity_id: null
benchmark_id: swe_bench_verified
source_snapshot_id: <uuid>
official_source_id: <uuid>
evidence_location:
  type: html_table_cell
  table_index: 0
  row_index: 7
  column_name: "% Resolved"
  model_column: Model
capture_method: html_table_parser
capture_confidence: 0.95
capture_status: parser_verified
```

---

# Part 4: Adapter and Ingestion Architecture

## 8. Adapter Interface

Every source adapter should implement the same interface.

```python
class SourceAdapter:
    source_type: str

    def fetch(self, source: OfficialSource) -> SourceFetchResult:
        """
        Fetch raw official source data.
        Must not extract claims yet.
        Must return raw bytes/text, content type, headers, status, and metadata.
        """

    def snapshot(self, fetch_result: SourceFetchResult) -> SourceSnapshotInput:
        """
        Prepare immutable snapshot metadata.
        Snapshot storage computes and stores the hash.
        """

    def extract_claims(
        self,
        source: OfficialSource,
        snapshot: SourceSnapshot,
    ) -> list[ResultClaimInput]:
        """
        Extract exact raw claims from the snapshot.
        Must preserve raw source values.
        Must include evidence_location.
        """

    def validate_claim(
        self,
        claim: ResultClaimInput,
        snapshot: SourceSnapshot,
    ) -> list[ClaimValidationInput]:
        """
        Validate that the extracted claim exists in the source.
        """
```

Important rule:

> Adapters must not write directly to the database. They return typed objects. The ingestion runner handles persistence.

This keeps source-specific extraction testable.

---

## 9. Ingestion Flow

Daily ingestion should follow this flow:

```text
1. Load active official sources.
2. For each source:
   a. Fetch source.
   b. Save immutable snapshot.
   c. If content hash already exists, optionally reuse snapshot.
   d. Extract candidate result claims.
   e. Validate claim structure.
   f. Match model_raw to Model/System Ledger aliases.
   g. Match benchmark_raw to Benchmark Ledger aliases.
   h. Compute claim_fingerprint.
   i. Insert claim if new.
   j. Attach validation records.
   k. Mark uncertain claims as needs_review.
3. Summarize ingestion run.
```

Pseudocode:

```python
def run_ingestion(source_ids: list[str] | None = None, dry_run: bool = False):
    run = create_ingestion_run()

    sources = load_active_sources(source_ids)

    for source in sources:
        adapter = adapter_registry.get(source.source_type)

        fetch_result = adapter.fetch(source)
        snapshot_input = adapter.snapshot(fetch_result)
        snapshot = save_snapshot(source, snapshot_input)

        claims = adapter.extract_claims(source, snapshot)

        for claim_input in claims:
            claim_input.model_entity_id = match_model(claim_input.model_raw)
            claim_input.benchmark_id = match_benchmark(claim_input.benchmark_raw, source)

            claim_input.claim_fingerprint = compute_claim_fingerprint(claim_input)

            validations = adapter.validate_claim(claim_input, snapshot)

            if not passes_minimum_validation(validations):
                claim_input.capture_status = "needs_review"

            if not dry_run:
                claim = insert_claim_if_new(claim_input)
                insert_validations(claim.id, validations)

    finish_ingestion_run(run)
```

---

## 10. Validation Rules

### Required fields

Every result claim must include:

```text
model_raw
benchmark_raw
score_raw
official_source_id
source_snapshot_id
capture_method
evidence_location
claim_fingerprint
```

### Source validation

At least one of these should pass:

```text
- JSON path points to exact value.
- CSV row/column points to exact value.
- HTML table row/column points to exact value.
- Text span contains exact score_raw.
- Human reviewer confirmed.
```

### Capture status logic

```text
parser_verified:
  deterministic parser found value and evidence pointer is valid

double_verified:
  two independent extraction paths agree

human_verified:
  reviewer confirmed value

needs_review:
  missing canonical model match, weak evidence, ambiguous table, low confidence, parser warning

disputed:
  source has conflicting values or extraction mismatch

deprecated:
  source/result was superseded but preserved historically
```

---

## 11. Official Source Policy

Add a hardcoded policy layer.

```python
TRUSTED_OFFICIALNESS_LEVELS = {"O5", "O4", "O3", "O2", "O1"}


def can_ingest_source(source: OfficialSource) -> bool:
    return (
        source.status == "active"
        and source.officialness_level in TRUSTED_OFFICIALNESS_LEVELS
    )
```

Treat `O2` carefully:

```text
O2 means the official benchmark source exists, but not necessarily official results.
For O2 sources, ingest metadata only unless the source has explicit result rows.
```

Do not ingest into the trusted official result ledger:

```text
O0 vendor blog
O0 article
O0 social post
O0 third-party roundup
O0 marketing page
```

Those can be used later for discovery, but not as trusted official results.

---

## 12. Source Priority

Adapters should use this extraction priority:

```text
1. Official API
2. Official JSON
3. Official CSV/Parquet
4. Official GitHub/Hugging Face file
5. Official markdown table
6. Official static HTML table
7. Official dynamic page with machine-readable data source
8. Rendered page extraction
9. Manual review
```

Principle:

> Prefer the most structured official source available.

For dynamic sites, Codex should inspect network calls, static assets, embedded JSON, or source repository files before using rendered-page scraping.

---

## 13. Seed Sources for MVP

Start with Hugging Face official benchmark data, then add a few curated official leaderboard sources.

### MVP source category 1: Hugging Face official benchmark API

Create adapter:

```text
hf_benchmark_api_adapter
```

It should:

```text
1. Discover official benchmark datasets.
2. For each benchmark dataset, fetch leaderboard rows.
3. Store one source snapshot per API response.
4. Store each leaderboard row as a result claim.
5. Preserve raw fields from the response.
```

Fields likely useful from Hugging Face leaderboard entries:

```text
rank
model_id
value
verified
author
source
filename
pull_request
notes
```

### MVP source category 2: curated official sources

Add a small `official_sources.yaml`.

Example sources:

```yaml
sources:
  - id: hf_official_benchmark_discovery
    benchmark_id: hf_official_benchmarks
    source_name: Hugging Face official benchmark discovery API
    source_url: https://huggingface.co/api/datasets?filter=benchmark:official
    source_type: hf_benchmark_api
    officialness_level: O5
    machine_readable: true
    requires_auth: false
    supports_history: false
    update_cadence: daily
    parser_name: hf_benchmark_api
    status: active

  - id: swe_bench_verified_official_leaderboard
    benchmark_id: swe_bench_verified
    source_name: SWE-bench official leaderboard
    source_url: https://www.swebench.com/
    source_type: html_table
    officialness_level: O4
    machine_readable: true
    requires_auth: false
    supports_history: false
    update_cadence: manual
    parser_name: generic_html_table
    status: active
    parser_config:
      table_hint: leaderboard
      model_column: Model
      score_column: "% Resolved"

  - id: livecodebench_official_leaderboard
    benchmark_id: livecodebench
    source_name: LiveCodeBench official leaderboard
    source_url: https://livecodebench.github.io/leaderboard.html
    source_type: html_table
    officialness_level: O4
    machine_readable: true
    requires_auth: false
    supports_history: false
    update_cadence: manual
    parser_name: generic_html_table
    status: active
    parser_config:
      table_hint: leaderboard
      model_column: Model
      score_column: Pass@1
```

---

## 14. CLI Commands

Implement a CLI called:

```bash
benchmark-ledger
```

Desired commands:

```bash
benchmark-ledger init-db

benchmark-ledger seed-registry \
  --benchmarks app/registry/benchmarks.yaml \
  --models app/registry/models.yaml \
  --sources app/registry/official_sources.yaml

benchmark-ledger ingest --all

benchmark-ledger ingest --source <official_source_id>

benchmark-ledger ingest --benchmark swe_bench_verified

benchmark-ledger ingest --dry-run --source <official_source_id>

benchmark-ledger claims list --benchmark swe_bench_verified

benchmark-ledger claims show <claim_id>

benchmark-ledger snapshots list --source <official_source_id>

benchmark-ledger validate --claim <claim_id>

benchmark-ledger review queue
```

MVP minimum:

```bash
benchmark-ledger init-db
benchmark-ledger seed-registry
benchmark-ledger ingest --all
benchmark-ledger ingest --source <official_source_id> --dry-run
benchmark-ledger claims list
```

---

## 15. Idempotency Rules

Running ingestion twice should not duplicate rows.

Rules:

```text
1. Same official_source_id + same content_hash = same source snapshot.
2. Same source_snapshot_id + same claim_fingerprint = same result claim.
3. Existing result claims are not overwritten.
4. If the source changes, create a new snapshot.
5. If the new snapshot contains changed values, create new claims.
6. Link changed claims through claim_relationships.
```

Do not do this:

```sql
UPDATE result_claims SET score_raw = 'new score';
```

Do this:

```text
Old snapshot → old claim
New snapshot → new claim
Relationship: new claim supersedes old claim
```

---

## 16. Evidence Location Formats

Different source types need different evidence formats.

### JSON

```json
{
  "type": "json_path",
  "path": "$.leaderboard[3].value",
  "model_path": "$.leaderboard[3].model_id",
  "rank_path": "$.leaderboard[3].rank"
}
```

### CSV

```json
{
  "type": "csv_cell",
  "row_index": 12,
  "column_name": "score",
  "model_column": "model",
  "metric_column": "metric"
}
```

### HTML table

```json
{
  "type": "html_table_cell",
  "table_index": 0,
  "row_index": 12,
  "column_name": "% Resolved",
  "model_column": "Model"
}
```

### Text span

```json
{
  "type": "text_span",
  "start_char": 4210,
  "end_char": 4237,
  "matched_text": "Claude 3.5 Sonnet 50.80"
}
```

### Screenshot or manual confirmation

```json
{
  "type": "manual_visual_confirmation",
  "page": 1,
  "bounding_box": {
    "x": 120,
    "y": 440,
    "width": 300,
    "height": 28
  },
  "reviewer": "human"
}
```

---

## 17. Matching Raw Models to the Model Ledger

Do not make matching destructive.

Each claim stores:

```text
model_raw = exact source value
model_entity_id = canonical match, nullable
```

Matching logic:

```text
1. Exact alias match.
2. Case-insensitive alias match.
3. Normalized punctuation match.
4. Provider/model-family heuristic.
5. Otherwise leave null and mark needs_review.
```

Never block ingestion because matching failed.

Example:

```json
{
  "model_raw": "Claude-3.5-Sonnet",
  "model_entity_id": null,
  "capture_status": "needs_review"
}
```

Later, a reviewer can map the raw model name to a canonical model/system entity.

---

## 18. Matching Raw Benchmarks

For most official source adapters, the benchmark is known from `official_sources.benchmark_id`.

Benchmark matching logic:

```text
1. If official source has benchmark_id, use that.
2. If source is multi-benchmark, match benchmark_raw through benchmark aliases.
3. If uncertain, store claim with benchmark_id = null and status = needs_review.
```

---

## 19. Testing Strategy

This project needs tests more than it needs UI.

### Unit tests

```text
- schema validation
- claim fingerprinting
- alias matching
- snapshot hashing
- source deduplication
- claim deduplication
- official source policy
- required-field validation
```

### Adapter fixture tests

Each adapter needs saved raw fixture files.

Example fixtures:

```text
tests/fixtures/hf_leaderboard_sample.json
tests/fixtures/swebench_sample.html
tests/fixtures/livecodebench_sample.html
tests/fixtures/generic_csv_sample.csv
tests/fixtures/generic_json_sample.json
```

Test pattern:

```text
Given fixture snapshot
When adapter.extract_claims runs
Then exact expected claims are returned
And score_raw matches fixture value
And evidence_location points to correct row/path
And adapter.validate_claim passes
```

### Idempotency test

```text
Run ingestion twice on same fixture.
Assert:
- one snapshot
- one set of claims
- no duplicates
```

### Source-change test

```text
Run ingestion on fixture v1.
Run ingestion on fixture v2 with changed score.
Assert:
- two snapshots
- two result claims
- relationship created, if relationship logic exists in this milestone
```

---

## 20. Review Queue

Do not build a full UI first. A CLI review queue is enough.

Command:

```bash
benchmark-ledger review queue
```

Example output:

```text
Claim ID: <uuid>
Benchmark: SWE-bench Verified
Model raw: Claude-3.5-Sonnet
Score raw: 50.80
Reason: model_entity_id is null
Source: SWE-bench official leaderboard
Snapshot: data/snapshots/...
Evidence: table 0, row 12, column "% Resolved"
```

Useful review commands:

```bash
benchmark-ledger review show <claim_id>
benchmark-ledger review map-model <claim_id> <model_entity_id>
benchmark-ledger review mark-human-verified <claim_id>
benchmark-ledger aliases add --entity-type model_entity --entity-id <id> --alias "..."
```

---

# Part 5: Codex Execution Plan

## 21. Milestones for Codex

Do not ask Codex to build everything in one pass. Give it small sequential tickets.

Milestone sequence:

```text
1. Scaffold
2. Database ledgers
3. Snapshotting and ingestion runner skeleton
4. Hugging Face official benchmark adapter
5. Generic JSON/CSV adapters
6. Generic HTML-table adapter
7. Review queue
8. Daily run readiness
```

---

## 22. Copy-Paste Master Prompt for Codex

Use this as the first message to Codex in the repository.

```text
You are building a Python project called benchmark-ledger.

Goal:
Build an official benchmark result capture system. This system does not run benchmarks and does not recalculate scores. It captures benchmark results exactly as reported by official benchmark websites, official benchmark APIs, official benchmark repositories, official benchmark datasets, or official evaluation-framework leaderboards.

Core idea:
Every result is an immutable source-backed claim:
“Official source X reported that model/system Y achieved raw score Z on benchmark B under setting S at capture time T.”

Do not build a normal leaderboard. Build append-only ledgers.

Required ledgers:
1. benchmarks
2. model_entities
3. aliases
4. official_sources
5. source_snapshots
6. result_claims
7. claim_validations
8. claim_relationships
9. ingestion_runs

Architecture:
- Python package
- CLI-first
- Postgres-compatible schema; local dev may use SQLite if easier
- local filesystem snapshot storage first
- object-storage abstraction for later
- typed schemas
- source adapters behind a common SourceAdapter interface
- tests with raw fixture files
- no UI in MVP

Hard rules:
- Preserve raw source values exactly.
- Do not overwrite result claims.
- If a source changes, create a new snapshot and new claims.
- Snapshot official source content before extraction.
- Every result claim must include evidence_location.
- Do not ingest articles, vendor blogs, newsletters, or social posts into the official result ledger.
- Use official APIs and structured files before scraping.
- For scraping, inspect each source and choose the least fragile extraction method. Do not hardcode a single scraping approach for all sites.
- If model matching is uncertain, keep model_raw, set model_entity_id null, and mark claim needs_review.
- Running ingestion twice on the same source snapshot must not create duplicate claims.
- Do not deploy to paid cloud services or trigger paid operations.

First task:
Scaffold the repository with:
- package structure
- config
- database models
- local snapshot storage
- CLI skeleton
- seed YAML files
- tests
- README explaining the architecture

Do not implement every adapter yet. Build the foundation cleanly.
```

---

## 23. Codex Prompt for Milestone 1: Scaffold

```text
Implement Milestone 1 for benchmark-ledger.

Create a Python project with the repository structure described in the README.

Requirements:
- package under app/
- config loader from environment variables
- CLI entrypoint named benchmark-ledger
- local snapshot storage class
- typed input/output schemas for:
  - OfficialSource
  - SourceFetchResult
  - SourceSnapshotInput
  - ResultClaimInput
  - ClaimValidationInput
- base SourceAdapter interface
- tests for config loading and snapshot hashing
- README with local setup instructions
- AGENTS.md with repo-specific rules for Codex

Do not implement real web ingestion yet.
Do not deploy anything.
Do not add a UI.
```

---

## 24. Codex Prompt for Milestone 2: Database Ledgers

```text
Implement the database ledgers.

Add tables/models for:
- benchmarks
- model_entities
- aliases
- official_sources
- source_snapshots
- result_claims
- claim_validations
- claim_relationships
- ingestion_runs

Requirements:
- include uniqueness constraints for snapshot deduplication and claim deduplication
- add repository functions for inserting/finding each core object
- add seed loader for registry YAML files
- add CLI command: benchmark-ledger init-db
- add CLI command: benchmark-ledger seed-registry
- add tests for inserting benchmark/model/source rows
- add tests for duplicate source_snapshot content_hash behavior
- add tests for duplicate result_claim claim_fingerprint behavior

Do not implement real ingestion yet.
```

---

## 25. Codex Prompt for Milestone 3: Snapshotting and Ingestion Runner Skeleton

```text
Implement snapshotting and ingestion runner skeleton.

Requirements:
- IngestionRunner loads active official_sources.
- It selects an adapter by source_type.
- Adapter.fetch returns SourceFetchResult.
- Snapshot storage writes raw content to local filesystem.
- source_snapshots table stores URI, hash, content type, headers, metadata.
- If the same official_source_id and content_hash already exist, reuse existing snapshot.
- Add CLI command: benchmark-ledger ingest --source <id> --dry-run
- Add ingestion_runs tracking.
- Add tests for idempotent snapshot creation.

Use a fake adapter in tests.
Do not implement external web fetching yet.
```

---

## 26. Codex Prompt for Milestone 4: Hugging Face Adapter

```text
Implement the Hugging Face official benchmark adapter.

Background:
Hugging Face exposes official benchmark datasets and leaderboard data through APIs:
- discover official benchmarks
- fetch dataset leaderboard rows

Requirements:
- Add source_type: hf_benchmark_api
- Fetch official benchmark datasets from the HF benchmark API.
- For a benchmark dataset, fetch leaderboard rows.
- Snapshot the raw JSON API response before extraction.
- Extract each leaderboard entry as ResultClaimInput.
- Preserve raw fields exactly where possible:
  - model_raw from model_id
  - score_raw from value
  - rank_raw from rank
  - source metadata from source/filename/pull_request/notes if available
- Store evidence_location as JSON path.
- Validate that the JSON path points to the same raw score.
- Add fixture tests using saved JSON responses.
- Add dry-run output showing claims without inserting.

Do not scrape HF pages if the API is available.
Do not overwrite existing claims.
```

---

## 27. Codex Prompt for Milestone 5: Generic JSON/CSV Adapters

```text
Implement generic structured-source adapters.

Add:
- generic_json adapter
- generic_csv adapter

Each official_source row may define parser_config JSON with:
- row path or record path
- model field
- score field
- benchmark field if multi-benchmark
- metric field
- split field
- rank field
- date field

Requirements:
- Preserve raw values.
- Store evidence_location as JSON path or CSV row/column.
- Add validation that extracted score_raw exists at evidence_location.
- Add fixture tests.
- Add helpful parser errors that mark claims needs_review rather than crashing the entire ingestion run.
```

---

## 28. Codex Prompt for Milestone 6: Generic HTML-Table Adapter

```text
Implement a generic HTML table adapter.

Important:
Do not assume all sites are the same. This adapter is only for simple static HTML tables. Dynamic websites should use source-specific adapters later.

Requirements:
- source_type: html_table
- parser_config identifies:
  - table selector or table index
  - header row
  - model column
  - score column
  - optional metric/split/rank/date columns
- Snapshot raw HTML before extraction.
- Extract rows into ResultClaimInput.
- Preserve exact cell text as score_raw.
- Store evidence_location with table_index, row_index, column_name.
- Validate that the table cell still contains score_raw.
- Add fixture tests.
- If table cannot be parsed confidently, create no verified claims and log needs_review.
```

---

## 29. Codex Prompt for Milestone 7: Review Queue

```text
Implement a CLI review queue.

Commands:
- benchmark-ledger review queue
- benchmark-ledger review show <claim_id>
- benchmark-ledger review map-model <claim_id> <model_entity_id>
- benchmark-ledger review mark-human-verified <claim_id>
- benchmark-ledger aliases add --entity-type model_entity --entity-id <id> --alias "..."

Requirements:
- claims with model_entity_id null appear in review queue
- claims with capture_status needs_review appear in review queue
- mapping a model should not alter model_raw
- human verification should add a claim_validations row
- tests for review workflow
```

---

## 30. Codex Prompt for Milestone 8: Daily Run Readiness

```text
Make benchmark-ledger ready for scheduled daily ingestion.

Requirements:
- command: benchmark-ledger ingest --all
- command: benchmark-ledger ingest --benchmark <benchmark_id>
- command: benchmark-ledger ingest --source <official_source_id>
- command: benchmark-ledger ingest --all --dry-run
- summary output:
  - sources checked
  - snapshots created/reused
  - claims extracted
  - claims inserted
  - claims unchanged
  - claims needing review
  - errors
- nonzero exit code only for fatal failures
- per-source failures should be recorded but should not stop the whole run unless --fail-fast is passed
- add docs for running daily via cron or GitHub Actions
- do not configure real paid cloud resources
```

---

# Part 6: Starter Registry Files

## 31. First Seed Registry

Start very small. Do not try to enumerate every benchmark immediately.

### `app/registry/benchmarks.yaml`

```yaml
benchmarks:
  - id: hf_official_benchmarks
    canonical_name: Hugging Face Official Benchmarks
    display_name: Hugging Face Official Benchmarks
    benchmark_family: meta_registry
    owner_name: Hugging Face
    official_home_url: https://huggingface.co/docs/hub/eval-results
    has_official_leaderboard: true
    has_official_result_api: true
    primary_metric: varies
    known_splits: []
    known_metrics: []
    status: active

  - id: swe_bench_verified
    canonical_name: SWE-bench Verified
    display_name: SWE-bench Verified
    benchmark_family: software_engineering
    owner_name: SWE-bench
    official_home_url: https://www.swebench.com/
    official_leaderboard_url: https://www.swebench.com/
    has_official_leaderboard: true
    primary_metric: "% Resolved"
    known_splits:
      - Verified
    known_metrics:
      - "% Resolved"
    status: active

  - id: livecodebench
    canonical_name: LiveCodeBench
    display_name: LiveCodeBench
    benchmark_family: coding
    owner_name: LiveCodeBench
    official_home_url: https://livecodebench.github.io/
    official_leaderboard_url: https://livecodebench.github.io/leaderboard.html
    has_official_leaderboard: true
    primary_metric: Pass@1
    known_metrics:
      - Pass@1
    status: active
```

### `app/registry/models.yaml`

```yaml
models:
  - id: unknown_model_placeholder
    canonical_name: Unknown Model
    display_name: Unknown Model
    entity_type: unknown
    provider: unknown
    access_type: unknown
    status: active
    aliases: []
```

Start with almost no model list. Let official results populate `model_raw`, then review/mapping builds the model ledger over time.

### `app/registry/official_sources.yaml`

```yaml
sources:
  - id: hf_official_benchmark_discovery
    benchmark_id: hf_official_benchmarks
    source_name: Hugging Face official benchmark discovery API
    source_url: https://huggingface.co/api/datasets?filter=benchmark:official
    source_type: hf_benchmark_api
    officialness_level: O5
    machine_readable: true
    requires_auth: false
    supports_history: false
    update_cadence: daily
    parser_name: hf_benchmark_api
    status: active

  - id: swe_bench_verified_official_leaderboard
    benchmark_id: swe_bench_verified
    source_name: SWE-bench official leaderboard
    source_url: https://www.swebench.com/
    source_type: html_table
    officialness_level: O4
    machine_readable: true
    requires_auth: false
    supports_history: false
    update_cadence: manual
    parser_name: generic_html_table
    status: active
    parser_config:
      table_hint: leaderboard
      model_column: Model
      score_column: "% Resolved"

  - id: livecodebench_official_leaderboard
    benchmark_id: livecodebench
    source_name: LiveCodeBench official leaderboard
    source_url: https://livecodebench.github.io/leaderboard.html
    source_type: html_table
    officialness_level: O4
    machine_readable: true
    requires_auth: false
    supports_history: false
    update_cadence: manual
    parser_name: generic_html_table
    status: active
    parser_config:
      table_hint: leaderboard
      model_column: Model
      score_column: Pass@1
```

---

# Part 7: Practical Implementation Guidance

## 32. What to Tell Codex to Build First

First concrete task:

```text
Build the ledger foundation and fake ingestion test.
```

Do not start with Hugging Face. Do not start with scraping. Do not start with benchmark websites.

First prove:

```text
Can we create benchmarks?
Can we create models/systems?
Can we create official sources?
Can we snapshot a fake source?
Can we extract fake claims?
Can we deduplicate repeated runs?
Can we preserve raw score values?
```

Once this works, add the Hugging Face adapter.

---

## 33. Recommended Build Order

Correct order:

```text
1. Repo scaffold
2. Database schema
3. Snapshot storage
4. Fake adapter
5. Ingestion runner
6. Idempotency tests
7. Seed registry loader
8. Hugging Face official benchmark adapter
9. Generic JSON/CSV adapters
10. Generic HTML-table adapter
11. Review queue
12. Add more official benchmarks
13. Add scheduling
14. Add API/UI later
```

Do not reverse this. Scraping first will make the project messy.

---

## 34. Reliability Checklist

Before trusting any result claim, require:

```text
- official_source_id exists
- source_snapshot_id exists
- raw source content was saved
- content_hash exists
- model_raw is preserved
- benchmark_raw is preserved
- score_raw is preserved
- evidence_location exists
- capture_method exists
- validation record exists
- duplicate ingestion does not create duplicate rows
```

For high-trust claims:

```text
- deterministic parser validation passes
- source value can be re-read from evidence_location
- canonical model mapping is known
- officialness_level is O5/O4/O3/O1
```

---

## 35. First Working Demo

The first demo should be simple.

```bash
benchmark-ledger init-db
benchmark-ledger seed-registry
benchmark-ledger ingest --source hf_official_benchmark_discovery --dry-run
benchmark-ledger ingest --source hf_official_benchmark_discovery
benchmark-ledger claims list
```

Expected output on first real run:

```text
Ingestion complete.

Sources checked: 1
Snapshots created: 1
Snapshots reused: 0
Claims extracted: 120
Claims inserted: 120
Claims unchanged: 0
Claims needing review: 15
Errors: 0
```

Then rerun:

```bash
benchmark-ledger ingest --source hf_official_benchmark_discovery
```

Expected output:

```text
Ingestion complete.

Sources checked: 1
Snapshots created: 0
Snapshots reused: 1
Claims extracted: 120
Claims inserted: 0
Claims unchanged: 120
Claims needing review: 15
Errors: 0
```

That proves idempotency.

---

## 36. Later Additions

Only after MVP works:

```text
- web dashboard
- reviewer UI
- source-change diff viewer
- benchmark registry crawler
- model registry crawler
- official-source discovery assistant
- LLM-assisted extraction for hard official sources
- screenshot storage
- source reliability scoring
- model alias confidence scoring
- daily email/Slack summary
- public API
- MCP server for internal tools
- object storage backend
- deployment config
```

Codex MCP integration may be useful later if Codex becomes one agent inside a larger orchestrated workflow, but it is not needed for the MVP.

---

## 37. Final Recommendation

Use Codex as an implementation agent, but give it small, sequential engineering tickets.

The best first build is:

```text
benchmark-ledger v0.1
---------------------
- Python CLI
- Postgres-compatible ledgers
- local snapshot storage
- official source registry
- immutable result claims
- idempotent ingestion runner
- fake adapter with tests
- Hugging Face official benchmark API adapter
- fixture-based tests
```

Do not start by scraping many benchmark websites.

Start by making the ledger system correct.

Then each new benchmark becomes:

```text
1. Add benchmark registry row.
2. Add official source row.
3. Add or reuse adapter.
4. Add fixture.
5. Add parser test.
6. Run ingestion.
7. Review unmatched models.
```

That is the simplest implementation path that remains robust, reproducible, and extensible.

---

# Part 8: Additional Useful Implementation Notes

## A. Suggested `AGENTS.md`

Create this in the root of the repo so Codex follows the project rules.

```markdown
# AGENTS.md

## Project

This repository implements `benchmark-ledger`, an official benchmark result capture system.

The system does not run benchmarks and does not recalculate scores. It captures official benchmark result claims exactly as reported by official sources and stores immutable evidence-backed claims.

## Core rules

- Preserve raw source values exactly.
- Do not overwrite result claims.
- Snapshot source content before extraction.
- Every result claim must have `source_snapshot_id`, `official_source_id`, `score_raw`, `model_raw`, `benchmark_raw`, and `evidence_location`.
- Use official APIs and structured files before scraping.
- Use HTML parsing only when structured data is not available.
- Do not ingest articles, vendor blogs, newsletters, or social posts into the official result ledger.
- If model matching is uncertain, keep `model_raw`, leave `model_entity_id` null, and mark the claim `needs_review`.
- Running ingestion twice on the same source snapshot must not create duplicate claims.
- Do not deploy to paid cloud services or trigger paid operations.

## Development workflow

- Keep changes small and testable.
- Add tests for every adapter.
- Use saved fixtures for parser tests.
- Run tests before marking work complete.
- Update README when CLI behavior changes.

## Done means

A task is complete only if:

- Required schema or code exists.
- Tests cover expected behavior.
- Idempotency is preserved.
- Raw source values are preserved.
- CLI commands are documented when relevant.
```

---

## B. Recommended Environment Variables

`.env.example`:

```bash
# Database
DATABASE_URL=sqlite:///./data/benchmark_ledger.db
# For Postgres later:
# DATABASE_URL=postgresql://benchmark:benchmark@localhost:5432/benchmark_ledger

# Snapshot storage
SNAPSHOT_STORAGE_BACKEND=local
SNAPSHOT_LOCAL_ROOT=./data/snapshots

# HTTP behavior
HTTP_TIMEOUT_SECONDS=30
HTTP_USER_AGENT=benchmark-ledger/0.1

# Hugging Face
# Public endpoints may work without a token, but a read token can help with rate limits or gated resources.
HF_TOKEN=

# Ingestion
INGESTION_FAIL_FAST=false
```

---

## C. Suggested `docker-compose.yml`

Use this only for local Postgres development.

```yaml
services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_USER: benchmark
      POSTGRES_PASSWORD: benchmark
      POSTGRES_DB: benchmark_ledger
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data

volumes:
  pgdata:
```

---

## D. Claim Fingerprint Guidance

Compute a stable hash from raw claim identity fields.

Suggested fields:

```text
official_source_id
source_snapshot_id
model_raw
benchmark_raw
score_raw
metric_raw
split_raw
setting_raw
rank_raw
date_raw
evidence_location
```

Pseudocode:

```python
def compute_claim_fingerprint(claim: ResultClaimInput) -> str:
    payload = {
        "official_source_id": str(claim.official_source_id),
        "source_snapshot_id": str(claim.source_snapshot_id),
        "model_raw": claim.model_raw,
        "benchmark_raw": claim.benchmark_raw,
        "score_raw": claim.score_raw,
        "metric_raw": claim.metric_raw,
        "split_raw": claim.split_raw,
        "setting_raw": claim.setting_raw,
        "rank_raw": claim.rank_raw,
        "date_raw": claim.date_raw,
        "evidence_location": claim.evidence_location,
    }
    canonical_json = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return sha256(canonical_json.encode("utf-8")).hexdigest()
```

---

## E. Source Snapshot Hash Guidance

Compute the content hash from raw bytes, not parsed text.

```python
def compute_content_hash(raw_bytes: bytes) -> str:
    return sha256(raw_bytes).hexdigest()
```

For HTTP responses, store:

```text
raw bytes
content type
HTTP status
ETag
Last-Modified
final URL after redirects
response headers subset
fetch timestamp
```

---

## F. Review Queue Reasons

A claim should enter review if:

```text
- model_entity_id is null
- benchmark_id is null
- parser confidence below threshold
- score_raw is empty or malformed
- evidence_location is missing
- validation failed or uncertain
- same source snapshot has duplicate raw model/metric rows
- source type is dynamic page without stable structured extraction
- claim conflicts with a previous claim from the same source without an obvious source update
```

---

## G. Recommended Capture Status Values

```text
unreviewed
parser_verified
double_verified
human_verified
needs_review
disputed
deprecated
```

Recommended scientific status values:

```text
unknown
methodology_named
setup_described
artifacts_available
independently_reproducible
```

For the MVP, scientific status can default to `unknown`.

---

## H. Officialness Policy Details

```text
O5: Benchmark-owner official structured source/API/file.
    Example: official benchmark API or official JSON result file.

O4: Benchmark-owner official leaderboard.
    Example: official benchmark website leaderboard table.

O3: Benchmark-owner official result table/file in official repo.
    Example: GitHub CSV or README table maintained by benchmark owner.

O2: Benchmark-owner official dataset/eval repo only.
    Example: official benchmark repo with no maintained result table.

O1: Official framework leaderboard.
    Example: HELM, OpenCompass, MTEB, or Hugging Face benchmark leaderboard.

O0: Non-official source.
    Example: vendor blog, article, newsletter, social post, third-party roundup.
```

Default trusted ingestion:

```text
Ingest O5/O4/O3/O1.
Use O2 for benchmark metadata unless explicit result rows exist.
Do not ingest O0 into official result claims.
```

---

## I. Suggested Future Benchmark Registry Expansion

After the MVP works, consider adding official sources for:

```text
General / broad capability:
- HELM
- OpenCompass
- MMLU-Pro
- Humanity's Last Exam
- LiveBench

Chat / preference / instruction following:
- LMArena / Chatbot Arena
- AlpacaEval
- IFEval official dataset/framework source

Coding / software engineering:
- SWE-bench
- LiveCodeBench
- BigCodeBench
- Terminal-Bench
- HumanEval metadata only unless official result source exists
- GSM8K metadata only unless official result source exists

Tool use / agents:
- Berkeley Function Calling Leaderboard
- ARC-AGI / ARC Prize
- GAIA
- HAL
- WebArena / VisualWebArena
- OSWorld

Multimodal:
- MMMU
- MathVista
- Open VLM Leaderboard

Embeddings / retrieval:
- MTEB
- BEIR metadata/framework results
```

Add each source one at a time with a fixture and parser test.

---

## J. Acceptance Criteria for MVP v0.1

The MVP is acceptable when this works:

```bash
benchmark-ledger init-db
benchmark-ledger seed-registry
benchmark-ledger ingest --source hf_official_benchmark_discovery --dry-run
benchmark-ledger ingest --source hf_official_benchmark_discovery
benchmark-ledger claims list
benchmark-ledger review queue
```

And tests verify:

```text
- database initializes successfully
- registry seeds successfully
- fake adapter creates snapshots and claims
- repeated ingestion is idempotent
- raw score values are preserved
- evidence locations validate against fixture content
- unmatched models go to review queue
- duplicate claims are not inserted
```

---

## K. Risks and Mitigations

### Risk: Scrapers become fragile

Mitigation:

```text
Use official APIs and structured files first.
Keep source-specific adapters small.
Use fixture tests.
Snapshot raw content.
Mark uncertain extraction as needs_review.
```

### Risk: Model names are ambiguous

Mitigation:

```text
Preserve model_raw.
Make model_entity_id nullable.
Use alias ledger.
Review unknown mappings manually.
Distinguish models from agent systems.
```

### Risk: Official leaderboards change historical values

Mitigation:

```text
Never overwrite claims.
Create new snapshots and new claims.
Link with claim_relationships.
Keep source hashes and capture timestamps.
```

### Risk: Some benchmarks have no official result source

Mitigation:

```text
Store benchmark metadata only.
Mark has_official_results = false.
Ingest framework leaderboards separately as O1, not as original benchmark-owner results.
```

### Risk: Dynamic pages hide data in JavaScript

Mitigation:

```text
Inspect static assets and network calls.
Prefer JSON payloads over rendered HTML.
Use browser rendering only when necessary.
```

### Risk: The project grows too broad too early

Mitigation:

```text
Implement one adapter at a time.
Every source needs a fixture test.
No UI until ingestion and ledgers are reliable.
```

---

## L. Recommended First GitHub Issues

### Issue 1: Project scaffold

```text
Create Python package, CLI skeleton, config loader, local snapshot storage, schemas, tests, README, and AGENTS.md.
```

### Issue 2: Database ledgers

```text
Implement database tables, migrations/init, repository methods, uniqueness constraints, and seed loader.
```

### Issue 3: Fake adapter and ingestion runner

```text
Build adapter registry, fake adapter, ingestion runner, snapshot persistence, claim insertion, and idempotency tests.
```

### Issue 4: Hugging Face official benchmark adapter

```text
Implement HF official benchmark discovery and leaderboard capture using official APIs, with fixtures and JSON-path validation.
```

### Issue 5: Generic structured adapters

```text
Implement generic JSON and CSV adapters using parser_config and evidence-location validation.
```

### Issue 6: Static HTML table adapter

```text
Implement simple static HTML table extraction using parser_config, with fixture tests and needs_review fallback.
```

### Issue 7: Review queue CLI

```text
Add commands to list, inspect, map, alias, and human-verify claims needing review.
```

### Issue 8: Daily ingestion readiness

```text
Add --all, --benchmark, --source, --dry-run, run summaries, nonfatal per-source failures, and scheduling docs.
```

---

## M. Final Handoff Summary

Build the database first, not the scrapers.

The robust architecture is:

```text
Benchmark Ledger
  Defines benchmarks and official resources.

Model/System Ledger
  Defines models, systems, aliases, and raw/canonical mapping.

Official Source Ledger
  Defines which sources are allowed into trusted ingestion.

Snapshot Ledger
  Saves exact source content before extraction.

Result Claim Ledger
  Stores exact official values as immutable source-backed claims.

Validation Ledger
  Proves each stored value matches the source.

Relationship Ledger
  Tracks duplicates, conflicts, and source updates.

Ingestion Run Ledger
  Tracks every run and its summary.
```

The simplest reliable implementation path is:

```text
1. Create the ledgers.
2. Prove idempotent fake ingestion.
3. Add Hugging Face official benchmark API ingestion.
4. Add generic structured adapters.
5. Add static HTML-table ingestion.
6. Add review queue.
7. Add more official sources one by one.
```

Everything else can come later.
