"""ROUTE_PAGES stage — hybrid recall-biased page retrieval.

Phase 2 skeleton: return every available page as a candidate. This lets the
downstream stages run end-to-end before the real retrieval layer exists.

v1 components (sub-phase 2c and later):
  (a) sqlite FTS over PDF text + OCR text.
  (b) question-family priors (bias toward chart-rich pages for chart QA).
  (c) DocLens-style 3× repeated sampling + union.

v1 excludes (per plan §8.2): vdr-2b-multi visual reranker. Add as an ablation
in Phase 5 behind `[visual-rerank]` extra.
"""

from __future__ import annotations

from focusparse.pipeline.events import PageCandidate, PagesEvent, PlanEvent, QuestionEvent


async def route_pages(
    question: QuestionEvent,
    plan: PlanEvent,
    *,
    n_pages: int,
    top_k: int | None = None,
) -> PagesEvent:
    """Skeleton retrieval: every page is a candidate.

    `n_pages` is the number of PNGs available for this example. The caller
    gets it from `len(example.page_images)`. When `top_k` is set we truncate;
    otherwise we return all pages so oracle-style protocols still work.
    """
    del question, plan  # unused in skeleton
    limit = n_pages if top_k is None else min(top_k, n_pages)
    candidates = [
        PageCandidate(page=i + 1, score=1.0, reason_code="skeleton_all_pages") for i in range(limit)
    ]
    return PagesEvent(candidates=candidates)
