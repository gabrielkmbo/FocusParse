"""INSPECT stage — ReActAgent loop over the tool belt.

Phase 3 strategy:
  - Wrap tools/*.py as FunctionTool instances.
  - Use llama_index.core.agent.workflow.ReActAgent.
  - Bind TokenCountingHandler with a token budget (raises BudgetExceeded).
  - Record each tool call as a TrajectoryStep.

The inspector decides when to stop based on:
  - Budget exhausted (max_tool_calls, max_crops, token budget).
  - Answer confidence > threshold.
  - Explicit abstain signal from the verifier loop.
"""

from __future__ import annotations

from focusparse.evidence.packet import EvidencePacket
from focusparse.pipeline.events import EvidenceEvent, PlanEvent, QuestionEvent, RegionsEvent


async def inspect_regions(
    question: QuestionEvent,
    plan: PlanEvent,
    regions: RegionsEvent,
) -> EvidenceEvent:
    raise NotImplementedError("inspect_regions — wire in Phase 3")
