# Granularity rules

## Dispatchable leaf

Must be XS/S/M, one primary objective, independent review, explicit I/O, acceptance criteria, verification, ready/done, routing metadata, bounded context.

## Split signals

Unrelated conjunctions; multiple components; multiple specialist roles; mixed schema+migration+app+rollout; L/XL size; many unrelated ACs.

## Merge signals

Trivial steps always done together; no independent completion state; orchestration overhead exceeds value.

## Not standalone tasks

Add import; rename local variable; open PR; run formatter; read a file; write one line; add comment; commit; invoke another agent.

Those belong as steps/verifiers inside a meaningful leaf.

## Not oversized leaves

Implement authentication; build the frontend; add all tests; create entire DB layer; deploy the product.
