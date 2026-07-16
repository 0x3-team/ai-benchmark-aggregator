# Continuous discovery, recheck, and notification threat model

Status: **DRAFT / UNAPPROVED**  
Date: 2026-07-15  
Decision authority: none  
Security/privacy review: not performed  
Production use: prohibited until the named approval and proof gates are complete

This document is design evidence for the planned continuous discovery and recheck system. It does not certify a source, authorize network access, approve a database role, enable external notifications, authorize publication, or make any artifact frontend-loadable. No official claim, source revision, privacy posture, incident response SLA, notification recipient, or recovery result has been reviewed or approved by this draft.

## Scope and invariants

In scope are scheduler wake-ups, discovery targets, source checks, immutable snapshots, extraction/validation, review work items, operational incidents, transactional notification intents, notification delivery receipts, dead letters, recovery/canary checks, storage/backup, release artifacts, and the static frontend boundary. Provider selection and production configuration are deliberately unresolved.

The non-negotiable containment invariants are:

- A scheduler, queue, browser, parser, incident, work item, notification, or timeout cannot certify a source or authorize capture/publication.
- Official content is snapshotted before extraction. Evidence and result claims are append-only; containment references never rewrite evidence.
- All remote inputs are hostile. Redirect targets and every connection peer are independently checked.
- Work and incident transitions are append-only, compare an exact prior event, and fail on branching or replay.
- Notification payloads contain only allowlisted stable IDs/codes and counts. They never contain raw model names, scores, source text, URLs, query strings, paths, provider bodies, secrets, HTML, or Markdown.
- External notification routes remain `externally_blocked` until separate privacy, recipient, retention, authentication, route, and owner decisions exist. Local fixtures do not send.
- An acknowledgement is not a resolution. A delivery receipt is neither. Resolution requires target-perspective evidence.
- One terminal outcome is accounted for every scheduled unit. Missing receipts are incidents, not silent success.
- The desired recovery promise remains “at most one completed data set lost”; it is only a target until restore proof demonstrates it.

## Assets and security objectives

| Asset | Objective |
|---|---|
| Immutable source snapshots and evidence locators | Preserve exact bytes, digest, origin/revision binding, availability, and append-only history. |
| Source/revision policy decisions | Prevent uncertified or expired revisions from crossing capture/publication gates. |
| Claims, review decisions, and publication decisions | Preserve raw fields and append-only decision lineage; prevent timeout or role bypass. |
| Schedule cycles, jobs, leases, and receipts | Ensure deterministic identity, at-most-one accepted commit per fenced lease, and exact denominator accounting. |
| Incidents and work items | Preserve stable fingerprint, owner, state sequence, evidence separation, occurrence count, and explicit due-policy uncertainty. |
| Notification intents and receipts | Preserve transactional binding, payload minimization, route authority, dedupe, retries, dead letter, recovery, and non-authoritative effects. |
| Database, object store, queues, secrets, backups | Enforce least privilege, isolation, retention, integrity, recoverability, and cost bounds. |
| Official release artifact and frontend selection | Prevent substitution, revoked selection, cache persistence, and Demo/Official provenance confusion. |
| Audit/telemetry data | Detect failure without leaking remote content, identifiers outside policy, credentials, or notification payload extensions. |

## Actors and assumptions

- Remote origin operator: may change content, redirects, DNS, certificates, rate limits, or structure without notice.
- Malicious remote content author: controls markup/data and may attempt SSRF, injection, parser exhaustion, or alert manipulation.
- Anonymous internet client: may probe public Pages/Worker endpoints and amplify cost.
- Compromised dependency, browser, adapter, CI job, Worker, queue consumer, or maintainer credential.
- Authorized operator making an error, using stale context, or acting outside the intended role.
- Scheduler/queue/storage/database/notification provider failure, including correlated regional or account failure.
- Independent watchdog: must use a distinct failure domain and credentials; independence is a target until proved.

Assumptions requiring later proof: Cloudflare product behavior and quotas, D1/R2/Queue backup/restore characteristics, browser isolation, outbound network controls, database append-only enforcement, secrets redaction, retention, recipient authority, business calendars, and incident/recovery SLAs.

## Data flow and trust boundaries

1. A non-authoritative clock wake-up derives a deterministic UTC slot.
2. The scheduler reads immutable discovery/source revisions and creates idempotent jobs.
3. A worker obtains a fenced lease and validates source/revision policy before any fetch.
4. The safe-fetch boundary resolves DNS, verifies the connected peer/TLS/redirect at every hop, applies size/time/type budgets, and writes immutable raw bytes.
5. A sandboxed parser reads only the immutable snapshot. Extraction and evidence re-resolution either pass exactly or quarantine.
6. Append-only claims and decisions remain in the ledger; review work items expose uncertainty but grant no authority.
7. Incident transitions and a redacted notification intent are committed transactionally. A separate adapter may create a receipt only within approved route authority.
8. Reconciliation/watchdog paths compare expected jobs/intents with receipts and create incidents for gaps.
9. A release builder reads only fully eligible ledger facts and produces a content-addressed artifact; an independent authorization pins its exact digest.
10. Pages serves the static frontend and approved artifact. The frontend cannot fall back silently or treat operational contracts as score data.
11. Backups/recovery copies are isolated, verified, and restored into a clean environment during tests.

Remote origin → fetch, fetch → snapshot store, snapshot → parser, worker → database, scheduler → queue, incident outbox → notification adapter, primary control plane → watchdog, release builder → artifact store, and artifact store → Pages are separate trust boundaries.

## High-risk register

`Owner` values are placeholders, not assignments. `Target proof` is mandatory evidence for a later review; none is satisfied by this draft.

| ID / threat | Required mitigation | Detection | Kill condition / containment | Owner placeholder | Residual risk | Target proof before production |
|---|---|---|---|---|---|---|
| T01 SSRF through target, redirect, or metadata address | Immutable allowlisted scheme/host/port policy; block loopback, link-local, private, multicast, reserved, credentials, non-HTTP(S), and user-controlled proxy settings; cap redirect hops. | Structured reason codes for each rejected hop; egress-deny telemetry without raw URL/query. | Pause the source and all targets sharing its origin; disable egress worker if any forbidden peer connects. | Security owner | DNS/CDN edge cases and platform proxy behavior. | Adversarial tests plus packet/peer evidence in the chosen runtime. |
| T02 DNS rebinding / peer mismatch / TLS confusion | Resolve and validate every hop immediately before connection; verify actual connected peer; re-check after redirects; require hostname/SNI/certificate validation; forbid downgrade. | Record hostname class, peer class, TLS result, redirect count, and policy revision as safe codes. | Quarantine snapshot and source revision on any resolution/peer/certificate mismatch. | Security owner | Runtime may hide the real peer; CDN address rotation. | Runtime-specific peer-verification test including rebinding and mixed-address answers. |
| T03 HTML/CSV/JSON/Markdown/LLM prompt injection | Treat source strings as data only; never interpolate into commands/prompts/alerts; strict schemas and typed locators; escape only at final UI boundary. | Rejected-field counters and fixture corpus; no raw remote string in logs. | Quarantine parser/source adapter on any untyped field reaching an operational or notification contract. | Ingestion owner | Novel parser gadget or unsafe maintainer tooling. | Injection corpus demonstrating no command, prompt, alert, or UI execution. |
| T04 Parser bombs, decompression bombs, oversized or deeply nested input | Byte, ratio, row, cell, depth, token, CPU, memory, and wall-clock limits; streaming where possible; sandbox parser with no network/secrets. | Resource-limit reason codes and worker resource telemetry. | Terminate parser, retain only policy-safe failure metadata, pause target after threshold. | Platform owner | Platform-specific resource accounting gaps. | Fuzz/property tests and measured hard-limit termination. |
| T05 Queue replay, duplicate delivery, or reordering | Deterministic idempotency keys; append-only expected-prior events; exact attempt/occurrence counters; atomic terminal receipts. | Duplicate/replay counters and reconciliation of expected versus terminal denominator. | Fence duplicate consumer; do not accept a second commit; open SCHEDULER incident. | Operations owner | Provider redelivery during partial outages. | Replay/ordering fault injection with exactly one accepted result. |
| T06 Lease theft, stale worker, or fencing bypass | Monotonic fencing token checked in the same transaction as every commit; bounded lease; no token reuse; least-privilege worker identity. | Stale-token rejection metrics and lease-owner audit facts. | Reject commit, revoke worker credential, pause affected lane if current-token integrity is uncertain. | Database owner | Database isolation/configuration defects. | Concurrent stale-worker test proving the old token cannot commit any stage. |
| T07 Object overwrite/delete or hash substitution | Content-addressed immutable keys, conditional create, post-write digest/length verification, separate delete role, retention/object-lock decision. | Inventory reconciliation, digest sampling, delete audit trail. | Stop capture/publication; quarantine affected objects; restore only from verified copy. | Storage owner | Provider/admin compromise and unapproved retention semantics. | Overwrite/delete denial tests and independent inventory digest report. |
| T08 Orphan snapshot/claim/database row | Transactional reference protocol or explicit pending/finalized state; immutable correlation IDs; periodic bidirectional reconciliation. | Orphan/missing-object census with exact denominator and age. | Pause affected source/lane when orphan threshold or any claim-without-snapshot appears. | Ledger owner | Cross-service atomicity is unavailable. | Crash-at-every-boundary tests and zero unexplained orphan reconciliation. |
| T09 Database role escalation / append-only bypass | Separate migration, writer, reader, release, and backup roles; deny update/delete on append-only facts; constraints/triggers; audited break-glass. | Role/privilege drift scan and append-only mutation canary. | Revoke role and stop all writes/publication on privilege drift or successful mutation canary. | Database owner | Account-level compromise or provider superuser behavior. | DDL/GRANT review and role-by-role negative permission tests. |
| T10 Secret exposure in source, environment, logs, errors, artifacts, or Pages | Managed secrets; no secrets in frontend/build artifacts; structured allowlisted logs; redact query/body/provider text; rotation procedure. | Secret scanning in repo/build/log samples and canary credentials. | Rotate exposed secret, disable affected adapter, purge only under approved retention procedure, open SEV0. | Security owner | Unknown copies and provider diagnostic retention. | Redacted incident drill and scans with zero secret-bearing artifacts. |
| T11 Browser/scraper breakout or shared-context leakage | Prefer API/structured files; isolated browser context per origin; no ledger/notification secrets; deny downloads and arbitrary navigation; sandbox filesystem/network. | Browser navigation/download policy violations and process-isolation health. | Kill browser pool, pause browser-required sources, fall back to quarantine—not synthetic data. | Ingestion owner | Browser zero-day and platform isolation limits. | Browser escape/navigation/download adversarial suite in selected runtime. |
| T12 Pages/static-host boundary leakage or cache confusion | Static build only; no server secrets; strict CSP after report-only proof, security headers, immutable artifact paths, explicit unavailable state, cache purge/withdrawal runbook. | Header/CSP scans, secret scan, artifact authorization mismatch telemetry. | Disable Official selection and serve unavailable artifact; withdraw compromised build. | Frontend owner | CDN propagation and stale client caches. | Header report, withdrawal/cache tabletop, and clean build artifact inventory. |
| T13 Release artifact substitution, rollback, or revoked selection | Content digest and artifact ID pinned by append-only authorization; builder input manifest; signature/key decision; monotonic release selection; explicit revocation/withdrawal. | Client/server digest check, selection audit, revoked-artifact probes. | Switch to unavailable; revoke exact digest; purge caches; never silently use Demo as Official. | Release owner | Signing/key custody and CDN consistency unresolved. | End-to-end substitution and revoked-cache tests. |
| T14 Notification/alert injection and data exfiltration | Fixed template and route versions; exact allowlist of stable IDs/codes/counts; digest payload; forbid raw model, score, source text, URL/query/path, HTML/Markdown, headers, or provider body. | Contract rejection counters and adversarial redaction tests. | Block route and dead-letter the intent; do not retry policy violations. | Privacy owner | Recipient platform may enrich/linkify safe identifiers. | Privacy review and rendered-message snapshots for every approved adapter. |
| T15 Notification replay, spoofed receipt, or acknowledgement spoofing | Transactional intent bound to exact incident event; stable dedupe; authenticated adapter; receipt binds intent self-digest, payload, route, adapter/version, and attempt; receipt effects are always false. | Duplicate receipt, binding mismatch, missing-intent, and signature/auth failures. | Reject receipt; keep incident state unchanged; open NOTIFY incident without recursive external notification. | Operations owner | Compromised approved adapter credential. | Replay/spoof tests and adapter authentication evidence. |
| T16 Retry storm, dead-letter loss, or recursive notification incident | Three-attempt budget, backoff/retryAt fence, no fourth retry, dead letter with recovery path, NOTIFY-family recursion suppression, route-level circuit breaker. | Attempt/intent/receipt denominators, dead-letter age, recursive-suppression count. | Disable route at threshold; preserve intent/dead letter; use independent escalation path only if approved. | Operations owner | Correlated provider outage and delayed human response. | Retry/dead-letter/recovery fault injection and bounded cost evidence. |
| T17 Alert/control common-mode failure | Transactional outbox plus independent watchdog in different failure domain, credential, schedule, and data path; watchdog checks expected receipts, not primary “healthy” flag. | Canary intent and missing-receipt incident; compare primary and watchdog clocks. | Halt automated publication and page an independently approved route when both paths disagree/fail. | Reliability owner | True independence may be impossible within one account/provider. | Documented failure-domain map and outage exercise proving independent detection. |
| T18 Backup corruption, deletion, or ransomware/common credentials | Encrypted versioned backups; separate account/role and retention; immutable recovery copies; checksums; restore into clean isolated environment; recovery catalog. | Backup age, digest, completeness, and restore-test receipts. | Stop publication if backup/restore SLO fails; rotate credentials; preserve last verified copy. | Recovery owner | Provider/account-wide compromise and retention policy gaps. | Repeated restore drill demonstrating at-most-one-completed-set RPO and approved RTO. |
| T19 Cost abuse through public endpoints, discovery cardinality, retries, browsers, or notifications | No anonymous mutation/dispatch; quotas per lane/origin/route; concurrency/byte/time caps; dedupe; budget alarms; fail closed before paid overflow. | Cost by stable target/route code, queue depth, browser minutes, egress, notification attempts. | Disable discovery/browser/external route at budget threshold; keep recheck/withdrawal safety path if approved. | FinOps owner | Free-tier/provider pricing changes and distributed amplification. | Load/abuse test and approved hard budget/kill-switch demonstration. |
| T20 Operator error, stale context, or unsafe bulk action | Typed references; preview/dry-run; two-person decision where required; exact expected-prior event; narrow roles; bounded batch; append-only correction; no timeout approval. | Decision audit, rejected stale transition count, unusual bulk-action alert. | Stop batch on first mismatch; revoke session; use append-only corrective decision, never rewrite history. | Governance owner | Authorized malicious insider and fatigue. | Tabletop for wrong source, wrong recipient, wrong revocation, and recovery. |
| T21 Dependency/CI supply-chain compromise | Lockfiles and integrity verification; minimal dependencies; provenance/SBOM decision; isolated untrusted PR builds; pinned actions; review generated artifacts. | Dependency/security scans and unexpected build-output diff. | Block build/release, rotate CI credentials, rebuild from reviewed source. | Engineering owner | Registry/action compromise and transitive build scripts. | Reproducible clean build plus dependency and CI permission review. |
| T22 Telemetry privacy leakage or observability outage | Stable-code telemetry only; approved retention/access; no remote text, scores, model raw names, URLs/query, paths, payload extensions, or secrets; metrics path separated from control path. | Schema checks, privacy sampling, missing-telemetry canary. | Disable offending telemetry sink without disabling safety containment; open privacy/security incident. | Privacy owner | Provider metadata and cardinality can still identify sources. | Field inventory and privacy approval with sampled redacted events. |

## Abuse and failure cases that must remain fail-closed

- Redirect or DNS answer changes between policy check and connection.
- Source response is a login/error/fallback/mock/derived page but returns HTTP 200.
- Parser returns a plausible score after partial extraction or schema drift.
- Queue delivers a job or incident event twice, out of order, or after lease expiry.
- Two operators claim/resolve the same work item from one prior event.
- A resolved incident recurs before closure or after closure; both append `REOPENED` and increment occurrence count while preserving fingerprint.
- A notification receipt exists without the exact intent digest, or a retry starts before its prior `retryAt`.
- The third transient notification failure proposes a fourth retry.
- The primary scheduler and primary alert sender fail together.
- An artifact is validly hashed but not the artifact authorized for Official selection.
- Backup exists but cannot restore, or recovery shares compromised credentials with production.
- A timeout, missing owner, or “no objection” is treated as approval.

Each case must create a typed failure/quarantine/incident outcome; none may synthesize data, overwrite evidence, approve publication, or silently fall back.

## Required controls and later evidence gates

Before shadow network execution: approve source/egress policy; prove DNS/peer/TLS/redirect enforcement; parser isolation and limits; secret isolation; immutable snapshot write semantics; and a kill switch.

Before shadow notifications: approve the minimized field inventory and retention; keep every external route blocked; prove transactional incident-event/outbox creation, dedupe, replay rejection, retry fences, dead letter, recursion suppression, canary, and exact binding. Local JSON receipts are the only currently admissible examples.

Before production capture: approve database/storage roles, append-only enforcement, fencing, backups, RPO/RTO, business calendars/SLA targets, privacy telemetry, operator roles, and source certification. Complete crash/replay/orphan/restore exercises.

Before any external notification: approve exact recipients, route, template, authentication, retention, data minimization, owner, and budget. Demonstrate adapter authentication, redacted rendered output, rate limits, revocation, dead-letter recovery, and an independent watchdog.

Before Official launch: satisfy the separate governed release authorization that pins the artifact ID, publication decision, policy, and digest; demonstrate withdrawal/cache behavior; complete threat-model approval and residual-risk acceptance. This draft is not that authorization.

## Open decisions and explicit blockers

- Security/privacy, operations, data governance, database, storage, reliability, release, and recovery owners are unassigned placeholders.
- Cloudflare database/object/queue/browser/notification products and limits are not selected or approved.
- Source egress allowlists, terms decisions, browser-needed sources, and source cadence are unresolved.
- Business calendars, severity exceptions, acknowledgement/mitigation targets, RTO, and retention are provisional.
- External notification recipients, adapters, credentials, templates, authentication, retention, and data-processing terms are blocked.
- Independent watchdog and backup failure-domain independence are unproved.
- The at-most-one-completed-set recovery promise has no restore evidence yet.
- No security test result, residual risk, claim, or launch decision has been reviewed by an authorized owner.

## Approval record

No approvals. A future revision must append named decisions and links to the target proofs; it must not change this draft into “approved” by editing away the unresolved history.
