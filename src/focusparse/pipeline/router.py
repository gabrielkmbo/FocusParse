"""ROUTE_PAGES stage — hybrid recall-biased page retrieval.

v1 components (Phase 2):
  (a) sqlite FTS over PDF text + OCR text.
  (b) question-family priors (e.g. bias toward chart-rich pages for chart QA).
  (c) DocLens-style 3× repeated sampling + union.

v1 excludes (per plan §8.2): vdr-2b-multi visual reranker. Add as an ablation
in Phase 5 behind `[visual-rerank]` extra once the decision for GPU vs HF
endpoint is made. No local model loading in v1.

TODO(Phase 2): implement the FTS index + union sampler.
"""

from __future__ import annotations

from focusparse.pipeline.events import PagesEvent, PlanEvent, QuestionEvent


async def route_pages(
    question: QuestionEvent,
    plan: PlanEvent,
    *,
    doc_path: str,
    top_k: int = 5,
) -> PagesEvent:
    raise NotImplementedError("route_pages — wire in Phase 2")
