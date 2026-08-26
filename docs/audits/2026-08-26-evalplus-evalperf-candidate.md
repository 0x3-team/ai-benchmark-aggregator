# EvalPlus EvalPerf bounded adapter candidate

**Status:** fixture-only engineering preparation on 2026-08-26. This candidate
is **not certified, capture ineligible, and publication ineligible**. It is not
a source-revision decision, authorization to fetch, snapshot, create a claim,
use a transport, write a database record, or publish an Official artifact.

## Candidate boundary

The first-party `evalplus/evalplus.github.io` repository identifies Apache-2.0
at its root. The proposed source shape is one immutable
`results/evalperf/*_evalperf_results.brief.json` file per result, whose
top-level summary can include source-reported `pass@1` and evaluation
configuration. Individual source files can also contain or be adjacent to
model-output/profiling material. That material is outside the ledger boundary:
the candidate adapter reads only configured top-level scalar summary scores,
the exact model label, and configured scalar evaluation fields. It neither
opens per-task/profile values nor calculates a task aggregate, win rate, DPS,
or any substitute score.

The checked-in fixture is deliberately generated as a small summary/configuration
shape and contains no model-output code, solution text, or profile payload. It
tests parser and exact-lexeme behavior only; it is not a copied source artifact
and does not demonstrate that every field in a real file has been reviewed.

## Single-file accounting and known coverage gap

The adapter accepts an explicit list of top-level summary score fields and
emits exactly one candidate observation for each configured field from one
brief-result file. It fail-closes a malformed root, duplicate JSON keys,
missing/null configuration or score values, nonnumeric/non-finite values,
duplicate configured score-field bindings, and payloads above its 256 KiB local
fixture bound. Typed `json_path_v1` evidence points to the one top-level record
and names the exact model, score, and configuration fields; replay re-resolves
those source lexemes without normalization.

This is not complete EvalPerf coverage. Broad use would require an immutable
multi-file manifest with an exact file denominator, revision binding, per-file
byte/schema limits, duplicate identity rules across files, and atomic snapshot
and failure accounting. None exists in this candidate, so it must not infer
coverage from a glob, crawl the directory, assemble result files, or represent
one file as a leaderboard-wide result set.

## Remaining blockers

1. An owner-reviewed immutable repository revision, result-file inventory,
   schema fingerprint, and source-specific manifest contract are absent.
2. Apache-2.0 at the repository root has not been recorded as a governed
   result-data reuse, display, attribution, retention, or correction decision.
3. Exact `pass@1`, any additional top-level score, and evaluation-config
   semantics have no approved benchmark/dimension mapping. The candidate does
   not treat a source-reported summary as authorization to calculate another
   metric.
4. Model labels remain raw and unresolved; the fixture adapter emits no model
   entity mapping and marks observations `needs_review`.
5. No source revision decision, safe-fetch receipt, snapshot, claim review,
   publication decision, or REL-05 release authorization exists.

The source registry and P4 candidate package are intentionally unchanged. The
registered parser cannot fetch and requires explicit `test_fixture_only` mode,
so this preparation does not activate any source or transport path.
