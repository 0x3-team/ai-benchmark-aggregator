from __future__ import annotations

import errno
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

    def store_snapshot(
        self,
        *,
        raw_bytes: bytes,
        object_kind: StorageObjectKind = StorageObjectKind.SNAPSHOT,
    ) -> StorageStoreReceipt:
        """Create or exactly reuse one canonical object, then verify its bytes."""
        kind = self._require_object_kind(object_kind)
        content_hash = compute_content_hash(raw_bytes)
        address = self.address_for_content_hash(content_hash, object_kind=kind)
        path = Path(address.uri)

        if path.exists() or path.is_symlink():
            self._verify_target(path, content_hash)
            outcome = "reused"
        else:
            created = self._write_new_target(path, raw_bytes, content_hash)
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
        """Read a root-contained regular snapshot file without hash verification."""
        return self._read_regular_file(self._path_from_uri(uri))

    def read_snapshot(self, *, uri: str, content_sha256: str) -> StorageReadResult:
        """Read all bytes and return a deterministic application SHA-256 receipt."""
        expected = require_full_sha256(content_sha256)
        path = self._path_from_uri(uri)
        raw_bytes = self._read_and_verify(path, expected, collision=False)
        address = self._address_from_path(path, expected)
        metadata = self._canonical_metadata(address, len(raw_bytes))
        verification = StorageVerificationReceipt.create(
            address=address,
            expected_sha256=expected,
            observed_sha256=compute_content_hash(raw_bytes),
            byte_length=len(raw_bytes),
            metadata=metadata,
        )
        return StorageReadResult.create(raw_bytes=raw_bytes, verification=verification)

    def verify_snapshot(
        self, *, uri: str, content_sha256: str
    ) -> StorageVerificationReceipt:
        return self.read_snapshot(
            uri=uri, content_sha256=content_sha256
        ).verification

    def inventory_orphans(
        self,
        *,
        referenced_uris: Iterable[str],
        object_kind: StorageObjectKind = StorageObjectKind.SNAPSHOT,
    ) -> OrphanInventoryReceipt:
        """Reconcile canonical local objects without reading, adopting, or deleting them."""
        kind = self._require_object_kind(object_kind)
        referenced: dict[str, StorageObjectAddress] = {}
        for uri in referenced_uris:
            address = self._canonical_address_from_uri(uri, object_kind=kind)
            if address.uri in {item.uri for item in referenced.values()} or address.key in referenced:
                raise SnapshotStorageIntegrityError(
                    "Orphan inventory contains a duplicate reference URI or key."
                )
            referenced[address.key] = address

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
    def _canonical_metadata(
        address: StorageObjectAddress, byte_length: int
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

    def _write_new_target(self, path: Path, raw_bytes: bytes, content_hash: str) -> bool:
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
                self._verify_target_from_parent(parent_fd, path, content_hash)
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
        parent_fd: int, path: Path, content_hash: str
    ) -> None:
        expected = require_full_sha256(content_hash)
        fd: int | None = None
        try:
            fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent_fd)
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise SnapshotStorageIntegrityError(
                    f"Snapshot target is not a regular file: {path}"
                )
            with os.fdopen(fd, "rb") as handle:
                fd = None
                raw_bytes = handle.read()
        except OSError as exc:
            raise SnapshotStorageIntegrityError(
                f"Cannot safely reuse snapshot target (symbolic links are rejected): {path}"
            ) from exc
        finally:
            if fd is not None:
                os.close(fd)
        actual = compute_content_hash(raw_bytes)
        if actual != expected:
            raise SnapshotStorageCollisionError(
                f"Snapshot at {path} hashes to {actual}, not expected digest {expected}."
            )

    def _verify_target(self, path: Path, content_hash: str) -> None:
        self._read_and_verify(path, content_hash, collision=True)

    def _read_and_verify(self, path: Path, content_hash: str, *, collision: bool) -> bytes:
        expected = require_full_sha256(content_hash)
        raw_bytes = self._read_regular_file(path)
        actual = compute_content_hash(raw_bytes)
        if actual != expected:
            error_type = SnapshotStorageCollisionError if collision else SnapshotStorageIntegrityError
            raise error_type(
                f"Snapshot at {path} hashes to {actual}, not expected digest {expected}."
            )
        return raw_bytes

    def _read_regular_file(self, path: Path) -> bytes:
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
            with os.fdopen(fd, "rb", closefd=False) as handle:
                return handle.read()
        except FileNotFoundError as exc:
            raise SnapshotStorageMissingError(f"Snapshot file is missing: {path}") from exc
        except OSError as exc:
            raise SnapshotStorageIntegrityError(
                f"Cannot safely read snapshot file (symbolic links are rejected): {path}"
            ) from exc
        finally:
            if fd is not None:
                os.close(fd)
            if current_fd is not None:
                os.close(current_fd)
