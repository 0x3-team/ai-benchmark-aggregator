# Model capability priors (cold-start seed)

**Research date:** 2026-07-11  
**Scope:** Models actually reachable on the Masih/Hermes host via Cline-pass, Antigravity (`agy`), and KiloCode free gateway.  
**Confidence:** Medium for strengths (official + independent benches + live catalog). **Low as permanent truth** — treat as priors only; outcome events must update posteriors.

**Rules for the orchestrator**

1. Load this file on cold start / first routing for a category.
2. Use fit scores and strengths as **prior specialization_fit** and qualitative notes only.
3. Never hardcode permanent rankings. After real tasks, trust `store/orchestrator.db` over this file.
4. Re-probe live catalogs when tools/models change (`cline`, `agy models`, Kilo `/models`).
5. Version awareness: if model version/provider/harness changes, start a new profile key (discount old priors).

---

## A) Cline-pass (live-verified 2026-07-11)

Harness: `cline` · Provider: `cline-pass` · CLI thinking: `--thinking none|low|medium|high|xhigh`

| Model ID | Name | Ctx | Caps | Pricing $/1M (in/out) | Prior fit by category | Thinking | Notes |
|----------|------|-----|------|------------------------|----------------------|----------|-------|
| `cline-pass/glm-5.2` | GLM-5.2 | 1M | tools, reasoning, structured_output, temp, prompt-cache | 0.9 / 3.08 | **frontend/ui 0.95**, agentic_coding 0.90, backend 0.75, explore 0.80 | Client levels; family glm | Strong UI/design taste; long-horizon coding; Terminal-Bench ~81 class claims |
| `cline-pass/minimax-m3` | MiniMax-M3 | 512k | images, tools, reasoning, … | 0.3 / 1.2 | frontend 0.85, multimodal 0.80, agentic 0.80, backend 0.75 | Client levels | Open-weight SWE-Pro ~59% class; good UI + tools |
| `cline-pass/kimi-k2.7-code` | Kimi K2.7 Code | 256k | images, tools, reasoning, … | 0.74 / 3.5 | agentic_coding 0.88, backend 0.80, frontend 0.70 | Client levels | Repo/MCP/agent coding specialist |
| `cline-pass/deepseek-v4-pro` | DeepSeek V4 Pro | 1M | tools, reasoning, … | 0.435 / 0.87 | coding 0.90, reasoning 0.88, backend 0.85, frontend 0.65 | **Thinking family** | SWE-Verified ~80.6% class; strong hard coding |
| `cline-pass/deepseek-v4-flash` | DeepSeek V4 Flash | 1M | tools, reasoning, … | 0.09 / 0.18 | bulk_coding 0.75, draft 0.80, architecture 0.45 | Flash family | Cheap volume worker; weaker deep builds |

**Relative thinking (Cline-pass):** Pro > GLM-5.2 ≈ Kimi Code > MiniMax M3 > Flash

---

## B) Antigravity (`agy models` live)

Harness: `agy` · Effort often **baked into model label**

| Model label | Prior fit | Thinking label | Notes |
|-------------|-----------|----------------|-------|
| Claude Opus 4.6 (Thinking) | architecture 0.95, backend 0.95, hard_debug 0.95, multi_agent 0.90 | Highest | Deep systems / exactness |
| Claude Sonnet 4.6 (Thinking) | daily_coding 0.92, backend 0.88, frontend 0.75 | High | Best default daily agentic coding |
| Gemini 3.1 Pro (High) | architecture 0.85, reasoning 0.85, multimodal 0.80 | High | Deep when Flash insufficient |
| Gemini 3.1 Pro (Low) | same family lower depth | Low | Faster/cheaper Pro |
| Gemini 3.5 Flash (High/Med/Low) | agentic 0.85, multimodal 0.90, coding 0.80 | Low→High | Fast multimodal agent; often beats older Pro on agent tasks |
| GPT-OSS 120B (Medium) | stem_reasoning 0.70, **app_coding 0.35** | Medium | Not primary app engineer |

---

## C) KiloCode free only (gateway live, $0)

Harness: `kilo` / `kilocode-gateway` · API model ids without `kilo/` prefix for gateway (e.g. `tencent/hy3:free`)  
CLI model form used successfully: `kilocode-gateway/tencent/hy3:free`

| Model ID | Prior fit | Reasoning params | Notes |
|----------|-----------|------------------|-------|
| `tencent/hy3:free` | volume_agent 0.75, tools 0.80, docs 0.80, **elite_coding 0.55** | reasoning, reasoning_effort (no/low/high style) | Free default; not top coder in some independent tests |
| `stepfun/step-3.7-flash:free` | multimodal 0.85, agent 0.80, coding 0.75 | reasoning; **high/med/low** | Screenshot→code, tools |
| `poolside/laguna-m.1:free` | coding_agent 0.80, se 0.78 | reasoning | Best free coding-agent personality |
| `poolside/laguna-xs-2.1:free` | coding_agent 0.70 | reasoning | Lighter free SE |
| `nvidia/nemotron-3-ultra-550b-a55b:free` | long_agent 0.85, reasoning 0.88 | reasoning_effort | NVIDIA trial logging ToS |
| `nvidia/nemotron-3-super-120b-a12b:free` | multi_agent 0.82, reasoning 0.85 | reasoning_effort | Efficient long agents; ToS |
| `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free` | perception 0.80, coding 0.50 | reasoning | Omni inputs; not main coder |
| `cohere/north-mini-code:free` | agentic_coding 0.68 | reasoning | Small free coding MoE |
| `kilo-auto/free` / `openrouter/free` | unpredictable 0.40 | varies | Routers only when model identity does not matter |
| Lyria / content-safety free | **coding 0.0** | n/a | Not coding models |

**Paid Hy3** (`tencent/hy3`, preview) exists but was blocked on zero credits in this environment.

---

## D) Specialty routing cheat sheet (priors only)

| Job | First prior pick | Second | Avoid as primary |
|-----|------------------|--------|------------------|
| UI/UX, frontend, visual taste | `cline-pass/glm-5.2` | MiniMax M3 / Step 3.7 Flash free | GPT-OSS 120B |
| Backend architecture / hard systems | Opus 4.6 Thinking (agy) | Sonnet 4.6 / DeepSeek V4 Pro | Hy3 free as “architect” |
| Daily coding agent | Sonnet 4.6 or DeepSeek V4 Pro | GLM-5.2 if UI-heavy | Routers |
| Long-horizon / big repo | GLM-5.2 | Nemotron Super/Ultra free / DS Pro | Flash-only |
| Free-only coding agent | Laguna M.1 free | Step 3.7 Flash free | Treating Hy3 free as elite coder |
| Multimodal / screenshots | Gemini 3.5 Flash or Step 3.7 free | MiniMax M3 | GPT-OSS |
| Cheap bulk drafts | DeepSeek V4 Flash | Hy3 free | Opus for volume |
| Tools/docs/volume free | Hy3 free | Laguna XS / North Mini | Content-safety / Lyria |

---

## E) Suggested cold-start Beta seeds (optional)

Use only when `sample_count=0`. Format: category → (α,β) implying mean α/(α+β). Keep α+β small (≤6) so live outcomes dominate quickly.

| Model | frontend | backend | agentic_coding | architecture | test/docs |
|-------|----------|---------|----------------|--------------|-----------|
| glm-5.2 | 4,1 | 2,2 | 3,1 | 2,2 | 2,2 |
| deepseek-v4-pro | 2,2 | 3,1 | 4,1 | 3,1 | 2,2 |
| deepseek-v4-flash | 2,2 | 2,2 | 2,2 | 1,3 | 2,2 |
| minimax-m3 | 3,1 | 2,2 | 3,1 | 2,2 | 2,2 |
| kimi-k2.7-code | 2,2 | 3,1 | 4,1 | 2,2 | 2,2 |
| opus-4.6-thinking | 2,2 | 4,1 | 3,1 | 4,1 | 2,2 |
| sonnet-4.6-thinking | 2,2 | 3,1 | 4,1 | 3,1 | 2,2 |
| hy3:free | 2,2 | 2,2 | 2,2 | 1,3 | 3,1 |
| laguna-m.1:free | 2,2 | 2,2 | 3,1 | 2,2 | 2,2 |

---

## F) Live discovery commands (re-verify)

```bash
# Cline-pass probe known IDs
cline -P cline-pass -m cline-pass/glm-5.2 --json "OK"

# Antigravity
agy models

# Kilo free catalog
# GET https://api.kilo.ai/api/gateway/models  (KILOCODE_API_KEY)
kilo run -m kilocode-gateway/tencent/hy3:free "OK"
```

When discovery finds a new model, add a static metadata row + weak Beta(1,1) unless evidence supports a seed.
