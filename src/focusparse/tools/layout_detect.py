"""layout_detect — HTTP client for the shared HuggingFace layout endpoint.

Mirrors parser-bench's contract:
  - POST PNG bytes with `Content-Type: image/png` + `Authorization: Bearer $HF_TOKEN`.
  - Parse { pred_boxes, pred_labels, scores, figure_classifications? }.
  - Retry 3× exponential backoff on 502/503/504/429/timeouts.
  - **Raise** on the single-full-page stub response — do not silently succeed.

Rate-limit to ≤ 2 req/s since this endpoint is shared with parser-bench. The
localizer is expected to serialize its per-page calls (or respect a caller-side
semaphore); this module does not enforce a global rate limit.

Responses are cached on disk at `<cache_dir>/<sha256(endpoint+png)>.json`. The
cache is content-addressed on the PNG bytes, so the same page image at the
same DPI yields the same result file across runs.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
from pathlib import Path

import httpx
from pydantic import BaseModel

logger = logging.getLogger(__name__)

DEFAULT_ENDPOINT = "https://jqkx3k3gn4ciymvi.us-east-1.aws.endpoints.huggingface.cloud"

_RETRYABLE_STATUS = {502, 503, 504, 429}
_DEFAULT_TIMEOUT_S = 180.0
_DEFAULT_MAX_RETRIES = 3


class DetectedBox(BaseModel):
    label: str
    bbox: tuple[float, float, float, float]  # absolute pixel coords (x0, y0, x1, y1)
    score: float
    figure_class: str | None = None  # e.g. "bar_chart" | "line_chart" | "logo"


class LayoutDetectionOutput(BaseModel):
    page: int
    width: int
    height: int
    boxes: list[DetectedBox]


class StubResponseError(RuntimeError):
    """Raised when the endpoint returned the single full-page stub response.

    Callers should handle this explicitly — never treat a stub like a real result.
    """


class LayoutEndpointUnavailable(RuntimeError):
    """Raised when the endpoint cannot be reached after retries, or HF_TOKEN
    is not set. Localizer catches this and falls back to a deterministic
    skeleton region — the workflow stays on the rails either way.
    """


async def detect_layout(
    page_png_bytes: bytes,
    *,
    page: int,
    image_width: int,
    image_height: int,
    endpoint_url: str | None = None,
    hf_token: str | None = None,
    cache_dir: Path | None = None,
    confidence_threshold: float = 0.0,
    max_retries: int = _DEFAULT_MAX_RETRIES,
    timeout_s: float = _DEFAULT_TIMEOUT_S,
    transport: httpx.AsyncBaseTransport | None = None,
) -> LayoutDetectionOutput:
    """Call the HF layout endpoint and return structured boxes.

    Args:
        page_png_bytes: PNG bytes of the rendered page.
        page: 1-indexed page number (carried through to the response).
        image_width / image_height: pixel dimensions of the source image;
            used to detect the full-page stub response.
        endpoint_url: override the default endpoint. Falls back to
            `$FOCUSPARSE_LAYOUT_ENDPOINT_URL` then `DEFAULT_ENDPOINT`.
        hf_token: override the token. Falls back to `$HF_TOKEN`.
        cache_dir: where to persist responses. If None, no caching.
        confidence_threshold: drop boxes below this score.
        transport: inject a mock transport for tests; if None, httpx picks its
            default AsyncHTTPTransport.

    Raises:
        StubResponseError: endpoint returned the single full-page stub shape.
        LayoutEndpointUnavailable: HF_TOKEN missing, or endpoint failed after
            `max_retries` attempts.
    """
    endpoint = endpoint_url or os.environ.get("FOCUSPARSE_LAYOUT_ENDPOINT_URL") or DEFAULT_ENDPOINT
    token = hf_token if hf_token is not None else os.environ.get("HF_TOKEN")
    if not token:
        raise LayoutEndpointUnavailable("HF_TOKEN not set; cannot call the layout endpoint.")

    cache_path: Path | None = None
    if cache_dir is not None:
        cache_path = cache_dir / f"{_cache_key(endpoint, page_png_bytes)}.json"
        cached = _read_cache(cache_path)
        if cached is not None:
            return _parse_response(
                cached,
                page=page,
                width=image_width,
                height=image_height,
                confidence_threshold=confidence_threshold,
            )

    result = await _post_with_retry(
        endpoint=endpoint,
        token=token,
        png_bytes=page_png_bytes,
        max_retries=max_retries,
        timeout_s=timeout_s,
        transport=transport,
    )

    if cache_path is not None:
        _write_cache(cache_path, result)

    return _parse_response(
        result,
        page=page,
        width=image_width,
        height=image_height,
        confidence_threshold=confidence_threshold,
    )


# ---------------------------------------------------------------------------
# Stub detection + parsing
# ---------------------------------------------------------------------------


def is_stub_response(boxes: list[DetectedBox], page_w: int, page_h: int) -> bool:
    """True iff the response is parser-bench's single-full-page safety stub.

    The real RT-DETRv2 head is trained to emit no more than ~20 boxes and
    effectively never emits exactly one box covering ≥95% of the page.
    """
    if len(boxes) != 1:
        return False
    b = boxes[0]
    area = (b.bbox[2] - b.bbox[0]) * (b.bbox[3] - b.bbox[1])
    page_area = page_w * page_h
    return page_area > 0 and (area / page_area) >= 0.95


def _parse_response(
    payload: dict,
    *,
    page: int,
    width: int,
    height: int,
    confidence_threshold: float,
) -> LayoutDetectionOutput:
    raw_boxes = payload.get("pred_boxes") or []
    raw_labels = payload.get("pred_labels") or []
    raw_scores = payload.get("scores") or []
    fig_cls = payload.get("figure_classifications") or {}

    boxes: list[DetectedBox] = []
    for idx, (bbox, label, score) in enumerate(
        zip(raw_boxes, raw_labels, raw_scores, strict=False)
    ):
        if score < confidence_threshold:
            continue
        figure_class: str | None = None
        # Picture regions carry a secondary figure_class keyed on the detection index.
        fc_entry = fig_cls.get(str(idx))
        if isinstance(fc_entry, dict):
            figure_class = fc_entry.get("figure_class")
        boxes.append(
            DetectedBox(
                label=str(label),
                bbox=tuple(float(v) for v in bbox),  # type: ignore[arg-type]
                score=float(score),
                figure_class=figure_class,
            )
        )

    if is_stub_response(boxes, width, height):
        raise StubResponseError(
            f"layout endpoint returned the single full-page stub for page={page} "
            f"({width}x{height}); treat as endpoint-down."
        )

    return LayoutDetectionOutput(page=page, width=width, height=height, boxes=boxes)


# ---------------------------------------------------------------------------
# HTTP with retry
# ---------------------------------------------------------------------------


async def _post_with_retry(
    *,
    endpoint: str,
    token: str,
    png_bytes: bytes,
    max_retries: int,
    timeout_s: float,
    transport: httpx.AsyncBaseTransport | None,
) -> dict:
    last_exc: Exception | None = None
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "image/png",
    }
    async with httpx.AsyncClient(transport=transport, timeout=timeout_s) as client:
        for attempt in range(1, max_retries + 1):
            try:
                resp = await client.post(endpoint, headers=headers, content=png_bytes)
                if resp.status_code not in _RETRYABLE_STATUS:
                    resp.raise_for_status()
                    return resp.json()
                last_exc = httpx.HTTPStatusError(
                    f"{resp.status_code} on attempt {attempt}",
                    request=resp.request,
                    response=resp,
                )
            except (httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError) as exc:
                last_exc = exc
            if attempt < max_retries:
                await asyncio.sleep(2**attempt)
                logger.warning(
                    "layout endpoint attempt %d/%d failed (%s); retrying",
                    attempt,
                    max_retries,
                    last_exc,
                )

    raise LayoutEndpointUnavailable(
        f"layout endpoint failed after {max_retries} attempts: {last_exc}"
    ) from last_exc


# ---------------------------------------------------------------------------
# Disk cache
# ---------------------------------------------------------------------------


def _cache_key(endpoint: str, png_bytes: bytes) -> str:
    h = hashlib.sha256()
    h.update(endpoint.encode("utf-8"))
    h.update(b"\0")
    h.update(png_bytes)
    return h.hexdigest()


def _read_cache(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def _write_cache(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.write_text(json.dumps(payload))
    except OSError as exc:
        logger.warning("layout cache write failed (%s); continuing uncached", exc)
