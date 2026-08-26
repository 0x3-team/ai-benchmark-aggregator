---
name: quality-orchestration
description: Use when selecting or supervising an agent, model, harness, or validation route for this repository.
---

# Quality orchestration

Keep the repository owner accountable for integration and acceptance. Select a route by task fit, evidence, risk, and ownership; billing route and speed break quality ties. On capy.ai, delegation happens through task agents with an explicit `model` choice, so every route is a recorded decision, not a default.

## Route economics

- Three budgets exist, and they are not interchangeable:
  - **Codex subscription** (`codex/*`): the volume engine. A large seat carries conductor work, implementation, and bulk reads at no marginal credit.
  - **SuperGrok subscription** (`supergrok/*`): a small seat. Its quota is scarce, so it buys vendor independence, not volume: cross-vendor review and fast second opinions only, never authorship.
  - **Capy API credit**: the only way to buy Anthropic quality and third-vendor diversity. Expiring credit is use-it-or-lose-it — spend it deliberately on oracle consults, alternate reviewers, and cheap diversity checks, not on work a seat does for $0.
- When the same model has both a subscription and an API route (`codex/gpt-5.6-sol` vs `openai/gpt-5.6-sol`, `supergrok/grok-4.6` vs `xai/grok-4.6`), the subscription route is the only correct choice.
- Re-check the live model catalog before dispatch: its ids, billing kinds, and cost words are the operative ranking. The price appendix below is a dated market anchor, not a bill.

## Topology: conductor, oracle, workers

- The **conductor** is the token-hungriest, most stateful role — it rereads context on every wake. It therefore runs on the strongest seat-billed model (`codex/gpt-5.6-sol`, reasoning `xhigh`), never on a frontier API model. It owns routing, integration, decisive checks, and acceptance.
- The **oracle** (`anthropic/claude-fable-5`, reasoning `max`) is consulted, never conducting: stateless one-shot dispatches with a distilled dossier in (question, constraints, candidate diffs or designs, disagreement record) and a verdict with rationale out. Triggers: architecture forks, release-scale gates, and recorded deadlocks between conductor and reviewer. Keep dossier prefixes stable so cache pricing applies.
- **Workers** hang at most two levels below the conductor (conductor → leads → workers). Deeper trees dilute acceptance: every diff still terminates in the conductor's own gate run.

## Capy dispatch mechanics

- Lanes bind to capy task agents: create tasks with an explicit `model` (route id plus pinned reasoning) from the lane table. Omitting `model` inherits the thread's model, which is acceptable only for conductor-lane work.
- Choose task machines by writes: shared machine for read-only lanes (bulk reads, reviews, second opinions), fresh machine for every writing lead or worker; one committer at a time on any shared tree.
- Overlapping or dependent work stacks instead of parallelizing: spec first, one task per layer, later tasks start on the earlier PR's branch.
- Ship through the platform's PR tooling so CI results, reviews, and merges flow back to the conductor automatically; event callbacks replace polling.
- Review findings are evidence, not instructions: the conductor re-verifies each finding against the actual diff before acting, and records the disposition.
- Reviews dispatch as read-only tasks over a bounded dossier (diff, contracts, decision record); verdicts come back as receipts in the thread.

## Lane table

Dispatch by lane, one primary per lane with a pinned reasoning effort. Consistency comes from never shopping models per task; changing a lane is a routing decision recorded by editing this table in a reviewed change.

| Lane | Primary | Escalation / notes |
| --- | --- | --- |
| Conductor: orchestration, integration, acceptance | `codex/gpt-5.6-sol`, reasoning `xhigh` | Seat-billed. Consults the oracle; the oracle never conducts. |
| Implementation leads: multi-file features (frontend and ledger) | `codex/gpt-5.6-sol`, reasoning `xhigh` (`max` for known-hard) | Fresh machine per writing lead. |
| Bounded workers: scoped, single-surface edits | `codex/gpt-5.6-terra`, reasoning `high` | `codex/gpt-5.6-luna` for simple bounded edits. |
| Mechanical edits: renames, rote refactors, scaffolds, lint fixes | `codex/gpt-5.3-codex-spark` | `supergrok/composer-2.5-fast` as alternative when Codex quota is under pressure. |
| Bulk reads: repo summaries, fixture drafts, log triage, doc drafts | `codex/gpt-5.6-luna` | `deepseek/deepseek-v4-flash-0731` overflow at pennies to protect seat quota. Owner reviews all output. |
| Independent review: all meaningful seat-authored diffs, including ledger claims, migrations, and evidence resolution | `supergrok/grok-4.6`, reasoning `xhigh` (its ceiling; the model has no `max`) | The small seat's whole job — review and tiebreaks only, never authorship. Mechanical diffs skip second-vendor review to protect quota. If xAI authored the diff, review with `deepseek/deepseek-v4-pro` `max` or `anthropic/claude-opus-5` `high` (credit). Release-scale gates escalate to the oracle. |
| Oracle consults: architecture forks, release gates, deadlocks | `anthropic/claude-fable-5`, reasoning `max` (credit) | One-shot distilled dossiers only; owner-approved per consult. |
| Cheap second-opinion reasoner: tiebreaks, sanity checks | `deepseek/deepseek-v4-pro`, reasoning `max` | Third-vendor diversity fallbacks: `zai/glm-5.2`, `qwen/qwen3.8-max`. |
| Vision QA: screenshots, rendered UI states | `google/gemini-3-flash-preview` | `zai/glm-5v-turbo` as alternative. |

Avoid without an owner-approved reason: `openai/gpt-5.5-pro` (one call can eat a double-digit share of a small credit pool) and `moonshotai/kimi-k3` (reasoning fixed at max, so all thinking bills as premium output). Dominated rows stay parked: every `openai/gpt-5.6-*` and `openai/gpt-5.4/5.5` API twin (seat route exists), `codex/gpt-5.5` and `codex/gpt-5.4`/`gpt-5.4-mini` (older than sol/terra/luna on the same seat), `anthropic/claude-opus-4-5`–`4-8` (opus-5 price, older), `claude-sonnet-4-6`, `claude-sonnet-5`, and `claude-haiku-4-5` (credit spent below opus-5 quality that a seat already covers), `moonshotai/kimi-k2.6`/`k2.7-code` (beaten by deepseek on price, seats on quality), `xai/grok-4.5`/`4.6` (subscription twin exists; `xai/grok-4.3` only when cheap 1M context is the point), `google/gemini-3.1-pro-preview` (Google-specific long-context multimodal only), `zai/glm-5-turbo` (`glm-5.2` is stronger at a nearby price).

## Consistency and acceptance

- Planning belongs to the planning route; implementation, integration, and acceptance stay with the implementation owner.
- Task agents receive only bounded, non-sensitive candidate work. They do not own shared contracts, deployment, migrations, secrets, or final acceptance.
- Independence rule: for integrity-critical work the reviewing model's vendor differs from the authoring model's vendor, and no model reviews its own diff.
- Owner reruns decisive checks regardless of model: `npm run typecheck && npm run build`; `cd ledger && pytest -q`. Inspect the actual diff before accepting output.
- Use exact fallback order — `codex/gpt-5.6-sol` → `supergrok/grok-4.6` → `anthropic/claude-sonnet-5` (credit) unless a lane names its own — and record every failed or blocked predecessor.
- Never send secrets, private archives, credentials, or unrelated worktree files.

## Budget rules

- Seat quota is a budget: size lanes to seat size, and never spend the small seat's quota on work the large seat can do.
- Estimate tokens before any credit dispatch; projected spend above roughly $10 needs owner sign-off, and actual spend goes in the receipt.
- Never run two premium models on the same question unless resolving a recorded disagreement.
- Prefer cache-friendly prompts (stable prefixes, reused context): cache-hit input is 10–50x cheaper on most routes.

Receipt fields: route, provider, model, billing kind, requested/effective effort, scope, files, evidence, estimated/actual cost, result (`ACCEPTED`, `REWORK`, `REJECTED`, or `BLOCKED`), and cleanup.

## Price appendix (vendor list, USD per 1M input/output tokens, checked 2026-08-26)

Seat-billed at $0 marginal credit: `codex/gpt-5.6-sol` / `terra` / `luna`, `codex/gpt-5.3-codex-spark`, `codex/gpt-5.4`/`5.4-mini`/`5.5`; `supergrok/grok-4.6`, `grok-4.5`, `composer-2.5-fast`. API list prices for the twins: sol $4/$20, terra $2/$12, luna $0.20/$1.20, grok-4.x $2/$6. Capy API billing may differ from vendor list; use this only for relative ordering. No public list price found for `zai/glm-5v-turbo`.

| Tier | Model | List price |
| --- | --- | --- |
| Bulk | deepseek-v4-flash-0731 | $0.14/$0.28 (peak/off-peak split announced from 2026-08-17, up to $0.44/$1.32) |
| Bulk | gemini-3-flash-preview | $0.50/$3.00 |
| Mid | deepseek-v4-pro | $0.435/$0.87 (same peak/off-peak note) |
| Mid | kimi-k2.7-code, kimi-k2.6 | $0.95/$4.00 |
| Mid | claude-haiku-4-5 | $1/$5 |
| Mid | glm-5-turbo | $1.20/$4.00 |
| Mid | grok-4.3 (API) | $1.25/$2.50 |
| Mid | glm-5.2 | $1.40/$4.40 |
| Mid | gpt-5.3-codex (API) | $1.75/$14 |
| Mid | claude-sonnet-5 | $2/$10 (intro price through 2026-08-31) |
| Mid | gemini-3.1-pro-preview | $2/$12 |
| Mid | qwen3.8-max | $2/$6 (no cache discount listed) |
| Premium | claude-sonnet-4-6 | $3/$15 |
| Premium | kimi-k3 | $3/$15 (reasoning fixed at max) |
| Premium | claude-opus-4-5…4-8, claude-opus-5 | $5/$25 |
| Frontier | claude-fable-5 | $10/$50 (cache-hit input $1) |
| Frontier | gpt-5.5-pro | $30/$180 |
