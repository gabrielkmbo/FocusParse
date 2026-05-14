"""Tests for `focusparse.tools.layout_detect.detect_layout`.

Covers:
  * happy path with two boxes + figure_classifications
  * confidence_threshold drops low-scoring boxes
  * stub response (one box >=95% of page) raises StubResponseError
  * transient 502/503 is retried and eventually succeeds
  * ConnectError is retried
  * non-retryable 4xx raises LayoutEndpointUnavailable after one attempt
  * missing layout token raises LayoutEndpointUnavailable before any request
  * disk cache round-trips: first call writes, second call skips the network

Uses `httpx.MockTransport` so no external dependency is introduced — respx is
not in the dev extras.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from focusparse.tools.layout_detect import (
    DEFAULT_ENDPOINT,
    LAYOUT_TOKEN_ENV,
    LEGACY_HF_TOKEN_ENV,
    DetectedBox,
    LayoutEndpointUnavailable,
    StubResponseError,
    detect_layout,
    is_stub_response,
)

_PNG_BYTES = b"\x89PNG\r\n\x1a\nfake-body"
_WIDTH = 1000
_HEIGHT = 1500


def _ok_payload() -> dict:
    return {
        "pred_boxes": [
            [100.0, 200.0, 400.0, 500.0],
            [600.0, 700.0, 900.0, 1100.0],
        ],
        "pred_labels": ["text", "picture"],
        "scores": [0.92, 0.81],
        "figure_classifications": {"1": {"figure_class": "bar_chart"}},
    }


def _stub_payload() -> dict:
    # Single box covering the whole page -> stub fallback signal.
    return {
        "pred_boxes": [[0.0, 0.0, float(_WIDTH), float(_HEIGHT)]],
        "pred_labels": ["text"],
        "scores": [0.5],
    }


def _transport(
    handlers: list,
    *,
    record: list[httpx.Request] | None = None,
) -> httpx.MockTransport:
    """Return a MockTransport that cycles through `handlers` per request.

    Each handler is either a callable `(request) -> httpx.Response` or a bare
    `httpx.Response`. Raised exceptions propagate to the client.
    """
    iterator = iter(handlers)

    def _handle(request: httpx.Request) -> httpx.Response:
        if record is not None:
            record.append(request)
        try:
            h = next(iterator)
        except StopIteration as exc:
            raise AssertionError("MockTransport ran out of handlers") from exc
        if callable(h):
            return h(request)
        return h

    return httpx.MockTransport(_handle)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


async def test_detect_layout_happy_path():
    transport = _transport([httpx.Response(200, json=_ok_payload())])

    out = await detect_layout(
        _PNG_BYTES,
        page=3,
        image_width=_WIDTH,
        image_height=_HEIGHT,
        hf_token="test-token",
        transport=transport,
    )

    assert out.page == 3
    assert out.width == _WIDTH
    assert out.height == _HEIGHT
    assert len(out.boxes) == 2
    first, second = out.boxes
    assert first.label == "text"
    assert first.bbox == (100.0, 200.0, 400.0, 500.0)
    assert first.score == pytest.approx(0.92)
    assert first.figure_class is None
    assert second.label == "picture"
    assert second.figure_class == "bar_chart"


async def test_detect_layout_applies_confidence_threshold():
    transport = _transport([httpx.Response(200, json=_ok_payload())])
    out = await detect_layout(
        _PNG_BYTES,
        page=1,
        image_width=_WIDTH,
        image_height=_HEIGHT,
        hf_token="tok",
        confidence_threshold=0.9,
        transport=transport,
    )
    assert len(out.boxes) == 1
    assert out.boxes[0].label == "text"


async def test_detect_layout_sends_expected_headers_and_body():
    record: list[httpx.Request] = []
    transport = _transport(
        [httpx.Response(200, json=_ok_payload())],
        record=record,
    )
    await detect_layout(
        _PNG_BYTES,
        page=1,
        image_width=_WIDTH,
        image_height=_HEIGHT,
        hf_token="abc123",
        transport=transport,
    )
    assert len(record) == 1
    req = record[0]
    assert req.method == "POST"
    assert req.url == httpx.URL(DEFAULT_ENDPOINT)
    assert req.headers["authorization"] == "Bearer abc123"
    assert req.headers["content-type"] == "image/png"
    assert req.content == _PNG_BYTES


# ---------------------------------------------------------------------------
# Stub detection
# ---------------------------------------------------------------------------


async def test_detect_layout_raises_on_stub_response():
    transport = _transport([httpx.Response(200, json=_stub_payload())])
    with pytest.raises(StubResponseError):
        await detect_layout(
            _PNG_BYTES,
            page=1,
            image_width=_WIDTH,
            image_height=_HEIGHT,
            hf_token="tok",
            transport=transport,
        )


def test_is_stub_response_threshold():
    # 94% area: not a stub.
    b = DetectedBox(label="text", bbox=(0.0, 0.0, 100.0, 94.0), score=0.5)
    assert is_stub_response([b], 100, 100) is False
    # 96% area: stub.
    b2 = DetectedBox(label="text", bbox=(0.0, 0.0, 100.0, 96.0), score=0.5)
    assert is_stub_response([b2], 100, 100) is True
    # Two boxes: never a stub.
    assert is_stub_response([b2, b2], 100, 100) is False


# ---------------------------------------------------------------------------
# Retry behavior
# ---------------------------------------------------------------------------


async def test_detect_layout_retries_on_502_then_succeeds(monkeypatch):
    # Neutralize the backoff so the test isn't slow.
    import focusparse.tools.layout_detect as ld_mod

    async def _no_sleep(_):
        return None

    monkeypatch.setattr(ld_mod.asyncio, "sleep", _no_sleep)

    record: list[httpx.Request] = []
    transport = _transport(
        [
            httpx.Response(502, text="bad gateway"),
            httpx.Response(200, json=_ok_payload()),
        ],
        record=record,
    )

    out = await detect_layout(
        _PNG_BYTES,
        page=1,
        image_width=_WIDTH,
        image_height=_HEIGHT,
        hf_token="tok",
        transport=transport,
    )
    assert len(out.boxes) == 2
    assert len(record) == 2


async def test_detect_layout_retries_on_connect_error(monkeypatch):
    import focusparse.tools.layout_detect as ld_mod

    async def _no_sleep(_):
        return None

    monkeypatch.setattr(ld_mod.asyncio, "sleep", _no_sleep)

    def _boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    transport = _transport([_boom, httpx.Response(200, json=_ok_payload())])
    out = await detect_layout(
        _PNG_BYTES,
        page=1,
        image_width=_WIDTH,
        image_height=_HEIGHT,
        hf_token="tok",
        transport=transport,
    )
    assert len(out.boxes) == 2


async def test_detect_layout_gives_up_after_max_retries(monkeypatch):
    import focusparse.tools.layout_detect as ld_mod

    async def _no_sleep(_):
        return None

    monkeypatch.setattr(ld_mod.asyncio, "sleep", _no_sleep)

    transport = _transport(
        [
            httpx.Response(503, text="overloaded"),
            httpx.Response(503, text="overloaded"),
            httpx.Response(503, text="overloaded"),
        ]
    )
    with pytest.raises(LayoutEndpointUnavailable):
        await detect_layout(
            _PNG_BYTES,
            page=1,
            image_width=_WIDTH,
            image_height=_HEIGHT,
            hf_token="tok",
            max_retries=3,
            transport=transport,
        )


async def test_detect_layout_non_retryable_4xx_raises():
    # 401 is not in the retryable set — should raise on first attempt.
    transport = _transport([httpx.Response(401, text="unauthorized")])
    with pytest.raises(LayoutEndpointUnavailable):
        await detect_layout(
            _PNG_BYTES,
            page=1,
            image_width=_WIDTH,
            image_height=_HEIGHT,
            hf_token="tok",
            transport=transport,
        )


# ---------------------------------------------------------------------------
# Token + cache
# ---------------------------------------------------------------------------


async def test_detect_layout_uses_modal_token_env(monkeypatch):
    monkeypatch.setenv(LAYOUT_TOKEN_ENV, "modal-token")
    monkeypatch.setenv(LEGACY_HF_TOKEN_ENV, "legacy-token")
    record: list[httpx.Request] = []
    transport = _transport([httpx.Response(200, json=_ok_payload())], record=record)

    await detect_layout(
        _PNG_BYTES,
        page=1,
        image_width=_WIDTH,
        image_height=_HEIGHT,
        transport=transport,
    )

    assert record[0].headers["authorization"] == "Bearer modal-token"


async def test_detect_layout_falls_back_to_legacy_hf_token_env(monkeypatch):
    monkeypatch.delenv(LAYOUT_TOKEN_ENV, raising=False)
    monkeypatch.setenv(LEGACY_HF_TOKEN_ENV, "legacy-token")
    record: list[httpx.Request] = []
    transport = _transport([httpx.Response(200, json=_ok_payload())], record=record)

    await detect_layout(
        _PNG_BYTES,
        page=1,
        image_width=_WIDTH,
        image_height=_HEIGHT,
        transport=transport,
    )

    assert record[0].headers["authorization"] == "Bearer legacy-token"


async def test_detect_layout_raises_when_layout_token_missing(monkeypatch):
    monkeypatch.delenv(LAYOUT_TOKEN_ENV, raising=False)
    monkeypatch.delenv(LEGACY_HF_TOKEN_ENV, raising=False)
    with pytest.raises(LayoutEndpointUnavailable):
        await detect_layout(
            _PNG_BYTES,
            page=1,
            image_width=_WIDTH,
            image_height=_HEIGHT,
        )


async def test_detect_layout_reads_from_cache_on_second_call(tmp_path: Path):
    # First call: hits transport, writes cache.
    record: list[httpx.Request] = []
    transport = _transport(
        [httpx.Response(200, json=_ok_payload())],
        record=record,
    )
    out1 = await detect_layout(
        _PNG_BYTES,
        page=1,
        image_width=_WIDTH,
        image_height=_HEIGHT,
        hf_token="tok",
        cache_dir=tmp_path,
        transport=transport,
    )
    assert len(record) == 1
    cached_files = list(tmp_path.glob("*.json"))
    assert len(cached_files) == 1
    # Cache content should parse back to the same payload.
    assert "pred_boxes" in json.loads(cached_files[0].read_text())

    # Second call: same PNG bytes, no transport calls (handlers exhausted would
    # raise AssertionError from MockTransport).
    empty_transport = _transport([])
    out2 = await detect_layout(
        _PNG_BYTES,
        page=1,
        image_width=_WIDTH,
        image_height=_HEIGHT,
        hf_token="tok",
        cache_dir=tmp_path,
        transport=empty_transport,
    )
    assert [b.bbox for b in out1.boxes] == [b.bbox for b in out2.boxes]


async def test_detect_layout_endpoint_override_changes_cache_key(tmp_path: Path):
    """Cache is keyed on endpoint + bytes, so different endpoints don't collide."""
    transport_a = _transport([httpx.Response(200, json=_ok_payload())])
    await detect_layout(
        _PNG_BYTES,
        page=1,
        image_width=_WIDTH,
        image_height=_HEIGHT,
        endpoint_url="https://example.com/a",
        hf_token="tok",
        cache_dir=tmp_path,
        transport=transport_a,
    )

    transport_b = _transport([httpx.Response(200, json=_ok_payload())])
    await detect_layout(
        _PNG_BYTES,
        page=1,
        image_width=_WIDTH,
        image_height=_HEIGHT,
        endpoint_url="https://example.com/b",
        hf_token="tok",
        cache_dir=tmp_path,
        transport=transport_b,
    )

    assert len(list(tmp_path.glob("*.json"))) == 2
