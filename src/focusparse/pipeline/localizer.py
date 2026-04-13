"""PROPOSE_REGIONS stage — deterministic fusion of layout + OCR + priors.

Phase 2 strategy:
  - Layout detector boxes (HF endpoint via tools/layout_detect.py).
  - OCR token anchors matching question keywords.
  - Question-family priors (e.g. chart + legend + axis for axis_value_interpolation).
  Optionally: cheap-tier LLM rerank when multiple close candidates exist.

Output: RegionsEvent with a **ranked candidate set** per page, not a single bbox.
"""

from __future__ import annotations

from focusparse.pipeline.events import PagesEvent, PlanEvent, QuestionEvent, RegionsEvent


async def propose_regions(
    question: QuestionEvent,
    plan: PlanEvent,
    pages: PagesEvent,
) -> RegionsEvent:
    raise NotImplementedError("propose_regions — wire in Phase 2")
