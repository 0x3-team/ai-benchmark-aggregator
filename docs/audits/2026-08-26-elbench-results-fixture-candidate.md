# ELBench results fixture-only candidate

**Status:** inactive, fixture-candidate only, not certified, capture
ineligible, and publication ineligible. This note records reviewed read-only
research and a local parser rehearsal. It is not a source decision, live fetch
receipt, source snapshot, claim, transport authorization, or release artifact.

## Reviewed artifact facts

- **Publisher/repository:** first-party Hugging Face dataset
  `ZeroLoss-Lab/ELBench-results`, whose result-only repository declares CC BY
  4.0. Attribution, display, modification-notice, owner, and certification
  decisions remain absent.
- **Immutable candidate revision:**
  `86ca44d147899fdb7ef40448c0cae50334aa10b4`.
- **Candidate artifact URL:**
  `https://huggingface.co/datasets/ZeroLoss-Lab/ELBench-results/resolve/86ca44d147899fdb7ef40448c0cae50334aa10b4/audit-judge-integrity/leaderboard_FINAL.json`.
- **Read-only observation:** 1,887 bytes; SHA-256
  `e183b908b030fb1e7aea5b413264a7e7d01897103af7a3e55e0860e3bb8dda09`;
  final response media type `text/plain; charset=utf-8` after the Hugging Face
  cache redirect. These observations are not a retained ledger snapshot or a
  safe-fetch receipt.
- **Aggregate-only schema:** root keys are exactly `rows`, `old_rank`, and
  `new_rank`; the reviewed revision has nine rows. Every row has exactly
  `model`, `gen`, `saf`, `bas`, `high`, `ovr_old`, and `ovr_new`.

The parser accepts only an inactive source configuration with
`mode: fixture_candidate_only` and a bounded expected-row count no greater
than nine. It rejects root or row additions, including withheld per-sample
content. It does not own a fetch path, and the inherited adapter fetch method
continues to require the central fetch plan.

## Candidate extraction semantics

Each aggregate field is emitted verbatim with `json_path_v1` evidence pointing
to its exact `$.rows[index]` record. Numeric JSON lexemes are decoded with the
ledger's exact-lexeme decoder and must be finite decimal values; no score is
reformatted, averaged, bootstrapped, inferred, or recalculated.

| Source field | Candidate metric label | Handling |
| --- | --- | --- |
| `gen` | General Capability | Direct source-reported score |
| `saf` | Safety & Trustworthiness | Direct source-reported score |
| `bas` | Basic Education | Direct source-reported score |
| `high` | High-Level Educational Cultivation | Direct source-reported score |
| `ovr_old` | Historical Overall (source-reported) | Direct historical score, kept distinct from current corrected overall |
| `ovr_new` | Corrected Overall | Direct corrected source-reported overall |

`old_rank` and `new_rank` are mandatory aggregate context maps whose keys must
exactly match the row model names, but they never emit score candidates.
Identity is retained exactly in `model_raw`; the adapter assigns no
`model_entity_id`, so later admission would leave every identity unresolved
until governed review.

The reduced fixture in `ledger/tests/fixtures/elbench_results_aggregate_fixture.json`
contains one aggregate row only, because it is a local source-shaped parser
fixture rather than a copied source artifact. Its score lexemes reproduce the
reviewed representative row. Its one-entry rank maps are generated structural
context for the reduced shape and are not asserted to be source rank values.
It contains no per-sample or withheld material and must never be treated as a
snapshot, checksum match, or complete nine-row artifact.

## Fixture coverage and remaining blockers

Dedicated tests prove registration without activation, strict fixture gating,
typed evidence replay, exact numeric lexeme preservation, duplicate-model
rejection, null/non-finite/malformed score quarantine, root and row-shape
rejection, complete accounting, rank-context exclusion, row and byte bounds,
and unresolved model identity.

This preparation does not resolve the observed `text/plain` final media type
against a future source contract, the redirect/final-URL policy, complete
nine-row immutable-fixture rehearsal, attribution and display obligations,
named source/governance owner, dimension approval, source-revision
certification, safe transport, snapshot, claim admission, review, or
publication. The adapter and fixture must remain inactive until those separate
decisions exist.
