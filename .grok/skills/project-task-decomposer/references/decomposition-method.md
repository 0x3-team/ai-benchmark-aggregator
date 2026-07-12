# Decomposition Method

## 1. Goal

Transform product intent into an execution graph whose leaf tasks can be assigned independently, verified objectively, and integrated safely.

## 2. Decomposition lattice

Use four axes to discover meaningful work:

1. **Product axis** — actor, journey, capability, feature, state, and outcome.
2. **System axis** — client, API, domain, data, integration, infrastructure, and operations.
3. **Lifecycle axis** — decide, design, implement, migrate, verify, release, observe, support, and retire.
4. **Quality axis** — correctness, security, privacy, reliability, performance, accessibility, usability, maintainability, and compliance.

For each feature, evaluate applicable cells in the lattice. Create tasks only for cells with a concrete artifact and verifier.

## 3. Task-size heuristic

A leaf should normally satisfy all of these:

- One primary verb and one primary outcome.
- One coherent owner archetype.
- One bounded artifact cluster.
- No unresolved architectural decision inside the implementation step.
- A direct verifier.
- `XS`, `S`, or `M` complexity.

Suggested interpretation:

- `XS`: localized change or artifact with one direct check.
- `S`: one component and a small set of tests.
- `M`: bounded multi-file change in one component with integration verification.
- `L`: multiple components, responsibilities, or deployment phases; must be split.
- `XL`: epic or workstream; never dispatch as a leaf.

## 4. Split signals

Split when a task:

- Contains unrelated conjunctions.
- Changes more than one independently deployable component.
- Requires different specialist roles.
- Has acceptance criteria with unrelated verification methods.
- Contains an unresolved decision and implementation.
- Mixes schema, migration, application changes, rollout, and cleanup.
- Has an `L` or `XL` size.

## 5. Merge signals

Merge when tasks:

- Are individually trivial and share the same artifact and verifier.
- Would always be assigned together.
- Have no meaningful independent completion state.
- Create more orchestration overhead than execution value.

## 6. Dependency construction

Prefer artifact dependencies. Phrase each edge as:

`Task B requires artifact X produced by Task A.`

If that sentence cannot be completed concretely, the edge may be a soft relationship rather than a hard dependency.

Use milestone/barrier nodes for many-to-many dependencies. Avoid connecting every upstream leaf to every downstream leaf.

## 7. Requirement coverage

For each material requirement, require:

- At least one delivery task.
- At least one verification task.
- Explicit negative/error behavior when applicable.
- Authorization and security work when applicable.
- Observability or measurable success evidence when applicable.
- Rollout and rollback work when risk warrants it.

## 8. PRD-only uncertainty

When implementation details are unavailable:

- Use logical component names.
- Set `requires_repo_binding: true`.
- Create discovery or decision tasks for architecture choices.
- Avoid invented file paths and commands.
- Keep implementation tasks provisional when their scope depends on the decision.

## 9. Corpus scaling

For thousands of tasks:

- Freeze vocabulary before parallel generation.
- Generate by workstream.
- Write JSONL shards incrementally.
- Use indexes rather than rereading every task for normal routing.
- Run cross-shard audits after local validation.
- Keep summaries in chat and full records on disk.
