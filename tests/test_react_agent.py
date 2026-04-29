"""Tests for the ReAct loop comparator + AgentBaseline.

Both inherit dispatch + parsing from `ReActAgent`. The variable that
distinguishes them in the headline-table comparator is the system
prompt + iteration budget. We test:

  * loop terminates on `final_answer` JSON
  * loop dispatches a tool when LLM emits a tool-call JSON
  * unknown tool name is recorded as `tool_error` and loop continues
  * malformed JSON falls through to "treat as final answer"
  * images are passed only on iteration 0
  * AgentBaselineAgent uses the generic prompt
  * `resolve_tool_set("minimal")` and `("full")` return correct counts
  * `resolve_tool_set` rejects unknown names

These tests run no real LLM and no real PDF — pure mock-driven.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from focusparse.models.base import ModelResponse
from focusparse.pipeline.agent_baseline import AgentBaselineAgent
from focusparse.pipeline.react_agent import ReActAgent, _parse_react_turn
from focusparse.tools import (
    GET_TEXT_LAYER_SPEC,
    INSPECT_REGION_SPEC,
    LAYOUT_DETECT_SPEC,
    RUN_PYTHON_SPEC,
    ToolSpec,
    resolve_tool_set,
)

# ---------------------------------------------------------------------------
# resolve_tool_set
# ---------------------------------------------------------------------------


def test_resolve_tool_set_minimal_returns_two_tools():
    tools = resolve_tool_set("minimal")
    assert len(tools) == 2
    names = {t.name for t in tools}
    assert names == {INSPECT_REGION_SPEC.name, GET_TEXT_LAYER_SPEC.name}


def test_resolve_tool_set_full_returns_four_tools():
    tools = resolve_tool_set("full")
    assert len(tools) == 4
    names = {t.name for t in tools}
    assert names == {
        INSPECT_REGION_SPEC.name,
        GET_TEXT_LAYER_SPEC.name,
        LAYOUT_DETECT_SPEC.name,
        RUN_PYTHON_SPEC.name,
    }


def test_resolve_tool_set_rejects_unknown():
    with pytest.raises(ValueError, match="Unknown tool set"):
        resolve_tool_set("medium")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _ScriptedClient:
    """ModelClient that returns a fixed sequence of responses."""

    def __init__(self, scripted_texts: list[str]) -> None:
        self._scripted = list(scripted_texts)
        self.calls: list[dict[str, Any]] = []

    async def predict(
        self,
        prompt: str,
        images: list[Path] | None = None,
        system: str | None = None,
        max_tokens: int | None = None,
    ) -> ModelResponse:
        idx = len(self.calls)
        self.calls.append({"prompt": prompt, "images": images, "system": system})
        text = self._scripted[idx] if idx < len(self._scripted) else self._scripted[-1]
        return ModelResponse(
            text=text,
            tokens_in=120,
            tokens_out=20,
            usd=0.0015,
            latency_ms=70,
        )

    def count_tokens(self, text: str) -> int:
        return max(1, len(text) // 4)


def _example():
    from focusparse._parser_bench import (
        AnswerType,
        BBox,
        BenchmarkExample,
        DifficultyScores,
        Domain,
    )

    return BenchmarkExample(
        id="ex-react",
        domain=Domain.DATASHEET,
        source_pdf="fake.pdf",
        page_images=["fake_page_0001.png"],
        question="What is X?",
        answer="42",
        answer_type=AnswerType.NUMERIC,
        tolerance=0.5,
        supporting_pages=[1],
        supporting_bboxes=[BBox(page=1, x0=0, y0=0, x1=1, y1=1)],
        difficulty=DifficultyScores(visual=1, reasoning=1, localization=1),
        question_family="single_value_lookup",
    )


def _stub_tool_spec(name: str = "stub_tool"):
    """A tool with no real I/O — returns whatever was passed in."""

    from pydantic import BaseModel

    class _StubInput(BaseModel):
        echo: str = ""

    async def _runner(inp: _StubInput, **_kw: Any) -> dict[str, Any]:
        return {"echoed": inp.echo}

    return ToolSpec(
        name=name,
        description="stub tool for tests",
        input_model=_StubInput,
        runner=_runner,
        summarize=lambda out: f"echoed={out.get('echoed')}",
    )


# ---------------------------------------------------------------------------
# ReActAgent loop
# ---------------------------------------------------------------------------


async def test_react_terminates_on_final_answer(parser_bench_submodule_present):
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required")
    client = _ScriptedClient(['{"thought": "I know it.", "final_answer": "42"}'])
    agent = ReActAgent(backend_client=client, tools=[_stub_tool_spec()])
    result = await agent.run(_example(), images=[])
    assert result.answer == "42"
    assert len(client.calls) == 1
    # No tool calls, so iteration count stops at 1.
    assert result.telemetry["n_tool_calls"] == 0


async def test_react_dispatches_tool_then_finals(parser_bench_submodule_present):
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required")
    client = _ScriptedClient(
        [
            '{"thought": "let me check", "action": "stub_tool", "action_input": {"echo": "ping"}}',
            '{"thought": "ok", "final_answer": "42"}',
        ]
    )
    agent = ReActAgent(backend_client=client, tools=[_stub_tool_spec()])
    result = await agent.run(_example(), images=[])
    assert result.answer == "42"
    assert result.telemetry["n_tool_calls"] == 1
    # Conversation grew (turn 2 sees observation about the stub tool).
    assert "echoed=ping" in client.calls[1]["prompt"]


async def test_react_records_tool_error_for_unknown_tool(parser_bench_submodule_present):
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required")
    client = _ScriptedClient(
        [
            '{"thought": "?", "action": "nope", "action_input": {}}',
            '{"thought": "fallback", "final_answer": "42"}',
        ]
    )
    agent = ReActAgent(backend_client=client, tools=[_stub_tool_spec()])
    result = await agent.run(_example(), images=[])
    actions = [s.action for s in result.trace.steps]
    assert "tool_error" in actions
    assert result.answer == "42"


async def test_react_passes_images_only_on_first_turn(parser_bench_submodule_present, tmp_path):
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required")
    img = tmp_path / "p.png"
    img.write_bytes(b"fake")
    client = _ScriptedClient(
        [
            '{"thought": "?", "action": "stub_tool", "action_input": {}}',
            '{"thought": "done", "final_answer": "42"}',
        ]
    )
    agent = ReActAgent(backend_client=client, tools=[_stub_tool_spec()])
    await agent.run(_example(), images=[img])
    # First turn has the image; second turn has None.
    assert client.calls[0]["images"] == [img]
    assert client.calls[1]["images"] is None


async def test_react_loop_exhaustion_falls_back(parser_bench_submodule_present):
    """All iterations issue tool calls → loop exhausts; agent falls back to a
    last-text fallback or 'Unanswerable'."""
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required")
    # Always emit a tool call, never final_answer.
    client = _ScriptedClient(['{"thought": "again", "action": "stub_tool", "action_input": {}}'])
    agent = ReActAgent(backend_client=client, tools=[_stub_tool_spec()], max_iterations=2)
    result = await agent.run(_example(), images=[])
    # Loop exhausted. Fallback returns last agent text or "Unanswerable".
    assert result.answer
    assert result.telemetry["iterations_used"] >= 2


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def test_parse_react_turn_handles_fenced_json():
    text = '```json\n{"thought": "x", "final_answer": "42"}\n```'
    parsed = _parse_react_turn(text)
    assert parsed.is_final
    assert parsed.final_answer == "42"


def test_parse_react_turn_handles_bare_json():
    text = '   {"thought": "x", "final_answer": "42"}   '
    parsed = _parse_react_turn(text)
    assert parsed.is_final
    assert parsed.final_answer == "42"


def test_parse_react_turn_falls_back_to_prose():
    text = "I think the answer is 42."
    parsed = _parse_react_turn(text)
    assert parsed.is_final
    assert parsed.final_answer == "I think the answer is 42."


def test_parse_react_turn_extracts_action():
    text = '{"thought": "?", "action": "inspect_region", "action_input": {"page": 1}}'
    parsed = _parse_react_turn(text)
    assert not parsed.is_final
    assert parsed.action == "inspect_region"
    assert parsed.action_input == {"page": 1}


# ---------------------------------------------------------------------------
# AgentBaselineAgent — uses generic prompt
# ---------------------------------------------------------------------------


async def test_agent_baseline_uses_generic_prompt(parser_bench_submodule_present):
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required")
    client = _ScriptedClient(['{"final_answer": "42"}'])
    agent = AgentBaselineAgent(backend_client=client, tools=[_stub_tool_spec()])
    await agent.run(_example(), images=[])
    system = client.calls[0]["system"]
    assert "AI assistant" in system
    # The careful ReAct citation block is NOT in the generic prompt.
    assert "normalized [0,1]" not in system


async def test_react_uses_careful_prompt(parser_bench_submodule_present):
    if not parser_bench_submodule_present:
        pytest.skip("parser-bench submodule required")
    client = _ScriptedClient(['{"final_answer": "42"}'])
    agent = ReActAgent(backend_client=client, tools=[_stub_tool_spec()])
    await agent.run(_example(), images=[])
    system = client.calls[0]["system"]
    assert "document-parsing agent" in system
    assert "normalized [0,1]" in system


async def test_agent_baseline_default_iterations_is_tighter_than_react():
    """Sanity: comparator-row has a smaller iteration budget than ReAct row."""
    from focusparse.pipeline.agent_baseline import _DEFAULT_MAX_ITERATIONS as BASELINE_N
    from focusparse.pipeline.react_agent import _DEFAULT_MAX_ITERATIONS as REACT_N

    assert BASELINE_N < REACT_N
