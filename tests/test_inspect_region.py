"""Tests for `focusparse.tools.inspect_region.inspect_region`.

Generates PyMuPDF PDFs on the fly so tests stay hermetic. Covers:

  * image mode: PNG crop is written and cached, dims match DPI
  * element mode: Tesseract OCR returns non-empty text on a legible crop,
    empty string on a blank area, confidence in [0,1]
  * region mode: monkeypatch `layout_detect` so no HF call is made; assert
    sub_regions carry (label, bbox_px, score, ocr_text); when endpoint
    is unavailable, sub_regions is [] but the whole-crop `ocr_text`
    still populates
  * cache round-trip: second call with same input is a no-op
  * cache key varies with mode/dpi/rotation/expansion/page/bbox
  * out-of-range page → ValueError
  * bbox outside [0,1] → ValueError
  * missing PDF → FileNotFoundError
  * expansion padding actually grows the crop (visible in output dims)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from focusparse.tools.inspect_region import (
    InspectRegionInput,
    inspect_region,
)


def _write_pdf(path: Path, page_text_specs: list[list[tuple[str, tuple[float, float]]]]) -> Path:
    """Write a PDF where each page is a list of `(text, (x, y))` entries."""
    import fitz

    path.parent.mkdir(parents=True, exist_ok=True)
    doc = fitz.open()
    for specs in page_text_specs:
        page = doc.new_page(width=600, height=800)
        for text, (x, y) in specs:
            page.insert_text((x, y), text, fontsize=14)
    doc.save(path)
    doc.close()
    return path


# ---------------------------------------------------------------------------
# image mode
# ---------------------------------------------------------------------------


async def test_image_mode_writes_cached_png(tmp_path):
    pdf = _write_pdf(tmp_path / "doc.pdf", [[("hello world", (50, 50))]])
    out = await inspect_region(
        InspectRegionInput(
            doc_path=str(pdf),
            page=1,
            bbox_norm=(0.0, 0.0, 0.5, 0.5),
            mode="image",
            dpi=150,
            expansion="none",
        ),
        cache_dir=tmp_path / "crops",
    )
    assert Path(out.crop_ref).exists()
    assert out.crop_ref.endswith(".png")
    assert out.ocr_text is None
    # At 150 DPI, a 600x800 PDF page renders to 1250x1666; top-left 50%
    # crop is ~625x833.
    from PIL import Image

    with Image.open(out.crop_ref) as img:
        assert 600 <= img.width <= 640
        assert 810 <= img.height <= 840
    # Page dims surfaced.
    assert out.page_width_px > 0
    assert out.page_height_px > 0


async def test_image_mode_is_cached_across_calls(tmp_path):
    pdf = _write_pdf(tmp_path / "doc.pdf", [[("x", (50, 50))]])
    cache_dir = tmp_path / "crops"
    out1 = await inspect_region(
        InspectRegionInput(doc_path=str(pdf), page=1, bbox_norm=(0.0, 0.0, 0.5, 0.5), mode="image"),
        cache_dir=cache_dir,
    )
    mtime_before = Path(out1.crop_ref).stat().st_mtime
    out2 = await inspect_region(
        InspectRegionInput(doc_path=str(pdf), page=1, bbox_norm=(0.0, 0.0, 0.5, 0.5), mode="image"),
        cache_dir=cache_dir,
    )
    # Same cache key → same file → not overwritten.
    assert out1.crop_ref == out2.crop_ref
    assert Path(out2.crop_ref).stat().st_mtime == mtime_before


# ---------------------------------------------------------------------------
# element mode (Tesseract)
# ---------------------------------------------------------------------------


async def test_element_mode_ocrs_crop_text(tmp_path):
    pdf = _write_pdf(
        tmp_path / "doc.pdf",
        [[("RECOGNIZE THIS TEXT", (100, 200))]],
    )
    out = await inspect_region(
        InspectRegionInput(
            doc_path=str(pdf),
            page=1,
            # Crop around the text; enlarged to give Tesseract easy context.
            bbox_norm=(0.0, 0.15, 1.0, 0.45),
            mode="element",
            dpi=300,
            expansion="default",
        ),
        cache_dir=tmp_path / "crops",
    )
    assert out.ocr_text is not None
    # Tesseract may lowercase or rearrange slightly — check a stable token.
    assert "RECOGNIZE" in out.ocr_text.upper()
    assert 0.0 <= out.confidence <= 1.0


async def test_element_mode_empty_crop_has_empty_ocr(tmp_path):
    """Blank crop region → Tesseract returns empty string, confidence 0."""
    pdf = _write_pdf(
        tmp_path / "doc.pdf",
        [[("text in top-left only", (50, 50))]],
    )
    out = await inspect_region(
        InspectRegionInput(
            doc_path=str(pdf),
            page=1,
            bbox_norm=(0.5, 0.5, 1.0, 1.0),  # bottom-right — no text
            mode="element",
            expansion="none",
        ),
        cache_dir=tmp_path / "crops",
    )
    assert out.ocr_text == ""
    assert out.confidence == 0.0


# ---------------------------------------------------------------------------
# region mode (layout endpoint + per-sub-region OCR)
# ---------------------------------------------------------------------------


async def test_region_mode_attaches_sub_regions(tmp_path, monkeypatch):
    pdf = _write_pdf(tmp_path / "doc.pdf", [[("HEADER", (100, 100))]])

    from focusparse.tools import layout_detect as ld

    async def _fake_detect(png_bytes, *, page, image_width, image_height, **kwargs):
        # Emit two sub-boxes in crop-pixel coordinates.
        return ld.LayoutDetectionOutput(
            page=page,
            width=image_width,
            height=image_height,
            boxes=[
                ld.DetectedBox(
                    label="text",
                    bbox=(10.0, 10.0, 200.0, 80.0),
                    score=0.9,
                ),
                ld.DetectedBox(
                    label="picture",
                    bbox=(10.0, 100.0, 200.0, 300.0),
                    score=0.75,
                    figure_class="line_chart",
                ),
            ],
        )

    monkeypatch.setattr(
        "focusparse.tools.inspect_region.detect_layout", _fake_detect, raising=False
    )
    # detect_layout is imported inside the helper, so we also monkeypatch
    # at the source module to cover the deferred import.
    monkeypatch.setattr(ld, "detect_layout", _fake_detect)

    out = await inspect_region(
        InspectRegionInput(
            doc_path=str(pdf),
            page=1,
            bbox_norm=(0.0, 0.0, 0.8, 0.8),
            mode="region",
            dpi=150,
        ),
        cache_dir=tmp_path / "crops",
    )
    assert out.ocr_text is not None  # whole-crop OCR still runs
    assert len(out.sub_regions) == 2
    labels = [s["label"] for s in out.sub_regions]
    assert "text" in labels and "picture" in labels
    picture = next(s for s in out.sub_regions if s["label"] == "picture")
    assert picture["figure_class"] == "line_chart"
    assert picture["bbox_px"] == [10, 100, 200, 300]
    # OCR on each sub-region is attempted (text or None).
    assert "ocr_text" in picture


async def test_region_mode_falls_back_when_endpoint_unavailable(tmp_path, monkeypatch):
    pdf = _write_pdf(tmp_path / "doc.pdf", [[("HEADER", (100, 100))]])

    from focusparse.tools import layout_detect as ld

    async def _raising(*args, **kwargs):
        raise ld.LayoutEndpointUnavailable("simulated outage")

    monkeypatch.setattr(ld, "detect_layout", _raising)

    out = await inspect_region(
        InspectRegionInput(
            doc_path=str(pdf),
            page=1,
            bbox_norm=(0.0, 0.0, 1.0, 1.0),
            mode="region",
            dpi=150,
        ),
        cache_dir=tmp_path / "crops",
    )
    # sub-layout failed, but whole-crop OCR is still there.
    assert out.sub_regions == []
    assert out.ocr_text is not None


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


async def test_missing_pdf_raises_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        await inspect_region(
            InspectRegionInput(
                doc_path=str(tmp_path / "nope.pdf"),
                page=1,
                bbox_norm=(0.0, 0.0, 1.0, 1.0),
                mode="image",
            ),
            cache_dir=tmp_path / "crops",
        )


async def test_out_of_range_page_raises_value_error(tmp_path):
    pdf = _write_pdf(tmp_path / "one.pdf", [[("x", (50, 50))]])
    with pytest.raises(ValueError, match="out of range"):
        await inspect_region(
            InspectRegionInput(
                doc_path=str(pdf),
                page=42,
                bbox_norm=(0.0, 0.0, 1.0, 1.0),
                mode="image",
            ),
            cache_dir=tmp_path / "crops",
        )


@pytest.mark.parametrize(
    "bad_bbox",
    [
        (0.5, 0.0, 0.5, 1.0),  # zero width
        (0.0, 0.5, 1.0, 0.5),  # zero height
        (-0.1, 0.0, 1.0, 1.0),  # below 0
        (0.0, 0.0, 1.1, 1.0),  # above 1
        (0.8, 0.0, 0.2, 1.0),  # inverted
    ],
)
async def test_invalid_bbox_raises_value_error(tmp_path, bad_bbox):
    pdf = _write_pdf(tmp_path / "x.pdf", [[("x", (50, 50))]])
    with pytest.raises(ValueError, match="bbox_norm"):
        await inspect_region(
            InspectRegionInput(
                doc_path=str(pdf),
                page=1,
                bbox_norm=bad_bbox,
                mode="image",
            ),
            cache_dir=tmp_path / "crops",
        )


# ---------------------------------------------------------------------------
# Cache-key distinctness
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "mutation",
    [
        {"mode": "image"},  # different mode
        {"dpi": 150},  # different dpi
        {"rotation": 90},  # different rotation
        {"expansion": "aggressive"},  # different expansion
        {"page": 2},  # different page
        {"bbox_norm": (0.1, 0.0, 0.5, 0.5)},  # different bbox
    ],
)
async def test_cache_key_varies_with_each_input_dimension(tmp_path, mutation):
    pdf = _write_pdf(
        tmp_path / "multi.pdf",
        [[("p1", (50, 50))], [("p2", (50, 50))]],
    )
    cache_dir = tmp_path / "crops"
    base = {
        "doc_path": str(pdf),
        "page": 1,
        "bbox_norm": (0.0, 0.0, 0.5, 0.5),
        "mode": "element",
        "dpi": 300,
        "rotation": 0,
        "expansion": "default",
    }
    await inspect_region(InspectRegionInput(**base), cache_dir=cache_dir)
    mutated = {**base, **mutation}
    await inspect_region(InspectRegionInput(**mutated), cache_dir=cache_dir)
    # Two distinct crop cache entries.
    assert len(list(cache_dir.glob("*.png"))) == 2


# ---------------------------------------------------------------------------
# Expansion padding
# ---------------------------------------------------------------------------


async def test_aggressive_expansion_yields_larger_crop(tmp_path):
    pdf = _write_pdf(tmp_path / "x.pdf", [[("x", (50, 50))]])
    cache_dir = tmp_path / "crops"
    tight = await inspect_region(
        InspectRegionInput(
            doc_path=str(pdf),
            page=1,
            bbox_norm=(0.4, 0.4, 0.6, 0.6),
            mode="image",
            expansion="none",
            dpi=150,
        ),
        cache_dir=cache_dir,
    )
    wide = await inspect_region(
        InspectRegionInput(
            doc_path=str(pdf),
            page=1,
            bbox_norm=(0.4, 0.4, 0.6, 0.6),
            mode="image",
            expansion="aggressive",
            dpi=150,
        ),
        cache_dir=cache_dir,
    )
    from PIL import Image

    with Image.open(tight.crop_ref) as t, Image.open(wide.crop_ref) as w:
        # Aggressive expansion (+5% on each side) yields a bigger crop.
        assert w.width > t.width
        assert w.height > t.height
