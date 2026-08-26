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

## Acceptance rules

- A skipped test is not a pass.
- A local pass does not prove GitHub CI, deployment, live behavior, or production readiness.
- Record exact commit SHA, commands, results, warnings, and cleanup evidence.
- Inspect `git diff --check` and preserve unrelated dirty files.
- Report states separately: validated locally, pushed, CI passed/blocked, deployed, live-verified, and remaining work.
