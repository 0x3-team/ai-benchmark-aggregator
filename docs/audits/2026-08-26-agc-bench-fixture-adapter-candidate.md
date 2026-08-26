# AGC-Bench fixture-adapter candidate

**Status:** fixture-only, inactive, not certified, capture-ineligible, and
publication-ineligible. This note records a bounded parser seam only. It is
not a source-revision decision, source registration, fetch receipt, snapshot,
claim, database action, transport authorization, or publication input.

## Candidate input and terms lead

The proposed first-party source is the Hugging Face dataset
`agcbench-2026/AGC-Bench`. The requested candidate input identifies
`LICENSE-DATA` as explicitly applying CC BY 4.0 to `release_data/` score
tables. That supplied terms lead is useful for a later owner review, but this
fixture-only work did not fetch it, preserve it as a snapshot, or turn it into
a reuse, attribution, retention, or publication decision.

## Bounded parser contract

`AGCBenchAdapter` accepts only generated UTF-8 CSV fixture bytes while its
source is `inactive` and has `mode: fixture_only`. It has no network path and
the ingestion runner rejects it if a production source were ever admitted.
The fixture configuration must declare byte and row ceilings at or below the
adapter's hard caps, plus four distinct source columns: model, benchmark or
dataset, metric, and score.

Two row shapes are deliberately narrow:

1. `model_dataset_scores` stores the reported dataset cell as
   `benchmark_raw`, the reported metric cell as `metric_raw`, and the score
   cell verbatim as `score_raw`.
2. `headline_leaderboard` requires reported benchmark and metric cells too;
   a source-reported composite remains the metric's exact reported label. The
   adapter does not derive a composite, z-score, rank, average, or substitute
   a value from another column.

Every candidate record uses a `csv_cell_v1` locator binding model, benchmark,
metric, and score fields at one CSV row. Fixture validation re-resolves those
four raw values. Empty/malformed rows, duplicate model/benchmark/metric
identities, nonnumeric or non-finite lexemes, missing columns, and byte/row
bound failures reject the entire local batch before a partial result escapes.
Unresolved model identity stays null; no matching or identity promotion occurs
in this adapter.

## Open certification gates

Before any future source registration or production adapter change, an owner
must review the exact immutable revision and actual CSV schema, certify the
`LICENSE-DATA` applicability and attribution obligations, choose governed raw
dimension meanings, bind an approved source/final URL and fetch limits, and
create the required append-only source-revision decision. If the real tables
lack direct cells for a required raw dimension, this candidate must remain
inactive rather than infer or coerce one.
