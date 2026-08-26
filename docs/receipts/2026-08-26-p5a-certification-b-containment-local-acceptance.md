# P5a Certification-B containment — local acceptance receipt

**Date:** 2026-08-26
**Base:** `origin/main` at `220ce272467ee99b1cb02a319a3c8277951c2f3c`
**Branch:** `feat/p5-certification-b-containment`
**Disposition:** accepted locally as candidate-only containment; no commit,
push, PR, deployment, certification, capture, or publication was performed.

## Changed paths

- `ledger/app/registry/official_sources.yaml`
- `ledger/app/registry/coverage_universe.yaml`
- `ledger/tests/test_p5_registry_containment.py`
- `ledger/tests/test_coverage_census.py`
- `docs/audits/2026-08-26-p5-certification-b-containment.md`
- `docs/receipts/2026-08-26-p5a-certification-b-containment-local-acceptance.md`

The external candidate was reworked and accepted only after review. Its
`parser_config` metadata additions and inline-formatting changes were removed.
For all ten routes, the official source object now differs from the base only
in `status` and `notes`. Coverage membership is unchanged; only the ten route
status/reason fields and deterministic digest literals changed.

## Validation

- `git diff --check` — passed.
- `git diff --name-only origin/main...HEAD` — empty; the branch remains at the
  stated base. Current uncommitted paths before this receipt were the five
  other paths listed above.
- `cd ledger && uv run --isolated --python 3.11 --locked --extra dev pytest -q tests/test_p5_registry_containment.py tests/test_coverage_contracts.py tests/test_coverage_census.py tests/test_registry_preservation.py` — **172 passed**.
- The real coverage census is computed twice in
  `test_real_universe_digest_and_baseline_denominators`; reports and exact
  digests are identical.
- Git-less portability simulation (Git shadowed by a failing shim):
  `tests/test_p5_registry_containment.py` — **7 passed**; the test has no
  Git, `.git`, or subprocess dependency.
- `cd ledger && uv run --isolated --python 3.11 --locked --extra dev pytest -q` — **1,691 passed, 14 skipped**.

Exact deterministic values:

- Coverage-universe `manifest.contentSha256`:
  `6a91f3fd311b43a67b3db545219056498f5bb5cd5b25b928e419350aff134320`
- Coverage-universe configured-source semantic digest:
  `1c3fc5768d488668ecdf868b111dc4c59514a70527a634fc46c26671bcadd274`
- Coverage-census report `manifest.contentSha256`:
  `03a84a8c21e18d63ca910a91e815cec66cf3acef36090e73c89b59a993f54040`

The ten routes remain configured but inactive. Configured coverage is `53`;
active routes are `13`. Disposable seeding retains the ten rows, excludes them
from active enumeration, and reseeding creates no new revisions, snapshots,
claims, or ingestion runs. No network socket or connection is permitted by the
containment test. The production census pin intentionally covers all `54`
official-source rows while the universe remains a `53`-route denominator; the
filtered 53-row digest is `ef2acc813d16b8ab4d9240002afd71d27403caa7bb089b694c349134212afce5`.

## Authority ceiling and residual gates

This receipt is local repository evidence only. It does not certify a source,
authorize capture, create source bytes or snapshots, admit claims, decide
terms, resolve identity, authorize publication, or establish release or
production readiness. The audit remains candidate-only and coverage-only.

The pre-existing `lmarena_first_party_leaderboard_candidate` remains outside
the universe. `UNIVERSE_REGISTRY_DENOMINATOR_MISMATCH` and
`REGISTRY_SOURCE_OUTSIDE_UNIVERSE` remain deliberate residual blockers, and
the universe remains `draft_unapproved` (`UNIVERSE_REVISION_UNAPPROVED`). P5a
does not fix P6 coverage approval.

Reactivation requires a new immutable source definition with an admitted typed
evidence locator, exact field map, governance and owner-approved terms, plus a
separate owner-reviewed append-only source-revision certification decision.
Fresh source retrieval, source-authority and completeness checks, terms review,
identity review, capture, claim review, publication, release, deployment, and
production verification remain open gates.
