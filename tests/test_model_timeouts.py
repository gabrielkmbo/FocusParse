"""Tests for provider model-call timeout guardrails."""

from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace

import pytest

from focusparse.models._timeouts import model_timeout_s
from focusparse.models.openai import OpenAIClient


def test_model_timeout_default_and_env_override(monkeypatch):
    monkeypatch.delenv("FOCUSPARSE_MODEL_TIMEOUT_S", raising=False)
    assert model_timeout_s() == 180.0

    monkeypatch.setenv("FOCUSPARSE_MODEL_TIMEOUT_S", "42.5")
    assert model_timeout_s() == 42.5

    monkeypatch.setenv("FOCUSPARSE_MODEL_TIMEOUT_S", "not-a-number")
    assert model_timeout_s() == 180.0


async def test_openai_client_wraps_provider_call_in_timeout(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("FOCUSPARSE_MODEL_TIMEOUT_S", "0.01")
    client_kwargs = {}

    class _Responses:
        async def create(self, **kwargs):
            await asyncio.sleep(2)
            raise AssertionError("provider call should have timed out")

    class _AsyncOpenAI:
        def __init__(self, **kwargs):
            client_kwargs.update(kwargs)
            self.responses = _Responses()

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(AsyncOpenAI=_AsyncOpenAI))

    with pytest.raises(TimeoutError):
        await OpenAIClient("gpt-test").predict("hello")
    assert client_kwargs["timeout"] == 1.0
