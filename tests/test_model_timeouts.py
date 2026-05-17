"""Tests for provider model-call timeout guardrails."""

from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace

import pytest

from focusparse.models._retry import (
    is_model_throttle_error,
    is_quota_exhausted_model_error,
    is_transient_model_error,
    retry_transient_model_call,
)
from focusparse.models._timeouts import model_retry_attempts, model_timeout_s
from focusparse.models.openai import OpenAIClient


def test_model_timeout_default_and_env_override(monkeypatch):
    monkeypatch.delenv("FOCUSPARSE_MODEL_TIMEOUT_S", raising=False)
    assert model_timeout_s() == 180.0

    monkeypatch.setenv("FOCUSPARSE_MODEL_TIMEOUT_S", "42.5")
    assert model_timeout_s() == 42.5

    monkeypatch.setenv("FOCUSPARSE_MODEL_TIMEOUT_S", "not-a-number")
    assert model_timeout_s() == 180.0


def test_model_retry_attempts_default_and_env_override(monkeypatch):
    monkeypatch.delenv("FOCUSPARSE_MODEL_RETRY_ATTEMPTS", raising=False)
    monkeypatch.delenv("FOCUSPARSE_MODEL_RETRIES", raising=False)
    assert model_retry_attempts() == 2

    monkeypatch.setenv("FOCUSPARSE_MODEL_RETRY_ATTEMPTS", "4")
    assert model_retry_attempts() == 4

    monkeypatch.setenv("FOCUSPARSE_MODEL_RETRY_ATTEMPTS", "not-a-number")
    assert model_retry_attempts() == 2

    monkeypatch.delenv("FOCUSPARSE_MODEL_RETRY_ATTEMPTS", raising=False)
    monkeypatch.setenv("FOCUSPARSE_MODEL_RETRIES", "3")
    assert model_retry_attempts() == 3


async def test_retry_transient_model_call_retries_timeout(monkeypatch):
    monkeypatch.setenv("FOCUSPARSE_MODEL_RETRY_ATTEMPTS", "2")
    monkeypatch.setenv("FOCUSPARSE_MODEL_RETRY_SLEEP_S", "0")
    calls = 0

    async def _call():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise TimeoutError("timed out")
        return "ok"

    assert await retry_transient_model_call("test", _call) == "ok"
    assert calls == 2


async def test_retry_transient_model_call_does_not_retry_non_transient(monkeypatch):
    monkeypatch.setenv("FOCUSPARSE_MODEL_RETRY_ATTEMPTS", "3")
    calls = 0

    async def _call():
        nonlocal calls
        calls += 1
        raise ValueError("bad request")

    with pytest.raises(ValueError):
        await retry_transient_model_call("test", _call)
    assert calls == 1


def test_transient_model_error_detects_network_unreachable():
    assert is_transient_model_error(OSError(51, "Network is unreachable"))


def test_transient_model_error_detects_rate_limit_marker():
    class ProviderRateLimitError(Exception):
        pass

    assert is_transient_model_error(
        ProviderRateLimitError("429 Too Many Requests: rate_limit_error")
    )
    assert is_model_throttle_error(ProviderRateLimitError("429 Too Many Requests"))


def test_transient_model_error_detects_gemini_unavailable():
    class ServerError(Exception):
        pass

    ServerError.__module__ = "google.genai.errors"
    exc = ServerError(
        "503 UNAVAILABLE. {'error': {'code': 503, 'message': "
        "'The service is currently unavailable.', 'status': 'UNAVAILABLE'}}"
    )
    assert is_transient_model_error(exc)
    assert not is_model_throttle_error(exc)


def test_quota_exhaustion_is_not_treated_as_retryable_transient():
    class ProviderQuotaError(Exception):
        pass

    exc = ProviderQuotaError(
        "429 RESOURCE_EXHAUSTED: You exceeded your current quota. "
        "Quota exceeded for metric GenerateRequestsPerDayPerProjectPerModel-FreeTier."
    )
    assert is_model_throttle_error(exc)
    assert is_quota_exhausted_model_error(exc)
    assert not is_transient_model_error(exc)


async def test_retry_transient_model_call_does_not_retry_daily_quota(monkeypatch):
    monkeypatch.setenv("FOCUSPARSE_MODEL_RETRY_ATTEMPTS", "3")
    calls = 0

    async def _call():
        nonlocal calls
        calls += 1
        raise RuntimeError("quota exceeded for requests per day")

    with pytest.raises(RuntimeError):
        await retry_transient_model_call("test", _call)
    assert calls == 1


async def test_openai_client_wraps_provider_call_in_timeout(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("FOCUSPARSE_MODEL_TIMEOUT_S", "0.01")
    monkeypatch.setenv("FOCUSPARSE_MODEL_RETRY_ATTEMPTS", "1")
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
