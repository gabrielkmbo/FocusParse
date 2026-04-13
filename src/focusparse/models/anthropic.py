"""Anthropic backend.

TODO(Phase 1 final): wire real Anthropic SDK calls + token usage propagation +
USD via focusparse.eval.pricing.
"""

from __future__ import annotations

import os
from pathlib import Path

from focusparse.models.base import ModelResponse


class AnthropicClient:
    def __init__(self, model: str, max_tokens: int | None = None) -> None:
        self.model = model
        self.max_tokens = max_tokens or 4096
        self.api_key = os.environ.get("ANTHROPIC_API_KEY")

    async def predict(
        self,
        prompt: str,
        images: list[Path] | None = None,
        system: str | None = None,
        max_tokens: int | None = None,
    ) -> ModelResponse:
        raise NotImplementedError("AnthropicClient.predict — wire in Phase 1 final")

    def count_tokens(self, text: str) -> int:
        # Approximate: 1 token ≈ 4 chars. Real impl: use anthropic.tokenizers.
        return max(1, len(text) // 4)
