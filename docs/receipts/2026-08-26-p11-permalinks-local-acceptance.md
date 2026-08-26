# P11 permalink local acceptance receipt

Recorded: 2026-08-26T16:25:47Z

Branch: `feat/p11-permalinks`

Base: `d35b0ef4211b0ee03b53891762424bdef9e4782b`

Build source digest: `2521e78951447d4868e2a4c1fae4f47fc464828e3a879e82fda7a1f70663b218`

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
- `npm test`: 21 files and 118 tests passed.
- Focused App and codec run: 26 tests passed.
- `npm run test:permalinks`: passed canonical restore, reload, stale-ID removal, invalid dual-sheet rejection, Back/Forward restoration, and exact 390 by 844 overflow and sheet-width assertions.
- `npm run test:mobile-overflow`: passed at 390 pixels (`documentScrollWidth=390`, `documentClientWidth=390`).
- `npm run build`: passed; 2,878 modules transformed.
- `npm run verify:build-provenance`: passed, including 25 adversarial tests.
- `npm run verify:pages-static`: passed, including 11 tests.
- `npm run verify:pages-workflows`: passed, including 18 tests.
- `npm run verify:bundle-budget`: passed (`eagerJs=497407`, `totalJs=1227527`) with 52 tests.
- `npm run verify:official-artifact`: passed for the governed unavailable containment artifact, with 8 tests.
- `cd ledger && uv run --locked --extra dev pytest -q`: 1,672 passed and 14 skipped.
- Independent GPT-5.6 Luna high-reasoning engineering review: `accept`; no material correctness finding.

The first concurrent full frontend run passed all 118 assertions but reported one Vitest worker teardown transport error. The isolated rerun passed cleanly and is the accepted result. A bare `pytest -q` attempt used unsupported macOS Python 3.9 and was rejected before collection; the accepted ledger result is from the locked `uv` environment above.

## Native browser evidence

Computer Use used GPT-5.6 Sol, low reasoning, Fast tier, through the Orca native browser only.

- Desktop canonicalization, visible filter/comparison/sort/model-sheet restoration, and reload: passed.
- Native Back and Forward restored exact `q=alpha` and `q=beta` URLs and visible search values: passed.
- Native malformed `model` plus `benchmark` input canonicalized to `?v=1` with no sheet open: passed.
- Supplemental native 425 by 812 preset: passed. The sheet fit, visible text did not overlap or clip, and the close control worked. Closing removed only the `model` query parameter. This is not a substitute for the exact viewport below.
- Exact native 390 by 844: blocked. Orca's Android emulator timed out while booting, and the native browser exposed fixed presets but no 390 by 844 or custom viewport. The exact automated 390 by 844 browser assertion passed, but it is not labeled as native evidence.

Native screenshots were produced in the Computer Use service's temporary storage. They are not committed artifacts and can expire.

## Scope and remaining gate

No router, storage, analytics, network request, source capture, credential operation, release authorization, deployment, paid operation, or production check was added or performed.

P11 implementation is accepted locally. Its plan lane remains acceptance-partial until exact-head GitHub Verify passes and the exact native 390 by 844 visual limitation is either resolved or explicitly accepted by the owner. H2 through H6 remain unsatisfied and production is not ready.
