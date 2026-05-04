"""Tests for the LLM-driven inspector dispatch (Phase 6 #1).

Mock-driven; no real LLM, no real PDF. The dispatch itself goes through
`_inspect_one_region` which we mock to return synthetic packets so the
inspector LLM logic stays in focus.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from focusparse.evidence.packet import EvidencePacket, PacketProvenance
from focusparse.models.base import ModelResponse
from focusparse.pipeline.events import (
    PlanEvent,
    QuestionEvent,
    RegionCandidate,
    RegionsEvent,
)
from focusparse.pipeline.inspector_react import (
    _build_user_prompt,
    _deterministic_topn,
    _InspectorPlan,
    _parse_plan,
    _PlanItem,
    react_inspect,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _candidates() -> list[RegionCandidate]:
    return [
        RegionCandidate(
            region_id="r0",
            page=3,
            bbox_norm=(0.10, 0.20, 0.50, 0.60),
            region_type="picture",
            score=0.91,
            supporting_signals=["figure_class:bar_chart"],
        ),
        RegionCandidate(
            region_id="r1",
            page=3,
            bbox_norm=(0.05, 0.10, 0.95, 0.15),
            region_type="text",
            score=0.95,
        ),
        RegionCandidate(
            region_id="r2",
            page=4,
            bbox_norm=(0.30, 0.40, 0.70, 0.80),
            region_type="table",
            score=0.85,
        ),
    ]


def _question() -> QuestionEvent:
    return QuestionEvent(
        example_id="ex1",
        question="What does the bar chart show?",
        doc_id="doc1",
        pages_available=10,
    )


def _plan(*, max_crops: int = 8, evidence_types: list[str] | None = None) -> PlanEvent:
    return PlanEvent(
        question_family="single_value_lookup",
        evidence_types=evidence_types or ["figure"],
        budget_class="easy_local",
        routing_policy="text_first",
        max_tool_calls=8,
        max_crops=max_crops,
        max_vlm_calls=4,
    )


class _ScriptedClient:
    def __init__(self, scripted_text: str) -> None:
        self._text = scripted_text
        self.calls: list[dict[str, Any]] = []

    async def predict(
        self,
        prompt: str,
        images: list[Path] | None = None,
        system: str | None = None,
        max_tokens: int | None = None,
    ) -> ModelResponse:
        self.calls.append({"prompt": prompt, "system": system})
        return ModelResponse(text=self._text, tokens_in=80, tokens_out=20, usd=0.005, latency_ms=80)

    def count_tokens(self, text: str) -> int:
        return max(1, len(text) // 4)


def _stub_packet(idx: int, region: RegionCandidate) -> EvidencePacket:
    return EvidencePacket(
        packet_id=f"pkt_{idx:03d}",
        page=region.page,
        bbox_norm=region.bbox_norm,
        region_type=region.region_type,
        page_thumbnail_ref="",
        local_crop_ref=f"/cache/crops/pkt_{idx:03d}.png",
        provenance=PacketProvenance(tool="stub_inspector", args_hash=""),
    )


@pytest.fixture
def patch_inspect_one_region():
    """Patch _inspect_one_region to return synthetic packets so we test the
    dispatch logic, not the real PyMuPDF/Tesseract path."""

    async def _fake(idx, region, **kwargs):
        return _stub_packet(idx, region)

    with patch(
        "focusparse.pipeline.inspector_react._inspect_one_region",
        side_effect=_fake,
    ) as p:
        yield p


# ---------------------------------------------------------------------------
# Plan parsing
# ---------------------------------------------------------------------------


def test_parse_plan_handles_fenced_json():
    text = '```json\n{"thought": "x", "plan": [{"region_idx": 0, "mode": "image"}]}\n```'
    items = _parse_plan(text, n_candidates=3)
    assert items == [_PlanItem(region_idx=0, mode="image")]


def test_parse_plan_handles_bare_json():
    text = '{"thought": "x", "plan": [{"region_idx": 1, "mode": "element"}]}'
    items = _parse_plan(text, n_candidates=3)
    assert items[0].region_idx == 1


def test_parse_plan_drops_out_of_range_indices():
    text = '{"plan": [{"region_idx": 99, "mode": "image"}, {"region_idx": 0, "mode": "image"}]}'
    items = _parse_plan(text, n_candidates=3)
    assert [i.region_idx for i in items] == [0]


def test_parse_plan_returns_empty_on_garbage():
    assert _parse_plan("not json at all", n_candidates=3) == []
    assert _parse_plan("", n_candidates=3) == []
    assert _parse_plan('"just a string"', n_candidates=3) == []


def test_parse_plan_returns_empty_on_missing_plan_key():
    assert _parse_plan('{"thought": "x"}', n_candidates=3) == []


def test_inspector_plan_default_mode_is_element():
    obj = _InspectorPlan.model_validate({"plan": [{"region_idx": 0}]})
    assert obj.plan[0].mode == "element"


# ---------------------------------------------------------------------------
# Prompt rendering
# ---------------------------------------------------------------------------


def test_user_prompt_lists_all_candidates_with_indices():
    p = _build_user_prompt(_question(), _plan(), _candidates(), max_crops=8)
    for idx in range(3):
        assert f"[{idx}]" in p
    assert "What does the bar chart show?" in p
    assert "type=picture" in p
    assert "type=text" in p
    assert "type=table" in p


def test_user_prompt_surfaces_figure_class():
    p = _build_user_prompt(_question(), _plan(), _candidates(), max_crops=8)
    assert "figure_class:bar_chart" in p


def test_user_prompt_includes_max_crops_budget():
    p = _build_user_prompt(_question(), _plan(max_crops=4), _candidates(), max_crops=4)
    assert "(budget): 4" in p


def test_user_prompt_includes_planner_evidence_types():
    p = _build_user_prompt(
        _question(),
        _plan(evidence_types=["figure", "caption"]),
        _candidates(),
        max_crops=8,
    )
    assert "figure" in p
    assert "caption" in p


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


async def test_react_inspect_dispatches_llm_picked_regions(patch_inspect_one_region):
    """LLM picks regions 0 and 2; harness dispatches both, in order."""
    client = _ScriptedClient(
        json.dumps(
            {
                "thought": "Bar chart needs both image + table.",
                "plan": [
                    {"region_idx": 0, "mode": "region"},
                    {"region_idx": 2, "mode": "element"},
                ],
            }
        )
    )
    result = await react_inspect(
        _question(),
        _plan(),
        RegionsEvent(candidates=_candidates()),
        backend_client=client,
        images_by_page={3: Path("/tmp/p3.png"), 4: Path("/tmp/p4.png")},
    )
    assert len(result.evidence.packets) == 2
    assert not result.fallback_used
    assert result.plan_size == 2
    # Dispatch happened in plan order — region 0 first, then region 2.
    dispatched_pages = [p.page for p in result.evidence.packets]
    assert dispatched_pages == [3, 4]
    # System prompt was the inspector's, not the comparator ReAct prompt.
    assert "INSPECT stage" in client.calls[0]["system"]


async def test_react_inspect_falls_back_when_no_backend_client(patch_inspect_one_region):
    result = await react_inspect(
        _question(),
        _plan(max_crops=2),
        RegionsEvent(candidates=_candidates()),
        backend_client=None,
        images_by_page={},
    )
    assert result.fallback_used
    # Top-N by score: idx 1 (text, 0.95) > idx 0 (picture, 0.91) > idx 2 (table, 0.85).
    assert [p.page for p in result.evidence.packets] == [3, 3]
    assert len(result.evidence.packets) == 2


async def test_react_inspect_falls_back_on_malformed_llm_response(patch_inspect_one_region):
    client = _ScriptedClient("not even close to JSON")
    result = await react_inspect(
        _question(),
        _plan(max_crops=2),
        RegionsEvent(candidates=_candidates()),
        backend_client=client,
        images_by_page={},
    )
    assert result.fallback_used
    assert len(result.evidence.packets) == 2  # top-N by score


async def test_react_inspect_falls_back_on_empty_plan(patch_inspect_one_region):
    client = _ScriptedClient(json.dumps({"thought": "no idea", "plan": []}))
    result = await react_inspect(
        _question(),
        _plan(max_crops=3),
        RegionsEvent(candidates=_candidates()),
        backend_client=client,
        images_by_page={},
    )
    assert result.fallback_used


async def test_react_inspect_caps_plan_to_max_crops(patch_inspect_one_region):
    """If the LLM picks more regions than budget, harness truncates."""
    client = _ScriptedClient(
        json.dumps(
            {
                "plan": [
                    {"region_idx": 0, "mode": "image"},
                    {"region_idx": 1, "mode": "image"},
                    {"region_idx": 2, "mode": "image"},
                ]
            }
        )
    )
    result = await react_inspect(
        _question(),
        _plan(max_crops=2),
        RegionsEvent(candidates=_candidates()),
        backend_client=client,
        images_by_page={},
    )
    assert len(result.evidence.packets) == 2


async def test_react_inspect_handles_empty_candidates(patch_inspect_one_region):
    """No candidates → no LLM call, empty evidence, fallback flagged."""
    client = _ScriptedClient("{}")
    result = await react_inspect(
        _question(),
        _plan(),
        RegionsEvent(candidates=[]),
        backend_client=client,
        images_by_page={},
    )
    assert result.evidence.packets == []
    assert result.fallback_used
    # No LLM call made — empty candidates short-circuits.
    assert client.calls == []


async def test_react_inspect_handles_llm_exception(patch_inspect_one_region):
    """LLM raises → fall back to deterministic, no crash."""

    class _ErrorClient:
        async def predict(self, **kwargs):
            raise RuntimeError("model timeout")

        def count_tokens(self, text):
            return 1

    result = await react_inspect(
        _question(),
        _plan(max_crops=2),
        RegionsEvent(candidates=_candidates()),
        backend_client=_ErrorClient(),
        images_by_page={},
    )
    assert result.fallback_used
    assert len(result.evidence.packets) == 2


# ---------------------------------------------------------------------------
# Deterministic fallback parity
# ---------------------------------------------------------------------------


def test_deterministic_topn_orders_by_score():
    items = _deterministic_topn(_candidates(), max_crops=3)
    # Score order: idx 1 (0.95) > idx 0 (0.91) > idx 2 (0.85)
    assert [it.region_idx for it in items] == [1, 0, 2]


def test_deterministic_topn_caps_to_budget():
    items = _deterministic_topn(_candidates(), max_crops=1)
    assert len(items) == 1
    assert items[0].region_idx == 1  # highest-score
