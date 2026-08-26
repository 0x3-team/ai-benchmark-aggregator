# Release rehearsal evidence-receipt template

**Status:** Blank template — every cell/line below is a receipt slot to fill by
the operator who actually performs the step. An empty field means **not yet
known / not yet executed**, never a pass.

This is the fill-in companion to the
[release, withdrawal, and rollback rehearsal runbook](release-withdrawal-rollback-rehearsal.md).
Each subsection proves exactly one of the strict states in that runbook (§1
state separation). Do **not** copy a value from a more advanced state into a
lesser one, and do **not** claim a state a receipt does not prove.

> **Never** record raw credentials, tokens, raw source bytes, database URLs,
> object-store paths, customer/visitor PII, or headers/cookies here. Use redacted
> IDs only (see the incident/telemetry runbook).

---

## 0. Operator and evaluated commit

| Field | Value |
| --- | --- |
| Operator (role, not personal identity if avoidable) | `___` |
| UTC timestamp(s) | `___` |
| `repo.commit` (`git rev-parse HEAD`) | `___` |
| `repo.branch` | `___` |
| Worktree state at capture (`git status --short`) | `___` (attach/point to output) |
| Rehearsal mode (shadow / copy-only) | `___` |

---

## 1. Validated locally

Proves only the **validated locally** state.

| Check | Command (link to §4) | Exit / result | As-of commit | Pass? |
| --- | --- | --- | --- | --- |
| Repo HEAD/branch | `git rev-parse HEAD` / `git branch --show-current` | `___` | `___` | `___` |
| Diff hygiene | `git diff --check` | `___` | `___` | `___` |
| Typecheck | `npm run typecheck` | `___` | `___` | `___` |
| Offline Official verifier | `npm run verify:official-artifact` | `___` | `___` | `___` |
| Build | `npm run build` | `___` total JS bytes | `___` | `___` |
| Static Pages verifier | `npm run verify:pages-static` | `___` | `___` | `___` |
| Ledger CLI help (fresh process) | `.venv/bin/benchmark-ledger --help` | `exit` `___` | `___` | `___` |
| Ledger suite (optional) | `.venv/bin/pytest -q` | `___ passed / ___ skipped` | `___` | `___` |

> The only build-output number to record here is **initial eager JS bytes** from
> `npm run build` (`index-*.js` size). Total JS after any future lazy split /
> deferred chunks is a separate measurement; do not compare total JS against the
> 1.1 MB eager budget.

---

## 2. CI verified

Proven only after a `Verify` workflow run on the **exact candidate commit**.

| Field | Value |
| --- | --- |
| GitHub run URL / run id | `BLOCKED / NOT EXECUTED` |
| Workflow (`ledger`, `frontend`, `clean-archive`) results | `___` |
| Commit the run evaluated | `___` |
| Note: CI result for a different commit is not evidence for this one | — |

---

## 3. Pushed

Proven only after the candidate is pushed to the remote.

| Field | Value |
| --- | --- |
| `origin` / remote + branch | `BLOCKED / NOT EXECUTED` |
| Pushed commit | `___` |
| Remote `git rev-parse origin/main` matches candidate? | `___` |

---

## 4. Deployed

Proven only by an authenticated provider showing the exact built artifact for
the candidate commit.

| Field | Value |
| --- | --- |
| Provider / project (Cloudflare Pages) | `BLOCKED / NOT EXECUTED` |
| `deploy.target` (branch/custom host) | `___` |
| `deploy.commit` (deployment-to-commit identity) | `___` |
| `deploy.url` (live + `*.pages.dev` preview) | `___` |
| Built artifact set on the host (`index*.js`, `index*.css`, `404.html`, `_headers`, `robots.txt`) | `___` |

---

## 5. Verified live

Proven only by an authenticated live-host/browser receipt tied to that
deployment.

| Field | Value |
| --- | --- |
| Native-browser / `iab`-capable browser receipt | `BLOCKED / NOT EXECUTED` |
| Route/header matrix result (see runbook §5b smoke list) | `___` |
| Grep the served HTML matches `deploy.commit`? | `___` |
| Console/network error receipt | `___` |

---

## 6. Smoke gate (runbook §5b)

| # | Check | Result | Status |
| --- | --- | --- | --- |
| 1 | Root serves expected commit's built HTML | `___` | BLOCKED |
| 2 | Unknown path 404 via top-level `404.html` | `___` | BLOCKED |
| 3 | Plain-text `robots.txt` + canonical | `___` | BLOCKED |
| 4 | `_headers` directives present | `___` | BLOCKED |
| 5 | No Official value under Demo/unavailable | `___` | BLOCKED |
| 6 | Console/network/keyboard clean | `___` | BLOCKED |

## 7. Withdrawal (runbook §5c)

| Field | Value |
| --- | --- |
| Withdrawal decision id + reason | `BLOCKED / NOT EXECUTED` |
| Artifact id/digest/policy withdrawn | `___` |
| Public `unavailable`/`withdrawn` state published | `___` |
| Cache-SLA evidence + detection/action time | `___` |
| Correction path + follow-up source/review decision | `___` |
| Owner + redacted account | `___` |

## 8. Rollback (runbook §5d)

| Field | Value |
| --- | --- |
| Previous deployment identity (commit/artifact/digest) | `BLOCKED / NOT EXECUTED` |
| Rollback action record | `___` |
| Post-rollback verification (runbook §6 blocklist) | `___` |
| Deployment-to-commit after rollback | `___` |

## 9. Evidence retention ledger

| Artifact | Location | Retention placeholder | Owner |
| --- | --- | --- | --- |
| commit/git status | `___` | 2 years (placeholder) | `UNASSIGNED` |
| artifact + digest + policy | `___` | 2 years | `UNASSIGNED` |
| deploy identity + route | `___` | 2 years | `UNASSIGNED` |
| REL-05 decision | `___` | 2 years | `UNASSIGNED` |
| withdrawal/rollback proof | `___` | 2 years | `UNASSIGNED` |
| incident/disclosure | `___` | policy + 2 years | `UNASSIGNED` |

---

## Instructions

- **Do not** copy a deployment/published value into the `validated locally` row
  or claim a provider state you have not executed.
- **Keep this file blank** until each step is actually performed by an
  authorized operator who fills it in from their own receipt.
- Fill `__` fields only from the executed command's output; never from
  memory, a prior state, or a teammate's screen.
- Link or append each exact command output (exit + relevant line) rather than
  quoting it abstractly.
- Any missing executable check that is really needed should be recorded in the
  runbook's §8 residual list, not invented inline here.