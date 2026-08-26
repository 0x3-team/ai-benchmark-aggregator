# Release, withdrawal, and rollback rehearsal runbook

**Status:** Copy-only rehearsal template — no deployment, withdrawal, rollback,
provider, or Official-publication step has been authorized or executed.

This runbook is the **operator-facing rehearsal** companion to the
[release artifact and withdrawal runbook](release-artifact-and-withdrawal.md)
(procedure design) and the [official publication and evidence preservation
runbook](official-publication-and-evidence-preservation.md) (containment
procedure). It turns those procedures into an executable rehearsal **template**
that records exact evidence and separates state, but it never runs a live
action itself. Every step that touches a provider, an authenticated account, an
Official artifact, a live frontend, or a remote is explicitly marked
**NOT EXECUTED** (or **BLOCKED**) until an authorized operator performs it and
fills in the receipt evidence.

Source of truth for state vocabulary, the LDR-08 candidate projection, the
REL-05 gate, the official-release-artifact schema, and the "never serve a
candidate feed as a live Official release" rule:

- [Release artifact and withdrawal runbook](release-artifact-and-withdrawal.md)
- [Official publication and evidence preservation runbook](official-publication-and-evidence-preservation.md)
- [Launch charter and decision record](launch-charter-and-decision-record.md)
- [Frontend scale and browser-evidence protocol](frontend-scale-and-browser-evidence.md)
- [Incident, telemetry, and disclosure baseline](incident-telemetry-and-disclosure.md)
- Artifact schemas: [`docs/contracts/official-release-artifact-v1.schema.json`](../contracts/official-release-artifact-v1.schema.json) and [`official-release-artifact-v2.schema.json`](../contracts/official-release-artifact-v2.schema.json)
- Offline artifact verifier (containment input): [`scripts/verify-official-artifact.mjs`](../../scripts/verify-official-artifact.mjs)
- Static Pages controls (in `public/`: `404.html`, `_headers`, `robots.txt`) and their verifier: [`scripts/verify-pages-static.mjs`](../../scripts/verify-pages-static.mjs)

> Do not run any live command that deploys, withdraws, rolls back, publishes an
> Official artifact, mutates a provider/database, fetches a source, or sends
> credentials. Until the blocklists in §5 clear, the only executed result is the
> read-only local validation named in §4.

---

## 1. State separation (record exactly which state each receipt proves)

A rehearsal receipt must state **which** state it proves and must not claim a
more advanced state. The five states below are distinct and must be kept strict:

| State | Proven by | How it is shown |
| --- | --- | --- |
| **Validated locally** | Local, CPU-only, no-provider command output (typecheck, tests, build, offline verifiers) | Yes, can be proven now (see §4). |
| **CI verified** | A `Verify` workflow run on the exact candidate commit | Only after a push is authorized (blocked now). |
| **Pushed** | `git` remotes showing the candidate `HEAD` | Only after push is authorized (blocked now). |
| **Deployed** | A provider (e.g. Cloudflare Pages) showing the exact built artifact for the candidate commit | BLOCKED — no provider authority. |
| **Verified live** | An authenticated live host/browser receipt tied to that deployment | BLOCKED — no provider or native-browser authority. |

No local test, local build, offline verifier, or `git status` proves a later
state. Claiming anything past the first row without the matching receipt is a
rupture of this lane.

---

## 2. Exact identifiers to record (fill in every field below)

Every receipt in the blank template
([`release-rehearsal-evidence-receipt.md`](release-rehearsal-evidence-receipt.md))
must pin these identifiers. Empty means "not yet known" and is **NOT** a pass.

| Identifier | Meaning | Rehearsal value |
| --- | --- | --- |
| `repo.commit` | `git rev-parse HEAD` (the exact commit evaluated) | `___` |
| `repo.branch` | `git branch --show-current` | `___` |
| `artifact.id` | canonical artifact ID for the LDR-08 projection | `NONE (containment)` |
| `artifact.digest` | content hash of the exact artifact bytes | `NONE` |
| `artifact.policy` | `official-release-artifact-v{1,2}` policy version | `NONE` |
| `artifact.published_frontend` | frontend build identity bound at REL-05 | `NONE` |
| `deploy.target` | Cloudflare Pages project + branch/custom host | `BLOCKED` |
| `deploy.commit` | deployment-to-commit identity on the provider | `BLOCKED` |
| `deploy.url` | the live URL and/or `*.pages.dev` route | `BLOCKED` |
| `release.approval_decision` | REL-05 approval decision id + signer | `NONE` |
| `withdrawal.decision` | revocation/withdrawal decision id + reason | `NONE` |
| `rollback_target` | exact previous deployment/commit/artifact hash | `BLOCKED` |

> The project ships only the tracked `src/data/official/export.unavailable.json`
> unavailable artifact; `export.from-ledger.json` is not produced (the CLI
> `export-official-json` command intentionally exits 2 during containment). See
> `scripts/verify-official-artifact.mjs`. That is the only legal Official input
> today.

---

## 3. Owners (all `UNASSIGNED` until launch charter is completed)

The [launch charter](launch-charter-and-decision-record.md) is the authority
for ownership. Every row below is `UNASSIGNED` today and every linked ownership
field in the template must be filled by the operator who actually performs the
step.

| Role | RTO/RPO-relevant duty |
| --- | --- |
| Release / REL-05 signer | Authorize one atomic frontend selection; no other artifact accepted. |
| Deployment / rollback owner | Own the Cloudflare deployment + rollback target and the deploy-to-SHA receipt. |
| Withdrawal / cache-SLA owner | Own the four-hour (proposed) withdrawal/cache SLA and the public withdrawn state. |
| Telemetry / monitoring owner | Own release/promotion/rollback events (see incident runbook). |
| Incident / disclosure owner | Own the incident handling template + approved disclosure SLA. |
| Source / revision owner | Own the certified source/revision and source cert decision. |
| Legal / retention reviewer | Own the two-year retention / legal hold / privacy decision. |

RTO/RPO and retention **placeholders** (from the launch charter P0-04):

| Target | Proposed value | Owner / status |
| --- | --- | --- |
| `RPO` | no more than one scheduled source-capture cycle; proposed ≤ 24 h (daily) | UNASSIGNED |
| `RTO` | ≤ one business day | UNASSIGNED |
| `WITHDRAWAL_SLA` | withdraw an incorrect public artifact within 4 h | UNASSIGNED |
| `RETENTION` | retain release artifacts/evidence for two years | UNASSIGNED |
| `HOLD/LEGAL` | Legal | UNDECIDED |

These are **proposed targets** recorded in the charter, not provider/deploy
ability. Do not claim a recovery/release SLA is met from a proposal.

---

## 4. Executable now — read-only local proof (this is the only `validated locally` state)

The following are the only steps that are **validated locally today**. Run them
against the current dirty worktree and record each **exact exit and result** in
the blank template. They never touch a provider or a live network:

```bash
# State the evaluated commit
git rev-parse HEAD
git branch --show-current
git status --short

# Diff hygiene (do not fix, just record — the worktree is intentionally dirty)
git diff --check

# Frontend: typecheck, offline artifact verifier, build, static Pages verifier
npm ci                      # from a clean checkout only; not needed if node_modules is current
npm run typecheck
npm run verify:official-artifact   # offline verifier of the tracked unavailable artifact
npm run build
npm run verify:pages-static        # requires a built dist (exit 1 without it)

# Ledger: read-only CLI help in a fresh process (no DB init/migrate/ingest)
cd ledger && .venv/bin/benchmark-ledger --help; echo "cli_help_exit=$?"
cd ledger && .venv/bin/pytest -q    # full suite — heavy; optional for this slice
# NOTE: `reports legacy-inventory` is read-only but requires a database copy;
# do not run it against a claim-bearing ledger. See the official-publication
# runbook "Do not run" list.
```

Record these exact baselines in the template. The bundle bytes (from
`npm run build`) and any CLI exit code are the only current, local, runnable
release-inputs.

> Do **not** run `benchmark-ledger ingest`, `export-official-json`,
> `review auto-verify-matched`, or a legacy `seed-registry` that deletes. See
> the [official publication runbook](official-publication-and-evidence-preservation.md)
> "Do not run" list.

---

## 5. Stop / abort / withdrawal / rollback gates (NOT EXECUTED until authorized)

Collectively these define the **stop-and-abort** plan. Until the preconditions
in each clear, the step is **BLOCKED**; when attempted by an authorized
operator it must produce the receipt in the template.

### 5a. Stop / abort trigger

Stop the rehearsal/sequence immediately and preserve evidence (do not delete,
reset, or overwrite) if any of the following is observed — and record UTC time
+ owner + exact identifiers:

1. A hash/integrity check fails (repo, artifact, snapshot, or `git archive HEAD`).
2. Claim or snapshot counts fall, or an immutable claim/snapshot is rewritten.
3. A supposed dry run or read-only command mutates state.
4. Source identity/revision/provenance link changes unexpectedly.
5. A deployed/probe route returns state inconsistent with the commit being
   rehearsed (wrong artifact, wrong headers, soft-200 unknown paths).
6. Any credential, token, raw source bytes, or protected value is exposed.

Evidence-preserving recovery: restore the last verified pre-migration/pre-motion
backup; **never use a downgrade, destructive reseed, or byte-overwrite at an
existing artifact address to repair immutable evidence.**

### 5b. Smoke gate

A smoke check confirms the candidate is safe to proceed *before* any
withdrawal/rollback path is needed. It is **BLOCKED** for any live/provided
route today, and is only `smoked` against the read-only local build in §4. The
smoke list, on real capacity:

1. The public root serves the **expected commit's** built HTML (not a stale or
   wrong artifact).
2. Unknown paths return 404 through the top-level `404.html` (SPA fallback
   disabled).
3. `robots.txt` is plain text; canonical = `https://benchmark.0x3.dev/`.
4. `_headers` directives present (nosniff, strict-referrer, frame-deny,
   report-only CSP) — no HSTS/enforcing CSP without proof.
5. No `Official` value is visible under a Demo/unavailable label.
6. Console/network errors absent; keyboard + focus path works on the table.

Each smoke item is `BLOCKED`/`NOT EXECUTED` until a provider + browser receipt
exists (see §8 residual R1/R2).

### 5c. Withdrawal gate

A withdrawal must reproduce the intent of the [withdrawal runbook]
(release-artifact-and-withdrawal.md `#future-withdrawal-protocol`) steps:
1. Append a revocation/withdrawal decision naming the **exact artifact** and
   reason (id, digest, policy, timestamp, signer).
2. Stop promotion; invalidate/replace the public static release per the
   approved cache SLA; publish an explicit `unavailable`/`withdrawn` state —
   never fall back to a Demo value under an Official label.
3. Preserve old artifact + decision history privately for audit; do not serve
   it as current.
4. Record detection time, action time, expiry, cache evidence, affected
   frontend build, owner, correction path, and follow-up source/review decision.

**Any withdrawal step that hits a provider/account/browser is `BLOCKED` today.**
The rehearsal records the planned sequence and a blank receipt; it does not
move a provider.

### 5d. Rollback gate

Planned rollback is a deployment-history/published-state action. Structure to
record on real capacity:
1. Identify the **previous deployment identity** (commit, artifact digest,
   `deploy.commit`, built bytes) that the provider serves.
2. Verify the candidate — if it degrades, initiate rollback to that exact prior
   (per the storage/recovery runbooks and the provider's own rollback semantics —
   see `provider-neutral-postgresql-and-object-storage-rehearsal.md`).
3. After rollback, run the **post-rollback verification** in §6 and capture a
   deployment-to-commit to prove the live host actually resolved the prior
   deployment.

**Cloudflare is `BLOCKED`** for Rollback: no correct account/project, no
Wrangler, no deployment history, no HSTS, and no native-browser. Do **not**
invent a `rollback` result.

---

## 6. Post-rollback verification (runs only after an actual rollback)

On a real rollback these confirm the target host actually resolved:

| Check | What proves the rollback took effect | Blocked |
| --- | --- | --- |
| Root `/` returns the previous deployment's HTML | a live `curl`/server/browser response | BLOCKED |
| Unknown path returns 404 (top `404.html`, sends SPA fallback) | route matrix | BLOCKED |
| `robots.txt` is plain text; canonical = `https://benchmark.0x3.dev/` | headers/robots | BLOCKED |
| `_headers` directives (`nosniff`, strict-referrer, frame-deny, report-only CSP) present | headers receipt | BLOCKED |
| `.pages.dev` host behaves as documented (redirect/noindex per policy) | live routing | BLOCKED |
| no `Official` value is visible under a Demo/unavailable label | browser/DOM + truth check | BLOCKED |
| bundle/monitoring/alert timeline consistent with deployment time | logs/telemetry | BLOCKED |

These are a **smoke/stop list**, not a promise the checks have run. Each is
`BLOCKED` until provider/browser authority exists.

---

## 7. Evidence retention

Record every receipt artifact, where it lives (private, not public), and the
retention period vs. the two-year placeholder:

| Receipt | Where stored | Retention placeholder |
| --- | --- | --- |
| Commit hash + `git status --short` | private release evidence | 2 years |
| Artifact id/digest + policy | private builder evidence | 2 years |
| Deployment-to-commit identity + live route | private provider evidence | 2 years |
| REL-05 approval decision + signer | immutable ledger decision | 2 years |
| Withdrawal/revocation decision + reason | immutable/audit | 2 years |
| Rollback decision + post-rollback proof | private ops evidence | 2 years |
| Incident / disclosure timeline | security/disclosure evidence | policy + 2 years |

**Retention is a placeholder, `UNASSIGNED`.** Do not claim a legal-hold or a
retention SLA is enforced before the retention/legal owner and policy exist.

---

## 8. Residual (not-yet-executable) checks

These are the steps the template calls for that **have no executable currently**.
Each is about residual evidence to close before a real rehearsal can claim CI/
deployment/live reads. Implement them as separate, named reservations rather
than inventing a script now:

- **Residual R1:** a deploy-to-SHA + live-route matrix check (does not exist;
  requires a provider token + a live target). BLOCKED.
- **Residual R2:** a native-browser/AT check that a rollback resolved the
  unavailable/Demo state and returns focus/state correctly (requires
  `iab`-capable browser). BLOCKED.
- **Residual R3:** a CI-only run of the ledger suite + clean-archive build on a
  GitHub `Verify` run for the exact candidate commit (requires push authority
  + billing). BLOCKED.
- **Residual R4:** an actual `benchmark-ledger export-official-json` artifact
  and its canonical-digest comparison in a clean checkout (requires the
  governed publication/export gate. Currently `NONE` available). BLOCKED.

Until (R1–R4) are closed, the rehearsal stays local read-only and the only
"validated" state achieved is **validated locally**.