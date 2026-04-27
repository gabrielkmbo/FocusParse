"""Tests for `focusparse.pipeline.region_reranker.rerank_regions` (Phase 2 item 4).

Covers:
  * skip path: backend_client=None → regions returned unchanged + None response
  * skip path: empty regions list → returned unchanged
  * happy path: LLM scores all regions; sort order = relevance × det.score desc
  * partial-score: LLM scores some regions, others keep original ranking and
    have relevance=None
  * relevance × score blend: low-detector + high-relevance can beat
    high-detector + low-relevance
  * `needed_for` taxonomy: only known roles flow through; unknown → ignored
  * `missing_context` extends `expansion_hints` (doesn't replace)
  * malformed LLM response → regions unchanged (defensive parse)
  * hallucinated region_id → silently dropped (no crash)
  * out-of-range relevance → ignored (≤0, >1, etc.)
  * non-list `regions` field → fall through to no-op
  * fenced JSON (```json ... ```) parses correctly
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from focusparse.models.base import ModelResponse
from focusparse.pipeline.events import (
    PlanEvent,
    QuestionEvent,
    RegionCandidate,
    RegionsEvent,
)
from focusparse.pipeline.region_reranker import rerank_regions

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _question() -> QuestionEvent:
    return QuestionEvent(
        example_id="ex-1",
        question="What is the maximum value shown on the y-axis of the chart?",
        doc_id="doc-rerank",
        pages_available=10,
        domain="finance",
    )


def _plan(family: str = "axis_value_interpolation") -> PlanEvent:
    return PlanEvent(
        question_family=family,
        evidence_types=["chart", "axis"],
        budget_class="easy_local",
        routing_policy="layout_first",
        max_tool_calls=12,
        max_crops=8,
        max_vlm_calls=4,
    )


def _region(
    region_id: str,
    *,
    page: int = 1,
    bbox: tuple[float, float, float, float] = (0.0, 0.0, 0.5, 0.5),
    region_type: str = "text",
    score: float = 0.5,
    expansion_hints: list[str] | None = None,
) -> RegionCandidate:
    return RegionCandidate(
        region_id=region_id,
        page=page,
        bbox_norm=bbox,
        region_type=region_type,
        score=score,
        expansion_hints=expansion_hints or [],
    )


class _FakeClient:
    """ModelClient stub returning a fixed JSON string."""

    def __init__(self, response_text: str, tokens_in: int = 200, tokens_out: int = 80) -> None:
        self._text = response_text
        self._tokens_in = tokens_in
        self._tokens_out = tokens_out
        self.calls: list[dict[str, Any]] = []

    async def predict(
        self,
        prompt: str,
        images: list[Path] | None = None,
        system: str | None = None,
        max_tokens: int | None = None,
    ) -> ModelResponse:
        self.calls.append({"prompt": prompt, "system": system, "n_images": len(images or [])})
        return ModelResponse(
            text=self._text,
            tokens_in=self._tokens_in,
            tokens_out=self._tokens_out,
            usd=0.0009,
            latency_ms=400,
        )

    def count_tokens(self, text: str) -> int:
        return max(1, len(text) // 4)


# ---------------------------------------------------------------------------
# Skip paths
# ---------------------------------------------------------------------------


async def test_skip_when_no_backend_client():
    """No tier_router wired → regions pass through unchanged + None response."""
    regions = RegionsEvent(
        candidates=[
            _region("r0", region_type="picture", score=0.7),
            _region("r1", region_type="text", score=0.9),
        ]
    )
    out, response = await rerank_regions(_question(), _plan(), regions, backend_client=None)
    assert out is regions  # same object — passthrough
    assert response is None


async def test_skip_when_empty_regions():
    """No regions → return as-is + None (don't waste an LLM call)."""
    regions = RegionsEvent(candidates=[])
    client = _FakeClient('{"regions": []}')
    out, response = await rerank_regions(_question(), _plan(), regions, backend_client=client)
    assert out is regions
    assert response is None
    # LLM was never called.
    assert client.calls == []


# ---------------------------------------------------------------------------
# Happy path: LLM scores every region
# ---------------------------------------------------------------------------


async def test_full_rerank_sorts_by_relevance_times_score():
    """LLM scores all regions; output ordered by relevance × score desc."""
    regions = RegionsEvent(
        candidates=[
            _region("text_block", region_type="text", score=0.95),
            _region("plot_area", region_type="picture", score=0.6),
            _region("legend_box", region_type="picture", score=0.4),
        ]
    )
    client = _FakeClient(
        '{"regions": ['
        '{"region_id": "text_block", "relevance": 0.1, "needed_for": "primary"},'
        '{"region_id": "plot_area", "relevance": 0.95, "needed_for": "primary", '
        '"missing_context": ["legend", "y_axis"]},'
        '{"region_id": "legend_box", "relevance": 0.85, "needed_for": "legend_binding"}'
        "]}"
    )
    out, response = await rerank_regions(_question(), _plan(), regions, backend_client=client)

    # plot_area: 0.95 × 0.6  = 0.570
    # legend_box: 0.85 × 0.4 = 0.340
    # text_block: 0.10 × 0.95 = 0.095
    assert [r.region_id for r in out.candidates] == ["plot_area", "legend_box", "text_block"]

    plot = out.candidates[0]
    assert plot.relevance == 0.95
    assert plot.needed_for == "primary"
    assert "legend" in plot.expansion_hints
    assert "y_axis" in plot.expansion_hints
    # LLM was called once with the prompt + system message.
    assert response is not None
    assert response.tokens_in == 200


async def test_partial_rerank_keeps_original_ranking_for_unscored():
    """LLM scores 2 of 3 regions; the third keeps its original record + relevance=None."""
    regions = RegionsEvent(
        candidates=[
            _region("scored_a", score=0.7),
            _region("scored_b", score=0.5),
            _region("untouched", region_type="page-footer", score=0.85),
        ]
    )
    client = _FakeClient(
        '{"regions": ['
        '{"region_id": "scored_a", "relevance": 0.9, "needed_for": "primary"},'
        '{"region_id": "scored_b", "relevance": 0.8, "needed_for": "axis_reading"}'
        "]}"
    )
    out, _ = await rerank_regions(_question(), _plan(), regions, backend_client=client)

    by_id = {r.region_id: r for r in out.candidates}
    assert by_id["scored_a"].relevance == 0.9
    assert by_id["scored_b"].relevance == 0.8
    assert by_id["untouched"].relevance is None
    assert by_id["untouched"].needed_for is None
    # Sort key for untouched falls back to its raw score (0.85).
    # scored_a combined: 0.9 × 0.7 = 0.63
    # scored_b combined: 0.8 × 0.5 = 0.40
    # untouched: 0.85 (raw fallback) → ranks between scored_a and scored_b
    assert [r.region_id for r in out.candidates] == ["untouched", "scored_a", "scored_b"]


async def test_relevance_can_promote_low_detector_score():
    """A small confident-but-irrelevant region should NOT win over a less-
    confident-but-very-relevant region."""
    regions = RegionsEvent(
        candidates=[
            _region("page_footer", region_type="page-footer", score=0.95),
            _region("small_legend", region_type="picture", score=0.45),
        ]
    )
    client = _FakeClient(
        '{"regions": ['
        '{"region_id": "page_footer", "relevance": 0.05, "needed_for": "primary"},'
        '{"region_id": "small_legend", "relevance": 0.95, "needed_for": "legend_binding"}'
        "]}"
    )
    out, _ = await rerank_regions(_question(), _plan(), regions, backend_client=client)
    # page_footer: 0.05 × 0.95 = 0.0475
    # small_legend: 0.95 × 0.45 = 0.4275
    assert out.candidates[0].region_id == "small_legend"


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------


async def test_unknown_needed_for_value_is_dropped():
    """`needed_for` outside the taxonomy → field stays None, region still
    gets relevance + ranking."""
    regions = RegionsEvent(candidates=[_region("r", score=0.5)])
    client = _FakeClient(
        '{"regions": [{"region_id": "r", "relevance": 0.9, "needed_for": "totally_made_up"}]}'
    )
    out, _ = await rerank_regions(_question(), _plan(), regions, backend_client=client)
    r = out.candidates[0]
    assert r.relevance == 0.9
    assert r.needed_for is None  # invalid value silently dropped


async def test_unknown_missing_context_entries_are_dropped():
    """Only entries in `_VALID_MISSING_CONTEXT` survive."""
    regions = RegionsEvent(candidates=[_region("r", score=0.5)])
    client = _FakeClient(
        '{"regions": [{"region_id": "r", "relevance": 0.9, '
        '"missing_context": ["legend", "qux", "x_axis", "asdf"]}]}'
    )
    out, _ = await rerank_regions(_question(), _plan(), regions, backend_client=client)
    r = out.candidates[0]
    assert "legend" in r.expansion_hints
    assert "x_axis" in r.expansion_hints
    assert "qux" not in r.expansion_hints
    assert "asdf" not in r.expansion_hints


async def test_missing_context_extends_existing_expansion_hints():
    """Pre-existing expansion_hints are preserved; LLM hints are appended."""
    regions = RegionsEvent(candidates=[_region("r", score=0.5, expansion_hints=["caption"])])
    client = _FakeClient(
        '{"regions": [{"region_id": "r", "relevance": 0.9, '
        '"missing_context": ["legend", "caption", "y_axis"]}]}'
    )
    out, _ = await rerank_regions(_question(), _plan(), regions, backend_client=client)
    r = out.candidates[0]
    assert r.expansion_hints == ["caption", "legend", "y_axis"]  # caption not duplicated


async def test_out_of_range_relevance_is_ignored():
    """Negative or > 1 relevance values fall through; region keeps relevance=None."""
    regions = RegionsEvent(candidates=[_region("r", score=0.5)])
    client = _FakeClient(
        '{"regions": [{"region_id": "r", "relevance": 1.5, "needed_for": "primary"}]}'
    )
    out, _ = await rerank_regions(_question(), _plan(), regions, backend_client=client)
    r = out.candidates[0]
    assert r.relevance is None
    # `needed_for` is recorded since it's in the valid set, even though
    # `relevance` was rejected — they're independent fields.
    assert r.needed_for == "primary"


# ---------------------------------------------------------------------------
# Defensive parsing
# ---------------------------------------------------------------------------


async def test_fenced_json_response_parses():
    """LLMs sometimes wrap JSON in markdown fences."""
    regions = RegionsEvent(candidates=[_region("r", score=0.5)])
    client = _FakeClient(
        '```json\n{"regions": [{"region_id": "r", "relevance": 0.7, "needed_for": "primary"}]}\n```'
    )
    out, _ = await rerank_regions(_question(), _plan(), regions, backend_client=client)
    assert out.candidates[0].relevance == 0.7


async def test_malformed_json_returns_unchanged_regions():
    """Bad JSON → caller gets the original RegionsEvent + the raw response."""
    regions = RegionsEvent(candidates=[_region("a", score=0.6), _region("b", score=0.4)])
    client = _FakeClient("this is not json at all")
    out, response = await rerank_regions(_question(), _plan(), regions, backend_client=client)
    # Original ordering preserved (no relevance fields applied).
    assert [r.region_id for r in out.candidates] == ["a", "b"]
    assert all(r.relevance is None for r in out.candidates)
    # Response surfaced for cost attribution even though parse failed.
    assert response is not None


async def test_hallucinated_region_id_is_dropped():
    """LLM scores a region_id that wasn't in the input → silently dropped."""
    regions = RegionsEvent(candidates=[_region("real", score=0.5)])
    client = _FakeClient(
        '{"regions": ['
        '{"region_id": "real", "relevance": 0.9, "needed_for": "primary"},'
        '{"region_id": "imaginary", "relevance": 0.99, "needed_for": "primary"}'
        "]}"
    )
    out, _ = await rerank_regions(_question(), _plan(), regions, backend_client=client)
    assert [r.region_id for r in out.candidates] == ["real"]
    assert out.candidates[0].relevance == 0.9


async def test_non_list_regions_field_is_no_op():
    """Top-level JSON object is shaped wrong → regions unchanged."""
    regions = RegionsEvent(candidates=[_region("r", score=0.5)])
    client = _FakeClient('{"regions": "not a list"}')
    out, _ = await rerank_regions(_question(), _plan(), regions, backend_client=client)
    assert out.candidates[0].relevance is None


async def test_entry_with_no_useful_fields_is_skipped():
    """An entry that only has `region_id` (no relevance / needed_for /
    missing_context) is skipped; the region keeps relevance=None."""
    regions = RegionsEvent(candidates=[_region("r", score=0.5)])
    client = _FakeClient('{"regions": [{"region_id": "r"}]}')
    out, _ = await rerank_regions(_question(), _plan(), regions, backend_client=client)
    r = out.candidates[0]
    assert r.relevance is None
    assert r.needed_for is None
