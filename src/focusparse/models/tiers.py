"""Tier routing: pick the right ModelClient for a given pipeline role.

Escalation is per-stage, never pipeline-wide. If a stage returns low confidence,
re-run that one stage at the next tier up. `TierRouter` tracks per-run
escalations so we cap them at `escalation.max_steps_escalated_per_run`.

`TierRouter` optionally wraps the returned client in a `CachingModelClient`
so upstream stages (planner, region reranker) can be replayed deterministically
across runs. See `LLMResponseCache` in `focusparse.cache.store` and the
variance-harness phase of plans/2026-05-11-harness-growth-sprint.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from focusparse.cache.store import LLMCacheMode, LLMReplayMiss, LLMResponseCache
from focusparse.models.anthropic import AnthropicClient
from focusparse.models.base import ModelClient, ModelResponse
from focusparse.models.gemini import GeminiClient
from focusparse.models.openai import OpenAIClient
from focusparse.utils.config import FocusConfig, TierSpec

_TIER_ORDER = ["cheap", "mid", "frontier"]

# Roles whose outputs we want deterministically replayable for per-stage A/Bs.
# Reasoner/verifier are deliberately *not* cached — those are the dependent
# variables we want to vary in downstream experiments.
DEFAULT_CACHED_ROLES = frozenset({"planner", "localizer_rerank"})


def _build_client(tier: TierSpec) -> ModelClient:
    provider = tier.provider.lower()
    if provider == "anthropic":
        return AnthropicClient(model=tier.model, max_tokens=tier.max_tokens)
    if provider == "openai":
        return OpenAIClient(
            model=tier.model,
            max_tokens=tier.max_tokens,
            max_completion_tokens=tier.max_completion_tokens,
        )
    if provider == "gemini":
        return GeminiClient(
            model=tier.model,
            max_tokens=tier.max_tokens,
            thinking_budget=tier.thinking_budget,
        )
    raise ValueError(f"Unknown provider: {tier.provider!r}")


class CachingModelClient:
    """Decorator around a `ModelClient` that records/replays via `LLMResponseCache`.

    Modes (matches `LLMCacheMode` literal):
      * ``record`` — always call the backend, always overwrite cache.
      * ``replay`` — read cache only; raise `LLMReplayMiss` on miss. Use this
        for strict reproducibility runs.
      * ``record-or-replay`` (default) — cache get; on miss, call backend and
        store. The natural day-to-day setting: the first run records and
        subsequent runs replay.

    Telemetry: a replayed response carries ``raw["replayed"] = True`` set by
    the cache itself; we additionally attach ``raw["cache_mode"]`` and
    ``raw["cache_hit"]`` so trace consumers can distinguish a fresh
    record-mode call (``cache_hit=False``) from a replayed one. We never
    overwrite tokens / usd / latency_ms — the recorded numbers stand.
    """

    def __init__(
        self,
        inner: ModelClient,
        *,
        role: str,
        model: str,
        cache: LLMResponseCache,
        mode: LLMCacheMode = "record-or-replay",
    ) -> None:
        self._inner = inner
        self._role = role
        self._model = model
        self._cache = cache
        self._mode: LLMCacheMode = mode

    async def predict(
        self,
        prompt: str,
        images: list[Path] | None = None,
        system: str | None = None,
        max_tokens: int | None = None,
    ) -> ModelResponse:
        if self._mode in ("replay", "record-or-replay"):
            cached = self._cache.get(
                role=self._role,
                model=self._model,
                prompt=prompt,
                system=system,
                images=images,
            )
            if cached is not None:
                return self._tag(cached, hit=True)
            if self._mode == "replay":
                raise LLMReplayMiss(
                    f"LLM cache miss for role={self._role!r} model={self._model!r} "
                    "in strict-replay mode. The upstream input shifted "
                    "(prompt / system / images / schema). Re-record by running "
                    "with --llm-cache-mode record-or-replay against a fresh "
                    "or shared cache dir."
                )

        response = await self._inner.predict(
            prompt=prompt, images=images, system=system, max_tokens=max_tokens
        )
        if self._mode in ("record", "record-or-replay"):
            self._cache.put(
                role=self._role,
                model=self._model,
                prompt=prompt,
                system=system,
                images=images,
                response=response,
            )
        return self._tag(response, hit=False)

    def count_tokens(self, text: str) -> int:
        return self._inner.count_tokens(text)

    def _tag(self, response: ModelResponse, *, hit: bool) -> ModelResponse:
        raw = dict(response.raw or {})
        raw["cache_mode"] = self._mode
        raw["cache_hit"] = hit
        return response.model_copy(update={"raw": raw})


class TierRouter:
    """Resolves a role name → concrete ModelClient at the configured tier.

    When ``llm_cache`` is provided, `client_for(role)` wraps the resolved
    client in a `CachingModelClient` for roles in ``cached_roles``. Roles
    outside the cache set (e.g. ``reasoner``, ``verifier``) get the raw
    client unchanged so we never accidentally cache the dependent variable.
    """

    def __init__(
        self,
        config: FocusConfig,
        *,
        llm_cache: LLMResponseCache | None = None,
        llm_cache_mode: LLMCacheMode = "record-or-replay",
        cached_roles: frozenset[str] | set[str] | None = None,
    ) -> None:
        self.config = config
        self._cache: dict[str, ModelClient] = {}
        self._escalations_used = 0
        self.llm_cache = llm_cache
        self.llm_cache_mode: LLMCacheMode = llm_cache_mode
        self.cached_roles = (
            frozenset(cached_roles) if cached_roles is not None else DEFAULT_CACHED_ROLES
        )

    def client_for(self, role: str, *, escalate: bool = False) -> ModelClient:
        tier_spec = self.config.tier_for(role)
        tier_name = self._tier_name_for_spec(tier_spec)
        if escalate:
            if self._escalations_used >= self.config.escalation.max_steps_escalated_per_run:
                # cap reached — fall back to the assigned tier
                escalate = False
            else:
                idx = _TIER_ORDER.index(tier_name)
                if idx < len(_TIER_ORDER) - 1:
                    tier_name = _TIER_ORDER[idx + 1]
                    tier_spec = self.config.tiers[tier_name]
                    self._escalations_used += 1
        cache_key = f"{role}:{tier_name}" if escalate else tier_name
        if cache_key not in self._cache:
            self._cache[cache_key] = _build_client(tier_spec)
        client = self._cache[cache_key]
        if self.llm_cache is not None and role in self.cached_roles:
            return CachingModelClient(
                client,
                role=role,
                model=tier_spec.model,
                cache=self.llm_cache,
                mode=self.llm_cache_mode,
            )
        return client

    def _tier_name_for_spec(self, spec: TierSpec) -> str:
        for name, s in self.config.tiers.items():
            if s is spec or (s.provider == spec.provider and s.model == spec.model):
                return name
        raise ValueError(f"Tier spec not found in config: {spec!r}")

    def snapshot(self) -> dict[str, Any]:
        snap: dict[str, Any] = {"escalations_used": self._escalations_used}
        if self.llm_cache is not None:
            snap["llm_cache_mode"] = self.llm_cache_mode
            snap["llm_cached_roles"] = sorted(self.cached_roles)
        return snap
