# Output Contract

## Canonical storage

- JSONL task shards are authoritative.
- Graph edges are authoritative in `graph/edges.jsonl`.
- Markdown is a generated view.
- Indexes may be rebuilt and must not contain unique source data.

## Manifest invariants

The manifest records:

- Project and corpus identity
- Mode and version
- Source digests
- Schema version
- Counts
- Shard inventory
- Readiness
- Audit status
- Creation and update timestamps

## Task status values

- `PLANNED`
- `PROVISIONAL`
- `BLOCKED`
- `READY`
- `RETIRED`

The decomposer does not use runtime execution statuses such as running, review, or integrated. Those belong to the Software Orchestrator.

## Dependency semantics

- `hard_dependencies`: task IDs whose artifacts are required before this task can start or finish correctly.
- `soft_dependencies`: related tasks that improve coordination but do not block execution.
- `blocking_decision_ids`: unresolved decisions that prevent readiness.
- `conflict_keys`: shared resources that prevent unsafe parallel execution.

## Acceptance criteria

Each criterion contains:

- Stable criterion ID
- Observable statement
- Verification type
- Optional command, query, inspection, or artifact reference
- Requirement IDs
- Whether it is mandatory

Preferred verification types:

- `TEST`
- `BUILD`
- `TYPECHECK`
- `LINT`
- `STATIC_ANALYSIS`
- `SECURITY_SCAN`
- `CONTRACT_CHECK`
- `SCHEMA_CHECK`
- `PERFORMANCE_CHECK`
- `ACCESSIBILITY_CHECK`
- `MANUAL_INSPECTION`
- `DOCUMENT_REVIEW`
- `METRIC_CHECK`
- `DEPLOYMENT_CHECK`

## Corpus update semantics

- `UNCHANGED`: same semantic task and stable ID.
- `CHANGED`: same task identity, altered constraints or criteria.
- `ADDED`: new task.
- `SPLIT`: old task retired and replaced by multiple tasks.
- `MERGED`: multiple old tasks retired and replaced by one task.
- `RETIRED`: no longer required.

Never delete history for tasks already consumed by an orchestrator.
