from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from app.storage.local import (
    LocalSnapshotStorage,
    SnapshotStorageCollisionError,
    SnapshotStorageIntegrityError,
    compute_content_hash,
)


def test_content_hash_stable():
    assert compute_content_hash(b"abc") == compute_content_hash(b"abc")
    assert compute_content_hash(b"abc") != compute_content_hash(b"abd")


def test_local_storage_dedup_uses_the_full_content_digest(tmp_path: Path):
    store = LocalSnapshotStorage(tmp_path)
    uri1, h1 = store.save(official_source_id="src1", raw_bytes=b'{"a":1}', extension="json")
    uri2, h2 = store.save(official_source_id="src1", raw_bytes=b'{"a":1}', extension="json")
    assert h1 == h2
    assert Path(uri1).exists()
    assert uri1 == uri2
    assert Path(uri2).name == h1


def test_same_prefix_different_full_digests_cannot_share_a_uri(tmp_path: Path):
    store = LocalSnapshotStorage(tmp_path)
    shared_prefix = "a" * 16
    first = f"{shared_prefix}{'b' * 48}"
    second = f"{shared_prefix}{'c' * 48}"

    assert first[:16] == second[:16]
    assert store.path_for_content_hash(first) != store.path_for_content_hash(second)


def test_stored_bytes_hash_to_the_persisted_digest(tmp_path: Path):
    store = LocalSnapshotStorage(tmp_path)
    raw_bytes = b'{"source":"exact bytes"}'
    uri, content_hash = store.save(
        official_source_id="source-a", raw_bytes=raw_bytes, extension="json"
    )

    assert compute_content_hash(Path(uri).read_bytes()) == content_hash
    store.verify(uri=uri, content_hash=content_hash)


def test_root_contained_legacy_snapshot_is_verified_without_rewriting(tmp_path: Path):
    store = LocalSnapshotStorage(tmp_path / "snapshots")
    raw_bytes = b"legacy immutable evidence"
    content_hash = compute_content_hash(raw_bytes)
    legacy_path = store.root / "legacy-source" / "20260713T000000Z_legacy.json"
    legacy_path.parent.mkdir()
    legacy_path.write_bytes(raw_bytes)

    store.verify(uri=str(legacy_path), content_hash=content_hash)
    assert legacy_path.read_bytes() == raw_bytes


def test_existing_target_with_different_bytes_fails_closed(tmp_path: Path):
    store = LocalSnapshotStorage(tmp_path)
    raw_bytes = b"trusted raw source bytes"
    uri, content_hash = store.save(
        official_source_id="source-a", raw_bytes=raw_bytes, extension="bin"
    )
    Path(uri).write_bytes(b"tampered bytes")

    with pytest.raises(SnapshotStorageCollisionError, match="not expected digest"):
        store.save(official_source_id="source-a", raw_bytes=raw_bytes, extension="bin")

    assert content_hash in uri


def test_reuse_verification_rejects_missing_or_tampered_persisted_bytes(tmp_path: Path):
    store = LocalSnapshotStorage(tmp_path)
    uri, content_hash = store.save(
        official_source_id="source-a", raw_bytes=b"immutable evidence", extension="bin"
    )
    Path(uri).write_bytes(b"tampered")

    with pytest.raises(SnapshotStorageIntegrityError, match="not expected digest"):
        store.verify(uri=uri, content_hash=content_hash)


def test_source_identifier_and_read_uri_cannot_escape_storage_root(tmp_path: Path):
    store = LocalSnapshotStorage(tmp_path / "snapshots")
    uri, _ = store.save(
        official_source_id="../../outside", raw_bytes=b"safe", extension="../../outside"
    )
    assert Path(uri).is_relative_to(store.root)

    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"not a snapshot")
    with pytest.raises(SnapshotStorageIntegrityError, match="outside"):
        store.read(str(outside))


def test_symlinked_snapshot_target_fails_closed(tmp_path: Path):
    store = LocalSnapshotStorage(tmp_path / "snapshots")
    raw_bytes = b"immutable evidence"
    uri, content_hash = store.save(
        official_source_id="source-a", raw_bytes=raw_bytes, extension="bin"
    )
    outside = tmp_path / "outside.bin"
    outside.write_bytes(raw_bytes)
    Path(uri).unlink()
    Path(uri).symlink_to(outside)

    with pytest.raises(SnapshotStorageIntegrityError, match="symbolic link"):
        store.verify(uri=uri, content_hash=content_hash)


def test_symlinked_snapshot_directory_fails_closed(tmp_path: Path):
    store = LocalSnapshotStorage(tmp_path / "snapshots")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "evidence.bin").write_bytes(b"not a root-contained object")
    (store.root / "linked").symlink_to(outside, target_is_directory=True)

    with pytest.raises(SnapshotStorageIntegrityError, match="symbolic link"):
        store.read(str(store.root / "linked" / "evidence.bin"))


def test_failed_atomic_publication_leaves_no_target_or_temp_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    store = LocalSnapshotStorage(tmp_path)
    raw_bytes = b"must not appear partially"
    content_hash = compute_content_hash(raw_bytes)
    target = store.path_for_content_hash(content_hash)

    def fail_link(_source: str, _target: str, **_kwargs: object) -> None:
        raise OSError("simulated link failure")

    monkeypatch.setattr("app.storage.local.os.link", fail_link)
    with pytest.raises(OSError, match="simulated link failure"):
        store.save(official_source_id="source-a", raw_bytes=raw_bytes, extension="bin")

    assert not target.exists()
    assert not list(target.parent.glob(".*.tmp"))


def test_concurrent_same_object_publication_keeps_one_verified_object(tmp_path: Path):
    store = LocalSnapshotStorage(tmp_path)
    raw_bytes = b"concurrent immutable evidence"

    def save_once() -> tuple[str, str]:
        return store.save(official_source_id="source-a", raw_bytes=raw_bytes, extension="bin")

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(lambda _ignored: save_once(), range(4)))

    assert len(set(results)) == 1
    uri, content_hash = results[0]
    assert compute_content_hash(Path(uri).read_bytes()) == content_hash
    assert not list(Path(uri).parent.glob(".*.tmp"))
