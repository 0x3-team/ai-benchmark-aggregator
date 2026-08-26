from __future__ import annotations

import errno
import hashlib
import os
import secrets
import stat
from pathlib import Path
from typing import Iterable

from .base import (
    OrphanInventoryReceipt,
    SnapshotStorageCollisionError,
    SnapshotStorageError,
    SnapshotStorageIntegrityError,
    SnapshotStorageMissingError,
    SnapshotStorageProtocolError,
    StorageObjectAddress,
    StorageObjectKind,
    StorageReadResult,
    StorageSecurityPosture,
    StorageStoreReceipt,
    StorageVerificationReceipt,
    compute_content_hash,
    require_full_sha256,
)

#: Conservative per-snapshot byte cap.  A single immutable SNAPSHOT object
#: larger than this is rejected before retention via an fstat early guard plus
#: a cap+1 streaming guard, so lying metadata or file growth cannot bypass the
#: bound.  The cap applies ONLY to ``StorageObjectKind.SNAPSHOT`` objects; the
#: ``ARTIFACT`` namespace holds relational backup blobs owned by the F9/F19
#: drivers and is intentionally unconstrained here.  64 MiB leaves very wide
#: headroom for a single captured-source snapshot (a benchmark/claim raw
#: payload) while still bounding the largest single held object well below the
#: cumulative checkpoint/restore budget evaluated in backup/service.py.
MAX_SNAPSHOT_BYTES = 64 * 1024 * 1024

#: Fixed read chunk size: the production reader never issues an unbounded
#: ``read()``/``read(-1)``; every object (snapshot or artifact) is streamed in
#: chunks of this size.
_CHUNK_SIZE = 64 * 1024


def _sha256_stream(handle, *, cap: int | None) -> tuple[str, int, bool]:
    """Stream one regular-file handle through bounded positive chunks.

    Returns ``(digest, byte_count, over_cap)``.  When ``cap`` is set the reader
    issues reads of ``min(_CHUNK_SIZE, (cap + 1) - byte_count)`` so it consumes
    at most ``cap + 1`` bytes total: a file that grows beyond the fstat-reported
    size (or that lied about its size) cannot be read unbounded and cannot be
    over-consumed by more than one chunk beyond the cap.  When ``cap`` is
    ``None`` (artifact namespace) the file is still read in ``_CHUNK_SIZE``
    chunks but no total bound is imposed.
    """
    digest = hashlib.sha256()
    byte_count = 0
    over_cap = False
    while True:
        if cap is not None:
            remaining = cap + 1 - byte_count
            if remaining <= 0:
                over_cap = True
                break
            read_size = min(_CHUNK_SIZE, remaining)
        else:
            read_size = _CHUNK_SIZE
        chunk = handle.read(read_size)
        if not chunk:
            break
        byte_count += len(chunk)
        digest.update(chunk)
        if cap is not None and byte_count > cap:
            over_cap = True
            break
    return digest.hexdigest(), byte_count, over_cap


def _raise_over_cap(cap: int) -> None:
    raise SnapshotStorageIntegrityError(
        f"Snapshot object exceeds the documented per-snapshot byte cap of {cap}"
    )


class LocalSnapshotStorage:
    """Local, content-addressed storage for immutable raw source bytes.

    The URI is intentionally derived only from the full SHA-256 digest.  Source
    identifiers and filename extensions are descriptive metadata, not storage
    identity, so neither can redirect a write or make equal bytes ambiguous.
    """

    def __init__(self, root: Path) -> None:
        root_path = Path(root).expanduser()
        root_path.mkdir(parents=True, exist_ok=True)
        self.root = root_path.resolve()

    security_posture = StorageSecurityPosture.application_only()

    # ------------------------------------------------------------------
    # Address handling
    # ------------------------------------------------------------------

    def path_for_content_hash(
        self,
        content_hash: str,
        *,
        object_kind: StorageObjectKind = StorageObjectKind.SNAPSHOT,
    ) -> Path:
        """Return the canonical, root-contained path for a full SHA-256 digest."""
        digest = require_full_sha256(content_hash)
        kind = self._require_object_kind(object_kind)
        # Two fan-out levels avoid a single oversized directory.  The filename
        # still contains the complete identity, never a truncated prefix.
        namespace = self.root if kind is StorageObjectKind.SNAPSHOT else self.root / "artifacts"
        return namespace / digest[:2] / digest[2:4] / digest

    def address_for_content_hash(
        self,
        content_hash: str,
        *,
        object_kind: StorageObjectKind = StorageObjectKind.SNAPSHOT,
    ) -> StorageObjectAddress:
        digest = require_full_sha256(content_hash)
        kind = self._require_object_kind(object_kind)
        path = self.path_for_content_hash(digest, object_kind=kind)
        return StorageObjectAddress(
            provider="local",
            object_kind=kind,
            uri=str(path),
            key=path.relative_to(self.root).as_posix(),
            content_sha256=digest,
        )

    def _is_snapshot_path(self, path: Path) -> bool:
        """True when ``path`` lives in the SNAPSHOT namespace (not ``artifacts/``).

        The ARTIFACT namespace holds relational backup blobs owned by the
        F9/F19 drivers; it is never subject to the per-snapshot byte cap.
        """
        relative = path.relative_to(self.root)
        return not (relative.parts and relative.parts[0] == "artifacts")

    def _cap_for_path(self, path: Path) -> int | None:
        """Per-object cap for a path: ``MAX_SNAPSHOT_BYTES`` for snapshots, ``None`` for artifacts."""
        return MAX_SNAPSHOT_BYTES if self._is_snapshot_path(path) else None

    # ------------------------------------------------------------------
    # Public immutable-object operations
    # ------------------------------------------------------------------

    def store_snapshot(
        self,
        *,
        raw_bytes: bytes,
        object_kind: StorageObjectKind = StorageObjectKind.SNAPSHOT,
    ) -> StorageStoreReceipt:
        """Create or exactly reuse one canonical object, then verify its bytes."""
        kind = self._require_object_kind(object_kind)
        cap = self._cap_for_kind(kind)
        if cap is not None and len(raw_bytes) > cap:
            _raise_over_cap(cap)
        content_hash = compute_content_hash(raw_bytes)
        address = self.address_for_content_hash(content_hash, object_kind=kind)
        path = Path(address.uri)

        if path.exists() or path.is_symlink():
            self._verify_target(path, content_hash, cap)
            outcome = "reused"
        else:
            created = self._write_new_target(path, raw_bytes, content_hash, cap)
            outcome = "created" if created else "reused"

        read_receipt = self.read_snapshot(uri=address.uri, content_sha256=content_hash)
        return StorageStoreReceipt.create(
            outcome=outcome,
            verification=read_receipt.verification,
            write_precondition="atomic_no_replace",
        )

    def save(
        self,
        *,
        official_source_id: str,
        raw_bytes: bytes,
        extension: str,
    ) -> tuple[str, str]:
        """Atomically persist bytes and return their canonical URI and digest.

        ``official_source_id`` and ``extension`` are retained for API
        compatibility.  They are deliberately not used in the path: the
        content digest is the only storage identity.
        """
        _ = official_source_id, extension
        receipt = self.store_snapshot(raw_bytes=raw_bytes)
        return receipt.address.uri, receipt.address.content_sha256

    def verify(self, *, uri: str, content_hash: str) -> StorageVerificationReceipt:
        """Fail closed unless an existing snapshot URI holds exactly this digest."""
        return self.verify_snapshot(uri=uri, content_sha256=content_hash)

    def read(self, uri: str) -> bytes:
        """Read a root-contained regular object without hash verification.

        Bounded: snapshots are streamed in fixed-size chunks and any snapshot
        over the per-object byte cap is rejected; the artifact namespace is
        streamed in the same fixed chunks but never capped.
        """
        path = self._path_from_uri(uri)
        cap = self._cap_for_path(path)
        _, _, raw_bytes = self._stream_object(path, cap=cap, materialize=True)
        return raw_bytes

    def read_snapshot(self, *, uri: str, content_sha256: str) -> StorageReadResult:
        """Read bytes only after bounded streaming verification.

        The object is hashed in fixed-size chunks (never an unbounded read);
        the bytes are returned only if the object is within its namespace
        bound (snapshots at or under the per-snapshot cap) and the streaming
        digest matches the expected one.
        """
        expected = require_full_sha256(content_sha256)
        path = self._path_from_uri(uri)
        cap = self._cap_for_path(path)
        observed, byte_length, raw_bytes = self._stream_object(
            path, cap=cap, materialize=True
        )
        if observed != expected:
            raise SnapshotStorageIntegrityError(
                f"Snapshot at {path} hashes to {observed}, not expected digest {expected}."
            )
        address = self._address_from_path(path, expected)
        metadata = self._canonical_metadata(address, byte_length)
        verification = StorageVerificationReceipt.create(
            address=address,
            expected_sha256=expected,
            observed_sha256=observed,
            byte_length=byte_length,
            metadata=metadata,
        )
        return StorageReadResult.create(raw_bytes=raw_bytes, verification=verification)

    def verify_snapshot(
        self, *, uri: str, content_sha256: str
    ) -> StorageVerificationReceipt:
        """Stream-verify a snapshot without materializing the object bytes.

        The digest is computed through fixed-size chunks from a descriptor-
        pinned no-follow regular file; the object is never read into memory.
        """
        expected = require_full_sha256(content_sha256)
        path = self._path_from_uri(uri)
        cap = self._cap_for_path(path)
        observed, byte_length, _ = self._stream_object(path, cap=cap, materialize=False)
        if observed != expected:
            raise SnapshotStorageIntegrityError(
                f"Snapshot at {path} hashes to {observed}, not expected digest {expected}."
            )
        address = self._address_from_path(path, expected)
        metadata = self._canonical_metadata(address, byte_length)
        return StorageVerificationReceipt.create(
            address=address,
            expected_sha256=expected,
            observed_sha256=observed,
            byte_length=byte_length,
            metadata=metadata,
        )

    def inventory_orphans(
        self,
        *,
        referenced_uris: Iterable[str],
        object_kind: StorageObjectKind = StorageObjectKind.SNAPSHOT,
    ) -> OrphanInventoryReceipt:
        """Reconcile canonical local objects without reading, adopting, or deleting them."""
        kind = self._require_object_kind(object_kind)
        referenced: dict[str, StorageObjectAddress] = {}
        referenced_uri_set: set[str] = set()
        for uri in referenced_uris:
            address = self._canonical_address_from_uri(uri, object_kind=kind)
            if address.uri in referenced_uri_set or address.key in referenced:
                raise SnapshotStorageIntegrityError(
                    "Orphan inventory contains a duplicate reference URI or key."
                )
            referenced[address.key] = address
            referenced_uri_set.add(address.uri)

        listed: dict[str, StorageObjectAddress] = {}
        for address in self._iter_canonical_addresses(kind):
            if address.key in listed:
                raise SnapshotStorageProtocolError(
                    "Canonical object inventory contains a duplicate key."
                )
            listed[address.key] = address

        orphan_keys = listed.keys() - referenced.keys()
        missing_keys = referenced.keys() - listed.keys()
        present_keys = referenced.keys() & listed.keys()
        if any(referenced[key] != listed[key] for key in present_keys):
            raise SnapshotStorageIntegrityError(
                "Orphan inventory found a substituted identity for a referenced local object."
            )
        scope = "snapshots" if kind is StorageObjectKind.SNAPSHOT else "artifacts"
        return OrphanInventoryReceipt.create(
            provider="local",
            object_kind=kind,
            scope=scope,
            pages_scanned=1,
            listed_count=len(listed),
            referenced_count=len(referenced),
            referenced_present=(referenced[key] for key in present_keys),
            orphan_objects=(listed[key] for key in orphan_keys),
            missing_references=(referenced[key] for key in missing_keys),
        )

    # ------------------------------------------------------------------
    # Inventory internals
    # ------------------------------------------------------------------

    def _iter_canonical_addresses(
        self, object_kind: StorageObjectKind
    ) -> Iterable[StorageObjectAddress]:
        """List canonical files through no-follow directory descriptors."""
        if not hasattr(os, "O_NOFOLLOW"):
            raise SnapshotStorageIntegrityError(
                "Secure local snapshot inventory requires no-follow file-descriptor support."
            )
        directory_flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_DIRECTORY", 0)
        root_fd: int | None = None
        namespace_fd: int | None = None
        try:
            root_fd = os.open(self.root, directory_flags)
            if object_kind is StorageObjectKind.ARTIFACT:
                try:
                    namespace_fd = os.open("artifacts", directory_flags, dir_fd=root_fd)
                except FileNotFoundError:
                    return
                namespace_path = self.root / "artifacts"
            else:
                namespace_fd = os.dup(root_fd)
                namespace_path = self.root

            for first_name in sorted(os.listdir(namespace_fd)):
                if not self._is_hex_component(first_name, length=2):
                    continue
                first_fd = self._open_inventory_directory(
                    namespace_fd, first_name, namespace_path / first_name
                )
                try:
                    for second_name in sorted(os.listdir(first_fd)):
                        if not self._is_hex_component(second_name, length=2):
                            continue
                        second_path = namespace_path / first_name / second_name
                        second_fd = self._open_inventory_directory(
                            first_fd, second_name, second_path
                        )
                        try:
                            for digest in sorted(os.listdir(second_fd)):
                                if not self._is_hex_component(digest, length=64):
                                    continue
                                path = second_path / digest
                                try:
                                    mode = os.stat(
                                        digest,
                                        dir_fd=second_fd,
                                        follow_symlinks=False,
                                    ).st_mode
                                except FileNotFoundError as exc:
                                    raise SnapshotStorageIntegrityError(
                                        f"Canonical object disappeared during inventory: {path}"
                                    ) from exc
                                if stat.S_ISLNK(mode):
                                    raise SnapshotStorageIntegrityError(
                                        f"Canonical object inventory rejects symbolic links: {path}"
                                    )
                                if not stat.S_ISREG(mode):
                                    raise SnapshotStorageIntegrityError(
                                        f"Canonical object inventory requires regular files: {path}"
                                    )
                                yield self._canonical_address_from_uri(
                                    str(path), object_kind=object_kind
                                )
                        finally:
                            os.close(second_fd)
                finally:
                    os.close(first_fd)
        except OSError as exc:
            raise SnapshotStorageIntegrityError(
                "Cannot safely enumerate local immutable object storage."
            ) from exc
        finally:
            if namespace_fd is not None:
                os.close(namespace_fd)
            if root_fd is not None:
                os.close(root_fd)

    @staticmethod
    def _is_hex_component(value: str, *, length: int) -> bool:
        return len(value) == length and all(
            character in "0123456789abcdef" for character in value
        )

    @staticmethod
    def _open_inventory_directory(parent_fd: int, name: str, path: Path) -> int:
        flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_DIRECTORY", 0)
        try:
            fd = os.open(name, flags, dir_fd=parent_fd)
        except OSError as exc:
            raise SnapshotStorageIntegrityError(
                f"Canonical object inventory rejects symbolic link or invalid directory: {path}"
            ) from exc
        try:
            if not stat.S_ISDIR(os.fstat(fd).st_mode):
                raise SnapshotStorageIntegrityError(
                    f"Canonical object inventory requires directories: {path}"
                )
            return fd
        except Exception:
            os.close(fd)
            raise

    @staticmethod
    def _require_object_kind(object_kind: StorageObjectKind) -> StorageObjectKind:
        if not isinstance(object_kind, StorageObjectKind):
            raise SnapshotStorageProtocolError("Object kind must be a StorageObjectKind value.")
        return object_kind

    @staticmethod
    def _cap_for_kind(object_kind: StorageObjectKind) -> int | None:
        return MAX_SNAPSHOT_BYTES if object_kind is StorageObjectKind.SNAPSHOT else None

    # ------------------------------------------------------------------
    # Path/identity reconciliation
    # ------------------------------------------------------------------

    def _canonical_metadata(
        self, address: StorageObjectAddress, byte_length: int
    ) -> dict[str, str]:
        return {
            "storage-contract": "immutable-object-v1",
            "object-kind": address.object_kind.value,
            "content-sha256": address.content_sha256,
            "byte-length": str(byte_length),
        }

    def _address_from_path(
        self, path: Path, content_sha256: str
    ) -> StorageObjectAddress:
        digest = require_full_sha256(content_sha256)
        artifact_path = self.path_for_content_hash(
            digest, object_kind=StorageObjectKind.ARTIFACT
        )
        if path == artifact_path:
            kind = StorageObjectKind.ARTIFACT
        else:
            # Historic root-contained paths remain snapshot evidence. They are
            # verified by full bytes but never silently renamed or rewritten.
            kind = StorageObjectKind.SNAPSHOT
        return StorageObjectAddress(
            provider="local",
            object_kind=kind,
            uri=str(path),
            key=path.relative_to(self.root).as_posix(),
            content_sha256=digest,
        )

    def _canonical_address_from_uri(
        self, uri: str, *, object_kind: StorageObjectKind
    ) -> StorageObjectAddress:
        path = self._path_from_uri(uri)
        digest = path.name
        address = self.address_for_content_hash(digest, object_kind=object_kind)
        if path != Path(address.uri):
            raise SnapshotStorageIntegrityError(
                "Referenced local object URI is not a canonical content-addressed key."
            )
        return address

    def _path_from_uri(self, uri: str) -> Path:
        candidate = Path(uri).expanduser()
        if not candidate.is_absolute():
            candidate = Path.cwd() / candidate
        # Do not resolve this path before opening it: resolution can follow a
        # symlink in a time-of-check/time-of-use window.  The fd-based reader
        # below walks every component with no-follow semantics instead.
        normalized = Path(os.path.abspath(candidate))
        try:
            normalized.relative_to(self.root)
        except ValueError as exc:
            raise SnapshotStorageIntegrityError(
                "Snapshot URI is outside the configured local storage root."
            ) from exc
        return normalized

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    def _write_new_target(
        self, path: Path, raw_bytes: bytes, content_hash: str, cap: int | None
    ) -> bool:
        parent_fd = self._open_or_create_parent(path.parent)
        temp_name: str | None = None
        try:
            temp_name = f".{content_hash}.{secrets.token_hex(16)}.tmp"
            fd = os.open(
                temp_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=parent_fd,
            )
            with os.fdopen(fd, "wb") as handle:
                handle.write(raw_bytes)
                handle.flush()
                os.fsync(handle.fileno())

            try:
                # Linking a fully fsynced temporary file is an atomic
                # no-overwrite publication on the same filesystem.  Unlike
                # os.replace(), it cannot replace bytes already used as
                # evidence by another writer.
                os.link(
                    temp_name,
                    path.name,
                    src_dir_fd=parent_fd,
                    dst_dir_fd=parent_fd,
                    follow_symlinks=False,
                )
            except FileExistsError:
                # This is a true atomic no-replace reuse; the race outcome is
                # bounded against the caller's accepted per-object cap.
                self._verify_target_from_parent(parent_fd, path, content_hash, cap)
                return False
            else:
                self._fsync_open_directory(parent_fd, path.parent)
                return True
        finally:
            if temp_name is not None:
                try:
                    os.unlink(temp_name, dir_fd=parent_fd)
                except FileNotFoundError:
                    pass
                except OSError:
                    # The primary write/integrity error is more useful than a
                    # cleanup error.  A later save cannot mistake a .tmp file
                    # for a snapshot because only canonical digest paths are
                    # ever read or reused.
                    pass
            os.close(parent_fd)

    @staticmethod
    def _fsync_open_directory(fd: int, directory: Path) -> None:
        try:
            os.fsync(fd)
        except OSError as exc:
            if exc.errno in (errno.EINVAL, errno.ENOTSUP):
                return
            raise SnapshotStorageError(f"Cannot fsync snapshot directory: {directory}") from exc

    def _open_or_create_parent(self, parent: Path) -> int:
        try:
            relative = parent.relative_to(self.root)
        except ValueError as exc:
            raise SnapshotStorageIntegrityError(
                "Snapshot write parent is outside the configured storage root."
            ) from exc
        flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_DIRECTORY", 0)
        current_fd = os.open(self.root, flags)
        try:
            for component in relative.parts:
                try:
                    next_fd = os.open(component, flags, dir_fd=current_fd)
                except FileNotFoundError:
                    try:
                        os.mkdir(component, mode=0o700, dir_fd=current_fd)
                    except FileExistsError:
                        pass
                    try:
                        next_fd = os.open(component, flags, dir_fd=current_fd)
                    except OSError as exc:
                        raise SnapshotStorageIntegrityError(
                            f"Snapshot write rejects symbolic link or invalid directory: {parent}"
                        ) from exc
                except OSError as exc:
                    raise SnapshotStorageIntegrityError(
                        f"Snapshot write rejects symbolic link or invalid directory: {parent}"
                    ) from exc
                previous_fd = current_fd
                current_fd = next_fd
                os.close(previous_fd)
            return current_fd
        except Exception:
            os.close(current_fd)
            raise

    @staticmethod
    def _verify_target_from_parent(
        parent_fd: int, path: Path, content_hash: str, cap: int | None
    ) -> None:
        expected = require_full_sha256(content_hash)
        fd: int | None = None
        try:
            fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent_fd)
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise SnapshotStorageIntegrityError(
                    f"Snapshot target is not a regular file: {path}"
                )
            if cap is not None and os.fstat(fd).st_size > cap:
                _raise_over_cap(cap)
            # Transfer ownership into the wrapper with closefd=True so the
            # context-manager exit (and any streaming error) closes the fd
            # exactly once; then clear our reference so the finally never
            # double-closes it.
            handle = os.fdopen(fd, "rb")
            fd = None
            with handle:
                actual, byte_count, over_cap = _sha256_stream(handle, cap=cap)
        except OSError as exc:
            raise SnapshotStorageIntegrityError(
                f"Cannot safely reuse snapshot target (symbolic links are rejected): {path}"
            ) from exc
        finally:
            if fd is not None:
                os.close(fd)
        if cap is not None and (over_cap or byte_count > cap):
            _raise_over_cap(cap)
        if actual != expected:
            raise SnapshotStorageCollisionError(
                f"Snapshot at {path} hashes to {actual}, not expected digest {expected}."
            )

    def _verify_target(self, path: Path, content_hash: str, cap: int | None) -> None:
        expected = require_full_sha256(content_hash)
        observed, byte_length, _ = self._stream_object(path, cap=cap, materialize=False)
        if observed != expected:
            raise SnapshotStorageCollisionError(
                f"Snapshot at {path} hashes to {observed}, not expected digest {expected}."
            )

    # ------------------------------------------------------------------
    # Reads (one ownership-transfer helper for all descriptor reads)
    # ------------------------------------------------------------------

    def _stream_object(
        self, path: Path, *, cap: int | None, materialize: bool
    ) -> tuple[str, int, bytes]:
        """Stream one no-follow regular file through bounded positive chunks.

        The only descriptor reader in the storage layer: it opens the exact
        regular inode, applies an fstat precheck plus a cap+1 streaming guard
        for snapshots (``cap`` is ``None`` for the artifact namespace), hashes
        through ``_CHUNK_SIZE``-sized reads (never an unbounded read) clamped to
        ``min(_CHUNK_SIZE, cap + 1 - byte_count)`` so at most ``cap + 1`` bytes
        are consumed, and closes the descriptor exactly once in every path.
        ``materialize`` chooses whether the raw bytes are retained
        (read_snapshot) or discarded (verify_snapshot).  Returns
        ``(digest, byte_count, raw_bytes)`` where ``raw_bytes`` is ``b""`` when
        not materialized.
        """
        fd = self._open_regular_file(path)
        parts: list[bytes] = [] if materialize else None  # type: ignore[assignment]
        digest = hashlib.sha256()
        byte_count = 0
        over_cap = False
        try:
            st = os.fstat(fd)
            if cap is not None and st.st_size > cap:
                _raise_over_cap(cap)
            with os.fdopen(fd, "rb", closefd=False) as handle:
                while True:
                    if cap is not None:
                        remaining = cap + 1 - byte_count
                        if remaining <= 0:
                            over_cap = True
                            break
                        read_size = min(_CHUNK_SIZE, remaining)
                    else:
                        read_size = _CHUNK_SIZE
                    chunk = handle.read(read_size)
                    if not chunk:
                        break
                    byte_count += len(chunk)
                    digest.update(chunk)
                    if materialize:
                        parts.append(chunk)
                    if cap is not None and byte_count > cap:
                        over_cap = True
                        break
        finally:
            # ``_open_regular_file`` transfers ownership of ``fd`` to us; we
            # are solely responsible for closing it exactly once.
            os.close(fd)
        if cap is not None and (over_cap or byte_count > cap):
            _raise_over_cap(cap)
        materialized = b"".join(parts) if materialize else b""
        return digest.hexdigest(), byte_count, materialized

    def _open_regular_file(self, path: Path) -> int:
        """Open a root-contained regular file with no-follow directory walk.

        Returns a raw file descriptor pinned to the exact regular inode; the
        caller takes ownership and MUST close the returned fd exactly once.
        On any exception path every intermediate and leaf descriptor is closed
        before the exception propagates, so no descriptor leaks.
        """
        try:
            relative = path.relative_to(self.root)
        except ValueError as exc:
            raise SnapshotStorageIntegrityError(
                "Snapshot path is outside the configured local storage root."
            ) from exc
        if not relative.parts:
            raise SnapshotStorageIntegrityError("Snapshot path must name a regular file.")
        if not hasattr(os, "O_NOFOLLOW"):
            raise SnapshotStorageIntegrityError(
                "Secure local snapshot reads require no-follow file-descriptor support."
            )

        no_follow = os.O_NOFOLLOW
        directory_flags = os.O_RDONLY | no_follow | getattr(os, "O_DIRECTORY", 0)
        current_fd: int | None = None
        fd: int | None = None
        success = False
        try:
            current_fd = os.open(self.root, directory_flags)
            if not stat.S_ISDIR(os.fstat(current_fd).st_mode):
                raise SnapshotStorageIntegrityError(
                    f"Snapshot root is not a directory: {self.root}"
                )
            for component in relative.parts[:-1]:
                next_fd = os.open(component, directory_flags, dir_fd=current_fd)
                try:
                    is_directory = stat.S_ISDIR(os.fstat(next_fd).st_mode)
                except OSError:
                    os.close(next_fd)
                    raise
                if not is_directory:
                    os.close(next_fd)
                    raise SnapshotStorageIntegrityError(
                        f"Snapshot path has a non-directory component: {path}"
                    )
                previous_fd = current_fd
                current_fd = next_fd
                os.close(previous_fd)
            fd = os.open(relative.parts[-1], os.O_RDONLY | no_follow, dir_fd=current_fd)
            mode = os.fstat(fd).st_mode
            if not stat.S_ISREG(mode):
                raise SnapshotStorageIntegrityError(f"Snapshot path is not a regular file: {path}")
            if current_fd is not None:
                os.close(current_fd)
                current_fd = None
            success = True
            return fd
        except FileNotFoundError as exc:
            raise SnapshotStorageMissingError(f"Snapshot file is missing: {path}") from exc
        except OSError as exc:
            raise SnapshotStorageIntegrityError(
                f"Cannot safely read snapshot file (symbolic links are rejected): {path}"
            ) from exc
        finally:
            # On success the fd ownership transfers to the caller; only close
            # the intermediate/leaf fds when an exception is propagating.
            if not success:
                if fd is not None:
                    try:
                        os.close(fd)
                    except OSError:
                        pass
                if current_fd is not None:
                    try:
                        os.close(current_fd)
                    except OSError:
                        pass