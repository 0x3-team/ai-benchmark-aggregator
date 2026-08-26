---
name: benchmark-ledger-integrity
description: Use when changing or reviewing the official benchmark ledger, claims, snapshots, migrations, or evidence resolution. Preserve source fidelity and reject unsafe claims.
---

# Benchmark ledger integrity

Use this skill for work under `ledger/` that can change official claims or their evidence.

## Rules

- Preserve raw source fields exactly. Never normalize a captured value to make it admissible.
- Snapshot official source content before extraction.
- Every claim must retain its source snapshot, official source, certified source revision, raw fields, and typed evidence location.
- Keep uncertain model matches unresolved with `model_raw` and `needs_review`.
- Manual identity corrections append review decisions; they never rewrite claims or promote publication.
- Do not store UI rankings, averages, synthetic scores, or vendor commentary as official claims.
- Re-ingesting one source snapshot must be idempotent.
- Use versioned Alembic migrations for durable schema changes. Do not use downgrade or delete as recovery.

## Verification

Run focused fixture tests first, then:

```sh
cd ledger
python scripts/verify_ci_lock.py
pytest -q
```

Report changed files, claim/evidence invariants checked, commands run, and any unresolved review items.
