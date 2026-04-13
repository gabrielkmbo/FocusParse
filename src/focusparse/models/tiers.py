"""Tier routing: pick the right ModelClient for a given pipeline role.

Escalation is per-stage, never pipeline-wide. If a stage returns low confidence,
re-run that one stage at the next tier up. `TierRouter` tracks per-run
escalations so we cap them at `escalation.max_steps_escalated_per_run`.
"""

from __future__ import annotations

from typing import Any

from focusparse.models.anthropic import AnthropicClient
from focusparse.models.base import ModelClient
from focusparse.models.gemini import GeminiClient
from focusparse.models.openai import OpenAIClient
from focusparse.utils.config import FocusConfig, TierSpec

_TIER_ORDER = ["cheap", "mid", "frontier"]


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


class TierRouter:
    """Resolves a role name → concrete ModelClient at the configured tier."""

    def __init__(self, config: FocusConfig) -> None:
        self.config = config
        self._cache: dict[str, ModelClient] = {}
        self._escalations_used = 0

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
        return self._cache[cache_key]

    def _tier_name_for_spec(self, spec: TierSpec) -> str:
        for name, s in self.config.tiers.items():
            if s is spec or (s.provider == spec.provider and s.model == spec.model):
                return name
        raise ValueError(f"Tier spec not found in config: {spec!r}")

    def snapshot(self) -> dict[str, Any]:
        return {"escalations_used": self._escalations_used}
