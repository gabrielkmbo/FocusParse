"""Tests for `focusparse.pipeline.planner.plan_question`.

Covers:
  * deterministic fallback when no `backend_client` is provided
  * LLM path with a well-formed JSON reply (all fields flow through)
  * LLM path with a fenced JSON reply
  * LLM path with malformed / non-JSON reply (graceful fallback)
  * invalid `question_family` is rejected per-domain
  * unknown `evidence_types` entries are dropped
  * token/usd telemetry comes back on the ModelResponse

No parser-bench submodule required — `QuestionEvent` is pydantic-only.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from focusparse.models.base import ModelResponse
from focusparse.pipeline.events import QuestionEvent
from focusparse.pipeline.planner import plan_question
from focusparse.utils.config import BudgetSpec


class _FakePlannerClient:
    def __init__(self, text: str, *, tokens_in: int = 80, tokens_out: int = 18) -> None:
        self._text = text
        self._tokens_in = tokens_in
        self._tokens_out = tokens_out
        self.calls: list[dict] = []

    async def predict(
        self,
        prompt: str,
        images: list[Path] | None = None,
        system: str | None = None,
        max_tokens: int | None = None,
    ) -> ModelResponse:
        self.calls.append({"prompt": prompt, "system": system})
        return ModelResponse(
            text=self._text,
            tokens_in=self._tokens_in,
            tokens_out=self._tokens_out,
            usd=0.0001,
            latency_ms=40,
        )

    def count_tokens(self, text: str) -> int:
        return max(1, len(text) // 4)


def _question(example_id: str = "ex-1", domain: str | None = None) -> QuestionEvent:
    return QuestionEvent(
        example_id=example_id,
        question="What is the max supply voltage on the MCU?",
        doc_id="datasheet-A",
        pages_available=10,
        domain=domain,
    )


# ---------------------------------------------------------------------------
# Deterministic fallback
# ---------------------------------------------------------------------------


async def test_plan_no_client_returns_deterministic_fallback():
    plan, response = await plan_question(_question())
    assert response is None
    assert plan.question_family == "unknown"
    assert plan.evidence_types == ["text", "image"]
    assert plan.budget_class == "easy_local"
    assert plan.routing_policy == "hybrid"
    # Budget defaults flow from BudgetSpec.
    assert plan.max_tool_calls == BudgetSpec().tool_calls


async def test_plan_no_client_respects_custom_budget():
    budget = BudgetSpec(tool_calls=3, crops=2, max_vlm_calls=1)
    plan, response = await plan_question(_question(), budget=budget)
    assert response is None
    assert plan.max_tool_calls == 3
    assert plan.max_crops == 2
    assert plan.max_vlm_calls == 1


# ---------------------------------------------------------------------------
# LLM path — happy case
# ---------------------------------------------------------------------------


async def test_plan_llm_happy_path_fills_all_fields():
    client = _FakePlannerClient(
        '{"question_family": "min_typ_max_disambiguation", '
        '"evidence_types": ["table", "footnote"], '
        '"budget_class": "easy_local", '
        '"routing_policy": "text_first"}'
    )
    plan, response = await plan_question(
        _question(domain="datasheet"),
        backend_client=client,
    )
    assert response is not None
    assert response.tokens_in == 80
    assert response.tokens_out == 18
    assert plan.question_family == "min_typ_max_disambiguation"
    assert plan.evidence_types == ["table", "footnote"]
    assert plan.budget_class == "easy_local"
    assert plan.routing_policy == "text_first"
    assert len(client.calls) == 1


async def test_plan_llm_accepts_fenced_json():
    client = _FakePlannerClient(
        "Here is the classification:\n"
        "```json\n"
        '{"question_family": "curve_axis_reading", '
        '"evidence_types": ["chart", "axis_label"], '
        '"budget_class": "highres_tiny", '
        '"routing_policy": "layout_first"}\n'
        "```"
    )
    plan, _ = await plan_question(_question(domain="datasheet"), backend_client=client)
    assert plan.question_family == "curve_axis_reading"
    assert plan.evidence_types == ["chart", "axis_label"]
    assert plan.budget_class == "highres_tiny"
    assert plan.routing_policy == "layout_first"


async def test_plan_llm_reads_domain_from_event_when_kwarg_absent():
    client = _FakePlannerClient(
        '{"question_family": "axis_value_interpolation", '
        '"evidence_types": ["chart"], '
        '"budget_class": "easy_local", '
        '"routing_policy": "image_first"}'
    )
    # Pass domain via the QuestionEvent, not the kwarg — planner should still
    # narrow the family set to finance.
    plan, _ = await plan_question(
        _question(domain="finance"),
        backend_client=client,
    )
    assert plan.question_family == "axis_value_interpolation"


# ---------------------------------------------------------------------------
# LLM path — defensive fallback
# ---------------------------------------------------------------------------


async def test_plan_llm_non_json_falls_back_but_still_returns_response():
    client = _FakePlannerClient("I think this is a table question.")
    plan, response = await plan_question(_question(), backend_client=client)
    assert response is not None  # we still attribute tokens/cost
    # All fields fell back.
    assert plan.question_family == "unknown"
    assert plan.evidence_types == ["text", "image"]


async def test_plan_llm_rejects_family_outside_domain():
    # min_typ_max_disambiguation is datasheet-only; asking with domain=finance
    # must reject it and fall back.
    client = _FakePlannerClient(
        '{"question_family": "min_typ_max_disambiguation", '
        '"evidence_types": ["chart"], '
        '"budget_class": "easy_local", '
        '"routing_policy": "hybrid"}'
    )
    plan, _ = await plan_question(_question(domain="finance"), backend_client=client)
    assert plan.question_family == "unknown"  # rejected, fell back
    assert plan.evidence_types == ["chart"]  # evidence_types survived


async def test_plan_llm_drops_unknown_evidence_types():
    client = _FakePlannerClient(
        '{"question_family": "min_typ_max_disambiguation", '
        '"evidence_types": ["table", "unicorn_region", "footnote"], '
        '"budget_class": "easy_local", '
        '"routing_policy": "hybrid"}'
    )
    plan, _ = await plan_question(_question(domain="datasheet"), backend_client=client)
    assert plan.evidence_types == ["table", "footnote"]


async def test_plan_llm_rejects_invalid_budget_class():
    client = _FakePlannerClient(
        '{"question_family": "min_typ_max_disambiguation", '
        '"evidence_types": ["table"], '
        '"budget_class": "impossible_class", '
        '"routing_policy": "hybrid"}'
    )
    plan, _ = await plan_question(_question(domain="datasheet"), backend_client=client)
    assert plan.budget_class == "easy_local"  # fallback


async def test_plan_llm_rejects_invalid_routing_policy():
    client = _FakePlannerClient(
        '{"question_family": "min_typ_max_disambiguation", '
        '"evidence_types": ["table"], '
        '"budget_class": "easy_local", '
        '"routing_policy": "random_walk"}'
    )
    plan, _ = await plan_question(_question(domain="datasheet"), backend_client=client)
    assert plan.routing_policy == "hybrid"  # fallback


async def test_plan_llm_unknown_domain_allows_union_of_families():
    # No domain → union of all families is acceptable; both finance- and
    # datasheet-specific families pass.
    client = _FakePlannerClient(
        '{"question_family": "axis_value_interpolation", '
        '"evidence_types": [], '
        '"budget_class": "easy_local", '
        '"routing_policy": "hybrid"}'
    )
    plan, _ = await plan_question(_question(domain=None), backend_client=client)
    assert plan.question_family == "axis_value_interpolation"


@pytest.mark.parametrize(
    "bad_payload",
    [
        "",  # empty
        "not json at all",  # no braces
        '{"question_family":}',  # broken JSON
        "[1, 2, 3]",  # array, not dict
    ],
)
async def test_plan_llm_robust_to_bad_payloads(bad_payload):
    client = _FakePlannerClient(bad_payload)
    plan, response = await plan_question(_question(), backend_client=client)
    assert response is not None
    assert plan.question_family == "unknown"
    assert plan.routing_policy == "hybrid"
    assert plan.budget_class == "easy_local"
