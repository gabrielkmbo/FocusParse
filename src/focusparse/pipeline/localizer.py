"""PROPOSE_REGIONS stage — deterministic fusion of layout + OCR + priors.

Phase 2 skeleton: emit one full-page region per candidate page. The real
layout-driven localizer lands in sub-phase 2e once `tools/layout_detect.py`
is wired.

v1 strategy:
  - Layout detector boxes (HF endpoint via tools/layout_detect.py).
  - OCR token anchors matching question keywords.
  - Question-family priors (chart + legend + axis for axis_value_interpolation).
  Optionally: cheap-tier LLM rerank when multiple close candidates exist.

Output: `RegionsEvent` with a **ranked candidate set** per page, not a single bbox.
"""

from __future__ import annotations

from focusparse.pipeline.events import (
    PagesEvent,
    PlanEvent,
    QuestionEvent,
    RegionCandidate,
    RegionsEvent,
)


async def propose_regions(
    question: QuestionEvent,
    plan: PlanEvent,
    pages: PagesEvent,
) -> RegionsEvent:
    """Skeleton: full-page bbox per candidate page.

    No layout detection, no OCR — just a deterministic (0,0,1,1) region per
    page so the inspector has something to wrap into an `EvidencePacket`.
    """
    del question, plan  # unused in skeleton
    candidates = [
        RegionCandidate(
            region_id=f"r{i}_p{pc.page}",
            page=pc.page,
            bbox_norm=(0.0, 0.0, 1.0, 1.0),
            region_type=None,
            score=pc.score,
            supporting_signals=["skeleton_full_page"],
        )
        for i, pc in enumerate(pages.candidates)
    ]
    return RegionsEvent(candidates=candidates)
