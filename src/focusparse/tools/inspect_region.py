"""inspect_region — the unified zoom/crop/OCR primitive (AgenticOCR-style).

Exactly three modes. Do not add a fourth without updating the plan.

  image:   crop only, no OCR. Cheapest. Use for visual inspection before
           committing (e.g. deciding whether a region is worth OCR'ing).
  element: crop + Tesseract OCR on the crop. Use when the target region
           is known + tight.
  region:  crop + sub-layout detection on the crop (via the HF docling
           layout-v3 endpoint, same URL as `layout_detect`) + Tesseract
           OCR per sub-element. Use for mixed structures like chart+
           legend+caption or table+notes.

Output crops are written to `<cache_dir>/<crop_sha>.png` and the path
is returned as `crop_ref`. The same bbox + dpi + rotation + expansion
yields the same cache file across runs, so the agent's repeated
zooms never re-render a page it's already seen.

Cropping uses PyMuPDF to render the page at the requested DPI, then
PIL to slice the bbox. OCR uses pytesseract (tesseract binary must be
on $PATH for `element` and `region` modes; missing tesseract degrades
to `ocr_text=None` and the agent loop escalates). `region` mode's
sub-layout call reuses `layout_detect` — when that endpoint is
unavailable, we fall back to `element` shape (the crop still has
`ocr_text` from whole-crop OCR).
"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

_EXPANSION_FRACTIONS = {
    "none": 0.0,
    "default": 0.02,
    "aggressive": 0.05,
}


class InspectRegionInput(BaseModel):
    doc_path: str  # local PDF path
    page: int = Field(ge=1, description="1-indexed page number")
    bbox_norm: tuple[float, float, float, float]  # (x0, y0, x1, y1) in [0,1]
    mode: Literal["image", "element", "region"] = "element"
    dpi: int = Field(default=300, ge=72, le=600)
    rotation: int = Field(default=0)
    expansion: Literal["none", "default", "aggressive"] = "default"


class InspectRegionOutput(BaseModel):
    crop_ref: str  # absolute path to the cached PNG crop
    ocr_text: str | None = None
    sub_regions: list[dict] = Field(default_factory=list)
    confidence: float = 1.0  # OCR confidence in [0,1]; 1.0 when no OCR ran
    tokens_used: int = 0  # reserved for a future LLM-based zoom path
    latency_ms: int = 0
    page_width_px: int = 0  # rendered page width at requested DPI
    page_height_px: int = 0


async def inspect_region(
    inp: InspectRegionInput,
    *,
    cache_dir: Path | None = None,
    layout_endpoint_url: str | None = None,
    hf_token: str | None = None,
    layout_cache_dir: Path | None = None,
) -> InspectRegionOutput:
    """Render a page crop (and optionally OCR/sub-detect it) for the agent.

    Args:
        inp: see `InspectRegionInput`.
        cache_dir: where to write cropped PNGs. When None, crops are
            written to `<cwd>/cache/crops/` — pass a configured root in
            production.
        layout_endpoint_url / hf_token / layout_cache_dir: forwarded to
            `layout_detect` for `mode="region"`. Unused in other modes.

    Raises:
        FileNotFoundError: `doc_path` does not exist.
        ValueError: `page` out of range, or `bbox_norm` has zero area.
    """
    pdf_path = Path(inp.doc_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    _validate_bbox(inp.bbox_norm)

    effective_cache_dir = cache_dir or (Path.cwd() / "cache" / "crops")
    effective_cache_dir.mkdir(parents=True, exist_ok=True)

    started = time.perf_counter()
    crop_key = _crop_cache_key(pdf_path, inp)
    crop_path = effective_cache_dir / f"{crop_key}.png"

    page_w, page_h = _render_crop_if_missing(pdf_path, inp, crop_path)

    ocr_text: str | None = None
    confidence = 1.0
    sub_regions: list[dict] = []
    if inp.mode in ("element", "region"):
        ocr_text, confidence = _ocr_crop(crop_path)
    if inp.mode == "region":
        sub_regions = await _detect_and_ocr_sub_regions(
            crop_path=crop_path,
            layout_endpoint_url=layout_endpoint_url,
            hf_token=hf_token,
            layout_cache_dir=layout_cache_dir,
        )

    latency_ms = int((time.perf_counter() - started) * 1000)
    return InspectRegionOutput(
        crop_ref=str(crop_path),
        ocr_text=ocr_text,
        sub_regions=sub_regions,
        confidence=confidence,
        latency_ms=latency_ms,
        page_width_px=page_w,
        page_height_px=page_h,
    )


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_crop_if_missing(
    pdf_path: Path,
    inp: InspectRegionInput,
    crop_path: Path,
) -> tuple[int, int]:
    """Render the page + crop the bbox, skipping if the cache file already exists.

    Returns the rendered page's pixel dimensions (w, h) regardless of cache
    hit/miss — the caller records these on the TrajectoryStep so the agent
    knows the source resolution without re-rendering.
    """
    import fitz
    from PIL import Image

    with fitz.open(pdf_path) as doc:
        if inp.page < 1 or inp.page > doc.page_count:
            raise ValueError(
                f"page={inp.page} out of range for {pdf_path.name} (has {doc.page_count} pages)"
            )
        page = doc[inp.page - 1]
        # 72 dpi is PDF-native; zoom = requested_dpi / 72.
        zoom = inp.dpi / 72.0
        matrix = fitz.Matrix(zoom, zoom)
        if inp.rotation:
            matrix = matrix.prerotate(inp.rotation)
        pix = page.get_pixmap(matrix=matrix, alpha=False)
        page_w, page_h = pix.width, pix.height

        if crop_path.exists():
            # Still return the page dims so the caller has them.
            return page_w, page_h

        # Slice the bbox in pixel space.
        crop_bbox_px = _bbox_norm_to_pixel(
            inp.bbox_norm,
            width=page_w,
            height=page_h,
            expansion=_EXPANSION_FRACTIONS[inp.expansion],
        )
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        crop = img.crop(crop_bbox_px)
        crop.save(crop_path, format="PNG")

    return page_w, page_h


def _bbox_norm_to_pixel(
    bbox_norm: tuple[float, float, float, float],
    *,
    width: int,
    height: int,
    expansion: float,
) -> tuple[int, int, int, int]:
    x0, y0, x1, y1 = bbox_norm
    # Expand symmetrically by `expansion` of the page dims on each side,
    # then clamp to the page rectangle.
    ex = expansion
    x0 = max(0.0, x0 - ex)
    y0 = max(0.0, y0 - ex)
    x1 = min(1.0, x1 + ex)
    y1 = min(1.0, y1 + ex)
    return (
        int(x0 * width),
        int(y0 * height),
        int(x1 * width),
        int(y1 * height),
    )


def _validate_bbox(bbox_norm: tuple[float, float, float, float]) -> None:
    x0, y0, x1, y1 = bbox_norm
    if not (0.0 <= x0 < x1 <= 1.0 and 0.0 <= y0 < y1 <= 1.0):
        raise ValueError(f"bbox_norm must be a non-empty [0,1] rectangle; got {bbox_norm}")


# ---------------------------------------------------------------------------
# OCR
# ---------------------------------------------------------------------------


def _ocr_crop(crop_path: Path) -> tuple[str | None, float]:
    """Run Tesseract on the crop. Returns (text, confidence).

    If tesseract is missing or fails at import, returns (None, 0.0) so the
    caller can still ship `crop_ref` for visual inspection. The agent loop
    sees `ocr_text is None` and escalates (retry at higher DPI, or fall
    back to VLM description).
    """
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        return None, 0.0

    try:
        with Image.open(crop_path) as img:
            img = img.convert("RGB")  # tesseract doesn't love non-RGB modes
            # Use tsv output so we can extract per-word confidence.
            tsv = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
    except (pytesseract.TesseractNotFoundError, OSError):
        return None, 0.0

    words = tsv.get("text") or []
    confs_raw = tsv.get("conf") or []

    # Tesseract emits -1 for non-word rows; filter those out.
    kept: list[tuple[str, float]] = []
    for text, conf_raw in zip(words, confs_raw, strict=False):
        if not text or not text.strip():
            continue
        try:
            conf = float(conf_raw)
        except (TypeError, ValueError):
            continue
        if conf < 0:
            continue
        kept.append((text, conf))

    if not kept:
        return "", 0.0

    joined = " ".join(t for t, _ in kept)
    mean_conf = sum(c for _, c in kept) / len(kept) / 100.0  # tesseract conf is 0-100
    return joined, max(0.0, min(1.0, mean_conf))


# ---------------------------------------------------------------------------
# Sub-region detection (region mode)
# ---------------------------------------------------------------------------


async def _detect_and_ocr_sub_regions(
    *,
    crop_path: Path,
    layout_endpoint_url: str | None,
    hf_token: str | None,
    layout_cache_dir: Path | None,
) -> list[dict]:
    """Run layout detection on the crop and OCR each detected sub-box.

    Returns a list of `{label, bbox_px, ocr_text, score, figure_class}`
    dicts. When the layout endpoint is unavailable or returns the stub
    response, returns [] — the caller's whole-crop `ocr_text` is still
    populated in `region` mode, so the agent still gets useful text.

    bbox_px coordinates are in the *crop's* pixel space, not page space.
    Callers that need page coordinates re-project via the crop's bbox on
    the page. We keep crop-space here because it's what the VLM sees.
    """
    from focusparse.tools.layout_detect import (
        LayoutEndpointUnavailable,
        StubResponseError,
        detect_layout,
    )

    png_bytes = crop_path.read_bytes()
    crop_w, crop_h = _png_dimensions(png_bytes)

    try:
        out = await detect_layout(
            png_bytes,
            page=1,  # sub-layout is a single-page call on the crop
            image_width=crop_w,
            image_height=crop_h,
            endpoint_url=layout_endpoint_url,
            hf_token=hf_token,
            cache_dir=layout_cache_dir,
        )
    except (LayoutEndpointUnavailable, StubResponseError):
        return []

    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        # No OCR available — still return the bboxes so the VLM can at
        # least see what was detected.
        return [
            {
                "label": box.label,
                "bbox_px": list(box.bbox),
                "score": box.score,
                "figure_class": box.figure_class,
                "ocr_text": None,
            }
            for box in out.boxes
        ]

    sub_regions: list[dict] = []
    with Image.open(crop_path) as img:
        rgb = img.convert("RGB")
        for box in out.boxes:
            x0, y0, x1, y1 = (int(v) for v in box.bbox)
            sub_img = rgb.crop((x0, y0, x1, y1))
            try:
                text = pytesseract.image_to_string(sub_img).strip() or None
            except (pytesseract.TesseractNotFoundError, OSError):
                text = None
            sub_regions.append(
                {
                    "label": box.label,
                    "bbox_px": [x0, y0, x1, y1],
                    "score": box.score,
                    "figure_class": box.figure_class,
                    "ocr_text": text,
                }
            )
    return sub_regions


def _png_dimensions(png_bytes: bytes) -> tuple[int, int]:
    import io

    from PIL import Image

    with Image.open(io.BytesIO(png_bytes)) as img:
        return int(img.width), int(img.height)


# ---------------------------------------------------------------------------
# Cache key
# ---------------------------------------------------------------------------


def _crop_cache_key(pdf_path: Path, inp: InspectRegionInput) -> str:
    h = hashlib.sha256()
    # Content-address on the PDF bytes so cache invalidates when the source
    # changes. For very large PDFs this is expensive but still << the render
    # cost; if it becomes a bottleneck we can switch to (mtime, size) hash.
    h.update(pdf_path.read_bytes())
    h.update(b"\0")
    h.update(str(inp.page).encode("ascii"))
    h.update(b"\0")
    h.update(",".join(f"{v:.6f}" for v in inp.bbox_norm).encode("ascii"))
    h.update(b"\0")
    h.update(inp.mode.encode("ascii"))
    h.update(b"\0")
    h.update(f"{inp.dpi}".encode("ascii"))
    h.update(b"\0")
    h.update(f"{inp.rotation}".encode("ascii"))
    h.update(b"\0")
    h.update(inp.expansion.encode("ascii"))
    return h.hexdigest()[:32]
