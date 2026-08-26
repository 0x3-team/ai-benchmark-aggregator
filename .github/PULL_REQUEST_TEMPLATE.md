## Trust-boundary reminder

Demo values are synthetic. Candidate projections, legacy reports, test fixtures,
samples, ignored local exports, and source-fetch output are never public Official
data. Official mode remains unavailable unless a separately governed REL-05
authorization pins one release artifact and digest.

## Summary and user impact

<!-- What changed, why, and which launch track/status it affects. -->

## Trust surface

- [ ] UI only — no dataset or Official-mode behavior
- [ ] Demo/unavailable status or frontend containment
- [ ] Ledger schema, source, fetch, claim, review, or publication boundary
- [ ] CI, release process, security, or documentation
- [ ] Governed Official release work (requires linked approval)

## Containment checks

- [ ] I did not make candidate, legacy, sample, ignored local-export, or fixture data a frontend input.
- [ ] I did not enable Official mode, live ingestion, public export, benchmark execution, or production secrets in CI.
- [ ] I did not overwrite claims/snapshots or use reset, delete, truncate, downgrade, or destructive migration recovery.
- [ ] If this touches score display, it preserves DatasetProvider/getValue and truthful no-data behavior.

## Validation evidence

<!-- List exact commands, fixtures, browser/manual checks, and their result. Do not claim unrun environments. -->

## Data/governance impact

<!-- Name source revision, policy/decision IDs, artifact digest, review authority, or say “not applicable”. -->

## Migration, release, or rollback impact

<!-- State “not applicable” or link copy-only rehearsal/release/withdrawal evidence. Never propose downgrade as recovery. -->

## Documentation

- [ ] I updated relevant README, ADR, runbook, and/or plan documentation.
- [ ] No documentation change is needed; rationale is included above.
