"""inspect_region — the unified zoom/crop/OCR primitive (AgenticOCR-style).

Exactly three modes. Do not add a fourth without updating the plan.

  image:   crop only, no OCR. Cheapest. Use for visual inspection before committing.
  element: crop + Tesseract OCR. Use when the target region is known + tight.
  region:  crop + sub-layout detection on the crop + OCR per sub-element. Highest
           cost; use for mixed structures like chart+legend+caption or table+notes.

TODO(Phase 3): wire PyMuPDF crop, Tesseract, layout HTTP, cache lookups.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class InspectRegionInput(BaseModel):
    doc_id: str
    page: int = Field(ge=1, description="1-indexed page number")
    bbox_norm: tuple[float, float, float, float]
    mode: Literal["image", "element", "region"] = "element"
    dpi: int = 300
    rotation: int = 0
    expansion: Literal["none", "default", "aggressive"] = "default"


class InspectRegionOutput(BaseModel):
    crop_ref: str                              # content-addressed cache key
    ocr_text: str | None = None
    sub_regions: list[dict] = Field(default_factory=list)
    confidence: float = 1.0
    tokens_used: int = 0
    latency_ms: int = 0


async def inspect_region(inp: InspectRegionInput) -> InspectRegionOutput:
    raise NotImplementedError("inspect_region — wire in Phase 3")
