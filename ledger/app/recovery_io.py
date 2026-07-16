"""Bounded, no-follow file I/O for DATA-10 operator contracts.

Checkpoint manifests and restore receipts are immutable evidence files.  This
module deliberately has no database, network, storage-provider, or clock
dependency.  It never overwrites an existing path and never renders a caller's
path or an operating-system exception into an operator-facing error.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import stat
from dataclasses import dataclass, field
from typing import Any, Mapping

from app.schemas.recovery_contracts import (
    RecoveryContractError,
    canonical_recovery_json,
    parse_canonical_recovery_bytes,
)


MAX_RECOVERY_CONTRACT_BYTES = 64 * 1024 * 1024


class RecoveryFileError(RuntimeError):
    """A recovery input/output file was unsafe, malformed, or unavailable."""


def _require_nofollow() -> int:
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    if not nofollow:
        raise RecoveryFileError(
            "Recovery contract files require no-follow descriptor support."
        )
    return nofollow


def _read_regular_file(
    path: Path,
    *,
    maximum_bytes: int = MAX_RECOVERY_CONTRACT_BYTES,
) -> bytes:
    if (
        type(maximum_bytes) is not int
        or maximum_bytes < 1
        or maximum_bytes > MAX_RECOVERY_CONTRACT_BYTES
    ):
        raise RecoveryFileError("Recovery contract read bound is invalid.")
    flags = os.O_RDONLY | _require_nofollow() | getattr(os, "O_CLOEXEC", 0)
    descriptor: int | None = None
    try:
        descriptor = os.open(os.fspath(Path(path)), flags)
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise RecoveryFileError("Recovery contract input must be a regular file.")
        if metadata.st_size > maximum_bytes:
            raise RecoveryFileError("Recovery contract input exceeds the bounded size limit.")
        chunks: list[bytes] = []
        remaining = maximum_bytes + 1
        while remaining:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        if len(raw) > maximum_bytes:
            raise RecoveryFileError("Recovery contract input exceeds the bounded size limit.")
        return raw
    except RecoveryFileError:
        raise
    except (OSError, ValueError, TypeError):
        raise RecoveryFileError("Recovery contract input cannot be read safely.") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _reject_constant(value: str) -> None:
    del value
    raise RecoveryFileError("Recovery JSON cannot contain non-finite numbers.")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise RecoveryFileError("Recovery JSON contains a duplicate object key.")
        result[key] = value
    return result


def read_json_object(
    path: Path,
    *,
    maximum_bytes: int = MAX_RECOVERY_CONTRACT_BYTES,
) -> dict[str, Any]:
    """Read one bounded JSON object without accepting duplicate keys or NaN."""

    raw = _read_regular_file(path, maximum_bytes=maximum_bytes)
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except RecoveryFileError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
        raise RecoveryFileError("Recovery JSON input is malformed.") from None
    if type(value) is not dict:
        raise RecoveryFileError("Recovery JSON input must be one object.")
    return value


def read_canonical_recovery_document(
    path: Path,
    *,
    maximum_bytes: int = MAX_RECOVERY_CONTRACT_BYTES,
) -> dict[str, Any]:
    """Read one exact canonical recovery manifest or receipt document."""

    raw = _read_regular_file(path, maximum_bytes=maximum_bytes)
    try:
        return parse_canonical_recovery_bytes(raw)
    except RecoveryContractError:
        raise RecoveryFileError(
            "Recovery contract input is not valid canonical recovery JSON."
        ) from None


@dataclass(slots=True)
class RecoveryOutputReservation:
    """One atomically reserved output inode that can be published exactly once."""

    _output_descriptor: int | None = field(repr=False)
    _directory_descriptor: int | None = field(repr=False)
    _published: bool = False

    def publish(self, document: Mapping[str, Any]) -> int:
        """Write, fsync, and close one canonical document into the reservation.

        Every error closes the held descriptors and retains the empty or
        partial output inode.  A caller must never repair or reuse it.
        """

        if self._output_descriptor is None or self._directory_descriptor is None:
            raise RecoveryFileError("Recovery contract output reservation is closed.")
        if self._published:
            raise RecoveryFileError("Recovery contract output was already published.")
        try:
            try:
                raw = canonical_recovery_json(document).encode("ascii")
            except (RecoveryContractError, TypeError, ValueError, UnicodeError):
                raise RecoveryFileError(
                    "Recovery contract output is not canonical JSON."
                ) from None
            if len(raw) > MAX_RECOVERY_CONTRACT_BYTES:
                raise RecoveryFileError(
                    "Recovery contract output exceeds the bounded size limit."
                )
            offset = 0
            while offset < len(raw):
                written = os.write(self._output_descriptor, raw[offset:])
                if written < 1:
                    raise RecoveryFileError(
                        "Recovery contract output could not be completed."
                    )
                offset += written
            os.fsync(self._output_descriptor)
            os.close(self._output_descriptor)
            self._output_descriptor = None
            os.fsync(self._directory_descriptor)
            self._published = True
            self.close()
            return len(raw)
        except RecoveryFileError:
            raise
        except (OSError, TypeError, ValueError):
            raise RecoveryFileError(
                "Recovery contract output could not be created safely."
            ) from None
        finally:
            if not self._published:
                self.close()

    def close(self) -> None:
        """Close the reservation while retaining its fail-closed output inode."""

        if self._output_descriptor is not None:
            os.close(self._output_descriptor)
            self._output_descriptor = None
        if self._directory_descriptor is not None:
            os.close(self._directory_descriptor)
            self._directory_descriptor = None


def reserve_new_recovery_output(path: Path) -> RecoveryOutputReservation:
    """Atomically reserve a private output path before recovery work mutates targets."""

    output = Path(path)
    if output.name in {"", ".", ".."}:
        raise RecoveryFileError("Recovery contract output path is invalid.")
    directory_flags = (
        os.O_RDONLY
        | _require_nofollow()
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    directory_descriptor: int | None = None
    output_descriptor: int | None = None
    try:
        directory_descriptor = os.open(os.fspath(output.parent), directory_flags)
        output_descriptor = os.open(
            output.name,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | _require_nofollow()
            | getattr(os, "O_CLOEXEC", 0),
            0o600,
            dir_fd=directory_descriptor,
        )
        os.fsync(directory_descriptor)
        reservation = RecoveryOutputReservation(
            _output_descriptor=output_descriptor,
            _directory_descriptor=directory_descriptor,
        )
        output_descriptor = None
        directory_descriptor = None
        return reservation
    except FileExistsError:
        raise RecoveryFileError(
            "Recovery contract output already exists and will not be overwritten."
        ) from None
    except (OSError, TypeError, ValueError):
        raise RecoveryFileError(
            "Recovery contract output could not be created safely."
        ) from None
    finally:
        if output_descriptor is not None:
            os.close(output_descriptor)
        if directory_descriptor is not None:
            os.close(directory_descriptor)


def write_new_canonical_recovery_document(
    path: Path,
    document: Mapping[str, Any],
) -> int:
    """Reserve and durably publish one canonical, mode-0600 contract.

    A write error can leave a partial, permanently unusable output file.  That
    fail-closed artifact is intentionally retained; callers must choose a new
    output path instead of deleting or repairing prior recovery evidence.
    """
    reservation = reserve_new_recovery_output(path)
    try:
        return reservation.publish(document)
    finally:
        reservation.close()


__all__ = [
    "MAX_RECOVERY_CONTRACT_BYTES",
    "RecoveryFileError",
    "RecoveryOutputReservation",
    "read_canonical_recovery_document",
    "read_json_object",
    "reserve_new_recovery_output",
    "write_new_canonical_recovery_document",
]
