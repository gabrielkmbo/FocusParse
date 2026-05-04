"""Agent baseline — a generic agentic loop comparator.

Sister of `react_agent.py`. Same think→act→observe loop, the same tool
dispatch, the same parsing and trajectory recording — but with a
deliberately *generic* system prompt (no domain hints, no answer-format
guidance, no FocusParse-specific framing) and a tighter iteration
budget. Fills the third row of the headline table:

    | Method                  | …
    | Base VLM                | (no tools)
    | ReAct +2 / +4 tools     | (careful agent prompt)
    | Agent baseline +2/+4    | <THIS — generic agent prompt>
    | Our harness +2 / +4     | (FocusParse stage machine)

The two comparator rows (`react` and `agent_baseline`) deliberately
differ in prompt-effort budget so the table can attribute lift to
either *the agent loop existing at all* (ReAct vs Base) or *prompt
quality and looping discipline* (Agent baseline vs ReAct). Per the
2026-04-29 plan, comparator polish does not move FocusParse's cells —
this file is intentionally thin (a system-prompt override + tighter
iteration budget; everything else inherited).
"""

from __future__ import annotations

import logging

from focusparse.models.base import ModelClient
from focusparse.pipeline.react_agent import ReActAgent
from focusparse.tools import ToolSpec, format_agent_tool_block

logger = logging.getLogger(__name__)

_DEFAULT_MAX_ITERATIONS = 4  # tighter than ReAct's 6 — generic agents stop earlier

_AGENT_BASELINE_SYSTEM_PROMPT = (
    "You are an AI assistant answering questions about a document. "
    "You have access to tools listed below; use them or answer directly. "
    'When you have an answer, output JSON: {"final_answer": "..."}. '
    'You may call a tool with: {"action": "<tool_name>", "action_input": {...}}.'
)


class AgentBaselineAgent(ReActAgent):
    """Generic agentic-loop comparator — thinner ReAct.

    Inherits `run()`, dispatch, parsing, and trace recording from
    `ReActAgent` (those are framework-agnostic). Only `_system_prompt`
    is overridden, so the two comparator rows differ in:
      * system prompting (generic vs domain-aware)
      * iteration budget (4 vs 6)

    Everything else — same model, same tools, same protocol, same
    parser, same trajectory schema — to keep the comparator clean.
    If FocusParse's harness beats this row by ≥ 5pp at non-overlapping
    CIs, the lift is attributable to *the harness architecture*, not
    just "having an agent loop with tools".
    """

    def __init__(
        self,
        *,
        backend_client: ModelClient,
        tools: list[ToolSpec],
        max_iterations: int = _DEFAULT_MAX_ITERATIONS,
    ) -> None:
        super().__init__(
            backend_client=backend_client,
            tools=tools,
            max_iterations=max_iterations,
        )

    def _system_prompt(self) -> str:
        # AgentBaseline keeps the generic, terser tool block per the active
        # plan's "comparator differences" note — the prompt-effort axis
        # between ReAct and AgentBaseline is the variable that lets us
        # attribute lift to ReAct's careful prompting vs the loop-existing
        # baseline. format_agent_tool_block(mode='generic') gives a
        # name+desc+field-names rendering, no examples or chaining notes.
        return (
            _AGENT_BASELINE_SYSTEM_PROMPT
            + "\n\n"
            + format_agent_tool_block(self.tools, mode="generic")
        )
