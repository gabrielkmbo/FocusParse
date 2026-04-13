"""PLAN stage — classify question family, set budget, choose routing policy.

TODO(Phase 2): one cheap-tier LLM call with Pydantic structured output.
Output: PlanEvent with `question_family ∈ parser_bench QuestionFamily enums`.
"""

from __future__ import annotations

from focusparse.pipeline.events import PlanEvent, QuestionEvent


async def plan_question(event: QuestionEvent) -> PlanEvent:
    raise NotImplementedError("plan_question — wire in Phase 2")
