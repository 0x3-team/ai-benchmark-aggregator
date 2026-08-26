# Contributing to AI Benchmark Aggregator

Thanks for contributing to `0x3-team/ai-benchmark-aggregator`.

This repository contains a React/Vite frontend and a Python ledger CLI. The
frontend currently shows `Demo (synthetic)` data. The governed `Official` track
is intentionally unavailable until a separately approved release artifact,
source evidence, review, and publication decision exist. A local fixture,
generated export, or test result is not an Official release.

## Start safely

Before changing anything, inspect the checkout and preserve existing work:

```bash
git status --short --branch
git diff --check
```

Do not use `reset`, `clean`, `checkout` to discard work, destructive database
commands, or production/provider operations as part of routine development.
Keep unrelated dirty files and untracked fixtures intact.

### Frontend

```bash
npm install
npm run verify:official-artifact
npm run typecheck
npm test
npm run build
node --test scripts/verify-pages-static-node-tests.mjs
```

`npm run dev` starts the local Vite server. Local build or preview evidence is
not deployment evidence. Do not upload or deploy from this repository without
separate authorization.

### Ledger CLI

Use a disposable local environment for Python dependencies. The normal local
checks are read-only after setup:

```bash
cd ledger
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
PYTHONPATH=. benchmark-ledger --help
pytest -q
```

Do not run ingestion, source fetching, bulk review, claim export, or an
Official-mode switch while working on an ordinary pull request. Those are
governed operations with separate evidence-preservation and release controls.
If a change needs a database, use only an explicitly disposable temporary
database and retain the test receipt; never point it at a claim-bearing ledger.

## Invariants

- Preserve raw source lexemes (`model_raw`, `benchmark_raw`, `score_raw`, and
  related fields) exactly.
- Claims and snapshots are append-only. Source changes create new snapshots and
  claims; they do not rewrite historical rows.
- Snapshot source bytes before extraction and retain typed evidence that can
  re-resolve every raw value.
- Uncertain model identity stays unresolved and marked for review.
- The frontend reads scores only through `DatasetProvider` and `getValue`.
- Missing scores remain no-data (`—`), never zero or a fabricated value.
- Demo, candidate, legacy, fixture, and ignored local-export data must not be
  presented as Official.
- Keep the ledger CLI-only; do not add a public ingestion or claims API.

## Pull request checklist

- [ ] `git diff --check` is clean and unrelated work is preserved.
- [ ] Relevant focused tests pass, plus the full frontend or ledger suite when
      that surface changed.
- [ ] `npm run verify:official-artifact` still reports the tracked Official
      artifact as unavailable/data-free when frontend files changed.
- [ ] Static Pages checks pass when public assets, metadata, or headers changed.
- [ ] No source was fetched, ingested, exported, published, or promoted to
      Official.
- [ ] No secrets, tokens, credentials, private URLs, or generated claim-bearing
      artifacts were added.
- [ ] Documentation and the issue/PR template are updated when behavior or a
      trust boundary changes.

## Issues and proposals

Use the templates in `.github/ISSUE_TEMPLATE/` for bug reports and feature
requests. For a new benchmark source, describe the official source, revision,
terms/permission status, dimensions, raw-value contract, evidence strategy, and
fixture plan. Do not attach credentials or claim-bearing exports, and do not
request live ingestion as a prerequisite for discussion.

## Branches, reviews, and status language

Use a short branch such as `feat/<description>` or `fix/<description>` and
Conventional Commit messages where practical. GitHub branch protection,
required checks, review routing, and CODEOWNERS validity are provider settings,
not promises made by this file; check the live repository before relying on
them. The current checkout contains a CODEOWNERS file, but its live owner
identities and write access still require GitHub verification.

Describe evidence precisely: “validated locally”, “pushed”, “deployed”, and
“verified live” are different states. A local build, a GitHub commit, and a
provider deployment do not prove one another.

## License

By contributing, you agree that your contributions are licensed under the MIT
License.
