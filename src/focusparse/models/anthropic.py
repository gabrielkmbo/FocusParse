"""Anthropic backend (anthropic SDK).

Claude models accept image inputs as base64 blocks. Token usage is returned
under `response.usage`. No prompt caching in v1.
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
        if not self.api_key:
            raise RuntimeError("ANTHROPIC_API_KEY not set; cannot call Anthropic.")
        from anthropic import AsyncAnthropic

        timeout_s = model_timeout_s()
        client = AsyncAnthropic(api_key=self.api_key, timeout=timeout_s)

        content: list[dict[str, Any]] = []
        for img_path in images or []:
            data = Path(img_path).read_bytes()
            b64 = base64.b64encode(data).decode("ascii")
            content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": b64,
                    },
                }
            )
        content.append({"type": "text", "text": prompt})

        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens or self.max_tokens,
            "messages": [{"role": "user", "content": content}],
        }
        if system:
            kwargs["system"] = system

        t0 = time.perf_counter()
        async with asyncio.timeout(timeout_s):
            resp = await client.messages.create(**kwargs)
        latency_ms = int((time.perf_counter() - t0) * 1000)

        text = ""
        for block in getattr(resp, "content", []) or []:
            if getattr(block, "type", None) == "text":
                text += getattr(block, "text", "") or ""

        usage = getattr(resp, "usage", None)
        tokens_in = int(getattr(usage, "input_tokens", 0) or 0) if usage else 0
        tokens_out = int(getattr(usage, "output_tokens", 0) or 0) if usage else 0
        usd = compute_usd("anthropic", self.model, tokens_in, tokens_out)

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
