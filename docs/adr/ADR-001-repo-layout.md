# ADR-001: Repository layout for ledger vs frontend

**Status:** Accepted  
**Date:** 2026-07-11  
**Decision ID:** DEC-001

## Context

The workspace root is the React SPA (`src/*`). The official benchmark ledger is a new Python CLI system. Paths must be chosen so both can live in one git repo without disrupting the existing frontend.

## Decision

Use a **monorepo subdirectory**:

```text
/
  src/                 # existing Vite React frontend
  ledger/              # Python package (benchmark-ledger)
  contracts/           # shared export schemas (later)
  docs/adr/            # architecture decisions
  .orchestrator/       # task corpus / runtime
```

## Consequences

- Ledger write scopes bind to `ledger/**`.
- Frontend continues at repo root for existing npm scripts.
- Later optional split into packages/ is a non-breaking move.

## Alternatives rejected

- Separate repository (harder dual-mode integration)
- Replacing root with Python package (breaks frontend UX)
