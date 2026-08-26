---
name: official-source-ingestion
description: Use when discovering, certifying, fetching, parsing, or preparing official benchmark sources for the ledger. Prefer structured primary sources and keep unsafe revisions quarantined.
---

# Official source ingestion

Use this skill when adding or updating source adapters, discovery targets, snapshots, or extraction code.

## Workflow

1. Identify the official publisher, source revision, access method, and allowed dimensions.
2. Prefer an official API or structured file before HTML scraping.
3. Capture an immutable snapshot before extraction and record its hash and revision evidence.
4. Certify the exact revision before writing any claim.
5. Resolve evidence locations against the immutable snapshot, not a mutable live page.
6. Quarantine mock, fallback, derived, uncertified, non-finite, nonnumeric, or unapproved data.
7. Keep uncertain identities unresolved and create a review item.

Never ingest articles, newsletters, vendor blogs, or social posts into the official result ledger.

## Verification

- Add or update adapter fixtures for every supported source shape.
- Test unsafe revisions, malformed scores, duplicate ingestion, and unresolved identity paths.
- Run `cd ledger && pytest -q` and report the exact source snapshot and evidence checks performed.
