# P11 permalink local acceptance receipt

Recorded: 2026-08-26T16:25:47Z

Branch: `feat/p11-permalinks`

Base: `d35b0ef4211b0ee03b53891762424bdef9e4782b`

Build source digest: `2bc13bc263f34bd0b56357f38b1a0c240145968084b283c917fe8d9b9bd1c573`

## Accepted local behavior

- The pure `v=1` codec canonicalizes the supported view state and omits default values other than the required version marker.
- Duplicate singleton parameters, invalid versions and enums, malformed percent sequences, control characters, oversized input, invalid sort pairs, and simultaneous model and benchmark sheets fail closed.
- Repeated vendor and comparison values preserve first-occurrence order. Comparison state is deduplicated and capped at six models.
- App state validates vendor, model, benchmark, comparison, category, and sort values against the active immutable dataset.
- User changes update the current URL with `history.replaceState`. `popstate` restores state without a toast or history-write loop.
- A governed source change clears data-dependent URL state. Awaiting-publication mode removes stale IDs and remains empty.
- Permalink state does not supply scores and does not bypass `DatasetProvider` or `getValue`.

## Local command evidence

- `npm run typecheck`: passed.
- `npm run typecheck:test`: passed.
- `npm test`: 21 files and 121 tests passed.
- Focused App and codec run: 29 tests passed.
- `npm run test:permalinks`: passed canonical restore, reload, stale-ID removal, invalid dual-sheet rejection, Back/Forward restoration, and exact 390 by 844 overflow and sheet-width assertions.
- `npm run test:mobile-overflow`: passed at 390 pixels (`documentScrollWidth=390`, `documentClientWidth=390`).
- `npm run build`: passed; 2,878 modules transformed.
- `npm run verify:build-provenance`: passed, including 25 adversarial tests.
- `npm run verify:pages-static`: passed, including 11 tests.
- `npm run verify:pages-workflows`: passed, including 18 tests.
- `npm run verify:bundle-budget`: passed (`eagerJs=497407`, `totalJs=1227527`) with 52 tests.
- `npm run verify:official-artifact`: passed for the governed unavailable containment artifact, with 8 tests.
- `cd ledger && uv run --locked --extra dev pytest -q`: 1,672 passed and 14 skipped.
- Independent engineering review: accepted with no material correctness finding.

CodeRabbit then found five bounded issues: percent-valued opaque fields did not round-trip, generated search values could exceed decoder limits, History API writes were not rate-contained, pending CDP requests could hang after socket failure, and reload/viewport assertions could read stale state. All five were verified against the code, fixed, and covered by the passing reruns above. The external docstring-coverage warning was not adopted because it is not a repository acceptance rule and would add comments without changing the contract.

The first concurrent full frontend run passed all 118 assertions but reported one Vitest worker teardown transport error. The isolated rerun passed cleanly and is the accepted result. A bare `pytest -q` attempt used unsupported macOS Python 3.9 and was rejected before collection; the accepted ledger result is from the locked `uv` environment above.

## Browser evidence

- Desktop canonicalization, visible filter/comparison/sort/model-sheet restoration, and reload: passed.
- Native Back and Forward restored exact `q=alpha` and `q=beta` URLs and visible search values: passed.
- Native malformed `model` plus `benchmark` input canonicalized to `?v=1` with no sheet open: passed.
- Supplemental native 425 by 812 preset: passed. The sheet fit, visible text did not overlap or clip, and the close control worked. Closing removed only the `model` query parameter. This is not a substitute for the exact viewport below.
- Exact manual 390 by 844: unavailable because the test surface did not expose that exact custom viewport. The exact automated 390 by 844 browser assertion passed, but it is not labeled as manual evidence.

Screenshots were temporary test artifacts and were not committed.

## Scope and remaining gate

No router, storage, analytics, network request, source capture, credential operation, release authorization, deployment, paid operation, or production check was added or performed.

P11 implementation is accepted locally. Its plan lane remains acceptance-partial until exact-head GitHub Verify passes and the exact native 390 by 844 visual limitation is either resolved or explicitly accepted by the owner. H2 through H6 remain unsatisfied and production is not ready.
