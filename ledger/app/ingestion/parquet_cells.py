"""Typed ``parquet_cell_v1`` evidence resolution against immutable snapshot bytes.

A Parquet evidence locator binds one cell grid exactly: ``row_group`` and
``row_index`` select the record, and the contract's field map selects source
columns.  Re-resolution must return the identical raw lexeme from the
immutable snapshot, so every supported cell is rendered through one
deterministic lexical policy:

- string cells render verbatim;
- integer cells render as canonical decimal text;
- float cells render with Python's shortest-round-trip ``repr`` (an exact,
  platform-stable rendering of the stored IEEE-754 value; non-finite cells
  render as ``nan``/``inf``/``-inf`` text so admission rejects them as
  nonnumeric — nothing is ever coerced into admissibility);
- decimal cells render with their exact preserved scale;
- null cells and unsupported column types (temporal, binary, nested, and
  boolean in v1) are absent from the rendered record, so a referenced
  field fails closed instead of inventing a lexeme.

This module performs no file, network, database, clock, or environment
access; callers supply snapshot bytes.
"""

from __future__ import annotations

from decimal import Decimal
import io
from typing import Any, Iterator

import pyarrow.parquet as pq


class ParquetCellError(ValueError):
    """Raised when Parquet evidence bytes cannot be read deterministically."""


def render_cell_lexeme(value: Any) -> str | None:
    """Render one supported Parquet cell as its exact raw lexeme.

    ``None`` marks nulls and unsupported types; the referenced field then
    fails closed at evidence comparison rather than being coerced.
    """

    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, Decimal):
        return str(value)
    return None


def _open(raw_bytes: bytes) -> pq.ParquetFile | None:
    try:
        return pq.ParquetFile(io.BytesIO(raw_bytes))
    except Exception:
        return None


def parquet_row_group_rows(raw_bytes: bytes) -> tuple[tuple[int, ...] | None, str | None]:
    """Return the exact row count of every row group, or a stable error."""

    parquet_file = _open(raw_bytes)
    if parquet_file is None:
        return None, "EVIDENCE_LOCATOR_INVALID"
    counts: list[int] = []
    for group_index in range(parquet_file.num_row_groups):
        rows = parquet_file.metadata.row_group(group_index).num_rows
        if rows is None or rows < 0:
            return None, "EVIDENCE_LOCATOR_INVALID"
        counts.append(rows)
    return tuple(counts), None


def read_parquet_record(
    raw_bytes: bytes, *, row_group: object, row_index: object
) -> tuple[dict[str, str] | None, str | None]:
    """Resolve one record's rendered cells, mirroring the CSV/JSON evidence seam."""

    if type(row_group) is not int or row_group < 0:
        return None, "EVIDENCE_LOCATOR_INVALID"
    if type(row_index) is not int or row_index < 0:
        return None, "EVIDENCE_LOCATOR_INVALID"
    parquet_file = _open(raw_bytes)
    if parquet_file is None:
        return None, "EVIDENCE_LOCATOR_INVALID"
    if row_group >= parquet_file.num_row_groups:
        return None, "EVIDENCE_NOT_FOUND"
    try:
        table = parquet_file.read_row_group(row_group)
    except Exception:
        return None, "EVIDENCE_LOCATOR_INVALID"
    if row_index >= table.num_rows:
        return None, "EVIDENCE_NOT_FOUND"
    row = table.slice(row_index, 1).to_pylist()[0]
    record: dict[str, str] = {}
    for column, value in row.items():
        lexeme = render_cell_lexeme(value)
        if lexeme is not None:
            record[column] = lexeme
    return record, None


def iter_parquet_records(
    raw_bytes: bytes,
) -> Iterator[tuple[int, int, dict[str, str]]]:
    """Yield ``(row_group, row_index, rendered record)`` for complete accounting.

    Raises :class:`ParquetCellError` on malformed bytes so batch accounting
    fails closed rather than silently dropping rows.
    """

    parquet_file = _open(raw_bytes)
    if parquet_file is None:
        raise ParquetCellError("Parquet evidence bytes are not a readable Parquet file")
    for group_index in range(parquet_file.num_row_groups):
        try:
            table = parquet_file.read_row_group(group_index)
        except Exception as exc:
            raise ParquetCellError(
                f"Parquet row group {group_index} cannot be read"
            ) from exc
        for row_index, row in enumerate(table.to_pylist()):
            record: dict[str, str] = {}
            for column, value in row.items():
                lexeme = render_cell_lexeme(value)
                if lexeme is not None:
                    record[column] = lexeme
            yield group_index, row_index, record


__all__ = [
    "ParquetCellError",
    "iter_parquet_records",
    "parquet_row_group_rows",
    "read_parquet_record",
    "render_cell_lexeme",
]
