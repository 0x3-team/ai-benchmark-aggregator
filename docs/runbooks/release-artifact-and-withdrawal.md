# Release artifact and withdrawal runbook

**Status:** Procedure design — pure candidate builder exists; artifact persistence, authorization, and Official publication are disabled

## State taxonomy

| State | May appear in public frontend? | Meaning |
| --- | --- | --- |
| Awaiting publication | Yes | The shipped immutable empty state; no models, benchmarks, or scores are public. |
| Candidate projection (LDR-08) | No | Offline read model only; not a release artifact. |
| Legacy inventory (LDR-09) | No | Read-only reconciliation report; not a decision or data source. |
| Approved immutable artifact | Not until REL-05 | A builder/release-control output awaiting governed frontend authorization. |
| Published Official release | Only after REL-05 | One exact artifact ID/digest, policy, decision, timestamp, and frontend release. |
| Withdrawn | Yes, when implemented | Explicit empty/unavailable public state; it must not continue serving the withdrawn artifact or fall back to any fixture. |

## Preconditions for a future build

1. The input is only the LDR-08 eligible projection after full six-dimension
   identity and duplicate/conflict checks.
2. Each selected claim retains capture-time source certification, immutable
   snapshot provenance, all-pass validation, effective review, and effective
   approved publication decisions.
3. The builder identity, artifact retention/store, public field allowlist,
   signing/attestation choice, review authority, cache/withdrawal SLA, and
   rollback owner are recorded in the launch charter.
4. The artifact calculation is deterministic and records canonical digest,
   artifact ID, policy version, approval decision, timestamp, source manifest,
   and frontend commit/build identity.

The current `ledger.app.export.official_release` candidate is deliberately
short of these operational preconditions. It has no output path or durable
record writer and requires explicit public display/evidence metadata because
the eligible-feed contract does not own those fields. Its output is not
authorized unless a separately governed external record exactly pins it; no
such record or v2 artifact is tracked.

## Prohibited shortcuts

- Do not package an ignored `export.from-ledger.json`, candidate projection,
  legacy report, fixture, sample, or operator-local export into `src/data`.
- Do not make the dormant v2 parser or Official selection path live because a
  file happens to validate or a digest happens to match.
- Do not put raw snapshots, protected source content, credentials, database
  identifiers, or runner telemetry in the public artifact.
- Do not correct/revoke a release by rewriting claims, deleting snapshots, or
  replacing bytes at an existing artifact address.

## Future release protocol

1. Build one immutable artifact from an approved eligible projection.
2. Verify its canonical digest in a clean checkout and package the exact bytes
   with the static frontend build.
3. Append a release approval decision that pins artifact ID, digest, policy,
   timestamp, signer, and frontend build.
4. Complete a non-production rehearsal including unavailable state, static
   rollback, cache behavior, source/evidence re-resolution, and browser checks.
5. REL-05 may then authorize one atomic frontend selection. Any other artifact
   must be rejected.

## Future withdrawal protocol

1. Append a revocation/withdrawal decision naming the exact artifact and reason.
2. Stop promotion and invalidate/replace the public static release according to
   the approved cache SLA; publish an explicit unavailable/withdrawn state.
3. Preserve old artifact and decision history privately for audit; do not serve
   it as the current release.
4. Record detection time, action time, cache evidence, affected frontend build,
   owner, correction path, and follow-up source/review decision.

Until those controls exist, the only valid public behavior is the immutable
empty awaiting-publication state. After a withdrawal, that empty/unavailable
state also remains the fail-closed public behavior until a different governed
artifact receives a new release authorization.
