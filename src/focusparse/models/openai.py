"""OpenAI backend (openai SDK, Responses API).

GPT-5.x lives on the Responses API and requires `max_output_tokens`
(or `max_completion_tokens` for chat.completions), **not** `max_tokens`. This
client uses Responses API with multimodal input.

We accept a `base_url` override so the same client can target vLLM / sglang
OSS-VLM endpoints exposing an OpenAI-compatible API (useful post-FocusTrain).
"""

from __future__ import annotations

import asyncio
import base64
import os
import time
from pathlib import Path
from typing import Any

from focusparse.eval.pricing import compute_usd
from focusparse.models._timeouts import model_timeout_s
from focusparse.models.base import ModelResponse
from focusparse.models.images import read_model_image_bytes


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
        self.base_url = base_url
        self.api_key = os.environ.get("OPENAI_API_KEY")

    async def predict(
        self,
        prompt: str,
        images: list[Path] | None = None,
        system: str | None = None,
        max_tokens: int | None = None,
    ) -> ModelResponse:
        if not self.api_key and not self.base_url:
            raise RuntimeError("OPENAI_API_KEY not set; cannot call OpenAI.")
        from openai import AsyncOpenAI

        timeout_s = model_timeout_s()
        client_kwargs: dict[str, Any] = {"api_key": self.api_key, "timeout": timeout_s}
        if self.base_url:
            client_kwargs["base_url"] = self.base_url
        client = AsyncOpenAI(**client_kwargs)

        user_content: list[dict[str, Any]] = []
        for img_path in images or []:
            data = read_model_image_bytes(Path(img_path))
            b64 = base64.b64encode(data).decode("ascii")
            user_content.append(
                {"type": "input_image", "image_url": f"data:image/png;base64,{b64}"}
            )
        user_content.append({"type": "input_text", "text": prompt})

        input_messages: list[dict[str, Any]] = []
        if system:
            input_messages.append(
                {"role": "system", "content": [{"type": "input_text", "text": system}]}
            )
        input_messages.append({"role": "user", "content": user_content})

        t0 = time.perf_counter()
        async with asyncio.timeout(timeout_s):
            resp = await client.responses.create(
                model=self.model,
                input=input_messages,
                max_output_tokens=max_tokens or self.max_completion_tokens,
            )
        latency_ms = int((time.perf_counter() - t0) * 1000)

        text = getattr(resp, "output_text", None) or ""
        usage = getattr(resp, "usage", None)
        tokens_in = int(getattr(usage, "input_tokens", 0) or 0) if usage else 0
        tokens_out = int(getattr(usage, "output_tokens", 0) or 0) if usage else 0
        usd = compute_usd("openai", self.model, tokens_in, tokens_out)

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
