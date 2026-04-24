"""Tests for `focusparse.tools.get_text_layer.get_text_layer`.

Generates small PyMuPDF PDFs on the fly so tests stay hermetic — no
checked-in binary fixtures. Covers:
  * native text extraction returns span list + joined text
  * `bbox_norm` filtering keeps spans whose centroid lies inside
  * image-only page returns `source="empty_native"` with no spans
  * 1-indexed page arg: page=1 is page 0 in PyMuPDF internals
  * out-of-range page raises ValueError
  * missing file raises FileNotFoundError
  * disk cache round-trip: first call writes JSON, second returns same output
  * cache key changes when page or bbox changes (same PDF)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from focusparse.tools.get_text_layer import (
    GetTextLayerInput,
    GetTextLayerOutput,
    get_text_layer,
)


def _write_pdf(path: Path, pages: list[list[tuple[str, tuple[float, float]]]]) -> Path:
    """Write a PDF with `pages` where each page is a list of `(text, (x, y))`.

    `x, y` are PDF-point coordinates with top-left origin.
    """
    import fitz

    path.parent.mkdir(parents=True, exist_ok=True)
    doc = fitz.open()
    for page_spec in pages:
        page = doc.new_page(width=600, height=800)
        for text, (x, y) in page_spec:
            page.insert_text((x, y), text, fontsize=12)
    doc.save(path)
    doc.close()
    return path


def _write_image_only_pdf(path: Path) -> Path:
    """Write a PDF page with no native text (just a blank page)."""
    import fitz

    path.parent.mkdir(parents=True, exist_ok=True)
    doc = fitz.open()
    doc.new_page(width=600, height=800)  # no insert_text calls
    doc.save(path)
    doc.close()
    return path


# ---------------------------------------------------------------------------
# Native extraction
# ---------------------------------------------------------------------------


async def test_extracts_native_text_and_spans(tmp_path):
    pdf = _write_pdf(
        tmp_path / "doc.pdf",
        pages=[
            [("Hello world", (50, 50)), ("VCC maximum", (50, 100))],
        ],
    )
    out = await get_text_layer(GetTextLayerInput(doc_path=str(pdf), page=1))
    assert isinstance(out, GetTextLayerOutput)
    assert out.source == "native"
    assert "Hello world" in out.text
    assert "VCC maximum" in out.text
    # Two logical spans, one per line.
    assert len(out.spans) == 2
    # Spans carry absolute PDF-point bboxes.
    for span in out.spans:
        assert all(isinstance(v, float) for v in span.bbox)
        assert span.confidence == 1.0
    assert out.page_width == pytest.approx(600.0)
    assert out.page_height == pytest.approx(800.0)


async def test_pages_are_one_indexed(tmp_path):
    pdf = _write_pdf(
        tmp_path / "multi.pdf",
        pages=[
            [("page one alpha", (50, 50))],
            [("page two beta", (50, 50))],
        ],
    )
    out1 = await get_text_layer(GetTextLayerInput(doc_path=str(pdf), page=1))
    out2 = await get_text_layer(GetTextLayerInput(doc_path=str(pdf), page=2))
    assert "alpha" in out1.text and "alpha" not in out2.text
    assert "beta" in out2.text and "beta" not in out1.text


async def test_bbox_norm_filters_spans_by_centroid(tmp_path):
    pdf = _write_pdf(
        tmp_path / "crop.pdf",
        pages=[
            [
                ("top-left header", (50, 50)),  # y~50 -> top band
                ("middle content", (50, 400)),  # y~400 -> middle
                ("bottom footer", (50, 750)),  # y~750 -> bottom band
            ],
        ],
    )
    # Ask only for the top ~1/8 of the page (y in [0, 100]).
    out = await get_text_layer(
        GetTextLayerInput(
            doc_path=str(pdf),
            page=1,
            bbox_norm=(0.0, 0.0, 1.0, 100.0 / 800.0),
        )
    )
    assert "top-left header" in out.text
    assert "middle content" not in out.text
    assert "bottom footer" not in out.text


async def test_image_only_page_returns_empty_native(tmp_path):
    pdf = _write_image_only_pdf(tmp_path / "blank.pdf")
    out = await get_text_layer(GetTextLayerInput(doc_path=str(pdf), page=1))
    assert out.source == "empty_native"
    assert out.text == ""
    assert out.spans == []


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


async def test_missing_file_raises_file_not_found(tmp_path):
    missing = tmp_path / "nope.pdf"
    with pytest.raises(FileNotFoundError):
        await get_text_layer(GetTextLayerInput(doc_path=str(missing), page=1))


async def test_out_of_range_page_raises_value_error(tmp_path):
    pdf = _write_pdf(tmp_path / "one_page.pdf", pages=[[("only", (50, 50))]])
    with pytest.raises(ValueError, match="out of range"):
        await get_text_layer(GetTextLayerInput(doc_path=str(pdf), page=99))


# ---------------------------------------------------------------------------
# Disk cache
# ---------------------------------------------------------------------------


async def test_cache_round_trip(tmp_path, monkeypatch):
    pdf = _write_pdf(tmp_path / "cache.pdf", pages=[[("cached text", (50, 50))]])
    cache_dir = tmp_path / "cache"

    out1 = await get_text_layer(
        GetTextLayerInput(doc_path=str(pdf), page=1),
        cache_dir=cache_dir,
    )
    cached_files = list(cache_dir.glob("*.json"))
    assert len(cached_files) == 1
    # Cached JSON should round-trip back to the same pydantic shape.
    assert "cached text" in cached_files[0].read_text()

    # Second call: the cache-key hash is content-addressed, so the PDF
    # still needs to exist on disk, but `_extract_page_text` must not be
    # called again. Monkeypatch it to a tripwire.
    import focusparse.tools.get_text_layer as mod

    def _must_not_be_called(*args, **kwargs):
        raise AssertionError("_extract_page_text re-ran despite cache hit")

    monkeypatch.setattr(mod, "_extract_page_text", _must_not_be_called)

    out2 = await get_text_layer(
        GetTextLayerInput(doc_path=str(pdf), page=1),
        cache_dir=cache_dir,
    )
    assert out1.text == out2.text
    assert [s.bbox for s in out1.spans] == [s.bbox for s in out2.spans]


async def test_cache_key_changes_with_page_and_bbox(tmp_path):
    pdf = _write_pdf(
        tmp_path / "multi.pdf",
        pages=[[("alpha", (50, 50))], [("beta", (50, 50))]],
    )
    cache_dir = tmp_path / "cache"

    await get_text_layer(
        GetTextLayerInput(doc_path=str(pdf), page=1),
        cache_dir=cache_dir,
    )
    await get_text_layer(
        GetTextLayerInput(doc_path=str(pdf), page=2),
        cache_dir=cache_dir,
    )
    await get_text_layer(
        GetTextLayerInput(
            doc_path=str(pdf),
            page=1,
            bbox_norm=(0.0, 0.0, 0.5, 0.5),
        ),
        cache_dir=cache_dir,
    )
    # Three distinct cache entries.
    assert len(list(cache_dir.glob("*.json"))) == 3


async def test_no_cache_dir_means_no_cache_files_written(tmp_path):
    pdf = _write_pdf(tmp_path / "uncached.pdf", pages=[[("x", (50, 50))]])
    out = await get_text_layer(GetTextLayerInput(doc_path=str(pdf), page=1))
    # Ensure the call still succeeded without a cache dir.
    assert "x" in out.text
    # Nothing dumped beside the PDF.
    assert list(tmp_path.glob("*.json")) == []
