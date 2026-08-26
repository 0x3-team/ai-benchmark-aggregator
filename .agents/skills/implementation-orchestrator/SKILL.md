---
name: implementation-orchestrator
description: Use for multi-surface implementation, audit remediation, or a saved plan that needs bounded execution and acceptance checks.
---

# Implementation orchestrator

Anchor `AGENTS.md`, the source artifact, branch, dirty state, and acceptance contract before editing. Keep the parent responsible for integration and acceptance.

## Loop

1. Define scope, non-goals, source of truth, contract boundary, evidence, stop conditions, and validation.
2. Choose parent-only or bounded workers. Never overlap write ownership.
3. Implement small slices using existing patterns.
4. Inspect every diff and treat worker reports as claims until verified.
5. Run focused checks, then the broader relevant gates.
6. Separate local, browser, live, pushed, deployed, and blocked states.

Do not claim `verified` without target-perspective evidence. Preserve unrelated changes and do not add a second source of truth without a cutover plan.
