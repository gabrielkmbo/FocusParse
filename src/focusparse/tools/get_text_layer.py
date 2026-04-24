"""get_text_layer — deterministic PDF text span extraction via PyMuPDF.

Reads the native PDF text layer for one page, optionally cropped to a
normalized bbox. No OCR fallback in this sub-phase: when a page has no
native text (scanned datasheet, image-only PDF), we return
`source="empty_native"` with empty text so the caller can decide to
escalate to Tesseract. Wiring OCR is a separate sub-phase — it needs
a Tesseract install guard, a rate-limit budget, and its own cache shape.

Contract notes:
  * `doc_path` must point to an existing PDF. Missing files raise
    `FileNotFoundError` before any PyMuPDF work — callers rely on this
    to distinguish "file gone" from "PDF malformed".
  * `page` is 1-indexed (matches every other FocusParse event). Out-of-
    range pages raise `ValueError` rather than returning empty text, so
    plumbing bugs surface immediately instead of silently degrading.
  * `bbox_norm` is `(x0, y0, x1, y1)` in [0,1] with top-left origin,
    matching `RegionCandidate.bbox_norm`. When supplied we filter spans
    whose centroid falls inside the bbox — partial spans on the edge
    are kept, since dropping them makes OCR text harder to stitch back.

The disk cache is keyed on `sha256(pdf_bytes + page + bbox_norm)` so the
same PDF + page + crop across runs returns byte-identical output.
Cache-miss cost is one `fitz.open` + one `get_text("dict")`, both cheap.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
from pathlib import Path

from pydantic import BaseModel, Field


class GetTextLayerInput(BaseModel):
    doc_path: str  # local path to the PDF
    page: int = Field(ge=1, description="1-indexed page number")
    bbox_norm: tuple[float, float, float, float] | None = None


class TextSpan(BaseModel):
    """A single span from the native text layer.

    `bbox` is in absolute PDF-point coordinates (top-left origin), not
    normalized, so downstream callers can crop images at matching resolution
    without re-reading the page dimensions.
    """

    text: str
    bbox: tuple[float, float, float, float]
    confidence: float = 1.0  # native text layer is treated as ground truth


class GetTextLayerOutput(BaseModel):
    text: str  # joined plain text, newlines preserved between blocks
    source: str  # "native" | "empty_native"
    spans: list[TextSpan] = Field(default_factory=list)
    page_width: float = 0.0  # PDF points
    page_height: float = 0.0


async def get_text_layer(
    inp: GetTextLayerInput,
    *,
    cache_dir: Path | None = None,
) -> GetTextLayerOutput:
    """Extract native text from one PDF page, optionally filtered to a bbox.

    Args:
        inp: see `GetTextLayerInput`.
        cache_dir: where to persist the result JSON. When None, the call
            is uncached — useful for tests but wasteful at scale.

    Raises:
        FileNotFoundError: `doc_path` does not exist.
        ValueError: `page` is out of range for this PDF.
    """
    pdf_path = Path(inp.doc_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    cache_path: Path | None = None
    if cache_dir is not None:
        cache_path = cache_dir / f"{_cache_key(pdf_path, inp.page, inp.bbox_norm)}.json"
        cached = _read_cache(cache_path)
        if cached is not None:
            return GetTextLayerOutput.model_validate(cached)

    result = _extract_page_text(pdf_path, page=inp.page, bbox_norm=inp.bbox_norm)

    if cache_path is not None:
        _write_cache(cache_path, result.model_dump())

    return result


def _extract_page_text(
    pdf_path: Path,
    *,
    page: int,
    bbox_norm: tuple[float, float, float, float] | None,
) -> GetTextLayerOutput:
    import fitz  # deferred — keep top-level imports lean

    with fitz.open(pdf_path) as doc:
        if page < 1 or page > doc.page_count:
            raise ValueError(
                f"page={page} out of range for {pdf_path.name} (has {doc.page_count} pages)"
            )
        pdf_page = doc[page - 1]
        width = float(pdf_page.rect.width)
        height = float(pdf_page.rect.height)

        raw = pdf_page.get_text("dict")

    crop_abs = _bbox_norm_to_abs(bbox_norm, width, height) if bbox_norm else None

    spans: list[TextSpan] = []
    for block in raw.get("blocks", []):
        if block.get("type") != 0:
            # type=0 is a text block; type=1 is an image. We only want text.
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                text = (span.get("text") or "").strip()
                if not text:
                    continue
                bbox = tuple(float(v) for v in span.get("bbox", (0, 0, 0, 0)))
                if len(bbox) != 4:
                    continue
                if crop_abs is not None and not _centroid_in_bbox(bbox, crop_abs):
                    continue
                spans.append(TextSpan(text=text, bbox=bbox, confidence=1.0))

    joined = _join_spans(spans)
    source = "native" if joined.strip() else "empty_native"

    return GetTextLayerOutput(
        text=joined,
        source=source,
        spans=spans,
        page_width=width,
        page_height=height,
    )


def _bbox_norm_to_abs(
    bbox_norm: tuple[float, float, float, float],
    width: float,
    height: float,
) -> tuple[float, float, float, float]:
    x0, y0, x1, y1 = bbox_norm
    return (x0 * width, y0 * height, x1 * width, y1 * height)


def _centroid_in_bbox(
    span_bbox: tuple[float, float, float, float],
    crop_bbox: tuple[float, float, float, float],
) -> bool:
    cx = (span_bbox[0] + span_bbox[2]) / 2.0
    cy = (span_bbox[1] + span_bbox[3]) / 2.0
    cx0, cy0, cx1, cy1 = crop_bbox
    return cx0 <= cx <= cx1 and cy0 <= cy <= cy1


def _join_spans(spans: list[TextSpan]) -> str:
    """Join spans back into plain text, preserving reading order.

    Span order as returned by PyMuPDF is block-by-block, top-to-bottom, so
    we just concatenate with spaces — higher-fidelity line reconstruction
    is the router's problem (it only needs BM25 bag-of-words anyway).
    """
    return " ".join(s.text for s in spans)


# ---------------------------------------------------------------------------
# Disk cache
# ---------------------------------------------------------------------------


def _cache_key(
    pdf_path: Path,
    page: int,
    bbox_norm: tuple[float, float, float, float] | None,
) -> str:
    h = hashlib.sha256()
    # Content-address on the PDF bytes so re-running after a PDF edit
    # invalidates the cache automatically.
    h.update(pdf_path.read_bytes())
    h.update(b"\0")
    h.update(str(page).encode("ascii"))
    h.update(b"\0")
    if bbox_norm is not None:
        h.update(",".join(f"{v:.6f}" for v in bbox_norm).encode("ascii"))
    return h.hexdigest()[:32]


def _read_cache(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def _write_cache(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Best-effort cache: a write failure should not propagate into the
    # caller's path. Same policy as layout_detect._write_cache.
    with contextlib.suppress(OSError):
        path.write_text(json.dumps(payload))
