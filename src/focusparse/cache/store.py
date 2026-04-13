"""Content-addressed on-disk cache.

Every tool checks the cache first via `key = sha256(doc_id, page, bbox_quant, dpi, mode)`.
Cache hits are free and deterministic across runs.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def cache_key(**parts: Any) -> str:
    """Deterministic sha256 key over keyword parts. Floats are quantized to 4dp."""
    canonical: dict[str, Any] = {}
    for k, v in sorted(parts.items()):
        if isinstance(v, float):
            canonical[k] = round(v, 4)
        elif isinstance(v, (list, tuple)):
            canonical[k] = [round(x, 4) if isinstance(x, float) else x for x in v]
        else:
            canonical[k] = v
    payload = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class CacheStore:
    """Disk-backed cache for crops, OCR, layout, embeddings.

    Layout:
        <root>/
          blobs/<sha256[:2]>/<sha256>              # binary blobs (PNG, etc.)
          json/<sha256[:2]>/<sha256>.json          # JSON-serializable outputs
    """

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        (self.root / "blobs").mkdir(parents=True, exist_ok=True)
        (self.root / "json").mkdir(parents=True, exist_ok=True)

    def _blob_path(self, key: str) -> Path:
        return self.root / "blobs" / key[:2] / key

    def _json_path(self, key: str) -> Path:
        return self.root / "json" / key[:2] / f"{key}.json"

    # --- blob API --------------------------------------------------------

    def has_blob(self, key: str) -> bool:
        return self._blob_path(key).exists()

    def get_blob(self, key: str) -> bytes | None:
        p = self._blob_path(key)
        if not p.exists():
            return None
        return p.read_bytes()

    def put_blob(self, key: str, data: bytes) -> Path:
        p = self._blob_path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return p

    # --- json API --------------------------------------------------------

    def get_json(self, key: str) -> Any | None:
        p = self._json_path(key)
        if not p.exists():
            return None
        return json.loads(p.read_text())

    def put_json(self, key: str, value: Any) -> Path:
        p = self._json_path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(value, default=str))
        return p
