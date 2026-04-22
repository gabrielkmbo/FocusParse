"""Tests for `focusparse.pipeline.router.route_pages`.

Covers the three reason-code paths (skeleton_all_pages, text_fts_match,
text_fts_no_matches), top_k truncation, score-descending ordering,
empty-query + empty-corpus edges, and pages-in-text-but-not-available
behavior.
"""

from __future__ import annotations

import pytest

from focusparse.pipeline.events import PlanEvent, QuestionEvent
from focusparse.pipeline.router import route_pages


def _question(q: str = "What is VCC max?") -> QuestionEvent:
    return QuestionEvent(
        example_id="ex-1",
        question=q,
        doc_id="doc-router-test",
        pages_available=10,
    )


def _plan() -> PlanEvent:
    return PlanEvent(
        question_family="single_value_lookup",
        evidence_types=["table"],
        budget_class="easy_local",
        routing_policy="text_first",
        max_tool_calls=12,
        max_crops=8,
        max_vlm_calls=4,
    )


# ---------------------------------------------------------------------------
# Skeleton fallback (no text available)
# ---------------------------------------------------------------------------


async def test_route_pages_skeleton_when_no_text_provided():
    pages = await route_pages(_question(), _plan(), pages=[1, 2, 3, 4, 5])
    assert [c.page for c in pages.candidates] == [1, 2, 3, 4, 5]
    assert all(c.reason_code == "skeleton_all_pages" for c in pages.candidates)
    assert all(c.score == 1.0 for c in pages.candidates)


async def test_route_pages_skeleton_respects_top_k():
    pages = await route_pages(_question(), _plan(), pages=[1, 2, 3, 4, 5], top_k=2)
    assert [c.page for c in pages.candidates] == [1, 2]
    assert all(c.reason_code == "skeleton_all_pages" for c in pages.candidates)


# ---------------------------------------------------------------------------
# FTS-driven ranking
# ---------------------------------------------------------------------------


async def test_route_pages_ranks_by_bm25_when_text_available(tmp_path):
    pages_text = {
        1: "Introduction and general overview.",
        2: "VCC maximum rating is 3.6 volts. Exceeding VCC may damage the device.",
        3: "Ordering information and package dimensions.",
        4: "VCC typical is 3.3 volts under nominal load.",
        5: "Electrical characteristics table.",
    }
    pages = await route_pages(
        _question("What is VCC max?"),
        _plan(),
        pages=[1, 2, 3, 4, 5],
        pages_text=pages_text,
        text_index_cache_dir=tmp_path,
    )
    # Page 2 (has both VCC + max) should rank above page 4 (only VCC).
    ranked_matches = [c for c in pages.candidates if c.reason_code == "text_fts_match"]
    assert ranked_matches[0].page == 2
    assert 4 in [c.page for c in ranked_matches]
    # Matched pages have positive BM25 score.
    assert all(c.score > 0 for c in ranked_matches)
    # Non-matches are filled at score 0 to hit the default top_k.
    non_matches = [c for c in pages.candidates if c.reason_code == "text_fts_no_matches"]
    assert all(c.score == 0.0 for c in non_matches)


async def test_route_pages_returns_at_most_default_top_k_when_text_available(tmp_path):
    """Default top_k=5 when pages_text is supplied; this prunes aggressively."""
    pages_text = {i: f"page {i} body content VCC info" for i in range(1, 21)}
    pages = await route_pages(
        _question("VCC"),
        _plan(),
        pages=list(range(1, 21)),
        pages_text=pages_text,
        text_index_cache_dir=tmp_path,
    )
    assert len(pages.candidates) == 5
    assert all(c.reason_code == "text_fts_match" for c in pages.candidates)


async def test_route_pages_caller_top_k_overrides_default(tmp_path):
    pages_text = {i: f"page {i} VCC" for i in range(1, 11)}
    pages = await route_pages(
        _question("VCC"),
        _plan(),
        pages=list(range(1, 11)),
        top_k=3,
        pages_text=pages_text,
        text_index_cache_dir=tmp_path,
    )
    assert len(pages.candidates) == 3


async def test_route_pages_filters_out_pages_not_in_available_set(tmp_path):
    """pages_text may include pages the caller doesn't have PNGs for."""
    pages_text = {
        1: "VCC maximum rating",  # has PNG
        2: "VCC typical value",  # no PNG
        3: "unrelated text",  # has PNG
    }
    pages = await route_pages(
        _question("VCC"),
        _plan(),
        pages=[1, 3],  # page 2 excluded
        pages_text=pages_text,
        text_index_cache_dir=tmp_path,
    )
    assert 2 not in [c.page for c in pages.candidates]
    # Page 1 (VCC match) ranked first with text_fts_match.
    assert pages.candidates[0].page == 1
    assert pages.candidates[0].reason_code == "text_fts_match"


# ---------------------------------------------------------------------------
# Zero-match fallback
# ---------------------------------------------------------------------------


async def test_route_pages_falls_back_when_fts_matches_nothing(tmp_path):
    pages_text = {
        1: "alpha bravo charlie",
        2: "delta echo foxtrot",
    }
    pages = await route_pages(
        _question("completely unrelated zulu"),
        _plan(),
        pages=[1, 2],
        pages_text=pages_text,
        text_index_cache_dir=tmp_path,
    )
    # Every page returned with the no-match reason.
    assert [c.page for c in pages.candidates] == [1, 2]
    assert all(c.reason_code == "text_fts_no_matches" for c in pages.candidates)
    assert all(c.score == 0.0 for c in pages.candidates)


async def test_route_pages_falls_back_on_punctuation_only_question(tmp_path):
    pages_text = {1: "some content", 2: "other content"}
    pages = await route_pages(
        _question("?!"),  # sanitizes to empty
        _plan(),
        pages=[1, 2],
        pages_text=pages_text,
        text_index_cache_dir=tmp_path,
    )
    assert all(c.reason_code == "text_fts_no_matches" for c in pages.candidates)


async def test_route_pages_empty_pages_text_falls_back(tmp_path):
    pages = await route_pages(
        _question(),
        _plan(),
        pages=[1, 2, 3],
        pages_text={},  # empty dict: text-aware path but zero corpus
        text_index_cache_dir=tmp_path,
    )
    assert [c.page for c in pages.candidates] == [1, 2, 3]
    assert all(c.reason_code == "text_fts_no_matches" for c in pages.candidates)


# ---------------------------------------------------------------------------
# Ordering invariant
# ---------------------------------------------------------------------------


async def test_route_pages_matches_precede_non_matches(tmp_path):
    pages_text = {
        1: "no match here",
        2: "VCC maximum rating",
        3: "nothing relevant",
        4: "VCC and more VCC VCC",
    }
    pages = await route_pages(
        _question("VCC"),
        _plan(),
        pages=[1, 2, 3, 4],
        top_k=4,
        pages_text=pages_text,
        text_index_cache_dir=tmp_path,
    )
    reasons = [c.reason_code for c in pages.candidates]
    # All matches come first, then fills.
    match_reasons = [r for r in reasons if r == "text_fts_match"]
    assert reasons[: len(match_reasons)] == match_reasons
    # Within matches, BM25 scores are non-increasing.
    match_scores = [c.score for c in pages.candidates if c.reason_code == "text_fts_match"]
    assert match_scores == sorted(match_scores, reverse=True)


# ---------------------------------------------------------------------------
# Cache wiring
# ---------------------------------------------------------------------------


async def test_route_pages_writes_to_cache_dir(tmp_path):
    pages_text = {1: "VCC maximum", 2: "GND reference"}
    await route_pages(
        _question("VCC"),
        _plan(),
        pages=[1, 2],
        pages_text=pages_text,
        text_index_cache_dir=tmp_path,
    )
    assert len(list(tmp_path.glob("*.sqlite"))) == 1


@pytest.mark.parametrize("top_k", [1, 3, 10])
async def test_route_pages_top_k_is_honored_under_various_limits(tmp_path, top_k):
    pages_text = {i: f"VCC content page {i}" for i in range(1, 6)}
    pages = await route_pages(
        _question("VCC"),
        _plan(),
        pages=list(range(1, 6)),
        top_k=top_k,
        pages_text=pages_text,
        text_index_cache_dir=tmp_path,
    )
    assert len(pages.candidates) == min(top_k, 5)
