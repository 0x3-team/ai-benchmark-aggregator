---
name: model-identity-review
description: Use when reconciling model names across registries, benchmark sources, discovery inventories, and the frontend. Keep raw names and review state separate from canonical identity.
---

# Model identity review

Use this skill for model discovery, registry enrichment, duplicate analysis, and identity decisions.

## Rules

- Preserve every observed `model_raw` value and its source context.
- Treat exact matches, aliases, family names, provider namespaces, and checkpoints as different cases.
- Do not merge models only because their display names look similar.
- If identity is uncertain, leave `model_entity_id` null and mark the record `needs_review`.
- Append a review decision for a manual correction; never rewrite the captured claim.
- Keep discovery inventories separate from official published results.
- Record source URL, retrieval time, revision/hash, and matching rationale for each candidate.

## Checks

Compare at least:

- frontend model identifiers;
- ledger registry entities;
- official source model labels;
- discovery candidates and aliases.

Report exact matches, unresolved candidates, possible collisions, and coverage gaps. Do not invent benchmark scores for missing models.
