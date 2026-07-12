# System map — AI Benchmark Platform

## Vision
Unify **official benchmark result capture** (Python ledger) with the existing **React comparison dashboard**.

```
Official sources (HF API, HTML tables, JSON/CSV files)
        │
        ▼
 SourceAdapter.fetch → Snapshot storage (content_hash)
        │
        ▼
 extract_claims → validate → match aliases → result_claims (immutable)
        │
        ▼
 CLI export / optional read API  ──bridge──►  Frontend data layer
                                                │
                              ┌─────────────────┼─────────────────┐
                              ▼                 ▼                 ▼
                         ScoreTable      ModelComparison     Detail Sheets
                         (ranking)       (radar/heatmap)     (provenance)
```

## Trust boundary
- Ledger stores **claims**: “source X reported score Z”.
- Frontend may **present** rankings/averages, but must not write averages back as official claims.
- Dual mode: `demo` synthetic data vs `official` ledger-backed data.

## Current repo facts
- Root is Vite/React SPA (`src/*`), synthetic scores in `src/data/scores.ts`.
- Ledger code not yet present; paths under `ledger/` are provisional pending DEC-001.
- Open FE work: Base UI migration (Toast decision DEC-002).

## Non-goals (MVP)
- Running model evaluations
- Recalculating or inventing benchmark scores
- Trusted ingestion of vendor blogs/articles
- Full ledger web UI / paid cloud deployment
