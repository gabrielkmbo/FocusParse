"""Gemini backend.

Gemini 2.5/3.x requires `thinking_budget ≥ 1024` or the visible response will
be empty (all output tokens go to hidden reasoning). See MEMORY.md.
"""

from __future__ import annotations

import os
from pathlib import Path

from focusparse.models.base import ModelResponse


class GeminiClient:
    def __init__(
        self,
        model: str,
        max_tokens: int | None = None,
        thinking_budget: int | None = None,
    ) -> None:
        self.model = model
        self.max_tokens = max_tokens or 4096
        self.thinking_budget = thinking_budget or 1024
        self.api_key = os.environ.get("GEMINI_API_KEY")

    async def predict(
        self,
        prompt: str,
        images: list[Path] | None = None,
        system: str | None = None,
        max_tokens: int | None = None,
    ) -> ModelResponse:
        raise NotImplementedError("GeminiClient.predict — wire in Phase 1 final")

    def count_tokens(self, text: str) -> int:
        return max(1, len(text) // 4)
