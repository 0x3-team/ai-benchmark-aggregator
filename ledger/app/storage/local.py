from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path


def compute_content_hash(raw_bytes: bytes) -> str:
    return hashlib.sha256(raw_bytes).hexdigest()


class LocalSnapshotStorage:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def save(
        self,
        *,
        official_source_id: str,
        raw_bytes: bytes,
        extension: str,
    ) -> tuple[str, str]:
        """Return (uri, content_hash)."""
        content_hash = compute_content_hash(raw_bytes)
        source_dir = self.root / official_source_id
        source_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        ext = extension.lstrip(".") or "bin"
        path = source_dir / f"{ts}_{content_hash[:16]}.{ext}"
        # Dedup by hash filename pattern: if any file with same hash exists, reuse
        for existing in source_dir.glob(f"*_{content_hash[:16]}.*"):
            return str(existing), content_hash
        path.write_bytes(raw_bytes)
        return str(path), content_hash

    def read(self, uri: str) -> bytes:
        return Path(uri).read_bytes()
