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
import re
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from focusparse.models.base import ModelClient

logger = logging.getLogger(__name__)

# Phase 7 (2026-05-11): the OCR-based extraction pipeline below is robust
# on synthetic-fixture charts but the Phase 4 n=148 diagnostic showed it
# returns empty CSV on every real chart it saw (10.5% attempt rate, 0%
# success). Real finance charts (axis-padded, irregular gridlines, mixed
# fonts) defeat the heuristic plot-detection + tick-OCR pipeline.
#
# `chart_to_table_llm` swaps in a vision-LLM call that reads the chart
# image directly and emits a CSV. Reuses the mid-tier reranker model so
# we don't pay a frontier-tier rate on every chart.
_LLM_CHART_SYSTEM_PROMPT = (
    "You are a chart-to-data extractor. Given an image of a chart, return "
    "STRICT JSON with these fields (no markdown, no prose outside the JSON):\n"
    '  {"csv": "x_value,y_value\\n0.0,5.0\\n1.0,10.0", '
    '"series_names": ["..."], "x_unit": "...", "y_unit": "...", '
    '"confidence": 0.85, "n_points": 2}\n'
    "\n"
    "Rules:\n"
    "1. `csv` is a CSV literal with a single header row 'x_value,y_value' "
    "and one data row per readable data point. Use '.' as decimal "
    "separator. If the chart has multiple series, emit them concatenated "
    "with a 'series' column and list names in `series_names`.\n"
    "2. If you cannot reliably read at least 2 data points from the chart, "
    "return an empty `csv` (empty string) and confidence=0.0. Do NOT "
    "hallucinate values.\n"
    "3. `x_unit` / `y_unit` are the unit strings from axis labels (e.g. "
    "'V', '%', '2024', 'million'). null when no unit is shown.\n"
    "4. `confidence` is your self-rated reliability in [0, 1] based on "
    "chart legibility and your certainty about value extraction.\n"
    "5. `n_points` is the count of data rows in `csv` (excluding header)."
)

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


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


async def chart_to_table_llm(
    inp: ChartToTableInput,
    *,
    backend_client: ModelClient,
    crop_cache_dir: Path | None = None,
) -> ChartToTableOutput:
    """LLM-based chart-to-table extraction (Phase 7).

    Replaces the OCR-based `chart_to_table` for real charts where the
    heuristic pipeline collapses (Phase 4 n=148: 10.5% attempt rate, 0%
    success). Sends the chart image to a vision model with a strict-JSON
    extraction prompt; falls back gracefully (empty CSV + confidence=0.0)
    on malformed responses, missing images, or backend errors.

    Args:
        inp: ChartToTableInput with crop_ref pointing at a chart PNG.
        backend_client: vision-capable ModelClient. Typically the
            mid-tier reranker (claude-haiku) — cheap enough at ~$0.005
            per chart and capable enough to read most chart types.
        crop_cache_dir: reserved for future cache key.

    Returns:
        ChartToTableOutput with table_csv populated when the LLM
        successfully read the chart, empty string otherwise. Never
        raises (caller treats as advisory).
    """
    del crop_cache_dir  # reserved for future cache key

    crop_path = Path(inp.crop_ref)
    if not crop_path.is_file():
        logger.warning("chart_to_table_llm: crop_ref does not exist: %s", crop_path)
        return ChartToTableOutput(table_csv="", confidence=0.0)

    user_prompt = (
        "Extract this chart's data as CSV. Follow the format described in the system prompt."
    )
    if inp.expected_x_axis:
        user_prompt += (
            f"\nPlanner hint: x-axis is '{inp.expected_x_axis}' "
            "(time / numeric / category). Format x_value accordingly."
        )

    try:
        response = await backend_client.predict(
            prompt=user_prompt,
            images=[crop_path],
            system=_LLM_CHART_SYSTEM_PROMPT,
        )
    except Exception as exc:  # noqa: BLE001 — advisory, never raise
        logger.warning("chart_to_table_llm: backend call failed (%s)", exc)
        return ChartToTableOutput(table_csv="", confidence=0.0)

    return _parse_llm_chart_response(response.text or "")


def _parse_llm_chart_response(text: str) -> ChartToTableOutput:
    """Parse the LLM's strict-JSON response. Tolerant of fenced output."""
    import json

    if not text:
        return ChartToTableOutput(table_csv="", confidence=0.0)
    candidate = text.strip()
    fence = _JSON_FENCE_RE.search(candidate)
    if fence:
        candidate = fence.group(1)
    else:
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start != -1 and end != -1 and end > start:
            candidate = candidate[start : end + 1]
    try:
        obj = json.loads(candidate)
    except json.JSONDecodeError:
        logger.debug("chart_to_table_llm: JSON parse failed on %r", text[:120])
        return ChartToTableOutput(table_csv="", confidence=0.0)
    if not isinstance(obj, dict):
        return ChartToTableOutput(table_csv="", confidence=0.0)

    csv = obj.get("csv")
    if not isinstance(csv, str):
        csv = ""
    series_names = obj.get("series_names")
    if not isinstance(series_names, list) or not all(isinstance(s, str) for s in series_names):
        series_names = []
    x_unit = obj.get("x_unit")
    if not isinstance(x_unit, str):
        x_unit = None
    y_unit = obj.get("y_unit")
    if not isinstance(y_unit, str):
        y_unit = None
    raw_conf = obj.get("confidence", 0.5)
    try:
        confidence = float(raw_conf)
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))
    raw_n = obj.get("n_points", 0)
    try:
        n_points = int(raw_n)
    except (TypeError, ValueError):
        # Fall back to counting newlines minus the header.
        n_points = max(0, csv.count("\n") - 1) if csv else 0
    return ChartToTableOutput(
        table_csv=csv,
        series_names=series_names,
        x_unit=x_unit,
        y_unit=y_unit,
        confidence=confidence,
        n_points=n_points,
    )


async def chart_to_table(
    inp: ChartToTableInput,
    *,
    crop_cache_dir: Path | None = None,
    backend_client: ModelClient | None = None,
) -> ChartToTableOutput:
    """Extract tabular data from a chart crop.

    Best-effort: returns ChartToTableOutput with confidence=0.0 and empty
    table_csv when any pipeline stage fails. Never raises (caller treats
    as advisory). When pytesseract / numpy / PIL is missing, confidence
    drops to 0.0; the deterministic pixel pipeline still tries.

    Phase 7 (2026-05-11): when `backend_client` is supplied, the LLM-based
    extractor (`chart_to_table_llm`) is called instead of the OCR pipeline.
    The OCR path is preserved for callers without a vision LLM wired —
    the Phase 4 diagnostic showed real finance charts always returned
    empty CSV under the OCR heuristic.
    """
    if backend_client is not None:
        return await chart_to_table_llm(
            inp,
            backend_client=backend_client,
            crop_cache_dir=crop_cache_dir,
        )
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
