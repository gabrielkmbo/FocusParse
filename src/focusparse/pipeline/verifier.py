"""VERIFY stage — mid-tier support check + escalation policy.

Phase 2 output: VerdictEvent.next_action ∈ {
  accept, retry_localization, expand_context, abstain, escalate_reasoner
}. Failure policy (plan §11):
  - right answer, wrong citation → retry_localization
  - right page, wrong crop      → retry_localization
  - evidence incomplete          → expand_context
  - conflicting evidence         → abstain or escalate
  - unsupported but confident    → reject
"""

from __future__ import annotations

from focusparse.pipeline.events import AnswerEvent, EvidenceEvent, QuestionEvent, VerdictEvent


async def verify_answer(
    question: QuestionEvent,
    evidence: EvidenceEvent,
    answer: AnswerEvent,
) -> VerdictEvent:
    raise NotImplementedError("verify_answer — wire in Phase 2")
