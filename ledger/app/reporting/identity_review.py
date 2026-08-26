"""Deterministic, read-only CSV projection of the identity review queue.

This report is decision support only.  It deliberately projects one already
bounded :class:`ReviewQueuePage`; it does not inspect evidence, resolve model
aliases, or write any ledger row.
"""

from __future__ import annotations

import base64
import csv
import hashlib
from io import StringIO
import unicodedata

from app.db.repositories import ReviewQueueItem, ReviewQueuePage


IDENTITY_REVIEW_CSV_COLUMNS = (
    "record_type",
    "claim_id",
    "official_source_id",
    "source_snapshot_id",
    "source_revision_decision_id",
    "benchmark_id",
    "captured_model_entity_id",
    "effective_model_entity_id",
    "effective_decision_id",
    "capture_status",
    "queue_reason_codes",
    "model_raw_b64",
    "model_raw_sha256",
    "model_raw_display",
    "next_cursor",
    "exhausted",
    "scanned",
    "emitted",
)


def _visible_text(value: str) -> str:
    """Return a human display projection with no terminal/control bytes."""

    out: list[str] = []
    for character in value:
        code = ord(character)
        if character == "\\":
            out.append("\\\\")
        elif character == "\n":
            out.append("\\n")
        elif character == "\r":
            out.append("\\r")
        elif character == "\t":
            out.append("\\t")
        elif character == "\b":
            out.append("\\b")
        elif character == "\f":
            out.append("\\f")
        elif unicodedata.category(character) in {"Cc", "Cf"}:
            if code <= 0xFF:
                out.append(f"\\x{code:02x}")
            elif code <= 0xFFFF:
                out.append(f"\\u{code:04x}")
            else:
                out.append(f"\\U{code:08x}")
        else:
            out.append(character)
    return "".join(out)


def _reason_codes(item: ReviewQueueItem) -> str:
    """Map queue semantics to a stable, intentionally closed code set."""

    claim = item.claim
    projection = item.projection
    codes: list[str] = []
    if projection.chain_error is not None:
        codes.append("REVIEW_CHAIN_INVALID")
    elif projection.model_entity_id is None:
        codes.append("MODEL_IDENTITY_UNRESOLVED")
    elif claim.model_entity_id is None:
        codes.append("MODEL_IDENTITY_REVIEWED")
    if claim.capture_status == "needs_review":
        codes.append("CAPTURE_NEEDS_REVIEW")
    return ";".join(codes)


def _blank_row(record_type: str) -> dict[str, str]:
    row = {column: "" for column in IDENTITY_REVIEW_CSV_COLUMNS}
    row["record_type"] = record_type
    return row


def _claim_row(item: ReviewQueueItem) -> dict[str, str]:
    claim = item.claim
    projection = item.projection
    raw = claim.model_raw.encode("utf-8")
    row = _blank_row("claim")
    row.update(
        {
            "claim_id": claim.id,
            "official_source_id": claim.official_source_id,
            "source_snapshot_id": claim.source_snapshot_id,
            "source_revision_decision_id": claim.source_revision_decision_id or "",
            "benchmark_id": projection.benchmark_id or claim.benchmark_id or "",
            "captured_model_entity_id": claim.model_entity_id or "",
            "effective_model_entity_id": projection.model_entity_id or "",
            "effective_decision_id": projection.effective_decision_id or "",
            "capture_status": claim.capture_status,
            "queue_reason_codes": _reason_codes(item),
            "model_raw_b64": base64.b64encode(raw).decode("ascii"),
            "model_raw_sha256": hashlib.sha256(raw).hexdigest(),
            # The prefix is a display-type marker.  It also prevents a value
            # beginning with =, +, -, or @ from becoming a spreadsheet formula.
            "model_raw_display": "text:" + _visible_text(claim.model_raw),
        }
    )
    return row


def build_identity_review_csv(page: ReviewQueuePage) -> bytes:
    """Build the complete deterministic UTF-8 CSV payload before any output."""

    output = StringIO(newline="")
    writer = csv.DictWriter(
        output,
        fieldnames=IDENTITY_REVIEW_CSV_COLUMNS,
        lineterminator="\r\n",
        quoting=csv.QUOTE_ALL,
        extrasaction="raise",
    )
    writer.writeheader()
    metadata = _blank_row("page")
    metadata.update(
        {
            "next_cursor": page.next_cursor or "",
            "exhausted": "true" if page.exhausted else "false",
            "scanned": str(page.scanned),
            "emitted": str(len(page.items)),
        }
    )
    writer.writerow(metadata)
    for item in page.items:
        writer.writerow(_claim_row(item))
    return output.getvalue().encode("utf-8")


__all__ = ["IDENTITY_REVIEW_CSV_COLUMNS", "build_identity_review_csv"]
