# Software Orchestrator handoff

This skill prepares a corpus. The Software Orchestrator executes it.

## Canonical files

1. `manifest.json`
2. `requirements/requirements.jsonl` + `traceability.json`
3. `tasks/tasks-*.jsonl` (sharded)
4. `graph/edges.jsonl` + `execution-waves.json` + `conflict-sets.json`
5. `indexes/*`

Markdown under `human/` is generated views, not source of truth.

## Load order for a ready task

1. `manifest.json` (readiness, shards, digests)
2. `graph/execution-waves.json` → pick ready wave
3. `indexes/by-status.json` / wave membership
4. Open only the shard containing the task
5. Load `source_refs` / requirement records as needed

Never load all shards into one context.

## Ready tasks

A leaf is orchestrator-ready when:

- `dispatchable: true`
- `status` in `READY` (or PLANNED if policy allows)
- All hard dependencies are INTEGRATED/VERIFIED in orchestrator state
- No blocking_decision_ids open
- Write scope conflicts checked against running work

## Routing

Use `capability_tags`, `suggested_agent_role`, `tools_required`, `estimated_context_size`, `risk`, `complexity`, `security_sensitivity`.  
**Do not** treat any field as a permanent model assignment.

## Completion reporting

Orchestrator results should reference `task_id` and `plan_version`.  
Status updates live in orchestrator state; corpus updates use CORPUS_UPDATE mode without silently rewriting in-progress IDs.

## Parallelism

Respect `parallelization.parallelizable`, `conflict_keys`, `write_scope`, `execution_wave`.
