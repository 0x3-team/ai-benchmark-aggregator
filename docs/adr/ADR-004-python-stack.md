# ADR-004: Python packaging and test stack

**Status:** Accepted  
**Date:** 2026-07-11; PostgreSQL driver update 2026-07-15
**Decision ID:** DEC-004

## Context

Ledger MVP needs stable, common libraries and fixture-heavy tests.

## Decision

| Concern | Choice |
|---------|--------|
| Packaging | `pyproject.toml` (setuptools) |
| Schemas | Pydantic v2 |
| DB | SQLAlchemy 2.x; SQLite locally plus psycopg 3 and real PostgreSQL-native target tests |
| Schema migrations | Alembic (see ADR-006) |
| CLI | Typer |
| HTTP | httpx |
| YAML | PyYAML |
| HTML tables | beautifulsoup4 + lxml (optional) |
| Tests | pytest |
| Entry point | `benchmark-ledger` |

## Consequences

- Local SQLite via `DATABASE_URL=sqlite:///./data/benchmark_ledger.db`.
- PostgreSQL URLs require the reviewed psycopg 3 binary extra; migrations use
  direct/session connections while runtime pooling remains a later measured
  configuration gate.
- Adapters never write DB directly; runner persists typed objects.
