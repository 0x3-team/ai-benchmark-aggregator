# Routing algorithm

## Hard filters (eliminate first)

Required language/modality/context/tools/access, privacy, license, budget, latency deadline, provider up, structured output, sandbox, reliability floor, risk policy.

## Utility

```
U(m,t) =
  w_q * P(success|m,t)
+ w_fit * specialization_fit
+ w_tools * tool_fit
+ w_ctx * context_fit
+ w_rel * reliability
+ w_exp * exploration_bonus
- w_cost * E[total_cost]
- w_lat * E[latency]
- w_rev * E[review_burden]
- w_retry * E[retry_cost]
- w_int * integration_risk
- w_sec * policy_risk
```

Default weights: see `scripts/select_model.py` (`DEFAULT_WEIGHTS`).

`E[total_cost]` includes invocation + context transfer + tools + expected retries + review + integration.

## Self comparison

Compute `U(self,t)` for Grok orchestrator direct execution.

Delegate only if:

1. candidate eligible  
2. `U(candidate) >= U(self) + delegation_margin` (default **0.08**)  
3. failure risk ≤ max for task risk class  
4. no security/privacy/integration violation  

## Success probability

Beta-Binomial posterior mean `α/(α+β)` from capability store, keyed by:

`(model_id, provider, version, harness, reasoning_setting, category, stack_key)`

Cold start: `α=1, β=1` (mean 0.5) plus optional low-confidence prior from documentation — never permanent benchmark rank as truth.

## Exploration

Contextual Thompson sampling on Beta posteriors for **low/medium risk only**.

`exploration_bonus = 1/sqrt(1+n)` when sampling.

Disabled for high/critical risk, security, migrations, release, data-loss paths.

## Worked example

Task: implement responsive React settings panel (category=frontend, risk=low).

Candidates (illustrative priors, not fixed truth):

| Model | α,β | fit | cost | U (approx) |
|-------|-----|-----|------|------------|
| self (Grok) | — | 0.7 | 0.15 | 0.52 |
| cline-pass/glm-5.2 | 4,2 | 0.9 | 0.08 | 0.61 |
| kilocode hy3:free | 2,2 | 0.55 | 0.01 | 0.48 |
| deepseek-v4-flash | 3,2 | 0.6 | 0.03 | 0.50 |

Margin 0.08 → glm-5.2 utility 0.61 ≥ 0.52+0.08 → **delegate glm-5.2**.

If glm fails acceptance twice → TAKE_OVER; attribute; lower frontend posterior if model_capability.

## Drift

If rolling 10-task success rate drops >20pp vs long-run mean → `drift_status=watch|drift`; discount old samples faster.
