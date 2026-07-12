# Task state machine

## States

`RECEIVED → SCOPED → PLANNED → BLOCKED|READY → ROUTING → DISPATCHED → RUNNING → REVIEW → REVISION_REQUESTED|APPROVED|SELF_FIX|TAKEOVER|FAILED → INTEGRATING → INTEGRATED → VERIFIED → LEARNED`

Also: `CANCELLED` from most non-terminal states under user abort.

## Valid transitions (primary)

| From | To | Guard |
|------|----|-------|
| RECEIVED | SCOPED | inspected |
| SCOPED | PLANNED | requirements linked |
| PLANNED | BLOCKED | unmet deps |
| PLANNED | READY | deps satisfied |
| BLOCKED | READY | deps satisfied |
| READY | ROUTING | scheduler picks |
| ROUTING | DISPATCHED | worker assigned |
| ROUTING | RUNNING | self-exec |
| DISPATCHED | RUNNING | adapter start |
| RUNNING | REVIEW | result ingested |
| RUNNING | FAILED | crash/timeout after policy |
| REVIEW | APPROVED | pass |
| REVIEW | SELF_FIX | minor only |
| REVIEW | REVISION_REQUESTED | retry remaining |
| REVIEW | TAKEOVER | retries exhausted / high risk |
| REVIEW | BLOCK_FOR_HUMAN | policy |
| REVISION_REQUESTED | DISPATCHED | retry packet sent |
| SELF_FIX | INTEGRATING | fixes done |
| APPROVED | INTEGRATING | merge start |
| TAKEOVER | INTEGRATING | orchestrator finished task |
| INTEGRATING | INTEGRATED | on integration branch |
| INTEGRATED | VERIFIED | project gates |
| VERIFIED | LEARNED | profile updated |
| * | FAILED | unrecoverable |
| * | CANCELLED | user/policy abort |

## Invariants

1. No transition to INTEGRATED without APPROVED|SELF_FIX|TAKEOVER path.  
2. No worker writes integration branch.  
3. LEARNED only after outcome event persisted.  
4. Parallel RUNNING tasks must have disjoint `write_scope` or explicit lock.  

## Terminal states

`LEARNED`, `FAILED`, `CANCELLED`
