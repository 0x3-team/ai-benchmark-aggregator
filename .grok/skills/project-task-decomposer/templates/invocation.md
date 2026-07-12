# Invocation templates

## PRD_ONLY

```text
/project-task-decomposer
Analyze @product-requirements.md in PRD_ONLY mode.
Target range: 1,000-2,500 dispatchable leaves if genuinely supported.
Mark inferred architecture provisional.
Do not invent repository paths.
Create architecture-decision and repository-binding tasks.
Do not implement the product.
Do not assign models.
```

## PRD_PLUS_REPO

```text
/project-task-decomposer
Input documents:
- @docs/product-handoff.md
- @docs/nonfunctional-requirements.md
Repository: current workspace
Mode: PRD_PLUS_REPO
Target leaf range: 1,500-3,000
Maximum leaf tasks: 5,000
Tasks per shard: 250
Output project slug: example-product
Plan version: 1.0.0
Constraints:
- Preserve architecture unless a decision task justifies change
- Include implementation, verification, security, privacy, a11y, observability, migration, release, rollback, docs, cleanup when applicable
- Do not assign models or implement the product
- Do not pad task count
- Mark destructive actions approval-gated
```

## CORPUS_UPDATE

```text
/project-task-decomposer
Mode: CORPUS_UPDATE
Existing corpus: @.orchestrator/plans/example-product/1.0.0/
Updated requirements: @docs/product-requirements-v2.md
New plan version: 1.1.0
Preserve stable task IDs where semantic identity is unchanged.
Produce changes/corpus-diff.json.
Do not silently modify in-progress tasks.
```
