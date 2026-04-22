"""PLAN stage — classify question family, set budget, choose routing policy.

Phase 2 skeleton: deterministic placeholder that emits a neutral plan. A real
cheap-tier LLM call with structured output lands in sub-phase 2c.

Output: `PlanEvent` with `question_family ∈ parser_bench QuestionFamily` enums.
"""

from __future__ import annotations

from focusparse.pipeline.events import PlanEvent, QuestionEvent
from focusparse.utils.config import BudgetSpec


async def plan_question(
    event: QuestionEvent,
    *,
    budget: BudgetSpec | None = None,
) -> PlanEvent:
    """Deterministic placeholder — neutral plan with budget from config.

    No LLM call. Sub-phase 2c replaces this with a cheap-tier structured-output
    call that fills in `question_family` from the question text.
    """
    budget = budget or BudgetSpec()
    return PlanEvent(
        question_family="unknown",
        evidence_types=["text", "image"],
        budget_class="easy_local",
        routing_policy="hybrid",
        max_tool_calls=budget.tool_calls,
        max_crops=budget.crops,
        max_vlm_calls=budget.max_vlm_calls,
    )
