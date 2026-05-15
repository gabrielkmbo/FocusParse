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
from focusparse.models._retry import retry_transient_model_call
from focusparse.models._timeouts import model_timeout_s
from focusparse.models.base import ModelResponse
from focusparse.models.images import read_model_image_bytes


class GeminiClient:
    def __init__(
        self,
        model: str,
        max_tokens: int | None = None,
        thinking_budget: int | None = None,
        thinking_level: str | None = None,
        media_resolution: str | None = None,
    ) -> None:
        self.model = model
        self.max_tokens = max_tokens or 4096
        self.thinking_budget = thinking_budget or 1024
        self.thinking_level = thinking_level
        self.media_resolution = media_resolution
        # Accept either env var — CLAUDE.md says GOOGLE_API_KEY, some parser-bench
        # scripts use GEMINI_API_KEY. Prefer GEMINI_API_KEY if both set.
        self.api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")

    async def predict(
        self,
        prompt: str,
        images: list[Path] | None = None,
        system: str | None = None,
        max_tokens: int | None = None,
        response_schema: Any | None = None,
    ) -> ModelResponse:
        if not self.api_key:
            raise RuntimeError("GEMINI_API_KEY (or GOOGLE_API_KEY) not set; cannot call Gemini.")
        # Deferred import so `focus status` works without the SDK installed.
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=self.api_key)

        parts: list[Any] = []
        for img_path in images or []:
            data = read_model_image_bytes(Path(img_path))
            parts.append(types.Part.from_bytes(data=data, mime_type="image/png"))
        parts.append(types.Part.from_text(text=prompt))

        gen_config_kwargs: dict[str, Any] = {
            "max_output_tokens": max_tokens or self.max_tokens,
            "thinking_config": _thinking_config(
                types,
                thinking_budget=self.thinking_budget,
                thinking_level=self.thinking_level,
            ),
        }
        media_resolution = _media_resolution(types, self.media_resolution)
        if media_resolution is not None:
            gen_config_kwargs["media_resolution"] = media_resolution
        if response_schema is not None:
            gen_config_kwargs["response_mime_type"] = "application/json"
            gen_config_kwargs["response_schema"] = response_schema
        if system:
            gen_config_kwargs["system_instruction"] = system

        t0 = time.perf_counter()
        timeout_s = model_timeout_s()

        async def _generate_content():
            async with asyncio.timeout(timeout_s):
                return await client.aio.models.generate_content(
                    model=self.model,
                    contents=[types.Content(parts=parts, role="user")],
                    config=types.GenerateContentConfig(**gen_config_kwargs),
                )

        response = await retry_transient_model_call("gemini", _generate_content)
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


def _thinking_config(types: Any, *, thinking_budget: int, thinking_level: str | None) -> Any:
    if thinking_level:
        level = _enum_value(types.ThinkingLevel, thinking_level, prefix="THINKING_LEVEL")
        return types.ThinkingConfig(thinking_level=level)
    return types.ThinkingConfig(thinking_budget=thinking_budget)


def _media_resolution(types: Any, value: str | None) -> Any | None:
    if not value:
        return None
    return _enum_value(types.MediaResolution, value, prefix="MEDIA_RESOLUTION")


def _enum_value(enum_type: Any, value: str, *, prefix: str) -> Any:
    normalized = str(value).strip().upper().replace("-", "_").replace(" ", "_")
    candidates = [normalized]
    if not normalized.startswith(prefix):
        candidates.append(f"{prefix}_{normalized}")
    for candidate in candidates:
        if hasattr(enum_type, candidate):
            return getattr(enum_type, candidate)
    valid = ", ".join(getattr(item, "name", str(item)) for item in enum_type)
    raise ValueError(f"Unsupported Gemini enum value {value!r}; expected one of: {valid}")
