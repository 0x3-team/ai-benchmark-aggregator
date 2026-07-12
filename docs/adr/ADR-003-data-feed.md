# ADR-003: Ledger-to-UI data feed

**Status:** Accepted  
**Date:** 2026-07-11  
**Decision ID:** DEC-003

## Context

The SPA must support synthetic demo data and official ledger-backed claims without mixing trust levels silently.

## Decision

**CLI JSON export first:**

1. `benchmark-ledger export-official-json --out <path>` writes a schema-validated file.
2. Frontend official mode loads that file (or a committed sample under `src/data/official/`).
3. Optional local HTTP API is deferred.

Trust labels: UI must show **Demo (synthetic)** vs **Official claims** mode.

Cross-benchmark averages remain **presentation-only** and must never be written back as ledger claims.

## Consequences

- No runtime coupling between Python and Vite in MVP.
- Operators control when official data is refreshed.
