# Task Corpus — AI Benchmark Platform v1.0.0

## 1. Project summary

Unified implementation plan for:

1. **Official Benchmark Ledger** (Python CLI, append-only claims from official sources)
2. **AI Benchmark Aggregator frontend** (existing React SPA; Base UI migration + hardening)
3. **Integration bridge** (official claims to dashboard dual mode with provenance)

Core invariant: every stored number is a **source-backed claim**, not recalculated scientific truth. UI rankings/averages are presentation-only.

## 2. Source inventory

| Source | Role |
|--------|------|
| `benchmark_ledger_codex_handoff.md` | Full ledger PRD/architecture/milestones |
| `frontend_handoff.md` | Live frontend architecture + open Base UI task |
| `README.md` / `package.json` / `src/*` | Repo binding for frontend |
| Derived unified intent | Trust boundary + dual-mode product |

## 3. Assumptions and open decisions

**Assumptions:** SQLite OK for local MVP; synthetic demo data remains; Base UI Toast may stay Radix temporarily; ledger paths provisional under `ledger/`.

**Open decisions (block many leaves):**

- **DEC-001** Repo layout for ledger vs frontend
- **DEC-002** Toast strategy during Base UI migration
- **DEC-003** Ledger to UI feed (CLI JSON export recommended)
- **DEC-004** Python packaging stack

## 4. Architecture overview

See `architecture/system-map.md`. Trust boundary: ledger stores claims; SPA may aggregate for display only.

## 5. Workstreams

| Workstream | Leaves | Focus |
|------------|--------|-------|
| Ledger Core | 19 | Package, 9 tables, seed |
| Ledger Ingestion | 13 | Runner, HF/JSON/CSV/HTML adapters |
| Base UI Migration | 11 | Radix to Base UI primitives |
| Foundation | 7 | ADRs, AGENTS.md, README |
| Ledger Ops | 7 | Full CLI + daily docs |
| Frontend Hardening | 7 | getValue, lowerIsBetter, a11y, build |
| Ledger Review | 6 | Matching + review CLI |
| Integration Bridge | 6 | Export contract + official mode UI |
| Registry Expansion | 5 | More official sources post-MVP |
| Quality Gates | 5 | Reliability, secrets, E2E golden path |

## 6. Requirement coverage

42 material requirements mapped to tasks (coverage audit PASS).

## 7. Task counts

- Total tasks: **124** (parents 38, leaves 86)
- Leaf status: READY 31, BLOCKED 50, PROVISIONAL 5
- By category: {'DECISION': 4, 'DOCUMENTATION': 8, 'IMPLEMENTATION': 52, 'CONTRACT': 3, 'VERIFICATION': 15, 'DISCOVERY': 1, 'CLEANUP': 1, 'SECURITY': 1, 'GOVERNANCE': 1}
- By size: {'S': 49, 'XS': 10, 'M': 27}
- By risk: {'HIGH': 6, 'MED': 78, 'LOW': 2}
- Hard edges: 109
- Execution waves: see `graph/execution-waves.json`

## 8. Critical path (longest dependency chain)

- `FOUNDATION-LAYOUT-DECISIONS-001` — Decide monorepo layout for ledger vs frontend (READY)
- `LEDGER-CORE-PACKAGE-SCAFFOLD-001` — Create pyproject.toml and package layout under chosen ledger root (BLOCKED)
- `LEDGER-CORE-DATABASE-LEDGERS-003-L` — Implement aliases table model and repository methods (BLOCKED)
- `LEDGER-REVIE-MATCHING-001` — Implement alias matching for model_raw (BLOCKED)
- `LEDGER-REVIE-REVIEW-CLI-001` — Implement review queue listing command (BLOCKED)
- `LEDGER-REVIE-REVIEW-CLI-002` — Implement review show and map-model commands (BLOCKED)
- `LEDGER-REVIE-REVIEW-CLI-003-L` — Implement mark-human-verified and aliases add commands (BLOCKED)
- `LEDGER-REVIE-REVIEW-CLI-004` — Add review workflow automated tests (BLOCKED)

## 9. Recommended execution order

1. **Decisions first:** DEC-001 through DEC-004 (Foundation).
2. **Ledger core:** package → schemas → snapshot storage → 9 tables → seed → idempotency tests.
3. **Fake adapter + runner** before any network adapter.
4. **HF adapter**, then generic JSON/CSV, then HTML (SWE-bench/LiveCodeBench).
5. **Matching + review CLI**.
6. **Ops / daily readiness** (`ingest --all`, failure isolation).
7. **Frontend hardening** in parallel (real `src/*` paths).
8. **Base UI migration** after toast ADR; one primitive per leaf; build green each time.
9. **Integration bridge** after ledger claims + DEC-003.
10. **Registry expansion + quality gates** last.

## 10. Audit results

- `schema-report`: **PASS**
- `coverage-report`: **PASS**
- `granularity-report`: **PASS**
- `duplication-report`: **PASS**
- `readiness-report`: **PASS**

## 11. Orchestrator instructions

Load order: `manifest.json` → `requirements/traceability.json` → `graph/execution-waves.json` → indexes → task shards.

Dispatch only `dispatchable:true` leaves. Prefer status READY; unblock BLOCKED by finishing decision tasks.

Do not hardcode models; use capability_tags + suggested_agent_role. Respect conflict_keys.
