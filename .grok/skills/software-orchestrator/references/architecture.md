# Software Orchestrator — Architecture

Research date: 2026-07-11.

## Planes

| Plane | Components | Authority |
|-------|------------|-----------|
| **Control** | Intake, planner, scheduler, router, review adjudicator, retry/takeover, policy | Grok orchestrator |
| **Execution** | Agent adapters, worktree manager, tool broker, workers | Workers execute; orchestrator dispatches |
| **Knowledge** | Capability store, outcome log, static model metadata | SQLite/JSONL durable |
| **Policy/security** | Permissions, approval gates, secret redaction | Policy layer + human when required |
| **User** | Brief, approvals, final report | User + orchestrator |

## Components

1. **Project Intake & Requirement Normalizer** — brief → structured requirements matrix  
2. **Repository & Environment Inspector** — tree, scripts, CI, git dirtiness  
3. **Requirements Traceability Manager** — req ↔ task ↔ verification  
4. **Planner & Task-Graph Builder** — DAG of bounded tasks  
5. **Task Readiness Scheduler** — READY when deps INTEGRATED/VERIFIED  
6. **Model & Agent Registry** — installed CLIs + provider catalogs  
7. **Capability Profile Store** — versioned posteriors  
8. **Routing & Delegation Engine** — expected utility + margin vs self  
9. **Context-Packaging Engine** — immutable context manifests  
10. **Agent Adapter Layer** — Cline, agy, kilo, Hermes delegate, Codex, Claude  
11. **Workspace & Worktree Manager** — `git worktree add` isolation  
12. **Tool & Permission Broker** — least privilege allowlists  
13. **Result Ingestion Layer** — schema-validate worker returns  
14. **Deterministic Validation Engine** — build/test/lint/type/security  
15. **Grok Review & Adjudication** — severity-first human-quality review  
16. **Retry & Takeover Controller** — bounded retries then self  
17. **Integration & Merge Manager** — orchestrator-only integrate  
18. **Release Verification Manager** — project-wide gates  
19. **Event & Telemetry Store** — append-only events  
20. **Learning & Profile Update** — Beta-Binomial + EWMA + attribution  
21. **Policy & Human-Approval Layer** — destructive/prod gates  
22. **Reusable Skill Interface** — this skill package  

## Isolation model (borrowed from Orca / Codex / Claude worktrees)

- One task → one worktree/branch  
- Non-overlapping write scopes for parallel tasks  
- Integration only after APPROVE/SELF_FIX  
- Workers never write main integration branch  

## Technology recommendations

| Concern | Default | Alternative |
|---------|---------|-------------|
| Capability DB | SQLite WAL | Postgres |
| Events | SQLite + JSONL export | OpenTelemetry + file |
| Workers (this host) | Cline, kilo, agy, Hermes delegate_task | Codex/Claude when installed |
| Validation | project package scripts | CI re-run |
| Skill host | Grok Build `.grok/skills/` + Hermes-compatible SKILL.md | Claude/Codex skill drop-in |

## Failure boundaries

- Adapter crash → task FAILED/retry infrastructure attribution  
- Invalid JSON result → reject, one reformat retry, then takeover  
- Flaky test → quarantine note; do not infinite retry  
- Merge conflict → orchestrator resolves; never worker force-push  
