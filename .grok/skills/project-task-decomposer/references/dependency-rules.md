# Dependency rules

## Hard dependencies

Add a hard edge **A → B** only when B cannot correctly start or complete without an artifact/decision/schema produced by A.

Phrase the edge as: `B requires artifact X produced by A.`

Typical hard edges:

- Decision → dependent design/implementation
- Contract → producer/consumer implementation
- Schema → persistence implementation
- Migration → code requiring new shape
- Implementation → integration/e2e verification
- Deployment prep → rollout → post-release validation

## Soft dependencies

Use soft dependencies for relatedness that does not block correctness (ordering preference, shared context, optional optimizations).

## Parent/child

Hierarchy edges are **not** execution dependencies. Represent them in `parent_task_id` / `ancestor_ids`, optionally also as `PARENT_CHILD` in `graph/edges.jsonl`.

## Barriers

When many leaves depend on many upstream leaves, insert a BARRIER/milestone node to avoid edge explosion.

## Validation

- No missing endpoints
- No self-edges
- No cycles
- No dependency on RETIRED tasks without supersession
