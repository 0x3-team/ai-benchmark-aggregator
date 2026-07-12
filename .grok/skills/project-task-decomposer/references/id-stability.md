# Stable identifiers

## Task ID

`TSK-` + 8–12 char uppercase hex digest of:

- project_id
- normalized objective
- sorted requirement_ids
- sorted expected_outputs

See `scripts/stable_ids.py`.

IDs must **not** depend on array order, shard number, or Markdown display order.

## Preserve on CORPUS_UPDATE when

Objective, requirement mapping, and expected artifact identity are materially unchanged.

## Never reuse

An old ID for a semantically different task. Prefer new ID + `supersedes` / `replaced_by` / `superseded_by` + RETIRED status.

## Display key

Human hierarchy key such as `IDENTITY-REFRESH-002`. May change without changing `task_id`.

## Requirement ID

`REQ-` + digest of project_id + statement + source_refs, or explicit stable labels from the PRD when provided.
