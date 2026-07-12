# ADR-004: Python packaging and test stack

**Status:** Accepted  
**Date:** 2026-07-11  
**Decision ID:** DEC-004

## Context

Ledger MVP needs stable, common libraries and fixture-heavy tests.

## Decision

| Concern | Choice |
|---------|--------|
| Packaging | `pyproject.toml` (setuptools) |
| Schemas | Pydantic v2 |
| DB | SQLAlchemy 2.x + SQLite (Postgres-compatible types where easy) |
| CLI | Typer |
| HTTP | httpx |
| YAML | PyYAML |
| HTML tables | beautifulsoup4 + lxml (optional) |
| Tests | pytest |
| Entry point | `benchmark-ledger` |

## Consequences

- Local SQLite via `DATABASE_URL=sqlite:///./data/benchmark_ledger.db`.
- Adapters never write DB directly; runner persists typed objects.
