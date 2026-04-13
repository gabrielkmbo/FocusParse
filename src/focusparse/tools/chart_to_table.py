"""chart_to_table — optional chart → tabular data extraction.

Gated behind `[chart-tools]` extra. Uses numpy peak-detection on gridlines +
axis OCR to produce a CSV-shaped table. Low default confidence so the verifier
knows to double-check.

TODO(Phase 3): implement gridline detection + axis OCR fusion.
"""

from __future__ import annotations

from pydantic import BaseModel


class ChartToTableInput(BaseModel):
    crop_ref: str                              # content-addressed crop produced earlier


class ChartToTableOutput(BaseModel):
    table_csv: str
    series_names: list[str]
    x_unit: str | None = None
    y_unit: str | None = None
    confidence: float = 0.5


async def chart_to_table(inp: ChartToTableInput) -> ChartToTableOutput:
    raise NotImplementedError("chart_to_table — wire in Phase 3 (optional)")
