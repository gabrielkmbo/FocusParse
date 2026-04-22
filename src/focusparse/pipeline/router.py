"""ROUTE_PAGES stage — hybrid recall-biased page retrieval.

Sub-phase 2f: when `pages_text` is supplied, we query a per-doc sqlite
FTS5 index (`focusparse.retrieval.text_index.TextIndex`) with question
tokens and return pages ranked by BM25. When no text is available we
degrade to the skeleton full-page-set behavior so downstream stages
always get *something* to work with — zero-hit FTS is the same story
(we don't know which page has the answer, so hand back every page).

Design notes:
  * Router is recall-biased: top_k defaults to `min(len(pages), 5)` when
    we have text, which matches the Phase 2 plan's "top-k=5 pages + reason
    codes" contract. Callers can pass `top_k=None` to get every matching
    page back in ranked order (useful for oracle/full-doc protocols).
  * Question-family priors (DocLens-style 3× repeated sampling, chart-bias
    for `axis_value_interpolation`, etc.) are deferred to a follow-up
    sub-phase — they need signal we don't have yet (per-page figure counts,
    table counts) and bolting them on without that signal would be noise.
  * Reason codes are stable strings so traces can attribute ranking
    decisions without parsing scores.

Reason codes:
  * `skeleton_all_pages` — no text available, returning every page.
  * `text_fts_no_matches` — text available but FTS matched nothing;
    fall back to every page (recall bias), score 0.
  * `text_fts_match` — FTS matched this page; score is BM25 (higher = better).
"""

from __future__ import annotations

from pathlib import Path

from focusparse.pipeline.events import PageCandidate, PagesEvent, PlanEvent, QuestionEvent
from focusparse.retrieval.text_index import TextIndex

_DEFAULT_TOP_K = 5


async def route_pages(
    question: QuestionEvent,
    plan: PlanEvent,
    *,
    pages: list[int],
    top_k: int | None = None,
    pages_text: dict[int, str] | None = None,
    text_index_cache_dir: Path | None = None,
) -> PagesEvent:
    """Return candidate pages ranked by text relevance, with fallback.

    Args:
        question / plan: upstream events.
        pages: every 1-indexed page number the caller has a PNG for.
            This defines the universe the router can choose from.
        top_k: cap on returned candidates. Defaults to 5 when text is
            available, or the full page list when it isn't (skeleton).
        pages_text: map of 1-indexed page -> plain text. Pages missing from
            this map are treated as empty-text pages (and thus can only be
            returned via the "no matches" fallback). When None, the router
            skips FTS entirely and returns every page.
        text_index_cache_dir: where to persist the sqlite FTS file. When
            None, the index lives in `cache/text_index/` by default, which
            is usable but not isolated per-test.

    Returns:
        A `PagesEvent` with at least one candidate per page that exists in
        `pages` (skeleton + no-match fallbacks always return the full page
        set). Ranking: FTS matches first (BM25 desc), then non-matches.
    """
    del plan  # routing_policy / question_family reserved for a later sub-phase

    if pages_text is None:
        return _skeleton_all_pages(pages, top_k=top_k)

    cache_dir = text_index_cache_dir or Path("cache") / "text_index"
    index = TextIndex(doc_id=question.doc_id, cache_dir=cache_dir)
    index.build(pages_text)

    hits_limit = top_k if top_k is not None else max(len(pages), _DEFAULT_TOP_K)
    hits = index.query(question.question, top_k=hits_limit)
    index.close()

    if not hits:
        # Query sanitized to empty OR FTS matched no page at all — the
        # router knows nothing, hand back every page so the localizer can
        # still try. This is identical to the skeleton shape but with a
        # distinct reason code so traces separate "no text" from "text
        # but no match".
        return _all_pages_with_reason(pages, reason="text_fts_no_matches", top_k=top_k)

    by_page = {page: score for page, score in hits}
    matched: list[PageCandidate] = [
        PageCandidate(page=p, score=s, reason_code="text_fts_match")
        for p, s in sorted(by_page.items(), key=lambda kv: -kv[1])
        if p in set(pages)
    ]

    # Effective top-k for the output: default to 5 when the caller didn't
    # pin it, so "text available" paths prune aggressively.
    effective_top_k = top_k if top_k is not None else _DEFAULT_TOP_K

    # Fill the remainder with non-matching pages so downstream protocols
    # that expect every page (oracle_full_doc) still work, but only if
    # the caller asked for enough slots.
    if len(matched) < effective_top_k:
        already = {c.page for c in matched}
        for p in pages:
            if p in already:
                continue
            matched.append(PageCandidate(page=p, score=0.0, reason_code="text_fts_no_matches"))
            if len(matched) >= effective_top_k:
                break

    return PagesEvent(candidates=matched[:effective_top_k])


# ---------------------------------------------------------------------------
# Skeleton fallbacks
# ---------------------------------------------------------------------------


def _skeleton_all_pages(pages: list[int], *, top_k: int | None) -> PagesEvent:
    """Every page, score 1.0, reason=`skeleton_all_pages`."""
    return _all_pages_with_reason(pages, reason="skeleton_all_pages", top_k=top_k)


def _all_pages_with_reason(pages: list[int], *, reason: str, top_k: int | None) -> PagesEvent:
    # score=1.0 for the skeleton path preserves the pre-sub-phase-2f
    # contract (every page equally likely). The text-no-match fallback
    # piggybacks on this same shape but with a different reason code.
    score = 1.0 if reason == "skeleton_all_pages" else 0.0
    sliced = pages if top_k is None else pages[:top_k]
    return PagesEvent(
        candidates=[PageCandidate(page=p, score=score, reason_code=reason) for p in sliced]
    )
