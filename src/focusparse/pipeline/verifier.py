"""VERIFY stage — mid-tier support check + escalation policy.

Phase 2 skeleton: deterministic always-accept verdict. The real support check
+ escalation policy lands in sub-phase 2f.

Phase 2f output: `VerdictEvent.next_action ∈ {
  accept, retry_localization, expand_context, abstain, escalate_reasoner
}`. Failure policy (plan §11):
  - right answer, wrong citation → retry_localization
  - right page, wrong crop      → retry_localization
  - evidence incomplete          → expand_context
  - conflicting evidence         → abstain or escalate
  - unsupported but confident    → reject
"""

from __future__ import annotations

from focusparse.pipeline.events import (
    AnswerEvent,
    EvidenceEvent,
    QuestionEvent,
    VerdictEvent,
)


async def verify_answer(
    question: QuestionEvent,
    evidence: EvidenceEvent,
    answer: AnswerEvent,
) -> VerdictEvent:
    """Skeleton: always accept, propagating the reasoner's confidence."""
    del question, evidence  # unused in skeleton
    return VerdictEvent(
        supported=True,
        reason="skeleton_always_accept",
        next_action="accept",
        confidence=answer.confidence,
    )
