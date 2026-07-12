# Goal mode (run-to-completion)

## Intent

When the Software Orchestrator is invoked with a **goal document** (plan, PRD, handoff, checklist, implementation plan, ticket pack), treat that document as a **standing goal**.

Same spirit as Hermes `/goal` and kanban `goal_mode=True`:

- Keep working **until the goal is achieved**
- Do **not** end the turn with a plan-only status, a partial summary, or “next steps for you”
- Stop early **only** for true blockers (below)

## Goal document is law

The attached/referenced document is the acceptance source of truth.

1. Read the full document (and linked paths it names).
2. Normalize it into a requirements matrix + task DAG.
3. Map **every** requirement/section/checkbox to task coverage.
4. The goal is **not complete** while any requirement is open, failed, or unverified.

If the document is multi-phase, finish **all** in-scope phases unless the user scoped a subset.

## Invocation shapes

```text
/software-orchestrator
/goal + software-orchestrator
Invoke Software Orchestrator on <path-or-attached-doc>
```

Any of these with an attached file, pasted plan, or path → **Goal Mode**.

If no document is provided, ask once for the goal artifact (path or paste). Do not invent a project.

## Completion loop (tight)

```text
while goal_incomplete and not hard_blocked:
  pick next READY tasks (respect deps)
  self-execute or delegate
  validate + review + integrate
  mark requirements covered with evidence
  re-check document coverage
report final status against the document
```

**Never exit the loop because:**

- A milestone finished (continue to remaining sections)
- A worker finished one task
- You wrote a plan or “proposed approach”
- Context feels long (summarize into durable state; keep going)
- You are “waiting for the user” without a hard blocker

## Hard blockers (only legal early stops)

Stop and surface a **decision-ready** blocker only when:

| Blocker | Example |
|---------|---------|
| Missing secret/credential the environment cannot provide | No API key and no alternative path |
| Explicit human policy gate | Prod deploy, destructive migration, force-push, billing change |
| Irreconcilable product ambiguity | Two mutually exclusive requirements, both blocking |
| External system down with no workaround | Critical upstream outage after retries |
| User-imposed budget/time hard stop | “Stop after $X / N tasks” |
| Safety/policy refusal | Malicious or disallowed action |

**Not blockers** (must continue):

- Preference unknowns → record conservative assumption, proceed
- Optional nice-to-haves unclear → defer or minimal default
- Worker failure → retry once, then takeover, continue graph
- Flaky test → investigate, quarantine with evidence, continue other work when safe
- Large scope → chunk into DAG; still finish the document

When blocked: state the exact decision needed, options, recommended default, and what remains incomplete in the document. Do **not** abandon remaining non-blocked work if any can proceed in parallel.

## Coverage ledger (required)

Maintain until done:

| Doc ref | Requirement | Task IDs | Status | Evidence |
|---------|-------------|----------|--------|----------|
| §2.1 | … | T3,T4 | VERIFIED | test log path |

Goal complete **only when** every in-scope row is `VERIFIED` or explicitly `OUT_OF_SCOPE` (with user authority or document exclusion).

## Progress reporting

While running, emit short progress pulses (not exits):

- What finished
- What is next
- Coverage % of document
- Open blockers (if any)

Final message only when:

1. Coverage ledger complete, or  
2. Hard-blocked with decision-ready question and max residual progress made  

## Anti-patterns

1. Stopping after “Phase 1 done” while later phases are in the same goal doc  
2. Returning only a plan when the user attached an implementation plan  
3. Asking optional questions instead of assuming + recording  
4. Waiting on a worker without takeover path  
5. Marking the goal done without project-wide verification mapped to the doc  
