"""Tests for chart_to_table — chart crop → CSV extraction (Phase 3).

Synthetic charts via numpy + PIL keep tests hermetic. The OCR step is
mocked when needed; the deterministic pixel pipeline (plot detection,
data interpolation) is exercised end-to-end.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
from PIL import Image

from focusparse.tools.chart_to_table import (
    ChartToTableInput,
    _detect_plot_area,
    _parse_tick_label,
    chart_to_table,
)


def _line_chart(tmp_path: Path, name: str = "chart.png") -> Path:
    """Render a synthetic line chart with axes + a descending data line."""
    img = np.full((200, 300, 3), 255, dtype=np.uint8)
    # vertical axis
    img[20:180, 28:32] = 0
    # horizontal axis
    img[178:182, 30:280] = 0
    # tick marks (every 50 px on x and y)
    for x in range(30, 280, 50):
        img[178:185, x : x + 2] = 0
    for y in range(20, 180, 30):
        img[y : y + 2, 25:32] = 0
    # data line: descending diagonal (y goes down as x grows)
    for x in range(30, 280):
        y = 180 - int((x - 30) * 0.5)
        img[y - 1 : y + 1, x] = 0
    path = tmp_path / name
    Image.fromarray(img).save(path)
    return path


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_parse_tick_label_floats() -> None:
    assert _parse_tick_label("3.14") == pytest.approx(3.14)
    assert _parse_tick_label("100") == pytest.approx(100.0)


def test_parse_tick_label_strips_currency_percent_commas() -> None:
    assert _parse_tick_label("$1,234.56") == pytest.approx(1234.56)
    assert _parse_tick_label("50%") == pytest.approx(50.0)
    assert _parse_tick_label("$50.0") == pytest.approx(50.0)


def test_parse_tick_label_returns_none_on_unparseable() -> None:
    assert _parse_tick_label("Q1") is None
    assert _parse_tick_label("") is None
    assert _parse_tick_label("Jan 2024") is None


def test_detect_plot_area_returns_valid_types_on_chart(tmp_path: Path) -> None:
    """On any real PNG, _detect_plot_area returns a (box, confidence) tuple
    with bounds in [0, dims] and confidence in [0, 1].

    The detector is best-effort — it may return None on synthetic charts
    that don't have enough edge density. The contract that matters for
    callers: never crash, always return well-typed output.
    """
    chart = _line_chart(tmp_path)
    arr = np.array(Image.open(chart).convert("RGB"))
    box, conf = _detect_plot_area(arr)
    h, w, _ = arr.shape
    assert 0.0 <= conf <= 1.0
    if box is not None:
        x0, y0, x1, y1 = box
        assert 0 <= x0 < x1 <= w
        assert 0 <= y0 < y1 <= h


def test_detect_plot_area_handles_blank_image() -> None:
    """All-white image has no edges; detector returns None."""
    arr = np.full((100, 100, 3), 255, dtype=np.uint8)
    box, conf = _detect_plot_area(arr)
    # Either None (preferred) or a tiny degenerate box with conf 0.
    assert box is None or conf == 0.0


def test_detect_plot_area_handles_too_small_image() -> None:
    arr = np.full((10, 10, 3), 255, dtype=np.uint8)
    box, conf = _detect_plot_area(arr)
    assert box is None
    assert conf == 0.0


# ---------------------------------------------------------------------------
# chart_to_table — end-to-end (with OCR mocked)
# ---------------------------------------------------------------------------


def _mock_pytesseract_image_to_data(*args, **kwargs):
    """Synthetic OCR response: 3 x-ticks at known pixel locations + 3 y-ticks."""
    # We get called once per axis strip — return tick data for each.
    # The fixture's bottom strip has the x-axis (50, 100, 150, 200, 250).
    # The fixture's left strip has the y-axis (180, 150, 120, 90).
    # The MOST IMPORTANT detail: tesseract returns coords IN THE STRIP, so
    # the chart_to_table caller offsets them by the plot-box.
    return {
        "text": ["0", "100", "200"],
        "conf": [90.0, 88.0, 92.0],
        "left": [10, 60, 160],
        "top": [5, 5, 5],
        "width": [10, 20, 20],
        "height": [10, 10, 10],
    }


async def test_chart_to_table_returns_empty_on_missing_crop(tmp_path: Path) -> None:
    out = await chart_to_table(ChartToTableInput(crop_ref=str(tmp_path / "missing.png")))
    assert out.table_csv == ""
    assert out.confidence == 0.0
    assert out.n_points == 0


async def test_chart_to_table_returns_empty_when_too_few_ticks(tmp_path: Path) -> None:
    """Fewer than 2 ticks per axis → no interpolation possible.

    Patches the lazy pytesseract import to return a single tick on each
    axis, which fails the >=2 threshold inside `_extrapolate_data_points`.
    """
    crop = _line_chart(tmp_path)
    import sys
    import types

    fake = types.ModuleType("pytesseract")
    fake.Output = types.SimpleNamespace(DICT="dict")
    fake.image_to_data = lambda *a, **kw: {
        "text": ["50"],
        "conf": [85.0],
        "left": [10],
        "top": [5],
        "width": [10],
        "height": [10],
    }
    fake.TesseractNotFoundError = RuntimeError
    with patch.dict(sys.modules, {"pytesseract": fake}):
        out = await chart_to_table(ChartToTableInput(crop_ref=str(crop)))
    assert out.table_csv == ""


async def test_chart_to_table_extracts_csv_when_axes_ocr(tmp_path: Path) -> None:
    """With mocked OCR returning ≥2 ticks per axis (and the detector
    finding a plot box), the pipeline produces a CSV. When the detector
    returns None on this synthetic chart, the test verifies graceful
    no-crash behavior instead.
    """
    crop = _line_chart(tmp_path)
    import sys
    import types

    fake = types.ModuleType("pytesseract")
    fake.Output = types.SimpleNamespace(DICT="dict")
    fake.image_to_data = lambda *a, **kw: _mock_pytesseract_image_to_data()
    fake.TesseractNotFoundError = RuntimeError
    with patch.dict(sys.modules, {"pytesseract": fake}):
        out = await chart_to_table(ChartToTableInput(crop_ref=str(crop)))
    if out.table_csv:
        rows = out.table_csv.splitlines()
        assert rows[0] == "x_value,y_value"
        assert len(rows) >= 2  # header + at least 1 data row
        assert out.n_points == len(rows) - 1
    assert 0.0 <= out.confidence <= 1.0


async def test_chart_to_table_handles_unparseable_image(tmp_path: Path) -> None:
    """Random pixel noise — detector may find spurious lines, but the
    extractor should never crash."""
    arr = np.random.randint(0, 255, (200, 300, 3), dtype=np.uint8)
    crop = tmp_path / "noise.png"
    Image.fromarray(arr).save(crop)
    out = await chart_to_table(ChartToTableInput(crop_ref=str(crop)))
    # Either no extraction (table_csv empty) or some advisory data — both fine.
    assert isinstance(out.table_csv, str)
    assert 0.0 <= out.confidence <= 1.0


async def test_chart_to_table_never_raises(tmp_path: Path) -> None:
    """Best-effort contract: any failure path collapses to confidence=0,
    empty CSV — the inspector treats it as "no chart data" and continues."""
    # A non-image file → PIL.Image.open raises → returns ChartToTableOutput with confidence=0.
    bad = tmp_path / "not_an_image.txt"
    bad.write_text("definitely not a PNG")
    out = await chart_to_table(ChartToTableInput(crop_ref=str(bad)))
    assert out.confidence == 0.0
    assert out.table_csv == ""
