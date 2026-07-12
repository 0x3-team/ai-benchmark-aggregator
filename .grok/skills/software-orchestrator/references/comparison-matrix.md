# Survey comparison matrix (Mode A research)

**Research date:** 2026-07-11  
**Method:** Official docs/repos first; engineering blogs secondary; community only for failure modes.  
**Orca disambiguation:** **Orca ADE (Stably / onorca.dev / stablyai/orca)** — agent IDE with worktrees. Unrelated to other “ORCA” papers/products unless cited.

| System | Ver/date | Category | Topology | Decomposition | Concurrency | Isolation | Routing | Context | Memory | Validation | Retry | Integration | Observability | Human | Security | Strengths | Weaknesses | Borrow | Avoid | Primary sources |
|--------|----------|----------|----------|---------------|-------------|-----------|---------|---------|--------|------------|-------|--------------|---------------|-------|----------|-----------|------------|--------|-------|-----------------|
| Orca ADE | docs 2026-07 | ADE | Human supervisor + multi CLI agents | User-defined tasks | Parallel agents | **Git worktree per task** + browser tab | BYO agent CLIs | Per-worktree terminal | None native learning | Diff review by human | Human re-run | Human merge | Local UI | Diff-first | Local-first, SSH remote | Excellent isolation UX | Not an autonomous planner/router | Worktree-per-task, diff-first integrate | Treating ADE as auto-router | onorca.dev/docs, github.com/stablyai/orca |
| Claude Code | docs 2026 | Coding agent | Supervisor + **subagents** | Skills + plan/explore | Subagents; worktree isolation option | Subagent context; optional worktree | Model tiers / subagent model field | CLAUDE.md + on-demand skills | Session + files | Hooks, tests user-run | Re-prompt | Main session | Session | Approvals/hooks | Permissions, tool deny | Context isolation, skills, hooks | Weak durable multi-project learning | Subagents, skills, hooks, least privilege | Unbounded nested agents | code.claude.com/docs/en/sub-agents |
| Grok Build | docs 2026-05+ | Coding agent | Primary + subagents | Skills/plugins | Parallel subagents | Compatible with worktrees/skills | User/model choice | AGENTS.md + SKILL.md | Skills durable | User/tests | Re-run | Main | Session | User | Skill/plugin boundaries | Skill portability w/ Claude format | Learning store not built-in | `.grok/skills`, slash skills, Claude compat | Invented frontmatter | docs.x.ai skills-plugins; x.ai/news/grok-skills |
| OpenAI Codex | app/CLI 2026 | Coding agent | Multi-agent app | User/tasks | Parallel sessions | **Worktrees** | Model in product | AGENTS.md | Session | Diff review | Re-run | User merge | App dashboard | Strong | Sandbox containers (web) | Parallel isolation mainstream | Not full utility router | Worktree parallel + review UI | Assuming cloud sandbox = local policy | OpenAI Codex app materials; Firecrawl/Codex multi-agent writeups |
| LangGraph | current | Framework | **Supervisor** / graph | Graph nodes | Graph parallelism | App-defined | Code-defined routing | State channels | Checkpointers | Custom | Graph retry | Custom | LangSmith etc. | Interrupts | App-level | Durable graphs, HITL | You build isolation/merge | Supervisor pattern, durable state | Naive supervisor over-delegation | LangGraph multi-agent docs |
| AutoGen / AG2 | current | Framework | Group chat / SoM | Conversation | Multi | Weak by default | Chat manager | Messages | Optional | Custom | Chat loop | Custom | Logs | Human proxy | App-level | Flexible multi-agent | Easy context thrash | Bounded roles | Unstructured group chat as control plane | AutoGen docs |
| CrewAI | current | Framework | Hierarchical crew | Role tasks | Process modes | Weak | Manager agent | Shared context | Limited | Custom | Process | Custom | Logs | Human | App-level | Fast crew setup | Less rigorous isolation | Role specialization | Shared mutable context | CrewAI docs |
| OpenAI Agents SDK | current | Framework | Handoffs | Agent tools | Async | App | Handoff graph | Sessions | Sessions | Guardrails | Retry tools | App | Traces | HITL | Guardrails | Clean handoffs | Not SE worktrees | Handoff + guardrails | Ignoring handoff loops | OpenAI Agents docs |
| Temporal/Prefect/Dagster | current | Workflow | Workflow/DAG | Explicit DAG | Workers | Activity isolation | Schedulers | Payloads | Durable history | Activity heartbeats | **Idempotent retry** | N/A | First-class | Signals | Worker perms | Durability patterns | Not LLM agents | Idempotency, checkpoints, timeouts | Treating workflows as planners | Temporal docs |
| SWE-agent / OpenHands / Aider / Devin | varies | SE agents | Single/multi loop | Issue→patch | Limited parallel | Sandbox/container varies | Single primary | Repo tools | Trajectory logs | Tests in harness | Retry trajectories | PR | Logs | Human PR | Sandbox | Strong SE loops | Heterogeneous routing weak | Test-in-the-loop | Blind benchmark worship | Project docs |

## Patterns decision table

| Pattern | Source | Works | Limit | Decision | In our design |
|---------|--------|-------|-------|----------|---------------|
| Worktree per task | Orca, Codex, Claude | Real isolation | Disk/git overhead | **Borrow** | Workspace Manager |
| Supervisor topology | LangGraph, Claude | Clear authority | Over-delegation | **Adapt** | Grok always supervisor; utility margin |
| Skills as procedures | Claude, Grok | Portable know-how | Matcher drift | **Borrow** | This skill + prompts |
| Hooks for safety | Claude, Grok | Deterministic gates | Hook bugs | **Borrow** | Pre-tool policy hooks |
| Durable workflow state | Temporal | Crash recovery | Heavy infra | **Adapt** | SQLite events + checkpoints |
| Group chat swarm | AutoGen | Creative | Context pollution | **Reject** as control plane | Only optional debate pattern later |
| Benchmark rank as router | Marketing | Cold start | Harness incomparability | **Reject** as truth | Low-confidence priors only |
| Worker self-merge | Some agents | Speed | Silent breakage | **Reject** | Orchestrator-only integrate |
| Unbounded retry | Common | Persistence | Cost loops | **Reject** | max 1 targeted retry default |
