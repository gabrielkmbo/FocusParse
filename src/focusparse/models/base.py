"""Backend-agnostic model client protocol.

Every backend (anthropic, openai, gemini) implements this shape so the
pipeline stages don't care which tier runs under the hood.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from pydantic import BaseModel


class ModelResponse(BaseModel):
    text: str
    tokens_in: int = 0
    tokens_out: int = 0
    usd: float | None = None
    latency_ms: int = 0
    raw: dict | None = None  # provider-specific response for debugging


class ModelClient(Protocol):
    """What every backend must expose."""

    async def predict(
        self,
        prompt: str,
        images: list[Path] | None = None,
        system: str | None = None,
        max_tokens: int | None = None,
    ) -> ModelResponse: ...

    def count_tokens(self, text: str) -> int: ...
