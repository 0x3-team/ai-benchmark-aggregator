---
name: quality-orchestration
description: Use when selecting or supervising an agent, model, harness, or validation route for this repository.
---

# Quality orchestration

Keep the repository owner accountable for integration and acceptance. Select a route by task fit, evidence, privacy, risk, and ownership; cost and speed only break quality ties.

- Planning belongs to the planning route; implementation, integration, and acceptance stay with the implementation owner.
- External agents may receive only bounded, non-sensitive candidate work. They do not own shared contracts, deployment, migrations, secrets, or final acceptance.
- Re-check model, effort, auth, and harness identity before dispatch. A catalog name or prior run is not proof.
- Use exact fallback order and record every failed or blocked predecessor.
- Never send secrets, private archives, credentials, or unrelated worktree files.
- Inspect the actual diff and rerun decisive checks before accepting output.

Receipt fields: route, provider, model, requested/effective effort, scope, files, evidence, result (`ACCEPTED`, `REWORK`, `REJECTED`, or `BLOCKED`), and cleanup.
