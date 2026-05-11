"""Tests for `CachingModelClient` + `TierRouter` LLM-cache wrap (Phase 0).

We exercise the three modes:

  * record-or-replay (default) — miss calls backend + records; hit replays.
  * replay — miss raises `LLMReplayMiss`; never touches the backend.
  * record — always calls the backend, always writes the cache.

Plus the TierRouter contract: cache wraps only the configured roles
(default: planner, localizer_rerank). Reasoner/verifier get the raw client.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from focusparse.cache.store import LLMReplayMiss, LLMResponseCache
from focusparse.models.base import ModelResponse
from focusparse.models.tiers import (
    DEFAULT_CACHED_ROLES,
    CachingModelClient,
    TierRouter,
)


class _StubClient:
    """Counts predict() calls + returns a deterministic response."""

    def __init__(self, text: str = "live") -> None:
        self.text = text
        self.calls: int = 0

    async def predict(
        self,
        prompt: str,
        images: list[Path] | None = None,
        system: str | None = None,
        max_tokens: int | None = None,
    ) -> ModelResponse:
        self.calls += 1
        return ModelResponse(
            text=f"{self.text}:{prompt}",
            tokens_in=10,
            tokens_out=5,
            usd=0.001,
            latency_ms=42,
        )

    def count_tokens(self, text: str) -> int:
        return len(text)


@pytest.mark.asyncio
async def test_record_or_replay_records_then_replays(tmp_path: Path) -> None:
    cache = LLMResponseCache.at(tmp_path)
    inner = _StubClient()
    cached = CachingModelClient(
        inner, role="planner", model="m", cache=cache, mode="record-or-replay"
    )

    first = await cached.predict(prompt="q", system="s")
    assert inner.calls == 1
    assert first.text == "live:q"
    # First call recorded; tag says cache_hit=False
    assert first.raw == {"cache_mode": "record-or-replay", "cache_hit": False}

    second = await cached.predict(prompt="q", system="s")
    # Backend not hit again
    assert inner.calls == 1
    assert second.text == "live:q"
    # Cache-hit tag + replay marker
    assert second.raw is not None
    assert second.raw.get("cache_hit") is True
    assert second.raw.get("replayed") is True


@pytest.mark.asyncio
async def test_replay_mode_miss_raises_replay_miss(tmp_path: Path) -> None:
    cache = LLMResponseCache.at(tmp_path)
    inner = _StubClient()
    cached = CachingModelClient(inner, role="planner", model="m", cache=cache, mode="replay")

    with pytest.raises(LLMReplayMiss):
        await cached.predict(prompt="q", system="s")
    # Backend must not be called in strict replay mode
    assert inner.calls == 0


@pytest.mark.asyncio
async def test_replay_mode_hit_returns_cached(tmp_path: Path) -> None:
    cache = LLMResponseCache.at(tmp_path)
    # Pre-populate
    cache.put(
        role="planner",
        model="m",
        prompt="q",
        system="s",
        images=None,
        response=ModelResponse(text="recorded", tokens_in=1, tokens_out=2),
    )
    inner = _StubClient()
    cached = CachingModelClient(inner, role="planner", model="m", cache=cache, mode="replay")
    got = await cached.predict(prompt="q", system="s")
    assert got.text == "recorded"
    assert inner.calls == 0
    assert got.raw is not None
    assert got.raw.get("cache_hit") is True


@pytest.mark.asyncio
async def test_record_mode_always_calls_backend(tmp_path: Path) -> None:
    cache = LLMResponseCache.at(tmp_path)
    inner = _StubClient()
    cached = CachingModelClient(inner, role="planner", model="m", cache=cache, mode="record")

    await cached.predict(prompt="q", system="s")
    await cached.predict(prompt="q", system="s")
    # Two backend calls — record mode bypasses replay
    assert inner.calls == 2


@pytest.mark.asyncio
async def test_different_role_separates_cache(tmp_path: Path) -> None:
    cache = LLMResponseCache.at(tmp_path)
    inner_planner = _StubClient(text="planner_out")
    inner_reranker = _StubClient(text="reranker_out")
    planner = CachingModelClient(
        inner_planner, role="planner", model="m", cache=cache, mode="record-or-replay"
    )
    reranker = CachingModelClient(
        inner_reranker, role="localizer_rerank", model="m", cache=cache, mode="record-or-replay"
    )
    a = await planner.predict(prompt="q", system="s")
    b = await reranker.predict(prompt="q", system="s")
    # Both backends called: keys are role-scoped
    assert inner_planner.calls == 1
    assert inner_reranker.calls == 1
    assert a.text == "planner_out:q"
    assert b.text == "reranker_out:q"


# --- TierRouter wrap ---------------------------------------------------------


class _FakeTierSpec:
    def __init__(self, provider: str, model: str) -> None:
        self.provider = provider
        self.model = model
        self.max_tokens = 100
        self.max_completion_tokens = 100
        self.thinking_budget = 1024


class _FakeConfig:
    def __init__(
        self, role_to_tier: dict[str, str], tier_to_spec: dict[str, _FakeTierSpec]
    ) -> None:
        self.tiers = tier_to_spec
        self._role_to_tier = role_to_tier

        class _Esc:
            max_steps_escalated_per_run = 1

        self.escalation = _Esc()

    def tier_for(self, role: str) -> _FakeTierSpec:
        return self.tiers[self._role_to_tier[role]]


def _patched_build_client(monkeypatch) -> dict[str, _StubClient]:
    """Replace `_build_client` with a stub factory; track issued clients
    by `(provider, model)` so tests can introspect."""
    issued: dict[str, _StubClient] = {}

    def fake_build(tier):
        key = f"{tier.provider}:{tier.model}"
        c = _StubClient(text=key)
        issued[key] = c
        return c

    monkeypatch.setattr("focusparse.models.tiers._build_client", fake_build)
    return issued


@pytest.mark.asyncio
async def test_tier_router_wraps_only_cached_roles(monkeypatch, tmp_path: Path) -> None:
    issued = _patched_build_client(monkeypatch)
    cfg = _FakeConfig(
        role_to_tier={
            "planner": "cheap",
            "localizer_rerank": "mid",
            "reasoner": "frontier",
            "verifier": "mid",
        },
        tier_to_spec={
            "cheap": _FakeTierSpec("gemini", "gemini-2.5-flash"),
            "mid": _FakeTierSpec("anthropic", "claude-haiku-4-5"),
            "frontier": _FakeTierSpec("openai", "gpt-5.4"),
        },
    )

    cache = LLMResponseCache.at(tmp_path)
    router = TierRouter(cfg, llm_cache=cache, llm_cache_mode="record-or-replay")

    planner = router.client_for("planner")
    reranker = router.client_for("localizer_rerank")
    reasoner = router.client_for("reasoner")

    assert isinstance(planner, CachingModelClient)
    assert isinstance(reranker, CachingModelClient)
    # Reasoner is NOT wrapped — it is the dependent variable for downstream A/Bs
    assert not isinstance(reasoner, CachingModelClient)

    # The underlying stubs are the ones issued by the build helper
    assert issued["gemini:gemini-2.5-flash"] is planner._inner  # type: ignore[attr-defined]
    assert issued["openai:gpt-5.4"] is reasoner


@pytest.mark.asyncio
async def test_tier_router_no_cache_returns_raw_clients(monkeypatch) -> None:
    _patched_build_client(monkeypatch)
    cfg = _FakeConfig(
        role_to_tier={"planner": "cheap", "reasoner": "frontier"},
        tier_to_spec={
            "cheap": _FakeTierSpec("gemini", "gemini-2.5-flash"),
            "frontier": _FakeTierSpec("openai", "gpt-5.4"),
        },
    )
    router = TierRouter(cfg)  # no llm_cache
    planner = router.client_for("planner")
    assert not isinstance(planner, CachingModelClient)


def test_default_cached_roles_are_upstream() -> None:
    """Sanity-check: the default cached-role set is exactly planner + rerank.
    Adding reasoner/verifier to this set is a research bug; this test exists
    so a future edit has to update the literal and explain why."""
    assert frozenset({"planner", "localizer_rerank"}) == DEFAULT_CACHED_ROLES


def test_tier_router_snapshot_includes_cache_mode(monkeypatch, tmp_path: Path) -> None:
    _patched_build_client(monkeypatch)
    cfg = _FakeConfig(
        role_to_tier={"planner": "cheap"},
        tier_to_spec={"cheap": _FakeTierSpec("gemini", "gemini-2.5-flash")},
    )
    router = TierRouter(
        cfg,
        llm_cache=LLMResponseCache.at(tmp_path),
        llm_cache_mode="replay",
        cached_roles={"planner"},
    )
    snap = router.snapshot()
    assert snap["llm_cache_mode"] == "replay"
    assert snap["llm_cached_roles"] == ["planner"]
