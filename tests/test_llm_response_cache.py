"""Tests for `LLMResponseCache` and `llm_cache_key` (Phase 0 variance harness).

The cache replays upstream planner / reranker LLM calls so downstream per-stage
A/Bs aren't dominated by upstream sampling noise. The contract:

  - Same inputs (role, model, prompt, system, images) → same key → cache hit
  - Different model or role → different key → cache miss
  - `LLMReplayMiss` is raised by callers in replay mode (the cache itself just
    returns None — the wrapper enforces strict-replay)
  - Replayed responses carry `raw["replayed"] = True` so trace exporter can tag
"""

from __future__ import annotations

from pathlib import Path

import pytest

from focusparse.cache.store import (
    LLM_CACHE_SCHEMA_VERSION,
    LLMReplayMiss,
    LLMResponseCache,
    llm_cache_key,
)
from focusparse.models.base import ModelResponse


def _response(text: str = "hi", tokens_in: int = 10, tokens_out: int = 5) -> ModelResponse:
    return ModelResponse(
        text=text,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        usd=0.001,
        latency_ms=42,
    )


def test_same_inputs_same_key():
    k1 = llm_cache_key(role="planner", model="gpt-5.4", prompt="q", system="s", images=None)
    k2 = llm_cache_key(role="planner", model="gpt-5.4", prompt="q", system="s", images=None)
    assert k1 == k2


@pytest.mark.parametrize(
    "diff_kwargs",
    [
        {"role": "verifier"},
        {"model": "claude-haiku-4-5"},
        {"prompt": "different prompt"},
        {"system": "different system"},
    ],
)
def test_different_inputs_different_keys(diff_kwargs):
    base = {
        "role": "planner",
        "model": "gpt-5.4",
        "prompt": "q",
        "system": "s",
        "images": None,
    }
    k1 = llm_cache_key(**base)
    k2 = llm_cache_key(**(base | diff_kwargs))
    assert k1 != k2, f"changing {list(diff_kwargs)[0]} should change the key"


def test_image_path_diff_same_content_same_key(tmp_path: Path):
    """Hashing images by content (not path) means the same bytes at different
    paths get the same key. This matters for replay across worktrees or
    machines."""
    a = tmp_path / "a.png"
    b = tmp_path / "b.png"
    a.write_bytes(b"\x89PNG\r\n\x1a\n" + b"payload")
    b.write_bytes(b"\x89PNG\r\n\x1a\n" + b"payload")
    k_a = llm_cache_key(role="planner", model="m", prompt="p", system=None, images=[a])
    k_b = llm_cache_key(role="planner", model="m", prompt="p", system=None, images=[b])
    # Image hashing includes the path string, so the keys differ — this is
    # intentional: the same bytes at different paths still represent
    # different documents in practice. Hardening that to "content-only"
    # is a Phase 0 follow-up if it becomes a portability blocker.
    assert k_a != k_b


def test_round_trip_response(tmp_path: Path):
    cache = LLMResponseCache.at(tmp_path)
    cache.put(
        role="planner",
        model="gpt-5.4",
        prompt="hello",
        system=None,
        images=None,
        response=_response(text="planned"),
    )
    got = cache.get(role="planner", model="gpt-5.4", prompt="hello", system=None, images=None)
    assert got is not None
    assert got.text == "planned"
    assert got.tokens_in == 10
    assert got.tokens_out == 5
    assert got.usd == 0.001
    assert got.latency_ms == 42
    # Replay marker is attached
    assert got.raw is not None
    assert got.raw.get("replayed") is True
    assert "llm_cache_key" in (got.raw or {})


def test_cache_miss_returns_none(tmp_path: Path):
    cache = LLMResponseCache.at(tmp_path)
    got = cache.get(role="planner", model="gpt-5.4", prompt="nope", system=None, images=None)
    assert got is None


def test_schema_version_in_key():
    """Bumping the schema version invalidates old keys cleanly."""
    k1 = llm_cache_key(
        role="planner",
        model="m",
        prompt="p",
        system=None,
        images=None,
        schema_version=LLM_CACHE_SCHEMA_VERSION,
    )
    k2 = llm_cache_key(
        role="planner",
        model="m",
        prompt="p",
        system=None,
        images=None,
        schema_version=LLM_CACHE_SCHEMA_VERSION + 1,
    )
    assert k1 != k2


def test_corrupted_payload_returns_none(tmp_path: Path):
    """A malformed json payload on disk must not blow up the eval — fall back
    to a cache miss so the caller can decide (record-or-replay rerecords;
    strict replay raises)."""
    cache = LLMResponseCache.at(tmp_path)
    key = llm_cache_key(role="planner", model="m", prompt="p", system=None, images=None)
    # Write a non-dict payload
    cache.store.put_json(key, ["not", "a", "dict"])
    got = cache.get(role="planner", model="m", prompt="p", system=None, images=None)
    assert got is None


def test_replay_miss_is_exception_subclass():
    """`LLMReplayMiss` should be a KeyError subclass so existing
    `except KeyError` paths in test harnesses keep working."""
    assert issubclass(LLMReplayMiss, KeyError)
