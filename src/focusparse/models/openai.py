"""OpenAI backend.

GPT-5.x requires `max_completion_tokens` (not `max_tokens`) — see MEMORY.md.
"""

from __future__ import annotations

import os
from pathlib import Path

from focusparse.models.base import ModelResponse


class OpenAIClient:
    def __init__(
        self,
        model: str,
        max_tokens: int | None = None,
        max_completion_tokens: int | None = None,
        base_url: str | None = None,
    ) -> None:
        self.model = model
        self.max_tokens = max_tokens
        self.max_completion_tokens = max_completion_tokens or 8192
        self.base_url = base_url                        # for vLLM / sglang via VLLM_API_KEY
        self.api_key = os.environ.get("OPENAI_API_KEY")

    async def predict(
        self,
        prompt: str,
        images: list[Path] | None = None,
        system: str | None = None,
        max_tokens: int | None = None,
    ) -> ModelResponse:
        raise NotImplementedError("OpenAIClient.predict — wire in Phase 1 final")

    def count_tokens(self, text: str) -> int:
        return max(1, len(text) // 4)
