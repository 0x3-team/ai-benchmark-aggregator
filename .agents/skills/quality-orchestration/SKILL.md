---
name: quality-orchestration
description: Use when selecting or supervising an agent, model, harness, or validation route for this repository.
---

# Quality orchestration

Keep the repository owner accountable for integration and acceptance. Select a route by task fit, evidence, risk, and ownership; billing route and speed break quality ties. On capy.ai, delegation happens through task agents with an explicit `model` choice, so every route is a recorded decision, not a default.

## Route economics

- Two billing kinds exist: **subscription** routes (`supergrok/*` today) bill a connected seat at no marginal credit; **Capy API** routes burn prepaid credit. When the same model has both routes (`xai/grok-4.6` vs `supergrok/grok-4.6`), the subscription route is the only correct choice.
- Prepaid credit that expires is use-it-or-lose-it: route volume to subscription lanes, and spend credit deliberately where it buys quality the seat cannot — independent premium reviews, hard escalations, and dirt-cheap bulk work.
- Re-check the live model catalog before dispatch: its ids, billing kinds, and cost words are the operative ranking. The price appendix below is a dated market anchor, not a bill.
- If a new subscription route appears in the catalog (for example a connected Codex seat), it immediately takes over its API twin's lanes.

## Lane table

Dispatch by lane, one primary per lane with a pinned reasoning effort. Consistency comes from never shopping models per task; changing a lane is a routing decision recorded by editing this table in a reviewed change.

| Lane | Primary | Escalation / notes |
| --- | --- | --- |
| Default engineering: plan, implement, debug (frontend and ledger) | `supergrok/grok-4.6`, reasoning `high` (`xhigh` for planning) | $0 marginal. Escalate only after one failed attempt or a known-hard task. |
| Mechanical edits: renames, rote refactors, scaffolds, lint fixes | `supergrok/composer-2.5-fast` | $0 marginal, fast. |
| Bulk cheap: repo summaries, fixture drafts, log triage, doc drafts | `deepseek/deepseek-v4-flash-0731` | `openai/gpt-5.6-luna` when tool-calling reliability matters. Pennies per task; owner reviews all output. |
| Hard implementation escalation: cross-cutting, multi-file, gnarly typing | `openai/gpt-5.6-sol`, reasoning `high` | Same-tier alternative: `anthropic/claude-sonnet-5`. |
| Integrity-critical review: ledger claims, migrations, evidence resolution, release gates | `anthropic/claude-opus-5`, reasoning `high` | Reviewer vendor must differ from author vendor. At most one `anthropic/claude-fable-5` `max` pass per release-scale gate, owner-approved. |
| Cheap second-opinion reasoner: tiebreaks, sanity checks on premium output | `deepseek/deepseek-v4-pro`, reasoning `max` | Third-vendor diversity fallbacks: `zai/glm-5.2`, `qwen/qwen3.8-max`. |
| Vision QA: screenshots, rendered UI states | `google/gemini-3-flash-preview` | `zai/glm-5v-turbo` as alternative. |

Avoid without an owner-approved reason: `openai/gpt-5.5-pro` (one call can eat a double-digit share of a small credit pool) and `moonshotai/kimi-k3` (reasoning fixed at max, so all thinking bills as premium output). Dominated rows stay parked: `openai/gpt-5.5`, `gpt-5.4`, `gpt-5.4-mini` (beaten by sol/terra/luna on price-quality), `anthropic/claude-opus-4-5`–`4-8` (opus-5 price, older), `claude-sonnet-4-6` and `claude-haiku-4-5` (beaten by sonnet-5 and luna), `moonshotai/kimi-k2.6` (`kimi-k2.7-code` is the same price, code-tuned), `xai/grok-4.5`/`4.6` API routes (subscription twin exists; `xai/grok-4.3` only when cheap 1M context is the point), `google/gemini-3.1-pro-preview` (Google-specific long-context multimodal only), `zai/glm-5-turbo` (`glm-5.2` is stronger at a nearby price).

## Consistency and acceptance

- Planning belongs to the planning route; implementation, integration, and acceptance stay with the implementation owner.
- Task agents receive only bounded, non-sensitive candidate work. They do not own shared contracts, deployment, migrations, secrets, or final acceptance.
- Independence rule: for integrity-critical work the reviewing model's vendor differs from the authoring model's vendor, and no model reviews its own diff.
- Owner reruns decisive checks regardless of model: `npm run typecheck && npm run build`; `cd ledger && pytest -q`. Inspect the actual diff before accepting output.
- Use exact fallback order — `supergrok/grok-4.6` → `openai/gpt-5.6-sol` → `anthropic/claude-sonnet-5` unless a lane names its own — and record every failed or blocked predecessor.
- Never send secrets, private archives, credentials, or unrelated worktree files.

## Budget rules

- Estimate tokens before any premium dispatch; projected spend above roughly $10 needs owner sign-off, and actual spend goes in the receipt.
- Never run two premium models on the same question unless resolving a recorded disagreement.
- Prefer cache-friendly prompts (stable prefixes, reused context): cache-hit input is 10–50x cheaper on most routes.

Receipt fields: route, provider, model, billing kind, requested/effective effort, scope, files, evidence, estimated/actual cost, result (`ACCEPTED`, `REWORK`, `REJECTED`, or `BLOCKED`), and cleanup.

## Price appendix (vendor list, USD per 1M input/output tokens, checked 2026-08-26)

Subscription seat, $0 marginal credit: `supergrok/grok-4.6` and `supergrok/grok-4.5` (API twins list $2/$6), `supergrok/composer-2.5-fast`. Capy API billing may differ from vendor list; use this only for relative ordering. No public list price found for `zai/glm-5v-turbo`.

| Tier | Model | List price |
| --- | --- | --- |
| Bulk | deepseek-v4-flash-0731 | $0.14/$0.28 (peak/off-peak split announced from 2026-08-17, up to $0.44/$1.32) |
| Bulk | gpt-5.6-luna | $0.20/$1.20 |
| Bulk | gemini-3-flash-preview | $0.50/$3.00 |
| Mid | deepseek-v4-pro | $0.435/$0.87 (same peak/off-peak note) |
| Mid | gpt-5.4-mini | $0.75/$4.50 |
| Mid | kimi-k2.7-code, kimi-k2.6 | $0.95/$4.00 |
| Mid | claude-haiku-4-5 | $1/$5 |
| Mid | glm-5-turbo | $1.20/$4.00 |
| Mid | grok-4.3 (API) | $1.25/$2.50 |
| Mid | glm-5.2 | $1.40/$4.40 |
| Mid | gpt-5.3-codex | $1.75/$14 |
| Mid | claude-sonnet-5 | $2/$10 (intro price through 2026-08-31) |
| Mid | gpt-5.6-terra | $2/$12 |
| Mid | gemini-3.1-pro-preview | $2/$12 |
| Mid | qwen3.8-max | $2/$6 (no cache discount listed) |
| Premium | claude-sonnet-4-6 | $3/$15 |
| Premium | kimi-k3 | $3/$15 (reasoning fixed at max) |
| Premium | gpt-5.6-sol | $4/$20 (promo through 2026-11-21) |
| Premium | gpt-5.4, gpt-5.5 | $2.50/$15, $5/$30 |
| Premium | claude-opus-4-5…4-8, claude-opus-5 | $5/$25 |
| Frontier | claude-fable-5 | $10/$50 |
| Frontier | gpt-5.5-pro | $30/$180 |
