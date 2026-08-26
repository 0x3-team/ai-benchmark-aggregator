---
name: capy-portable-workflow
description: Use when Capy is asked to implement or review work in this repository. Keep changes scoped, Linux-portable, evidence-led, and safe for a pull-request workflow.
---

# Capy portable workflow

This repository is the source of truth. Read `AGENTS.md`, `README.md`, and the relevant ledger, frontend, contract, or runbook files before editing.

## Boundaries

- Work only in the requested scope. Do not expose secrets or copy local machine paths into committed files.
- Do not deploy to paid services or trigger paid operations without explicit authorization.
- Do not treat synthetic/demo data as official benchmark data.
- Do not change claim semantics, schemas, auth, or deployment configuration as incidental cleanup.
- Preserve unrelated untracked or dirty files.

## Delivery

- Make small, reviewable changes.
- Add or update tests and documentation when behavior or CLI contracts change.
- Use repository-relative commands and paths so the skill works on Capy Ubuntu machines.
- Before proposing a pull request, run the narrowest relevant checks, inspect the diff, then run the release gates when the change spans surfaces.
- Report what changed, what was verified, what was not checked, and any manual follow-up.
