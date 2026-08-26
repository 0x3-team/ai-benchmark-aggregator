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

## CI billing block

GitHub Actions on this private repo intermittently refuses to start jobs: runs fail in 2–6 seconds, upload no logs, and each failed check-run carries the annotation "The job was not started because recent account payments have failed or your spending limit needs to be increased." Reruns cannot fix this state.

Standing workaround (owner-approved):

1. Confirm the signature from the check-run annotations, not from the run list.
2. Scan for committed secrets before any visibility change: tracked files, history filenames, and high-signal patterns. Never flip a repository that fails the scan.
3. Switch the repository to public (repo Settings → General → Danger Zone). Public repos run standard GitHub-hosted runners on free minutes. Visibility changes need repo admin, which agent tokens lack — a human flips it.
4. Rerun the failed run (or push) and verify the checks go green.
5. Switch the repository back to private, and record both flips plus the CI result in the receipt.

## Acceptance rules

- A skipped test is not a pass.
- A local pass does not prove GitHub CI, deployment, live behavior, or production readiness.
- Record exact commit SHA, commands, results, warnings, and cleanup evidence.
- Inspect `git diff --check` and preserve unrelated dirty files.
- Report states separately: validated locally, pushed, CI passed/blocked, deployed, live-verified, and remaining work.
