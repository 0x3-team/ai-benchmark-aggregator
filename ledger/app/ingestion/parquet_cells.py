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

Binding: every read path that accepts both ``raw_bytes`` and a resolver must
fail closed when the resolver is not bound to those exact immutable bytes.
A resolver records the exact ``bytes`` object it was built from; the same
object is accepted by an O(1) identity fast path (no re-hash), and any
*equal-but-distinct* ``bytes`` object is accepted only after a full sha256
digest comparison.  Object identity alone is never authoritative, and a
resolver bound to different bytes is rejected.

Lifetime: the resolver is intentionally immutable (its decoded cells) and
provides an explicit ``close()`` / context-manager lifecycle.  ``close()``
drops the resolver's reference to the decoded snapshot so the decoded form
can be reclaimed; it does not pretend to free the caller's own ``raw_bytes``
reference.  There is no process-global cache.
"""

from __future__ import annotations

from decimal import Decimal
import hashlib
import io
from types import MappingProxyType
from typing import Any, Iterator, Mapping

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


# ---------------------------------------------------------------------------
# Conservative metadata-derived resource caps and batch bound.
#
# A hostile Parquet footer can claim a gigantic table (huge row-group counts,
# row counts, column counts, or a decompressed payload far larger than the
# on-disk bytes via a codec like GZIP).  These caps are enforced from *footer
# metadata only* — before any ``iter_batches``/``to_pylist`` call that would
# allocate the claimed grid — so a hostile file is rejected without ever
# materializing it.  They are deliberately generous relative to the current
# fixtures (a 10k-row, 3-column evidence snapshot) and to the bounded
# ``parquet_cell_v1`` single-cell evidence contract, and they are *not* a
# tunable-per-source framework: the runner does not thread new configuration
# through; the limits are fixed contract constants here.
#
# The row/cell ceilings are deliberate *safety* ceilings, not heap guarantees.
# They are chosen *conservative* against Python amplification of decoding, not
# as a claim about Parquet-encoded size: every decoded row becomes a dict of
# rendered string lexemes (plus, in the adapter path, a ``ResultClaimInput`` and
# an entry in a duplicate-tracking set per dimension).  They are set tight
# enough to reject hostile multi-megabyte amplification, yet remain ~10x the row
# bound and >16x the cell bound of the current 10k-row x 3-column fixture
# (100,000 rows / 500,000 cells caps versus 10,000 rows / 30,000 cells used).
# ``MAX_PARQUET_DECOMPRESSED_BYTES`` is a metadata-derived *estimate* of
# worst-case codec expansion (the sum of each column chunk's
# ``total_uncompressed_size``): it does *not* guarantee the decode never
# allocates transiently beyond it during codec expansion of a single batch.
# The consumption of the decoded grid is bounded separately by
# ``MAX_PARQUET_CELLS``, and metadata size alone is not a statement about the
# Python heap footprint of materializing the claimed grid.
# ---------------------------------------------------------------------------
MAX_PARQUET_ROW_GROUPS = 128
MAX_PARQUET_ROWS = 100_000
MAX_PARQUET_COLUMNS = 32
MAX_PARQUET_CELLS = 500_000
MAX_PARQUET_DECOMPRESSED_BYTES = 128 * 1024 * 1024
# Fixed, documented maximum number of rows decoded per ``iter_batches`` batch.
# ``iter_batches`` slices each row group into batches of at most this many
# rows, so only this many records are ever handed to ``to_pylist`` at a time
# and ``row_index`` stays exact across batch boundaries.  It is deliberately
# modest and is *not* tunable per source.
MAX_PARQUET_BATCH_SIZE = 8_192


def _metadata_limit_reason(
    *,
    row_groups: int,
    columns: int,
    rows: int,
    cells: int,
    decompressed_bytes: int,
) -> str | None:
    """Return a stable reason the claimed parquet grid exceeds a cap, else ``None``.

    ``cells`` is the metadata-derived ``rows * columns`` product and
    ``decompressed_bytes`` is the sum of each column chunk's
    ``total_uncompressed_size`` (a metadata value, not a decode).  This is a
    pure helper so tests can exercise hostile cardinalities as plain integers
    with no Parquet allocation at all.  Negative or non-scalar values are
    rejected by the strict validation path before ever reaching here.
    """
    if row_groups > MAX_PARQUET_ROW_GROUPS:
        return "row_groups"
    if columns > MAX_PARQUET_COLUMNS:
        return "columns"
    if rows > MAX_PARQUET_ROWS:
        return "rows"
    if cells > MAX_PARQUET_CELLS:
        return "cells"
    if decompressed_bytes > MAX_PARQUET_DECOMPRESSED_BYTES:
        return "decompressed_size"
    return None


class ParquetMetadataLimitError(ParquetCellError):
    """The snapshot's *claimed* metadata exceeds a fixed resource ceiling.

    Raised during resolver construction, before any row decode, so a hostile
    high-cardinality footer is rejected without allocating the claimed table.
    ``reason`` is a stable token.  The scalar cap rejections emit the base
    reason token from :func:`_metadata_limit_reason`
    (``row_groups``/``columns``/``rows``/``cells``/``decompressed_size``), while
    the strict non-negative-integer validation path emits a
    ``metadata_<kind>`` prefixed token (``metadata_row_groups``,
    ``metadata_columns``, ``metadata_rows``, ``metadata_decompressed_size``).
    Both families are stable consumer-safe tokens.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(f"Parquet snapshot metadata exceeds the {reason} limit")
        self.reason = reason


def _open(raw_bytes: bytes) -> pq.ParquetFile | None:
    try:
        return pq.ParquetFile(io.BytesIO(raw_bytes))
    except Exception:
        return None


def _require_nonnegative_int(value: object, what: str) -> int:
    """Return ``value`` if it is a non-negative ``int``, else fail closed.

    This is deliberately strict: negative or non-integer metadata is never
    silently coerced (no ``or 0``, no ``abs``), because a negative value must
    never be allowed to *reduce* a running total and misrepresent the claimed
    grid as smaller than it really is.
    """
    if type(value) is not int or value < 0:
        raise ParquetMetadataLimitError(f"metadata_{what}")
    return value


def _enforce_metadata_limits(parquet_file: pq.ParquetFile) -> None:
    """Reject a metadata-claimed grid that exceeds the fixed resource caps.

    Called during resolver construction *before* any row decode.  Every
    denominator is read from the footer metadata: row-group count,
    ``num_rows`` per row group, column count from the shared schema, and the
    sum of column-chunk ``total_uncompressed_size`` values as the
    decompressed-size estimate.

    The scalar row-group and column ceilings are enforced from the top-level
    footer *before* any row-group is accessed, so a hostile ``num_row_groups``
    cannot trigger an unbounded ``range`` loop before rejection.  All metadata
    values are validated as strict non-negative integers (the file schema
    column count, each group's ``num_rows``, each group's ``num_columns``, and
    every column chunk's ``total_uncompressed_size``); invalid values fail
    closed with a stable :class:`ParquetMetadataLimitError` rather than being
    coerced.
    """

    # Pure scalar caps first — no row-group access, no iteration over a hostile
    # count, so a bad claim is rejected before any ``range(row_groups)`` work.
    row_groups = _require_nonnegative_int(parquet_file.num_row_groups, "row_groups")
    columns = _require_nonnegative_int(
        parquet_file.metadata.num_columns, "columns"
    )
    # A zero-column table cannot carry separable evidence; reject early.
    if columns == 0:
        raise ParquetMetadataLimitError("columns")
    reason = _metadata_limit_reason(
        row_groups=row_groups,
        columns=columns,
        rows=0,
        cells=0,
        decompressed_bytes=0,
    )
    if reason is not None:
        raise ParquetMetadataLimitError(reason)

    total_rows = 0
    cells = 0
    decompressed_bytes = 0
    for group_index in _range_bounded(row_groups):
        group = parquet_file.metadata.row_group(group_index)
        rows = _require_nonnegative_int(group.num_rows, "rows")
        # An ill-typed or inconsistent column count is rejected rather than
        # healing the denominator.
        group_columns = _require_nonnegative_int(group.num_columns, "columns")
        if group_columns != columns:
            raise ParquetMetadataLimitError("columns")
        total_rows += rows
        cells += rows * columns
        for column_index in range(group_columns):
            uncompressed = _require_nonnegative_int(
                group.column(column_index).total_uncompressed_size,
                "decompressed_size",
            )
            decompressed_bytes += uncompressed

    reason = _metadata_limit_reason(
        row_groups=row_groups,
        columns=columns,
        rows=total_rows,
        cells=cells,
        decompressed_bytes=decompressed_bytes,
    )
    if reason is not None:
        raise ParquetMetadataLimitError(reason)


def _range_bounded(count: int) -> range:
    """Return ``range(count)`` for a count already proved non-negative.

    This is a small seam so a load-bearing test can assert that a hostile
    ``num_row_groups`` never reaches ``range`` iteration before rejection: the
    scalar cap gate runs first and raises for any count above
    ``MAX_PARQUET_ROW_GROUPS``.
    """
    return range(count)


def build_snapshot_digest(raw_bytes: bytes) -> str:
    """Return the full sha256 hex digest of the immutable snapshot bytes.

    Used to bind a resolver to snapshot content instead of ``id(raw_bytes)``:
    the digest is stable, content-addressed, and independent of object
    identity, so two call sites holding equal bytes (even distinct buffer
    objects) resolve the same snapshot.
    """
    return hashlib.sha256(raw_bytes).hexdigest()


class ParquetEvidenceResolver:
    """Exactly-once decoding of one Parquet snapshot, with O(1) cell lookup.

    Construction opens the Parquet file a single time, records every row
    group's denominator, and decodes the shape into an immutable nested
    structure: ``groups[row_group][row_index]`` is a single direct index,
    never a linear scan over the whole snapshot.

    Binding: the resolver is constructed from exactly one ``raw_bytes``
    object and remembers that object plus its sha256 digest.  Pass either the
    same object (O(1) identity fast path) or any equal-but-distinct object
    (full-digest confirmation) — otherwise :meth:`verify` raises
    :class:`ParquetCellError` and every read path fails closed.

    Lifetime: decoded cells are immutable; ``close()`` / context-manager exit
    drops the resolver's references so the decoded snapshot can be reclaimed.
    There is no global cache.
    """

    def __init__(
        self,
        raw_bytes: bytes,
        *,
        _lookup_counter: Any | None = None,
    ) -> None:
        if not isinstance(raw_bytes, bytes):
            raise TypeError("Parquet evidence snapshot must be bytes.")
        parquet_file = _open(raw_bytes)
        if parquet_file is None:
            raise ParquetCellError(
                "Parquet evidence bytes are not a readable Parquet file"
            )
        counts: list[int] = []
        groups: list[tuple[Mapping[str, str], ...]] = []
        try:
            # Reject a hostile metadata-claimed grid *before* any row decode so
            # a high-cardinality footer never causes the claimed table to be
            # materialized.  This is metadata-only and bounded, and it also
            # validates every denominator's type/nonnegativity strictly.
            _enforce_metadata_limits(parquet_file)
            for group_index in range(parquet_file.num_row_groups):
                rows = _require_nonnegative_int(
                    parquet_file.metadata.row_group(group_index).num_rows, "rows"
                )
                counts.append(rows)
                record_cells = self._decode_group(parquet_file, group_index, rows)
                groups.append(tuple(record_cells))
        except ParquetCellError:
            raise
        except Exception as exc:
            raise ParquetCellError(
                f"Parquet row group cannot be read from snapshot"
            ) from exc
        finally:
            # The Parquet file handle is always released — on success, on
            # metadata-limit rejection, and on any decode exception.
            # In PyArrow 18 ``ParquetFile.close(force=False)`` skips closing
            # the underlying reader when the file was opened from caller-owned
            # in-memory bytes (``io.BytesIO``), not an OS path pyarrow owns.
            # ``force=True`` promptly releases that file-like reader (and the
            # caller-owned buffer it holds) on every exit.  This is prompt
            # explicit release, not a claim about when a garbage collector
            # would or would not eventually reclaim the snapshot's bytes.
            parquet_file.close(force=True)
        self._closed = False
        self._raw_bytes = raw_bytes
        self._digest = build_snapshot_digest(raw_bytes)
        self._row_group_rows = tuple(counts)
        self._groups = tuple(groups)
        self._lookup_counter = _lookup_counter

    @staticmethod
    def _decode_group(
        parquet_file: pq.ParquetFile,
        group_index: int,
        expected_rows: int,
    ) -> list[Mapping[str, str]]:
        """Decode exactly one row group through bounded ``iter_batches`` batches.

        ``iter_batches`` is used with ``use_threads=False``, which disables
        concurrent column decoding at this boundary for resource predictability.
        It never uses ``read_row_group``/``to_pylist`` on a whole group, so each
        ``RecordBatch`` handed to ``to_pylist`` contains at most
        ``MAX_PARQUET_BATCH_SIZE`` rows.  ``row_index`` is tracked across batch
        boundaries so the global index inside the row group stays exact
        regardless of where a batch boundary falls.

        Honest note: the per-batch cap bounds how many records a single
        ``to_pylist`` call converts at once.  The retained rendered grid still
        accumulates across the whole row group and is separately bounded by the
        metadata ``MAX_PARQUET_CELLS``; total peak allocation is not one batch.
        Codec internals may still attempt to expand an individual column
        chunk's compressed bytes when decoding a batch; the
        ``total_uncompressed_size``-derived cap bounds that estimate but does not
        guarantee a codec never allocates transiently beyond it.
        """
        record_cells: list[Mapping[str, str]] = []
        row_index = 0
        batch_size = MAX_PARQUET_BATCH_SIZE
        # ``use_threads=False`` disables concurrent column decoding at this
        # boundary; per PyArrow's documentation that is the effect of the flag.
        # It is a resource/concurrency control, not a guarantee of output
        # determinism across unrelated process/thread state.
        for batch in parquet_file.iter_batches(
            batch_size=batch_size,
            row_groups=[group_index],
            use_threads=False,
        ):
            # Guard the fixed cap: a batch must never exceed the documented
            # bound handed to ``iter_batches``.
            if batch.num_rows > batch_size:
                raise ParquetCellError(
                    f"Parquet batch of {batch.num_rows} rows exceeds the fixed "
                    f"{batch_size} limit"
                )
            for row in batch.to_pylist():
                rendered: dict[str, str] = {}
                for column, value in row.items():
                    lexeme = render_cell_lexeme(value)
                    if lexeme is not None:
                        rendered[column] = lexeme
                record_cells.append(MappingProxyType(rendered))
                row_index += 1
        if row_index != expected_rows:
            raise ParquetCellError(
                f"Parquet row group {group_index} decoded {row_index} rows "
                f"but metadata claims {expected_rows}"
            )
        return record_cells

    # --- identity / binding -------------------------------------------------

    @property
    def digest(self) -> str:
        """The sha256 digest this resolver is bound to."""
        return self._digest

    @property
    def row_group_rows(self) -> tuple[int, ...]:
        """Exact row count of every row group."""
        return self._row_group_rows

    def verify(self, raw_bytes: bytes) -> None:
        """Fail closed if ``raw_bytes`` is not the exact snapshot this resolver is bound to.

        The same object is accepted by an O(1) identity fast path.  An
        equal-but-distinct ``bytes`` object is accepted only after a full
        sha256 digest match (Python has no cheap structural equality for
        bytes, so a digest is required).  Anything else raises
        :class:`ParquetCellError`.
        """
        if self._closed:
            raise ParquetCellError("Parquet evidence resolver is closed.")
        if raw_bytes is self._raw_bytes:
            return  # same object: identity fast path, no re-hash
        if not isinstance(raw_bytes, bytes):
            raise TypeError("Parquet evidence snapshot must be bytes.")
        if build_snapshot_digest(raw_bytes) != self._digest:
            raise ParquetCellError(
                "Parquet evidence resolver is not bound to the supplied snapshot bytes"
            )

    # --- resolution --------------------------------------------------------

    def read(
        self, *, row_group: object, row_index: object
    ) -> tuple[Mapping[str, str] | None, str | None]:
        """Resolve one record's rendered cells via direct row-group/index lookup.

        Bounds are checked first; the returned record is an immutable Mapping.
        """
        if self._closed:
            raise ParquetCellError("Parquet evidence resolver is closed.")
        if type(row_group) is not int or row_group < 0:
            return None, "EVIDENCE_LOCATOR_INVALID"
        if type(row_index) is not int or row_index < 0:
            return None, "EVIDENCE_LOCATOR_INVALID"
        if row_group >= len(self._groups):
            return None, "EVIDENCE_NOT_FOUND"
        row_cells = self._groups[row_group]
        if row_index >= len(row_cells):
            return None, "EVIDENCE_NOT_FOUND"
        self._note_lookup()
        return row_cells[row_index], None

    def iter_records(self) -> Iterator[tuple[int, int, Mapping[str, str]]]:
        """Yield ``(row_group, row_index, rendered record)`` in exact order."""
        if self._closed:
            raise ParquetCellError("Parquet evidence resolver is closed.")
        for group_index, row_cells in enumerate(self._groups):
            for row_index, record in enumerate(row_cells):
                self._note_lookup()
                yield group_index, row_index, record

    def _note_lookup(self) -> None:
        """Record one direct record access on an optional operation counter.

        This powers the deterministic bounded-operation assertion: a valid
        ``read`` performs exactly one record access regardless of the row's
        position, which is impossible with a linear scan.
        """
        if self._lookup_counter is not None:
            self._lookup_counter.accesses += 1

    # -- lifecycle -----------------------------------------------------------

    def close(self) -> None:
        """Drop the resolver's references so the decoded snapshot can be reclaimed.

        This is an honest lifetime hook: after the call, method calls (except
        idempotent ``close``/``verify``) raise.  The caller still owns any
        ``raw_bytes`` it holds — this never frees the caller's own reference.
        """
        self._closed = True
        self._raw_bytes = None
        self._groups = ()
        self._row_group_rows = ()

    def __enter__(self) -> "ParquetEvidenceResolver":
        return self

    def __exit__(self, *exc_info: object) -> bool:
        self.close()
        return False


def parquet_row_group_rows(raw_bytes: bytes) -> tuple[tuple[int, ...] | None, str | None]:
    """Return the exact row count of every row group, or a stable error.

    This is a metadata-only operation: it opens the Parquet footer and reads
    each row group's ``num_rows`` from the metadata.  It never decodes row
    data — ``read_row_group``/``to_pylist`` are not called here — so the
    returned denormalization is bounded by the (small) number of row groups,
    not by the size of the snapshot's rows.  A full row-grid decode is left to
    :class:`ParquetEvidenceResolver`, which a caller shares across extraction,
    admission, and validation.
    """
    parquet_file = _open(raw_bytes)
    if parquet_file is None:
        return None, "EVIDENCE_LOCATOR_INVALID"
    try:
        # Apply the same metadata-limit ceiling and strict non-negative
        # validation that the resolver uses, without decoding any row data.
        _enforce_metadata_limits(parquet_file)
        rows = tuple(
            _require_nonnegative_int(
                parquet_file.metadata.row_group(i).num_rows, "rows"
            )
            for i in _range_bounded(parquet_file.num_row_groups)
        )
    except ParquetMetadataLimitError as exc:
        return None, f"EVIDENCE_METADATA_LIMIT_{exc.reason}"
    except ParquetCellError:
        return None, "EVIDENCE_LOCATOR_INVALID"
    except Exception:
        return None, "EVIDENCE_LOCATOR_INVALID"
    finally:
        # Release the handle even on the metadata-rejection path.
        parquet_file.close(force=True)
    return rows, None


def read_parquet_record(
    raw_bytes: bytes,
    *,
    row_group: object,
    row_index: object,
    resolver: ParquetEvidenceResolver | None = None,
) -> tuple[Mapping[str, str] | None, str | None]:
    """Resolve one record's rendered cells, mirroring the CSV/JSON evidence seam.

    When ``resolver`` is supplied it is used as-is, but only after verifying it
    is bound to ``raw_bytes``; otherwise a single-shot resolver is built for
    this one record.  A supplied resolver bound to different bytes fails closed
    with ``EVIDENCE_SNAPSHOT_MISMATCH``.
    """

    if type(row_group) is not int or row_group < 0:
        return None, "EVIDENCE_LOCATOR_INVALID"
    if type(row_index) is not int or row_index < 0:
        return None, "EVIDENCE_LOCATOR_INVALID"
    if resolver is not None:
        try:
            resolver.verify(raw_bytes)
        except ParquetCellError:
            return None, "EVIDENCE_SNAPSHOT_MISMATCH"
        return resolver.read(row_group=row_group, row_index=row_index)
    try:
        with ParquetEvidenceResolver(raw_bytes) as single:
            return single.read(row_group=row_group, row_index=row_index)
    except ParquetCellError:
        return None, "EVIDENCE_LOCATOR_INVALID"


def iter_parquet_records(
    raw_bytes: bytes,
    resolver: ParquetEvidenceResolver | None = None,
) -> Iterator[tuple[int, int, Mapping[str, str]]]:
    """Yield ``(row_group, row_index, record)`` for complete batch accounting.

    Raises :class:`ParquetCellError` on malformed bytes so batch accounting
    fails closed. A supplied resolver is used only after it verifies against
    ``raw_bytes``; a mismatched resolver fails closed.
    """

    if resolver is not None:
        resolver.verify(raw_bytes)  # raises ParquetCellError on mismatch
        yield from resolver.iter_records()
        return
    with ParquetEvidenceResolver(raw_bytes) as single:
        yield from single.iter_records()


__all__ = [
    "MAX_PARQUET_BATCH_SIZE",
    "MAX_PARQUET_CELLS",
    "MAX_PARQUET_COLUMNS",
    "MAX_PARQUET_DECOMPRESSED_BYTES",
    "MAX_PARQUET_ROW_GROUPS",
    "MAX_PARQUET_ROWS",
    "ParquetCellError",
    "ParquetEvidenceResolver",
    "ParquetMetadataLimitError",
    "build_snapshot_digest",
    "iter_parquet_records",
    "parquet_row_group_rows",
    "read_parquet_record",
    "render_cell_lexeme",
]
