"""ANSWER stage — frontier-tier reasoner sees ONLY EvidencePackets.

Never the full document. Uses CitationQueryEngine-style 'Source N:' markers so
the model emits citations the verifier can check.

Phase 2 strategy:
  - Sample K=2 candidate answers with different packet orderings.
  - Emit AnswerEvent with citations = list of packet_id refs.
  - Confidence = self-consistency across samples.
"""

from __future__ import annotations

from focusparse.pipeline.events import AnswerEvent, EvidenceEvent, QuestionEvent


async def answer_from_evidence(
    question: QuestionEvent,
    evidence: EvidenceEvent,
) -> AnswerEvent:
    raise NotImplementedError("answer_from_evidence — wire in Phase 2")
