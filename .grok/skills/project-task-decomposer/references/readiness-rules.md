# Readiness rules

## Statuses

| Status | Meaning |
|--------|---------|
| READY | All hard structural gates pass |
| CONDITIONALLY_READY | Substantial work can proceed; explicit blockers remain |
| NOT_READY | Unsafe for orchestrator (schema/cycle/coverage failures) |

## Hard gates (must pass for READY)

1. Schema/structure validity 100%
2. Dependency references 100% valid
3. Zero self-dependencies
4. Zero hard-dependency cycles
5. Material requirement coverage 100% or explicit blockers
6. Every dispatchable leaf has acceptance criteria
7. Every dispatchable leaf has verification plan
8. Every dispatchable leaf has definition of ready/done
9. Every dispatchable leaf has routing metadata
10. Zero dispatchable L/XL leaves
11. Zero parent records marked dispatchable
12. Conflict-prone leaves have conflict keys

## Commands

```bash
python scripts/validate_task_corpus.py <corpus> --json --write-report
python scripts/detect_cycles.py <corpus>
python scripts/audit_coverage.py <corpus> --write
python scripts/audit_granularity.py <corpus> --write
python scripts/audit_duplicates.py <corpus> --write
python scripts/calculate_execution_waves.py <corpus> --write
python scripts/build_indexes.py <corpus>
python scripts/check_readiness.py <corpus> --write
```
