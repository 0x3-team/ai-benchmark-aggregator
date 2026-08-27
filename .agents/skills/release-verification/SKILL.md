---
name: release-verification
description: Use before merging or releasing benchmark-platform changes. Run the repository's frontend, ledger, artifact, provenance, static, and bundle gates and separate local proof from remote or live status.
---

# Release verification

Use this skill for release checks, CI diagnosis, checkpoint closeout, and handover updates.

## Local gates

```sh
npm run typecheck
npm run typecheck:test
npm test
npm run build
npm run verify:official-artifact
npm run verify:build-provenance
npm run verify:pages-static
npm run verify:bundle-budget
cd ledger && python scripts/verify_ci_lock.py && pytest -q
```

Run only the relevant subset first when debugging, then the complete set before acceptance.

## CI diagnosis

This repository is public and must remain public. Never change visibility as a
CI workaround.

1. Pin the exact candidate commit SHA. Read the workflow run, job, check-run,
   annotation, and event evidence before classifying the failure.
2. Distinguish an absent run from queued, runner, workflow, account, and test
   failures. Diagnose the exact state instead of treating every missing check as
   a code failure.
3. Rerun the same candidate when the workflow supports it. A push creates a new
   candidate; explicitly promote and record that SHA before acceptance.
4. Require the complete named checks on the exact candidate. Record the run ID,
   event, SHA, job conclusions, and any cancelled redundant run.
5. If a future policy change proposes different visibility, stop. It needs a
   separately reviewed, per-use owner decision that audits reachable Git
   history, retained Actions logs and artifacts, public-fork persistence,
   secrets, and runner billing. That policy change is outside this skill.

## Acceptance rules

- A skipped test is not a pass.
- A local pass does not prove GitHub CI, deployment, live behavior, or production readiness.
- Record exact commit SHA, commands, results, warnings, and cleanup evidence.
- Inspect `git diff --check` and preserve unrelated dirty files.
- Report states separately: validated locally, pushed, CI passed/blocked, deployed, live-verified, and remaining work.
