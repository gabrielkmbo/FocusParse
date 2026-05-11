"""Content-addressed on-disk cache.

Every tool checks the cache first via `key = sha256(doc_id, page, bbox_quant, dpi, mode)`.
Cache hits are free and deterministic across runs.

`LLMResponseCache` extends the same disk layout to upstream LLM stages (planner,
region reranker) so per-stage A/Bs aren't dominated by upstream sampling noise.
See `plans/2026-05-11-harness-growth-sprint.md` Phase 0.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Literal

from focusparse.models.base import ModelResponse

# Bumped when the on-disk cache schema for LLMResponseCache changes in a
# backward-incompatible way. Included in every cache key so old caches
# silently miss instead of returning stale shapes.
LLM_CACHE_SCHEMA_VERSION = 1

LLMCacheMode = Literal["record", "replay", "record-or-replay"]


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


class LLMReplayMiss(KeyError):
    """Raised when `LLMResponseCache.get(...)` is called in replay mode and the
    key is not on disk.

    Replay mode never silently calls the backend — a miss is the signal that
    the upstream input shifted (different prompt, different model, different
    images, schema version bump) and the run is no longer reproducing the
    pinned trajectory.
    """


def _hash_text(text: str | None) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _hash_images(images: list[Path] | None) -> str:
    """Hash images by content (file bytes) so the cache key survives a
    different working directory layout. Missing files hash as their path
    so a deliberately-missing-fixture test still has a stable key.
    """
    if not images:
        return "no_images"
    digest = hashlib.sha256()
    for img in images:
        p = Path(img)
        digest.update(str(p).encode("utf-8"))
        digest.update(b"\0")
        try:
            digest.update(p.read_bytes())
        except (FileNotFoundError, IsADirectoryError, PermissionError):
            digest.update(b"missing")
        digest.update(b"\0")
    return digest.hexdigest()


def llm_cache_key(
    *,
    role: str,
    model: str,
    prompt: str,
    system: str | None,
    images: list[Path] | None,
    schema_version: int = LLM_CACHE_SCHEMA_VERSION,
) -> str:
    """Deterministic content key for an LLM call.

    Includes `role` so a cache shared across stages cannot collide (same
    prompt, different role). Includes `model` so cached planner outputs do
    not replay across model swaps. Includes the schema version so format
    bumps invalidate cleanly.
    """
    return cache_key(
        schema_version=schema_version,
        role=role,
        model=model,
        prompt_sha=_hash_text(prompt),
        system_sha=_hash_text(system),
        images_sha=_hash_images(images),
    )


class LLMResponseCache:
    """Disk-backed cache for `ModelResponse` payloads keyed by call inputs.

    Wraps a `CacheStore` and stores responses as JSON under
    `<root>/json/<sha>.json`. Replay markers (`replayed=True`) are
    attached on read so the trace exporter can distinguish recorded
    versus replayed calls.
    """

    def __init__(self, store: CacheStore) -> None:
        self.store = store

    @classmethod
    def at(cls, root: Path | str) -> LLMResponseCache:
        return cls(CacheStore(Path(root)))

    def get(
        self,
        *,
        role: str,
        model: str,
        prompt: str,
        system: str | None,
        images: list[Path] | None,
    ) -> ModelResponse | None:
        key = llm_cache_key(role=role, model=model, prompt=prompt, system=system, images=images)
        raw = self.store.get_json(key)
        if raw is None:
            return None
        payload = raw.get("response") if isinstance(raw, dict) else None
        if not isinstance(payload, dict):
            return None
        response = ModelResponse.model_validate(payload)
        # Tag the response so downstream telemetry can see this was replayed
        # without changing the recorded tokens / usd / latency_ms.
        existing_raw = response.raw or {}
        existing_raw = dict(existing_raw)
        existing_raw["replayed"] = True
        existing_raw["llm_cache_key"] = key
        return response.model_copy(update={"raw": existing_raw})

    def put(
        self,
        *,
        role: str,
        model: str,
        prompt: str,
        system: str | None,
        images: list[Path] | None,
        response: ModelResponse,
    ) -> str:
        key = llm_cache_key(role=role, model=model, prompt=prompt, system=system, images=images)
        self.store.put_json(
            key,
            {
                "schema_version": LLM_CACHE_SCHEMA_VERSION,
                "role": role,
                "model": model,
                "response": response.model_dump(mode="json"),
            },
        )
        return key
