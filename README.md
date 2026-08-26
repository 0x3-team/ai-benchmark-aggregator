# AI Benchmark Aggregator

**Organization:** 0x3-team  
**Repository:** `0x3-team/ai-benchmark-aggregator`  
**Status:** Private (MIT-licensed, open-source-quality standards) — Demo available; Official publication intentionally unavailable pending source certification

A single-page **AI model benchmark comparison dashboard** with a **dual-mode data architecture**:

| Mode | Source | Purpose |
|------|--------|---------|
| **Demo (Synthetic)** | `src/data/scores.ts` — curated demo fixtures | Instant UI development, zero dependencies |
| **Official (Ledger)** | Tracked unavailable artifact; future governed ledger release artifact | Explicitly unavailable until source, evidence, review, and release gates pass |

> **Trust boundary:** Ledger stores *claims* ("source X reported score Z"). UI rankings/averages are **presentation-only** — never persisted as official claims. A local generated export or a sample fixture is not an Official release artifact. The future v2 artifact parser is deliberately dormant until REL-05 provides a separately governed authorization that pins an immutable artifact and its digest. Until then, an Official request explicitly keeps the visible dataset in Demo (synthetic); a future governed release will show its artifact, approval, timestamp, and policy metadata without claiming the UI independently verifies scores.

### Future governed score evidence

Official remains unavailable in the shipped runtime. Once REL-05 authorizes an
immutable published artifact, every individual score display will expose a
keyboard-operable evidence disclosure with the verbatim raw value, source URL,
claim and snapshot IDs, evidence location, retrieval timestamp, and governing
policy. The disclosure resolves only when the score provenance exactly matches
the release source manifest; malformed or mismatched provenance exposes no
evidence control, and malformed URLs never produce empty links. The future
Official status area also provides a separate source-manifest disclosure. Demo
scores and presentation-only rankings/averages are intentionally not labelled
as Official claims.

---

## Quick Start

### Frontend (React SPA)

```bash
npm install
npm run dev          # Vite dev server
npm run verify:official-artifact  # validates the tracked unavailable release artifact offline
npm run typecheck    # tsc --noEmit (must pass)
npm run test         # vitest unit tests
npm run build        # tsc -b && vite build (must pass)
```

### Ledger (Python CLI)

```bash
cd ledger
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
benchmark-ledger init-db
benchmark-ledger seed-registry
pytest -q
```

With the default `DATABASE_URL=sqlite:///./data/benchmark_ledger.db`,
`init-db` creates at most the one missing direct `data/` parent under the
existing `ledger/` directory, then applies the versioned migrations to a fresh
SQLite file. It is idempotent at the migration head, refuses populated
unversioned or otherwise unsupported databases, and never upgrades an existing
claim-bearing database. `ingest` does not initialize or migrate a database;
run `init-db` first and confirm the database is current.

Use `init-db` only for a new, disposable development database. `seed-registry`
is an append-only source-reconciliation operation, never a reset: it retains
claims, snapshots, and runs while creating source revisions or retirement
decisions. Do **not** run ingestion (including `--dry-run`), bulk auto-review,
or export against a claim-bearing ledger during remediation. Those production
routes are intentionally blocked; see the [evidence-preservation runbook](docs/runbooks/official-publication-and-evidence-preservation.md).

The operator baseline is available without initializing or changing a ledger:

```bash
benchmark-ledger coverage status --format markdown
benchmark-ledger coverage status --format json
```

This bounded census accounts for every current registry row and reports
duplicate identities, alias collisions, source divergence, and quarantined
SQLite health. Exit `1` means a complete report was emitted but blockers remain;
exit `2` means the inputs/report were invalid. The census and its discovery
candidate contracts are operational read models, never Official claims or
frontend data. The checked-in Coverage Universe is intentionally
`draft_unapproved`, so its missing owner decision is itself a visible blocker;
the census cannot approve that revision. Census readiness covers deterministic
reconciliation only. Freshness remains `not_assessed` until a later scheduled
receipt binds an explicit cycle/as-of value.

The continuous-operations contracts and their durable persistence foundation
are implemented but deliberately inert. The
[contract catalog](docs/contracts/README.md),
[ADR-008](docs/adr/ADR-008-continuous-collection-contract-boundaries.md), and
[local rehearsal runbook](docs/runbooks/continuous-discovery-recheck-contract-rehearsal.md)
define source/check, benchmark/system identity, UTC scheduling/fencing, and
incident/notification receipts. [ADR-009](docs/adr/ADR-009-operational-persistence-and-inert-runtime-composition.md)
and its [acceptance runbook](docs/runbooks/operational-persistence-and-runtime-composition-rehearsal.md)
add forward-only operational tables, guarded leases, exact evidence
references, and a live-disabled dependency composition root on fresh or
disposable databases. They do not run discovery, fetch sources, send alerts,
migrate the quarantined ledger, provision a provider, publish data, or activate
Official mode.

The provider-neutral DATA-10 recovery foundation now creates one immutable
checkpoint per terminal collection cycle across the relational backup and all
retained snapshot bytes, then verifies a restore only on new relational and
object targets. SQLite and real disposable PostgreSQL 16 paths share the same
manifest, object-copy, lineage, and receipt semantics. The operator CLI uses
explicit local paths or fixed PostgreSQL environment variables, never the
configured application database or a DSN on argv. A failed target is retained
and never reset/reused. The requested loss of at most one completed cycle is
still a target—not a production promise—and local duration, different local
roots, and a successful custom archive do not prove provider independence,
retention, role/ACL recovery, RPO/RTO, cutover, or Official publication. See
[ADR-010](docs/adr/ADR-010-provider-neutral-recovery-evidence.md) and the
[recovery runbook](docs/runbooks/provider-neutral-recovery-checkpoint-and-restore.md).

---

## Project Structure

```
ai-benchmark-aggregator/
├── .github/                    # GitHub org config
│   ├── workflows/verify.yml    # CI: ledger/frontend checks + clean archive build
│   ├── workflows/deploy-cloudflare-pages.yml # Environment-gated Pages candidate
│   ├── ISSUE_TEMPLATE/         # Bug report & feature request templates
│   ├── dependabot.yml          # Weekly dependency updates (npm, pip, actions)
│   └── CODEOWNERS              # Auto-review assignment
├── src/                        # React SPA (Vite + TS + Tailwind)
│   ├── components/             # UI components (glassmorphism, charts, tables)
│   │   ├── evilcharts/        # Vendored EvilCharts (Recharts 3 + Motion), read-only
│   │   └── charts/             # App chart adapters mapping app data to EvilCharts
│   ├── data/                   # Data access layer
│   │   ├── official/           # Tracked unavailable artifact; ignored local export is not runtime input
│   │   ├── dataset.tsx         # Immutable React snapshot + sole getValue() accessor
│   │   └── scores.ts           # Deterministic synthetic Demo score generator
│   ├── lib/                    # Utilities (colors, aggregation, categories, chartData builders)
│   └── types.ts                # Shared TypeScript types
├── ledger/                     # Python CLI (Typer + SQLAlchemy + Pydantic)
│   ├── app/
│   │   ├── cli.py              # Typer commands
│   │   ├── backup/             # Provider-neutral checkpoint/new-target restore drivers
│   │   ├── db/                 # SQLAlchemy models, migration service, repositories
│   │   ├── ingestion/          # Adapters (official_sources.yaml → claims)
│   │   ├── matching/           # Model/benchmark alias resolution
│   │   ├── registry/           # official_sources.yaml + seed_loader
│   │   ├── export/             # Future governed export projection
│   │   └── schemas/            # Pydantic boundaries
│   ├── tests/                  # Offline pytest fixtures + tests
│   ├── migrations/             # Forward-only Alembic schema history (no downgrade recovery)
│   ├── alembic.ini             # Migration configuration
│   └── pyproject.toml
├── docs/adr/                   # Architecture Decision Records
├── AGENTS.md                   # Agent rules for both systems
├── package.json
├── tsconfig.json
└── vite.config.ts
```

---

## CI / CD

**GitHub Actions** (`.github/workflows/verify.yml`) runs on every PR:

1. **Ledger tests** — exact Python 3.11 CI constraints + `pytest -q`, including real-dialect and fresh-target recovery suites against disposable PostgreSQL 16
2. **Frontend** — `npm run typecheck && npm run test && npm run build`
3. **Clean archive** — verifies the immutable unavailable artifact and builds a fresh tracked archive without an ignored ledger export

The workflow pins GitHub Actions to reviewed commit SHAs, uses `contents: read`
only, and does not receive production data-plane credentials or run ingestion.
Python constraints are reviewed in [`ledger/requirements-ci.lock`](ledger/requirements-ci.lock);
they are not a release-artifact authorization or a replacement for future
SBOM/provenance review.

The [Cloudflare Pages deployment candidate](docs/runbooks/cloudflare-pages-deployment.md)
is workflow-dispatch-only and requires an explicit `DEPLOY` confirmation plus
a successful `Verify` push run for the exact full SHA. ND4 keeps every public
deployment blocked until the future REL-05 governed artifact, authorization,
and composition verifier paths land together. This is not a claim that any
provider, domain, DNS, environment, or secret is currently configured. The
companion smoke check is manual-only until an owner approves monitoring
permissions and a schedule.

**Branch protection:** recommended settings are requiring the `verify` workflow
and code review from `CODEOWNERS`; this README does not claim those settings are
enabled.

---

## Data Pipeline

```
Tracked `src/data/official/export.unavailable.json`
         ↓
Demo remains the only selectable runtime dataset
         ↓
Future governed path (currently disabled): certified source revision
→ immutable snapshot → raw claim + review decision
→ deterministic, content-hashed export + provenance manifest
→ explicitly enabled Official UI
```

The ignored `export.from-ledger.json` is an operator-local artifact only. It is
not committed, imported by the runtime, or accepted by CI as release evidence.

**Quarantined adapter inventory (not currently eligible for ingestion or publication):**

| Adapter | Sources |
|---------|---------|
| `generic_json` | MMLU, GPQA, MATH, HumanEval, MBPP, SWE-Bench, PaperBench, BFCL, GAIA, AgentBench, Terminal-Bench, WebArena, APEX-Agents, ToolBench, BrowseComp, TruthfulQA, FrontierCode, Aider Polyglot |
| `generic_csv` | HELM (JSON→CSV), IMO AnswerBench |
| `hf_datasets_server` | MMLU-Pro, GPQA Diamond, HLE |
| `fake` | Retired LDR-06 synthetic fixture adapter — temporary test-database fixture only; never an Official ingestion source |
| `artificial_analysis_api` | Retired LDR-06 third-party aggregate route — fixture parser only; never an Official ingestion source |
| `lmsys_arena_api` | Retired LDR-06 primary-plus-fallback route — fixture parser only; never an Official ingestion source |
| `livebench_adapter` | Retired LDR-06 assembled/derived aggregate route — fixture parser only; never an Official ingestion source |
| `livecodebench_adapter` | Retired LDR-06 date-window derived aggregate route — fixture parser only; never an Official ingestion source |
| `github_yaml` | Aider Polyglot (YAML in repo) |
| `taubench_s3` | Retired LDR-06 S3 submission aggregate route — fixture parser only; never an Official ingestion source |
| `frontiermath_epoch` | FrontierMath (Epoch AI) |
| `imo_answerbench` | IMO AnswerBench (GitHub CSV — inactive, no model scores) |
| `helm_json` | HELM (GCS — URL 404, needs rediscovery) |

---

## Credentials and environment

No source credential is used by the current ingestion boundary. The current
contained routes require and authorize no source credentials. The central
safe-fetch client refuses credentialed sources and has no enabled live transport
until a private runner/egress policy and one source certification are approved.
Do not add a token to the browser, CI, a registry URL, adapter, or public log.
Historical `.env.example` placeholders are not authorization to use those
routes. See the [safe-fetch runbook](docs/runbooks/source-certification-and-safe-fetch.md).

---

## Development Rules (from AGENTS.md)

- **Ledger:** Preserve raw source values exactly. No recalculation. Existing claims/snapshots are retained; do not use registry reseeding as a reset mechanism.
- **Frontend:** `getValue(modelId, benchmarkId)` is the **only** score accessor. Null scores render as `—` (dashed).
- **UI:** Glassmorphism via `cn(...)` + Tailwind. Sticky columns = `overflow-x-auto` + sticky left. SOTA = gold ring (`.sota-cell`).
- **Charts:** EvilCharts (Recharts 3 + Motion), vendored read-only at `src/components/evilcharts/`; app adapters in `src/components/charts/`; data builders in `src/lib/chartData.ts`. All new charts MUST use EvilCharts; hand-rolled SVG/div charts are forbidden. Heatmap tables (ScoreTable, ScoreHeatmap, ModelDetail dots) are data tables, not charts, and remain on `heatmapColor()`.
- **Quality gates:** `npm run typecheck && npm run build && npm test` + `cd ledger && pytest -q` **must pass** before merge.

---

## ADRs (Architecture Decisions)

| ID | Title | Summary |
|----|-------|---------|
| ADR-001 | Monorepo Layout | `src/` + `ledger/` at root, shared `AGENTS.md` |
| ADR-002 | Toast Strategy | Radix Toast retained; other primitives → Base UI |
| ADR-003 | Data Feed | Dual-mode boundary with tracked unavailable baseline |
| ADR-004 | Python Stack | Typer, SQLAlchemy 2.0, Pydantic v2, Typer CLI |
| ADR-005 | Official Publication Governance | Fail-closed containment, release artifact, and legacy-retention policy |
| ADR-006 | Versioned Ledger Migrations | Copy-only SQLite rehearsal, append-only provenance seams, and backup recovery |
| ADR-007 | PostgreSQL Portability | Provider-neutral PostgreSQL/R2 contracts are implemented and locally proven; provider provisioning, retention, restore, and cutover evidence remain gated |
| ADR-008 | Continuous Collection Contracts | Inert source, identity, schedule, incident, and notification boundaries before runtime/persistence work |
| ADR-009 | Operational Persistence | Durable operational evidence and explicit live-disabled runtime composition on fresh/disposable targets; service/provider activation remains gated |
| ADR-010 | Provider-neutral Recovery Evidence | Immutable cycle/database/object checkpoints, measured new-target receipts, and explicit non-claims for provider/RPO/RTO/cutover |

See `docs/adr/` for full records.

---

## License

MIT — see `LICENSE`.

---

## Team & Contacts

| Role | GitHub owner | Slack |
|------|-------------|-------|
| Core / Infra | `@Masih-0x3` | #0x3-core |
| Ledger | `@Masih-0x3` | #0x3-ledger |
| Frontend | `@Masih-0x3` | #0x3-frontend |

For questions, open an issue using the templates in `.github/ISSUE_TEMPLATE/`.
