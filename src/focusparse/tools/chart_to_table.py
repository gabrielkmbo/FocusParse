"""chart_to_table — pixel-level chart → tabular data extraction.

Sprint Phase 3 (Phase 6 candidate #7). The headline-v1 diagnostic showed
focus +4 trails Base VLM by 4.2pp on Finance — chart-reading is the
likely culprit. This tool gives the inspector a way to extract a CSV
from a chart crop *before* the reasoner sees it, so axis-value
interpolation and candlestick OHLC questions land on hard data instead
of guesses.

Pipeline:
  1. Load the chart crop as a numpy array (PIL).
  2. Detect the plot area: row/col edge sums find the gridline-rich
     plot rectangle.
  3. OCR axis tick labels via pytesseract on the left + bottom strips.
  4. Interpolate per-column: find the darkest non-axis pixel in each
     column inside the plot, map (col_px, row_px) → (x_data, y_data)
     via the OCR-derived axis ticks.
  5. Emit `table_csv` with header `x_value,y_value`.

Confidence reflects two factors: axis OCR confidence (per-character)
averaged across visible ticks, and plot detection confidence (1.0 when
≥4 gridlines on each side, scaled down linearly when fewer).

Research-grade. Pytesseract failure or unparseable axis labels collapses
confidence; the inspector's caller treats it as advisory evidence (the
reasoner still sees the raw crop alongside).

Gated on the inspector side by `question_family ∈ {axis_value_interpolation,
candlestick_ohlc_extraction}` AND `region.figure_class ∈ {bar_chart,
line_chart, candlestick}`. This keeps cost bounded — most n=148 examples
don't hit it.
"""

from __future__ import annotations

import logging
from pathlib import Path

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class ChartToTableInput(BaseModel):
    crop_ref: str = Field(
        ...,
        description="Absolute path to the chart crop PNG (an inspect_region.crop_ref).",
    )
    expected_x_axis: str | None = Field(
        default=None,
        description=(
            "Optional planner hint: 'time' | 'numeric' | 'category'. Influences "
            "tick parsing (e.g. dates vs floats)."
        ),
    )


class ChartToTableOutput(BaseModel):
    table_csv: str = Field(
        ...,
        description=(
            "CSV table extracted from the chart. Header: x_value,y_value. "
            "Empty string when extraction failed."
        ),
    )
    series_names: list[str] = Field(
        default_factory=list,
        description="Detected series names (legend OCR). Empty when no legend was detected.",
    )
    x_unit: str | None = Field(default=None, description="X-axis unit if OCR resolved one.")
    y_unit: str | None = Field(default=None, description="Y-axis unit if OCR resolved one.")
    confidence: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Overall extraction confidence; advisory for the verifier stage.",
    )
    n_points: int = Field(default=0, description="Number of (x, y) rows in the CSV.")


async def chart_to_table(
    inp: ChartToTableInput,
    *,
    crop_cache_dir: Path | None = None,
) -> ChartToTableOutput:
    """Extract tabular data from a chart crop.

    Best-effort: returns ChartToTableOutput with confidence=0.0 and empty
    table_csv when any pipeline stage fails. Never raises (caller treats
    as advisory). When pytesseract / numpy / PIL is missing, confidence
    drops to 0.0; the deterministic pixel pipeline still tries.
    """
    del crop_cache_dir  # reserved for future cache key

    try:
        import numpy as np  # noqa: F401  (used in helpers below)
        from PIL import Image
    except ImportError as exc:
        logger.warning("chart_to_table: numpy/PIL not available (%s)", exc)
        return ChartToTableOutput(table_csv="", confidence=0.0)

    crop_path = Path(inp.crop_ref)
    if not crop_path.is_file():
        logger.warning("chart_to_table: crop_ref does not exist: %s", crop_path)
        return ChartToTableOutput(table_csv="", confidence=0.0)

    try:
        with Image.open(crop_path) as im:
            rgb = im.convert("RGB")
            import numpy as np

            arr = np.array(rgb)
    except Exception as exc:  # noqa: BLE001 — best-effort
        logger.warning("chart_to_table: could not decode %s: %s", crop_path, exc)
        return ChartToTableOutput(table_csv="", confidence=0.0)

    plot_box, plot_conf = _detect_plot_area(arr)
    if plot_box is None:
        return ChartToTableOutput(table_csv="", confidence=0.0)

    x_ticks, y_ticks, ocr_conf = _ocr_axis_ticks(arr, plot_box)

    x_data, y_data = _extrapolate_data_points(arr, plot_box, x_ticks, y_ticks)
    if not x_data:
        return ChartToTableOutput(table_csv="", confidence=plot_conf * 0.5)

    rows = ["x_value,y_value"]
    for x, y in zip(x_data, y_data, strict=False):
        rows.append(f"{x:.4f},{y:.4f}")
    table_csv = "\n".join(rows)

    confidence = (plot_conf * 0.5) + (ocr_conf * 0.5)
    return ChartToTableOutput(
        table_csv=table_csv,
        confidence=confidence,
        n_points=len(x_data),
    )


# ---------------------------------------------------------------------------
# Pipeline helpers (private)
# ---------------------------------------------------------------------------


def _detect_plot_area(arr) -> tuple[tuple[int, int, int, int] | None, float]:
    """Find the rectangular plot region inside the crop.

    Strategy: convert to grayscale, take horizontal+vertical edge sums,
    find the longest run of non-zero edges on each axis to identify the
    plot bounding box. Confidence = 1.0 when ≥4 gridlines on each side,
    linear scale-down when fewer.

    Returns ((x0, y0, x1, y1) in crop pixel space, confidence) or
    (None, 0.0) on failure.
    """
    try:
        import numpy as np
    except ImportError:
        return None, 0.0

    h, w, _ = arr.shape
    if h < 30 or w < 30:
        return None, 0.0

    gray = arr.mean(axis=2)
    col_edges = np.abs(np.diff(gray, axis=0)).sum(axis=0)
    row_edges = np.abs(np.diff(gray, axis=1)).sum(axis=1)

    col_thresh = col_edges.mean() + 0.5 * col_edges.std()
    row_thresh = row_edges.mean() + 0.5 * row_edges.std()

    col_active = col_edges > col_thresh
    row_active = row_edges > row_thresh

    x0 = int(np.argmax(col_active)) if col_active.any() else 0
    x1 = int(w - np.argmax(col_active[::-1]) - 1) if col_active.any() else w - 1
    y0 = int(np.argmax(row_active)) if row_active.any() else 0
    y1 = int(h - np.argmax(row_active[::-1]) - 1) if row_active.any() else h - 1

    if x1 <= x0 + 10 or y1 <= y0 + 10:
        return None, 0.0

    n_v_lines = int(col_active.sum())
    n_h_lines = int(row_active.sum())
    confidence = min(1.0, (min(n_v_lines, n_h_lines) / 8.0))

    return (x0, y0, x1, y1), confidence


def _ocr_axis_ticks(
    arr,
    plot_box: tuple[int, int, int, int],
) -> tuple[list[tuple[int, float]], list[tuple[int, float]], float]:
    """OCR the left + bottom strips for axis tick labels.

    Returns:
        x_ticks: list of (pixel_col, data_value) for the bottom axis.
        y_ticks: list of (pixel_row, data_value) for the left axis.
        ocr_conf: average tesseract confidence across detected tick chars in [0,1].
    """
    try:
        import numpy as np
        import pytesseract
        from PIL import Image
    except ImportError:
        return [], [], 0.0

    x0, y0, x1, y1 = plot_box
    h, w, _ = arr.shape

    left_strip = arr[y0:y1, max(0, x0 - 80) : x0]
    bottom_strip = arr[y1 : min(h, y1 + 60), x0:x1]

    x_ticks: list[tuple[int, float]] = []
    y_ticks: list[tuple[int, float]] = []
    confs: list[float] = []

    for strip, axis in ((left_strip, "y"), (bottom_strip, "x")):
        if strip.size == 0:
            continue
        try:
            tsv = pytesseract.image_to_data(
                Image.fromarray(strip),
                output_type=pytesseract.Output.DICT,
            )
        except (pytesseract.TesseractNotFoundError, OSError) as exc:
            logger.debug("axis OCR (%s) failed: %s", axis, exc)
            continue

        for i, raw_text in enumerate(tsv.get("text") or []):
            text = (raw_text or "").strip()
            if not text:
                continue
            value = _parse_tick_label(text)
            if value is None:
                continue
            try:
                conf = float(tsv["conf"][i])
            except (KeyError, TypeError, ValueError):
                continue
            if conf < 0:
                continue
            confs.append(conf / 100.0)
            cx = (tsv["left"][i] + tsv["width"][i] // 2) + (x0 if axis == "x" else 0)
            cy = (tsv["top"][i] + tsv["height"][i] // 2) + (y0 if axis == "y" else 0)
            if axis == "x":
                x_ticks.append((cx, value))
            else:
                y_ticks.append((cy, value))

    ocr_conf = float(np.mean(confs)) if confs else 0.0
    x_ticks.sort()
    y_ticks.sort()
    return x_ticks, y_ticks, ocr_conf


def _parse_tick_label(text: str) -> float | None:
    """Parse a tick label like '5.0' / '$1,234' / '50%' into a float.

    Returns None if no numeric content can be extracted.
    """
    cleaned = text.replace("$", "").replace(",", "").replace("%", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return None


def _extrapolate_data_points(
    arr,
    plot_box: tuple[int, int, int, int],
    x_ticks: list[tuple[int, float]],
    y_ticks: list[tuple[int, float]],
) -> tuple[list[float], list[float]]:
    """Walk every column inside the plot, find the darkest pixel, map to data.

    Requires at least 2 x-ticks and 2 y-ticks for linear interpolation.
    Returns ([], []) when extraction is infeasible.
    """
    try:
        import numpy as np
    except ImportError:
        return [], []

    if len(x_ticks) < 2 or len(y_ticks) < 2:
        return [], []

    x0, y0, x1, y1 = plot_box
    plot_arr = arr[y0:y1, x0:x1].mean(axis=2)

    x_pix = np.array([t[0] for t in x_ticks])
    x_val = np.array([t[1] for t in x_ticks])
    y_pix = np.array([t[0] for t in y_ticks])
    y_val = np.array([t[1] for t in y_ticks])

    x_slope, x_intercept = np.polyfit(x_pix, x_val, 1)
    y_slope, y_intercept = np.polyfit(y_pix, y_val, 1)

    plot_h, plot_w = plot_arr.shape
    if plot_w == 0 or plot_h == 0:
        return [], []

    sample_cols = list(range(0, plot_w, max(1, plot_w // 50)))
    x_data: list[float] = []
    y_data: list[float] = []
    for col in sample_cols:
        column = plot_arr[:, col]
        row = int(np.argmin(column))
        crop_col = col + x0
        crop_row = row + y0
        x_data.append(float(x_slope * crop_col + x_intercept))
        y_data.append(float(y_slope * crop_row + y_intercept))

    return x_data, y_data
