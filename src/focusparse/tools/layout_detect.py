"""layout_detect — HTTP client for the shared HuggingFace layout endpoint.

Mirrors parser-bench's contract:
  - POST PNG bytes with `Content-Type: image/png` + `Authorization: Bearer $HF_TOKEN`.
  - Parse { pred_boxes, pred_labels, scores, figure_classifications? }.
  - Retry 3× exponential backoff on 502/503/504/429/timeouts.
  - **Raise** on the single-full-page stub response — do not silently succeed.

Rate-limit to ≤ 2 req/s since this endpoint is shared with parser-bench.

TODO(Phase 3): wire httpx + tenacity + disk cache at cache/layout/<sha>.json.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel

DEFAULT_ENDPOINT = (
    "https://jqkx3k3gn4ciymvi.us-east-1.aws.endpoints.huggingface.cloud"
)


class DetectedBox(BaseModel):
    label: str
    bbox: tuple[float, float, float, float]    # absolute pixel coords
    score: float
    figure_class: str | None = None            # e.g. "bar_chart" | "line_chart" | "logo"


class LayoutDetectionOutput(BaseModel):
    page: int
    width: int
    height: int
    boxes: list[DetectedBox]


class StubResponseError(RuntimeError):
    """Raised when the endpoint returned the single full-page stub response.

    Callers should handle this explicitly — never treat a stub like a real result.
    """


async def detect_layout(
    page_png_bytes: bytes,
    *,
    page: int,
    endpoint_url: str | None = None,
    hf_token: str | None = None,
) -> LayoutDetectionOutput:
    """Call the HF layout endpoint and return structured boxes.

    Stub fallback detection: if the response has exactly 1 box covering ≥ 95%
    of the page, raise StubResponseError instead of returning it. That shape is
    parser-bench's safety-net stub and means the real endpoint is down.
    """
    _ = endpoint_url or os.environ.get("FOCUSPARSE_LAYOUT_ENDPOINT_URL") or DEFAULT_ENDPOINT
    _ = hf_token or os.environ.get("HF_TOKEN")
    raise NotImplementedError("detect_layout — wire in Phase 3 (httpx POST + tenacity retry)")


def is_stub_response(boxes: list[DetectedBox], page_w: int, page_h: int) -> bool:
    if len(boxes) != 1:
        return False
    b = boxes[0]
    area = (b.bbox[2] - b.bbox[0]) * (b.bbox[3] - b.bbox[1])
    page_area = page_w * page_h
    return page_area > 0 and (area / page_area) >= 0.95


def fixture_path() -> Path:
    return Path(__file__).resolve().parents[3] / "tests" / "fixtures"


def _example_args_for_doc(doc_id: str) -> dict[str, Any]:
    """Helper used in tests."""
    return {"doc_id": doc_id}
