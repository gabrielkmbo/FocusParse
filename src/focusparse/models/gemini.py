"""Gemini backend (google-genai SDK).

Gemini 2.5/3.x requires `thinking_budget ≥ 1024` or the visible response will
be empty — all output tokens spend silently on hidden reasoning. Config
default is 1024, override per-call via the constructor.

Image inputs are uploaded as inline `Part.from_bytes`. No caching or batch
mode in v1 — one predict call == one API round-trip.
"""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from typing import Any

from focusparse.eval.pricing import compute_usd
from focusparse.models._timeouts import model_timeout_s
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
        # Accept either env var — CLAUDE.md says GOOGLE_API_KEY, some parser-bench
        # scripts use GEMINI_API_KEY. Prefer GEMINI_API_KEY if both set.
        self.api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")

    async def predict(
        self,
        prompt: str,
        images: list[Path] | None = None,
        system: str | None = None,
        max_tokens: int | None = None,
    ) -> ModelResponse:
        if not self.api_key:
            raise RuntimeError("GEMINI_API_KEY (or GOOGLE_API_KEY) not set; cannot call Gemini.")
        # Deferred import so `focus status` works without the SDK installed.
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=self.api_key)

        parts: list[Any] = []
        for img_path in images or []:
            data = Path(img_path).read_bytes()
            parts.append(types.Part.from_bytes(data=data, mime_type="image/png"))
        parts.append(types.Part.from_text(text=prompt))

        gen_config_kwargs: dict[str, Any] = {
            "max_output_tokens": max_tokens or self.max_tokens,
            "thinking_config": types.ThinkingConfig(thinking_budget=self.thinking_budget),
        }
        if system:
            gen_config_kwargs["system_instruction"] = system

        t0 = time.perf_counter()
        async with asyncio.timeout(model_timeout_s()):
            response = await client.aio.models.generate_content(
                model=self.model,
                contents=[types.Content(parts=parts, role="user")],
                config=types.GenerateContentConfig(**gen_config_kwargs),
            )
        latency_ms = int((time.perf_counter() - t0) * 1000)

        text = response.text or ""
        usage = getattr(response, "usage_metadata", None)
        tokens_in = int(getattr(usage, "prompt_token_count", 0) or 0) if usage else 0
        tokens_out = int(getattr(usage, "candidates_token_count", 0) or 0) if usage else 0
        usd = compute_usd("gemini", self.model, tokens_in, tokens_out)

        return ModelResponse(
            text=text,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            usd=usd,
            latency_ms=latency_ms,
            raw=None,
        )

    def count_tokens(self, text: str) -> int:
        return max(1, len(text) // 4)
