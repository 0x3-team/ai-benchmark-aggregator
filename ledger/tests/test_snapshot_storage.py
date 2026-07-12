from pathlib import Path

from app.storage.local import LocalSnapshotStorage, compute_content_hash


def test_content_hash_stable():
    assert compute_content_hash(b"abc") == compute_content_hash(b"abc")
    assert compute_content_hash(b"abc") != compute_content_hash(b"abd")


def test_local_storage_dedup(tmp_path: Path):
    store = LocalSnapshotStorage(tmp_path)
    uri1, h1 = store.save(official_source_id="src1", raw_bytes=b'{"a":1}', extension="json")
    uri2, h2 = store.save(official_source_id="src1", raw_bytes=b'{"a":1}', extension="json")
    assert h1 == h2
    assert Path(uri1).exists()
    # second save reuses path with same hash prefix
    assert h1[:16] in uri2
